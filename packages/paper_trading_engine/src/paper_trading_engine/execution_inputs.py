"""Host-only projection of prepared DFLS calendars into EC rule inputs."""
from zoneinfo import ZoneInfo

from dataflows.equity_data import sessions_from_metadata
from execution_channels.market_rules import PriceLimitMode
from execution_channels.market_rules.constraints import RuleInterval, resolve_execution_context
from execution_channels.serialization import from_record, to_record
from execution_channels.instruments import InstrumentId
from execution_channels.policy import ResearchExecutionSpec


def resolve_live_context(candidate, interval, calendar, metadata):
    """Use static EC rules; broker acceptance determines dynamic tradability.

    No historical status or company-action table is required or synthesized.
    """
    instrument, spec = candidate.instrument, candidate.definition.execution_spec
    day = interval.start.astimezone(ZoneInfo(instrument.timezone)).date()
    sessions = sessions_from_metadata(metadata)
    current = next((session for session in sessions if session.session_date == day), None)
    if current is None or interval not in current.bars(spec.decision_clock):
        raise ValueError('live decision interval is absent from the prepared calendar')
    known = calendar.loc[calendar.SessionDate.eq(day.isoformat())]
    if len(known) != 1 or known.iloc[0].AvailableDate > interval.start:
        raise ValueError('live session was unavailable at the decision')
    following = next((session for session in sessions if session.session_date > day), None)
    if following is None and metadata.get('following_session') is not None:
        following = sessions_from_metadata({'sessions': [metadata['following_session']]})[0]
        if following.session_date <= day or following.timezone != instrument.timezone:
            raise ValueError('invalid explicit following execution session')
    period = RuleInterval(day, interval.start, interval.end,
        None if following is None else following.segments[0].start,
        None if following is None else following.segments[-1].end)
    context = resolve_execution_context(from_record(InstrumentId, to_record(instrument)),
        from_record(ResearchExecutionSpec, to_record(spec)), period)
    return dict(**context.to_record(), AvailableDate=interval.start,
        PriceLimitPolicy='CHANNEL_CHECKED' if context.rule.price_limits is PriceLimitMode.DATED else 'EXPLICIT_UNBOUNDED',
        PriceLimitLower=None, PriceLimitUpper=None)
