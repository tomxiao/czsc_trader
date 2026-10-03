from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import json
import re

import pandas as pd
import pytest
from strategy_runtime import ObservedSeries, StrategyObservation, StrategyIdentity

from czsc_trader.backtesting.chart import render_backtest_chart_html
from czsc_trader.backtesting.chart_context import (
    BacktestChartContext, BacktestChartMetrics, ChartAccount, ChartBar, ChartBenchmark, ChartFill, ChartSignal,
    build_backtest_chart_context, build_ma_chart_context,
)


@pytest.fixture
def chart_context():
    first, second = date(2026, 9, 15), date(2026, 9, 16)
    return BacktestChartContext(
        'S900-C0001', 'a' * 64, 'b' * 64, '588080.SH', first, second, 1000.,
        (ChartBar(first, 10., 12., 9., 11.), ChartBar(second, 11., 13., 10., 12.)),
        (ChartSignal('D1', date(2026, 9, 14), first, 1., 'BUY', (ObservedSeries('score', 'Score', .8, ()),)),
         ChartSignal('D2', first, second, 0., 'SELL', (ObservedSeries('score', 'Score', .2, ()),))),
        (ChartFill('F1', 'D1', datetime(2026, 9, 15, 10), 'BUY', 100, 1., .1),
         ChartFill('F2', 'D2', datetime(2026, 9, 16, 10), 'SELL', 100, 1.1, .11)),
        (ChartAccount(first, 100, 1000.), ChartAccount(second, 0, 1009.79)),
        (ChartBenchmark('BuyHold', (1000., 1010.)),),
        BacktestChartMetrics(.00979, -.02, 1, .5, None, 1.),
    )


def payload_from_html(html):
    return json.loads(re.search(r'<script id="forward-context" type="application/json">(.*?)</script>', html, re.S)[1])


def test_chart_separates_signals_fills_and_account_facts(chart_context):
    payload = payload_from_html(render_backtest_chart_html(chart_context))
    assert [x['signal_date'] for x in payload['observations']] == ['2026-09-14', '2026-09-15']
    assert [x['session'] for x in payload['execution']['fills']] == ['2026-09-15', '2026-09-16']
    assert payload['market_data']['bars'][0]['low'] == 9.
    assert payload['execution']['fills'][0]['price'] == 1.
    assert [x['quantity'] for x in payload['execution']['snapshots']] == [100, 0]
    assert payload['metrics'] == {'return': .00979, 'max_drawdown': -.02, 'closed_trades': 1,
                                 'calmar': .5, 'win_loss_ratio': None, 'win_rate': 1.}
    assert payload['observations'][0]['observation']['series'][0]['value'] == .8
    empty = payload_from_html(render_backtest_chart_html(replace(chart_context, fills=())))
    assert empty['execution']['fills'] == []


def test_chart_is_standalone_and_escapes_strategy_text(chart_context):
    context = replace(chart_context, reference='S900-</script><script>alert(1)</script>')
    html = render_backtest_chart_html(context)
    assert '<html lang="zh-CN">' in html
    assert 'tdr-backtest-chart' in html and 'forward-svg' in html
    assert 'Plotly.newPlot' not in html
    assert '<script src=' not in html
    assert '</script><script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    with pytest.raises(TypeError, match='BacktestChartContext'):
        render_backtest_chart_html({})


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
        {'decision_id': 'DEC-' + 'E' * 20, 'signal_date': '2026-09-14', 'valid_session': '2026-09-15',
         'target_position': 1., 'action': 'BUY', 'score': .8}]), fills=pd.DataFrame(),
        account_daily=pd.DataFrame([{'date': x.session, 'quantity': x.quantity, 'equity': x.equity}
                                    for x in chart_context.accounts]))
    result.observations = (StrategyObservation(StrategyIdentity('S900', 'S900-C0001', 'a' * 64, 'b' * 64, '588080.SH'), 'c' * 64, 'd' * 64, 'e' * 64, date(2026,9,14), date(2026,9,15), 'BUY', 1., (ObservedSeries('score','Score',.8,()),), ()),)
    # The adapter expects a real typed result identity; only repository-independent facts are synthetic.
    result.identity = SimpleNamespace(reference='S900-C0001')
    signals.snapshot.identity = result.identity
    projected = build_backtest_chart_context(signals, data, result, 1000., metrics=chart_context.metrics)
    prices.loc[0, 'close'] = 999.
    assert projected.bars[0].close == 11.
    result.identity = SimpleNamespace(reference='S900-OTHER')
    with pytest.raises(ValueError, match='identity differs'):
        build_backtest_chart_context(signals, data, result, 1000., metrics=chart_context.metrics)


def test_chart_has_exact_six_metrics_and_pte_controls(chart_context):
    html = render_backtest_chart_html(chart_context)
    cards = re.findall(r'<div class="backtest-metric"><span>(.*?)</span><strong>(.*?)</strong></div>', html)
    assert cards == [('收益率', '0.98%'), ('最大回撤', '-2.00%'), ('闭合交易数', '1'),
                     ('卡玛比率', '0.500'), ('盈亏比', 'N/A'), ('交易胜率', '100.00%')]
    assert '夏普' not in html
    assert 'data-range="all" aria-pressed="true"' in html
    assert all(f'data-layer="{layer}"' in html for layer in ('signal', 'fill', 'position'))
    unavailable = render_backtest_chart_html(replace(chart_context, metrics=replace(chart_context.metrics, calmar=None)))
    assert '<span>卡玛比率</span><strong>N/A</strong>' in unavailable
    no_closed_trades = replace(chart_context.metrics, closed_trades=0, win_rate=None)
    html = render_backtest_chart_html(replace(chart_context, metrics=no_closed_trades))
    assert '<span>交易胜率</span><strong>N/A</strong>' in html


@pytest.mark.parametrize('changes', [
    {'closed_trades': True}, {'closed_trades': -1}, {'total_return': float('nan')},
    {'max_drawdown': .1}, {'win_loss_ratio': -1}, {'calmar': float('inf')},
    {'win_rate': None}, {'win_rate': -.1}, {'win_rate': 1.1}, {'win_rate': True},
    {'win_rate': float('nan')}, {'closed_trades': 0, 'win_rate': .5},
])
def test_chart_metric_contract_rejects_invalid_values(chart_context, changes):
    with pytest.raises((TypeError, ValueError)):
        replace(chart_context.metrics, **changes)


def test_ma_chart_preserves_next_open_dates_and_uses_own_metrics(chart_context):
    from czsc_trader.backtesting.benchmarks import BenchmarkReplay

    benchmark = BenchmarkReplay(
        metrics={'ma5_ma20': {'metrics': {'return': .01, 'max_drawdown': 0., 'closed_trades': 1,
                                         'calmar': None, 'win_loss_ratio': None, 'win_rate': 1.}}},
        buyhold_account_daily=pd.DataFrame(), buyhold_orders=pd.DataFrame(),
        ma_signals=pd.DataFrame([
            {'date': '2026-09-14', 'ma5': 12., 'ma20': 11.},
            {'date': '2026-09-15', 'ma5': 10., 'ma20': 11.},
        ]),
        ma_orders=pd.DataFrame([
            {'signal_date': '2026-09-14', 'execution_date': '2026-09-15',
             'side': 'BUY', 'size': 100., 'price': 1., 'fees': .1},
            {'signal_date': '2026-09-15', 'execution_date': '2026-09-16',
             'side': 'SELL', 'size': 100., 'price': 1.1, 'fees': .11},
        ]),
        ma_account_daily=pd.DataFrame([
            {'date': '2026-09-15', 'signal_date': '2026-09-14', 'target_position': 1.,
             'quantity': 100., 'equity': 1000.},
            {'date': '2026-09-16', 'signal_date': '2026-09-15', 'target_position': 0.,
             'quantity': 0., 'equity': 1010.},
        ]),
        ma_trades=pd.DataFrame(), ma_audit_signals=pd.DataFrame(),
    )
    projected = build_ma_chart_context(chart_context, benchmark)
    payload = payload_from_html(render_backtest_chart_html(projected))
    assert payload['observations'][0]['signal_date'] == '2026-09-14'
    assert payload['execution']['fills'][0]['occurred_at'] == '2026-09-15'
    assert payload['execution']['fills'][0]['price'] == 1.
    assert payload['metrics']['return'] == .01 and payload['metrics']['calmar'] is None
    assert projected.identity_hash != chart_context.identity_hash
