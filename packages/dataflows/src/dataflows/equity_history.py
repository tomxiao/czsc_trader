"""Versioned bars and trading facts with an explicit common price basis."""
from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from datetime import date
from hashlib import sha256

import pandas as pd

from .contract import EquityDataRequest, ProviderBinding
from .equity_contracts import (AcquisitionMethod, BarFrequency, EquityProduct, EquityQuery, InstrumentId,
    PriceAdjustment, ProviderKey, SourceRef, TradingSession)
from .equity_data import equity_metadata, session_record, validate_equity_frame
from .errors import DataContractError, IncompleteDataError


@dataclass(frozen=True, slots=True)
class EquitySourceCoverage:
    start: date
    end: date
    evidence: str

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise TypeError('source coverage requires ordered local dates')
        if type(self.evidence) is not str or not self.evidence.strip():
            raise TypeError('source coverage requires explicit provenance evidence')


@dataclass(frozen=True, slots=True)
class EquityFrequencyFacts:
    frequency: BarFrequency
    bars: pd.DataFrame
    trading_facts: pd.DataFrame
    adjustment: PriceAdjustment = PriceAdjustment.NONE
    acquisition_method: AcquisitionMethod | None = None

    def __post_init__(self):
        if type(self.frequency) is not BarFrequency:
            raise TypeError('frequency facts require BarFrequency')
        if type(self.adjustment) is not PriceAdjustment:
            raise TypeError('frequency facts require explicit PriceAdjustment')
        if self.acquisition_method is not None and type(self.acquisition_method) is not AcquisitionMethod:
            raise TypeError('frequency facts require AcquisitionMethod')
        if self.adjustment is not PriceAdjustment.NONE and self.acquisition_method is None:
            raise DataContractError('adjusted frequency facts require their acquisition method')
        if self.acquisition_method is not None and (
                (self.acquisition_method is AcquisitionMethod.PROVIDER_RAW)
                != (self.adjustment is PriceAdjustment.NONE)):
            raise DataContractError('frequency acquisition method differs from its price basis')
        if any(type(frame) is not pd.DataFrame or frame.empty for frame in (self.bars, self.trading_facts)):
            raise TypeError('frequency facts require nonempty bars and trading_facts')


def versioned_equity_bindings(*, instrument: InstrumentId, source: SourceRef,
        coverage: EquitySourceCoverage, sessions: tuple[TradingSession, ...],
        frequencies: tuple[EquityFrequencyFacts, ...],
        following_session: TradingSession | None = None):
    """Admit facts once; serve detached selections without converting price bases.

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
            or len({(item.frequency, item.adjustment) for item in frequencies}) != len(frequencies)):
        raise TypeError('versioned frequencies must be explicit and unique')
    if (any(session.timezone != instrument.timezone
            or not coverage.start <= session.session_date <= coverage.end for session in sessions)
            or tuple(s.session_date for s in sessions) != tuple(sorted({s.session_date for s in sessions}))):
        raise DataContractError('source calendar differs from market or declared coverage')
    if following_session is not None and (type(following_session) is not TradingSession
            or following_session.timezone != instrument.timezone
            or following_session.session_date <= coverage.end):
        raise DataContractError('following trading session must be after the attested coverage')
    # The installed provider owns private numeric containers. Later caller
    # mutation, or mutation of a fetched view, cannot change source facts.
    saved = {(item.frequency, item.adjustment): (pd.DataFrame(item.bars, copy=True),
                             pd.DataFrame(item.trading_facts, copy=True)) for item in frequencies}
    methods = {(item.frequency, item.adjustment): (item.acquisition_method or AcquisitionMethod.PROVIDER_RAW)
               for item in frequencies}
    source_receipt = {'coverage_evidence': coverage.evidence,
        'coverage_evidence_sha256': sha256(coverage.evidence.encode()).hexdigest()}
    if any({'BarStatus', 'ExecutionBlocked'}.intersection(frame.columns) for frame, _ in saved.values()):
        if any(not {'BarStatus', 'ExecutionBlocked'}.issubset(frame) for frame, _ in saved.values()):
            raise DataContractError('explicit observation facts must be supplied for every frequency')
        source_receipt['observation_contract'] = 'EXPLICIT_SOURCE_OBSERVATIONS_V1'
        source_receipt['observation_basis'] = 'SOURCE_FACTS_NOT_INFERRED_HISTORICAL_HALTS'

    def metadata(request, selected_sessions):
        meta = equity_metadata(request, selected_sessions,
            availability_basis='EXPLICIT_SOURCE_TIMESTAMPS') | source_receipt
        query = request.parameters.query
        if query.product is EquityProduct.BARS:
            meta['acquisition_method'] = methods[(query.frequency, query.adjustment)].value
        return meta

    def request_for(product, frequency, adjustment, start, end):
        return EquityDataRequest(instrument, source, EquityQuery(product, start, end, frequency,
            PriceAdjustment.NONE if product is EquityProduct.SESSIONS else adjustment))

    session_frame = pd.DataFrame({'Date': [s.segments[0].start for s in sessions],
        'AvailableDate': [s.segments[0].start for s in sessions],
        'SessionDate': [s.session_date.isoformat() for s in sessions]})
    # Validate the complete source before publishing any binding. No successful
    # selection can hide an invalid trading rule or omitted source bar.
    for (frequency, adjustment), (bars, trading_facts) in saved.items():
        for product, frame in ((EquityProduct.BARS, bars),
                (EquityProduct.TRADING_FACTS, trading_facts), (EquityProduct.SESSIONS, session_frame)):
            request = request_for(product, frequency, adjustment, coverage.start, coverage.end)
            validate_equity_frame(frame, request, metadata(request, sessions))
    days = tuple(s.session_date for s in sessions)
    row_days = {frequency: (
        tuple(pd.to_datetime(bars.BarStart).dt.tz_convert(instrument.timezone).dt.date),
        tuple(pd.to_datetime(trading_facts.Date).dt.tz_convert(instrument.timezone).dt.date))
        for frequency, (bars, trading_facts) in saved.items()}

    def select(frame, dates, start, end):
        return frame.iloc[bisect_left(dates, start):bisect_right(dates, end)]

    def fetch(request):
        parameters = request.parameters
        query = parameters.query
        if parameters.instrument != instrument or parameters.source != source:
            raise DataContractError('MARKET_CONTRACT_MISMATCH: versioned source identity differs')
        key = (query.frequency, query.adjustment)
        if query.product is not EquityProduct.SESSIONS and key not in saved:
            raise DataContractError('requested frequency and price basis have no explicit source facts')
        if query.start < coverage.start or query.end > coverage.end:
            raise IncompleteDataError('requested interval exceeds attested source coverage')
        selected_sessions = sessions[bisect_left(days, query.start):bisect_right(days, query.end)]
        if not selected_sessions:
            raise IncompleteDataError('requested interval contains no declared trading sessions')
        meta = metadata(request, selected_sessions)
        if query.product is EquityProduct.TRADING_FACTS:
            next_index = bisect_right(days, query.end)
            next_session = sessions[next_index] if next_index < len(sessions) else following_session
            if next_session is not None:
                meta['following_session'] = session_record(next_session)
        if query.product is EquityProduct.SESSIONS:
            selected = select(session_frame, days, query.start, query.end)
        else:
            bars, trading_facts = saved[key]
            original = bars if query.product is EquityProduct.BARS else trading_facts
            indexed_days = row_days[key][0 if query.product is EquityProduct.BARS else 1]
            selected = select(original, indexed_days, query.start, query.end)
        if query.completed_through is not None:
            selected = selected.loc[selected.Date <= query.completed_through]
        selected = pd.DataFrame(selected, copy=True).reset_index(drop=True)
        # The complete source was validated at admission and the indexed local-
        # date slice preserves the exact grid. Managed publication independently
        # validates the returned product; do not rescan full source history here.
        return selected, meta

    return {ProviderKey(product, instrument.market, source):
            ProviderBinding(source.provider, source.revision, fetch) for product in EquityProduct}
