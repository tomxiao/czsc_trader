"""Offline TDR backtest view reproducing the PTE forward-chart UI."""
from __future__ import annotations

from html import escape
from dataclasses import asdict
from datetime import datetime
from strategy_chart import get_chart_assets, chart_body
import json

from .chart_context import BacktestChartContext
from .observation import UnavailablePlanObservation


def _observation_payload(signal):
    recorded = signal.observation
    if isinstance(recorded, UnavailablePlanObservation):
        return {"status": "UNAVAILABLE", "message": recorded.unavailable.message,
                "recorded_plan": recorded.to_dict()}
    if recorded is not None:
        return recorded.to_dict()
    # Built-in benchmarks have numerical facts but no SRT implementation declaration.
    return {"status": "READY", "target_position": signal.target_position,
            "series": [{**asdict(series), "guides": [asdict(g) for g in series.guides]} for series in signal.series],
            "facts": [asdict(fact) for fact in signal.facts]}


def _chart_payload(context: BacktestChartContext) -> dict[str, object]:
    if not isinstance(context, BacktestChartContext):
        raise TypeError("TDR chart requires BacktestChartContext")
    return {
        "contract_version": "tdr_backtest_chart.v2",
        "mode": "BACKTEST",
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
            "observation": _observation_payload(x),
        } for x in context.signals],
        "execution": {
            "decisions": [],
            "fills": [{"fill_id": x.fill_id, "decision_id": x.decision_id,
                       "occurred_at": x.time.isoformat(),
                       "session": (x.time.date() if isinstance(x.time, datetime) else x.time).isoformat(),
                       "side": x.side, "quantity": x.quantity, "price": x.price, "fee": x.fees,
                       "time_precision": "TIMESTAMP" if isinstance(x.time, datetime) else "SESSION"}
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
    assets = get_chart_assets()
    css, script = assets.css, assets.javascript
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
.chart-section-title{{margin:0;padding:14px 18px;font-size:16px;font-weight:500}}
@media(max-width:700px){{.backtest-metrics{{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px 12px}}.backtest-metric strong{{font-size:13px}}}}
  </style>
</head>
<body style="margin:0;background:#0d1117">
  <main id="tdr-backtest-chart" class="strategy-chart" aria-label="{title}回测复盘图">
    <header class="forward-topbar">
      <div class="forward-brand"><span class="forward-logo" aria-hidden="true">T</span><div><h1 id="forward-title"></h1><p id="forward-subtitle"></p></div></div>
      <div class="forward-status"><span></span><b id="forward-asof"></b></div>
    </header>
    <section class="backtest-metrics" aria-label="回测绩效指标">{metric_html}</section>
    <section aria-label="策略运行复盘">
      <h2 class="chart-section-title">策略运行复盘</h2>
      {chart_body()}
    </section>
  </main>
  <script id="forward-context" type="application/json">{encoded}</script>
  <script>{script}</script>
  <script>mountStrategyChart(document.querySelector('#tdr-backtest-chart'), JSON.parse(document.querySelector('#forward-context').textContent));</script>
</body>
</html>'''
