"""Declared auxiliary observations and causally available exchange sessions."""
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
import math

import pandas as pd
from dataflows import BarFrequency, TradingSession


def _times(frame, column):
    if not isinstance(frame, pd.DataFrame) or column not in frame:
        raise ValueError(f'equity context requires {column}')
    values = frame[column]
    if not isinstance(values, pd.Series) or not isinstance(values.dtype, pd.DatetimeTZDtype):
        values = pd.to_datetime(values, errors='raise')
    if values.isna().any() or values.dt.tz is None:
        raise ValueError(f'{column} requires aware finite timestamps')
    return values.dt.tz_convert('UTC')


def _finite(values):
    # Standard numeric columns are already converted by pd.to_numeric. Keep its
    # uncommon extension/complex scalar behaviour, including conversion errors.
    dtypes = values.dtypes if isinstance(values, pd.DataFrame) else (values.dtype,)
    if all(not isinstance(dtype, pd.api.extensions.ExtensionDtype)
           and dtype.kind in 'biuf' for dtype in dtypes):
        return values.notna() & ~values.isin((float('inf'), float('-inf')))
    return values.map(math.isfinite)


def _auxiliary_history(declaration, frame, point, latency, *, slice_history):
    dates, available = _times(frame, 'Date'), _times(frame, 'AvailableDate')
    if not dates.is_monotonic_increasing or dates.duplicated().any() or (available < dates).any():
        raise ValueError('auxiliary observations require ordered unique completion and availability')
    visible = (dates <= point.decision_at) & (available + pd.Timedelta(seconds=latency) <= point.decision_at)
    if not slice_history and not visible.all():
        raise ValueError('CAUSAL_TIME_VIOLATION: future auxiliary observation')
    frame = frame.loc[visible].copy(deep=True)
    if frame.empty:
        raise ValueError(f'AUXILIARY_INPUT_UNAVAILABLE: {declaration.name}')
    if 'BarStatus' in frame:
        if not frame.BarStatus.isin(('OBSERVED', 'MISSING', 'ZERO_VOLUME')).all():
            raise ValueError('unknown auxiliary bar status')
        if frame.BarStatus.iloc[-1] != 'OBSERVED':
            raise ValueError(f'AUXILIARY_INPUT_UNAVAILABLE: latest {declaration.name}')
        frame = frame.loc[frame.BarStatus.eq('OBSERVED')].copy(deep=True)
    required = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not set(required).issubset(frame):
        raise ValueError('auxiliary observations require OHLCV')
    numeric = frame[required].apply(pd.to_numeric, errors='raise')
    if (not _finite(numeric).all().all() or (numeric.iloc[:, :4] <= 0).any().any()
            or (numeric.Volume <= 0).any()):
        raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: invalid or zero-volume observation')
    if ((numeric.High < numeric[['Open', 'Close', 'Low']].max(axis=1))
            | (numeric.Low > numeric[['Open', 'Close', 'High']].min(axis=1))).any():
        raise ValueError('invalid auxiliary OHLC bounds')
    if 'Amount' in frame:
        amount = pd.to_numeric(frame.Amount, errors='raise')
        if not _finite(amount).all() or (amount < 0).any():
            raise ValueError('auxiliary Amount must be finite and nonnegative')
    if 'BarStart' in frame:
        if (_times(frame, 'BarStart') >= _times(frame, 'Date')).any():
            raise ValueError('auxiliary BarStart must precede completion')
    if len(frame) < declaration.warmup_bars:
        raise ValueError(f'AUXILIARY_WARMUP_INSUFFICIENT: {declaration.name}')
    if (pd.Timestamp(point.decision_at) - pd.Timestamp(frame.Date.iloc[-1])).total_seconds() > declaration.max_age_seconds:
        raise ValueError(f'AUXILIARY_INPUT_STALE: {declaration.name}')
    columns = ('Date', 'AvailableDate', 'BarStart', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount')
    return frame.loc[:, [name for name in columns if name in frame]].copy(deep=True)


def _validate_session(definition, point, session, available_at):
    if type(session) is not TradingSession or type(available_at) is not datetime:
        raise TypeError('session context requires TradingSession and typed availability datetime')
    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise ValueError('session availability must be timezone aware')
    available_at = available_at.astimezone(timezone.utc)
    if available_at > point.decision_at:
        raise ValueError('CAUSAL_TIME_VIOLATION: session is not yet available')
    if session.timezone != definition.instrument.timezone or point.execution_interval not in session.bars(definition.execution_spec.decision_clock):
        raise ValueError('session does not contain the exact execution interval')
    return available_at


def validate_equity_decision_context(definition, context):
    """Validate direct candidate calls and isolate all mutable strategy inputs."""
    dates, available = _times(context.history, 'Date'), _times(context.history, 'AvailableDate')
    if (dates > context.point.observed_through).any() or (available + pd.Timedelta(
            seconds=definition.execution_spec.data_latency_seconds) > context.point.decision_at).any():
        raise ValueError('CAUSAL_TIME_VIOLATION: future primary observation')
    histories = {}
    if definition.auxiliary_inputs:
        if not isinstance(context.auxiliary_histories, Mapping):
            raise TypeError('auxiliary histories require a mapping')
        for item in definition.auxiliary_inputs:
            if item.name not in context.auxiliary_histories:
                raise ValueError(f'AUXILIARY_INPUT_UNAVAILABLE: {item.name}')
            histories[item.name] = _auxiliary_history(item, context.auxiliary_histories[item.name],
                context.point, definition.execution_spec.data_latency_seconds, slice_history=False)
    session = context.session if definition.session_context else None
    availability = (_validate_session(definition, context.point, session, context.session_available_at)
                    if definition.session_context else None)
    return replace(context, history=context.history.copy(deep=True),
                   auxiliary_histories=MappingProxyType(histories), session=session,
                   session_available_at=availability)


def build_equity_decision_context(definition, history, portfolio, point, *,
                                 auxiliary_histories=None, sessions=None, trading_sessions=()):
    """Slice declared products; callers authenticate source metadata and fingerprints.

    Sessions contain public calendar boundaries only. Market observations never
    enter through this channel. Availability belongs to the matching session row.
    """
    from .equity_definition import EquityDecisionContext
    dates, primary_available = _times(history, 'Date'), _times(history, 'AvailableDate')
    if (dates > point.observed_through).any() or (primary_available + pd.Timedelta(
            seconds=definition.execution_spec.data_latency_seconds) > point.decision_at).any():
        raise ValueError('CAUSAL_TIME_VIOLATION: future primary observation')
    histories = {}
    if definition.auxiliary_inputs:
        if not isinstance(auxiliary_histories, Mapping):
            raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: required histories')
        for item in definition.auxiliary_inputs:
            if item.name not in auxiliary_histories:
                raise ValueError(f'AUXILIARY_INPUT_UNAVAILABLE: {item.name}')
            histories[item.name] = _auxiliary_history(item, auxiliary_histories[item.name], point,
                definition.execution_spec.data_latency_seconds, slice_history=True)
    session, availability = None, None
    if definition.session_context:
        if type(trading_sessions) is not tuple or any(type(s) is not TradingSession for s in trading_sessions):
            raise TypeError('session context requires typed calendar evidence')
        days = [s.session_date for s in trading_sessions]
        if not days or days != sorted(set(days)):
            raise ValueError('session calendar must be unique and ordered')
        dates, available = _times(sessions, 'Date'), _times(sessions, 'AvailableDate')
        if ('SessionDate' not in sessions or tuple(sessions.SessionDate) != tuple(d.isoformat() for d in days)
                or tuple(dates) != tuple(pd.Timestamp(s.segments[0].start) for s in trading_sessions)):
            raise ValueError('session table differs from calendar evidence')
        frequency = definition.execution_spec.decision_clock
        if type(frequency) is not BarFrequency:
            raise TypeError('frequency requires BarFrequency')
        # bars() rejects incomplete M30 segments anywhere in the calendar, even
        # outside the current session. Preserve that check without constructing
        # every historical TimeInterval at each decision.
        if frequency is not BarFrequency.DAILY:
            step = timedelta(minutes=30)
            if any((segment.end - segment.start) % step
                   for s in trading_sessions for segment in s.segments):
                raise ValueError('session contains an incomplete 30-minute interval')
        interval = point.execution_interval
        matches = [i for i, s in enumerate(trading_sessions)
                   if s.segments[0].start <= interval.start and interval.end <= s.segments[-1].end
                   and interval in s.bars(frequency)]
        if len(matches) != 1:
            raise ValueError('current execution interval has no unique session')
        index = matches[0]
        session = trading_sessions[index]
        availability = available.iloc[index].to_pydatetime()
        _validate_session(definition, point, session, availability)
    return EquityDecisionContext(history.copy(deep=True), portfolio, point, definition.parameters,
                                 MappingProxyType(histories), session, availability)
