"""Offline ledger and initial-delay audit of twenty fixed support timing controls."""
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
PREVIOUS = ROOT / 'research/S014/experiments/EX021_20261018'
EXPECTED = {f'{base}_delay{delay}': f'S014-C{36 + group * 10 + delay - 1:04}'
            for group, base in enumerate(('repeated_H10', 'support_entry_H10')) for delay in range(1, 11)}
REUSED = {'repeated_H10_delay0': ('EX021_20261018', 'repeated_H10', 'S014-C0033'),
          'support_entry_H10_delay0': ('EX021_20261018', 'support_entry_H10', 'S014-C0034')}

SUMMARY = EX / 'others/account_audit.json'
FULL = ROOT / 'research/S014/assets/runs/EX022_20261018/account_audit_full.json'



def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_result(result):
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX022 account audit evidence')
    FULL.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    FULL.write_bytes(content)
    summary = {k: v for k, v in result.items() if k != 'checks'}
    summary['accounts'] = [{k: v for k, v in account.items() if k != 'support_event_records'}
                           for account in result['accounts']]
    summary['full_audit'] = {'path': FULL.relative_to(ROOT).as_posix(),
                           'sha256': sha256(content).hexdigest(), 'bytes': len(content)}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                       encoding='utf-8', newline='\n')






def audit_support(variant, tables, shadow, anchor, prior, require):
    """Rebuild support from completed account closes and decisions from real fill cycles."""
    base, delay_text = variant.rsplit('_delay', 1)
    delay = int(delay_text)
    daily = prior.by_date(tables['account_daily'], 'date').sort_values('date').reset_index(drop=True)
    fills = prior.by_date(tables['fills'], 'fill_time')
    prewindow = shadow.loc[shadow.index < daily.date.iloc[0]]
    require(variant + ' execution prewindow excluded from warmup and support',
            prewindow.warmup_sessions.eq(0).all() and prewindow.support_floor.isna().all()
            and not prewindow.ready.any() and not prewindow.entry_signal.any()
            and prewindow.target_position.eq(0).all())
    episode = None
    previous_target = 0.
    previous_entry_signal = False
    completed_closes = []
    events = []
    entries = exits = breaks = failed_buys = 0
    first_ready = None
    first_actual_entry = None
    for count, row in enumerate(daily.itertuples(), 1):
        day = row.date
        i = int(shadow.index.get_loc(day))
        label = f'{variant} {day.date()} independent support'
        today = shadow.loc[day]
        floor = min(completed_closes[-5:]) if len(completed_closes) >= 5 else None
        ready = count >= 60 + delay and floor is not None
        support_ok = floor is not None and float(row.close) >= floor
        support_break = floor is not None and float(row.close) < floor
        require(label + ' support excludes current close and prewindow',
                pd.isna(today.support_floor) if floor is None
                else abs(float(today.support_floor) / anchor - floor) < 1e-9)
        require(label + ' exact fixed initial delay after 60 evaluation closes',
                int(today.warmup_sessions) == count and bool(today.ready) == ready)
        require(label + ' independent support equality and strict-break boundary',
                bool(today.support_ok) == support_ok and bool(today.support_break) == support_break)
        if ready and first_ready is None:
            first_ready = str(day.date())
        require(label + ' actual target comes from independent previous close', float(row.target_position) == previous_target)
        same = fills.loc[fills.fill_time.eq(day)]
        buys, sells = same.loc[same.side.eq('BUY')], same.loc[same.side.eq('SELL')]
        require(label + ' no same-session round trip', not (len(buys) and len(sells)))
        if len(sells):
            require(label + ' actual full sale follows a latched decision',
                    episode is not None and episode['exit_pending'] and i > episode['exit_signal_index']
                    and int(sells.quantity.sum()) == episode['quantity'])
            exits += 1
            episode = None
        if len(buys):
            require(label + ' actual buy follows fresh eligible prior signal',
                    episode is None and previous_entry_signal and ready)
            episode = {'entry_index': i, 'entry_date': str(day.date()), 'deadline': i + 9,
                       'quantity': int(buys.quantity.sum()), 'exit_pending': False,
                       'exit_signal_index': None}
            entries += 1
            if first_actual_entry is None:
                first_actual_entry = str(day.date())
        failed_buy = previous_entry_signal and not len(buys)
        failed_buys += int(bool(failed_buy))
        require(label + ' failed buy resets for this close', bool(today.failed_buy_reset) == bool(failed_buy))
        accepted = False
        if episode is not None:
            was_pending = episode['exit_pending']
            early_exit = False  # Neither locked A nor B has a support-triggered exit.
            if not was_pending and (i >= episode['deadline'] or early_exit):
                episode['exit_pending'] = True
                episode['exit_signal_index'] = i
                breaks += int(early_exit and i < episode['deadline'])
                events.append({'entry_date': episode['entry_date'], 'exit_signal_date': str(day.date()),
                               'entry_index': episode['entry_index'], 'deadline_index': episode['deadline'],
                               'exit_signal_index': i, 'support_break': bool(support_break),
                               'support_exit_applied': bool(early_exit), 'time_exit_due': i >= episode['deadline'],
                               'quantity': episode['quantity'], 'normalized_close': float(row.close),
                               'normalized_prior_five_floor': floor})
            target = float(not episode['exit_pending'])
            require(label + ' fixed actual-entry plus-nine deadline and no topups',
                    int(today.entry_index) == episode['entry_index'] and int(today.deadline_index) == episode['deadline']
                    and int(today.holding_horizon) == 10 and int(row.quantity) == episode['quantity'])
            require(label + ' strict support/time exit remains latched after recovery',
                    bool(today.exit_pending) == episode['exit_pending'])
        else:
            accepted = bool(not failed_buy and ready and (base == 'repeated_H10' or support_ok))
            target = float(accepted)
            require(label + ' flat state resets actual-entry clock and pending exit',
                    int(row.quantity) == 0 and int(today.entry_index) == -1 and int(today.deadline_index) == -1
                    and not bool(today.exit_pending) and int(today.holding_horizon) == (10 if accepted else 0))
        require(label + ' independent fresh-entry signal and next-session target',
                bool(today.entry_signal) == accepted and float(today.target_position) == target)
        previous_target = target
        previous_entry_signal = accepted
        completed_closes.append(float(row.close))
    require(variant + ' complete actual cycles without forced terminal sale', entries - exits == int(episode is not None))
    require(variant + ' first ready decision exactly fixed delayed evaluation close',
            first_ready == str(daily.date.iloc[59 + delay].date()))
    require(variant + ' no hidden support early exit', breaks == 0)
    return {'actual_entry_cycles': entries, 'first_ready_decision': first_ready,
            'earliest_possible_entry': str(daily.date.iloc[60 + delay].date()),
            'first_actual_entry': first_actual_entry, 'fixed_initial_delay': delay,
            'support_triggered_exits_before_time_cap': breaks, 'failed_buy_reset_days': failed_buys,
            'support_event_records': events,
            'observation_scope': 'Support independently rebuilt from prior five actual normalized account closes, fixed 60-plus-delay in-window startup, real fill entry clock and irreversible SELL intent; cutoff-close state has no subsequent execution.'}


def main():
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX022 account audit evidence')
    checks, accounts, refs = [], [], []
    external_attempts = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def prohibited(*args, **kwargs):
        external_attempts.append('blocked')
        raise RuntimeError('No external call permitted during EX022 account audit')

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
        prior = module('s014_ex022_predecessor_account_audit', prior_audit_path)
        data = prior.load_frames()
        records = read(EX / 'others/account_results.json')['records']
        comparison = read(EX / 'others/comparison_accounts.json')['records']
        previous = read(OLD / 'others/account_results.json')['records']
        require('exactly twenty unique authorized new accounts',
                len(records) == len(EXPECTED) and {r['variant'] for r in records} == set(EXPECTED))
        require('comparison contains twenty new controls and two exact delay-zero baselines',
                len(comparison) == 22 and {r['variant'] for r in comparison} == set(EXPECTED) | set(REUSED))
        combined = {r['variant']: r for r in comparison}
        previous = {r['variant']: r for r in previous}
        reused_records = {batch: {r['variant']: r for r in read(EX.parent / batch / 'others/account_results.json')['records']}
                          for batch in {v[0] for v in REUSED.values()}}
        source_path = EX / 'src/strategy_runtime/strategies/repair.py'
        source_hash = sha256(source_path.read_bytes()).hexdigest()
        precheck = read(EX / 'others/precheck.json')
        require('causal precheck binds actual source', precheck['status'] == 'PASS'
                and precheck['source_sha256'] == source_hash)
        require('predecessor account audit passed', read(OLD / 'others/account_audit.json')['status'] == 'PASS')
        require('EX021 predecessor account audit passed', read(PREVIOUS / 'others/account_audit.json')['status'] == 'PASS')
        strategy = module('s014_ex022_account_audit_repair', source_path)
        market, raw, limits, status = [data[k] for k in (
            'stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
        indexed = [x.set_index(pd.to_datetime(x.Date)).sort_index() for x in (market, raw, limits)]
        old_strategy = module('s014_ex022_delay_zero_original', PREVIOUS / 'src/strategy_runtime/strategies/repair.py')
        for zero_variant, (_, old_variant, _) in REUSED.items():
            zero = strategy.history(market, raw, limits, status, zero_variant)
            original = old_strategy.history(market, raw, limits, status, old_variant)
            pd.testing.assert_frame_equal(zero, original, check_exact=True)
            require(zero_variant + ' exact original all-column history', True)
        old_high = verified_record(previous['high_H3'])
        require('original high H3 has complete buyhold execution',
                old_high['buyhold'] is not None and old_high['buyhold']['execution'] is not None)
        benchmark = json.dumps(old_high['buyhold'], sort_keys=True, separators=(',', ':'))
        for variant, (batch, old_name, candidate) in REUSED.items():
            left = combined[variant]
            right = reused_records[batch][old_name]
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
            shadow = strategy.history(market, raw, limits, status, variant)
            instance = strategy.RepairStrategy.from_parameters(strategy.ParameterSet({'variant': variant}))
            visible = instance.calculate_history({'market': market, 'raw': raw, 'limits': limits,
                                                   'status': status}, shadow.index)
            pd.testing.assert_frame_equal(visible, shadow, check_dtype=False)
            require(variant + ' public history preserves all economic values', True)
            states = status.set_index(pd.to_datetime(status.Date)).Status
            session_dates = pd.DatetimeIndex(pd.to_datetime(ledgers['account_daily'].date))
            aligned_states = states.reindex(session_dates)
            require(variant + ' explicit valid stock status covers every actual session',
                    aligned_states.isin(['TRADING', 'SUSPENDED']).all())
            fill_dates = pd.DatetimeIndex(pd.to_datetime(ledgers['fills'].fill_time)).normalize()
            require(variant + ' actual fills never occur during suspension', states.reindex(fill_dates).eq('TRADING').all())
            report = prior.audit_ledger(variant, ledgers, *indexed, strategy, require, shadow)
            conditional = audit_support(variant, ledgers, shadow, report['normalization_anchor'], prior, require)
            accounts.append({'variant': variant, 'candidate': record['candidate'], **report, **conditional,
                             'actual_suspended_sessions': int(aligned_states.eq('SUSPENDED').sum())})
            print('ACCOUNT_AUDIT_PASS', variant, len(checks), flush=True)
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
                  'formal_evidence': refs, 'source_sha256': source_hash,
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
    print('EX022_ACCOUNT_AUDIT_PASS', len(checks))


if __name__ == '__main__':
    main()
