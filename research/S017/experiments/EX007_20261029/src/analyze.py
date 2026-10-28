"""Authenticate old/new accounts and locate the incremental recovery outcome."""
from collections import Counter
from datetime import date
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import ExperimentRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest
from czsc_trader.research_tools.evaluation import EvaluationWindow
from run import ROOT, WORK, REPOSITORY, EXPERIMENT, context, save, material


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DIAG = load('_s017_ex006_for_reentry', ROOT/'research/S017/experiments/EX006_20261028/src/diagnose.py')
PRIOR = DIAG.PRIOR
DEPENDENCIES = tuple(dict.fromkeys((Path(DIAG.__file__), *DIAG.DEPENDENCIES)))


def recovery_entries(run):
    decisions = {row['decision_id']: row for row in run['decisions']}
    trades = {row['cycle_id']: row for row in run['trades']}
    groups = {}
    for fill in run['fills']:
        if fill['side'] != 'BUY':
            continue
        decision = decisions[fill['order_id']]
        facts = {item['key']: item['text'] for item in decision['explanation']['basis']}
        recovered, breakout = facts['recovery_entry'] == 'True', facts['breakout_entry'] == 'True'
        if not (recovered or breakout):
            raise ValueError('entry is not explained by either declared condition')
        group = 'BOTH' if recovered and breakout else 'RECOVERY_ONLY' if recovered else 'BREAKOUT_ONLY'
        trade = trades.get(fill['cycle_id'])
        groups.setdefault(group, []).append({'cycle_id': fill['cycle_id'], 'entry_at': fill['interval_start'],
            'closed': trade is not None, 'net_pnl': None if trade is None else trade['net_pnl']})
    return {key: {'entries': len(rows), 'closed': sum(row['closed'] for row in rows),
                  'closed_net_pnl': sum(row['net_pnl'] for row in rows if row['closed']),
                  'losing_closed': sum(row['closed'] and row['net_pnl'] < 0 for row in rows),
                  'cycles': rows} for key, rows in groups.items()}


def main():
    hashes = {path: sha256(path.read_bytes()).hexdigest() for path in DEPENDENCIES}
    payloads, refs = PRIOR.load_subset(WORK, EXPERIMENT, ('C0030',), exact_manifest=True)
    for origin, keys in (('EX002_20261028', ('C0000',)), ('EX003_20261028', ('C0013',)),
                         ('EX005_20261028', ('C0029',))):
        experiment = ExperimentRef('S017', origin)
        p, r = PRIOR.load_subset(experiment.resolve(ROOT), experiment, keys)
        payloads.update(p)
        refs.update(r)
    print('ACCOUNTS_AUTHENTICATED', flush=True)
    contracts = PRIOR.verify_contracts(payloads)
    hold_path = PRIOR.PRIOR.verify_hold_path(payloads)
    summary = {key: PRIOR.PRIOR.summarize(payload) for key, payload in payloads.items()}
    diagnosis = {}
    research = context()
    for control in ('C0029', 'C0000'):
        key = 'C0030_vs_'+control
        value = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            PRIOR.account_ref(refs[control], payloads[control]),
            PRIOR.account_ref(refs['C0030'], payloads['C0030']),
            EvaluationWindow('DEV_2019_2025', date(2019,1,2), date(2025,12,31))))
        path = WORK/'others'/(key+'.json')
        save(path, value.to_dict())
        reference = material(research, key, path)
        diagnosis[key] = {'status': value.status.value, 'issues': list(value.issues),
                          'evidence': reference.to_dict(), 'reconciliation': value.to_dict()['reconciliation']}
        print('DIAGNOSIS', key, value.status.value, flush=True)
    partitions = {control: DIAG.exposure_decomposition(payloads['C0030']['runs']['candidate'],
        payloads[control]['runs']['candidate'], 100000.) for control in ('C0029', 'C0000')}
    if any(sha256(path.read_bytes()).hexdigest() != digest for path, digest in hashes.items()):
        raise RuntimeError('retained helper changed during analysis')
    metrics = summary['C0030']['audited_metrics']
    benchmark = summary['C0030']['buy_hold_metrics']
    goals = {'annualized': metrics['annualized_return'] >= 1.5*benchmark['annualized_return'],
             'drawdown': metrics['bar_max_drawdown'] <= min(.25, .8*benchmark['bar_max_drawdown']),
             'frequency_median': metrics['rolling_60_closed_cycle_median'] >= 6,
             'frequency_coverage': summary['C0030']['frequency_60_sessions']['coverage_at_least_three'] >= .9}
    okay = contracts['status'] == hold_path['status'] == 'PASS' and all(
        item['status'] == 'COMPUTED' for item in diagnosis.values())
    output = {'status': 'PASS' if okay else 'FAIL', 'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_accounts': {key: ref.to_dict() for key, ref in refs.items()},
        'dependencies': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest} for path,digest in hashes.items()],
        'contract_checks': contracts, 'paired_buyhold_check': hold_path, 'summaries': summary,
        'diagnostics': diagnosis, 'exposure_partitions': partitions,
        'new_entry_groups': recovery_entries(payloads['C0030']['runs']['candidate']),
        'order_reasons': dict(Counter(row['reason'] for row in payloads['C0030']['runs']['candidate']['orders'])),
        'goals': goals, 'all_goals_met': all(goals.values()), 'new_configurations': 1,
        'formal_requests': 1, 'account_replays': 2, 'public_diagnoses': 2,
        'engine_identity_note': 'New feedback mode and implementation source identities are bound separately; economic/data fields and paired buyhold paths are compared; old evidence is immutable.',
        'limitations': ['Same repeatedly seen development sample; not independent validation.',
                       'Entry-group PnL is descriptive: removing entries would change later capital and opportunities.',
                       'Holdout, robustness, stage three and frozen strategy admission were not performed.']}
    save(WORK/'others/analysis.json', output)
    print({key: {name: value['audited_metrics'][name] for name in
           ('annualized_return','bar_max_drawdown','closed_cycles')} for key,value in summary.items()}, flush=True)
    if not okay:
        raise RuntimeError('formal comparison has incomplete technical checks')


if __name__ == '__main__':
    main()
