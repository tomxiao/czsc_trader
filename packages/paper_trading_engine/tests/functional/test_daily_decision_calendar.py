"""Pure exchange-calendar tests for pre-execution daily decision eligibility."""

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import BarFrequency, TimeInterval
from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient, FormalV4ScheduleProvider


def _calendar_provider(zone, signal_day, execution_day, signal_close, execution_close):
    tz = ZoneInfo(zone)
    records = []
    for day, close in ((signal_day, signal_close), (execution_day, execution_close)):
        periods = (
            ((time(9, 30), time(11, 30)), (time(13), close))
            if zone == "Asia/Shanghai"
            else ((time(9, 30), close),)
        )
        records.append(
            {
                "session_date": day,
                "timezone": zone,
                "segments": [
                    {
                        "start": datetime.combine(date.fromisoformat(day), start, tz).isoformat(),
                        "end": datetime.combine(date.fromisoformat(day), end, tz).isoformat(),
                    }
                    for start, end in periods
                ],
            }
        )
    fetched = SimpleNamespace(
        ready=True,
        identity=SimpleNamespace(metadata={"sessions": records}),
        dataframe=pd.DataFrame(
            {
                "SessionDate": [signal_day, execution_day],
                "AvailableDate": [datetime(2026, 1, 1, tzinfo=timezone.utc)] * 2,
            }
        ),
    )
    account = {"account_id": "test", "release_hash": "a" * 64, "run_state": "RUNNING"}
    client = object.__new__(FormalV4AdviceClient)
    client.recipe = lambda _: SimpleNamespace(release_hash=account["release_hash"])
    client._calendar_products = lambda *_: {"sessions": fetched}
    client.store = SimpleNamespace(
        equity_account_rules=lambda _: SimpleNamespace(
            execution=SimpleNamespace(decision_clock=BarFrequency.DAILY)
        )
    )
    client._interval_allowed = lambda *_: True
    return FormalV4ScheduleProvider(client, None), account, tz


# Independent risk: PTE05; responsibility-level assertions.
@pytest.mark.parametrize(
    "zone,signal_day,execution_day,signal_close,execution_close,utc_hour",
    [
        ("Asia/Shanghai", "2026-11-05", "2026-11-06", time(15), time(15), 12),
        ("America/New_York", "2026-10-29", "2026-10-30", time(16), time(16), 1),
        ("America/New_York", "2026-11-27", "2026-11-30", time(13), time(16), 23),
    ],
    ids=["PTE05-C03", "PTE05-C04", "PTE05-C05"],
)
def test_daily_decision_uses_actual_previous_close_and_next_trading_session(
    zone, signal_day, execution_day, signal_close, execution_close, utc_hour
):
    provider, account, tz = _calendar_provider(
        zone, signal_day, execution_day, signal_close, execution_close
    )
    closed_at = datetime.combine(date.fromisoformat(signal_day), signal_close, tz)
    eligible = closed_at + timedelta(hours=5)
    assert provider.due_decision(account, eligible - timedelta(microseconds=1)) is None
    task = provider.due_decision(account, eligible)
    assert task.decision_at == eligible
    assert task.decision_at.astimezone(timezone.utc).hour == utc_hour
    expected_interval = TimeInterval(
        datetime.combine(date.fromisoformat(execution_day), time(9, 30), tz),
        datetime.combine(date.fromisoformat(execution_day), execution_close, tz),
    )
    assert task.interval == expected_interval
    assert task.submit_after > task.decision_at
    assert provider.due_decision(account, task.submit_after).task_id == task.task_id
    assert provider.due_decision(account, task.submit_before) is None


def test_PTE05_C02_manual_drive_obeys_close_plus_five_hours():
    from contextlib import nullcontext

    provider, account, zone = _calendar_provider(
        "Asia/Shanghai", "2026-11-05", "2026-11-06", time(15), time(15)
    )
    account.update(health="OK", last_decision_payload=None)
    provider.client.decision_cycle_lock = lambda _: nullcontext()
    provider.client._require_running = lambda _: None
    provider.client.store.virtual_account = lambda _: account
    provider.client.prepare_interval = lambda *a, **kw: pytest.fail("early drive must not prepare")
    with pytest.raises(RuntimeError, match="no executable V4 interval"):
        provider.drive_decision("test", datetime(2026, 11, 5, 19, 59, 59, tzinfo=zone))
