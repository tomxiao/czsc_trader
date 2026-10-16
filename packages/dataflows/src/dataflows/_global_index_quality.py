"""SPX historical continuity guard, independent of source/cache provenance."""

import pandas as pd

from .errors import IncompleteDataError


# Same calendar-day horizon already declared for SPX availability in SRT inputs.
# This detects large internal holes; it does not certify every US trading session.
SPX_MAXIMUM_GAP_DAYS = 10


def validate_global_index_history(dataframe: pd.DataFrame, symbol: str | None) -> None:
    if symbol is None or symbol.upper() != 'SPX':
        return
    dates = pd.to_datetime(dataframe['Date'], errors='raise').dt.normalize()
    gaps = dates.diff().dt.days
    oversized = gaps.gt(SPX_MAXIMUM_GAP_DAYS)
    if oversized.any():
        position = int(oversized.to_numpy().argmax())
        raise IncompleteDataError(
            'SPX history has an internal gap exceeding its availability horizon',
            symbol='SPX', previous_date=dates.iloc[position - 1].date().isoformat(),
            next_date=dates.iloc[position].date().isoformat(),
            gap_days=int(gaps.iloc[position]), maximum_gap_days=SPX_MAXIMUM_GAP_DAYS,
        )
