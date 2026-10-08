"""PTE-owned rendering of strategy-neutral forward-observation facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from html import escape
import json
from typing import Mapping
from strategy_runtime import (
    ConstantGuide, ObservedFact, ObservedSeries, ObservationFormat, ObservationValueType,
)


FORWARD_CHART_CONTRACT_VERSION = "pte_forward_chart.v2"


@dataclass(frozen=True, slots=True)
class ChartObservation:
    """Display values independent of strategy-package and execution identities."""

    series: tuple[ObservedSeries, ...]
    facts: tuple[ObservedFact, ...]

    def __post_init__(self):
        if (type(self.series) is not tuple or type(self.facts) is not tuple or
            any(not isinstance(item, ObservedSeries) for item in self.series) or
            any(not isinstance(item, ObservedFact) for item in self.facts)):
            raise ValueError("chart observation requires typed values")
        keys = [item.key for item in (*self.series, *self.facts)]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate chart observation keys")

    @classmethod
    def from_dict(cls, value: object) -> ChartObservation:
        if (not isinstance(value, dict) or set(value) != {"status", "series", "facts"} or
            value["status"] != "READY" or type(value["series"]) is not list or
            type(value["facts"]) is not list):
            raise ValueError("invalid chart observation fields")
        series = []
        for item in value["series"]:
            if (not isinstance(item, dict) or set(item) != {"key", "label", "value", "guides"} or
                type(item["guides"]) is not list):
                raise ValueError("invalid chart series fields")
            guides = []
            for guide in item["guides"]:
                if not isinstance(guide, dict) or set(guide) != {"key", "label", "value"}:
                    raise ValueError("invalid chart guide fields")
                guides.append(ConstantGuide(**guide))
            series.append(ObservedSeries(item["key"], item["label"], item["value"], tuple(guides)))
        facts = []
        for item in value["facts"]:
            if (not isinstance(item, dict) or
                set(item) != {"key", "label", "value_type", "format", "value"}):
                raise ValueError("invalid chart fact fields")
            facts.append(ObservedFact(
                item["key"], item["label"], ObservationValueType(item["value_type"]),
                ObservationFormat(item["format"]), item["value"],
            ))
        return cls(tuple(series), tuple(facts))

    def to_dict(self):
        return {
            "status": "READY",
            "series": [{**asdict(item), "guides": [asdict(g) for g in item.guides]} for item in self.series],
            "facts": [asdict(item) for item in self.facts],
        }


def render_forward_chart_html(value: object) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("PTE forward chart input must be an object")
    context = dict(value)
    if set(context) != {
        "contract_version", "strategy", "window", "market_data", "observations", "execution",
    }:
        raise ValueError("PTE forward chart input fields are invalid")
    if context["contract_version"] != FORWARD_CHART_CONTRACT_VERSION:
        raise ValueError(f"PTE forward chart requires {FORWARD_CHART_CONTRACT_VERSION}")
    strategy = context.get("strategy")
    if not isinstance(strategy, Mapping):
        raise ValueError("PTE forward chart strategy identity is missing")
    release_id = str(strategy.get("release_id", "")).strip()
    strategy_name = str(strategy.get("name", "")).strip()
    if not release_id or not strategy_name:
        raise ValueError("PTE forward chart strategy title is incomplete")
    for row in context['observations']:
        ChartObservation.from_dict(row['observation'])
        if (row['account_id'] != strategy['account_id'] or
            row['symbol'] != strategy['symbol']):
            raise ValueError('forward observation differs from account or symbol')
        if date.fromisoformat(row['signal_date']) >= date.fromisoformat(row['valid_session']):
            raise ValueError('invalid chart observation sessions')
    for row in context['execution'].get('decisions', []):
        if row['account_id'] != strategy['account_id']:
            raise ValueError('forward decision event differs from account identity')
    encoded = json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).replace("</", "<\\/")
    title = escape(f"{release_id} · {strategy_name}")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} · 前瞻观察</title>
  <link rel="stylesheet" href="/static/forward-chart.css">
</head>
<body>
  <main id="pte-forward-chart" aria-label="{title}前瞻观察图">
    <header class="forward-topbar">
      <div class="forward-brand"><span class="forward-logo" aria-hidden="true">P</span><div><h1 id="forward-title"></h1><p id="forward-subtitle"></p></div></div>
      <div class="forward-status"><span></span><b id="forward-asof"></b></div>
    </header>
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
      <svg id="forward-svg" role="img" aria-label="交易日K线、策略信号、决策事件、成交、持仓及逐日事件"></svg>
      <div class="forward-tooltip" id="forward-tooltip" role="tooltip" hidden></div>
    </section>
    <footer><span>截止线左侧为行情背景；信号按信号日展示，决策按生效日展示，并保留已替代的历史记录</span><span>紫色＝策略信号　橙色＝成交　蓝色＝持仓</span><span>K线使用后复权价；成交箭头仅标记日期，纵坐标不代表成交价。</span></footer>
  </main>
  <script id="forward-context" type="application/json">{encoded}</script>
  <script src="/static/forward-chart.js"></script>
</body>
</html>"""
