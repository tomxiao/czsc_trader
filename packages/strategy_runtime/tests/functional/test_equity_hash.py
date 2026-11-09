"""SRT-02: persisted identity bytes use the established canonical contract."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo
import json
import numpy as np
import pandas as pd
import pytest
from strategy_runtime.equity import equity_hash


def reference_hash(value):
    def default(item):
        if isinstance(item, (datetime, pd.Timestamp)):
            stamp = item.to_pydatetime() if isinstance(item, pd.Timestamp) else item
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("equity timestamps must be timezone-aware")
            return stamp.astimezone(UTC).isoformat()
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"unserializable equity identity {type(item)}")

    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=default
        ).encode()
    ).hexdigest()


def test_SRT_02_C01_same_absolute_time_has_same_identity():
    stamp = datetime(2026, 10, 1, 14, tzinfo=UTC)
    assert equity_hash(stamp) == equity_hash(stamp.astimezone(timezone(timedelta(hours=8))))
    assert equity_hash(stamp) == reference_hash(stamp)


def test_SRT_02_C02_dst_fold_is_not_conflated():
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0)
    assert equity_hash(first) != equity_hash(first.replace(fold=1))


def test_SRT_02_C03_signed_zero_is_preserved():
    assert equity_hash(-0.0) != equity_hash(0.0)
    assert equity_hash(Decimal("-0.00")) != equity_hash(Decimal("0.00"))


def test_SRT_02_C04_circular_input_rejected():
    value = []
    value.append(value)
    with pytest.raises(ValueError, match="Circular reference"):
        equity_hash(value)


@pytest.mark.parametrize(
    "value,error",
    [
        (object(), TypeError),
        (float("nan"), ValueError),
    ],
    ids=["SRT-02-C05", "SRT-02-C06"],
)
def test_unsupported_and_nonfinite_input_keep_exception_type(value, error):
    with pytest.raises(error):
        equity_hash({"value": value})
