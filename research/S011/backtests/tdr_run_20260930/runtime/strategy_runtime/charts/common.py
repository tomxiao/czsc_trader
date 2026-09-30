"""Shared visual system for strategy-owned TDR backtest charts."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


@dataclass(frozen=True)
class Guide:
    name: str
    value: float
    color: str


@dataclass(frozen=True)
class Panel:
    columns: tuple[str, ...]
    name: str
    color: str
    guides: tuple[Guide, ...] = ()
    dynamic_threshold: str | None = None
    line_shape: str = "linear"


def _frame(rows: object, *date_fields: str) -> pd.DataFrame:
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    flattened = []
    for raw in rows:
        row = dict(raw)
        output = row.pop("strategy_output", None)
        if isinstance(output, dict):
            row.update(output)
        flattened.append(row)
    frame = pd.DataFrame(flattened)
    date_field = next((field for field in date_fields if field in frame), None)
    if date_field is not None:
        frame["date"] = (
            pd.to_datetime(frame[date_field], utc=True).dt.tz_convert(None).dt.normalize()
        )
        frame = frame.sort_values("date")
    return frame


def _prices(context: dict[str, Any]) -> pd.DataFrame:
    frame = pd.DataFrame(context["market_data"]["bars"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    return frame.set_index("date").sort_index()


def _panel_column(frame: pd.DataFrame, panel: Panel) -> str:
    column = next((name for name in panel.columns if name in frame), None)
    if column is None:
        raise ValueError(f"strategy chart requires one of {panel.columns}")
    return column


def _marker_y(
    prices: pd.DataFrame, dates: pd.Series, side: pd.Series, distance: float,
) -> list[float]:
    values = []
    for session, action in zip(dates, side, strict=True):
        upper = str(action).upper() in {"SELL", "EXIT"}
        column = "high" if upper else "low"
        values.append(float(prices.loc[session, column]) + (distance if upper else -distance))
    return values


def _hover_text(
    prices: pd.DataFrame, rows: pd.DataFrame, panels: tuple[Panel, ...],
) -> list[str]:
    by_date = (
        {session: group.iloc[-1] for session, group in rows.groupby("date")}
        if not rows.empty
        else {}
    )
    output = []
    for session, price in prices.iterrows():
        lines = [
            f"<b>{session.date().isoformat()}</b>",
            f"开 {float(price['open']):.3f}",
            f"高 {float(price['high']):.3f}",
            f"低 {float(price['low']):.3f}",
            f"收 {float(price['close']):.3f}",
        ]
        row = by_date.get(session)
        if row is not None:
            for panel in panels:
                column = next((name for name in panel.columns if name in row.index), None)
                if column is not None and pd.notna(row[column]):
                    lines.append(f"{panel.name} {float(row[column]):.4f}")
            if "regime" in row.index and pd.notna(row["regime"]):
                lines.append(f"行情状态 {row['regime']}")
        output.append("<br>".join(lines))
    return output


def _shell(
    figure: go.Figure,
    context: dict[str, Any],
    *,
    cards: list[tuple[str, str]],
    title: str,
) -> str:
    runtime = context["render"]["plotly_runtime"]
    include_plotlyjs: bool | str = True if runtime == "embedded" else "/static/plotly.min.js"
    plot = figure.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"displaylogo": False, "responsive": True},
    )
    metrics = "".join(
        f'<div class="metric"><span>{escape(name)}</span><strong>{escape(value)}</strong></div>'
        for name, value in cards
    )
    reference = escape(str(context["strategy"]["reference_id"]))
    mode = "TDR · 回测复盘"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{{margin:0;background:#07111f;color:#eef5ff;font-family:Inter,"Microsoft YaHei",sans-serif}}
*{{box-sizing:border-box}}.shell{{padding:18px 20px 10px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-bottom:12px}}
.eyebrow{{font-size:11px;letter-spacing:.18em;color:#72b7ff}}h1{{font-size:20px;margin:5px 0 0}}.reference{{color:#a9b8ca;font-size:12px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-bottom:10px}}.metric{{border:1px solid #1c334b;background:#0b1727;border-radius:8px;padding:8px 10px}}
.metric span{{display:block;color:#8fa5bd;font-size:11px}}.metric strong{{display:block;margin-top:3px;font-size:15px}}.plot{{border:1px solid #1c334b;border-radius:10px;overflow:hidden;background:#0b1727}}
</style></head><body><section class="shell"><header><div><div class="eyebrow">{mode}</div><h1>{escape(title)}</h1></div><div class="reference">{reference}</div></header><div class="metrics">{metrics}</div><main class="plot">{plot}</main></section></body></html>"""


class UnifiedStrategyCharts:
    """Base renderer. Each frozen strategy supplies only its semantic panels."""

    def panels(self, context: dict[str, Any]) -> tuple[Panel, ...]:
        raise NotImplementedError

    @staticmethod
    def _base_figure(
        context: dict[str, Any], panels: tuple[Panel, ...],
    ) -> tuple[go.Figure, pd.DataFrame, pd.DataFrame]:
        prices = _prices(context)
        rows = _frame(
            context["strategy_output"].get("chart_rows", []), "date", "signal_date"
        )
        row_count = 1 + len(panels)
        heights = [0.56, *([0.22 / max(len(panels), 1)] * len(panels))]
        if panels:
            heights[0] = 0.68
            scale = (1 - heights[0]) / sum(heights[1:])
            heights[1:] = [height * scale for height in heights[1:]]
        figure = make_subplots(
            rows=row_count,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.025,
            row_heights=heights,
        )
        figure.add_trace(
            go.Candlestick(
                x=prices.index,
                open=prices["open"],
                high=prices["high"],
                low=prices["low"],
                close=prices["close"],
                name="日K",
                increasing_line_color="#ef4444",
                decreasing_line_color="#22c55e",
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=prices.index,
                y=prices["close"],
                mode="markers",
                name="交易日详情",
                showlegend=False,
                marker={"color": "rgba(0,0,0,0)", "size": 12},
                text=_hover_text(prices, rows, panels),
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        for index, panel in enumerate(panels, start=2):
            column = None if rows.empty else _panel_column(rows, panel)
            figure.add_trace(
                go.Scatter(
                    x=[] if rows.empty else rows["date"],
                    y=[]
                    if column is None
                    else pd.to_numeric(rows[column], errors="coerce"),
                    mode="lines",
                    name=panel.name,
                    line={"color": panel.color, "width": 2, "shape": panel.line_shape},
                    hovertemplate="%{x|%Y-%m-%d}<br>%{y:.4f}<extra>" + panel.name + "</extra>",
                ),
                row=index,
                col=1,
            )
            if panel.dynamic_threshold is not None:
                if not rows.empty and panel.dynamic_threshold not in rows:
                    raise ValueError(
                        f"strategy chart requires {panel.dynamic_threshold}"
                    )
                figure.add_trace(
                    go.Scatter(
                        x=[] if rows.empty else rows["date"],
                        y=[]
                        if rows.empty
                        else pd.to_numeric(
                            rows[panel.dynamic_threshold], errors="coerce"
                        ),
                        mode="lines",
                        name="动态阈值",
                        line={"color": "#ef4444", "width": 1, "dash": "dash"},
                    ),
                    row=index,
                    col=1,
                )
            for guide in panel.guides:
                figure.add_hline(
                    y=guide.value,
                    line={"color": guide.color, "width": 1, "dash": "dash"},
                    annotation_text=guide.name,
                    row=index,
                    col=1,
                )
            figure.update_yaxes(title_text=panel.name, row=index, col=1)
        return figure, prices, rows

    @staticmethod
    def _events(
        figure: go.Figure, prices: pd.DataFrame, context: dict[str, Any],
    ) -> None:
        decisions = _frame(context["strategy_output"].get("decisions", []), "signal_date")
        if not decisions.empty:
            decisions = decisions.loc[decisions["date"].isin(prices.index)].copy()
            if "action" not in decisions:
                changed = decisions["target_position"].ne(
                    decisions["target_position"].shift(fill_value=0)
                )
                decisions = decisions.loc[changed]
                decisions["action"] = decisions["target_position"].map(
                    {1: "BUY", 0: "SELL"}
                )
            active = decisions.loc[
                decisions["action"].astype(str).str.upper().isin(
                    {"BUY", "SELL", "ENTER", "EXIT"}
                )
            ]
            if not active.empty:
                span = float(prices["high"].max() - prices["low"].min())
                gap = max(span * 0.035, float(prices["close"].median()) * 0.002)
                figure.add_trace(
                    go.Scatter(
                        x=active["date"],
                        y=_marker_y(prices, active["date"], active["action"], gap),
                        mode="markers",
                        name="策略决策",
                        text=active.get("decision_id", active["action"]),
                        marker={"color": "#f59e0b", "symbol": "diamond", "size": 11},
                        hovertemplate="%{x|%Y-%m-%d}<br>%{text}<extra>策略决策</extra>",
                    ),
                    row=1,
                    col=1,
                )
        fills = _frame(
            context["execution"].get("fills", []),
            "fill_time",
            "occurred_at",
            "session",
        )
        if not fills.empty and "side" in fills:
            fills = fills.loc[fills["date"].isin(prices.index)]
            if not fills.empty:
                span = float(prices["high"].max() - prices["low"].min())
                gap = max(span * 0.06, float(prices["close"].median()) * 0.003)
                figure.add_trace(
                    go.Scatter(
                        x=fills["date"],
                        y=_marker_y(prices, fills["date"], fills["side"], gap),
                        mode="markers",
                        name="成交",
                        text=fills.get("fill_id", fills["side"]),
                        marker={"color": "#a78bfa", "symbol": "star", "size": 13},
                        hovertemplate="%{x|%Y-%m-%d}<br>%{text}<extra>成交</extra>",
                    ),
                    row=1,
                    col=1,
                )

    @staticmethod
    def _layout(figure: go.Figure, context: dict[str, Any], *, height: int) -> None:
        figure.update_layout(
            height=height,
            template="plotly_dark",
            paper_bgcolor="#07111f",
            plot_bgcolor="#0b1727",
            font={"color": "#eef5ff"},
            hovermode="x unified",
            hoversubplots="axis",
            legend={"orientation": "h", "y": 1.02, "x": 0},
            margin={"l": 70, "r": 24, "t": 42, "b": 40},
            xaxis_rangeslider_visible=False,
            uirevision=f'strategy-chart-{context["strategy"]["reference_id"]}',
        )
        figure.update_xaxes(gridcolor="#16283c", zerolinecolor="#20344b")
        figure.update_yaxes(gridcolor="#16283c", zerolinecolor="#20344b")
        figure.update_yaxes(title_text="后复权价格", row=1, col=1)

    def render_backtest(self, context: dict[str, Any]) -> str:
        panels = self.panels(context)
        figure, prices, _rows = self._base_figure(context, panels)
        self._events(figure, prices, context)
        self._layout(figure, context, height=700 if len(panels) == 1 else 780)
        account = _frame(context["execution"].get("account_daily", []), "date")
        initial = float(context["execution"]["initial_cash"])
        final = initial if account.empty else float(account.iloc[-1]["equity"])
        peak = account["equity"].cummax() if not account.empty else pd.Series([initial])
        drawdown = (
            (account["equity"] / peak - 1).min() if not account.empty else 0.0
        )
        window = context["window"]
        cards = [
            ("区间收益", f"{final / initial - 1:+.2%}"),
            ("最大回撤", f"{float(drawdown):.2%}"),
            ("交易日", str(len(prices))),
            ("区间", f'{window["evaluation_start"]} → {window["evaluation_end"]}'),
        ]
        return _shell(
            figure,
            context,
            cards=cards,
            title=f'{context["strategy"]["symbol"]} 策略回测',
        )
