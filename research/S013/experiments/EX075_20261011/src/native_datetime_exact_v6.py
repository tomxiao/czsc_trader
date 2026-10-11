"""Lossless datetime-unit metadata normalization; full frame still exact."""

import numpy as np
import pandas as pd


def canonical_copy(frame):
    if not isinstance(frame, pd.DataFrame) or "dt" not in frame or frame.columns.has_duplicates:
        raise ValueError("unique native dt dataframe required")
    before = frame["dt"].copy()
    if not pd.api.types.is_datetime64_dtype(before.dtype) or before.isna().any():
        raise ValueError("finite timezone-naive datetime64 native timestamps required")
    unit = np.datetime_data(before.dtype)[0]
    normalized = before.dt.as_unit("ns")
    roundtrip = normalized.dt.as_unit(unit)
    pd.testing.assert_series_equal(roundtrip, before, check_exact=True)
    if normalized.tolist() != before.tolist():
        raise ValueError("native datetime timestamp values changed")
    result = frame.copy()
    result["dt"] = normalized
    return result, dict(
        original_unit=unit,
        canonical_unit="ns",
        rows=len(frame),
        timestamp_exact=True,
        original_unit_roundtrip_exact=True,
    )


def assert_native_exact(left, right):
    a, left_proof = canonical_copy(left)
    b, right_proof = canonical_copy(right)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    return dict(
        status="PASS",
        left=left_proof,
        right=right_proof,
        all_other_columns_and_dtypes_and_order_exact=True,
    )
