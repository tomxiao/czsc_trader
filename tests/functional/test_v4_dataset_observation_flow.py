# Risk ownership: SRT-32
"""Read-side weekly boundaries for historical observation declarations."""
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from dataflows import Dataset, ProviderBinding
from strategy_runtime.dataset_observations import DatasetObservationInput, ObservationAvailability


@pytest.fixture
def weekly_calendar(tmp_path):
    from dataflows import Dataflows, DataSpace, ProviderConfig

    closed = set()

    def calendar(query):
        days = pd.date_range(query.start, query.end)
        return pd.DataFrame(
            {
                "Date": days,
                "IsOpen": [
                    int(day.weekday() < 5 and day.strftime("%Y-%m-%d") not in closed)
                    for day in days
                ],
            }
        ), {}

    flows = Dataflows(
        base_dir=tmp_path,
        space=DataSpace(Path("calendar")),
        providers=ProviderConfig(
            bindings={Dataset.TRADING_CALENDAR: ProviderBinding("synthetic", "v1", calendar)}
        ),
    )
    return flows, closed


@pytest.mark.parametrize(
    "case",
    ["midweek", "holiday", "boundary", "partial_first", "fixed_end", "naive", "no_week"],
    ids=[
        "SRT-32-C01",
        "SRT-32-C02",
        "SRT-32-C03",
        "SRT-32-C04",
        "SRT-32-C05",
        "SRT-32-C06",
        "SRT-32-C07",
    ],
)
def test_completed_week_request_boundaries(tmp_path, weekly_calendar, case):
    from strategy_runtime.observation_preparation import resolve_observation_requests

    flows, closed = weekly_calendar
    zone = ZoneInfo("Asia/Shanghai")
    declaration = DatasetObservationInput(
        "weekly",
        Dataset.ETF_OHLCV,
        "588080.SH",
        frequency="weekly",
        availability=ObservationAvailability("Asia/Shanghai", "15:00"),
    )
    start = date(2026, 10, 5)
    moment = datetime(2026, 10, 14, 16, tzinfo=zone)
    expected = "2026-10-09"
    failure = None
    if case == "holiday":
        closed.add("2026-10-16")
        moment = datetime(2026, 10, 15, 15, tzinfo=zone)
        expected = "2026-10-15"
    elif case == "boundary":
        moment = datetime(2026, 10, 16, 14, 59, 59, tzinfo=zone)
    elif case == "partial_first":
        start = date(2026, 10, 6)
        declaration = replace(declaration, history_start=start)
        failure = "start omits source sessions"
    elif case == "fixed_end":
        declaration = replace(declaration, history_start=start, history_end=date(2026, 10, 14))
        failure = "fixed weekly observation end"
    elif case == "naive":
        moment = moment.replace(tzinfo=None)
        failure = "aware cutoff"
    elif case == "no_week":
        start = date(2026, 10, 12)
        failure = "no completed source trading week"
    if failure:
        with pytest.raises(ValueError, match=failure):
            resolve_observation_requests(
                flows, (declaration,), start, moment.date(), source_root=tmp_path, as_of=moment
            )
    else:
        ((_, query),) = resolve_observation_requests(
            flows, (declaration,), start, moment.date(), source_root=tmp_path, as_of=moment
        )
        assert query.end == expected
        if case == "boundary":
            moment = moment.replace(hour=15, minute=0, second=0)
            ((_, complete),) = resolve_observation_requests(
                flows, (declaration,), start, moment.date(), source_root=tmp_path, as_of=moment
            )
            assert complete.end == "2026-10-16"
