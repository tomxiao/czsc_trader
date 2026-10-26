"""Dependency-free shared chart assets for TDR and PTE."""

from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class ChartAssets:
    css: str
    javascript: str


def get_chart_assets() -> ChartAssets:
    """Return self-contained resources; no network or broker access is required."""
    assets = files(__package__).joinpath("static")
    return ChartAssets(
        assets.joinpath("strategy-chart.css").read_text(encoding="utf-8"),
        assets.joinpath("strategy-chart.js").read_text(encoding="utf-8"),
    )


def chart_body() -> str:
    """Return the shared view shell; caller owns the enclosing region and heading."""
    return '''<div class="forward-toolbar">
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
  <svg id="forward-svg" role="img" tabindex="0" aria-label="策略运行图，移动指针查看日期，左右方向键逐日浏览，Home和End跳至首尾，包含非交易日事件"></svg>
  <div class="forward-tooltip" id="forward-tooltip" role="tooltip" hidden></div>
</section>
<footer><span>移动指针查看 · ← → 逐日浏览（含非交易日事件）</span><span>信号按信号日 · 成交按记录日期</span><span>K线后复权 · 成交价不复权；箭头仅标记日期</span></footer>'''


__all__ = ["ChartAssets", "get_chart_assets", "chart_body"]
