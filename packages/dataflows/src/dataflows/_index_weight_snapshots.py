"""Monthly Tushare snapshots selected by the complete exchange calendar."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .errors import DataContractError, IncompleteDataError


def monthly_snapshot_calendar(client, start_date, end_date):
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if (pd.isna(start) or pd.isna(end) or start.tzinfo is not None or end.tzinfo is not None
            or start != start.normalize() or end != end.normalize() or start > end):
        raise DataContractError('snapshot interval must contain ordered calendar dates')
    first = start.to_period('M').start_time
    last = end.to_period('M').end_time.normalize()
    calendar = client.trade_cal(exchange='SSE', start_date=first.strftime('%Y%m%d'),
        end_date=last.strftime('%Y%m%d'), fields='exchange,cal_date,is_open,pretrade_date')
    if not isinstance(calendar, pd.DataFrame) or not {'exchange','cal_date','is_open'}.issubset(calendar.columns):
        raise IncompleteDataError('a complete SSE calendar is required for monthly snapshots')
    days = pd.to_datetime(calendar.cal_date.astype(str), errors='coerce')
    expected = pd.date_range(first, last)
    if (days.isna().any() or days.duplicated().any()
            or not pd.DatetimeIndex(days).sort_values().equals(expected)
            or calendar.exchange.ne('SSE').any() or not calendar.is_open.isin([0,1]).all()):
        raise IncompleteDataError('SSE calendar is incomplete or ambiguous')
    open_days = pd.DatetimeIndex(days[calendar.is_open.eq(1)]).sort_values()
    selected = []
    for month in pd.period_range(first, last, freq='M'):
        sessions = open_days[open_days.to_period('M') == month]
        if sessions.empty:
            raise IncompleteDataError('calendar month has no trading session', month=str(month))
        day = sessions[-1]
        if start <= day <= end:
            selected.append(day)
    return calendar, open_days, tuple(selected)


def fetch_weight_snapshot(client, symbol, day, *, include_weight=True, allow_missing=False):
    day = pd.Timestamp(day)
    columns = ['index_code','con_code','trade_date'] + (['weight'] if include_weight else [])
    raw = client.index_weight(index_code=symbol, trade_date=day.strftime('%Y%m%d'), fields=','.join(columns))
    if not isinstance(raw, pd.DataFrame):
        raise DataContractError('index_weight did not return a dataframe')
    if raw.empty:
        if allow_missing:
            return pd.DataFrame(columns=columns)
        raise IncompleteDataError('expected monthly index_weight snapshot is missing',
                                  index_code=symbol, trade_date=day.strftime('%Y%m%d'))
    if not set(columns).issubset(raw.columns) or raw.index_code.ne(symbol).any():
        raise DataContractError('index_weight response is missing its identity or mixes indexes')
    raw = raw.loc[:, columns].copy()
    dates = pd.to_datetime(raw.trade_date.astype(str), errors='coerce')
    if dates.isna().any() or dates.ne(day).any():
        raise DataContractError('index_weight returned a date different from requested trade_date')
    if (raw.con_code.isna().any() or not raw.con_code.map(lambda s: isinstance(s, str) and bool(s.strip())).all()
            or raw.con_code.duplicated().any()):
        raise DataContractError('index_weight snapshot has invalid or duplicate constituent symbols')
    if symbol == '000905.SH' and len(raw) != 500:
        raise IncompleteDataError('CSI500 snapshot must contain 500 unique constituents',
                                  trade_date=day.strftime('%Y%m%d'), actual=len(raw), expected=500)
    if include_weight:
        weights = pd.to_numeric(raw.weight, errors='coerce')
        if not np.isfinite(weights).all() or weights.lt(0).any():
            raise DataContractError('index_weight snapshot contains invalid weights')
    return raw.reset_index(drop=True)
