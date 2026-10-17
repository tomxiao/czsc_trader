"""Offline ledger, support-window and actual-fill clock audit of two conditional reservation support accounts."""
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
EXPECTED = {'support_exit_profit_reserve_H10': 'S014-C0075',
            'support_exit_nonprofit_reserve_H10': 'S014-C0076'}
REUSED = {'support_exit_H10': ('EX021_20261018', 'support_exit_H10', 'S014-C0035'),
          'support_exit_reserve_H10': ('EX023_20261018', 'support_exit_reserve_H10', 'S014-C0056')}

SUMMARY = EX / 'others/account_audit.json'
FULL = ROOT / 'research/S014/assets/runs/EX029_20261018/account_audit_full.json'



def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_result(result):
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX029 account audit evidence')
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
    """Rebuild conditional reservation from actual fills and current normalized closes."""
    positive_rule = variant == 'support_exit_profit_reserve_H10'
    daily = prior.by_date(tables['account_daily'], 'date').sort_values('date').reset_index(drop=True)
    fills = prior.by_date(tables['fills'], 'fill_time')
    pre = shadow.loc[shadow.index < daily.date.iloc[0]]
    require(variant + ' prewindow excluded and no initial condition state',
            pre.warmup_sessions.eq(0).all() and pre.support_floor.isna().all()
            and not pre.ready.any() and not pre.entry_signal.any() and pre.target_position.eq(0).all()
            and pre.reservation_index.eq(-1).all() and not pre.reservation_checked.any()
            and not pre.reservation_selected.any() and not pre.reservation_evaluated.any()
            and pre.reservation_float_pnl.eq(0).all() and pre.entry_fill_price.eq(0).all())
    episode = None
    reservation = -1
    checked = selected = False
    previous_target = 0.
    previous_entry_signal = False
    closes = []
    entries = exits = failed_buys = 0
    wait_flat = blocked_signal = 0
    positive_events = nonpositive_events = zero_events = 0
    selected_events = released_on_sell = carried_pending = pending_nonselected = 0
    time_decisions = 0
    events, wait_records, classifications = [], [], []
    first_ready = None
    for count, row in enumerate(daily.itertuples(), 1):
        day = row.date
        i = int(shadow.index.get_loc(day))
        today = shadow.loc[day]
        label = f'{variant} {day.date()} independent reservation'
        floor = min(closes[-5:]) if len(closes) >= 5 else None
        ready = count >= 60 and floor is not None
        support_ok = floor is not None and float(row.close) >= floor
        support_break = floor is not None and float(row.close) < floor
        require(label + ' previous five evaluation closes only', pd.isna(today.support_floor) if floor is None
                else abs(float(today.support_floor) / anchor - floor) < 1e-9)
        require(label + ' original startup and support equality boundary',
                int(today.warmup_sessions) == count and bool(today.ready) == ready
                and bool(today.support_ok) == support_ok and bool(today.support_break) == support_break)
        if ready and first_ready is None:
            first_ready = str(day.date())
        require(label + ' actual target follows independently reconstructed prior close',
                float(row.target_position) == previous_target)
        same = fills.loc[fills.fill_time.eq(day)]
        buys, sells = same.loc[same.side.eq('BUY')], same.loc[same.side.eq('SELL')]
        require(label + ' no same-session sale and rebuy', not (len(buys) and len(sells)))
        if len(sells):
            require(label + ' actual full sale follows latched SELL',
                    episode is not None and episode['exit_pending']
                    and i > episode['exit_signal_index'] and int(sells.quantity.sum()) == episode['quantity'])
            if checked and not selected:
                require(label + ' declined reservation stays original until actual sale',
                        reservation == episode['entry_index'] + 10)
                reservation = -1
                released_on_sell += 1
            episode = None
            exits += 1
        if len(buys):
            require(label + ' actual BUY follows previous fresh eligible signal',
                    episode is None and previous_entry_signal and ready)
            episode = {'entry_index': i, 'entry_date': str(day.date()), 'deadline': i + 9,
                       'quantity': int(buys.quantity.sum()), 'exit_pending': False, 'exit_signal_index': None,
                       'fill_price': float((buys.price * buys.quantity).sum() / buys.quantity.sum())}
            reservation = i + 10
            checked = False
            selected = True
            entries += 1
        failed_buy = previous_entry_signal and not len(buys)
        failed_buys += int(bool(failed_buy))
        require(label + ' failed BUY reset unchanged', bool(today.failed_buy_reset) == bool(failed_buy))
        evaluated = False
        pnl = 0.
        accepted = False
        if episode is not None:
            was_pending = episode['exit_pending']
            carried_pending += int(was_pending)
            pending_nonselected += int(was_pending and checked and not selected)
            if not was_pending and i < episode['deadline'] and support_break:
                require(label + ' first early SELL condition has not previously classified', not checked)
                evaluated = checked = True
                pnl = float(row.close) / (episode['fill_price'] * 1.001) - 1
                selected = bool(pnl > 0 if positive_rule else pnl <= 0)
                positive_events += int(pnl > 0)
                nonpositive_events += int(pnl <= 0)
                zero_events += int(pnl == 0)
                selected_events += int(selected)
                classifications.append({'entry_date': episode['entry_date'], 'decision_date': str(day.date()),
                    'entry_index': episode['entry_index'], 'decision_index': i,
                    'deadline_index': episode['deadline'], 'actual_fill_price_normalized': episode['fill_price'],
                    'normalized_close': float(row.close), 'float_pnl': pnl, 'positive': pnl > 0,
                    'reservation_selected': selected, 'reservation_index': reservation})
            if not was_pending and (i >= episode['deadline'] or support_break):
                episode['exit_pending'] = True
                episode['exit_signal_index'] = i
                time_due = i >= episode['deadline']
                time_decisions += int(time_due)
                require(label + ' TIME takes precedence and never classifies P',
                        not time_due or not evaluated and not checked and selected)
                events.append({'entry_date': episode['entry_date'], 'exit_signal_date': str(day.date()),
                    'entry_index': episode['entry_index'], 'exit_signal_index': i,
                    'deadline_index': episode['deadline'], 'time_exit_due': time_due,
                    'support_break': support_break, 'reservation_selected': selected,
                    'reservation_checked': checked, 'quantity': episode['quantity']})
            target = float(not episode['exit_pending'])
            require(label + ' actual holding clock quantity and SELL latch',
                    int(today.entry_index) == episode['entry_index']
                    and int(today.deadline_index) == episode['deadline']
                    and int(today.holding_horizon) == 10 and int(row.quantity) == episode['quantity']
                    and bool(today.exit_pending) == episode['exit_pending'])
        else:
            unconstrained = bool(not failed_buy and ready and support_ok)
            waiting = reservation >= 0 and i < reservation
            wait_flat += int(waiting)
            blocked_signal += int(waiting and unconstrained)
            if waiting:
                wait_records.append({'date': str(day.date()), 'source_index': i, 'reservation_index': reservation,
                    'eligible_without_reservation': unconstrained, 'quantity': int(row.quantity)})
            accepted = bool(unconstrained and not waiting)
            target = float(accepted)
            require(label + ' flat state original clock reset and fresh BUY planning',
                    int(row.quantity) == 0 and int(today.entry_index) == -1 and int(today.deadline_index) == -1
                    and not bool(today.exit_pending) and int(today.holding_horizon) == (10 if accepted else 0))
        require(label + ' reservation released only at actual SELL or reset by actual BUY',
                int(today.reservation_index) == reservation)
        require(label + ' once-only event and retained state across flat',
                bool(today.reservation_evaluated) == evaluated and bool(today.reservation_checked) == checked
                and bool(today.reservation_selected) == selected)
        require(label + ' actual fill P includes buy fee and is zero outside classification',
                abs(float(today.reservation_float_pnl) - pnl) < 1e-10
                and abs(float(today.entry_fill_price) / anchor - (episode['fill_price'] if episode is not None else 0.)) < 1e-9)
        require(label + ' independent new signal and next target',
                bool(today.entry_signal) == accepted and float(today.target_position) == target)
        previous_target, previous_entry_signal = target, accepted
        closes.append(float(row.close))
    require(variant + ' complete actual cycles without terminal invented sale', entries - exits == int(episode is not None))
    require(variant + ' exact original startup', first_ready == '2020-04-02')
    return {'actual_entry_cycles': entries, 'first_ready_decision': first_ready,
            'reservation_evaluations': len(classifications), 'reservation_positive': positive_events,
            'reservation_nonpositive': nonpositive_events, 'reservation_exact_zero': zero_events,
            'reservation_selected_count': selected_events,
            'reservation_declined_count': len(classifications) - selected_events,
            'reservation_released_on_actual_sell': released_on_sell,
            'time_exit_decisions_without_classification': time_decisions,
            'reservation_wait_flat_sessions': wait_flat, 'reservation_blocked_entry_signal_sessions': blocked_signal,
            'failed_buy_reset_days': failed_buys,
            'exit_latch_carried_close_sessions': carried_pending,
            'pending_sell_nonselected_reservation_retained_sessions': pending_nonselected,
            'failed_sell_orders': int((tables['orders'].side.eq('SELL') & tables['orders'].status.ne('FILLED')).sum()),
            'first_break_records': classifications, 'reservation_wait_records': wait_records,
            'support_event_records': events,
            'observation_scope': 'Real fills determine entry clock and retained state; previous-five actual normalized closes determine support; first strictly early break classifies P once for reentry reservation only. SELL is unchanged, TIME skips P, declined reservation releases only after actual full sale.'}


def main():
    if SUMMARY.exists() or FULL.exists():
        raise RuntimeError('Preserve previous EX029 account audit evidence')
    checks, accounts, refs = [], [], []
    external_attempts = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def prohibited(*args, **kwargs):
        external_attempts.append('blocked')
        raise RuntimeError('No external call permitted during EX029 account audit')

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
        prior = module('s014_ex029_predecessor_account_audit', prior_audit_path)
        data = prior.load_frames()
        records = read(EX / 'others/account_results.json')['records']
        comparison = read(EX / 'others/comparison_accounts.json')['records']
        previous = read(OLD / 'others/account_results.json')['records']
        require('exactly two authorized new accounts',
                len(records) == len(EXPECTED) and {r['variant'] for r in records} == set(EXPECTED))
        require('comparison contains two conditional reservation rules and two exact endpoint baselines',
                len(comparison) == len(EXPECTED) + len(REUSED) and {r['variant'] for r in comparison} == set(EXPECTED) | set(REUSED))
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
        strategy = module('s014_ex029_account_audit_repair', source_path)
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
    print('EX029_ACCOUNT_AUDIT_PASS', len(checks))


if __name__ == '__main__':
    main()
