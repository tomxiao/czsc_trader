"""Shared bounded DFLS observation selection for research and forward preparation."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import DataIdentity, DataRequest, Dataset, PreparePolicy


def request_selection(request):
    """Physical identity shared by DataRequest and its typed equity subclass."""
    return (request.dataset, request.symbol, request.start, request.end,
            request.required_cutoff, request.frequency, request.parameters, request.coverage)


def resolve_observation_requests(dataflows, declarations, start, end, *, source_root, as_of=None):
    """Resolve trading dates and completed source weeks from published calendars."""
    calendars = {}
    calendar_requests = {}
    keys = {}
    for item in declarations:
        if item.dataset is Dataset.STOCK_MONEYFLOW or item.frequency == 'weekly':
            first, last = item.bounds(start, end)
            if item.frequency == 'weekly':
                first -= timedelta(days=first.weekday())
                last += timedelta(days=6-last.weekday())
            key = (item.calendar, first, last)
            keys[item.name] = key
            calendar_requests[key] = DataRequest(Dataset.TRADING_CALENDAR, item.calendar,
                first.isoformat(), last.isoformat(), None)
    if calendar_requests:
        queries = tuple(calendar_requests.values())
        prepared = dataflows.prepare(queries, policy=PreparePolicy.REUSE)
        if not prepared.ready:
            raise ValueError('observation trading calendar preparation is incomplete')
        for key, query in calendar_requests.items():
            fetched = dataflows.fetch(query, prepared=prepared.reference)
            if not fetched.ready:
                raise ValueError('observation trading calendar is unavailable')
            frame = fetched.dataframe
            if not {'Date', 'IsOpen'}.issubset(frame.columns):
                raise ValueError('observation trading calendar lacks Date/IsOpen')
            frame = frame.loc[pd.to_numeric(frame.IsOpen, errors='raise').eq(1)]
            days = sorted({pd.Timestamp(value).date() for value in frame.Date})
            calendars[key] = tuple(day.isoformat() for day in days if key[1] <= day <= key[2])
            if not calendars[key]:
                raise ValueError('observation trading calendar has no open dates')
    result = []
    for item in declarations:
        cutoff = end
        dates = calendars.get(keys.get(item.name), ())
        if item.frequency == 'weekly':
            first, last = item.bounds(start, end)
            first_week = first - timedelta(days=first.weekday())
            if any(first_week <= date.fromisoformat(day) < first for day in dates):
                raise ValueError('weekly observation start omits source sessions in its first week')
            week_ends = {}
            for value in dates:
                day = date.fromisoformat(value)
                week_ends[day-timedelta(days=day.weekday())] = day
            moment = as_of or datetime.combine(last, time.max, ZoneInfo('Asia/Shanghai'))
            if type(moment) is not datetime or moment.utcoffset() is None:
                raise ValueError('completed weekly observation requires an aware cutoff')
            completed = [day for day in week_ends.values() if first <= day <= last
                and datetime.combine(day, time(15), ZoneInfo('Asia/Shanghai')) <= moment]
            if not completed:
                raise ValueError('observation has no completed source trading week')
            cutoff = max(completed)
            if item.history_end is not None and cutoff != item.history_end:
                raise ValueError('fixed weekly observation end is not a completed source week')
        result.append((item.data_key(), item.request(start, cutoff, source_root=source_root,
            trading_dates=dates if item.dataset is Dataset.STOCK_MONEYFLOW else ())))
    return tuple(result)


def observation_end(request):
    return date.fromisoformat(request.end[:10])


def observation_forward_end(declaration, point, *, default_timezone):
    """Bound date-only publications by their explicit source-day assumption."""
    policy = declaration.availability
    local = point.astimezone(ZoneInfo(policy.timezone if policy else default_timezone))
    if policy is None:
        return local.date()
    published = datetime.combine(local.date(), time.fromisoformat(policy.available_time), local.tzinfo)
    return local.date() - timedelta(days=policy.day_offset + int(local < published))


def observation_identity(identity):
    return {name: dict(identity.metadata) if name == 'metadata' else getattr(identity, name)
            for name in DataIdentity.__dataclass_fields__}


def prepare_observation_tables(declarations, products, identities):
    from .dataset_observations import PreparedObservationTable
    return {item.name: PreparedObservationTable.from_frame(products[item.data_key()],
        DataIdentity(**identities[item.data_key()]['observation_identity']), declaration=item)
        for item in declarations}
