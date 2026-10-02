"""Offline TDR backtest view reproducing the PTE forward-chart UI."""
from __future__ import annotations

from html import escape
from dataclasses import asdict
from datetime import datetime
from importlib.resources import files
import json

from .chart_context import BacktestChartContext


def _chart_payload(context: BacktestChartContext) -> dict[str, object]:
    if not isinstance(context, BacktestChartContext):
        raise TypeError("TDR chart requires BacktestChartContext")
    return {
        "contract_version": "tdr_backtest_chart.v1",
        "strategy": {
            "reference_id": context.reference,
            "identity_hash": context.identity_hash,
            "symbol": context.symbol,
        },
        "window": {"start": context.start.isoformat(), "end": context.end.isoformat()},
        "metrics": {
            "return": context.metrics.total_return,
            "max_drawdown": context.metrics.max_drawdown,
            "closed_trades": context.metrics.closed_trades,
            "calmar": context.metrics.calmar,
            "win_loss_ratio": context.metrics.win_loss_ratio,
            "win_rate": context.metrics.win_rate,
        },
        "market_data": {
            "identity": context.market_identity,
            "as_of": context.end.isoformat(),
            "adjustment": "hfq",
            "bars": [{"date": x.session.isoformat(), "open": x.open, "high": x.high,
                      "low": x.low, "close": x.close} for x in context.bars],
        },
        "observations": [{
            "decision_id": x.decision_id,
            "signal_date": x.signal_date.isoformat(),
            "valid_session": x.valid_session.isoformat(),
            "action": x.action,
            "observation": {
                "status": "READY", "target_position": x.target_position,
                "series": [{**asdict(series), "guides": [asdict(guide) for guide in series.guides]} for series in x.series],
                "facts": [asdict(fact) for fact in x.facts],
            },
        } for x in context.signals],
        "execution": {
            "fills": [{"fill_id": x.fill_id, "decision_id": x.decision_id,
                       "occurred_at": x.time.isoformat(),
                       "session": (x.time.date() if isinstance(x.time, datetime) else x.time).isoformat(),
                       "side": x.side, "quantity": x.quantity, "price": x.price, "fees": x.fees}
                      for x in context.fills],
            "snapshots": [{"session": x.session.isoformat(), "quantity": x.quantity}
                          for x in context.accounts],
        },
    }


def render_backtest_chart_html(context: BacktestChartContext) -> str:
    """Embed TDR-owned assets and audited facts in one portable HTML artifact."""
    payload = _chart_payload(context)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).replace("</", "<\\/")
    assets = files("czsc_trader.backtesting").joinpath("static")
    css = assets.joinpath("backtest-chart.css").read_text(encoding="utf-8")
    script = assets.joinpath("backtest-chart.js").read_text(encoding="utf-8")
    title = escape(f"{context.reference} · {context.symbol}")
    metrics = context.metrics
    cards = (
        ("收益率", f"{metrics.total_return:.2%}"),
        ("最大回撤", f"{metrics.max_drawdown:.2%}"),
        ("闭合交易数", str(metrics.closed_trades)),
        ("卡玛比率", "N/A" if metrics.calmar is None else f"{metrics.calmar:.3f}"),
        ("盈亏比", "N/A" if metrics.win_loss_ratio is None else f"{metrics.win_loss_ratio:.3f}"),
        ("交易胜率", "N/A" if metrics.win_rate is None else f"{metrics.win_rate:.2%}"),
    )
    metric_html = "".join(f'<div class="backtest-metric"><span>{label}</span><strong>{value}</strong></div>'
                          for label, value in cards)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} · 回测复盘</title>
  <style>{css}
.backtest-metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:16px;padding:12px 18px;background:var(--surface);border-bottom:1px solid var(--line)}}
.backtest-metric span{{display:block;font-size:11px;color:var(--muted)}}.backtest-metric strong{{display:block;margin-top:5px;font-size:16px;font-weight:500;font-variant-numeric:tabular-nums}}
@media(max-width:700px){{.backtest-metrics{{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px 12px}}.backtest-metric strong{{font-size:13px}}}}
  </style>
</head>
<body>
  <main id="tdr-backtest-chart" aria-label="{title}回测复盘图">
    <header class="forward-topbar">
      <div class="forward-brand"><span class="forward-logo" aria-hidden="true">T</span><div><h1 id="forward-title"></h1><p id="forward-subtitle"></p></div></div>
      <div class="forward-status"><span></span><b id="forward-asof"></b></div>
    </header>
    <section class="backtest-metrics" aria-label="回测绩效指标">{metric_html}</section>
    <div class="forward-toolbar">
      <div class="forward-controls" aria-label="观察窗口">
        <button type="button" data-range="20" aria-pressed="false">20日</button>
        <button type="button" data-range="40" aria-pressed="false">40日</button>
        <button type="button" data-range="all" aria-pressed="true">全部</button>
      </div>
      <div class="forward-controls" aria-label="图层">
        <button type="button" data-layer="signal" aria-pressed="true"><i class="signal"></i>策略信号</button>
        <button type="button" data-layer="fill" aria-pressed="true"><i class="fill"></i>成交事件</button>
        <button type="button" data-layer="position" aria-pressed="true"><i class="position"></i>持仓轨迹</button>
      </div>
    </div>
    <section class="forward-stage" id="forward-stage">
      <svg id="forward-svg" role="img" aria-label="交易日K线、策略信号、成交、持仓及逐日解释"></svg>
      <div class="forward-tooltip" id="forward-tooltip" role="tooltip" hidden></div>
    </section>
    <footer><span>信号按信号日展示；成交提示为未复权实际成交价</span><span>紫色＝策略信号　橙色＝成交　蓝色＝持仓</span></footer>
  </main>
  <script id="forward-context" type="application/json">{encoded}</script>
  <script>{script}</script>
</body>
</html>'''
