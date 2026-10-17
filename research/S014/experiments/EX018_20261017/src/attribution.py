"""Offline attribution of the published high-H3 account; no account replay."""
from datetime import datetime, time
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import requests
from czsc_trader.research_tools import EvidenceRef
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = ROOT / 'research/S014/experiments/EX017_20261017'
sys.path.insert(0, str(OLD / 'src'))
from audit_accounts import load_frames, frame

REASONS = ('STARTUP_NOT_READY', 'FAILED_BUY_RESET', 'PARENT_GAP_ONLY',
           'PARENT_INTRADAY_ONLY', 'PARENT_BOTH', 'LOW_ENVIRONMENT', 'BUY_UNFILLED')


def module(path):
    spec = importlib.util.spec_from_file_location('s014_ex018_prior_strategy', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def date_series(values):
    return pd.to_datetime(values).dt.tz_localize(None).dt.normalize()


def scopes(frame_, year='year'):
    return [('ALL', frame_), ('WITHOUT2026', frame_.loc[frame_[year].ne(2026)]),
            *[(str(y), frame_.loc[frame_[year].eq(y)]) for y in range(2020, 2027)]]


def returns(part):
    v = part.bh_log_return
    return {'days': len(part), 'positive_days': int(v.gt(0).sum()),
            'negative_days': int(v.lt(0).sum()), 'zero_days': int(v.eq(0).sum()),
            'positive_log_contribution': float(v.clip(lower=0).sum()),
            'negative_log_contribution': float(v.clip(upper=0).sum()),
            'net_log_contribution': float(v.sum())}


def main():
    output = EX / 'others/attribution_v2.json'
    if output.exists():
        raise RuntimeError('Preserve completed attribution')
    requests.sessions.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Offline only'))
    refs = json.loads((OLD / 'others/result.json').read_text(encoding='utf-8'))
    ref = EvidenceRef.from_dict(refs['evidence']['account-high-h3'])
    content = ref.resolve(ROOT).read_bytes()
    assert sha256(content).hexdigest() == ref.sha256
    evidence = json.loads(content)
    assert len(evidence['runs']) == 1
    run = evidence['runs'][0]
    tables = {name: frame(value) for name, value in run['ledgers'].items()}
    daily = tables['account_daily'].copy()
    daily['date'] = date_series(daily.date)
    daily['signal_date'] = date_series(daily.signal_date)
    daily = daily.sort_values('date').reset_index(drop=True)
    benchmark = frame(run['buyhold']['account_daily'])
    benchmark['date'] = date_series(benchmark.date)
    benchmark = benchmark.sort_values('date').reset_index(drop=True)
    assert daily.date.equals(benchmark.date) and len(daily) == 1642
    daily['bh_log_return'] = np.log(benchmark.equity.to_numpy(float)
        / np.r_[100000., benchmark.equity.to_numpy(float)[:-1]])
    daily['year'] = daily.date.dt.year
    fills = tables['fills'].copy()
    fills['day'] = date_series(fills.fill_time)
    fully_flat = daily.quantity_before.eq(0) & daily.quantity.eq(0) & ~daily.date.isin(fills.day)
    daily['fully_flat'] = fully_flat
    data = load_frames()
    keys = ('stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')
    market, raw, limits, status = [data[key] for key in keys]
    implementation = OLD / 'src/strategy_runtime/strategies/repair_v3.py'
    calibration = implementation.with_name('calibration_samples.csv')
    strategy = module(implementation)
    history = strategy.history(market, raw, limits, status, pd.read_csv(calibration), 'high_H3')
    indexed = [f.set_index(pd.to_datetime(f.Date)).sort_index() for f in (market, raw, limits, status)]
    market, raw, limits, status = indexed
    # A source cutoff is not an extra trading day; Dec31 is the genuine prior signal day.
    gap = np.log(market.Open / market.Close.shift())
    decisions = tables['decisions'].copy()
    decisions['signal_date'] = date_series(decisions.signal_date)
    decisions['valid_session'] = date_series(decisions.valid_session)
    decisions = decisions.set_index('valid_session')
    assert len(decisions) == len(daily)
    orders = tables['orders'].copy()
    orders['day'] = date_series(orders.execution_date)
    rows = []
    for row in daily.itertuples():
        h = history.loc[row.signal_date]
        d = decisions.loc[row.date]
        assert d.signal_date == row.signal_date
        for field in ('ready', 'parent', 'high', 'failed_buy_reset', 'entry_signal'):
            assert bool(h[field]) == bool(d[field]), (row.date, field)
        gap_known = bool(np.isfinite(gap.loc[row.signal_date]))
        missing_gap = gap_known and not bool(gap.loc[row.signal_date] < 0)
        missing_positive = not bool(market.loc[row.signal_date, 'Close'] > market.loc[row.signal_date, 'Open'])
        condition = ('UNREADY' if not h.ready else 'NO_PARENT' if not h.parent else
                     'LOW_ENVIRONMENT' if not h.high else 'ALL_CONDITIONS')
        today = orders.loc[orders.day.eq(row.date)]
        assert len(today) <= 1
        lifecycle = 'RESET_NO_ORDER' if h.failed_buy_reset else 'NOT_SUBMITTED'
        if len(today):
            lifecycle = str(today.side.iloc[0]) + ('_FILLED' if today.status.iloc[0] == 'FILLED' else '_UNFILLED')
        reason = 'NOT_FULLY_FLAT'
        if row.fully_flat:
            if h.failed_buy_reset:
                reason = 'FAILED_BUY_RESET'
            elif not h.ready:
                reason = 'STARTUP_NOT_READY'
            elif not h.parent:
                reason = ('PARENT_BOTH' if missing_gap and missing_positive else
                          'PARENT_GAP_ONLY' if missing_gap else 'PARENT_INTRADAY_ONLY')
            elif not h.high:
                reason = 'LOW_ENVIRONMENT'
            else:
                assert h.entry_signal and len(today) == 1 and today.side.eq('BUY').all()
                assert today.status.ne('FILLED').all()
                reason = 'BUY_UNFILLED'
        rows.append({'reason': reason, 'prev_signal_condition': condition, 'order_lifecycle': lifecycle,
                     'signal_gap_observed': gap_known, 'signal_ready': bool(h.ready), 'signal_parent': bool(h.parent),
                     'signal_high': bool(h.high), 'signal_failed_buy_reset': bool(h.failed_buy_reset),
                     'gap_not_negative': missing_gap, 'close_not_above_open': missing_positive})
    daily = pd.concat([daily, pd.DataFrame(rows)], axis=1)
    assert daily.loc[daily.fully_flat, 'reason'].isin(REASONS).all()
    assert (daily.reason.ne('NOT_FULLY_FLAT') == daily.fully_flat).all()
    summaries, parent_rows, partitions = [], [], []
    for scope, part in scopes(daily):
        for reason in REASONS:
            summaries.append({'scope': scope, 'reason': reason, **returns(part.loc[part.reason.eq(reason)])})
        for name, selected in [('ALL_SESSIONS', part), ('FULLY_FLAT', part.loc[part.fully_flat]),
                               ('NOT_FULLY_FLAT', part.loc[~part.fully_flat])]:
            partitions.append({'scope': scope, 'partition': name, **returns(selected)})
        idle = part.loc[part.fully_flat]
        for reason in (*REASONS, 'ALL_FULLY_FLAT'):
            q = idle if reason == 'ALL_FULLY_FLAT' else idle.loc[idle.reason.eq(reason)]
            # These three failure groups are disjoint, including within other priority reasons.
            for name, mask in [('GAP_ONLY', q.signal_gap_observed & q.gap_not_negative & ~q.close_not_above_open),
                               ('INTRADAY_ONLY', q.signal_gap_observed & ~q.gap_not_negative & q.close_not_above_open),
                               ('BOTH', q.signal_gap_observed & q.gap_not_negative & q.close_not_above_open),
                               ('NEITHER', q.signal_gap_observed & ~q.gap_not_negative & ~q.close_not_above_open),
                               ('GAP_UNOBSERVABLE', ~q.signal_gap_observed)]:
                parent_rows.append({'scope': scope, 'reason': reason, 'parent_failure': name, **returns(q.loc[mask])})
        flat_total = returns(idle)
        selected = [r for r in summaries if r['scope'] == scope]
        assert sum(r['days'] for r in selected) == flat_total['days']
        for field in ('positive_log_contribution', 'negative_log_contribution', 'net_log_contribution'):
            assert np.isclose(sum(r[field] for r in selected), flat_total[field], rtol=0, atol=1e-12)
    assert np.isclose(daily.bh_log_return.sum(), np.log(benchmark.equity.iloc[-1] / 100000.), atol=1e-12)

    anchor = float(market.loc[daily.date.iloc[0], 'Close'] / daily.close.iloc[0])
    assert np.allclose(market.loc[daily.date, 'Close'] / anchor, daily.close, rtol=0, atol=1e-9)
    scaled = market[['Open', 'High', 'Low', 'Close']] / anchor
    scales = market.Close / raw.Close / anchor
    trading = pd.DatetimeIndex(status.index[status.Status.eq('TRADING')])
    trading = trading[trading.isin(market.index)]
    extensions = []
    trades = tables['trades'].loc[tables['trades'].status.eq('CLOSED')].copy()
    for trade in trades.itertuples():
        exit_day = pd.Timestamp(trade.exit_date).normalize()
        pos = int(trading.get_loc(exit_day)); target = pos + 3
        item = {'cycle_id': trade.cycle_id, 'original_exit': exit_day.date().isoformat(),
                'year': exit_day.year, 'original_exit_price': float(trade.exit_price),
                'quantity': int(trade.quantity), 'entry_price': float(trade.entry_price),
                'status': 'RIGHT_CENSORED', 'scheduled_exit': None, 'actual_extended_exit': None,
                'exit_delay_sessions': None, 'gross_price_return': None,
                'paired_net_cash_change': None, 'paired_increment_per_entry_outlay': None,
                'price_envelope_mfe': None, 'price_envelope_mae': None,
                'original_sell_precision': None, 'extended_sell_precision': None}
        sell = fills.loc[fills.cycle_id.eq(trade.cycle_id) & fills.side.eq('SELL')]
        assert len(sell) == 1
        item['original_sell_precision'] = sell.time_precision.iloc[0]
        if target < len(trading):
            item['scheduled_exit'] = trading[target].date().isoformat()
            for j in range(target, len(trading)):
                day = trading[j]; b = limits.loc[day]; bar = scaled.loc[day]
                fill = resolve_fill(OrderSpec('SELL', 'MARKET', int(trade.quantity)),
                    session_open=float(bar.Open), session_time=datetime.combine(day.date(), time(9, 30)),
                    intraday_touches=(), daily_quote=DailyQuote(float(bar.Low), float(bar.High)),
                    session_limits=SessionPriceLimits(day.date(), float(b.DownLimit * scales.loc[day]),
                        float(b.UpLimit * scales.loc[day]), float(.01 * scales.loc[day])))
                if not fill.filled:
                    continue
                # No new purchase: compare two sale proceeds on the same historical position.
                delta = float(trade.quantity) * (float(fill.price) - float(trade.exit_price)) * .999
                between = scaled.loc[(scaled.index >= exit_day) & (scaled.index < day)]
                high = max(float(between.High.max()), float(fill.price))
                low = min(float(between.Low.min()), float(fill.price))
                item.update(status='OBSERVED', actual_extended_exit=day.date().isoformat(),
                    exit_delay_sessions=j-target, gross_price_return=float(fill.price / trade.exit_price - 1),
                    paired_net_cash_change=delta,
                    paired_increment_per_entry_outlay=delta / (float(trade.quantity * trade.entry_price) * 1.001),
                    price_envelope_mfe=float(high / trade.exit_price - 1),
                    price_envelope_mae=float(low / trade.exit_price - 1),
                    extended_sell_precision=str(fill.time_precision))
                break
        extensions.append(item)
    ext = pd.DataFrame(extensions)
    ext_summaries = []
    for scope, part in scopes(ext):
        observed = part.loc[part.status.eq('OBSERVED')]
        v = observed.paired_increment_per_entry_outlay.astype(float)
        ext_summaries.append({'scope': scope, 'closed_trades': len(part), 'observed': len(observed),
            'right_censored': int(part.status.eq('RIGHT_CENSORED').sum()),
            'delayed_exits': int(observed.exit_delay_sessions.gt(0).sum()),
            'positive_extensions': int(v.gt(0).sum()), 'negative_extensions': int(v.lt(0).sum()),
            'mean_paired_increment_per_entry_outlay': float(v.mean()) if len(v) else None,
            'median_paired_increment_per_entry_outlay': float(v.median()) if len(v) else None,
            'positive_contribution_per_observation': float(v.clip(lower=0).mean()) if len(v) else None,
            'negative_contribution_per_observation': float(v.clip(upper=0).mean()) if len(v) else None,
            'mean_gross_price_return': float(observed.gross_price_return.mean()) if len(v) else None,
            'mean_price_envelope_mfe': float(observed.price_envelope_mfe.mean()) if len(v) else None,
            'mean_price_envelope_mae': float(observed.price_envelope_mae.mean()) if len(v) else None,
            'drop_best_three_mean_increment': float(v.sort_values().iloc[:-3].mean()) if len(v)>3 else None})
    outputs = {'attribution_daily.csv': daily, 'attribution_idle_summary.csv': pd.DataFrame(summaries),
               'attribution_partitions.csv': pd.DataFrame(partitions),
               'attribution_parent_breakdown.csv': pd.DataFrame(parent_rows),
               'attribution_extension_members.csv': ext,
               'attribution_extension_summary.csv': pd.DataFrame(ext_summaries)}
    outputs = {name.replace('attribution_', 'attribution_v2_'): value for name, value in outputs.items()}
    for name, value in outputs.items():
        path = EX / 'others' / name
        if path.exists():
            raise RuntimeError('Preserve existing output ' + name)
        value.to_csv(path, index=False, lineterminator='\n')
    result = {'status': 'PASS', 'account_evidence': ref.to_dict(), 'new_account_runs': 0, 'source_calls': 0,
        'correction': 'v2 marks the first signal day Dec31 gap unobservable because Dec30 is outside input; previously counted as gap failure inside startup subgroup only. Main idle categories, log contributions and extension results unchanged. Original files retained.',
        'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'prior_strategy_sha256': sha256(implementation.read_bytes()).hexdigest(),
        'calibration_sha256': sha256(calibration.read_bytes()).hexdigest(),
        'flat_definition': 'quantity_before==0 and quantity==0 and no fills during session; exit and entry days excluded',
        'reason_precedence': ['FAILED_BUY_RESET', 'STARTUP_NOT_READY', 'PARENT_FAILURE_THREE_DISJOINT_CASES', 'LOW_ENVIRONMENT', 'BUY_UNFILLED'],
        'timing': 'prev_signal_condition and reset are known at previous completed signal; BUY_UNFILLED/order_lifecycle is realized during current execution and is not asserted to be predictable.',
        'bh_contribution': 'Natural log of actual fixed BuyHold closing NAV / previous closing NAV, initial NAV100000. Positive and negative parts reported; subset sum is neither isolated strategy return nor alpha.',
        'extension_contract': 'From actual original liquidation to third subsequent tradable-session planned open; same original quantity, normalized HFQ scale, .001 sell fee on each counterfactual exit; public TXE resolve_fill and delayed blocked sales. No new buy fee or account run.',
        'extension_limits': ['Overlapping episodes and skipped competing trades mean these are paired position diagnostics, not a new continuous strategy.',
            'Year belongs to original exit, not annual account PnL.',
            'Daily price envelopes include original exit-day extremes; SESSION fills have unknown intraday ordering. MFE/MAE are descriptive bounds, not achievable exits.',
            'Exit-day and subsequent-window attribution overlaps idle-day attribution; never add the two.',
            'Right-censored extensions excluded from means and explicitly counted.'],
        'all_partitions': [r for r in partitions if r['scope']=='ALL'],
        'all_idle': [r for r in summaries if r['scope']=='ALL'],
        'extension_summary': ext_summaries,
        'checks': ['formal evidence SHA256','1642 aligned benchmark/strategy sessions','all previous signal states reproduced against formal decisions',
                   'idle reasons mutually exclusive and exhaustive','annual and all-period category contributions sum exactly',
                   'full BH log sum equals terminal wealth ratio','normalized execution anchor matches original account','all original exits have exactly one sell fill'],
        'outputs': {name: sha256((EX/'others'/name).read_bytes()).hexdigest() for name in outputs}}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'idle': result['all_idle'], 'extensions': ext_summaries}, ensure_ascii=False))


if __name__ == '__main__':
    main()
