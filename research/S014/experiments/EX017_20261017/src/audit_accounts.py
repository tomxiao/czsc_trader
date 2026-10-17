"""Offline audit of published accounts against the immutable strategy state machine."""
from datetime import datetime, time
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import ast
import importlib.util
import json
from pathlib import Path
import traceback
from uuid import UUID

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest, Dataset, PreparedDataRef
from czsc_trader.research_tools import EvidenceRef
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
VARIANTS = ('parent_H1', 'parent_H3', 'high_H3', 'high_H3_low_H1')
FULL_INPUT_REFERENCE = {
    'space_id': '9b7260bb-f12c-4eab-bc37-884d0cc58c91',
    'preparation_id': 'dfb12e42-f327-4e1b-bf25-d15201b4e69b',
    'manifest_sha256': 'b68cf906d81e19a16b131fe63ca1f4f901f9baa202bae75110481b5f209d8f57',
}


def load_frames():
    from pinned_inputs import get_context
    ctx = get_context()
    ref = PreparedDataRef(UUID(FULL_INPUT_REFERENCE['space_id']),
        UUID(FULL_INPUT_REFERENCE['preparation_id']), FULL_INPUT_REFERENCE['manifest_sha256'])
    values = {}
    for dataset, start in ((Dataset.STOCK_OHLCV, '2019-12-31'),
        (Dataset.STOCK_UNADJUSTED_DAILY, '2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS, '2020-01-01'),
        (Dataset.SECURITY_TRADING_STATUS, '2019-12-01')):
        result = ctx.data.fetch(DataRequest(dataset, '600722.SH', start, '2026-10-15', '2026-10-15'), prepared=ref)
        if not result.ready:
            raise RuntimeError('Full pinned input unavailable: ' + dataset.value)
        values[dataset.value] = result.dataframe
    return values


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def frame(table):
    return pd.DataFrame(table['data'], columns=[f['name'] for f in table['schema']['fields']])


def write_result(result):
    full = ROOT / 'research/S014/assets/runs/EX017_20261017/account_audit_full.json'
    full.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if full.exists():
        raise RuntimeError('Preserve full account audit evidence')
    full.write_bytes(content)
    summary = {key: value for key, value in result.items() if key != 'checks'}
    summary['full_audit'] = {'path': full.relative_to(ROOT).as_posix(),
                           'sha256': sha256(content).hexdigest(), 'bytes': len(content)}
    (EX / 'others/account_audit.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def by_date(value, column):
    result = value.copy()
    result[column] = pd.to_datetime(result[column]).dt.tz_localize(None).dt.normalize()
    return result


def synthetic_crossscale(strategy, require):
    days = pd.bdate_range('2020-01-02', periods=28)
    close = 10 + .05 * np.sin(np.arange(28))
    raw = pd.DataFrame({'Date': days, 'Open': close, 'High': close + .1,
                        'Low': close - .1, 'Close': close})
    raw.loc[25, ['Open', 'High', 'Low', 'Close']] = [9.9, 10.1, 9.8, 10.]
    raw.loc[26, ['Open', 'High', 'Low', 'Close']] = [5.10, 5.20, 5.06, 5.15]
    raw.loc[27, ['Open', 'High', 'Low', 'Close']] = [5., 5.01, 5., 5.01]
    market = raw.copy()
    market.loc[26:, ['Open', 'High', 'Low', 'Close']] *= 2.
    bounds = pd.DataFrame({'Date': days, 'DownLimit': 8., 'UpLimit': 12.})
    bounds.loc[26, ['DownLimit', 'UpLimit']] = [4.5, 5.5]
    bounds.loc[27, ['DownLimit', 'UpLimit']] = [5., 6.]
    status = pd.DataFrame({'Date': days, 'Status': 'TRADING'})
    samples = pd.DataFrame({'maturity_date': pd.date_range('2019-01-01', periods=60),
                            'gap_autocorr': -1.})
    h = strategy.history(market, raw, bounds, status, samples, 'parent_H1')
    require('crossscale prior signal accepted', h.entry_signal.iloc[25])
    require('crossscale raw low below limit does not imply HFQ fill',
            h.failed_buy_reset.iloc[26] and not h.held_at_close.iloc[26])
    raw.loc[26, 'Low'] = 5.05
    market.loc[26, 'Low'] = 10.10
    h = strategy.history(market, raw, bounds, status, samples, 'parent_H1')
    require('crossscale inclusive limit touch and next day sell',
            h.buy_filled_today.iloc[26] and h.held_at_close.iloc[26]
            and h.target_position.iloc[26] == 0 and h.sell_filled_today.iloc[27]
            and not h.held_at_close.iloc[27])
    sell = resolve_fill(OrderSpec('SELL', 'MARKET', 100), session_open=10.,
        session_time=datetime.combine(days[27].date(), time(9, 30)), intraday_touches=(),
        daily_quote=DailyQuote(10., 10.02),
        session_limits=SessionPriceLimits(days[27].date(), 10., 12., .02))
    require('crossscale sell uses current two-cent scaled tick',
            sell.filled and abs(sell.price - 10.02) < 1e-12)


def audit_ledger(name, tables, market, raw, limits, strategy, require, shadow=None):
    daily = by_date(tables['account_daily'], 'date').sort_values('date').reset_index(drop=True)
    daily['signal_date'] = pd.to_datetime(daily.signal_date).dt.tz_localize(None).dt.normalize()
    orders = by_date(tables['orders'], 'execution_date')
    fills = by_date(tables['fills'], 'fill_time')
    decisions = by_date(tables['decisions'], 'valid_session')
    decisions['signal_date'] = pd.to_datetime(decisions.signal_date).dt.tz_localize(None).dt.normalize()
    calendar = market.index[(market.index >= '2020-01-02') & (market.index <= '2026-10-15')]
    require(name + ' full 1642 sessions including last day',
            len(daily) == 1642 and pd.DatetimeIndex(daily.date).equals(calendar))
    require(name + ' unique ledger keys', daily.date.is_unique and orders.order_id.is_unique
            and fills.fill_id.is_unique and decisions.valid_session.is_unique)
    require(name + ' fills reference actual orders', set(fills.order_id).issubset(set(orders.order_id)))
    anchor = float(market.loc[daily.date.iloc[0], 'Close'] / daily.close.iloc[0])
    require(name + ' constant HFQ execution normalization', np.allclose(
        market.loc[daily.date, 'Close'].to_numpy() / anchor, daily.close, rtol=0, atol=1e-9))
    scale = market.Close / raw.Close / anchor
    prices = market[['Open', 'High', 'Low', 'Close']] / anchor
    cash = 100000.
    quantity = 0
    no_order_days = 0
    buy_days = 0
    sell_days = 0
    failed_buys = 0
    for row in daily.itertuples():
        label = f'{name} {row.date.date()}'
        require(label + ' opening continuity', abs(row.cash_before - cash) < 1e-6
                and int(row.quantity_before) == quantity)
        same_orders = orders.loc[orders.execution_date.eq(row.date)]
        same_fills = fills.loc[fills.fill_time.eq(row.date)]
        decision = decisions.loc[decisions.valid_session.eq(row.date)]
        require(label + ' one decision and correct lag', len(decision) == 1
                and decision.signal_date.iloc[0] == row.signal_date and row.signal_date < row.date
                and float(decision.target_position.iloc[0]) == float(row.target_position))
        target = float(row.target_position)
        expected_limit = strategy.buy_limit(float(raw.loc[row.signal_date, 'Close']),
                                             float(scale.loc[row.signal_date]))
        if target == 1 and quantity == 0:
            unit = Decimal(str(expected_limit)) * Decimal('1.001') * Decimal(100)
            affordable = int((Decimal(str(cash)) / unit).to_integral_value(rounding=ROUND_FLOOR)) * 100
            require(label + ' full cash entry order size',
                    int(same_orders.quantity.sum()) == affordable
                    and (same_orders.side.eq('BUY').all() if len(same_orders) else affordable == 0))
        elif target == 0 and quantity > 0:
            require(label + ' full position exit order size',
                    int(same_orders.quantity.sum()) == quantity and same_orders.side.eq('SELL').all())
        else:
            require(label + ' no topup or phantom order', len(same_orders) == 0)
        if not len(same_orders):
            no_order_days += 1
        price = prices.loc[row.date]
        bound = limits.loc[row.date]
        session_limits = SessionPriceLimits(row.date.date(), float(bound.DownLimit * scale.loc[row.date]),
            float(bound.UpLimit * scale.loc[row.date]), float(.01 * scale.loc[row.date]))
        for order in same_orders.itertuples():
            require(label + ' integer lot and max slice', int(order.quantity) > 0
                    and int(order.quantity) % 100 == 0 and int(order.quantity) <= 1000000)
            require(label + ' order signal and decision identity',
                    pd.Timestamp(order.signal_date).normalize() == row.signal_date
                    and order.decision_id == decision.decision_id.iloc[0])
            if order.side == 'BUY':
                require(label + ' exact frozen buy limit', order.order_type == 'LIMIT'
                        and abs(float(order.limit_price) - expected_limit) < 1e-9)
            else:
                require(label + ' market sell unchanged', order.order_type == 'MARKET')
            expected = resolve_fill(OrderSpec(order.side, order.order_type, int(order.quantity),
                float(order.limit_price) if order.order_type == 'LIMIT' else None),
                session_open=float(price.Open), session_time=datetime.combine(row.date.date(), time(9, 30)),
                intraday_touches=(), daily_quote=DailyQuote(float(price.Low), float(price.High)),
                session_limits=session_limits)
            associated = same_fills.loc[same_fills.order_id.eq(order.order_id)]
            require(label + ' actual fill and reason equal canonical TXE',
                    (order.status == 'FILLED') == expected.filled
                    and len(associated) == int(expected.filled) and order.reason == expected.reason)
            if order.side == 'BUY' and not expected.filled:
                failed_buys += 1
            if not expected.filled:
                continue
            fill = associated.iloc[0]
            require(label + ' execution price quantity and 0.1 percent fee',
                    fill.side == order.side and int(fill.quantity) == int(order.quantity)
                    and abs(float(fill.price) - expected.price) < 1e-9
                    and abs(float(fill.fees) - int(fill.quantity) * float(fill.price) * .001) < 1e-7)
            if fill.side == 'BUY':
                cash -= int(fill.quantity) * float(fill.price) + float(fill.fees)
                quantity += int(fill.quantity)
            else:
                cash += int(fill.quantity) * float(fill.price) - float(fill.fees)
                quantity -= int(fill.quantity)
        require(label + ' closing cash quantity equity', abs(row.cash - cash) < 1e-6
                and int(row.quantity) == quantity and cash >= -1e-6 and quantity >= 0
                and abs(row.equity - (cash + quantity * row.close)) < 1e-6)
        buying = same_fills.side.eq('BUY').any()
        selling = same_fills.side.eq('SELL').any()
        buy_days += int(buying)
        sell_days += int(selling)
        if shadow is not None:
            today = shadow.loc[row.date]
            signal = shadow.loc[row.signal_date]
            require(label + ' shadow exact daily holding and fills',
                    bool(today.held_at_close) == (quantity > 0)
                    and bool(today.buy_filled_today) == bool(buying)
                    and bool(today.sell_filled_today) == bool(selling))
            require(label + ' target uses previous signal not same-day exposure',
                    float(signal.target_position) == target)
            if today.failed_buy_reset:
                require(label + ' failed buy clears intent without new signal',
                        today.target_position == 0 and not today.entry_signal and quantity == 0)
    require(name + ' no calendar-year account reset', float(daily.cash_before.iloc[0]) == 100000.
            and int(daily.quantity_before.iloc[0]) == 0)
    trades = tables['trades']
    closed = trades.loc[trades.status.eq('CLOSED')]
    require(name + ' closed trades consistent with sells and T plus one',
            len(closed) == sell_days and all(pd.Timestamp(r.exit_date).normalize()
                > pd.Timestamp(r.entry_date).normalize() for r in closed.itertuples()))
    return {'sessions': len(daily), 'no_order_days': no_order_days, 'buy_days': buy_days,
            'sell_days': sell_days, 'failed_buy_orders': failed_buys, 'ending_quantity': quantity,
            'ending_cash': cash, 'normalization_anchor': anchor, 'last_session_verified': str(daily.date.iloc[-1].date())}


def main():
    destination = EX / 'others/account_audit.json'
    if destination.exists():
        raise RuntimeError('Preserve previous account audit')
    results = json.loads((EX / 'others/account_results.json').read_text(encoding='utf-8'))
    checks = []
    summaries = []
    evidence_refs = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    requests.sessions.Session.request = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError('No external call permitted during account audit'))
    try:
        data = load_frames()
        strategy_path = EX / 'src/strategy_runtime/strategies/repair_v3.py'
        previous_path = EX / 'src/strategy_runtime/strategies/repair_v2.py'
        strategy = module('s014_account_audit_repair', strategy_path)
        source_hash = sha256(strategy_path.read_bytes()).hexdigest()
        precheck = json.loads((EX / 'others/precheck_v2.json').read_text(encoding='utf-8'))
        require('prior causal precheck authenticated v2 source', precheck['status'] == 'PASS'
                and precheck['source_sha256'] == sha256(previous_path.read_bytes()).hexdigest()
                and precheck['check_count'] == 37)
        old_tree = ast.parse(previous_path.read_text(encoding='utf-8'))
        new_tree = ast.parse(strategy_path.read_text(encoding='utf-8'))
        for name in ('tick', 'buy_limit', 'history'):
            nodes = [next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
                     for tree in (old_tree, new_tree)]
            require('v3 same economic AST ' + name, ast.dump(nodes[0]) == ast.dump(nodes[1]))
        synthetic_crossscale(strategy, require)
        require('four original account variants succeeded', len(results['records']) == 4
                and {r['variant'] for r in results['records']} == set(VARIANTS)
                and all(r['status'] == 'SUCCEEDED' for r in results['records']))
        market, raw, limits, status = [data[k] for k in (
            'stock.ohlcv', 'stock.unadjusted_daily', 'security.price_limits', 'security.trading_status')]
        samples = pd.read_csv(EX / 'src/strategy_runtime/strategies/calibration_samples.csv')
        indexed = [x.set_index(pd.to_datetime(x.Date)).sort_index() for x in (market, raw, limits)]
        benchmark_identity = None
        for record in results['records']:
            require(record['variant'] + ' declared v3 candidate identity',
                    record['candidate'] == f'S014-C{VARIANTS.index(record["variant"]) + 9:04}')
            ref = EvidenceRef.from_dict(record['evidence'])
            content = ref.resolve(ROOT).read_bytes()
            require(record['variant'] + ' formal evidence sha256', sha256(content).hexdigest() == ref.sha256)
            payload = json.loads(content)
            require(record['variant'] + ' formal result identity', payload['result_hash'] == record['result_hash']
                    and len(payload['runs']) == 1)
            evidence_refs.append(ref.to_dict())
            run = payload['runs'][0]
            ledgers = {name: frame(table) for name, table in run['ledgers'].items()}
            shadow = strategy.history(market, raw, limits, status, samples, record['variant'])
            instance = strategy.RepairStrategy.from_parameters(strategy.ParameterSet({'variant': record['variant']}))
            visible = instance.calculate_history({'market': market, 'raw': raw, 'limits': limits,
                                                   'status': status}, shadow.index)
            require(record['variant'] + ' v3 observation cast leaves all economic values identical',
                    visible[['parent', 'high']].dtypes.eq(float).all()
                    and np.array_equal(visible[['parent', 'high']].to_numpy(), shadow[['parent', 'high']].to_numpy()))
            pd.testing.assert_frame_equal(visible.drop(columns=['parent', 'high']),
                                          shadow.drop(columns=['parent', 'high']))
            report = audit_ledger(record['variant'], ledgers, *indexed, strategy, require, shadow)
            summaries.append({'variant': record['variant'], **report})
            bh = run['buyhold']
            require(record['variant'] + ' full canonical buyhold execution', bh is not None and bh['execution'] is not None)
            identity = json.dumps(bh, sort_keys=True, separators=(',', ':'))
            if benchmark_identity is None:
                benchmark_identity = identity
                bh_tables = {name: frame(table) for name, table in bh['execution'].items()}
                bh_report = audit_ledger('buyhold', bh_tables, *indexed, strategy, require)
                bh_fills = bh_tables['fills']
                require('buyhold first purchase 2020-01-02 and no exits',
                        len(bh_fills) == 1 and bh_fills.side.eq('BUY').all()
                        and pd.Timestamp(bh_fills.fill_time.iloc[0]).date().isoformat() == '2020-01-02')
                summaries.append({'variant': 'buyhold', **bh_report})
            else:
                require(record['variant'] + ' identical full buyhold evidence', identity == benchmark_identity)
        result = {'status': 'PASS', 'check_count': len(checks), 'checks': checks,
                  'accounts': summaries, 'formal_evidence': evidence_refs,
                  'source_sha256': source_hash, 'full_input_reference': FULL_INPUT_REFERENCE,
                  'external_calls': 0, 'new_account_runs': 0}
    except Exception as exc:
        result = {'status': 'FAIL', 'check_count': len(checks), 'checks': checks,
                  'accounts': summaries, 'formal_evidence': evidence_refs,
                  'error': type(exc).__name__ + ': ' + str(exc), 'traceback': traceback.format_exc(),
                  'external_calls': 0, 'new_account_runs': 0}
        write_result(result)
        raise
    write_result(result)
    print('ACCOUNT_AUDIT_PASS', len(checks))


if __name__ == '__main__':
    main()
