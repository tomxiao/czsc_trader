from __future__ import annotations

from datetime import date

from .models import StrategySnapshot


def render_report(
    snapshot: StrategySnapshot,
    metrics: dict[str, object],
    *,
    strategy_reference_symbol: str,
    backtest_symbol: str,
    application_mode: str,
    research_start: date | None,
    research_end: date | None,
    calculation_start: date,
    calculation_end: date,
    evaluation_start: date,
    evaluation_end: date,
    trading_days: int,
    lot_size: int,
) -> str:
    def percent(value: object) -> str:
        return "N/A" if value is None else f"{float(value):.2%}"

    def ratio(value: object) -> str:
        return "N/A" if value is None else f"{float(value):.3f}"

    strategy = metrics["strategy"]
    benchmarks = metrics["benchmarks"]
    if not isinstance(strategy, dict) or not isinstance(benchmarks, dict):
        raise TypeError("comparison metrics have an invalid structure")
    rows = [
        (snapshot.identity.reference, strategy["metrics"]),
        ("BuyHold", benchmarks["buyhold"]["metrics"]),
        ("MA5/MA20", benchmarks["ma5_ma20"]["metrics"]),
    ]
    research_window = (
        "未登记"
        if research_start is None or research_end is None
        else f"{research_start.isoformat()}—{research_end.isoformat()}"
    )
    lines = [
        f"# {snapshot.identity.reference} 回测报告",
        "",
        "本报告由 TDR Backtest v2 基于确定性账户回放生成。成交均为虚拟成交。",
        "主策略使用冻结执行规则；BuyHold与MA5/MA20使用独立资金按次日开盘成交。",
        f"- 策略参考标的：{strategy_reference_symbol}",
        f"- 实际回测标的：{backtest_symbol}",
        f"- 策略、BuyHold、MA5/MA20 最小交易数量单位：{lot_size}",
        (
            "- 应用方式：跨标的泛化测试"
            if application_mode == "cross_symbol_generalization"
            else "- 应用方式：原始标的回测"
        ),
        f"- 策略研发窗口：{research_window}",
        f"- 计算窗口：{calculation_start.isoformat()}—{calculation_end.isoformat()}",
        (
            f"- 回测窗口：{evaluation_start.isoformat()}—{evaluation_end.isoformat()}，"
            f"共{int(trading_days)}个交易日"
        ),
        "",
        "## 策略比较",
        "",
        "| 策略 | 收益率 | 最大回撤 | 卡玛比率 | 盈亏比 | 夏普率 | 闭合交易 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, item in rows:
        if not isinstance(item, dict):
            raise TypeError("one strategy metric row is invalid")
        lines.append(
            f"| {label} | {percent(item['return'])} | {percent(item['max_drawdown'])} | "
            f"{ratio(item['calmar'])} | {ratio(item['win_loss_ratio'])} | "
            f"{ratio(item['sharpe'])} | {int(item['closed_trades'])} |"
        )
    lines.extend(
        [
            "",
            "## 交互式图表",
            "",
            "- [主策略图表](chart.html)",
            "- [MA5/MA20图表](ma_chart.html)",
            "",
        ]
    )
    return "\n".join(lines)
