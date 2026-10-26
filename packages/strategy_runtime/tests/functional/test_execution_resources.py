"""The public execution budget uses the same explicit policy across hosts."""
from dataclasses import FrozenInstanceError

import pytest

from strategy_runtime import ExecutionResources, InspectionControl, default_worker_count


@pytest.mark.parametrize("logical,expected", [(1, 1), (2, 1), (3, 2), (8, 6), (16, 12), (32, 24)])
def test_default_budget_uses_seventy_five_percent_of_logical_cpus(monkeypatch, logical, expected):
    monkeypatch.setattr("strategy_runtime.resources.os.cpu_count", lambda: logical)
    assert default_worker_count() == expected
    assert ExecutionResources().max_workers == expected
    assert InspectionControl().max_workers == expected
    assert ExecutionResources().native_threads_per_worker == 1


@pytest.mark.parametrize("logical", [None, 0, -1, True, 1.5])
def test_unavailable_cpu_count_requires_explicit_budget(monkeypatch, logical):
    monkeypatch.setattr("strategy_runtime.resources.os.cpu_count", lambda: logical)
    with pytest.raises(RuntimeError, match="specify max_workers explicitly"):
        ExecutionResources()
    with pytest.raises(RuntimeError, match="specify max_workers explicitly"):
        InspectionControl()
    assert ExecutionResources(max_workers=3).max_workers == 3
    assert InspectionControl(max_workers=3).max_workers == 3


@pytest.mark.parametrize("kwargs", [
    {"max_workers": 0}, {"max_workers": True}, {"max_workers": 2.5},
    {"native_threads_per_worker": -1}, {"native_threads_per_worker": False},
    {"random_seed": -1}, {"random_seed": True},
])
def test_execution_budget_rejects_invalid_resource_values(kwargs):
    with pytest.raises(ValueError):
        ExecutionResources(**kwargs)


def test_execution_budget_is_explicit_and_immutable(monkeypatch):
    monkeypatch.setattr("strategy_runtime.resources.os.cpu_count", lambda: 16)
    resources = ExecutionResources(max_workers=2, native_threads_per_worker=3, random_seed=7)
    assert (resources.max_workers, resources.native_threads_per_worker, resources.random_seed) == (2, 3, 7)
    with pytest.raises(FrozenInstanceError):
        resources.max_workers = 4
