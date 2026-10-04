from datetime import date, datetime
import json
from threading import Event, Thread
import time
from types import SimpleNamespace

import pytest

from paper_trading_engine.account_data_preparer import (
    AccountDataPreparationError,
    AccountDataPreparer,
)
from paper_trading_engine.account_strategy_cycle import AccountStrategyCycle
from paper_trading_engine.audit import AuditRecorder
from paper_trading_engine.scheduler import RuntimeScheduler


class Engine:
    def __init__(self):
        self.calls = []
        self.failures = {}

    def refresh_orders(self):
        self.calls.append("orders")

    def refresh_account(self, account_id=None, *, prepared=None):
        if account_id is None:
            self.calls.append("account")
            return
        self.calls.append(("decision", account_id))
        error = self.failures.get(account_id)
        if error is not None:
            raise error

    def refresh_decisions(self):
        self.calls.append("decisions")

    def refresh_decision(self, account_id):
        self.calls.append(("decision", account_id))
        error = self.failures.get(account_id)
        if error is not None:
            raise error


class Store:
    def __init__(self):
        self.values, self.events, self.failures, self.audit_events = {}, [], {}, []
        self.accounts = []

    def get_setting(self, key):
        return self.values.get(key)

    def set_setting(self, key, value):
        self.values[key] = value

    def add_event(self, kind, payload):
        self.events.append((kind, payload))

    def set_operation_failure(self, operation, payload):
        self.failures[operation] = payload

    def clear_operation_failure(self, operation):
        self.failures.pop(operation, None)

    def operation_failures(self):
        return [{"operation": key, **value} for key, value in self.failures.items()]

    def append_audit_event(self, event):
        value = event.to_dict()
        self.audit_events.append(value)
        return value

    def strategy_virtual_accounts(self):
        return [a for a in self.accounts if a.get("account_type", "STRATEGY") == "STRATEGY"]

    def virtual_account(self, account_id):
        return next(a for a in self.accounts if a["account_id"] == account_id)


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


def _account(account_id="s007-v1", **overrides):
    value = {
        "account_id": account_id,
        "symbol": "588080.SH",
        "asset_type": "etf",
        "status": "RUNNING",
        "strategy_id": "S007",
        "strategy_version": "v1",
        "release_hash": "b" * 64,
        "last_decision_payload": json.dumps({"signal_date": "2026-09-17"}),
    }
    value.update(overrides)
    return value


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


def test_account_data_preparer_delegates_one_account_to_srt():
    advice = Advice()
    result = AccountDataPreparer(advice=advice).prepare(
        _account(), signal_date=date(2026, 9, 18)
    )
    assert result.data_identity == "a" * 64
    assert advice.calls == [{
        "account_id": "s007-v1",
        "strategy_id": "S007",
        "strategy_version": "v1",
        "symbol": "588080.SH",
        "asset": "etf",
        "signal_date": date(2026, 9, 18),
    }]


def test_account_data_preparer_rejects_wrong_release():
    advice = Advice()
    advice.results["s007-v1"] = _prepared("S003-v1")
    with pytest.raises(AccountDataPreparationError, match="another strategy"):
        AccountDataPreparer(advice=advice).prepare(
            _account(), signal_date=date(2026, 9, 18)
        )


def test_operator_cycle_derives_date_prepares_then_drives_decision():
    trace = []
    store = Store()
    store.accounts = [_account()]

    class Preparer:
        @staticmethod
        def latest_completed_signal_date(at):
            trace.append(("date", at))
            return date(2026, 9, 18)

        @staticmethod
        def prepare(account, *, signal_date):
            trace.append(("prepare", account["account_id"], signal_date))
            return _prepared(signal_date=signal_date)

    class Accounts:
        @staticmethod
        def drive_account_decision(account_id, *, prepared):
            trace.append(("decide", account_id, prepared.data_identity))
            return "decision-result"

    observed_at = datetime(2026, 9, 19, 8, 0)
    result = AccountStrategyCycle(Accounts(), Preparer(), store).run_latest(
        "s007-v1", observed_at=observed_at
    )

    assert result == "decision-result"
    assert trace == [
        ("date", observed_at),
        ("prepare", "s007-v1", date(2026, 9, 18)),
        ("decide", "s007-v1", "a" * 64),
    ]
    assert store.values["last_data_prepare_date:s007-v1"] == "2026-09-18"
    assert store.values["last_account_decision_date:s007-v1"] == "2026-09-18"


def test_scheduler_prepares_then_decides_each_account_after_2030():
    store, engine, advice = Store(), Engine(), Advice()
    store.accounts = [_account(), _account("s003-v1", strategy_id="S003")]
    scheduler = _scheduler(
        engine,
        AccountDataPreparer(advice=advice),
        store,
        preparation_time="20:30",
        audit=AuditRecorder(store),
    )
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 29, 59))
    assert advice.calls == []
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 30))
    _wait_until(lambda: len(engine.calls) == 2)
    assert [item["account_id"] for item in advice.calls] == ["s007-v1", "s003-v1"]
    assert engine.calls == [
        ("decision", "s007-v1"),
        ("decision", "s003-v1"),
    ]
    assert store.values["last_account_decision_date:s007-v1"] == "2026-09-18"
    assert store.values["last_account_decision_date:s003-v1"] == "2026-09-18"
    assert [e["account_id"] for e in store.audit_events] == ["s007-v1", "s003-v1"]


def test_scheduler_account_failure_does_not_block_other_account_and_retries():
    store, engine, advice = Store(), Engine(), Advice()
    store.accounts = [_account(), _account("s003-v1", strategy_id="S003")]
    advice.results["s007-v1"] = RuntimeError("source not ready")
    scheduler = _scheduler(
        engine,
        AccountDataPreparer(advice=advice),
        store,
        preparation_time="00:00",
    )
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 30))
    _wait_until(
        lambda: "account_strategy_cycle:s007-v1" in store.failures
        and len(engine.calls) == 1
    )
    assert engine.calls == [("decision", "s003-v1")]
    assert "account_strategy_cycle:s007-v1" in store.failures
    assert store.values["last_account_decision_date:s003-v1"] == "2026-09-18"

    advice.results["s007-v1"] = _prepared()
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 30, 5))
    _wait_until(lambda: len(engine.calls) == 2)
    assert engine.calls[-1] == ("decision", "s007-v1")
    assert "account_strategy_cycle:s007-v1" not in store.failures


def test_scheduler_revalidates_prepared_data_before_retrying_decision():
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
    assert engine.calls == [
        ("decision", "s007-v1"),
        ("decision", "s003-v1"),
        ("decision", "s007-v1"),
    ]


def test_scheduler_skips_closed_session_for_that_calendar_date():
    store, engine, advice = Store(), Engine(), Advice()
    store.accounts = [_account()]
    advice.results["s007-v1"] = None
    scheduler = _scheduler(
        engine,
        AccountDataPreparer(advice=advice),
        store,
        preparation_time="00:00",
    )
    scheduler.tick_daily(datetime(2026, 9, 19, 20, 30))
    _wait_until(lambda: len(advice.calls) == 1)
    scheduler.tick_daily(datetime(2026, 9, 19, 20, 30, 5))
    assert len(advice.calls) == 1
    assert engine.calls == []


def test_hung_account_preparation_does_not_block_other_accounts():
    blocked, release = Event(), Event()

    class Preparer:
        def prepare(self, account, *, signal_date):
            if account["account_id"] == "s007-v1":
                blocked.set()
                assert release.wait(5)
            return _prepared(
                f"{account['strategy_id']}-{account['strategy_version']}",
                signal_date,
            )

    store, engine = Store(), Engine()
    store.accounts = [_account(), _account("s003-v1", strategy_id="S003")]
    scheduler = _scheduler(
        engine, Preparer(), store, preparation_time="00:00"
    )
    scheduler.tick_daily(datetime(2026, 9, 18, 20, 30))
    try:
        assert blocked.wait(1)
        _wait_until(lambda: ("decision", "s003-v1") in engine.calls)
        assert ("decision", "s007-v1") not in engine.calls
    finally:
        release.set()
    _wait_until(lambda: ("decision", "s007-v1") in engine.calls)


def test_slow_preparation_does_not_stop_order_reconciliation():
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


def test_scheduler_rejects_malformed_persisted_failure_state():
    store = Store()
    store.failures["orders"] = {
        "fingerprint": "RuntimeError:test",
        "failure_count": "bad",
        "first_at": "2026-09-18T08:00:00",
        "last_at": "2026-09-18T08:00:00",
        "next_retry": "2026-09-18T08:01:00",
    }
    with pytest.raises(ValueError, match="invalid persisted scheduler failure"):
        _scheduler(Engine(), object(), store)
