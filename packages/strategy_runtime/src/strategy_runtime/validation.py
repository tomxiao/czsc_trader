"""SRT contract validation shared by data preparation and planning."""

from __future__ import annotations

import pandas as pd
from .errors import RuntimeContractError


def validate_history_depth(
    input_name: str,
    required_sessions: int,
    dataframe: pd.DataFrame,
) -> None:
    if required_sessions <= 0:
        return
    date_column = next(
        (
            candidate
            for candidate in (
                "Date",
                "date",
                "datetime",
                "dt",
                "trade_date",
                "cal_date",
            )
            if candidate in dataframe.columns
        ),
        None,
    )
    if date_column is None:
        raise RuntimeContractError(
            f"prepared input {input_name} has no session timestamp"
        )
    observed = pd.to_datetime(dataframe[date_column], errors="coerce").dropna().dt.normalize().nunique()
    if observed < required_sessions:
        raise RuntimeContractError(
            f"prepared input {input_name} has insufficient history: "
            f"required={required_sessions}, observed={observed}"
        )
