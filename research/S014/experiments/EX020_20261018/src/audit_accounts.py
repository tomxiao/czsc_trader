"""Offline ledger and independent deadline audit of eight signal-renewal accounts."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np
import pandas as pd
import requests
from czsc_trader.research_tools import EvidenceRef
from strategy_runtime import implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / 'research/S014/experiments/EX017_20261017'
PREVIOUS = ROOT / 'research/S014/experiments/EX018_20261017'
COORDINATES = {f'renewal_{kind}_H{h}_cap{cap}': (h, kind, cap)
               for h in (3, 6) for kind in ('qualified', 'parent') for cap in (12, 0)}
EXPECTED = {variant: f'S014-C{number:04}' for number, variant in enumerate(COORDINATES, 25)}

REUSED = {'baseline_H3': ('EX017_20261017', 'high_H3', 'S014-C0011'),
          'baseline_H6': ('EX018_20261017', 'parent_high_H6', 'S014-C0016')}
SUMMARY = EX / 'others/account_audit.json'
FULL = ROOT / 'research/S014/assets/runs/EX020_20261018/account_audit_full.json'



def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_result(result):
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX020 account audit evidence')
    FULL.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    FULL.write_bytes(content)
    summary = {k: v for k, v in result.items() if k != 'checks'}
    summary['accounts'] = [{k: v for k, v in account.items() if k != 'renewal_event_records'}
                           for account in result['accounts']]
    summary['full_audit'] = {'path': FULL.relative_to(ROOT).as_posix(),
                           'sha256': sha256(content).hexdigest(), 'bytes': len(content)}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                       encoding='utf-8', newline='\n')




def audit_renewal(variant, tables, shadow, prior, require):
    """Rebuild deadlines from real fill cycles and independently latched exit intent."""
    horizon, kind, cap = COORDINATES[variant]
    daily = prior.by_date(tables['account_daily'], 'date').sort_values('date').reset_index(drop=True)
    fills = prior.by_date(tables['fills'], 'fill_time')
    episode = None
    entries = exits = applied_count = signal_count = cap_count = locked_signal_count = 0
    event_records = []
    for row in daily.itertuples():
        day = row.date
        i = int(shadow.index.get_loc(day))
        label = f'{variant} {day.date()} independent renewal'
        today = shadow.loc[day]
        same = fills.loc[fills.fill_time.eq(day)]
        buys, sells = same.loc[same.side.eq('BUY')], same.loc[same.side.eq('SELL')]
        require(label + ' no same-session round trip', not (len(buys) and len(sells)))
        if episode is not None:
            require(label + ' actual target uses previously latched exit intent',
                    float(row.target_position) == float(not episode['exit_pending']))
        if len(sells):
            require(label + ' actual full exit follows existing deadline and SELL intent',
                    episode is not None and episode['exit_pending'] and i > episode['deadline']
                    and int(sells.quantity.sum()) == episode['quantity'])
            exits += 1
            episode = None
        if len(buys):
            require(label + ' actual buy starts one new cycle', episode is None)
            episode = {'entry_index': i, 'entry_date': str(day.date()),
                       'quantity': int(buys.quantity.sum()), 'deadline': i + horizon - 1,
                       'exit_pending': False}
            entries += 1
        if episode is None:
            require(label + ' flat has no residual renewal state',
                    int(row.quantity) == 0 and int(today.deadline_index) == -1
                    and not bool(today.exit_pending) and not bool(today.renewal_signal)
                    and not bool(today.renewal_applied) and not bool(today.cap_hit))
            continue
        previous_deadline = episode['deadline']
        was_pending = episode['exit_pending']
        signal = bool(today.parent and today.ready and (kind == 'parent' or today.high))
        applied = hit_cap = False
        proposed = previous_deadline
        if signal and not was_pending:
            proposed = max(previous_deadline, i + horizon)
            if cap:
                ceiling = episode['entry_index'] + cap - 1
                hit_cap = proposed > ceiling
                proposed = min(proposed, ceiling)
            applied = proposed > previous_deadline
            episode['deadline'] = proposed
        if i >= episode['deadline']:
            episode['exit_pending'] = True
        require(label + ' eligible signal uses only known original condition', bool(today.renewal_signal) == signal)
        require(label + ' exact independent deadline and strict extension event',
                int(today.deadline_index) == episode['deadline'] and bool(today.renewal_applied) == applied)
        require(label + ' cap clamps from original real entry without resetting clock', bool(today.cap_hit) == hit_cap)
        require(label + ' frozen exit latch and next-session target agree',
                bool(today.exit_pending) == episode['exit_pending']
                and float(today.target_position) == float(not episode['exit_pending']))
        require(label + ' continuation never changes actual share count or base horizon',
                int(row.quantity) == episode['quantity'] and int(today.holding_horizon) == horizon)
        require(label + ' deadline cannot move backwards or exceed fixed cap',
                episode['deadline'] >= previous_deadline
                and (cap == 0 or episode['deadline'] <= episode['entry_index'] + cap - 1))
        if was_pending:
            require(label + ' failed sale cannot be withdrawn by new signal',
                    episode['exit_pending'] and not applied and not hit_cap
                    and episode['deadline'] == previous_deadline and float(today.target_position) == 0.)
        signal_count += int(signal)
        applied_count += int(applied)
        cap_count += int(hit_cap)
        locked_signal_count += int(signal and was_pending)
        if signal or (episode['exit_pending'] and not was_pending):
            event_records.append({'date': str(day.date()), 'history_index': i,
                                  'entry_date': episode['entry_date'], 'entry_index': episode['entry_index'],
                                  'quantity': episode['quantity'], 'previous_deadline': previous_deadline,
                                  'deadline': episode['deadline'], 'renewal_signal': signal,
                                  'renewal_applied': applied, 'cap_hit': hit_cap,
                                  'previous_exit_pending': was_pending,
                                  'exit_pending': episode['exit_pending']})
    require(variant + ' all actual cycles accounted for without virtual round trips',
            entries - exits == int(episode is not None))
    return {'actual_entry_cycles': entries, 'renewal_signals': signal_count,
            'renewal_applications': applied_count, 'cap_hit_events': cap_count,
            'renewal_signals_ignored_after_exit_latch': locked_signal_count,
            'renewal_event_records': event_records,
            'observation_scope': 'Authenticated runtime state reconciled against actual fill cycles, unchanged original environment, and an independently rebuilt deadline and SELL latch; no post-cutoff execution.'}


def main():
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX020 account audit evidence')
    checks, accounts, refs = [], [], []
    external_attempts = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def prohibited(*args, **kwargs):
        external_attempts.append('blocked')
        raise RuntimeError('No external call permitted during EX020 account audit')

    def verified_record(record):
        require(record['variant'] + ' succeeded', record['status'] == 'SUCCEEDED')
        ref = EvidenceRef.from_dict(record['evidence'])
        content = ref.resolve(ROOT).read_bytes()
        require(record['variant'] + ' formal evidence bytes', sha256(content).hexdigest() == ref.sha256)
        payload = json.loads(content)
        require(record['variant'] + ' formal result hash and single run',
                payload['result_hash'] == record['result_hash'] and len(payload['runs']) == 1)
        run = payload['runs'][0]
        require(record['variant'] + ' candidate and full baseline coordinate',
                record['candidate'] == 'S014-' + run['candidate_id']
                and (run['window_id'], run['scenario_id']) == ('full', 'baseline'))
        refs.append(ref.to_dict())
        return run

    original_request = requests.sessions.Session.request
    requests.sessions.Session.request = prohibited
    original_path = list(sys.path)
    try:
        # Reuse the authenticated EX017 prepared input and independent ledger checks.
        sys.path.insert(0, str(OLD / 'src'))
        prior_audit_path = OLD / 'src/audit_accounts.py'
        prior = module('s014_ex020_predecessor_account_audit', prior_audit_path)
        data = prior.load_frames()
        records = read(EX / 'others/account_results.json')['records']
        comparison = read(EX / 'others/comparison_accounts.json')['records']
        previous = read(OLD / 'others/account_results.json')['records']
        require('exactly eight unique authorized new accounts',
                len(records) == len(EXPECTED) and {r['variant'] for r in records} == set(EXPECTED))
        require('comparison contains eight new rules and two exact baselines',
                len(comparison) == 10 and {r['variant'] for r in comparison} == set(EXPECTED) | set(REUSED))
        combined = {r['variant']: r for r in comparison}
        previous = {r['variant']: r for r in previous}
        ex018 = {r['variant']: r for r in read(PREVIOUS / 'others/account_results.json')['records']}
        source_path = EX / 'src/strategy_runtime/strategies/repair.py'
        sample_path = source_path.with_name('calibration_samples.csv')
        source_hash = sha256(source_path.read_bytes()).hexdigest()
        sample_hash = sha256(sample_path.read_bytes()).hexdigest()
        precheck = read(EX / 'others/precheck.json')
        require('causal precheck binds actual source and calibration',
                precheck['status'] == 'PASS' and precheck['source_sha256'] == source_hash
                and precheck['calibration_sha256'] == sample_hash)
        require('calibration identical to original fixed baseline',
                sample_path.read_bytes() == (OLD / 'src/strategy_runtime/strategies/calibration_samples.csv').read_bytes())
        require('predecessor account audit passed', read(OLD / 'others/account_audit.json')['status'] == 'PASS')
        require('EX018 predecessor account audit passed', read(PREVIOUS / 'others/account_audit_v2.json')['status'] == 'PASS')
        strategy = module('s014_ex020_account_audit_repair', source_path)
        market, raw, limits, status = [data[k] for k in (
            'stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
        samples = pd.read_csv(sample_path)
        indexed = [x.set_index(pd.to_datetime(x.Date)).sort_index() for x in (market, raw, limits)]
        old_strategy = module('s014_ex020_prior_environment', PREVIOUS / 'src/strategy_runtime/strategies/repair.py')
        old_environment = old_strategy.history(market, raw, limits, status, samples, 'parent_high_H3')
        old_high = verified_record(previous['high_H3'])
        require('original high H3 has complete buyhold execution',
                old_high['buyhold'] is not None and old_high['buyhold']['execution'] is not None)
        benchmark = json.dumps(old_high['buyhold'], sort_keys=True, separators=(',', ':'))
        for variant, (batch, old_name, candidate) in REUSED.items():
            left = combined[variant]
            right = (previous if batch == OLD.name else ex018)[old_name]
            require(variant + ' fixed baseline candidate', left['candidate'] == candidate)
            require(variant + ' reuses exact original candidate result and evidence',
                    all(left[k] == right[k] for k in ('candidate', 'result_hash', 'evidence', 'status')))
            reused_run = verified_record(left)
            require(variant + ' unchanged complete buyhold evidence',
                    json.dumps(reused_run['buyhold'], sort_keys=True, separators=(',', ':')) == benchmark)
        for record in records:
            variant = record['variant']
            require(variant + ' authorized candidate identity', record['candidate'] == EXPECTED[variant])
            require(variant + ' comparison references same new result',
                    all(combined[variant][k] == record[k] for k in ('candidate', 'result_hash', 'evidence', 'status')))
            payload = read(EX / f'protocols/payload_{variant}.json')
            runtime = payload['runtime']
            require(variant + ' fixed parameter and authenticated runtime closure',
                    payload['parameters'] == {'variant': variant}
                    and implementation_sha256(tuple(runtime['source_files']),
                        source_root=EX / 'src/strategy_runtime') == runtime['source_sha256'])
            run = verified_record(record)
            ledgers = {name: prior.frame(table) for name, table in run['ledgers'].items()}
            shadow = strategy.history(market, raw, limits, status, samples, variant)
            instance = strategy.RepairStrategy.from_parameters(strategy.ParameterSet({'variant': variant}))
            visible = instance.calculate_history({'market': market, 'raw': raw, 'limits': limits,
                                                   'status': status}, shadow.index)
            pd.testing.assert_frame_equal(visible, shadow, check_dtype=False)
            require(variant + ' public history preserves all economic values', True)
            common = ['parent', 'ready', 'high', 'threshold', 'gap_autocorr']
            pd.testing.assert_frame_equal(shadow[common], old_environment[common], check_exact=True)
            require(variant + ' unchanged causal entry environment', True)
            report = prior.audit_ledger(variant, ledgers, *indexed, strategy, require, shadow)
            conditional = audit_renewal(variant, ledgers, shadow, prior, require)
            accounts.append({'variant': variant, 'candidate': record['candidate'], **report, **conditional})
            require(variant + ' full buyhold exactly equals original high H3 benchmark',
                    run['buyhold'] is not None
                    and json.dumps(run['buyhold'], sort_keys=True, separators=(',', ':')) == benchmark)
        bh_tables = {name: prior.frame(table) for name, table in old_high['buyhold']['execution'].items()}
        bh_report = prior.audit_ledger('buyhold', bh_tables, *indexed, strategy, require)
        bh_fills = bh_tables['fills']
        require('buyhold first purchase original first session and never sold',
                len(bh_fills) == 1 and bh_fills.side.eq('BUY').all()
                and pd.Timestamp(bh_fills.fill_time.iloc[0]).date().isoformat() == '2020-01-02')
        accounts.append({'variant': 'buyhold', **bh_report})
        require('no attempted external calls', not external_attempts)
        result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks,
                  'accounts': accounts, 'new_accounts_audited': len(EXPECTED), 'reused_accounts': REUSED,
                  'formal_evidence': refs, 'source_sha256': source_hash, 'calibration_sha256': sample_hash,
                  'predecessor_audit_source_sha256': sha256(prior_audit_path.read_bytes()).hexdigest(),
                  'audit_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
                  'method_review_sha256': sha256((EX / 'others/method_review.json').read_bytes()).hexdigest(),
                  'full_input_reference': prior.FULL_INPUT_REFERENCE,
                  'external_calls': 0, 'external_attempts': len(external_attempts), 'new_account_runs': 0}
    except Exception as exc:
        result = {'status': 'FAIL', 'check_count': len(checks), 'checks': checks,
                  'accounts': accounts, 'formal_evidence': refs,
                  'error': type(exc).__name__ + ': ' + str(exc), 'traceback': traceback.format_exc(),
                  'external_calls': 0, 'external_attempts': len(external_attempts), 'new_account_runs': 0}
        write_result(result)
        raise
    finally:
        requests.sessions.Session.request = original_request
        sys.path[:] = original_path
    write_result(result)
    print('EX020_ACCOUNT_AUDIT_PASS', len(checks))


if __name__ == '__main__':
    main()
