"""Exact original prepared-data contract; no autodetection or fallback."""

import numpy as np
import pandas as pd

MAPPING = {
    "Date": "dt",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "vol",
    "Amount": "amount",
}


def numerical(frame):
    if not isinstance(frame, pd.DataFrame) or frame.columns.has_duplicates:
        raise ValueError("original prepared frame with unique columns required")
    if not set(MAPPING).issubset(frame.columns):
        raise ValueError("exact Date/Open/High/Low/Close/Volume/Amount contract required")
    if set(MAPPING.values()).intersection(frame.columns):
        raise ValueError("mixed raw/pre-normalized schema forbidden")
    result = frame.loc[:, list(MAPPING)].rename(columns=MAPPING).copy()
    result["dt"] = pd.to_datetime(result["dt"], errors="raise").dt.as_unit("ns")
    if result["dt"].isna().any() or result["dt"].dt.tz is not None:
        raise ValueError("valid timezone-naive Date required")
    for name in list(MAPPING.values())[1:]:
        result[name] = pd.to_numeric(result[name], errors="raise")
        if not np.isfinite(result[name].to_numpy(float)).all():
            raise ValueError("finite original prepared numeric values required")
    result.attrs = {}
    return result
