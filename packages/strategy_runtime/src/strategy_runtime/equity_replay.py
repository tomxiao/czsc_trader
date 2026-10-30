"""As-of feature replay and transactional, explicitly owned strategy state."""
from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from enum import StrEnum
import math
from statistics import median
from time import perf_counter
from types import MappingProxyType
from typing import Generic, TypeVar

import pandas as pd
import numpy as np

from dataflows import BarFrequency, MarketId, TimeInterval, TradingSession
from .equity import DecisionPoint, EquityPlan, EquityPortfolio, equity_hash
from .equity_features import (FeatureGraph, FeatureView, HistoryView, Lag, Mean,
                              NotReady, RawField, ReadyValue, SameLocalSlotMedian, TrueRange,
                              _HistoryAppend, _history_insert)


class StateValueType(StrEnum):
    BOOL = 'bool'
    INT = 'int'
    FLOAT = 'float'
    STR = 'str'
    DATETIME = 'datetime'


@dataclass(frozen=True, slots=True)
class StateField:
    key: str
    value_type: StateValueType
    nullable: bool = False

    def __post_init__(self):
        if type(self.key) is not str or not self.key or type(self.value_type) is not StateValueType:
            raise TypeError('state field requires a name and StateValueType')
        if type(self.nullable) is not bool:
            raise TypeError('state nullable must be boolean')


StateScalar = bool | int | float | str | datetime | None


@dataclass(frozen=True, slots=True)
class StateRecord:
    values: tuple[tuple[str, StateScalar], ...] = ()

    def __post_init__(self):
        if type(self.values) is not tuple:
            raise TypeError('state record requires immutable field pairs')
        keys = set()
        for item in self.values:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError('state entries require pairs')
            key, value = item
            if type(key) is not str or not key or key in keys:
                raise ValueError('state keys must be unique nonempty strings')
            keys.add(key)
            if type(value) not in (bool, int, float, str, datetime, type(None)):
                raise TypeError('state values must be typed immutable scalars')
            if type(value) is float and not math.isfinite(value):
                raise ValueError('state floats must be finite')
            if type(value) is datetime and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError('state datetimes must be timezone aware')

    def get(self, key: str) -> StateScalar:
        for name, value in self.values:
            if name == key:
                return value
        raise KeyError(key)


@dataclass(frozen=True, slots=True)
class StrategyStateSchema:
    account_fields: tuple[StateField, ...] = ()
    cycle_fields: tuple[StateField, ...] = ()

    def __post_init__(self):
        for fields in (self.account_fields, self.cycle_fields):
            if type(fields) is not tuple or any(type(item) is not StateField for item in fields):
                raise TypeError('state schema requires tuples of StateField')
            if len({item.key for item in fields}) != len(fields):
                raise ValueError('duplicate state schema field')

    def validate_record(self, record: StateRecord, *, scope: str):
        if type(record) is not StateRecord or scope not in ('account', 'cycle'):
            raise TypeError('typed state record and explicit scope required')
        fields = self.account_fields if scope == 'account' else self.cycle_fields
        values = dict(record.values)
        if set(values) != {item.key for item in fields}:
            raise ValueError('state fields differ from declared ' + scope + ' schema')
        types = {StateValueType.BOOL: bool, StateValueType.INT: int, StateValueType.FLOAT: float,
                 StateValueType.STR: str, StateValueType.DATETIME: datetime}
        for item in fields:
            value = values[item.key]
            if value is None and item.nullable:
                continue
            if type(value) is not types[item.value_type]:
                raise TypeError('state field type differs: ' + item.key)

    def validate_result(self, result):
        if type(result) is not StepResult:
            raise TypeError('V3 step requires StepResult')
        self.validate_record(result.account, scope='account')
        if result.cycle_values is not None:
            self.validate_record(result.cycle_values, scope='cycle')

    def to_dict(self):
        return {scope: [{'key': item.key, 'value_type': item.value_type.value,
                         'nullable': item.nullable} for item in fields]
                for scope, fields in (('account_fields', self.account_fields),
                                      ('cycle_fields', self.cycle_fields))}

    @classmethod
    def from_dict(cls, value):
        if set(value) != {'account_fields', 'cycle_fields'}:
            raise ValueError('unsupported strategy state schema')
        return cls(*(tuple(StateField(item['key'], StateValueType(item['value_type']), item['nullable'])
                           for item in value[scope]) for scope in ('account_fields', 'cycle_fields')))


@dataclass(frozen=True, slots=True)
class CycleState:
    cycle_id: str
    entry_at: datetime
    values: StateRecord

    def __post_init__(self):
        if type(self.cycle_id) is not str or not self.cycle_id or type(self.values) is not StateRecord:
            raise TypeError('cycle state requires its execution identity and typed values')
        if type(self.entry_at) is not datetime or self.entry_at.tzinfo is None:
            raise ValueError('cycle entry must be timezone aware')


@dataclass(frozen=True, slots=True)
class StrategyState:
    revision: int = 0
    account: StateRecord = field(default_factory=StateRecord)
    cycle: CycleState | None = None
    binding: str | None = None

    def __post_init__(self):
        if type(self.revision) is not int or self.revision < 0 or type(self.account) is not StateRecord:
            raise TypeError('strategy state requires a nonnegative revision and typed account record')
        if self.cycle is not None and type(self.cycle) is not CycleState:
            raise TypeError('strategy cycle must be CycleState or None')
        if self.binding is not None and (type(self.binding) is not str or not self.binding):
            raise TypeError('state ownership binding must be a nonempty string or None')


@dataclass(frozen=True, slots=True)
class StepResult:
    decision: object
    account: StateRecord = field(default_factory=StateRecord)
    cycle_values: StateRecord | None = None

    def __post_init__(self):
        from .equity_definition import EquityDecision
        if type(self.decision) is not EquityDecision or self.decision.explanation is None:
            raise TypeError('V3 decision requires EquityDecision with structured facts')
        if type(self.account) is not StateRecord or (self.cycle_values is not None
                                                   and type(self.cycle_values) is not StateRecord):
            raise TypeError('V3 proposed state must use immutable StateRecord')


@dataclass(frozen=True, slots=True)
class StepContext:
    point: DecisionPoint
    portfolio: EquityPortfolio
    parameters: Mapping
    features: FeatureView
    history: HistoryView
    auxiliary_histories: Mapping = field(default_factory=dict)
    session: TradingSession | None = None
    session_available_at: datetime | None = None

    def __post_init__(self):
        if type(self.point) is not DecisionPoint or type(self.portfolio) is not EquityPortfolio:
            raise TypeError('step context requires a typed point and confirmed portfolio')
        if type(self.features) is not FeatureView or type(self.history) is not HistoryView:
            raise TypeError('step context requires immutable feature/history views')
        from .equity_definition import _freeze
        object.__setattr__(self, 'parameters', _freeze(dict(self.parameters)))
        if any(type(view) is not HistoryView for view in self.auxiliary_histories.values()):
            raise TypeError('auxiliary observations require HistoryView')
        object.__setattr__(self, 'auxiliary_histories', MappingProxyType(dict(self.auxiliary_histories)))
        if self.features.as_of != self.point.decision_at or self.history.as_of != self.point.decision_at:
            raise ValueError('feature/history views must belong to this exact decision')
        if any(view.as_of != self.point.decision_at for view in self.auxiliary_histories.values()):
            raise ValueError('auxiliary views must belong to this exact decision')
        if self.session is not None:
            if (type(self.session) is not TradingSession or type(self.session_available_at) is not datetime
                    or self.session_available_at.tzinfo is None
                    or self.session_available_at > self.point.decision_at):
                raise ValueError('session context requires an already available typed calendar')


class _Row(Mapping):
    __slots__ = ('_values',)

    def __init__(self, values):
        object.__setattr__(self, '_values', MappingProxyType(dict(values)))

    def __setattr__(self, name, value):
        raise TypeError('prepared rows are immutable')

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def get(self, key, default=None):
        return self._values.get(key, default)

    def items(self):
        return self._values.items()

    def keys(self):
        return self._values.keys()

    def values(self):
        return self._values.values()

    def __reduce__(self):
        return type(self), (dict(self._values),)


def _frame_records(frame, time_columns):
    """Convert aware datetime columns in bulk, retaining ordinary record boxing."""
    columns = tuple(name for name in time_columns if name in frame
                    and isinstance(frame[name], pd.Series)
                    and isinstance(frame[name].dtype, pd.DatetimeTZDtype))
    if columns:
        frame = frame.copy(deep=False)
        for name in columns:
            frame[name] = pd.Series(frame[name].array.to_pydatetime(), index=frame.index,
                                    dtype=object)
    return frame.to_dict('records')


@dataclass(frozen=True, slots=True)
class _ReplayData:
    rows: tuple
    columns: tuple[str, ...]
    constraints: tuple
    starts: tuple[datetime, ...]
    ends: tuple[datetime, ...]
    ready_at: tuple[datetime, ...]
    observed: tuple[bool, ...]
    days: tuple
    slots: tuple
    events: tuple[int, ...]
    latency_seconds: int
    identity: str


@dataclass(frozen=True, slots=True)
class PreparedReplay:
    _data: _ReplayData
    graph: FeatureGraph
    _auxiliary: tuple = ()
    _sessions: tuple = ()
    _calendar_intervals: tuple = ()
    identity: str = ''

    @classmethod
    def from_frames(cls, bars, constraints, graph, *, latency_seconds=0,
                    auxiliary_histories=None, sessions=None, trading_sessions=()):
        if type(graph) is not FeatureGraph or type(latency_seconds) is not int or latency_seconds < 0:
            raise TypeError('replay requires a typed graph and nonnegative integer latency')
        required = {'BarStart', 'Date', 'AvailableDate', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount'}
        if not required.issubset(bars.columns) or bars.empty:
            raise ValueError('replay requires nonempty complete OHLCV observations')
        for column in ('BarStart', 'Date', 'AvailableDate'):
            if not isinstance(bars[column].dtype, pd.DatetimeTZDtype) or bars[column].isna().any():
                raise ValueError('replay timestamps must be aware and finite')
        if not bars.Date.is_monotonic_increasing or bars.Date.duplicated().any():
            raise ValueError('replay completion times must be unique and ordered')
        if (bars.AvailableDate < bars.Date).any() or (bars.BarStart >= bars.Date).any():
            raise ValueError('replay observations must complete before availability')
        if any(a < b for a, b in zip(bars.BarStart.iloc[1:], bars.Date.iloc[:-1])):
            raise ValueError('replay bars must not overlap')
        rows = []
        for record in _frame_records(bars, ('BarStart', 'Date', 'AvailableDate')):
            status = record.get('BarStatus', 'OBSERVED')
            if status not in ('OBSERVED', 'MISSING', 'ZERO_VOLUME'):
                raise ValueError('unsupported observed bar status')
            if status == 'MISSING':
                if not all(pd.isna(record[key]) for key in ('Open', 'High', 'Low', 'Close', 'Volume', 'Amount')):
                    raise ValueError('missing bars cannot fabricate observations')
            else:
                numbers = [float(record[key]) for key in ('Open', 'High', 'Low', 'Close', 'Volume', 'Amount')]
                opening, high, low, close, volume, amount = numbers
                if (not all(math.isfinite(value) for value in numbers) or min(numbers[:4]) <= 0
                        or min(volume, amount) < 0 or high < max(opening, close, low)
                        or low > min(opening, close, high)):
                    raise ValueError('invalid replay OHLCV observation')
                if 'BarStatus' in record and ((status == 'ZERO_VOLUME') != (volume == 0)):
                    raise ValueError('replay volume differs from observation status')
            if 'ExecutionBlocked' in record and type(record['ExecutionBlocked']) is not bool:
                raise TypeError('execution block requires boolean')
            if any(not isinstance(value, (str, int, float, bool, datetime, type(None))) for value in record.values()):
                raise TypeError('replay rows require immutable scalar observations')
            rows.append(_Row(record))
        constraint_map = {}
        if not {'Date', 'AvailableDate', 'QuantityStep', 'PriceTick', 'Tradable'}.issubset(constraints.columns):
            raise ValueError('replay requires dated trading constraints')
        for record in _frame_records(constraints, ('Date', 'AvailableDate', 'SettlementAt')):
            for key in ('Date', 'AvailableDate', 'SettlementAt'):
                if key in record and record[key] is not None:
                    stamp = record[key] if type(record[key]) is datetime else pd.Timestamp(record[key])
                    if pd.isna(stamp) or stamp.tzinfo is None:
                        raise ValueError('constraint times must be aware and finite')
                    record[key] = stamp if type(stamp) is datetime else stamp.to_pydatetime()
            if record['Date'] in constraint_map:
                raise ValueError('duplicate trading constraint')
            constraint_map[record['Date']] = _Row(record)
        local = bars.BarStart.dt.tz_convert('America/New_York')
        starts, ends = tuple(row['BarStart'] for row in rows), tuple(row['Date'] for row in rows)
        ready = tuple(max(row['Date'], row['AvailableDate'] + timedelta(seconds=latency_seconds)) for row in rows)
        dated = tuple(constraint_map.get(stamp) for stamp in starts)
        identity = equity_hash({'bars': [{key: None if type(value) is float and math.isnan(value) else value
                                        for key, value in row.items()} for row in rows],
                                'constraints': [dict(row) if row is not None else None for row in dated],
                                'latency_seconds': latency_seconds})
        data = _ReplayData(tuple(rows), tuple(bars.columns), dated, starts, ends, ready,
            tuple(row.get('BarStatus', 'OBSERVED') == 'OBSERVED' for row in rows),
            tuple(local.dt.date), tuple(local.dt.hour * 60 + local.dt.minute),
            tuple(sorted(range(len(rows)), key=lambda i: (ready[i], i))), latency_seconds, identity)
        auxiliary = []
        if auxiliary_histories is not None:
            if not isinstance(auxiliary_histories, Mapping):
                raise TypeError('auxiliary histories require named DataFrames')
            from dataclasses import replace
            for name, frame in auxiliary_histories.items():
                if type(name) is not str or not isinstance(frame, pd.DataFrame):
                    raise TypeError('auxiliary histories require named DataFrames')
                original_columns = tuple(column for column in
                    ('Date', 'AvailableDate', 'BarStart', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount')
                    if column in frame)
                if 'BarStart' not in frame:
                    raise ValueError('V3 auxiliary preparation requires explicit BarStart')
                frame = frame if 'Amount' in frame else frame.assign(Amount=0.)
                empty = pd.DataFrame(columns=('Date', 'AvailableDate', 'QuantityStep', 'PriceTick', 'Tradable'))
                auxiliary_data = cls.from_frames(frame, empty, FeatureGraph(), latency_seconds=latency_seconds)._data
                auxiliary.append((name, replace(auxiliary_data, columns=original_columns)))
        calendars, intervals = [], []
        if sessions is not None or trading_sessions:
            if (sessions is None or type(trading_sessions) is not tuple
                    or not trading_sessions or any(type(item) is not TradingSession for item in trading_sessions)):
                raise TypeError('session context requires its table and typed calendar tuple')
            if not {'Date', 'AvailableDate', 'SessionDate'}.issubset(sessions.columns):
                raise ValueError('session evidence requires Date, AvailableDate and SessionDate')
            days = tuple(item.session_date for item in trading_sessions)
            if tuple(sorted(set(days))) != days or len(sessions) != len(days):
                raise ValueError('session calendar must be unique ordered and aligned')
            known = set()
            for session, row in zip(trading_sessions, sessions.itertuples(), strict=True):
                stamp, available = pd.Timestamp(row.Date), pd.Timestamp(row.AvailableDate)
                if (stamp.tzinfo is None or available.tzinfo is None or pd.isna(stamp) or pd.isna(available)
                        or str(row.SessionDate) != session.session_date.isoformat()
                        or stamp != session.segments[0].start or session.timezone != 'America/New_York'):
                    raise ValueError('session evidence differs from US calendar')
                calendar_index = len(calendars)
                calendars.append((session, available.to_pydatetime()))
                for interval in session.bars(BarFrequency.M30):
                    key = interval.start, interval.end
                    if key in known:
                        raise ValueError('execution interval has ambiguous sessions')
                    known.add(key)
                    intervals.append((key, calendar_index))
        prepared_identity = equity_hash({'primary': data.identity,
            'auxiliary': [(name, item.identity, item.columns) for name, item in sorted(auxiliary)],
            'sessions': [{'day': item.session_date.isoformat(), 'timezone': item.timezone,
                          'segments': [(part.start, part.end) for part in item.segments],
                          'available': available} for item, available in calendars]})
        return cls(data, graph, tuple(auxiliary), tuple(calendars), tuple(intervals), prepared_identity)

    def with_graph(self, graph):
        if type(graph) is not FeatureGraph:
            raise TypeError('replay requires FeatureGraph')
        return PreparedReplay(self._data, graph, self._auxiliary, self._sessions,
                              self._calendar_intervals, self.identity)


class _Visibility:
    """Ordered availability events and a Fenwick index over event-time positions."""
    def __init__(self, data):
        self.data = data
        self.active = [False] * len(data.rows)
        self.ordered_arrivals = all(earlier <= later for earlier, later in
                                    zip(data.ready_at, data.ready_at[1:]))
        self.tree = None if self.ordered_arrivals else [0] * (len(data.rows) + 1)
        self.count = 0
        self.event = 0
        self.latest_completed = -1
        self.observed_indices = tuple(i for i, value in enumerate(data.observed) if value)
        self.prefix = 0
        self.history_root = None
        self.history_columns = tuple(name for name in data.columns if name not in ('BarStatus', 'ExecutionBlocked'))
        self.visible_rows = {}

    def advance(self, when):
        while self.event < len(self.data.events):
            index = self.data.events[self.event]
            if self.data.ready_at[index] > when:
                break
            self.latest_completed = max(self.latest_completed, index)
            if self.data.observed[index]:
                self.active[index] = True
                self.count += 1
                row = _Row({key: self.data.rows[index][key] for key in self.history_columns})
                self.visible_rows[index] = row
                if self.ordered_arrivals:
                    # Certification makes every visible observation set a prefix.
                    # Keep only the already-visible past, with O(1) append work.
                    self.history_root = _HistoryAppend(row, self.history_root, self.count,
                                                       self.data.ready_at[index])
                else:
                    self.history_root = _history_insert(self.history_root, index, row, self.data.ready_at[index])
                    cursor = index + 1
                    while cursor < len(self.tree):
                        self.tree[cursor] += 1
                        cursor += cursor & -cursor
            self.event += 1
        while self.prefix < len(self.observed_indices) and self.active[self.observed_indices[self.prefix]]:
            self.prefix += 1

    def row(self, offset):
        if offset < 0 or offset >= self.count:
            return None
        if self.prefix == self.count:
            return self.observed_indices[self.count - 1 - offset]
        rank, index = self.count - offset, 0
        bit = 1 << (len(self.tree).bit_length() - 1)
        while bit:
            proposed = index + bit
            if proposed < len(self.tree) and self.tree[proposed] < rank:
                index = proposed
                rank -= self.tree[proposed]
            bit >>= 1
        return index

    def history_view(self, when):
        recent = tuple(self.visible_rows[self.row(offset)] for offset in range(min(2, self.count)))
        return HistoryView(when, self.history_root, self.count, recent, self.history_columns)


class _FeatureEvaluator:
    def __init__(self, data, graph, visibility):
        self.data, self.graph, self.visibility = data, graph, visibility
        self.nodes = {node.key: node for node in graph.nodes}
        self.by_slot = {}
        same_slot_required = any(type(node) is SameLocalSlotMedian for node in graph.nodes)
        seen = set()
        for i, slot in enumerate(data.slots):
            if data.observed[i]:
                if same_slot_required:
                    key = data.days[i], slot
                    if (key in seen or slot < 570 or slot >= 960 or (slot - 570) % 30
                            or data.starts[i].second or data.starts[i].microsecond):
                        raise ValueError('same-slot features require unique 30-minute US RTH local slots')
                    seen.add(key)
                self.by_slot.setdefault(slot, []).append(i)
        # This lowering is legal only when every observed sequence seen at a
        # decision is a prefix. Nonmonotonic publication retains as-of evaluation.
        self._prefix_outputs = None
        if visibility.ordered_arrivals:
            self._prefix_outputs = self._compile_prefix()

    def _compile_prefix(self):
        observed = self.visibility.observed_indices
        size = len(observed)
        positions = {index: rank for rank, index in enumerate(observed)}
        columns = {}

        def shifted(values, ready, periods):
            result, mask = np.full(size, np.nan), np.zeros(size, dtype=bool)
            if periods == 0:
                result[:] = values
                mask[:] = ready
            elif periods < size:
                result[periods:], mask[periods:] = values[:-periods], ready[:-periods]
            return result, mask

        def compile_node(key):
            if key in columns:
                return columns[key]
            node = self.nodes[key]
            if type(node) is RawField:
                values = np.fromiter((float(self.data.rows[index][node.field.value]) for index in observed),
                                     dtype=float, count=size)
                ready = np.ones(size, dtype=bool)
            elif type(node) is Lag:
                values, ready = shifted(*compile_node(node.source), node.bars)
            elif type(node) is TrueRange:
                high, high_ready = compile_node(node.high)
                low, low_ready = compile_node(node.low)
                previous, previous_ready = shifted(*compile_node(node.close), 1)
                with np.errstate(invalid='ignore', over='ignore'):
                    values = np.maximum(high - low, np.maximum(np.abs(high - previous), np.abs(low - previous)))
                ready = high_ready & low_ready & previous_ready
            elif type(node) is Mean:
                source, source_ready = compile_node(node.source)
                # CPython 3.12 sum(float) uses compensation. NumPy reduction,
                # prefix sums and incremental means are not bitwise substitutes.
                # Convert to Python floats, then compute each fixed window once.
                items, valid = source.tolist(), source_ready.tolist()
                values, ready = np.full(size, np.nan), np.zeros(size, dtype=bool)
                for right in range(node.window - 1, size):
                    left = right - node.window + 1
                    if all(valid[left:right + 1]):
                        values[right] = sum(items[left:right + 1]) / node.window
                        ready[right] = True
            elif type(node) is SameLocalSlotMedian:
                source, _ = compile_node(node.source)
                at_anchor, ready_at_anchor = np.full(size, np.nan), np.zeros(size, dtype=bool)
                for group in self.by_slot.values():
                    indices = np.fromiter((positions[index] for index in group), dtype=np.intp, count=len(group))
                    if len(indices) <= node.sessions:
                        continue
                    samples = source[indices]
                    windows = np.lib.stride_tricks.sliding_window_view(samples, node.sessions)[:-1]
                    with np.errstate(invalid='ignore', over='ignore'):
                        medians = np.median(windows, axis=1)
                    # Preserve statistics.median's signed-zero representation.
                    for index in np.flatnonzero(medians == 0.):
                        medians[index] = median(windows[index].tolist())
                    at_anchor[indices[node.sessions:]] = medians
                    ready_at_anchor[indices[node.sessions:]] = True
                values, ready = shifted(at_anchor, ready_at_anchor, node.anchor_lag)
            else:
                raise TypeError('unsupported feature node')
            values.setflags(write=False)
            ready.setflags(write=False)
            columns[key] = values, ready
            return values, ready

        return tuple((key, *compile_node(key)) for key in self.graph.outputs)

    def at(self, when):
        if self._prefix_outputs is not None:
            position = self.visibility.count - 1
            values = {key: ReadyValue(float(column[position])) if position >= 0 and ready[position] else NotReady()
                      for key, column, ready in self._prefix_outputs}
            return FeatureView(when, values)
        cache, row_cache = {}, {}

        def row(offset):
            if offset not in row_cache:
                row_cache[offset] = self.visibility.row(offset)
            return row_cache[offset]

        def calculate(key, offset=0):
            identity = key, offset
            if identity in cache:
                return cache[identity]
            node = self.nodes[key]
            current = row(offset)
            value = None
            if current is not None:
                if type(node) is RawField:
                    value = float(self.data.rows[current][node.field.value])
                elif type(node) is Lag:
                    value = calculate(node.source, offset + node.bars)
                elif type(node) is TrueRange:
                    high, low = calculate(node.high, offset), calculate(node.low, offset)
                    previous = calculate(node.close, offset + 1)
                    if high is not None and low is not None and previous is not None:
                        value = max(high - low, abs(high - previous), abs(low - previous))
                elif type(node) is Mean:
                    # Deliberately preserve chronological Python float addition.
                    values = [calculate(node.source, offset + j) for j in range(node.window - 1, -1, -1)]
                    if all(item is not None for item in values):
                        value = sum(values) / node.window
                elif type(node) is SameLocalSlotMedian:
                    anchor = row(offset + node.anchor_lag)
                    if anchor is not None:
                        candidates = self.by_slot[self.data.slots[anchor]]
                        position = bisect_left(candidates, anchor) - 1
                        selected, days = [], set()
                        source = self.nodes[node.source]
                        while position >= 0 and len(selected) < node.sessions:
                            index = candidates[position]
                            day = self.data.days[index]
                            if (day < self.data.days[anchor] and self.visibility.active[index]
                                    and day not in days):
                                selected.append(float(self.data.rows[index][source.field.value]))
                                days.add(day)
                            position -= 1
                        if len(selected) == node.sessions:
                            value = float(median(selected))
            cache[identity] = value
            return value

        values = {}
        for key in self.graph.outputs:
            value = calculate(key)
            values[key] = NotReady() if value is None else ReadyValue(float(value))
        return FeatureView(when, values)


ResultT = TypeVar('ResultT')


@dataclass(frozen=True, slots=True)
class ReplayStatistics:
    feature_seconds: float
    replay_seconds: float
    rows: int
    decisions: int
    source_checks: int = 0
    source_bytes_read: int = 0
    module_loads: int = 0


@dataclass(frozen=True, slots=True)
class ReplayOutcome(Generic[ResultT]):
    execution_result: ResultT
    state: StrategyState
    statistics: ReplayStatistics


class ReplayFailure(RuntimeError):
    """One interval failed; its predecessor state remains committed, never success."""
    def __init__(self, committed_state, next_execution_start, cause):
        self.committed_state = committed_state
        self.next_execution_start = next_execution_start
        self.cause = cause
        super().__init__(f'replay failed at {next_execution_start.isoformat()}: {cause}')


def _plan(decision, point, portfolio, reference, spec, spec_hash, implementation, owner, fee_rate):
    target = decision.target
    side, quantity, limit = 'HOLD', 0, None
    if target == 1 and portfolio.quantity == 0:
        tick = Decimal(str(spec.price_tick))
        limit = float((Decimal(str(reference)) * (1 + Decimal(str(spec.buy_premium))) / tick)
                      .to_integral_value(rounding=ROUND_FLOOR) * tick)
        if limit <= 0:
            raise ValueError('buy limit must remain positive')
        quantity = int(Decimal(str(portfolio.cash)) /
                       (Decimal(str(limit)) * (1 + Decimal(str(fee_rate))) * spec.quantity_step)) * spec.quantity_step
        side = 'BUY' if quantity else 'WAIT'
    elif target == 0 and portfolio.quantity:
        side, quantity = 'SELL', portfolio.quantity
    explanation = decision.explanation.to_dict()
    payload = {'candidate': owner, 'implementation': implementation, 'specification': spec_hash,
               'point': {'observed_through': point.observed_through, 'decision_at': point.decision_at,
                         'execution_interval': {'start': point.execution_interval.start, 'end': point.execution_interval.end}},
               'target': target, 'quantity': quantity, 'side': side, 'limit': limit,
               'revision': portfolio.revision, 'reference': reference, 'fee_rate': fee_rate,
               'explanation': explanation}
    return EquityPlan(equity_hash(payload), point, float(target), quantity, side, limit,
                      portfolio.revision, reference, spec_hash, explanation)


def run_replay(prepared, candidate, executor, *, start, end, fee_rate, initial_state=None, owner=None):
    """Load the strategy once and execute one independent account in memory."""
    from dataclasses import replace
    started = perf_counter()
    with candidate.bind_replay() as source_scope:
        outcome = _run_replay(prepared, candidate, executor, start=start, end=end,
                              fee_rate=fee_rate, initial_state=initial_state, owner=owner)
    return replace(outcome, statistics=replace(outcome.statistics, replay_seconds=perf_counter() - started,
        source_checks=source_scope.checks, source_bytes_read=source_scope.bytes_read,
        module_loads=source_scope.loads))


def _run_replay(prepared, candidate, executor, *, start, end, fee_rate, initial_state=None, owner=None):
    """Replay one independent account; features/state never hold future prices."""
    started = perf_counter()
    if type(prepared) is not PreparedReplay:
        raise TypeError('V3 replay requires PreparedReplay')
    definition = candidate.definition
    spec, schema = definition.execution_spec, definition.state_schema
    if (definition.contract_version != 3 or spec.market_id is not MarketId.US
            or spec.decision_clock is not BarFrequency.M30):
        raise ValueError('V3 replay supports explicit US M30 research definitions only')
    if definition.feedback_mode not in ('CONFIRMED_EXECUTION', 'CONFIRMED_CLOSED_CYCLE_V1'):
        raise ValueError('V3 state requires confirmed execution feedback')
    if definition.feature_graph != prepared.graph or spec.data_latency_seconds != prepared._data.latency_seconds:
        raise ValueError('prepared feature/visibility contract differs from candidate')
    if type(schema) is not StrategyStateSchema:
        raise TypeError('V3 replay requires StrategyStateSchema')
    if type(fee_rate) not in (int, float) or not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
        raise ValueError('fee rate must be finite in [0,1)')
    if any(type(stamp) is not datetime or stamp.tzinfo is None for stamp in (start, end)) or start >= end:
        raise ValueError('replay requires an aware positive window')
    owner = candidate.candidate_id if owner is None else owner
    if type(owner) is not str or not owner:
        raise TypeError('replay owner requires a nonempty identity')
    spec_hash, implementation = spec.fingerprint, candidate.implementation_hash
    binding = equity_hash({'owner': owner, 'implementation': implementation,
                           'specification': spec_hash, 'fee_rate': fee_rate,
                           'prepared': prepared.identity})
    if executor.spec.fingerprint != spec_hash or executor.fee_rate != fee_rate:
        raise ValueError('executor contract differs from replay')
    state = StrategyState() if initial_state is None else initial_state
    if type(state) is not StrategyState:
        raise TypeError('V3 replay requires typed initial state')
    if state.binding not in (None, binding) or (state.revision > 0 and state.binding is None):
        raise ValueError('strategy state belongs to a different replay owner or candidate')
    schema.validate_record(state.account, scope='account')
    if state.cycle is not None:
        schema.validate_record(state.cycle.values, scope='cycle')
    data = prepared._data
    visibility = _Visibility(data)
    feature_started = perf_counter()
    evaluator = _FeatureEvaluator(data, prepared.graph, visibility)
    feature_seconds = perf_counter() - feature_started
    auxiliary_data = dict(prepared._auxiliary)
    auxiliary = {}
    for declaration in definition.auxiliary_inputs:
        if declaration.name not in auxiliary_data:
            raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: ' + declaration.name)
        item = auxiliary_data[declaration.name]
        invalid_at = min((ready for row, ready, observed in zip(item.rows, item.ready_at, item.observed)
                          if observed and float(row['Volume']) <= 0), default=None)
        auxiliary[declaration.name] = (item, _Visibility(item), invalid_at)
    session_intervals = dict(prepared._calendar_intervals)
    if definition.session_context and not session_intervals:
        raise ValueError('session context requires certified calendar evidence')
    parameters = definition.parameters
    decisions = rows = 0
    for index, (bar_start, bar_end) in enumerate(zip(data.starts, data.ends)):
        if bar_start < start or bar_end > end:
            continue
        prior_state = state
        try:
            visibility.advance(bar_start)
            if visibility.count < definition.warmup_bars:
                raise ValueError('insufficient causal warmup at window start')
            constraint = data.constraints[index]
            if constraint is None or constraint['AvailableDate'] > bar_start:
                raise ValueError('no dated trading constraints available at execution start')
            observed_index = visibility.row(0)
            point = DecisionPoint(data.ends[observed_index], bar_start, TimeInterval(bar_start, bar_end))
            with executor.transaction():
                portfolio = executor.snapshot_at(point.observed_through, point.decision_at)
                if portfolio.revision != state.revision or bool(portfolio.quantity) != (state.cycle is not None):
                    raise ValueError('strategy state differs from confirmed execution revision/cycle')
                if state.cycle is not None and (state.cycle.entry_at != portfolio.cycle_entry
                                                or state.cycle.cycle_id != executor.cycle):
                    raise ValueError('strategy cycle identity differs from confirmed fill')
                reference = float(data.rows[observed_index]['Close']) * portfolio.reference_price_scale
                suppressed = not data.observed[visibility.latest_completed]
                if suppressed:
                    target = float(portfolio.quantity > 0)
                    payload = {'candidate': owner, 'implementation': implementation,
                               'specification': spec_hash,
                               'point': {'observed_through': point.observed_through, 'decision_at': point.decision_at,
                                         'execution_interval': {'start': bar_start, 'end': bar_end}},
                               'revision': portfolio.revision, 'reference': reference, 'target': target,
                               'signal_status': 'SUPPRESSED_UNOBSERVED_BAR'}
                    plan = EquityPlan(equity_hash(payload), point, target, 0, 'WAIT', None,
                                      portfolio.revision, reference, spec_hash,
                                      signal_status='SUPPRESSED_UNOBSERVED_BAR')
                    proposed_account = state.account
                    proposed_cycle = state.cycle.values if state.cycle is not None else None
                else:
                    feature_start = perf_counter()
                    features = evaluator.at(bar_start)
                    auxiliary_views = {}
                    for declaration in definition.auxiliary_inputs:
                        item, indexer, invalid_at = auxiliary[declaration.name]
                        indexer.advance(bar_start)
                        if (indexer.latest_completed < 0 or not item.observed[indexer.latest_completed]
                                or (invalid_at is not None and invalid_at <= bar_start)):
                            raise ValueError('AUXILIARY_INPUT_UNAVAILABLE: ' + declaration.name)
                        if indexer.count < declaration.warmup_bars:
                            raise ValueError('AUXILIARY_WARMUP_INSUFFICIENT: ' + declaration.name)
                        latest = indexer.row(0)
                        if (bar_start - item.ends[latest]).total_seconds() > declaration.max_age_seconds:
                            raise ValueError('AUXILIARY_INPUT_STALE: ' + declaration.name)
                        auxiliary_views[declaration.name] = indexer.history_view(bar_start)
                    session = session_available_at = None
                    if definition.session_context:
                        session_index = session_intervals.get((bar_start, bar_end))
                        if session_index is None:
                            raise ValueError('current execution interval has no unique session')
                        session, session_available_at = prepared._sessions[session_index]
                        if session_available_at > bar_start:
                            raise ValueError('CAUSAL_TIME_VIOLATION: session is not yet available')
                    feedback = portfolio
                    if definition.feedback_mode == 'CONFIRMED_EXECUTION' and portfolio.closed_cycle_feedback is not None:
                        from dataclasses import replace
                        feedback = replace(portfolio, closed_cycle_feedback=None)
                    if definition.feedback_mode == 'CONFIRMED_CLOSED_CYCLE_V1' and portfolio.closed_cycle_feedback is None:
                        raise ValueError('CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
                    ctx = StepContext(point, feedback, parameters, features,
                                      visibility.history_view(bar_start),
                                      auxiliary_views, session, session_available_at)
                    feature_seconds += perf_counter() - feature_start
                    result = candidate.step(ctx, state)
                    schema.validate_result(result)
                    proposed_account, proposed_cycle = result.account, result.cycle_values
                    if (portfolio.quantity or result.decision.target) and proposed_cycle is None:
                        raise ValueError('active or proposed entry requires explicit cycle state values')
                    plan = _plan(result.decision, point, portfolio, reference, spec, spec_hash,
                                 implementation, owner, fee_rate)
                    decisions += 1
                after = executor.execute(plan, data.rows[index], constraint=constraint)
                if after.revision != portfolio.revision + 1:
                    raise ValueError('replay transition did not advance exactly one account revision')
                cycle = None
                if after.quantity:
                    if proposed_cycle is None:
                        raise ValueError('actual holding requires proposed typed cycle state')
                    cycle = CycleState(executor.cycle, after.cycle_entry, proposed_cycle)
                    schema.validate_record(cycle.values, scope='cycle')
                state = StrategyState(after.revision, proposed_account, cycle, binding)
                rows += 1
        except Exception as error:
            state = prior_state
            raise ReplayFailure(state, bar_start, error) from error
    execution_result = executor.finish()
    return ReplayOutcome(execution_result, state,
                         ReplayStatistics(feature_seconds, perf_counter() - started, rows, decisions))
