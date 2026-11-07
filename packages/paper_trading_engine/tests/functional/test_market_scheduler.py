"""Bounded scheduling across explicit CN/US calendars; never contacts a broker."""
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from zoneinfo import ZoneInfo

import pytest

from dataflows import TimeInterval
from paper_trading_engine.scheduler import RuntimeScheduler
from paper_trading_engine.scheduling_contracts import ScheduledDecision
from test_scheduler import Engine, Store, _account


NY = ZoneInfo("America/New_York")
CN = ZoneInfo("Asia/Shanghai")


def _task(key="us-open", *, month=11, day=5, hour=9, minute=30):
    start = datetime(2026, month, day, hour, minute, tzinfo=NY)
    return ScheduledDecision(key, TimeInterval(start, start + timedelta(minutes=30)), start)


class Provider:
    def __init__(self, tasks):
        self.tasks = tasks
        self.calls = []
        self.failures = {}

    def due_decision(self, account, observed_at):
        return self.tasks.get(account["account_id"])

    def run_scheduled(self, account_id, task, observed_at):
        if account_id in self.failures:
            raise self.failures[account_id]
        self.calls.append((account_id, task, observed_at))


def _runtime(store, provider, **kwargs):
    return RuntimeScheduler(Engine(), object(), store, schedule_provider=provider, **kwargs)


def _join(scheduler):
    for worker in tuple(scheduler._account_workers.values()):
        worker.join(2)
        assert not worker.is_alive()


@pytest.mark.parametrize("month,day,expected_utc_hour", [(10, 30, 13), (11, 2, 14)])
def test_explicit_us_interval_runs_without_shanghai_daily_gate(month, day, expected_utc_hour):
    # The schedule provider supplies the actual session. Scheduler does not
    # reinterpret the provider's calendar using the workstation's date.
    task = _task(month=month, day=day)
    store = Store()
    store.accounts = [_account("us", symbol="MU", channel_id="futu_US_sim_channel")]
    provider = Provider({"us": task})
    scheduler = _runtime(store, provider, preparation_time="23:59")
    scheduler.tick_daily(task.decision_at)
    _join(scheduler)
    assert provider.calls == [("us", task, task.decision_at.astimezone(timezone.utc))]
    assert provider.calls[0][2].hour == expected_utc_hour
    assert store.get_setting("last_account_schedule_task:us") == task.task_id


def test_schedule_rejects_submission_at_early_close():
    start = datetime(2026, 11, 27, 12, 30, tzinfo=NY)
    task = ScheduledDecision("us-early-close", TimeInterval(start, start + timedelta(minutes=30)), start)
    assert task.submit_before.astimezone(NY).hour == 13
    store = Store()
    store.accounts = [_account("us")]
    provider = Provider({"us": task})
    scheduler = _runtime(store, provider)
    scheduler.tick_daily(task.submit_before)
    _join(scheduler)
    assert provider.calls == []
    assert "account_strategy_cycle:us" in store.failures
    assert store.get_setting("last_account_schedule_task:us") is None


def test_closed_calendar_does_not_run_even_when_daily_gate_is_open():
    store = Store()
    store.accounts = [_account("cn"), _account("us")]
    provider = Provider({})  # Calendar has no eligible completed interval.
    scheduler = _runtime(store, provider, preparation_time="00:00")
    scheduler.tick_daily(datetime(2026, 11, 7, 23, tzinfo=CN))
    _join(scheduler)
    assert provider.calls == []
    assert not any(key.startswith("last_account_schedule_task:") for key in store.values)


def test_same_task_survives_restart_and_next_intraday_interval_can_run():
    task = _task()
    store = Store()
    store.accounts = [_account("us")]
    provider = Provider({"us": task})
    scheduler = _runtime(store, provider)
    scheduler.tick_daily(task.decision_at)
    _join(scheduler)
    restarted = _runtime(store, provider)
    restarted.tick_daily(task.decision_at + timedelta(seconds=5))
    _join(restarted)
    assert len(provider.calls) == 1
    next_task = _task("next-interval", hour=10, minute=0)
    provider.tasks["us"] = next_task
    restarted.tick_daily(next_task.decision_at)
    _join(restarted)
    assert [call[1].task_id for call in provider.calls] == ["us-open", "next-interval"]


def test_failed_account_does_not_mark_complete_or_block_other_market():
    task = _task()
    store = Store()
    store.accounts = [_account("cn"), _account("us")]
    provider = Provider({"cn": task, "us": task})
    provider.failures["us"] = RuntimeError("US data not ready")
    scheduler = _runtime(store, provider)
    scheduler.tick_daily(task.decision_at)
    _join(scheduler)
    assert [call[0] for call in provider.calls] == ["cn"]
    assert store.get_setting("last_account_schedule_task:us") is None
    provider.failures.clear()
    scheduler.tick_daily(task.decision_at + timedelta(seconds=5))
    _join(scheduler)
    assert [call[0] for call in provider.calls] == ["cn", "us"]


def test_workers_are_bounded_and_each_waiting_account_eventually_runs():
    task = _task()
    store = Store()
    store.accounts = [_account(str(n)) for n in range(5)]
    release, entered = Event(), Event()
    lock = Lock()
    running = maximum = 0

    class BlockingProvider(Provider):
        def run_scheduled(self, account_id, task, observed_at):
            nonlocal running, maximum
            with lock:
                running += 1
                maximum = max(maximum, running)
                if running == 2:
                    entered.set()
            try:
                assert release.wait(3)
                super().run_scheduled(account_id, task, observed_at)
            finally:
                with lock:
                    running -= 1

    provider = BlockingProvider({str(n): task for n in range(5)})
    scheduler = _runtime(store, provider, max_account_workers=2)
    scheduler.tick_daily(task.decision_at)
    try:
        assert entered.wait(1)
        scheduler.tick_daily(task.decision_at + timedelta(seconds=5))
        scheduler.tick_fast(task.decision_at)
        assert scheduler.engine.calls == ["account", "orders"]
        assert len(scheduler._account_workers) == 2
    finally:
        release.set()
    _join(scheduler)
    for seconds in (10, 15, 20):
        scheduler.tick_daily(task.decision_at + timedelta(seconds=seconds))
        _join(scheduler)
    assert maximum == 2
    assert sorted(call[0] for call in provider.calls) == [str(n) for n in range(5)]


def test_task_contract_and_aware_clock_are_required():
    task = _task()
    with pytest.raises(ValueError, match="timezone-aware"):
        ScheduledDecision("bad", task.interval, datetime(2026, 11, 5))
    with pytest.raises(ValueError, match="submission start"):
        ScheduledDecision("bad", task.interval, task.submit_after + timedelta(seconds=1))
    with pytest.raises(TypeError, match="typed calendar"):
        ScheduledDecision("bad", (task.submit_after, task.submit_before), task.decision_at)
    with pytest.raises(ValueError, match="positive integer"):
        _runtime(Store(), Provider({}), max_account_workers=True)
    scheduler = _runtime(Store(), Provider({}))
    with pytest.raises(ValueError, match="timezone-aware"):
        scheduler.tick_daily(datetime(2026, 11, 5))


def test_slow_due_resolution_stays_outside_broker_poll_lane():
    store = Store()
    store.accounts = [_account("us")]
    entered, release = Event(), Event()

    class SlowProvider(Provider):
        def due_decision(self, account, observed_at):
            entered.set()
            assert release.wait(3)
            return None

    scheduler = _runtime(store, SlowProvider({}))
    scheduler.tick_daily(_task().decision_at)
    try:
        assert entered.wait(1)
        scheduler.tick_fast(_task().decision_at)
        assert scheduler.engine.calls == ["account", "orders"]
    finally:
        release.set()
    _join(scheduler)


def test_channel_failure_backoff_does_not_skip_healthy_channel():
    store = Store()

    class Unavailable(Engine):
        def refresh_orders(self):
            super().refresh_orders()
            raise ConnectionError("CN unavailable")

    cn, us = Unavailable(), Engine()
    scheduler = _runtime(store, Provider({}),
        channel_operations={"cn-main": cn, "us-main": us}, order_interval=5)
    start = _task().decision_at
    for seconds in (0, 5, 10):
        scheduler.tick_fast(start + timedelta(seconds=seconds))
    assert cn.calls.count("orders") == 2
    assert us.calls.count("orders") == 3
    assert "orders:cn-main" in store.failures
    assert "orders:us-main" not in store.failures
    assert scheduler.engine.calls == []


def test_channel_account_failure_still_polls_all_orders():
    store = Store()

    class AccountUnavailable(Engine):
        def refresh_account(self):
            super().refresh_account()
            raise ConnectionError("US account unavailable")

    cn, us = Engine(), AccountUnavailable()
    scheduler = _runtime(store, Provider({}), channel_operations={"us-main": us, "cn-main": cn})
    scheduler.tick_fast(_task().decision_at)
    assert cn.calls == ["account", "orders"]
    assert us.calls == ["account", "orders"]
    assert "account:us-main" in store.failures
    assert "account:cn-main" not in store.failures
