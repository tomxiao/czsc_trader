"""Independent result consistency checks; no account replay or parameter change."""
from hashlib import sha256
from dataclasses import asdict
import math
from czsc_trader.research_tools import EvidenceRef
from run import ROOT, WORK, read, save, digest, configurations

def authenticated(value):
    ref = EvidenceRef.from_dict(value)
    raw = ref.resolve(ROOT).read_bytes()
    if sha256(raw).hexdigest() != ref.sha256:
        raise ValueError('Published evidence changed')
    return read(ref.resolve(ROOT))

def main():
    result = read(WORK/'others/analysis.json')
    manifests = read(WORK/'others/accounts.json')
    if (result['status'] != 'PASS' or result['analysis_source_path'] != 'src/analyze_v2.py'
            or result['analysis_source_sha256'] != digest(WORK/'src/analyze_v2.py')
            or set(result['summaries']) != set(configurations()) or set(manifests) != set(configurations())):
        raise ValueError('Analysis/source/declared population mismatch')
    pre = read(WORK/'others/pre_run_evidence.json')
    revision = read(WORK/'others/analysis_revision.json')
    if (revision['original_source_sha256'] != digest(WORK/'src/analyze.py')
            or revision['revised_source_sha256'] != digest(WORK/'src/analyze_v2.py')
            or revision['account_manifest_sha256'] != digest(WORK/'others/accounts.json')
            or revision['account_replays_added'] != 0 or revision['experiment_rounds_added'] != 0):
        raise ValueError('Analysis-only format revision is not bound to unchanged accounts')
    for name in ('strategy', 'run', 'precheck', 'check_mechanism', 'analyze'):
        ref = EvidenceRef.from_dict(pre[name+'-source'])
        if digest(ref.resolve(ROOT)) != digest(WORK/f'src/{name}.py'):
            raise ValueError('Frozen source changed: '+name)
    payloads, checks = {}, []
    for key, record in manifests.items():
        if record['evidence'] != result['source_accounts'][key]:
            raise ValueError('Summary account is not the published account')
        payload = authenticated(record['evidence'])
        payloads[key] = payload
        for side, label in (('candidate', 'candidate'), ('buy_hold', 'benchmark')):
            run = payload['runs'][side]
            summary = result['summaries'][key][label]
            if summary['audited_metrics'] != run['metrics']:
                raise ValueError('Summary differs from independent public account metrics')
            initial, final = payload['request']['initial_cash'], run['account_points'][-1]['equity']
            if not math.isclose(summary['total_return'], final/initial-1, abs_tol=1e-12):
                raise ValueError('Final equity does not reconcile to total return')
            compounded = math.prod(1+row['net_return'] for row in summary['year_returns'])
            if not math.isclose(compounded, final/initial, abs_tol=1e-12):
                raise ValueError('Continuous year returns do not compound to final equity')
            freq = run['metrics']['rolling_60_closed_cycle_counts']
            if len(freq) != len(run['account_daily'])-59:
                raise ValueError('Frequency does not cover every complete 60-session window')
            if summary['closed_cycles'] != len(run['trades']):
                raise ValueError('Closed frequency includes nonclosed positions')
            if not math.isclose(summary['holding_bar_fraction'],
                    sum(p['quantity']>0 for p in run['account_points'])/len(run['account_points']), abs_tol=1e-12):
                raise ValueError('Holding exposure summary differs from actual account')
        item = result['summaries'][key]
        candidate, benchmark = item['candidate'], item['benchmark']
        expected = {
            'annualized_return': candidate['annualized_return'] >= 1.5*benchmark['annualized_return']
                if benchmark['annualized_return']>0 else candidate['annualized_return']>0,
            'relative_drawdown': candidate['bar_max_drawdown'] <= .8*benchmark['bar_max_drawdown'],
            'absolute_drawdown': candidate['bar_max_drawdown'] <= .25,
            'frequency_median': candidate['rolling_60_closed_cycle_median'] >= 6,
            'frequency_coverage': candidate['frequency_60_sessions']['coverage_at_least_three'] >= .9,
        }
        if item['goals'] != expected or item['all_goals_met'] != all(expected.values()):
            raise ValueError('Confirmed simultaneous goals were misclassified')
        counts = item['mechanism']['counts']
        if counts['entry_signals'] != 324 or counts['decisions'] != 22790 or counts['not_ready']:
            raise ValueError('Full account signal population changed')
        if counts['actual_buy_fills'] != len(payload['runs']['candidate']['trades']) + int(candidate['ending_quantity']>0):
            raise ValueError('Actual entries do not reconcile with closed and open cycles')
        checks.append({'candidate': key, 'status': 'PASS', 'all_goals_met': all(expected.values())})
    if set(result['diagnostics']) != {'C0049_vs_C0048', 'C0050_vs_C0048'}:
        raise ValueError('Required direct comparisons missing')
    for name, item in result['diagnostics'].items():
        diagnosis = authenticated(item['evidence'])
        subject, control = name.split('_vs_')
        if (diagnosis['status'] != 'COMPUTED' or diagnosis['issues']
                or diagnosis['sources'] != [asdict(EvidenceRef.from_dict(manifests[k]['evidence'])) for k in (control, subject)]
                or diagnosis['reconciliation'] != item['reconciliation']
                or any(abs(row['residual'])>1e-7 for row in diagnosis['reconciliation'])):
            raise ValueError('Public money diagnosis is incomplete or mismatched')
    output = {'status': 'PASS', 'analysis_sha256': digest(WORK/'others/analysis.json'),
        'verification_source_sha256': digest(WORK/'src/verify.py'), 'checks': checks,
        'public_comparisons': 2, 'real_account_replays': 0, 'reserved_2026_used': False,
        'scope': 'Frozen sources, published account and diagnosis identities, equity/year/frequency/holding reconciliation, simultaneous user goals; not new economic simulation or independent market validation.'}
    save(WORK/'others/result_validation.json', output)
    print('RESULT_VALIDATION_PASS', flush=True)

if __name__ == '__main__':
    main()
