"""Strategy-independent market data for PTE observation charts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from dataflows import (
    BarFrequency, DataError, DataRequest, Dataflows, Dataset, EquityDataRequest,
    EquityProduct, EquityQuery, PreparePolicy, PriceAdjustment, canonical_frame_sha256,
)
from dataflows.equity_data import sessions_from_metadata
import pandas as pd

from execution_channels.futu.trading_window import SHANGHAI, shanghai_now
from .scheduling_contracts import DAILY_CLOSE_DELAY


LEGACY_CHART_UPDATE_TIME = time(20)  # The legacy CN date-only calendar uses the regular 15:00 close.


def _chart_ready_at(session, calendar_available):
    return max(session.segments[-1].end + DAILY_CLOSE_DELAY, calendar_available)


class AccountChartDataError(ValueError):
    """Readable chart failure retaining the original DFLS evidence."""

    def __init__(self, request: DataRequest, error: DataError) -> None:
        self.request, self.data_error = request, error
        label = "交易日历" if request.dataset == Dataset.TRADING_CALENDAR else "图表行情"
        context = error.context
        if error.code == "INCOMPLETE_DATA":
            reason = "数据不完整"
        elif error.code == "EMPTY_DATA":
            reason = "数据源未返回数据"
        elif error.code == "SOURCE_NOT_READY":
            reason = "数据源尚未就绪"
        else:
            reason = f"数据读取失败：{error.message}"
        message = f"{label}不可用：{request.symbol}，{reason}"
        if request.required_cutoff:
            message += f"；要求截至 {request.required_cutoff}"
        if context.get("actual_cutoff"):
            message += f"，实际截至 {str(context['actual_cutoff'])[:10]}"
        if context.get("missing_dates"):
            dates = list(context["missing_dates"])
            message += f"；缺失交易日：{', '.join(str(day) for day in dates[:5])}"
            if len(dates) > 5:
                message += f"等 {len(dates)} 日"
        message += f"（{error.code}）"
        super().__init__(message)


class AccountChartMarketData:
    """Read adjusted daily bars without creating or inspecting a strategy instance."""

    def __init__(
        self,
        *,
        dataflows: Dataflows,
        now: Callable[[], datetime] = shanghai_now,
        formal_inputs=None,
    ) -> None:
        self.dataflows = dataflows
        self.now = now
        self.formal_inputs = formal_inputs

    def _formal_calendar(self, inputs, start, end):
        parameters = dict(inputs.binding.request_bindings)["sessions"]
        request = EquityDataRequest(parameters.instrument, parameters.source,
                                    EquityQuery(EquityProduct.SESSIONS, start, end,
                                                session=parameters.query.session))
        result = self._fetch(request, PreparePolicy.REUSE)
        availability = {str(row.SessionDate): row.AvailableDate for row in result.dataframe.itertuples()}
        return tuple((session, availability[session.session_date.isoformat()])
                     for session in sessions_from_metadata(result.identity.metadata))

    def scheduled_session_ready(self, account_id: str, at: datetime) -> bool | None:
        """Return None on non-session days and False before the chart refresh window."""
        inputs = self.formal_inputs(account_id)
        zone = ZoneInfo(inputs.binding.instrument.timezone)
        day = at.astimezone(zone).date()
        for session, available in self._formal_calendar(inputs, day - timedelta(days=14), day):
            if session.session_date == day:
                return at >= _chart_ready_at(session, available)
        return None

    def _formal_history(self, account_id, cutoff, context_sessions, refresh_source):
        inputs = self.formal_inputs(account_id)
        zone = ZoneInfo(inputs.binding.instrument.timezone)
        now = self.now()
        if now.utcoffset() is None:
            raise ValueError("account chart clock must be timezone-aware")
        day = now.astimezone(zone).date()
        start = cutoff - timedelta(days=max(180, context_sessions * 3))
        completed = [session.session_date for session, available in self._formal_calendar(inputs, start, day)
                      if _chart_ready_at(session, available) <= now]
        if not completed or completed[-1] < cutoff:
            raise ValueError("account selection cutoff exceeds the latest completed trading session")
        parameters = dict(inputs.binding.request_bindings)["bars"]
        request = EquityDataRequest(parameters.instrument, parameters.source,
            EquityQuery(EquityProduct.BARS, start, completed[-1], BarFrequency.DAILY,
                        PriceAdjustment.BACKWARD, parameters.query.session))
        frame = self._read(request, PreparePolicy.REFRESH if refresh_source else PreparePolicy.REUSE)
        frame = frame.loc[pd.to_datetime(frame["AvailableDate"], utc=True) <= now].copy()
        if frame.empty:
            raise ValueError("截至当前时点还没有可用的图表行情")
        identity = canonical_frame_sha256(frame)
        frame["Date"] = pd.to_datetime(frame["Date"], utc=True).dt.tz_convert(zone).dt.date
        if frame["Date"].max() < cutoff:
            raise ValueError("已发布图表行情尚未覆盖策略选择截止日")
        return identity, frame

    def is_trading_day(self, *, symbol: str, session: date) -> bool:
        """Use the symbol's exchange calendar to admit a scheduled update."""
        exchange = {"SH": "SSE", "SZ": "SZSE"}.get(symbol.upper().rsplit(".", 1)[-1])
        if exchange is None:
            raise ValueError("account chart symbol must identify an SH or SZ exchange")
        day = session.isoformat()
        frame = self._read(DataRequest(
            Dataset.TRADING_CALENDAR, exchange, day, day, day, "daily",
        ), PreparePolicy.REUSE)
        flags = frame.loc[pd.to_datetime(frame["Date"]).dt.date.eq(session), "IsOpen"]
        if len(flags) != 1 or flags.iloc[0] not in (0, 1):
            raise ValueError(f"交易日历不可用：{symbol}，{day} 的开市标记缺失或非法")
        return bool(flags.iloc[0])

    def history(
        self,
        *,
        symbol: str,
        asset: str,
        selection_data_cutoff: str,
        context_sessions: int,
        refresh_source: bool = False,
        account_id: str | None = None,
    ) -> tuple[str, object]:
        normalized_asset = asset.lower()
        if normalized_asset not in {"stock", "etf"}:
            raise ValueError("account chart asset must be stock or etf")
        cutoff = date.fromisoformat(selection_data_cutoff)
        if account_id is not None:
            if self.formal_inputs is None:
                raise ValueError("formal chart data binding is unavailable")
            return self._formal_history(account_id, cutoff, context_sessions, refresh_source)
        moment = self.now()
        if moment.tzinfo is None:
            raise ValueError("account chart clock must be timezone-aware")
        moment = moment.astimezone(SHANGHAI)
        start = cutoff - timedelta(days=max(180, context_sessions * 3))
        policy = PreparePolicy.REFRESH if refresh_source else PreparePolicy.REUSE
        symbol = symbol.upper()
        exchange = {"SH": "SSE", "SZ": "SZSE"}.get(symbol.rsplit(".", 1)[-1])
        if exchange is None:
            raise ValueError("account chart symbol must identify an SH or SZ exchange")
        calendar = self._read(DataRequest(
            Dataset.TRADING_CALENDAR, exchange, start.isoformat(),
            moment.date().isoformat(), moment.date().isoformat(), "daily",
        ), policy)
        sessions = pd.to_datetime(calendar.loc[calendar["IsOpen"].eq(1), "Date"]).dt.date
        sessions = sessions[sessions <= moment.date()] if moment.time() >= LEGACY_CHART_UPDATE_TIME else sessions[sessions < moment.date()]
        if sessions.empty:
            raise ValueError("account chart calendar has no completed trading session")
        end = sessions.iloc[-1]
        if cutoff > end:
            raise ValueError("account selection cutoff exceeds the latest completed trading session")
        dataset = Dataset.ETF_OHLCV if normalized_asset == "etf" else Dataset.STOCK_OHLCV
        request = DataRequest(
            dataset,
            symbol,
            start.isoformat(),
            end.isoformat(),
            end.isoformat(),
            "daily",
        )
        frame = self._read(request, policy)
        return canonical_frame_sha256(frame), frame

    def _fetch(self, request: DataRequest, policy: PreparePolicy):
        prepared = self.dataflows.prepare((request,), policy=policy)
        if not prepared.ready:
            item = prepared.items[0]
            error = item.error or DataError(str(item.status), "数据准备未完成")
            raise AccountChartDataError(request, error)
        result = self.dataflows.fetch(request, prepared=prepared.reference)
        if not result.ready:
            error = result.error or DataError(str(result.status), "数据读取未完成")
            raise AccountChartDataError(request, error)
        return result

    def _read(self, request: DataRequest, policy: PreparePolicy) -> pd.DataFrame:
        result = self._fetch(request, policy)
        frame = result.dataframe.copy()
        if frame.empty:
            raise ValueError("account chart market data is empty")
        return frame
