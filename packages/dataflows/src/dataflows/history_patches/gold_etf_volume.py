"""Source-bound 5m volume-unit repair verified against complete 1m bars."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..errors import DataRepairError
from ..history_validation import inspect_intraday_against_daily
from .common import configured_repair_dates, rebuild_intraday_from_1m

VOLUME_DATES = (
    "2024-04-03", "2024-04-19", "2024-04-26", "2024-04-30",
    "2024-05-24", "2024-05-31", "2024-06-14",
)


def matches_volume_series(series):
    return (series.vendor == "tushare" and series.endpoint == "etf_mins"
            and series.symbol in {"518850.SH", "518880.SH"}
            and series.dataset == "etf.ohlcv" and series.frequency == "5m"
            and series.adjustment == "none")


def volume_reference_dates(daily, series, findings):
    if not matches_volume_series(series):
        return ()
    dates = {day for f in findings if f.code == "CROSS_FREQUENCY_MISMATCH"
             for day, fields in f.context.get("fields_by_date", {}).items()
             if fields == ["Volume"] and day in VOLUME_DATES}
    return configured_repair_dates(daily, sorted(dates))


def repair_volume(dataframe, patch, series, findings, references):
    dates = volume_reference_dates(references.get("daily"), series, findings)
    if not dates:
        return dataframe.copy(), ()
    if "1m" not in references:
        raise DataRepairError(f"{patch.patch_id}: complete 1m volume evidence required")
    result = dataframe.copy()
    days = pd.to_datetime(result.Date).dt.strftime("%Y-%m-%d")
    daily = references["daily"]
    daily_days = pd.to_datetime(daily.Date).dt.strftime("%Y-%m-%d")
    for day in dates:
        rebuilt = rebuild_intraday_from_1m(references["1m"], daily, "5m", dates=(day,))
        reference = daily.loc[daily_days == day]
        # The reference must reconcile in full before its volume can repair 5m.
        inspect_intraday_against_daily(rebuilt, reference, "5m").require_pass()
        current = result.loc[days == day]
        if (not pd.to_datetime(current.Date).reset_index(drop=True).equals(rebuilt.Date)
                or not np.allclose(current.Volume.to_numpy() / 100., rebuilt.Volume,
                                   rtol=1e-5, atol=1.)
                or not np.allclose(current.Amount.to_numpy(), rebuilt.Amount,
                                   rtol=1e-5, atol=1.)):
            raise DataRepairError(f"{patch.patch_id}: unknown 100x volume signature on {day}")
        # No daily price is injected; only independently reconstructed volume changes.
        result.loc[current.index, "Volume"] = rebuilt.Volume.to_numpy()
    return result, dates
