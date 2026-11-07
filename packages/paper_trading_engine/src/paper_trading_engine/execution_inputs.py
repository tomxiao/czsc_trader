"""Host-only projection of prepared DFLS calendars into EC rule inputs."""
from zoneinfo import ZoneInfo

from dataflows import canonical_frame_sha256
from dataflows.equity_data import sessions_from_metadata
from execution_channels.market_rules import PriceLimitMode
from execution_channels.market_rules.constraints import RuleInterval, assemble_constraints, resolve_execution_context
from execution_channels.serialization import from_record, to_record
from execution_channels.instruments import InstrumentId
from execution_channels.policy import ResearchExecutionSpec


def execution_constraints(definition, products, metadata):
    sessions = sessions_from_metadata(metadata['sessions'])
    following = dict(zip((s.session_date for s in sessions), sessions[1:]))
    record = metadata['trading_facts'].get('following_session')
    if record is not None:
        tail = sessions_from_metadata({'sessions': [record]})[0]
        if tail.session_date <= sessions[-1].session_date or tail.timezone != sessions[-1].timezone:
            raise ValueError('invalid following trading session')
        following[sessions[-1].session_date] = tail
    grid = tuple(RuleInterval(s.session_date, p.start, p.end,
        following[s.session_date].segments[0].start if s.session_date in following else None,
        following[s.session_date].segments[-1].end if s.session_date in following else None)
        for s in sessions for p in s.bars(definition.execution_spec.decision_clock))
    frame = assemble_constraints(from_record(InstrumentId, to_record(definition.instrument)),
        from_record(ResearchExecutionSpec, to_record(definition.execution_spec)), grid, products['trading_facts'])
    return frame, {'content_sha256': canonical_frame_sha256(frame),
                   'metadata': {'market_rules': sorted(set(frame.MarketRuleHash))}}


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
    period = RuleInterval(day, interval.start, interval.end,
        None if following is None else following.segments[0].start,
        None if following is None else following.segments[-1].end)
    context = resolve_execution_context(from_record(InstrumentId, to_record(instrument)),
        from_record(ResearchExecutionSpec, to_record(spec)), period)
    return dict(**context.to_record(), AvailableDate=interval.start,
        PriceLimitPolicy='CHANNEL_CHECKED' if context.rule.price_limits is PriceLimitMode.DATED else 'EXPLICIT_UNBOUNDED',
        PriceLimitLower=None, PriceLimitUpper=None)
