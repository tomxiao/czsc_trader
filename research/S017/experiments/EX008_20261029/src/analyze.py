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
from run import ROOT, WORK, REPOSITORY, EXPERIMENT, context, read, save, material


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


COMPARISONS = (('C0031','C0030'), ('C0032','C0031'), ('C0031','C0029'), ('C0032','C0029'))
NEW_KEYS = ('C0031','C0032')


def verify_contracts(payloads):
    fields = ('initial_cash', 'fee_rate', 'window', 'history_start', 'data_manifest',
              'specification_hash', 'specification', 'benchmark_sha256', 'sources', 'instrument',
              'drawdown_basis', 'concentration_basis', 'frequency_window_days', 'measurement_tier')
    control = payloads['C0000']['request']
    checks, warmups = [], {}
    for key, payload in payloads.items():
        request = payload['request']
        for field in fields:
            equal = request[field] == control[field]
            checks.append({'candidate':key,'field':field,'equal':equal})
            if not equal:
                raise ValueError(f'economic/data contract differs: {key}/{field}')
        left, right = dict(request['input_binding']), dict(control['input_binding'])
        warmups[key] = left.pop('warmup_bars')
        right.pop('warmup_bars')
        if left != right:
            raise ValueError('actual input binding differs beyond declared warmup requirement')
        expected = 326 if key in NEW_KEYS else 261
        if warmups[key] != expected:
            raise ValueError('unexpected warmup declaration')
    precheck = read(WORK/'others/precheck.json')
    actual_warmup = precheck['cases']['prepared_input_and_actual_warmup']['actual_pre_evaluation_bars']
    if precheck['status'] != 'PASS' or actual_warmup < 326:
        raise ValueError('actual common prehistory does not satisfy both declared requirements')
    return {'status':'PASS','checks':checks,'declared_warmup_bars':warmups,
        'actual_warmup_observations':actual_warmup,
        'difference':'Only the minimum lookback requirement changes from 261 to 326; exact data identities, history start, first tradable interval and economic fields remain identical.'}


def main():
    hashes = {path: sha256(path.read_bytes()).hexdigest() for path in DEPENDENCIES}
    payloads, refs = PRIOR.load_subset(WORK, EXPERIMENT, NEW_KEYS, exact_manifest=True)
    for origin, keys in (('EX002_20261028', ('C0000',)), ('EX003_20261028', ('C0013',)),
                         ('EX005_20261028', ('C0029',)), ('EX007_20261029', ('C0030',))):
        experiment = ExperimentRef('S017', origin)
        p, r = PRIOR.load_subset(experiment.resolve(ROOT), experiment, keys)
        payloads.update(p)
        refs.update(r)
    print('ACCOUNTS_AUTHENTICATED', flush=True)
    contracts = verify_contracts(payloads)
    hold_path = PRIOR.PRIOR.verify_hold_path(payloads)
    summary = {key: PRIOR.PRIOR.summarize(payload) for key, payload in payloads.items()}
    diagnosis = {}
    research = context()
    for subject, control in COMPARISONS:
        key = subject+'_vs_'+control
        value = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            PRIOR.account_ref(refs[control], payloads[control]),
            PRIOR.account_ref(refs[subject], payloads[subject]),
            EvaluationWindow('DEV_2019_2025', date(2019,1,2), date(2025,12,31))))
        path = ROOT/'.tmp/s017-ex008-diagnostics'/(key+'.json')
        save(path, value.to_dict())
        reference = material(research, key, path)
        diagnosis[key] = {'status': value.status.value, 'issues': list(value.issues),
                          'evidence': reference.to_dict(), 'reconciliation': value.to_dict()['reconciliation']}
        print('DIAGNOSIS', key, value.status.value, flush=True)
    partitions = {subject+'_vs_'+control: DIAG.exposure_decomposition(
        payloads[subject]['runs']['candidate'],payloads[control]['runs']['candidate'],100000.)
        for subject,control in COMPARISONS}
    if any(sha256(path.read_bytes()).hexdigest() != digest for path, digest in hashes.items()):
        raise RuntimeError('retained helper changed during analysis')
    goals = {}
    for key in NEW_KEYS:
        metrics, benchmark = summary[key]['audited_metrics'], summary[key]['buy_hold_metrics']
        goals[key] = {'annualized':metrics['annualized_return'] >= 1.5*benchmark['annualized_return'],
            'drawdown':metrics['bar_max_drawdown'] <= min(.25,.8*benchmark['bar_max_drawdown']),
            'frequency_median':metrics['rolling_60_closed_cycle_median'] >= 6,
            'frequency_coverage':summary[key]['frequency_60_sessions']['coverage_at_least_three'] >= .9}
    okay = contracts['status'] == hold_path['status'] == 'PASS' and all(
        item['status'] == 'COMPUTED' for item in diagnosis.values())
    output = {'status': 'PASS' if okay else 'FAIL', 'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_accounts': {key: ref.to_dict() for key, ref in refs.items()},
        'dependencies': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest} for path,digest in hashes.items()],
        'contract_checks': contracts, 'paired_buyhold_check': hold_path, 'summaries': summary,
        'diagnostics': diagnosis, 'exposure_partitions': partitions,
        'new_entry_groups': {key: recovery_entries(payloads[key]['runs']['candidate']) for key in NEW_KEYS},
        'order_reasons': {key: dict(Counter(row['reason'] for row in payloads[key]['runs']['candidate']['orders'])) for key in NEW_KEYS},
        'goals': goals, 'all_goals_met': {key:all(value.values()) for key,value in goals.items()}, 'new_configurations': 2,
        'formal_requests': 2, 'account_replays': 4, 'public_diagnoses': 4,
        'engine_identity_note': 'Same platform feedback version; new strategy sources and declared lookback are separately bound. Actual input and economic paths of paired buyhold are compared; old evidence remains immutable.',
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
