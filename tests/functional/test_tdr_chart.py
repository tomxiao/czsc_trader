from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from czsc_trader.backtesting.chart import build_backtest_figure, render_backtest_chart_html
from czsc_trader.backtesting.chart_context import (
    BacktestChartContext, ChartAccount, ChartBar, ChartBenchmark, ChartFill, ChartSignal,
    build_backtest_chart_context,
)


@pytest.fixture
def chart_context():
    first, second = date(2026, 9, 15), date(2026, 9, 16)
    return BacktestChartContext(
        'S900-C001', 'a' * 64, 'b' * 64, '588080.SH', first, second, 1000.,
        (ChartBar(first, 10., 12., 9., 11.), ChartBar(second, 11., 13., 10., 12.)),
        (ChartSignal('D1', date(2026, 9, 14), first, 1., 'BUY', (('score', .8),)),
         ChartSignal('D2', first, second, 0., 'SELL', (('score', .2),))),
        (ChartFill('F1', 'D1', datetime(2026, 9, 15, 10), 'BUY', 100, 1., .1),
         ChartFill('F2', 'D2', datetime(2026, 9, 16, 10), 'SELL', 100, 1.1, .11)),
        (ChartAccount(first, 100, 1000.), ChartAccount(second, 0, 1009.79)),
        (ChartBenchmark('BuyHold', (1000., 1010.)),),
    )


def test_chart_separates_signals_fills_and_account_facts(chart_context):
    figure = build_backtest_figure(chart_context)
    traces = {trace.name: trace for trace in figure.data}
    assert tuple(traces['策略信号'].x) == ('2026-09-14', '2026-09-15')
    assert tuple(traces['买入成交'].x) == ('2026-09-15',)
    assert tuple(traces['买入成交'].y) == (9.,)  # Adjusted candle low, not raw fill price 1.
    assert '未复权成交价 1' in traces['买入成交'].text[0]
    assert tuple(traces['实际持仓'].y) == (100, 0)
    assert tuple(traces['策略净值'].y) == (1., 1.00979)
    assert tuple(traces['BuyHold'].y) == (1., 1.01)
    assert tuple(traces['score'].y) == (.8, .2)
    assert figure.layout.meta['renderer'] == 'TDR'
    assert figure.layout.xaxis.categoryarray[0] == '2026-09-14'


def test_chart_is_standalone_and_escapes_strategy_text(chart_context):
    context = replace(chart_context, reference='S900-</script><script>alert(1)</script>')
    html = render_backtest_chart_html(context)
    assert '<html lang="zh-CN">' in html
    assert 'tdr-backtest-chart' in html and 'plotly.js' in html
    assert '<script src=' not in html
    assert '</script><script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    with pytest.raises(TypeError, match='BacktestChartContext'):
        render_backtest_chart_html({})


def test_no_fills_is_a_valid_chart_without_invented_transactions(chart_context):
    figure = build_backtest_figure(replace(chart_context, fills=()))
    assert all(not trace.x for trace in figure.data if trace.name in {'买入成交', '卖出成交'})


@pytest.mark.parametrize('change', [
    lambda c: {'initial_cash': 0},
    lambda c: {'initial_cash': True},
    lambda c: {'initial_cash': float('nan')},
    lambda c: {'bars': c.bars[::-1]},
    lambda c: {'bars': (replace(c.bars[0], high=8.), c.bars[1])},
    lambda c: {'accounts': c.accounts[:1]},
    lambda c: {'accounts': (replace(c.accounts[0], quantity=-1), c.accounts[1])},
    lambda c: {'accounts': (replace(c.accounts[0], equity=float('inf')), c.accounts[1])},
    lambda c: {'signals': (replace(c.signals[0], signal_date=c.start), c.signals[1])},
    lambda c: {'signals': (replace(c.signals[0], target_position=1.1), c.signals[1])},
    lambda c: {'signals': (c.signals[0], c.signals[0])},
    lambda c: {'fills': (replace(c.fills[0], decision_id='foreign'),)},
    lambda c: {'fills': (replace(c.fills[0], time=datetime(2026, 9, 16, 10)),)},
    lambda c: {'fills': (replace(c.fills[0], price=float('nan')), )},
    lambda c: {'benchmarks': (ChartBenchmark('BuyHold', (1000.,)),)},
])
def test_chart_rejects_invalid_or_misaligned_facts(chart_context, change):
    with pytest.raises((TypeError, ValueError)):
        replace(chart_context, **change(chart_context))


def test_projection_detaches_frames_and_rejects_foreign_identity(chart_context):
    identity = object()
    signals = SimpleNamespace(snapshot=SimpleNamespace(identity=identity, source_hash='a' * 64),
                              evaluation_start=pd.Timestamp(chart_context.start),
                              evaluation_end=pd.Timestamp(chart_context.end))
    prices = pd.DataFrame([{'dt': x.session, 'open': x.open, 'high': x.high,
                            'low': x.low, 'close': x.close} for x in chart_context.bars])
    data = SimpleNamespace(adjusted_daily=prices, fingerprint='b' * 64, symbol='588080.SH')
    result = SimpleNamespace(identity=identity, decisions=pd.DataFrame([
        {'decision_id': 'D1', 'signal_date': '2026-09-14', 'valid_session': '2026-09-15',
         'target_position': 1., 'action': 'BUY', 'score': .8}]), fills=pd.DataFrame(),
        account_daily=pd.DataFrame([{'date': x.session, 'quantity': x.quantity, 'equity': x.equity}
                                    for x in chart_context.accounts]))
    # The adapter expects a real typed result identity; only repository-independent facts are synthetic.
    result.identity = SimpleNamespace(reference='S900-C001')
    signals.snapshot.identity = result.identity
    projected = build_backtest_chart_context(signals, data, result, 1000.)
    prices.loc[0, 'close'] = 999.
    assert projected.bars[0].close == 11.
    result.identity = SimpleNamespace(reference='S900-OTHER')
    with pytest.raises(ValueError, match='identity differs'):
        build_backtest_chart_context(signals, data, result, 1000.)
