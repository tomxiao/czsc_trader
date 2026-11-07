"""Temporal admission for already-supplied historical execution constraints."""
from collections.abc import Mapping
from datetime import datetime, timezone

import pandas as pd


CONSTRAINT_TIMES = ('Date', 'AvailableDate', 'BuySellableAt', 'SettlementAt')


def normalize_constraint_times(record: Mapping[str, object]) -> dict[str, object]:
    """Validate every execution clock before any strategy or account mutation.

    ISO timestamps and datetime values are admitted; naive or missing values
    never acquire an inferred timezone. UTC microsecond projection matches the
    historical strategy observation clock without changing the input record.
    """
    result = dict(record)
    for name in CONSTRAINT_TIMES:
        # Immediate-cash policies do not require settlement facts. If supplied,
        # the timestamp is still validated before any side can execute.
        if name == 'SettlementAt' and name not in record:
            continue
        value = record.get(name)
        if type(value) is datetime and value.utcoffset() is not None:
            result[name] = value.astimezone(timezone.utc)
            continue
        if not isinstance(value, (str, datetime, pd.Timestamp)) or pd.isna(value):
            raise ValueError(f'execution constraint {name} requires a nonmissing aware timestamp')
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f'execution constraint {name} requires an aware timestamp') from error
        if pd.isna(stamp) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f'execution constraint {name} requires a nonmissing aware timestamp')
        result[name] = stamp.tz_convert('UTC').to_pydatetime(warn=False)
    return result
