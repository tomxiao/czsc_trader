from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audit_models import ReturnMatrixEvidence
from .models import Record


@dataclass(frozen=True)
class PerformanceMetrics(Record):
    cagr: float
    max_drawdown: float
    calmar: float


@dataclass(frozen=True)
class BootstrapMetric(Record):
    metric: str
    direction: str
    point_difference: float
    lower_95: float
    upper_95: float
    probability_favorable: float


@dataclass(frozen=True)
class BootstrapComparison(Record):
    champion_id: str
    comparator_id: str
    repetitions: int
    mean_block_length: int
    cagr: BootstrapMetric
    max_drawdown: BootstrapMetric
    calmar: BootstrapMetric


@dataclass(frozen=True)
class BootstrapInterval(Record):
    metric: str
    point: float
    lower_90: float
    upper_90: float
    lower_95: float
    upper_95: float
    probability_above_zero: float


@dataclass(frozen=True)
class AbsoluteBootstrap(Record):
    candidate_id: str
    repetitions: int
    mean_block_length: int
    cagr: BootstrapInterval
    max_drawdown: BootstrapInterval
    calmar: BootstrapInterval


def performance_metrics(returns: np.ndarray) -> PerformanceMetrics:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < 2 or not np.isfinite(values).all():
        raise ValueError("performance returns must be a finite one-dimensional series")
    if np.any(values <= -1.0):
        raise ValueError("daily returns must be greater than -1")
    wealth = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(np.r_[1.0, wealth])
    drawdowns = np.r_[1.0, wealth] / peaks - 1.0
    maximum_drawdown = float(np.min(drawdowns))
    cagr = float(np.exp(np.log1p(values).sum() * 252.0 / len(values)) - 1.0)
    calmar = cagr / abs(maximum_drawdown) if maximum_drawdown < 0.0 else float("nan")
    return PerformanceMetrics(cagr, maximum_drawdown, float(calmar))


def _row_cagr(values: np.ndarray) -> np.ndarray:
    return np.exp(np.log1p(values).sum(axis=1) * 252.0 / values.shape[1]) - 1.0


def _row_metrics(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cagr = _row_cagr(values)
    wealth = np.cumprod(1.0 + values, axis=1)
    wealth = np.column_stack([np.ones(len(values)), wealth])
    peaks = np.maximum.accumulate(wealth, axis=1)
    drawdown = np.min(wealth / peaks - 1.0, axis=1)
    calmar = np.divide(
        cagr, np.abs(drawdown), out=np.full_like(cagr, np.nan), where=drawdown < 0.0,
    )
    return cagr, drawdown, calmar


def _summary(metric: str, point: float, values: np.ndarray) -> BootstrapMetric:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return BootstrapMetric(metric, "higher_is_better", point, float("nan"), float("nan"), float("nan"))
    lower, upper = np.quantile(finite, (0.025, 0.975))
    return BootstrapMetric(
        metric, "higher_is_better", point, float(lower), float(upper),
        float(np.mean(finite > 0.0) + 0.5 * np.mean(finite == 0.0)),
    )


def _interval(metric: str, point: float, values: np.ndarray) -> BootstrapInterval:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        missing = float("nan")
        return BootstrapInterval(metric, point, missing, missing, missing, missing, missing)
    lower_90, upper_90 = np.quantile(finite, (0.05, 0.95))
    lower_95, upper_95 = np.quantile(finite, (0.025, 0.975))
    return BootstrapInterval(
        metric,
        point,
        float(lower_90),
        float(upper_90),
        float(lower_95),
        float(upper_95),
        float(np.mean(finite > 0.0) + 0.5 * np.mean(finite == 0.0)),
    )


def stationary_bootstrap_performance(
    returns: np.ndarray,
    *,
    candidate_id: str,
    repetitions: int = 10_000,
    mean_block_length: int = 21,
    seed: int = 0,
) -> AbsoluteBootstrap:
    """Estimate absolute performance uncertainty with a stationary block bootstrap."""
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("absolute bootstrap returns must be finite and one-dimensional")
    if np.any(values <= -1.0):
        raise ValueError("daily returns must be greater than -1")
    if repetitions < 1 or mean_block_length < 1:
        raise ValueError("repetitions and mean block length must be positive")

    rng = np.random.default_rng(seed)
    samples = [[], [], []]
    chunk_size = min(256, repetitions)
    for start in range(0, repetitions, chunk_size):
        count = min(chunk_size, repetitions - start)
        indices = np.empty((count, len(values)), dtype=np.int32)
        indices[:, 0] = rng.integers(0, len(values), size=count)
        for column in range(1, len(values)):
            restart = rng.random(count) < 1.0 / mean_block_length
            indices[:, column] = np.where(
                restart,
                rng.integers(0, len(values), size=count),
                (indices[:, column - 1] + 1) % len(values),
            )
        for metric_index, metric_values in enumerate(_row_metrics(values[indices])):
            samples[metric_index].append(metric_values)

    arrays = tuple(np.concatenate(parts) for parts in samples)
    point = performance_metrics(values)
    intervals = tuple(
        _interval(name, value, distribution)
        for name, value, distribution in zip(
            ("cagr", "max_drawdown", "calmar"),
            (point.cagr, point.max_drawdown, point.calmar),
            arrays,
            strict=True,
        )
    )
    return AbsoluteBootstrap(
        candidate_id,
        repetitions,
        mean_block_length,
        intervals[0],
        intervals[1],
        intervals[2],
    )


def _paired_returns(champion_returns, comparator_returns, repetitions, mean_block_length):
    champion = np.asarray(champion_returns, dtype=float)
    comparator = np.asarray(comparator_returns, dtype=float)
    if champion.shape != comparator.shape or champion.ndim != 1 or len(champion) < 2:
        raise ValueError("paired returns must be aligned one-dimensional series")
    if not np.isfinite(champion).all() or not np.isfinite(comparator).all():
        raise ValueError("paired returns must be finite")
    if np.any(champion <= -1.0) or np.any(comparator <= -1.0):
        raise ValueError("daily returns must be greater than -1")
    if repetitions < 1 or mean_block_length < 1:
        raise ValueError("repetitions and mean block length must be positive")
    return champion, comparator


def _paired_sample_indices(observations, repetitions, mean_block_length, seed):
    """Retain the original chunk boundaries and all stationary-bootstrap RNG draws."""
    rng = np.random.default_rng(seed)
    chunk_size = min(256, repetitions)
    for start in range(0, repetitions, chunk_size):
        count = min(chunk_size, repetitions - start)
        indices = np.empty((count, observations), dtype=np.int32)
        indices[:, 0] = rng.integers(0, observations, size=count)
        for column in range(1, observations):
            restart = rng.random(count) < 1.0 / mean_block_length
            indices[:, column] = np.where(
                restart, rng.integers(0, observations, size=count),
                (indices[:, column - 1] + 1) % observations,
            )
        yield indices


def _paired_stationary_bootstrap_cagr(
    champion_returns: np.ndarray,
    comparator_returns: np.ndarray,
    *,
    repetitions: int = 10_000,
    mean_block_length: int = 21,
    seed: int = 0,
) -> BootstrapMetric:
    """Compute the stage-four CAGR summary without sampled drawdown or Calmar arrays."""
    champion, comparator = _paired_returns(
        champion_returns, comparator_returns, repetitions, mean_block_length,
    )
    differences = []
    for indices in _paired_sample_indices(len(champion), repetitions, mean_block_length, seed):
        differences.append(_row_cagr(champion[indices]) - _row_cagr(comparator[indices]))
    point = performance_metrics(champion).cagr - performance_metrics(comparator).cagr
    return _summary("cagr", point, np.concatenate(differences))


def paired_stationary_bootstrap(
    champion_returns: np.ndarray,
    comparator_returns: np.ndarray,
    *,
    champion_id: str,
    comparator_id: str,
    repetitions: int = 10_000,
    mean_block_length: int = 21,
    seed: int = 0,
) -> BootstrapComparison:
    champion, comparator = _paired_returns(
        champion_returns, comparator_returns, repetitions, mean_block_length,
    )
    champion_metrics = [[], [], []]
    comparator_metrics = [[], [], []]
    for indices in _paired_sample_indices(len(champion), repetitions, mean_block_length, seed):
        for target, values in ((champion_metrics, champion[indices]), (comparator_metrics, comparator[indices])):
            computed = _row_metrics(values)
            for metric_index, metric_values in enumerate(computed):
                target[metric_index].append(metric_values)

    champion_arrays = tuple(np.concatenate(parts) for parts in champion_metrics)
    comparator_arrays = tuple(np.concatenate(parts) for parts in comparator_metrics)
    differences = tuple(left - right for left, right in zip(champion_arrays, comparator_arrays, strict=True))
    point_left = performance_metrics(champion)
    point_right = performance_metrics(comparator)
    points = (
        point_left.cagr - point_right.cagr,
        point_left.max_drawdown - point_right.max_drawdown,
        point_left.calmar - point_right.calmar,
    )
    summaries = tuple(
        _summary(name, point, values)
        for name, point, values in zip(("cagr", "max_drawdown", "calmar"), points, differences, strict=True)
    )
    return BootstrapComparison(
        champion_id, comparator_id, repetitions, mean_block_length,
        summaries[0], summaries[1], summaries[2],
    )


def audit_pairwise_bootstrap(
    evidence: ReturnMatrixEvidence,
    champion_id: str,
    incumbent_id: str,
    peer_ids: tuple[str, ...],
    *,
    repetitions: int = 10_000,
    block_lengths: tuple[int, ...] = (21, 10, 42),
    seed: int = 0,
) -> tuple[BootstrapComparison, ...]:
    values = np.asarray(evidence.returns, dtype=float)
    expected = (len(evidence.dates), len(evidence.candidate_ids))
    if values.shape != expected or not np.isfinite(values).all():
        raise ValueError("comparison return matrix is invalid")
    locations = {candidate_id: index for index, candidate_id in enumerate(evidence.candidate_ids)}
    comparators = (incumbent_id, *peer_ids)
    missing = {champion_id, *comparators} - set(locations)
    if missing:
        raise ValueError(f"comparison return matrix is missing {sorted(missing)}")
    rows: list[BootstrapComparison] = []
    for comparator_index, comparator_id in enumerate(comparators):
        for block_length in block_lengths:
            rows.append(paired_stationary_bootstrap(
                values[:, locations[champion_id]], values[:, locations[comparator_id]],
                champion_id=champion_id, comparator_id=comparator_id,
                repetitions=repetitions, mean_block_length=block_length,
                seed=seed + comparator_index * 1009 + block_length,
            ))
    return tuple(rows)
