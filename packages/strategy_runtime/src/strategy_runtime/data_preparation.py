"""One source-bound preparation path for research and online observations.

This module owns data acquisition and causal observation construction. It does
not resolve market rules, simulate fills or inspect an execution account.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from collections.abc import Mapping

from dataflows import BarFrequency, EquityDataRequest, EquityProduct
from dataflows.equity_data import sessions_from_metadata

from .observation_preparation import (
    observation_identity, prepare_observation_tables, request_selection,
)


class CalendarCoverage(StrEnum):
    EXACT = "EXACT"
    OVERLAPPING_SESSIONS = "OVERLAPPING_SESSIONS"


@dataclass(frozen=True, slots=True)
class PreparedProducts:
    """Frames and authenticated identities read from one preparation reference."""
    products: dict
    identities: dict

    @property
    def metadata(self):
        return {role: value["metadata"] for role, value in self.identities.items()}


def fetch_prepared_products(dataflows, items, *, prepared, expected_identities=None,
                            calendar_coverage=CalendarCoverage.EXACT):
    """Fetch each physical request once and validate every declared input role."""
    if type(items) is not tuple or not items:
        raise TypeError("prepared products require a nonempty tuple of role/request pairs")
    if type(calendar_coverage) is not CalendarCoverage:
        raise TypeError("prepared products require an explicit calendar coverage policy")
    if expected_identities is not None and not isinstance(expected_identities, Mapping):
        raise TypeError("prepared identities require a role/hash mapping")
    products, identities, calendars, fetched = {}, {}, {}, {}
    for role, request in items:
        if type(role) is not str or not role or role in products:
            raise ValueError("prepared products require unique nonempty input roles")
        key = request_selection(request)
        if key not in fetched:
            fetched[key] = dataflows.fetch(request, prepared=prepared)
        result = fetched[key]
        if not result.ready:
            raise ValueError(f"pinned equity product unavailable ({role}): {result.error}")
        identity = result.identity
        if expected_identities is not None and identity.content_sha256 != expected_identities.get(role):
            raise ValueError("equity preparation product identity differs: " + role)
        products[role] = result.dataframe
        identities[role] = {"content_sha256": identity.content_sha256,
                            "metadata": dict(identity.metadata)}
        if role.startswith("observation:"):
            identities[role]["observation_identity"] = observation_identity(identity)
            continue
        group = role.rsplit(":", 1)[0] if ":" in role else "primary"
        declared = identity.metadata["sessions"]
        if calendar_coverage is CalendarCoverage.EXACT:
            if group in calendars and calendars[group] != declared:
                raise ValueError("equity preparation calendars differ: " + group)
            calendars[group] = declared
        else:
            incoming = {row["session_date"]: row for row in declared}
            if len(incoming) != len(declared):
                raise ValueError("equity preparation contains duplicate calendar sessions")
            previous = calendars.setdefault(group, {})
            if any(previous[day] != incoming[day] for day in previous.keys() & incoming.keys()):
                raise ValueError("equity preparation calendars differ: " + group)
            previous.update(incoming)
    if expected_identities is not None and set(products) != set(expected_identities):
        raise ValueError("equity preparation lacks required products")
    return PreparedProducts(products, identities)


def observation_inputs(definition, products, identities, *, bindings=()):
    """Build the same auxiliary, session and table inputs for every host."""
    result = {
        "auxiliary_histories": {
            item.name: products[item.data_key(EquityProduct.BARS)]
            for item in definition.auxiliary_inputs
        },
        "sessions": products["sessions"],
        "trading_sessions": sessions_from_metadata(identities["sessions"]["metadata"]),
    }
    if definition.observation_inputs:
        result["observation_tables"] = prepare_observation_tables(
            definition.observation_inputs, products, identities, bindings=bindings)
    return result


def causal_history(bars, at, *, latency_seconds=0, minimum_observations=0):
    """Select completed, available bars without changing their source values."""
    import pandas as pd
    if not isinstance(at, datetime) or at.utcoffset() is None:
        raise TypeError("observation cutoff requires an aware timestamp")
    if type(latency_seconds) is not int or latency_seconds < 0:
        raise ValueError("observation latency must be a nonnegative integer")
    if type(minimum_observations) is not int or minimum_observations < 0:
        raise ValueError("minimum observations must be a nonnegative integer")
    delay = pd.Timedelta(seconds=latency_seconds)
    history = bars.loc[(bars.Date <= at) & (bars.AvailableDate + delay <= at)].copy(deep=True)
    if len(history) < minimum_observations:
        raise ValueError("insufficient causal equity warmup")
    return history


def prepare_observations(definition, products, identities, *, bindings=(), as_of=None):
    """Prepare strategy-only observations without execution facts or market rules."""
    from .equity_replay import PreparedObservations
    roles = ('bars',) + tuple(item.data_key(EquityProduct.BARS) for item in definition.auxiliary_inputs)
    for role in roles:
        metadata = identities[role]['metadata']
        if metadata.get('adjustment') != 'hfq':
            raise ValueError('strategy observations require HFQ prices: ' + role)
        if metadata.get('acquisition_method') not in ('PROVIDER_ADJUSTED', 'DFLS_ADJUSTED'):
            raise ValueError('HFQ observations require an explicit acquisition method: ' + role)
    bars = products["bars"]
    if as_of is not None:
        bars = causal_history(bars, as_of,
            latency_seconds=definition.execution_spec.data_latency_seconds,
            minimum_observations=definition.warmup_bars)
    return PreparedObservations.from_frames(bars, definition.feature_graph,
        latency_seconds=definition.execution_spec.data_latency_seconds,
        frequency=definition.execution_spec.decision_clock,
        timezone=definition.instrument.timezone,
        **observation_inputs(definition, products, identities, bindings=bindings))


def forward_equity_requests(binding, interval, definition, calendars, *, cutoff):
    """Expand host equity products to one causal decision point."""
    from zoneinfo import ZoneInfo
    from .equity_definition import InputBindingScope
    if binding.scope is not InputBindingScope.OBSERVATION:
        raise ValueError('forward recipe requires explicit observation-only input migration')
    items = []
    for role, parameters in binding.request_bindings:
        day = interval.start.astimezone(ZoneInfo(parameters.instrument.timezone)).date()
        completed_through = None
        if parameters.query.product is EquityProduct.BARS:
            key = role.rsplit(':', 1)[0] + ':sessions' if ':' in role else 'sessions'
            calendar = calendars[key]
            availability = {str(row.SessionDate): row.AvailableDate for row in calendar.dataframe.itertuples()}
            sessions = sessions_from_metadata(calendar.identity.metadata)
            if (definition.execution_spec.decision_clock is BarFrequency.M30
                    and parameters.query.frequency is BarFrequency.M30):
                ready = cutoff - timedelta(seconds=definition.execution_spec.data_latency_seconds)
                for session in reversed(sessions):
                    if availability[session.session_date.isoformat()] > cutoff:
                        continue
                    bar = next((bar for bar in reversed(session.bars(BarFrequency.M30)) if bar.end <= ready), None)
                    if bar is not None:
                        day = session.session_date
                        if bar.end != session.segments[-1].end:
                            completed_through = bar.end
                        break
                else:
                    raise ValueError('forward inputs have no completed 30-minute bar')
            else:
                completed = [session.session_date for session in sessions
                    if session.segments[-1].end <= cutoff and availability[session.session_date.isoformat()] <= cutoff]
                if not completed:
                    raise ValueError('forward inputs have no completed historical session')
                day = max(completed)
        elif parameters.query.product is EquityProduct.SESSIONS:
            # Calendar dates, not future market observations, are needed to
            # schedule the next legal sellability/settlement boundary.
            day += timedelta(days=14)
        else:
            raise ValueError('strategy-only recipe contains an execution product')
        items.append((role, replace(parameters, query=replace(parameters.query, end=day,
                                                               completed_through=completed_through))))
    requests = tuple(EquityDataRequest(p.instrument, p.source, p.query)
                     for p in dict.fromkeys(p for _, p in items))
    return requests, items
