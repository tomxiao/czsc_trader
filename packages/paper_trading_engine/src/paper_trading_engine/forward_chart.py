"""PTE-owned rendering of strategy-neutral forward-observation facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from html import escape
import json
from typing import Mapping
from strategy_chart import chart_body
from strategy_runtime import (
    ConstantGuide, ObservedFact, ObservedSeries, ObservationFormat, ObservationValueType,
    SignalPanelSnapshot,
)


FORWARD_CHART_CONTRACT_VERSION = "pte_forward_chart.v2"


@dataclass(frozen=True, slots=True)
class ChartObservation:
    """Display values independent of strategy-package and execution identities."""

    series: tuple[ObservedSeries, ...]
    facts: tuple[ObservedFact, ...]
    signal_panel: SignalPanelSnapshot | None = None
    definition_sha256: str | None = None
    release_hash: str | None = None
    message: str | None = None

    def __post_init__(self):
        if self.message is not None:
            if (type(self.message) is not str or not self.message.strip() or self.series != ()
                    or self.facts != () or self.signal_panel is not None
                    or self.definition_sha256 is not None or self.release_hash is not None):
                raise ValueError("unavailable chart observation requires only an explicit reason")
            return
        if (type(self.series) is not tuple or type(self.facts) is not tuple or
            any(not isinstance(item, ObservedSeries) for item in self.series) or
            any(not isinstance(item, ObservedFact) for item in self.facts)):
            raise ValueError("chart observation requires typed values")
        keys = [item.key for item in (*self.series, *self.facts)]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate chart observation keys")
        if self.signal_panel is not None:
            import re

            if not isinstance(self.signal_panel, SignalPanelSnapshot) or any(
                not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (self.definition_sha256, self.release_hash)
            ):
                raise ValueError("signal panel requires authenticated observation identities")
        elif self.definition_sha256 is not None or self.release_hash is not None:
            raise ValueError("signal identities require a signal panel")

    @classmethod
    def from_dict(cls, value: object) -> ChartObservation:
        if isinstance(value, dict) and value.get("status") == "UNAVAILABLE":
            if set(value) != {"status", "message"} or type(value["message"]) is not str:
                raise ValueError("invalid unavailable chart observation fields")
            return cls((), (), message=value["message"])
        fields = {"status", "series", "facts"}
        enhanced = isinstance(value, dict) and "signal_panel" in value
        if enhanced:
            fields |= {"signal_panel", "definition_sha256", "release_hash"}
        if (not isinstance(value, dict) or set(value) != fields or
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
        return cls(
            tuple(series), tuple(facts),
            SignalPanelSnapshot.from_dict(value["signal_panel"]) if enhanced else None,
            value.get("definition_sha256"), value.get("release_hash"),
        )

    def to_dict(self):
        if self.message is not None:
            return {"status": "UNAVAILABLE", "message": self.message}
        result = {
            "status": "READY",
            "series": [{**asdict(item), "guides": [asdict(g) for g in item.guides]} for item in self.series],
            "facts": [asdict(item) for item in self.facts],
        }
        if self.signal_panel is not None:
            result.update(
                signal_panel=self.signal_panel.to_dict(),
                definition_sha256=self.definition_sha256,
                release_hash=self.release_hash,
            )
        return result


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
    context["mode"] = "PAPER"
    context["execution"] = {**context["execution"], "decisions": context["execution"].get("decisions", [])}
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
  <link rel="stylesheet" href="/static/strategy-chart.css">
</head>
<body style="margin:0;background:#0d1117">
  <main id="pte-forward-chart" class="strategy-chart" aria-label="{title}前瞻观察图">
    <header class="forward-topbar">
      <div class="forward-brand"><span class="forward-logo" aria-hidden="true">P</span><div><h1 id="forward-title"></h1><p id="forward-subtitle"></p></div></div>
      <div class="forward-status"><span></span><b id="forward-asof"></b></div>
    </header>
    {chart_body()}

  </main>
  <script id="forward-context" type="application/json">{encoded}</script>
  <script src="/static/strategy-chart.js"></script>
  <script>mountStrategyChart(document.querySelector('#pte-forward-chart'), JSON.parse(document.querySelector('#forward-context').textContent));</script>
</body>
</html>"""
