"""SRT-28: bounded resources are validated before any host work."""

from dataclasses import FrozenInstanceError
import pytest
from strategy_runtime import ExecutionResources, InspectionControl, default_worker_count


def test_SRT_28_C01_default_cpu_budget_and_explicit_override(monkeypatch):
    monkeypatch.setattr("strategy_runtime.resources.os.cpu_count", lambda: 16)
    assert default_worker_count() == 12
    assert ExecutionResources().max_workers == InspectionControl().max_workers == 12
    explicit = ExecutionResources(max_workers=2, native_threads_per_worker=3, random_seed=7)
    assert (explicit.max_workers, explicit.native_threads_per_worker, explicit.random_seed) == (
        2,
        3,
        7,
    )
    with pytest.raises(FrozenInstanceError):
        explicit.max_workers = 4


def test_SRT_28_C02_unknown_cpu_requires_explicit_budget(monkeypatch):
    monkeypatch.setattr("strategy_runtime.resources.os.cpu_count", lambda: None)
    with pytest.raises(RuntimeError, match="specify max_workers explicitly"):
        ExecutionResources()
    with pytest.raises(RuntimeError, match="specify max_workers explicitly"):
        InspectionControl()
    assert (
        ExecutionResources(max_workers=3).max_workers
        == InspectionControl(max_workers=3).max_workers
        == 3
    )


@pytest.mark.parametrize(
    "workers",
    [
        False,
        0,
    ],
    ids=["SRT-28-C03", "SRT-28-C04"],
)
def test_worker_budget_is_a_positive_integer(workers):
    with pytest.raises(ValueError):
        ExecutionResources(max_workers=workers)


def test_SRT_28_C05_timeout_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        InspectionControl(max_workers=1, timeout_seconds=0)


def test_SRT_28_C06_callback_must_be_callable():
    with pytest.raises(TypeError, match="callable"):
        InspectionControl(max_workers=1, cancelled="cancel")
