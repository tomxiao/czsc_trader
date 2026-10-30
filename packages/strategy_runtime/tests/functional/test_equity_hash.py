"""Canonical identity bytes retain the pre-optimization conversion contract."""
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from hashlib import sha256
import json
import warnings
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from strategy_runtime.equity import equity_hash


def legacy_hash(value):
    """Independent copy of the old JSON default, including UTC validation."""
    def utc(stamp):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("equity timestamps must be timezone-aware")
        return stamp.astimezone(UTC)
    def default(item):
        if isinstance(item, (datetime, pd.Timestamp)):
            return utc(item.to_pydatetime() if isinstance(item, pd.Timestamp) else item).isoformat()
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"unserializable equity identity {type(item)}")
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False, default=default).encode()).hexdigest()


class FoldOffset(tzinfo):
    def utcoffset(self, stamp):
        return timedelta(minutes=30 if stamp.fold else 60)

    def dst(self, stamp):
        return timedelta(0)


class AbsentOffset(tzinfo):
    def utcoffset(self, stamp):
        return None


class ConvertedDatetime(datetime):
    def astimezone(self, tz=None):
        return datetime(2000, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("stamp", [
    datetime(2026, 10, 1, 14, tzinfo=UTC),
    datetime(2026, 10, 1, 14, 1, 2, 123456, tzinfo=UTC, fold=1),
    datetime.min.replace(tzinfo=UTC),
    datetime.max.replace(tzinfo=UTC),
    datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0),
    datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1),
    datetime(2026, 10, 1, 14, tzinfo=timezone(timedelta(hours=8))),
    datetime(2026, 10, 1, 14, tzinfo=FoldOffset(), fold=0),
    datetime(2026, 10, 1, 14, tzinfo=FoldOffset(), fold=1),
    ConvertedDatetime(2026, 10, 1, 14, tzinfo=UTC),
])
def test_datetime_identity_matches_original_utc_conversion(stamp):
    payload = {"point": {"start": stamp, "end": stamp}, "unicode": "中文😀\ud800", "negative_zero": -0.0}
    assert equity_hash(payload) == legacy_hash(payload)


@pytest.mark.parametrize("value", [
    pd.Timestamp("2026-10-01T14:00:00Z"),
    pd.Timestamp("2026-10-01T14:00:00.123456789Z"),
    pd.Timestamp("2026-10-01T14:00:00.123456001+08:00"),
    Decimal("-0.00"), Decimal("1E-7"), Decimal("NaN"), Decimal("Infinity"),
    np.int64(2**63 - 1), np.bool_(True), np.float32(-0.0), np.float64(-0.0),
    np.float32(.1), np.str_("中文"), np.datetime64("2026-10-01T14:00:00", "ns"),
    {"z": (1e-7, 1e20), "a": [False, None, "\\u4e2d", "a\n"]},
])
def test_other_supported_values_and_timestamp_warnings_are_unchanged(value):
    def observe(operation):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = operation({"value": value})
        return result, tuple((item.category, str(item.message)) for item in captured)
    assert observe(equity_hash) == observe(legacy_hash)


@pytest.mark.parametrize("value", [
    datetime(2026, 10, 1), datetime(2026, 10, 1, tzinfo=AbsentOffset()),
    datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
    datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))),
    pd.Timestamp("2026-10-01T14:00:00.123456789"), pd.NaT,
    float("nan"), float("inf"), float("-inf"), np.float32("nan"), np.float64("inf"),
    date(2026, 10, 1), b"bytes", np.complex128(1 + 2j), object(), {1: "number", "a": "string"},
])
def test_rejected_values_preserve_exception_and_warning_contract(value):
    def observe(operation):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            with pytest.raises(Exception) as error:
                operation({"value": value})
        return type(error.value), str(error.value), tuple((item.category, str(item.message)) for item in captured)
    assert observe(equity_hash) == observe(legacy_hash)


@pytest.mark.parametrize("container", ["list", "dict"])
def test_circular_references_still_reject(container):
    value = [] if container == "list" else {}
    if container == "list":
        value.append(value)
    else:
        value["self"] = value
    for operation in (legacy_hash, equity_hash):
        with pytest.raises(ValueError, match="Circular reference detected"):
            operation(value)


def test_signed_zero_and_dst_folds_are_not_conflated():
    assert equity_hash(-0.0) != equity_hash(0.0)
    assert equity_hash(Decimal("-0.00")) != equity_hash(Decimal("0.00"))
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0)
    second = first.replace(fold=1)
    assert equity_hash(first) != equity_hash(second)
