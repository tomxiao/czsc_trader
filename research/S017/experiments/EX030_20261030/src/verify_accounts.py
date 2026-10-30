"""Independently reconcile new V3 accounts and the reused EX029 parent."""
from hashlib import sha256
from math import fsum, isclose
from pathlib import Path
from statistics import median

from common import ROOT, WORK, EXPERIMENT, read, save, digest
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.equity_replay_v3 import materialize_v3


def close(a, b):
    if a is None or b is None:
        assert a is b
    else:
        assert isclose(a, b, rel_tol=1e-10, abs_tol=1e-10), (a, b)


def diagnostic_source(value):
    """AccountDiagnosisResult.to_dict emits known dataclasses without tags.

    Explicitly restore those two schema tags, then use the public strong type;
    all business identity fields and the exact source order remain mandatory.
    """
    assert set(value) == {'experiment', 'evidence_id', 'sha256', 'media_type',
                          'name', 'schema', 'schema_version'}
    assert set(value['experiment']) == {'strategy_id', 'experiment_id'}
    return EvidenceRef.from_dict({'type': 'EvidenceRef', **value,
        'experiment': {'type': 'ExperimentRef', **value['experiment']}})


def main():
    analysis = read(WORK/'others/account_analysis.json')
    if analysis['status'] == 'NOT_RUN':
        assert read(WORK/'others/accounts.json') == {}
        save(WORK/'others/account_result_validation.json', {'status': 'NOT_RUN', 'reason': 'No formal accounts'})
        return
    assert analysis['status'] == 'PASS'
    assert analysis['analysis_source_sha256'] == digest(WORK/'src/analyze_accounts.py')
    new_manifest = read(WORK/'others/accounts.json')
    assert analysis['account_manifest_sha256'] == digest(WORK/'others/accounts.json')
    parent_path = WORK.parent/'EX029_20261030/others/accounts_v3.json'
    assert analysis['parent_account_manifest_sha256'] == digest(parent_path)
    manifest = {'C0056': read(parent_path)['C0056'], **new_manifest}
    all_expected = {'C0056': ('S017-M017', 6), 'C0059': ('S017-M019', 6), 'C0060': ('S017-M020', 6)}
    selected = read(WORK/'others/selection.json')['selected_mechanisms']
    assert set(new_manifest) == {key for key, value in all_expected.items() if key != 'C0056' and value[0] in selected}
    expected = {key: value for key, value in all_expected.items() if key in manifest}
    assert set(manifest) == set(expected) == set(analysis['summaries'])
    assert analysis['new_strategy_accounts'] == len(new_manifest)
    assert analysis['reused_parent_strategy_accounts'] == 1
    cache = {}
    for key, record in manifest.items():
        ref = EvidenceRef.from_dict(record['evidence'])
        assert ref.experiment == (ExperimentRef('S017', 'EX029_20261030') if key == 'C0056' else EXPERIMENT)
        assert (ref.schema, ref.schema_version) == ('equity_research', 3)
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        result = EquityEvaluationResult(record['request_hash'], raw)
        envelope = result.payload
        allowed = {(envelope[n]['kind'], envelope[n]['sha256'])
                   for n in ('input_ref', 'candidate_ref', 'benchmark_ref')}
        directory = ref.resolve(ROOT).parent

        def resolve(artifact):
            assert set(artifact) == {'kind', 'sha256'}
            assert (artifact['kind'], artifact['sha256']) in allowed
            target = directory/(artifact['sha256']+'.json')
            if target not in cache:
                cache[target] = target.read_bytes()
            return cache[target]

        payload = materialize_v3(result, resolve).payload
        assert payload['schema'] == 'equity-research/v3' and payload['schema_version'] == 3
        assert payload['request']['candidate_definition']['contract_version'] == 3
        reported = analysis['summaries'][key]
        assert reported['parameters'] == {'entry_mechanism': expected[key][0], 'max_holding_bars': expected[key][1]}
        for kind, label in (('candidate', 'candidate'), ('buy_hold', 'benchmark')):
            run, summary = payload['runs'][kind], reported[label]
            m = run['metrics']
            for field in ('total_return', 'annualized_return', 'bar_max_drawdown', 'daily_max_drawdown',
                          'closed_cycles', 'rolling_60_closed_cycle_median', 'fees'):
                close(summary[field], m[field])
            assert summary['audited_metrics'] == m
            counts = m['rolling_60_closed_cycle_counts']
            assert len(counts) == summary['frequency_60_sessions']['complete_windows']
            close(summary['frequency_60_sessions']['coverage_at_least_three'], sum(x >= 3 for x in counts)/len(counts))
            assert summary['trade_pnl']['closed_count'] == len(run['trades']) == m['closed_cycles']
            close(summary['trade_pnl']['net_pnl'], fsum(t['net_pnl'] for t in run['trades']))
            returns = [t['net_return'] for t in run['trades']]
            close(summary['trade_pnl']['mean_cycle_net_return'], fsum(returns)/len(returns) if returns else None)
            close(summary['trade_pnl']['median_cycle_net_return'], median(returns) if returns else None)
            points = run['account_points']
            close(summary['holding_bar_fraction'], sum(x['quantity'] > 0 for x in points)/len(points))
            close(summary['ending_equity'], points[-1]['equity'])
            opening = payload['request']['initial_cash']
            for item in summary['year_returns']:
                population = [p for p in run['account_daily'] if p['session'].startswith(str(item['year']))]
                assert len(population) == item['sessions']
                close(item['opening_equity'], opening)
                close(item['closing_equity'], population[-1]['equity'])
                close(item['net_return'], population[-1]['equity']/opening-1.)
                opening = population[-1]['equity']
        own, base = reported['candidate'], reported['benchmark']
        gates = {'annualized_return': own['annualized_return'] >= base['annualized_return']*1.5 if base['annualized_return'] > 0 else own['annualized_return'] > 0,
            'relative_drawdown': own['bar_max_drawdown'] <= .8*base['bar_max_drawdown'],
            'absolute_drawdown': own['bar_max_drawdown'] <= .25,
            'frequency_median': own['rolling_60_closed_cycle_median'] >= 6,
            'frequency_coverage': own['frequency_60_sessions']['coverage_at_least_three'] >= .9}
        assert gates == reported['goals'] and all(gates.values()) == reported['all_goals_met']
    for name, result in analysis['diagnostics'].items():
        ref = EvidenceRef.from_dict(result['evidence'])
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        import json
        diagnosis = json.loads(raw)
        assert diagnosis['status'] == result['status'] == 'COMPUTED'
        assert diagnosis['issues'] == [] and result['sources_match']
        subject, control = name.split('_vs_')
        assert tuple(diagnostic_source(v) for v in diagnosis['sources']) == (
            EvidenceRef.from_dict(manifest[control]['evidence']),
            EvidenceRef.from_dict(manifest[subject]['evidence']))
        assert all(abs(x['residual']) <= 1e-7 for x in diagnosis['reconciliation'])
    save(WORK/'others/account_result_validation.json', {'status': 'PASS',
        'scope': 'INDEPENDENT_REPORT_NUMBERS_AND_PUBLIC_DIAGNOSTIC_REFERENCE_CHECK',
        'analysis_sha256': digest(WORK/'others/account_analysis.json'),
        'verification_source_sha256': digest(Path(__file__)), 'accounts': list(expected),
        'checks': ['immutable_source_identity', 'public_metrics', 'fee_amounts', 'trade_counts_and_net_pnl',
            'annual_continuous_equity', 'holding_fraction', 'original_five_goals', 'public_diagnosis_exact_sources_and_reconciliation']})
    print('ACCOUNT_RESULT_VALIDATION_PASS', flush=True)


if __name__ == '__main__':
    main()
