"""One offline TDR chart for candidate and frozen backtests."""
from __future__ import annotations

from html import escape

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .chart_context import BacktestChartContext

SIGNAL = "#a78bfa"
FILL = "#f6b84a"
POSITION = "#68a5ff"


def build_backtest_figure(context: BacktestChartContext) -> go.Figure:
    if not isinstance(context, BacktestChartContext):
        raise TypeError("TDR chart requires BacktestChartContext")
    sessions = [bar.session.isoformat() for bar in context.bars]
    # Keep preceding signals visible and separate from execution days.
    timeline = sorted(set(sessions) | {x.signal_date.isoformat() for x in context.signals})
    values = sorted({key for signal in context.signals for key, _ in signal.values})
    titles = ["价格 · 后复权", "策略目标仓位 · 信号日", *[escape(x) for x in values],
              "实际持仓 · 股", "账户净值 · 相同初始资金"]
    count = len(titles)
    figure = make_subplots(rows=count, cols=1, shared_xaxes=True,
                           vertical_spacing=min(0.025, 0.15 / count),
                           row_heights=[3, *([1] * (count - 2)), 1.6], subplot_titles=titles)
    figure.add_trace(go.Candlestick(
        x=sessions, open=[x.open for x in context.bars], high=[x.high for x in context.bars],
        low=[x.low for x in context.bars], close=[x.close for x in context.bars],
        name="后复权K线", increasing_line_color="#ff6675", decreasing_line_color="#34c38f",
    ), row=1, col=1)
    signal_dates = [x.signal_date.isoformat() for x in context.signals]
    signal_hover = [f"信号日 {x.signal_date} → 执行日 {x.valid_session}<br>"
                    f"{escape(x.action)} · 目标 {x.target_position:g}<br>{escape(x.decision_id)}"
                    for x in context.signals]
    figure.add_trace(go.Scatter(
        x=signal_dates, y=[x.target_position for x in context.signals], name="策略信号",
        mode="lines+markers", line={"color": SIGNAL, "shape": "hv"},
        text=signal_hover, hovertemplate="%{text}<extra></extra>",
    ), row=2, col=1)
    figure.update_yaxes(range=[-0.05, 1.05], tickformat=".0%", row=2, col=1)
    for index, key in enumerate(values, start=3):
        points = [(x.signal_date.isoformat(), dict(x.values).get(key))
                  for x in context.signals]
        figure.add_trace(go.Scatter(
            x=[x[0] for x in points], y=[x[1] for x in points], name=escape(key),
            mode="lines+markers", connectgaps=False, line={"color": SIGNAL},
            hovertemplate="%{x}<br>%{y:.6g}<extra>" + escape(key) + "</extra>",
        ), row=index, col=1)
    by_day = {bar.session: bar for bar in context.bars}
    for side, symbol in (("BUY", "triangle-up"), ("SELL", "triangle-down")):
        fills = [x for x in context.fills if x.side == side]
        # Event markers use adjusted candle boundaries, not unadjusted fill prices.
        y = [by_day[x.time.date()].low if side == "BUY" else by_day[x.time.date()].high for x in fills]
        figure.add_trace(go.Scatter(
            x=[x.time.date().isoformat() for x in fills], y=y, mode="markers",
            name="买入成交" if side == "BUY" else "卖出成交", legendgroup="fills",
            marker={"symbol": symbol, "size": 11, "color": FILL},
            text=[f"{x.time.isoformat()} · {side}<br>未复权成交价 {x.price:.6g}<br>"
                  f"数量 {x.quantity} · 费用 {x.fees:.6g}<br>{escape(x.fill_id)}<br>"
                  "图标仅标识成交日，不表示后复权成交价" for x in fills],
            hovertemplate="%{text}<extra></extra>",
        ), row=1, col=1)
    figure.add_trace(go.Scatter(
        x=sessions, y=[x.quantity for x in context.accounts], name="实际持仓",
        line={"color": POSITION, "shape": "hv"},
        hovertemplate="%{x}<br>收盘持仓 %{y:,.0f} 股<extra></extra>",
    ), row=count - 1, col=1)
    figure.add_trace(go.Scatter(
        x=sessions, y=[x.equity / context.initial_cash for x in context.accounts], name="策略净值",
        line={"color": POSITION}, hovertemplate="%{x}<br>净值 %{y:.6f}<extra></extra>",
    ), row=count, col=1)
    for index, benchmark in enumerate(context.benchmarks):
        color = ("#8b98a7", "#34c38f")[index % 2]
        figure.add_trace(go.Scatter(
            x=sessions, y=[x / context.initial_cash for x in benchmark.equity],
            name=escape(benchmark.name), line={"color": color, "dash": "dot"},
            hovertemplate="%{x}<br>净值 %{y:.6f}<extra>" + escape(benchmark.name) + "</extra>",
        ), row=count, col=1)
    figure.update_xaxes(type="category", categoryorder="array", categoryarray=timeline,
                        rangeslider_visible=False, showspikes=True, spikemode="across",
                        spikesnap="cursor", spikecolor="#8b98a7", gridcolor="#26303b",
                        nticks=6, tickangle=0)
    figure.update_yaxes(gridcolor="#26303b", zerolinecolor="#303a47", fixedrange=False)
    figure.update_annotations(font_size=12)
    figure.update_layout(
        template="plotly_dark", paper_bgcolor="#0d1117", plot_bgcolor="#151b23",
        font={"family": 'Inter, "Microsoft YaHei", sans-serif', "color": "#e6edf3"},
        height=660 + 140 * len(values), margin={"l": 60, "r": 25, "t": 125, "b": 40},
        hovermode="x unified", hoversubplots="axis", dragmode="pan",
        legend={"orientation": "h", "y": 1.09, "yanchor": "bottom", "x": 0},
        uirevision="tdr_backtest.v1",
        meta={"contract_version": "tdr_backtest_chart.v1", "renderer": "TDR",
              "reference": context.reference, "identity_hash": context.identity_hash,
              "market_identity": context.market_identity},
    )
    return figure


def render_backtest_chart_html(context: BacktestChartContext) -> str:
    """Return standalone HTML; no PTE server or CDN is required."""
    figure = build_backtest_figure(context)
    plot = figure.to_html(full_html=False, include_plotlyjs=True, div_id="tdr-backtest-chart",
                          config={"displaylogo": False, "responsive": True, "scrollZoom": True})
    title = escape(f"{context.reference} · {context.symbol}")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 回测复盘</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#0d1117;color:#e6edf3;font:14px "Microsoft YaHei",sans-serif}}
header{{padding:20px 24px;background:#151b23;border-bottom:1px solid #303a47}}h1{{font-size:20px;margin:5px 0}}
p,footer{{color:#8b98a7;font-size:12px;line-height:1.8}}footer{{padding:12px 24px;border-top:1px solid #303a47}}
main{{padding:8px}}.badge{{font-size:11px;color:#68a5ff;letter-spacing:.12em}}
</style></head><body><header><span class="badge">TDR · 回测复盘</span><h1>{title}</h1>
<p>{context.start} — {context.end} · 初始资金 {context.initial_cash:,.2f}<br>
紫色：策略信号　橙色：实际成交　蓝色：实际持仓与净值 · 点击图例切换图层，滚轮缩放，拖动平移，双击复位</p>
</header><main>{plot}</main><footer>信号按信号日展示，悬浮查看实际执行日。K线为后复权价格；成交提示为未复权实际成交价。
成交图标仅定位成交日。持仓与净值来自TXE账本，基准来自本次受管回测。</footer></body></html>'''
