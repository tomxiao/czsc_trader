"""Offline diagnosis from verified EvidenceRef and native DFLS identities.

This is an execution-boundary probe, not a strategy or account evaluation.
"""
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import json

import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef
from strategy_runtime.execution_rules import ExecutionRuleInput, build_frozen_execution_plan
from trading_execution_engine import OrderSpec, resolve_fill

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/600722-pilot-20261016'


def read_reference(value):
    reference = EvidenceRef.from_dict(value)
    return json.loads(reference.resolve(ROOT).read_text(encoding='utf-8'))


def main():
    references = json.loads((EXPERIMENT / 'others/input_evidence.json').read_text(encoding='utf-8'))
    source = read_reference(references['provider-snapshot'])
    preparations = read_reference(references['native-preparations'])
    frames = {label: pd.DataFrame(rows) for label, rows in source['responses'].items()}
    daily = frames['daily'].sort_values('trade_date').reset_index(drop=True)
    calendar = frames['calendar']
    expected = set(calendar.loc[calendar.is_open.eq(1), 'cal_date'])
    actual = set(daily.trade_date)
    assert len(actual) == len(daily) and actual == expected
    assert set(daily.ts_code) == {'600722.SH'}
    for label in ('factors', 'limits'):
        assert set(frames[label].trade_date) == actual and not frames[label].trade_date.duplicated().any()
    merged = daily.merge(frames['limits'], on=['ts_code', 'trade_date'], validate='one_to_one')
    assert (merged.low >= merged.down_limit - 0.005).all()
    assert (merged.high <= merged.up_limit + 0.005).all()
    assert np.isfinite(daily[['open', 'high', 'low', 'close', 'vol', 'amount']]).all().all()
    assert (daily[['open', 'high', 'low', 'close', 'vol', 'amount']] > 0).all().all()
    locked = merged.loc[np.isclose(merged.high, merged.low)].copy()
    locked['direction'] = np.where(np.isclose(locked.close, locked.up_limit), 'UP', 'DOWN')
    assert np.isclose(locked.close, np.where(locked.direction.eq('UP'), locked.up_limit, locked.down_limit)).all()

    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S014'),
                                      providers=ProviderConfig(bindings={}))
    admitted, native_results = {}, []
    for record in preparations['records']:
        assert record['status'] == 'READY'
        raw = record['request']
        request = DataRequest(Dataset(raw['dataset']), raw['symbol'], raw['start'], raw['end'], raw['required_cutoff'], frequency=raw['frequency'])
        locator = record['reference']
        prepared = PreparedDataRef(UUID(locator['space_id']), UUID(locator['preparation_id']), locator['manifest_sha256'])
        result = context.data.fetch(request, prepared=prepared)
        assert result.ready and result.identity.content_sha256 == record['content_sha256']
        key = raw['dataset'] + ':' + raw['start']
        admitted[key] = result.dataframe
        native_results.append(dict(dataset=raw['dataset'], start=raw['start'], rows=len(result.dataframe),
                                   prepared=locator, content_sha256=result.identity.content_sha256,
                                   quality=dict(result.identity.metadata['ohlcv_quality'])))

    raw = admitted['stock.unadjusted_daily:2020-01-01'].sort_values('Date').reset_index(drop=True)
    adjusted = admitted['stock.ohlcv:2020-01-01'].sort_values('Date').reset_index(drop=True)
    factor = frames['factors'].sort_values('trade_date').adj_factor.to_numpy()
    assert pd.to_datetime(raw.Date).equals(pd.to_datetime(adjusted.Date))
    assert pd.to_datetime(raw.Date).dt.strftime('%Y%m%d').tolist() == daily.trade_date.tolist()
    for public, vendor in (('Open', 'open'), ('High', 'high'), ('Low', 'low'), ('Close', 'close')):
        np.testing.assert_allclose(raw[public], daily[vendor], rtol=0, atol=1e-8)
        np.testing.assert_allclose(adjusted[public], raw[public] * factor, rtol=0, atol=1e-8)
    np.testing.assert_allclose(raw.Volume, daily.vol * 100, rtol=0, atol=1e-6)
    np.testing.assert_allclose(raw.Amount, daily.amount * 1000, rtol=0, atol=1e-6)
    np.testing.assert_allclose(adjusted.Volume, raw.Volume / factor, rtol=0, atol=1e-6)
    np.testing.assert_allclose(adjusted.Amount, raw.Amount, rtol=0, atol=1e-6)

    settings = {
        'instrument': {'lot_size': 100, 'price_tick': 0.01, 'price_limit_ratio': 0.1, 'maximum_order_quantity': 100000},
        'capital': {'mode': 'ALL_AVAILABLE', 'target_scope': 'SINGLE_SYMBOL', 'fee_rate': 0.001},
        'entry': {'order_type': 'LIMIT', 'limit_parameter': 0.01},
        'exit': {'order_type': 'MARKET', 'limit_ratio': 0.1},
    }
    probes = []
    for row in locked.itertuples():
        previous = daily.loc[daily.trade_date < row.trade_date].iloc[-1]
        is_buy = row.direction == 'UP'
        plan = build_frozen_execution_plan(ExecutionRuleInput(
            'FROZEN_RULE', settings, {}, 100000.0 if is_buy else 0.0, 0 if is_buy else 100,
            1.0 if is_buy else 0.0, float(previous.close), float(previous.close)))
        order = plan['orders'][0]
        fill = resolve_fill(OrderSpec(order['side'], order['order_type'], order['quantity'], order['limit_price']),
                            session_open=float(row.open), session_time=datetime.strptime(row.trade_date, '%Y%m%d'), intraday_touches=())
        # Negative control: the existing 1% buy limit rejects these upward gaps.
        # The sell probe exposes deterministic full fills without queue evidence.
        assert fill.filled == (not is_buy)
        probes.append(dict(date=row.trade_date, direction=row.direction, price=float(row.close),
                           volume_lots=float(row.vol), order=order, current_fill=asdict(fill),
                           interpretation='BUY_1PCT_ALREADY_UNFILLED' if is_buy else 'SELL_FULL_FILL_WITHOUT_QUEUE_EVIDENCE'))
    # Prove the downward sample includes an unchanged eight-bar minute path.
    for day, direction in [('2020-02-03', 'DOWN'), ('2021-02-09', 'UP')]:
        minute = admitted['stock.unadjusted_intraday:' + day]
        price = float(locked.loc[locked.trade_date.eq(day.replace('-', '')), 'close'].iloc[0])
        assert len(minute) == 8 and np.isclose(minute[['Open', 'High', 'Low', 'Close']], price).all()

    dividends = frames['dividends']
    events = dividends.loc[dividends.ex_date.fillna('').between('20200101', '20260930')]
    event_values = events[['stk_div', 'cash_div', 'cash_div_tax']].fillna(0)
    positive_events = int(event_values.ne(0).any(axis=1).sum())
    changes = int(frames['factors'].sort_values('trade_date').adj_factor.diff().fillna(0).ne(0).sum())
    assert positive_events == 0 and changes == 0
    source_paths = [ROOT / 'packages/trading_execution_engine/src/trading_execution_engine' / item
                    for item in ('fills.py', 'historical.py')]
    source_paths += [ROOT / 'packages/strategy_runtime/src/strategy_runtime/execution_rules.py']
    result = dict(
        status='DATA_PREPARATION_PASS_EXECUTION_GAP_CONFIRMED', symbol='600722.SH',
        window={'start': '2020-01-01', 'end': '2026-09-30'},
        inputs=references, upstream_calls=source['manifest']['calls'] + preparations['upstream_calls'],
        coverage={'exchange_sessions': len(expected), 'daily_rows': len(daily), 'missing_dates': sorted(expected - actual),
                  'daily_duplicates': int(daily.trade_date.duplicated().sum()), 'factor_changes': changes,
                  'positive_ex_dividend_records': positive_events, 'suspension_rows': len(frames['suspensions']),
                  'locked_up_days': int(locked.direction.eq('UP').sum()), 'locked_down_days': int(locked.direction.eq('DOWN').sum())},
        native_assets=native_results, execution_probes=probes,
        platform_sources={str(path.relative_to(ROOT).as_posix()): sha256(path.read_bytes()).hexdigest() for path in source_paths},
        findings=[
            '日线、因子及涨跌停价1636日对齐；6份原生数据准备全部READY；原始单位与复权换算逐值复核通过。',
            '3个全天跌停日的市价卖出探针均直接判满额成交；实际队列是否能成交未知，现接口未表达这一不确定性。',
            '9个全天涨停日的默认1%限价买单均未成交；不把填充内核的理论缺口扩大为当前买入规则的已发生问题。',
            '4日分钟样本不证明全区间分钟完整；未运行账户，所以现金、持仓、权益及未成交延续尚未验收。',
            '本标的窗口内没有正分红送股或因子变化；停牌接口为空且日线无缺日，仍缺少这些边界的阳性用例。',
            '固定单侧0.1%只用于订单探针，真实费用拆分、停牌、T+1可卖数量与公司行动尚待合同及最小专门验证。',
        ],
        proposed_minimum_dev_scope={
            'data': 'DFLS提供逐日涨跌停价与交易状态的强类型执行输入，原始价格口径，缺失应明确非READY；停牌不伪造成缺数或人工行情。',
            'execution': '在现有TXE路径统一执行A股市场约束；建议全天涨停不买入、全天跌停不卖出的保守成交合同，需用户确认；这是假设，不是历史成交事实。',
            'order_lifecycle': '未成交不得改变现金和持仓；当日单到期，次日根据仍有效的目标和新交易状态重下单；基准共用规则。',
            'tests': '正常日成交/未触价、全天涨跌停及对侧、盘中开板、缺失状态、停牌与复牌、未成交后续日、T+1和费用边界；比较ETF旧合同兼容。',
            'limits': '不扩至美股、选股池、基本面或多标的组合；不改已有冻结策略的历史语义。',
        },
        next_step='请用户确认A股成交合同及授权DEV修改平台，再做固定订单的现金/持仓/权益账本验证；通过后再提交策略机制方案。',
        models=0, account_evaluations=0, S013_state='PAUSED',
    )
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'upstream_calls', 'coverage')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
