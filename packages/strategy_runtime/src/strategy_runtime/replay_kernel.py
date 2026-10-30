"""Shared account lifecycle; market clocks and execution models supply facts.

Only drivers own transactional policy. A confirmed partial execution must never
be rolled back merely because a later execution leg fails.
"""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Protocol, TypeVar

Tick = TypeVar("Tick")
Snapshot = TypeVar("Snapshot")
Plan = TypeVar("Plan")
Outcome = TypeVar("Outcome")
Result = TypeVar("Result")


class ReplayDriver(Protocol[Tick, Snapshot, Plan, Outcome, Result]):
    def transaction(self, tick: Tick) -> AbstractContextManager: ...
    def snapshot(self, tick: Tick) -> Snapshot: ...
    def decide(self, tick: Tick, before: Snapshot) -> Plan: ...
    def execute(self, tick: Tick, plan: Plan) -> Outcome: ...
    def commit(self, tick: Tick, before: Snapshot, plan: Plan, after: Outcome) -> None: ...
    def failure(self, tick: Tick, error: Exception) -> Exception: ...
    def finish(self) -> Result: ...


def run_account_replay(points: Iterable[Tick], driver: ReplayDriver[Tick, Snapshot, Plan, Outcome, Result]) -> Result:
    """Advance one account, committing strategy state after confirmed execution.

Inputs are streamed, never materialized or copied per step. Bind methods once
outside the hot loop; no source/data IO, market dispatch or serialization occurs
in this kernel. An exception prevents successful account finalization.
    """
    transaction, snapshot, decide = driver.transaction, driver.snapshot, driver.decide
    execute, commit, failure = driver.execute, driver.commit, driver.failure
    for tick in points:
        try:
            with transaction(tick):
                before = snapshot(tick)
                plan = decide(tick, before)
                after = execute(tick, plan)
                commit(tick, before, plan, after)
        except Exception as error:
            raised = failure(tick, error)
            if raised is error:
                raise
            raise raised from error
    return driver.finish()
