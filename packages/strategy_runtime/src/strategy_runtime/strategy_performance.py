"""Opt-in CPU profiling and enforcement for the executable strategy contract."""

from dataclasses import dataclass
from math import isfinite
from time import thread_time_ns


@dataclass(frozen=True, slots=True)
class StrategyPerformanceBudget:
    """Calibrated limits for one strategy call and the mean CPU per 1,000 calls."""

    max_call_seconds: float | None = None
    max_seconds_per_1000_calls: float | None = None

    def __post_init__(self):
        for value in (self.max_call_seconds, self.max_seconds_per_1000_calls):
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or value <= 0):
                raise ValueError('strategy CPU limits require positive finite seconds')

    @property
    def enforces_limits(self):
        return self.max_call_seconds is not None or self.max_seconds_per_1000_calls is not None


@dataclass(frozen=True, slots=True)
class StrategyPerformanceStatistics:
    calls: int
    strategy_cpu_seconds: float
    custom_feature_cpu_seconds: float
    feature_graph_cpu_seconds: float
    peak_call_cpu_seconds: float
    prefix_calls: int
    prefix_strategy_cpu_seconds: float


class StrategyPerformanceExceeded(RuntimeError):
    """The measured strategy CPU cost exceeds its configured budget."""


class _StrategyPerformanceProbe:
    def __init__(self, budget: StrategyPerformanceBudget, points: int):
        self.budget = budget
        self.prefix_target = points // 2
        self.calls = self.strategy_ns = self.custom_ns = self.graph_ns = self.peak_ns = 0
        self.prefix_calls = self.prefix_ns = 0

    def strategy(self, function, *args):
        started = thread_time_ns()
        value = function(*args)
        elapsed = thread_time_ns() - started
        self.calls += 1
        self.strategy_ns += elapsed
        self.peak_ns = max(self.peak_ns, elapsed)
        if self.calls == self.prefix_target:
            self.prefix_calls, self.prefix_ns = self.calls, self.strategy_ns
        limit = self.budget.max_call_seconds
        if limit is not None and elapsed > limit * 1e9:
            raise StrategyPerformanceExceeded(f'strategy call {self.calls} used {elapsed / 1e9:.6f}s CPU, limit {limit:g}s')
        return value

    def feature(self, function, *args):
        started = thread_time_ns()
        value = function(*args)
        self.custom_ns += thread_time_ns() - started
        return value

    def graph(self, function, *args):
        started = thread_time_ns()
        value = function(*args)
        self.graph_ns += thread_time_ns() - started
        return value

    def finish(self):
        if self.budget.enforces_limits and not self.calls:
            raise StrategyPerformanceExceeded('no executed strategy calls for CPU qualification')
        limit = self.budget.max_seconds_per_1000_calls
        if self.calls and limit is not None:
            measured = self.strategy_ns / self.calls / 1e6
            if measured > limit:
                raise StrategyPerformanceExceeded(f'strategy used {measured:.6f}s CPU per 1,000 calls, limit {limit:g}s')
        return StrategyPerformanceStatistics(self.calls, self.strategy_ns / 1e9, self.custom_ns / 1e9,
            self.graph_ns / 1e9, self.peak_ns / 1e9, self.prefix_calls, self.prefix_ns / 1e9)
