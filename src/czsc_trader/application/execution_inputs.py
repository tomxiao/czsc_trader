"""Application boundary: project DFLS calendars into execution-owned rule inputs."""
from dataflows import canonical_frame_sha256
from dataflows.equity_data import sessions_from_metadata
from execution_channels.market_rules.constraints import RuleInterval, assemble_constraints
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
