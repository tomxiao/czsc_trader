"""Typed, causal table observations for native account strategies.

These inputs are observations, never executable quotations.  Dataset publication
and frozen assets retain their existing DFLS identities.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import (DataRequest, Dataset, DataCoverageRequirement, DataIdentity,
    NoParameters, MoneyflowParameters, EvidenceParameters)


_DATASETS = frozenset((Dataset.ETF_OHLCV, Dataset.INDEX_CONSTITUENT_WEIGHT,
    Dataset.STOCK_MONEYFLOW, Dataset.STRATEGY_FEATURE_EVIDENCE, Dataset.SHIBOR_DAILY,
    Dataset.INDEX_DAILY_BASIC, Dataset.ETF_SHARE_SIZE, Dataset.GLOBAL_INDEX_DAILY,
    Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY))


@dataclass(frozen=True, slots=True)
class FrozenDataAsset:
    relative_path: str
    sha256: str

    def __post_init__(self):
        if type(self.relative_path) is not str:
            raise TypeError('frozen data path requires text')
        path = PurePosixPath(self.relative_path)
        if (not self.relative_path or path.is_absolute() or '..' in path.parts
                or str(path) != self.relative_path or '\\' in self.relative_path
                or ':' in self.relative_path or path.suffix != '.csv'):
            raise ValueError('frozen data requires a package-relative CSV path')
        if type(self.sha256) is not str or not re.fullmatch('[a-f0-9]{64}', self.sha256):
            raise ValueError('frozen data requires SHA-256')

    def resolve(self, source_root: Path) -> Path:
        root = Path(source_root).resolve()
        path = root / self.relative_path
        if not path.resolve().is_relative_to(root):
            raise ValueError('frozen data escapes package')
        for parent in (path, *path.parents):
            if parent == root:
                break
            if parent.is_symlink() or parent.is_junction():
                raise ValueError('frozen data cannot contain links')
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != self.sha256:
            raise ValueError('frozen data content differs from declaration')
        return path


@dataclass(frozen=True, slots=True)
class ObservationAvailability:
    """Explicit publication assumption for a provider's date-only timestamps."""
    timezone: str
    available_time: str
    day_offset: int = 0

    def __post_init__(self):
        ZoneInfo(self.timezone)
        if type(self.available_time) is not str or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', self.available_time):
            raise ValueError('observation availability requires HH:MM')
        if type(self.day_offset) is not int or self.day_offset < 0:
            raise ValueError('observation availability offset must be nonnegative')


@dataclass(frozen=True, slots=True)
class DatasetObservationInput:
    name: str
    dataset: Dataset
    symbol: str | None = None
    frequency: str = 'daily'
    history_start: date | None = None
    history_end: date | None = None
    coverage: DataCoverageRequirement = field(default_factory=lambda: DataCoverageRequirement(maximum_start_lag_days=None))
    asset: FrozenDataAsset | None = None
    calendar: str = 'SSE'
    availability: ObservationAvailability | None = None
    max_staleness_days: int | None = None
    required_from: date | None = None

    def __post_init__(self):
        if type(self.name) is not str or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', self.name):
            raise ValueError('observation requires a stable alias')
        if type(self.dataset) is not Dataset or self.dataset not in _DATASETS:
            raise ValueError('unsupported observation dataset')
        if type(self.coverage) is not DataCoverageRequirement:
            raise TypeError('observation requires typed coverage')
        if self.availability is not None and type(self.availability) is not ObservationAvailability:
            raise TypeError('observation requires typed availability')
        if self.required_from is not None:
            if type(self.required_from) is not date:
                raise TypeError('observation required-from requires a date')
            if (type(self.history_start) is not date or self.required_from < self.history_start
                    or self.history_end is not None or self.asset is not None or self.availability is None):
                raise ValueError('required-from requires a dynamic history start no later than activation and explicit availability')
        if self.max_staleness_days is not None and (type(self.max_staleness_days) is not int or self.max_staleness_days < 0):
            raise ValueError('observation staleness must be nonnegative days')
        for stamp in (self.history_start, self.history_end):
            if stamp is not None and type(stamp) is not date:
                raise TypeError('observation bounds require dates')
        if self.history_end is not None and (self.history_start is None or self.history_start > self.history_end):
            raise ValueError('fixed observation end requires an ordered start')
        if (self.dataset is Dataset.STRATEGY_FEATURE_EVIDENCE) != (self.asset is not None):
            raise ValueError('only frozen evidence declares an asset')
        if self.asset is not None and (type(self.asset) is not FrozenDataAsset or self.history_end is None):
            raise ValueError('frozen evidence requires an asset and fixed interval')
        if self.calendar not in ('SSE', 'SZSE'):
            raise ValueError('unsupported moneyflow calendar')
        # The DFLS boundary remains authoritative for dataset-specific fields.
        parameters = (MoneyflowParameters(('2000-01-04',)) if self.dataset is Dataset.STOCK_MONEYFLOW
                      else EvidenceParameters(Path.cwd().resolve(), self.asset.relative_path, self.asset.sha256)
                      if self.asset else NoParameters())
        DataRequest(self.dataset, self.symbol, '2000-01-04', '2000-01-04', None,
                    self.frequency, parameters)

    def data_key(self):
        return 'observation:' + self.name

    @property
    def activation_at(self):
        if self.required_from is None:
            return None
        policy = self.availability
        return datetime.combine(self.required_from + timedelta(days=policy.day_offset),
            time.fromisoformat(policy.available_time), ZoneInfo(policy.timezone))

    def inactive_on(self, end):
        return self.required_from is not None and end < self.required_from

    def bounds(self, start: date, end: date):
        if type(start) is not date or type(end) is not date or start > end:
            raise ValueError('observation request requires ordered dates')
        lower = self.history_start if self.history_start is not None else start
        upper = self.history_end if self.history_end is not None else end
        if lower > upper:
            raise ValueError('observation request has empty interval')
        return lower, upper

    def request(self, start: date, end: date, *, source_root: Path,
                trading_dates: tuple[str, ...] = ()) -> DataRequest | None:
        if self.inactive_on(end):
            return None
        lower, upper = self.bounds(start, end)
        parameters = NoParameters()
        if self.asset is not None:
            self.asset.resolve(source_root)
            parameters = EvidenceParameters(Path(source_root).resolve(), self.asset.relative_path, self.asset.sha256)
        elif self.dataset is Dataset.STOCK_MONEYFLOW:
            MoneyflowParameters(trading_dates)
            parameters = MoneyflowParameters(tuple(day for day in trading_dates if lower.isoformat() <= day <= upper.isoformat()))
        elif trading_dates:
            raise ValueError('only moneyflow consumes trading dates')
        return DataRequest(self.dataset, self.symbol, lower.isoformat(), upper.isoformat(), None,
                           self.frequency, parameters, self.coverage)

    def validate_request(self, request: DataRequest) -> None:
        """Check an explicit request against this declaration without data access."""
        if type(request) is not DataRequest:
            raise TypeError('observation requires a typed dataset request')
        if ((self.dataset, self.symbol, self.frequency, self.coverage) !=
                (request.dataset, request.symbol, request.frequency, request.coverage)):
            raise ValueError('observation binding differs from declaration')
        if self.history_start and request.start != self.history_start.isoformat():
            raise ValueError('observation binding differs from canonical start')
        if self.history_end and request.end != self.history_end.isoformat():
            raise ValueError('observation binding differs from fixed end')
        if self.asset and (request.parameters.source_path, request.parameters.source_sha256) != (self.asset.relative_path, self.asset.sha256):
            raise ValueError('observation binding differs from frozen asset')

    def to_dict(self):
        value = asdict(self)
        if self.required_from is None:
            value.pop('required_from')
        value['dataset'] = self.dataset.value
        for key in ('history_start', 'history_end', 'required_from'):
            if key in value:
                value[key] = getattr(self, key).isoformat() if getattr(self, key) else None
        return value

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value['dataset'] = Dataset(value['dataset'])
        value['coverage'] = DataCoverageRequirement(**value['coverage'])
        for key in ('history_start', 'history_end', 'required_from'):
            if value.get(key) is not None:
                value[key] = date.fromisoformat(value[key])
        if value.get('asset') is not None:
            value['asset'] = FrozenDataAsset(**value['asset'])
        if value.get('availability') is not None:
            value['availability'] = ObservationAvailability(**value['availability'])
        return cls(**value)


def observation_request_to_dict(request):
    value = asdict(request)
    value['dataset'] = request.dataset.value
    if isinstance(request.parameters, EvidenceParameters):
        value['parameters']['repository_root'] = str(request.parameters.repository_root)
    return value


def observation_request_from_dict(value):
    value = dict(value)
    dataset = Dataset(value['dataset'])
    raw = value['parameters']
    if dataset is Dataset.STOCK_MONEYFLOW:
        value['parameters'] = MoneyflowParameters(tuple(raw['trading_dates']))
    elif dataset is Dataset.STRATEGY_FEATURE_EVIDENCE:
        value['parameters'] = EvidenceParameters(Path(raw['repository_root']), raw['source_path'], raw['source_sha256'])
    else:
        value['parameters'] = NoParameters(**raw)
    if value.get('coverage') is not None:
        value['coverage'] = DataCoverageRequirement(**value['coverage'])
    return DataRequest(**value)


@dataclass(frozen=True, slots=True)
class DatasetObservationBinding:
    input: DatasetObservationInput
    request: DataRequest | None
    content_sha256: str | None
    inactive_through: date | None = None

    def __post_init__(self):
        if type(self.input) is not DatasetObservationInput:
            raise TypeError('observation binding requires typed input')
        if self.inactive_through is not None:
            if (type(self.inactive_through) is not date or not self.input.inactive_on(self.inactive_through)
                    or self.request is not None or self.content_sha256 is not None):
                raise ValueError('inactive binding requires an unstarted declaration without physical data')
            return
        if type(self.request) is not DataRequest:
            raise TypeError('observation binding requires typed input and request')
        if type(self.content_sha256) is not str or not re.fullmatch('[a-f0-9]{64}', self.content_sha256):
            raise ValueError('observation binding requires content SHA-256')
        self.input.validate_request(self.request)

    def to_dict(self):
        if self.inactive_through is not None:
            return {'input': self.input.to_dict(), 'inactive_through': self.inactive_through.isoformat()}
        return {'input': self.input.to_dict(), 'request': observation_request_to_dict(self.request),
                'content_sha256': self.content_sha256}

    @classmethod
    def from_dict(cls, value):
        if isinstance(value, Mapping) and set(value) == {'input', 'inactive_through'}:
            return cls(DatasetObservationInput.from_dict(value['input']), None, None,
                       date.fromisoformat(value['inactive_through']))
        if not isinstance(value, Mapping) or set(value) != {'input', 'request', 'content_sha256'}:
            raise ValueError('unsupported observation binding')
        return cls(DatasetObservationInput.from_dict(value['input']),
                   observation_request_from_dict(value['request']), value['content_sha256'])


class TableObservationStatus(StrEnum):
    ACTIVE = 'ACTIVE'
    INACTIVE = 'INACTIVE'


@dataclass(frozen=True, slots=True)
class TableHistoryView:
    """Immutable visible rows in source order; no access to future row storage."""
    as_of: datetime
    rows: tuple
    columns: tuple[str, ...]
    source_time_field: str = 'Date'
    status: TableObservationStatus = TableObservationStatus.ACTIVE

    def __post_init__(self):
        if type(self.as_of) is not datetime or self.as_of.utcoffset() is None:
            raise ValueError('observation view requires aware time')
        if type(self.status) is not TableObservationStatus or (self.status is TableObservationStatus.INACTIVE and self.rows):
            raise ValueError('inactive observations must have no rows')
        from .equity_replay import _Row
        object.__setattr__(self, 'rows', tuple(row if type(row) is _Row else _Row(dict(row)) for row in self.rows))

    def __len__(self):
        return len(self.rows)

    def to_frame(self):
        return pd.DataFrame([dict(row) for row in self.rows], columns=self.columns)

    @property
    def observation_count(self):
        return len(self.rows)

    @property
    def session_count(self):
        return len({pd.Timestamp(row[self.source_time_field]).date() for row in self.rows})


@dataclass(frozen=True, slots=True)
class PreparedObservationTable:
    content_sha256: str
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    _rows: tuple
    _available: tuple[datetime, ...]
    _order: tuple[int, ...]
    source_time_field: str = 'Date'
    _monotonic_availability: bool = False
    source_timezone: str = 'UTC'
    _inactive_before: datetime | None = None

    def __post_init__(self):
        if not re.fullmatch('[a-f0-9]{64}', self.content_sha256):
            raise ValueError('prepared observation requires content SHA-256')
        if not self._rows or len(self._rows) != len(self._available) or tuple(sorted(self._order)) != tuple(range(len(self._rows))):
            raise ValueError('prepared observation index differs from rows')
        if any(type(stamp) is not datetime or stamp.utcoffset() is None for stamp in self._available) or tuple(sorted(self._available)) != self._available:
            raise ValueError('prepared observation availability must be ordered and aware')

    @classmethod
    def from_frame(cls, frame, identity: DataIdentity, *, declaration=None):
        if not isinstance(frame, pd.DataFrame) or type(identity) is not DataIdentity:
            raise TypeError('observation preparation requires a published table and identity')
        if frame.empty:
            raise ValueError('observation table is empty')
        temporal = identity.temporal_contract
        source, available = temporal.source_time_field, temporal.availability_time_field
        primary = identity.primary_key
        if not primary or not set((*primary, source, available)).issubset(frame.columns):
            raise ValueError('observation requires declared primary key and time columns')
        if frame[list(primary)].isna().any().any() or frame.duplicated(list(primary)).any():
            raise ValueError('observation primary key is missing or duplicated')
        if declaration is not None and (declaration.dataset, declaration.symbol) != (identity.dataset, identity.symbol):
            raise ValueError('observation identity differs from declaration')
        policy = declaration.availability if declaration is not None else None
        stamps = pd.to_datetime(frame[available], errors='raise')
        if stamps.isna().any():
            raise ValueError('observation availability cannot be missing')
        if not isinstance(stamps.dtype, pd.DatetimeTZDtype):
            if policy is None:
                raise ValueError('date-only observation requires explicit publication timezone/time')
            clock = pd.Timedelta(hours=int(policy.available_time[:2]), minutes=int(policy.available_time[3:]))
            floor = stamps.dt.normalize() + clock + timedelta(days=policy.day_offset)
            stamps = stamps.where(stamps >= floor, floor).dt.tz_localize(policy.timezone, ambiguous='raise', nonexistent='raise')
        source_times = pd.to_datetime(frame[source], errors='raise')
        if source_times.isna().any():
            raise ValueError('observation source time cannot be missing')
        if not isinstance(source_times.dtype, pd.DatetimeTZDtype):
            source_times = source_times.dt.tz_localize(policy.timezone if policy else stamps.dt.tz,
                                                      ambiguous='raise', nonexistent='raise')
        if (source_times > stamps).any():
            raise ValueError('observation source time exceeds availability')
        stamps = stamps.dt.tz_convert('UTC')
        rows = []
        from .equity_replay import _Row
        for row in frame.to_dict('records'):
            converted = {}
            for key, value in row.items():
                if isinstance(value, pd.Timestamp):
                    value = value.to_pydatetime()
                if not isinstance(value, (str, int, float, bool, datetime, date, type(None))):
                    raise TypeError('observation rows require immutable scalar values')
                converted[key] = value
            rows.append(_Row(converted))
        times = tuple(stamps.array.to_pydatetime())
        order = tuple(sorted(range(len(rows)), key=lambda i: (times[i], i)))
        return cls(identity.content_sha256, tuple(frame.columns), primary, tuple(rows),
                   tuple(times[i] for i in order), order, source, order == tuple(range(len(rows))), str(source_times.dt.tz),
                   declaration.activation_at if declaration is not None else None)

    def view(self, when):
        if type(when) is not datetime or when.utcoffset() is None:
            raise ValueError('observation cutoff requires aware time')
        if self._inactive_before is not None and when < self._inactive_before:
            return TableHistoryView(when, (), self.columns, self.source_time_field, TableObservationStatus.INACTIVE)
        count = bisect_right(self._available, when)
        positions = self._order[:count] if self._monotonic_availability else sorted(self._order[:count])
        return TableHistoryView(when, tuple(self._rows[i] for i in positions), self.columns, self.source_time_field)


@dataclass(frozen=True, slots=True)
class InactiveObservationTable:
    """Declared absence before activation; contains no synthetic data identity."""
    binding: DatasetObservationBinding

    def __post_init__(self):
        if type(self.binding) is not DatasetObservationBinding or self.binding.inactive_through is None:
            raise ValueError('inactive table requires an explicit inactive binding')

    def view(self, when):
        if type(when) is not datetime or when.utcoffset() is None:
            raise ValueError('observation cutoff requires aware time')
        if when >= self.binding.input.activation_at:
            raise ValueError('OBSERVATION_ACTIVATED_REQUIRES_PREPARATION: ' + self.binding.input.name)
        return TableHistoryView(when, (), (), status=TableObservationStatus.INACTIVE)
