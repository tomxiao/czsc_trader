from datetime import date, datetime
from threading import Event, Thread
import time
from types import SimpleNamespace

import pytest
from scheduler_support import Engine, Store, _account

from paper_trading_engine.account_data_preparer import (
    AccountDataPreparer,
)
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.scheduler import RuntimeScheduler
from execution_channels.futu.trading_window import SHANGHAI


def _scheduler(engine, prepared_data, store, **kwargs):
    cycle = AccountStrategyCycle(engine, prepared_data, store)
    return RuntimeScheduler(engine, cycle, store, **kwargs)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _prepared(
    release_id="S007-v1",
    signal_date=date(2026, 9, 18),
    identity="a" * 64,
):
    return SimpleNamespace(
        strategy=SimpleNamespace(reference_id=release_id, release_hash="b" * 64),
        tradable_window=SimpleNamespace(
            start=date(2026, 9, 21), end=date(2026, 9, 21)
        ),
        available_through=signal_date,
        data_identity=identity,
        data_reference={"space_id": "11111111-1111-1111-1111-111111111111",
                        "preparation_id": "22222222-2222-2222-2222-222222222222",
                        "manifest_sha256": "a" * 64},
    )




class Advice:
    def __init__(self):
        self.calls = []
        self.results = {}

    def prepare_account_data(self, **kwargs):
        self.calls.append(kwargs)
        account_id = kwargs["account_id"]
        if account_id in self.results:
            result = self.results[account_id]
            if isinstance(result, Exception):
                raise result
            return result
        return _prepared(
            f"{kwargs['strategy_id']}-{kwargs['strategy_version']}",
            kwargs["signal_date"],
        )

    def latest_completed_signal_date(self, at):
        self.calls.append(("latest", at))
        return date(2026, 9, 18)


# Independent risk: PTE06; responsibility-level assertions.
def test_PTE06_C02_paused_manual_cycle_does_not_even_resolve_data_date():
    store = Store()
    store.accounts = [_account(run_state="PAUSED")]
    cycle = AccountStrategyCycle(None, None, store)
    with pytest.raises(ValueError, match="running account"):
        cycle.run_latest("s007-v1", observed_at=datetime(2026, 9, 18, 20, 30, tzinfo=SHANGHAI))


# Independent risk: PTE07; responsibility-level assertions.
def test_PTE07_C04_scheduler_revalidates_prepared_data_before_retrying_decision():
    store, engine, advice = Store(), Engine(), Advice()
    store.accounts = [_account(), _account("s003-v1", strategy_id="S003")]
    engine.failures["s007-v1"] = RuntimeError("decision failed")
    scheduler = _scheduler(
        engine,
        AccountDataPreparer(advice=advice),
        store,
        preparation_time="00:00",
    )
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 30))
    _wait_until(
        lambda: "account_strategy_cycle:s007-v1" in store.failures
        and store.values.get("last_account_decision_date:s003-v1") == "2026-09-18"
    )
    assert store.values["last_data_prepare_date:s007-v1"] == "2026-09-18"
    assert "last_account_decision_date:s007-v1" not in store.values
    assert store.values["last_account_decision_date:s003-v1"] == "2026-09-18"
    engine.failures.clear()
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 30, 5))
    _wait_until(lambda: len(engine.calls) == 3)
    assert len(advice.calls) == 3
    assert sorted(engine.calls) == [
        ("decision", "s003-v1"),
        ("decision", "s007-v1"),
        ("decision", "s007-v1"),
    ]


# Independent risk: PTE08; responsibility-level assertions.
def test_PTE08_C01_slow_preparation_does_not_stop_order_reconciliation(monkeypatch):
    entered, release, stopped = Event(), Event(), Event()
    reconciled = Event()

    class ReconciliationEngine(Engine):
        blocked_order_calls = 0

        def refresh_orders(self):
            super().refresh_orders()
            if entered.is_set() and not release.is_set():
                self.blocked_order_calls += 1
                if self.blocked_order_calls >= 2:
                    reconciled.set()

    class Preparer:
        def prepare(self, account, *, signal_date):
            del account, signal_date
            entered.set()
            assert release.wait(5)
            raise RuntimeError("test stop")

    engine, store = ReconciliationEngine(), Store()
    store.accounts = [_account()]
    scheduler = _scheduler(
        engine,
        Preparer(),
        store,
        order_interval=0.01,
        account_interval=0.02,
        preparation_time="00:00",
    )
    tick_daily = scheduler.tick_daily
    monkeypatch.setattr(scheduler, "tick_daily", lambda _: tick_daily(
        datetime(2026, 9, 18, 20, 30, tzinfo=SHANGHAI)))
    worker = Thread(target=scheduler.run, args=(stopped,))
    worker.start()
    try:
        assert entered.wait(1), "account preparation did not start"
        assert reconciled.wait(2), "order reconciliation stopped during blocked preparation"
    finally:
        stopped.set()
        release.set()
        worker.join(2)
    assert not worker.is_alive()
