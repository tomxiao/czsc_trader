"""SC-03: Python resource boundary; browser behavior runs directly under Node."""

from strategy_chart import chart_body, get_chart_assets


def test_shared_shell_has_direct_date_navigation_without_event_date_selector() -> None:
    body = chart_body()
    assert 'id="forward-event-date"' not in body
    assert "事件日期" not in body
    assert 'id="forward-svg" role="img" tabindex="0"' in body
    assert "非交易日事件" in body


def test_hosts_use_the_same_packaged_chart_assets() -> None:
    from czsc_trader.backtesting import chart as historical
    from paper_trading_engine import forward_chart as forward
    assert historical.chart_body is forward.chart_body is chart_body
    assert historical.get_chart_assets is get_chart_assets
    assets = get_chart_assets()
    assert '.strategy-chart' in assets.css
    assert 'StrategyChart' in assets.javascript
