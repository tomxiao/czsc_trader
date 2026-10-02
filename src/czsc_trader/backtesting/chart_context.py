"""Typed, detached plotting facts owned by TDR."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from numbers import Real

import pandas as pd

from .execution_data import BacktestExecutionData
from .result import BacktestResult
from .signal_replay import SignalReplay


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"chart {name} must be finite numeric data")
    return float(value)


@dataclass(frozen=True)
class ChartBar:
    session: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ChartSignal:
    decision_id: str
    signal_date: date
    valid_session: date
    target_position: float
    action: str
    values: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ChartFill:
    fill_id: str
    decision_id: str
    time: datetime
    side: str
    quantity: int
    price: float
    fees: float


@dataclass(frozen=True)
class ChartAccount:
    session: date
    quantity: int
    equity: float


@dataclass(frozen=True)
class ChartBenchmark:
    name: str
    equity: tuple[float, ...]


@dataclass(frozen=True)
class BacktestChartContext:
    reference: str
    identity_hash: str
    market_identity: str
    symbol: str
    start: date
    end: date
    initial_cash: float
    bars: tuple[ChartBar, ...]
    signals: tuple[ChartSignal, ...]
    fills: tuple[ChartFill, ...]
    accounts: tuple[ChartAccount, ...]
    benchmarks: tuple[ChartBenchmark, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(x, str) and x for x in (
            self.reference, self.identity_hash, self.market_identity, self.symbol,
        )):
            raise ValueError("chart identity is incomplete")
        if any(len(x) != 64 or any(c not in "0123456789abcdef" for c in x)
               for x in (self.identity_hash, self.market_identity)):
            raise ValueError("chart identities must be SHA-256 values")
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("chart window requires dates")
        if self.start > self.end or _number(self.initial_cash, "initial_cash") <= 0:
            raise ValueError("chart window or initial cash is invalid")
        for field, kind in (("bars", ChartBar), ("signals", ChartSignal), ("fills", ChartFill),
                            ("accounts", ChartAccount), ("benchmarks", ChartBenchmark)):
            values = getattr(self, field)
            if type(values) is not tuple or any(not isinstance(x, kind) for x in values):
                raise TypeError(f"chart {field} requires a tuple of {kind.__name__}")
        sessions = tuple(x.session for x in self.bars)
        if any(type(x) is not date for x in sessions):
            raise TypeError("chart bars require session dates")
        if (not sessions or sessions != tuple(sorted(set(sessions)))
                or sessions[0] != self.start or sessions[-1] != self.end):
            raise ValueError("chart bars must uniquely cover the evaluation window")
        for bar in self.bars:
            for field in ("open", "high", "low", "close"):
                if _number(getattr(bar, field), field) <= 0:
                    raise ValueError("chart prices must be positive")
            if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                raise ValueError("chart OHLC is invalid")
        if tuple(x.session for x in self.accounts) != sessions:
            raise ValueError("chart account sessions differ from market sessions")
        for account in self.accounts:
            if type(account.quantity) is not int or account.quantity < 0:
                raise ValueError("chart account quantity is invalid")
            if _number(account.equity, "equity") < 0:
                raise ValueError("chart equity must be nonnegative")
        decisions = {x.decision_id: x for x in self.signals}
        if len(decisions) != len(self.signals):
            raise ValueError("chart decision IDs must be unique")
        for signal in self.signals:
            if type(signal.signal_date) is not date or type(signal.valid_session) is not date:
                raise TypeError("chart signals require session dates")
            if (not signal.decision_id or not signal.action or signal.valid_session not in sessions
                    or signal.signal_date >= signal.valid_session
                    or not 0 <= _number(signal.target_position, "target_position") <= 1):
                raise ValueError("chart signal identity, timing or target is invalid")
            if type(signal.values) is not tuple:
                raise TypeError("chart signal values must be a tuple")
            if len({key for key, _ in signal.values}) != len(signal.values):
                raise ValueError("chart signal fields must be unique")
            for key, value in signal.values:
                if not isinstance(key, str) or not key:
                    raise ValueError("chart signal field name is invalid")
                _number(value, key)
        if len({x.fill_id for x in self.fills}) != len(self.fills):
            raise ValueError("chart fill IDs must be unique")
        for fill in self.fills:
            if type(fill.time) is not datetime:
                raise TypeError("chart fills require timestamps")
            if (not fill.fill_id or fill.side not in {"BUY", "SELL"}
                    or fill.decision_id not in decisions or fill.time.date() not in sessions
                    or fill.time.date() != decisions[fill.decision_id].valid_session
                    or type(fill.quantity) is not int or fill.quantity <= 0
                    or _number(fill.price, "fill price") <= 0
                    or _number(fill.fees, "fees") < 0):
                raise ValueError("chart fill identity, session or execution value is invalid")
        if len({x.name for x in self.benchmarks}) != len(self.benchmarks):
            raise ValueError("chart benchmark names must be unique")
        for benchmark in self.benchmarks:
            if not benchmark.name or type(benchmark.equity) is not tuple or len(benchmark.equity) != len(sessions):
                raise ValueError("chart benchmark is incomplete")
            for value in benchmark.equity:
                if _number(value, "benchmark equity") < 0:
                    raise ValueError("chart benchmark equity must be nonnegative")


def _session(value: object) -> date:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("chart session is missing")
    return timestamp.date()


def _quantity(value: object) -> int:
    number = _number(value, "quantity")
    if not number.is_integer():
        raise ValueError("chart quantity must be integral")
    return int(number)


def build_backtest_chart_context(
    signal_replay: SignalReplay,
    execution_data: BacktestExecutionData,
    result: BacktestResult,
    initial_cash: float,
    *,
    benchmark_accounts: tuple[tuple[str, pd.DataFrame], ...] = (),
) -> BacktestChartContext:
    """Project audited facts without recomputing strategy or executions."""
    if result.identity != signal_replay.snapshot.identity:
        raise ValueError("chart result identity differs from signal replay")
    start, end = signal_replay.evaluation_start.date(), signal_replay.evaluation_end.date()
    prices = execution_data.adjusted_daily.copy()
    if "dt" in prices:
        prices = prices.set_index("dt")
    prices.index = pd.DatetimeIndex(pd.to_datetime(prices.index))
    prices = prices.loc[pd.Timestamp(start):pd.Timestamp(end)]
    bars = tuple(ChartBar(_session(day), *(_number(row[key], key) for key in ("open", "high", "low", "close")))
                 for day, row in prices.iterrows())
    excluded = {"decision_id", "signal_date", "valid_session", "target_position", "plan_mode", "action"}
    signals = tuple(ChartSignal(
        str(row["decision_id"]), _session(row["signal_date"]), _session(row["valid_session"]),
        _number(row["target_position"], "target_position"), str(row["action"]),
        tuple((str(key), _number(value, str(key))) for key, value in row.items()
              if key not in excluded and isinstance(value, Real) and not isinstance(value, bool)),
    ) for row in result.decisions.to_dict("records"))
    fills = tuple(ChartFill(
        str(row["fill_id"]), str(row["decision_id"]), pd.Timestamp(row["fill_time"]).to_pydatetime(),
        str(row["side"]), _quantity(row["quantity"]), _number(row["price"], "price"),
        _number(row["fees"], "fees"),
    ) for row in result.fills.to_dict("records"))
    accounts = tuple(ChartAccount(_session(row["date"]), _quantity(row["quantity"]),
                                 _number(row["equity"], "equity"))
                     for row in result.account_daily.to_dict("records"))
    benchmarks = []
    for name, frame in benchmark_accounts:
        if tuple(_session(x) for x in frame["date"]) != tuple(x.session for x in bars):
            raise ValueError("chart benchmark sessions differ from market sessions")
        benchmarks.append(ChartBenchmark(name, tuple(_number(x, "benchmark equity") for x in frame["equity"])))
    return BacktestChartContext(
        result.identity.reference, signal_replay.snapshot.source_hash, execution_data.fingerprint,
        execution_data.symbol, start, end, initial_cash, bars, signals, fills, accounts,
        tuple(benchmarks),
    )
