"""Offline ledger, support-window and actual-fill clock audit of six short-cycle support accounts."""
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
EXPECTED = {'support_entry_H3': 'S014-C0062', 'support_exit_reserve_H3': 'S014-C0063',
            'support_first_profit_exit_H3': 'S014-C0064', 'support_entry_H5': 'S014-C0065',
            'support_exit_reserve_H5': 'S014-C0066', 'support_first_profit_exit_H5': 'S014-C0067'}
REUSED = {'support_entry_H10': ('EX021_20261018', 'support_entry_H10', 'S014-C0034'),
          'support_exit_reserve_H10': ('EX023_20261018', 'support_exit_reserve_H10', 'S014-C0056'),
          'support_first_profit_exit_H10': ('EX024_20261018', 'support_first_profit_exit_H10', 'S014-C0057')}
BASE_KIND = {'support_entry_H3': 'B', 'support_exit_reserve_H3': 'R', 'support_first_profit_exit_H3': 'P',
             'support_entry_H5': 'B', 'support_exit_reserve_H5': 'R', 'support_first_profit_exit_H5': 'P'}
HORIZONS = {variant: int(variant.rsplit('_H', 1)[1]) for variant in EXPECTED}

SUMMARY = EX / 'others/account_audit.json'
FULL = ROOT / 'research/S014/assets/runs/EX026_20261018/account_audit_full.json'



def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_result(result):
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX026 account audit evidence')
    FULL.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    FULL.write_bytes(content)
    summary = {k: v for k, v in result.items() if k != 'checks'}
    summary['accounts'] = [{k: v for k, v in account.items() if k not in ('support_event_records', 'reservation_wait_records', 'first_break_records')}
                           for account in result['accounts']]
    summary['full_audit'] = {'path': FULL.relative_to(ROOT).as_posix(),
                           'sha256': sha256(content).hexdigest(), 'bytes': len(content)}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                       encoding='utf-8', newline='\n')






def audit_support(variant, tables, shadow, anchor, prior, require):
    """Rebuild support from completed account closes and decisions from real fill cycles."""
    kind = BASE_KIND[variant]
    horizon = HORIZONS[variant]
    reserve = kind != 'B'
    conditional = kind == 'P'
    daily = prior.by_date(tables['account_daily'], 'date').sort_values('date').reset_index(drop=True)
    fills = prior.by_date(tables['fills'], 'fill_time')
    prewindow = shadow.loc[shadow.index < daily.date.iloc[0]]
    require(variant + ' execution prewindow excluded from warmup and support',
            prewindow.warmup_sessions.eq(0).all() and prewindow.support_floor.isna().all()
            and not prewindow.ready.any() and not prewindow.entry_signal.any()
            and prewindow.target_position.eq(0).all())
    if reserve:
        require(variant + ' reservation absent before first real buy', prewindow.reservation_index.eq(-1).all())
    else:
        require(variant + ' fixed-horizon B has no reservation observation', 'reservation_index' not in shadow.columns)
    if conditional:
        require(variant + ' conditional state absent before first actual entry',
                not prewindow.first_break_evaluated.any() and not prewindow.early_exit_selected.any()
                and not prewindow.break_checked.any() and prewindow.entry_fill_price.eq(0).all()
                and prewindow.float_pnl.eq(0).all())
    episode = None
    reservation = -1
    wait_flat = blocked_signal = 0
    reservation_records = []
    previous_target = 0.
    previous_entry_signal = False
    completed_closes = []
    events = []
    first_break_records = []
    selected_breaks = rejected_breaks = positive_breaks = nonpositive_breaks = 0
    repeated_breaks_ignored = exit_latch_carry_days = 0
    entries = exits = breaks = failed_buys = 0
    first_ready = None
    for count, row in enumerate(daily.itertuples(), 1):
        day = row.date
        i = int(shadow.index.get_loc(day))
        label = f'{variant} {day.date()} independent support'
        today = shadow.loc[day]
        floor = min(completed_closes[-5:]) if len(completed_closes) >= 5 else None
        ready = count >= 60 and floor is not None
        support_ok = floor is not None and float(row.close) >= floor
        support_break = floor is not None and float(row.close) < floor
        require(label + ' support excludes current close and prewindow',
                pd.isna(today.support_floor) if floor is None
                else abs(float(today.support_floor) / anchor - floor) < 1e-9)
        require(label + ' exact 60-completed-evaluation-session startup',
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
            episode = {'entry_index': i, 'entry_date': str(day.date()), 'deadline': i + horizon - 1,
                       'quantity': int(buys.quantity.sum()), 'exit_pending': False,
                       'exit_signal_index': None, 'break_checked': False,
                       'fill_price': float((buys.price * buys.quantity).sum() / buys.quantity.sum())}
            if reserve:
                reservation = i + horizon
            entries += 1
        if reserve:
            require(label + ' reservation is last actual buy plus locked horizon and survives flat days',
                    int(today.reservation_index) == reservation)
        failed_buy = previous_entry_signal and not len(buys)
        failed_buys += int(bool(failed_buy))
        require(label + ' failed buy resets for this close', bool(today.failed_buy_reset) == bool(failed_buy))
        accepted = False
        evaluated = selected = False
        float_pnl = 0.
        if episode is not None:
            was_pending = episode['exit_pending']
            exit_latch_carry_days += int(was_pending)
            repeated_breaks_ignored += int(not was_pending and episode['break_checked']
                                          and i < episode['deadline'] and support_break)
            if conditional and not was_pending and not episode['break_checked'] and i < episode['deadline'] and support_break:
                evaluated = True
                episode['break_checked'] = True
                float_pnl = float(row.close) / (episode['fill_price'] * 1.001) - 1
                positive = float_pnl > 0
                selected = positive
                positive_breaks += int(positive)
                nonpositive_breaks += int(not positive)
                selected_breaks += int(selected)
                rejected_breaks += int(not selected)
                first_break_records.append({'entry_date': episode['entry_date'], 'decision_date': str(day.date()),
                    'entry_index': episode['entry_index'], 'decision_index': i,
                    'deadline_index': episode['deadline'], 'actual_fill_price_normalized': episode['fill_price'],
                    'normalized_close': float(row.close), 'float_pnl': float_pnl,
                    'positive': bool(positive), 'early_exit_selected': bool(selected)})
            early_exit = selected if conditional else kind == 'R' and support_break
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
            require(label + ' fixed actual-entry plus horizon minus one deadline and no topups',
                    int(today.entry_index) == episode['entry_index'] and int(today.deadline_index) == episode['deadline']
                    and int(today.holding_horizon) == horizon and int(row.quantity) == episode['quantity'])
            require(label + ' strict support/time exit remains latched after recovery',
                    bool(today.exit_pending) == episode['exit_pending'])
        else:
            unconstrained = bool(not failed_buy and ready and support_ok)
            waiting = reservation >= 0 and i < reservation
            wait_flat += int(waiting)
            blocked_signal += int(waiting and unconstrained)
            if waiting:
                reservation_records.append({'date': str(day.date()), 'source_index': i,
                    'reservation_index': reservation, 'ready_support_without_failed_buy': unconstrained,
                    'actual_quantity': int(row.quantity)})
            accepted = bool(unconstrained and not waiting)
            target = float(accepted)
            require(label + ' flat state resets actual-entry clock and pending exit',
                    int(row.quantity) == 0 and int(today.entry_index) == -1 and int(today.deadline_index) == -1
                    and not bool(today.exit_pending) and int(today.holding_horizon) == (horizon if accepted else 0))
        if conditional:
            require(label + ' first eligible support break is evaluated once with complementary branch',
                    bool(today.first_break_evaluated) == evaluated and bool(today.early_exit_selected) == selected)
            require(label + ' independently computed first-break P includes buy fee only and zero otherwise',
                    abs(float(today.float_pnl) - float_pnl) < 1e-10)
            require(label + ' break-checked state and actual-entry price persist only while held',
                    bool(today.break_checked) == (episode['break_checked'] if episode is not None else False)
                    and abs(float(today.entry_fill_price) / anchor - (episode['fill_price'] if episode is not None else 0.)) < 1e-9)
        require(label + ' independent fresh-entry signal and next-session target',
                bool(today.entry_signal) == accepted and float(today.target_position) == target)
        previous_target = target
        previous_entry_signal = accepted
        completed_closes.append(float(row.close))
    require(variant + ' complete actual cycles without forced terminal sale', entries - exits == int(episode is not None))
    require(variant + ' first ready decision exactly 60th actual evaluation close',
            first_ready == str(daily.date.iloc[59].date()) == '2020-04-02')
    return {'actual_entry_cycles': entries, 'first_ready_decision': first_ready,
            'earliest_possible_entry': str(daily.date.iloc[60].date()),
            'support_triggered_exits_before_time_cap': breaks, 'failed_buy_reset_days': failed_buys,
            'locked_holding_horizon': horizon,
            'reservation_wait_flat_sessions': wait_flat,
            'reservation_blocked_entry_signal_sessions': blocked_signal,
            'last_actual_buy_reservation_index': reservation,
            'reservation_wait_records': reservation_records,
            'first_break_evaluations': len(first_break_records),
            'first_break_positive': positive_breaks, 'first_break_nonpositive': nonpositive_breaks,
            'first_break_selected': selected_breaks, 'first_break_rejected': rejected_breaks,
            'later_predeadline_breaks_ignored_after_rejection': repeated_breaks_ignored,
            'exit_latch_carried_close_sessions': exit_latch_carry_days,
            'failed_sell_orders': int((tables['orders'].side.eq('SELL') & tables['orders'].status.ne('FILLED')).sum()),
            'first_break_records': first_break_records,
            'support_event_records': events,
            'observation_scope': 'Support independently rebuilt from prior five actual normalized account closes, 60-session in-window startup, real fill entry clock, locked H3/H5 actual-entry deadline/reservation and corresponding B/R/P exit mechanism, and irreversible SELL intent; cutoff-close state has no subsequent execution.'}


def main():
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX026 account audit evidence')
    checks, accounts, refs = [], [], []
    external_attempts = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def prohibited(*args, **kwargs):
        external_attempts.append('blocked')
        raise RuntimeError('No external call permitted during EX026 account audit')

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
        prior = module('s014_ex026_predecessor_account_audit', prior_audit_path)
        data = prior.load_frames()
        records = read(EX / 'others/account_results.json')['records']
        comparison = read(EX / 'others/comparison_accounts.json')['records']
        previous = read(OLD / 'others/account_results.json')['records']
        require('exactly six authorized new accounts',
                len(records) == len(EXPECTED) and {r['variant'] for r in records} == set(EXPECTED))
        require('comparison contains six short-cycle rules and three exact H10 baselines',
                len(comparison) == 9 and {r['variant'] for r in comparison} == set(EXPECTED) | set(REUSED))
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
        require('EX018 predecessor account audit passed', read(PREVIOUS / 'others/account_audit_v2.json')['status'] == 'PASS')
        require('EX021 predecessor account audit passed', read(EX.parent / 'EX021_20261018/others/account_audit.json')['status'] == 'PASS')
        require('EX023 predecessor account audit passed', read(EX.parent / 'EX023_20261018/others/account_audit.json')['status'] == 'PASS')
        require('EX024 predecessor account audit passed', read(EX.parent / 'EX024_20261018/others/account_audit.json')['status'] == 'PASS')
        strategy = module('s014_ex026_account_audit_repair', source_path)
        market, raw, limits, status = [data[k] for k in (
            'stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
        indexed = [x.set_index(pd.to_datetime(x.Date)).sort_index() for x in (market, raw, limits)]
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
    print('EX026_ACCOUNT_AUDIT_PASS', len(checks))


if __name__ == '__main__':
    main()
