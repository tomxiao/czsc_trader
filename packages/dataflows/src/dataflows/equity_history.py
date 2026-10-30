"""Versioned, source-attested RAW equity facts for either market.

The host supplies independent calendars, economic events and dated trading
rules. This adapter never reconstructs events from adjusted prices or guesses
market rules. Provider completeness is an explicit source declaration, not a
claim inferred from an empty API response.
"""
from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from datetime import date
from hashlib import sha256

import pandas as pd

from .contract import EquityDataRequest, ProviderBinding
from .equity_contracts import (BarFrequency, EquityProduct, EquityQuery, InstrumentId,
    PriceAdjustment, ProviderKey, SourceRef, TradingSession)
from .equity_data import equity_metadata, validate_equity_frame
from .errors import DataContractError, IncompleteDataError


@dataclass(frozen=True, slots=True)
class EquitySourceCoverage:
    start: date
    end: date
    evidence: str
    actions_complete: bool
    no_actions_verified: bool = False

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise TypeError('source coverage requires ordered local dates')
        if type(self.evidence) is not str or not self.evidence.strip():
            raise TypeError('source coverage requires explicit provenance evidence')
        if type(self.actions_complete) is not bool or type(self.no_actions_verified) is not bool:
            raise TypeError('action coverage declarations must be bool')
        if not self.actions_complete:
            raise IncompleteDataError('complete economic-event source coverage is required')


@dataclass(frozen=True, slots=True)
class EquityFrequencyFacts:
    frequency: BarFrequency
    bars: pd.DataFrame
    constraints: pd.DataFrame

    def __post_init__(self):
        if type(self.frequency) is not BarFrequency:
            raise TypeError('frequency facts require BarFrequency')
        if any(type(frame) is not pd.DataFrame or frame.empty for frame in (self.bars, self.constraints)):
            raise TypeError('frequency facts require nonempty bars and constraints')


def versioned_equity_bindings(*, instrument: InstrumentId, source: SourceRef,
        coverage: EquitySourceCoverage, sessions: tuple[TradingSession, ...],
        frequencies: tuple[EquityFrequencyFacts, ...], actions: pd.DataFrame):
    """Admit complete facts once; serve detached, exact-range RAW selections.

    ``coverage.evidence`` identifies the upstream verification or source receipt.
    It remains a host declaration: passing synthetic evidence validates software,
    not historical provider completeness. D1 and M30 must each be supplied; an
    unavailable frequency is rejected rather than resampled or obtained elsewhere.
    """
    if type(instrument) is not InstrumentId or type(source) is not SourceRef:
        raise TypeError('versioned facts require an instrument and source revision')
    if type(coverage) is not EquitySourceCoverage:
        raise TypeError('versioned facts require EquitySourceCoverage')
    if (type(sessions) is not tuple or not sessions
            or any(type(session) is not TradingSession for session in sessions)):
        raise TypeError('versioned facts require independent TradingSession evidence')
    if (type(frequencies) is not tuple or not frequencies
            or any(type(item) is not EquityFrequencyFacts for item in frequencies)
            or len({item.frequency for item in frequencies}) != len(frequencies)):
        raise TypeError('versioned frequencies must be explicit and unique')
    if type(actions) is not pd.DataFrame or actions.empty:
        raise IncompleteDataError('economic events or an explicit verified NONE record are required')
    if not {'Date', 'AvailableDate', 'EventId', 'Kind', 'Ratio', 'CashPerShare', 'PayAt'}.issubset(actions):
        raise DataContractError('economic-event source fields are incomplete')
    if (any(session.timezone != instrument.timezone
            or not coverage.start <= session.session_date <= coverage.end for session in sessions)
            or tuple(s.session_date for s in sessions) != tuple(sorted({s.session_date for s in sessions}))):
        raise DataContractError('source calendar differs from market or declared coverage')
    # The installed provider owns private numeric containers. Later caller
    # mutation, or mutation of a fetched view, cannot change source facts.
    saved = {item.frequency: (pd.DataFrame(item.bars, copy=True),
                             pd.DataFrame(item.constraints, copy=True)) for item in frequencies}
    action_frame = pd.DataFrame(actions, copy=True)
    if coverage.no_actions_verified and not (len(action_frame) == 1 and action_frame.Kind.iloc[0] == 'NONE'):
        raise DataContractError('no-action attestation conflicts with supplied economic events')
    event_days = pd.to_datetime(action_frame.Date, errors='raise')
    if event_days.isna().any() or event_days.dt.tz is None:
        raise DataContractError('economic event dates must be aware and finite')
    if not event_days.dt.tz_convert(instrument.timezone).dt.date.between(coverage.start, coverage.end).all():
        raise DataContractError('economic events exceed their attested source coverage')
    source_receipt = {'coverage_evidence': coverage.evidence,
        'coverage_evidence_sha256': sha256(coverage.evidence.encode()).hexdigest(),
        'action_history_complete': True, 'economic_price_basis': 'RAW',
        'constraint_contract': 'DATED_EQUITY_RULES_V1'}
    if any({'BarStatus', 'ExecutionBlocked'}.intersection(frame.columns) for frame, _ in saved.values()):
        if any(not {'BarStatus', 'ExecutionBlocked'}.issubset(frame) for frame, _ in saved.values()):
            raise DataContractError('explicit observation facts must be supplied for every frequency')
        source_receipt['observation_contract'] = 'EXPLICIT_SOURCE_OBSERVATIONS_V1'
        source_receipt['observation_basis'] = 'SOURCE_FACTS_NOT_INFERRED_HISTORICAL_HALTS'

    def metadata(request, selected_sessions):
        return equity_metadata(request, selected_sessions,
            availability_basis='EXPLICIT_SOURCE_TIMESTAMPS') | source_receipt | {
                'no_actions_verified': coverage.no_actions_verified}

    def request_for(product, frequency, start, end):
        return EquityDataRequest(instrument, source, EquityQuery(product, start, end, frequency))

    session_frame = pd.DataFrame({'Date': [s.segments[0].start for s in sessions],
        'AvailableDate': [s.segments[0].start for s in sessions],
        'SessionDate': [s.session_date.isoformat() for s in sessions]})
    # Validate the complete source before publishing any binding. No successful
    # selection can hide an invalid event, trading rule or omitted source bar.
    for frequency, (bars, constraints) in saved.items():
        for product, frame in ((EquityProduct.BARS, bars),
                (EquityProduct.CONSTRAINTS, constraints), (EquityProduct.SESSIONS, session_frame),
                (EquityProduct.ACTIONS, action_frame)):
            request = request_for(product, frequency, coverage.start, coverage.end)
            validate_equity_frame(frame, request, metadata(request, sessions))
    days = tuple(s.session_date for s in sessions)
    action_days = tuple(event_days.dt.tz_convert(instrument.timezone).dt.date)
    row_days = {frequency: (
        tuple(pd.to_datetime(bars.BarStart).dt.tz_convert(instrument.timezone).dt.date),
        tuple(pd.to_datetime(constraints.Date).dt.tz_convert(instrument.timezone).dt.date))
        for frequency, (bars, constraints) in saved.items()}

    def select(frame, dates, start, end):
        return frame.iloc[bisect_left(dates, start):bisect_right(dates, end)]

    def fetch(request):
        parameters = request.parameters
        query = parameters.query
        if parameters.instrument != instrument or parameters.source != source:
            raise DataContractError('MARKET_CONTRACT_MISMATCH: versioned source identity differs')
        if query.adjustment is not PriceAdjustment.NONE:
            raise DataContractError('explicit economic-event histories require RAW prices')
        if query.frequency not in saved:
            raise DataContractError('requested frequency has no explicit source facts')
        if query.start < coverage.start or query.end > coverage.end:
            raise IncompleteDataError('requested interval exceeds attested source coverage')
        selected_sessions = sessions[bisect_left(days, query.start):bisect_right(days, query.end)]
        if not selected_sessions:
            raise IncompleteDataError('requested interval contains no declared trading sessions')
        meta = metadata(request, selected_sessions)
        if query.product is EquityProduct.SESSIONS:
            selected = select(session_frame, days, query.start, query.end)
        elif query.product is EquityProduct.ACTIONS:
            selected = select(action_frame, action_days, query.start, query.end)
            selected = selected.loc[selected.Kind.ne('NONE')]
            if selected.empty:
                # This deduction is permitted only after admission of a complete
                # versioned action history, never from an unverified empty fetch.
                stamp = selected_sessions[0].segments[0].start
                selected = pd.DataFrame([{'Date': stamp, 'AvailableDate': stamp,
                    'EventId': f'{source.provider}:{source.revision}:verified-empty:{query.start}:{query.end}',
                    'Kind': 'NONE', 'Ratio': 1., 'CashPerShare': 0., 'PayAt': None}])
                meta['no_actions_verified'] = True
        else:
            bars, constraints = saved[query.frequency]
            original = bars if query.product is EquityProduct.BARS else constraints
            indexed_days = row_days[query.frequency][0 if query.product is EquityProduct.BARS else 1]
            selected = select(original, indexed_days, query.start, query.end)
        selected = pd.DataFrame(selected, copy=True).reset_index(drop=True)
        # The complete source was validated at admission and the indexed local-
        # date slice preserves the exact grid. Managed publication independently
        # validates the returned product; do not rescan full source history here.
        return selected, meta

    return {ProviderKey(product, instrument.market, source):
            ProviderBinding(source.provider, source.revision, fetch) for product in EquityProduct}
