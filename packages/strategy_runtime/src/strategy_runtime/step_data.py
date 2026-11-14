"""DFLS reads granted to one strategy invocation."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from uuid import UUID

from dataflows import (
    AssetClass, BarFrequency, DataRequest, Dataset, EquityDataRequest, EquityProduct,
    EquityQuery, InstrumentId, MarketId, PreparedDataRef, PriceAdjustment, SourceRef,
    canonical_frame_sha256,
)
from dataflows.contract import EvidenceParameters

from .dataset_observations import FrozenDataAsset, ObservationAvailability


STEP_DATA_CONTRACT = 5
_HFQ = frozenset({Dataset.ETF_OHLCV, Dataset.STOCK_OHLCV})
_PRODUCTS = _HFQ | {
    Dataset.TRADING_CALENDAR, Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,
    Dataset.GLOBAL_INDEX_DAILY, Dataset.SHIBOR_DAILY, Dataset.INDEX_DAILY_BASIC,
    Dataset.ETF_SHARE_SIZE, Dataset.STRATEGY_FEATURE_EVIDENCE, Dataset.EQUITY_BARS,
}
_HFQ_PRODUCTS = _HFQ | {Dataset.EQUITY_BARS}


@dataclass(frozen=True, slots=True)
class StepDataInput:
    name: str
    dataset: Dataset
    symbol: str | None
    frequency: str
    max_calendar_days: int
    availability: ObservationAvailability
    asset: FrozenDataAsset | None = None
    instrument: InstrumentId | None = None
    source: SourceRef | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', self.name):
            raise ValueError('strategy data input requires a stable name')
        if type(self.dataset) is not Dataset or self.dataset not in _PRODUCTS:
            raise ValueError('unsupported strategy data product')
        if self.dataset is Dataset.SHIBOR_DAILY:
            if self.symbol is not None:
                raise ValueError('Shibor is a fixed series and requires no symbol')
        elif type(self.symbol) is not str or not self.symbol.strip():
            raise ValueError('strategy data input requires a symbol or exchange')
        if type(self.max_calendar_days) is not int or self.max_calendar_days < 1:
            raise ValueError('strategy data input requires a positive maximum range')
        if type(self.availability) is not ObservationAvailability:
            raise TypeError('strategy data input requires declared availability')
        if self.dataset is Dataset.STRATEGY_FEATURE_EVIDENCE:
            if type(self.asset) is not FrozenDataAsset:
                raise ValueError('strategy feature evidence requires a frozen asset')
        elif self.asset is not None:
            raise ValueError('only strategy feature evidence accepts a frozen asset')
        if self.dataset is Dataset.EQUITY_BARS:
            if (type(self.instrument) is not InstrumentId or type(self.source) is not SourceRef
                    or self.instrument.symbol != self.symbol
                    or self.instrument.timezone != self.availability.timezone):
                raise ValueError('equity bars require matching instrument, calendar timezone and explicit source')
        elif self.instrument is not None or self.source is not None:
            raise ValueError('only typed equity bars accept instrument and source')
        self.request(StepDataWindow(self.name, date(2000, 1, 1), date(2000, 1, 1)),
                     source_root=Path.cwd())

    def request(self, window, *, source_root=None, observed_through=None):
        if type(window) is not StepDataWindow or window.name != self.name:
            raise ValueError('strategy window does not match the declared input')
        if self.dataset is Dataset.EQUITY_BARS:
            frequency = BarFrequency(self.frequency)
            cutoff = None
            if frequency is BarFrequency.M30 and observed_through is not None:
                if type(observed_through) is not datetime or observed_through.utcoffset() is None:
                    raise ValueError('completed bar selection requires an aware observation time')
                local = observed_through.astimezone(ZoneInfo(self.instrument.timezone))
                if local.date() == window.end:
                    cutoff = observed_through
            return EquityDataRequest(self.instrument, self.source, EquityQuery(
                EquityProduct.BARS, window.start, window.end, frequency, PriceAdjustment.BACKWARD,
                completed_through=cutoff))
        if self.asset is not None:
            if source_root is None:
                raise ValueError('strategy feature evidence requires the host-owned source root')
            parameters = EvidenceParameters(Path(source_root).resolve(), self.asset.relative_path, self.asset.sha256)
            return DataRequest(self.dataset, self.symbol, window.start.isoformat(),
                               window.end.isoformat(), None, self.frequency, parameters)
        return DataRequest(self.dataset, self.symbol, window.start.isoformat(),
                           window.end.isoformat(), None, self.frequency)

    def to_dict(self):
        return {key: value for key, value in asdict(self).items() if
                key not in {'asset', 'instrument', 'source'} or value is not None}

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        if value.get('asset') is not None:
            value['asset'] = FrozenDataAsset(**value['asset'])
        if value.get('instrument') is not None:
            instrument = value['instrument']
            value['instrument'] = InstrumentId(MarketId(instrument['market']),
                                               AssetClass(instrument['asset_class']), instrument['symbol'])
        if value.get('source') is not None:
            value['source'] = SourceRef(**value['source'])
        return cls(**{**value, 'dataset': Dataset(value['dataset']),
                      'availability': ObservationAvailability(**value['availability'])})


@dataclass(frozen=True, slots=True)
class StepDataWindow:
    name: str
    start: date
    end: date

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise TypeError('strategy window requires an input name')
        if type(self.start) is not date or type(self.end) is not date or self.start > self.end:
            raise ValueError('strategy window requires ordered dates')

    def to_dict(self):
        return {'name': self.name, 'start': self.start.isoformat(), 'end': self.end.isoformat()}

    @classmethod
    def from_dict(cls, value):
        return cls(value['name'], date.fromisoformat(value['start']), date.fromisoformat(value['end']))


@dataclass(frozen=True, slots=True)
class StepDataRead:
    window: StepDataWindow
    prepared: PreparedDataRef
    prepared_slice_sha256: str
    visible_slice_sha256: str
    as_of: str
    observed_through: str
    first: str
    last: str
    rows: int

    def to_dict(self):
        return {**asdict(self), 'window': self.window.to_dict(),
                'prepared': {key: str(value) for key, value in asdict(self.prepared).items()}}

    @classmethod
    def from_dict(cls, value):
        ref = value['prepared']
        return cls(**{**value, 'window': StepDataWindow.from_dict(value['window']),
                      'prepared': PreparedDataRef(UUID(ref['space_id']), UUID(ref['preparation_id']),
                                                  ref['manifest_sha256'])})


class StepData:
    """A read-only capability that expires when the current step returns."""

    def __init__(self, inputs, *, as_of, observed_through, load: Callable | None, source_root=None,
                 equity_latency_seconds=0):
        if any(type(value) is not datetime or value.utcoffset() is None for value in (as_of, observed_through)):
            raise ValueError('strategy data scope requires aware decision and observation times')
        if observed_through > as_of:
            raise ValueError('strategy observation time exceeds the data cutoff')
        if type(equity_latency_seconds) is not int or equity_latency_seconds < 0:
            raise ValueError('equity observation latency requires nonnegative seconds')
        self._inputs = {item.name: item for item in inputs}
        self._as_of = as_of
        self._observed_through = observed_through
        self._load = load
        self._source_root = source_root
        self._equity_latency_seconds = equity_latency_seconds
        self._cache = {}
        self._reads = []
        self._failed = False

    def fetch(self, window: StepDataWindow):
        if self._cache is None:
            raise RuntimeError('strategy data scope has expired')
        try:
            if type(window) is not StepDataWindow or window.name not in self._inputs:
                raise ValueError('strategy must request a declared input')
            item = self._inputs[window.name]
            zone = ZoneInfo(item.availability.timezone)
            latest = self._observed_through.astimezone(zone).date()
            if (window.end > latest
                    or window.start <= latest - timedelta(days=item.max_calendar_days)):
                raise ValueError('strategy data window exceeds the observation boundary or maximum lookback')
            if window not in self._cache:
                request = item.request(window, source_root=self._source_root, observed_through=self._observed_through)
                reference, result = self._load(window, request)
                if type(reference) is not PreparedDataRef:
                    raise TypeError('strategy read requires a prepared DFLS reference')
                if not result.ready:
                    raise ValueError(f'STRATEGY_DATA_UNAVAILABLE {window.name}: {result.error}')
                if item.dataset in _HFQ_PRODUCTS and result.identity.metadata.get('adjustment') != 'hfq':
                    raise ValueError('strategy quotation requires HFQ')
                if item.asset is not None and (
                        result.identity.metadata.get('source_sha256') != item.asset.sha256
                        or result.identity.metadata.get('source_path') != item.asset.relative_path):
                    raise ValueError('strategy feature evidence differs from the frozen asset')
                visible = self._visible(result, item, zone)
                if visible.empty:
                    raise ValueError('STRATEGY_DATA_UNAVAILABLE: no visible rows')
                self._reads.append(StepDataRead(window, reference, result.identity.content_sha256,
                    canonical_frame_sha256(visible), self._as_of.isoformat(), self._observed_through.isoformat(),
                    visible.Date.iloc[0].isoformat(),
                    visible.Date.iloc[-1].isoformat(), len(visible)))
                self._cache[window] = visible
            return self._cache[window].copy(deep=True)
        except Exception:
            self._failed = True
            raise

    def _visible(self, result, item, zone):
        import pandas as pd
        frame = result.dataframe
        temporal = result.identity.temporal_contract
        source = pd.to_datetime(frame[temporal.source_time_field], errors='raise')
        available = pd.to_datetime(frame[temporal.availability_time_field], errors='raise')
        if source.isna().any() or available.isna().any():
            raise ValueError('strategy data contains missing timestamps')
        def localize(values):
            return values.dt.tz_localize(zone) if values.dt.tz is None else values.dt.tz_convert(zone)
        source, available = localize(source), localize(available)
        if item.dataset is Dataset.EQUITY_BARS:
            available += pd.Timedelta(seconds=self._equity_latency_seconds)
        # Calculate the declared wall-clock floor before timezone localization across DST.
        clock = datetime.strptime(item.availability.available_time, '%H:%M').time()
        floor = (source.dt.tz_localize(None).dt.normalize() + pd.Timedelta(
            days=item.availability.day_offset, hours=clock.hour, minutes=clock.minute)).dt.tz_localize(zone)
        visible = frame.loc[(source <= self._observed_through) & (available <= self._as_of)
                            & (floor <= self._as_of)].reset_index(drop=True)
        if not pd.api.types.is_datetime64_any_dtype(visible['Date']):
            visible['Date'] = pd.to_datetime(visible['Date'], errors='raise')
        return visible

    def close(self):
        self._load = None
        self._cache = None

    def receipts(self):
        if self._failed:
            raise ValueError('strategy attempted an invalid or unavailable data read')
        return tuple(self._reads)
