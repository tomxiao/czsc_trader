"""Typed finite-window features evaluated on the history visible at a decision."""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
import re
from types import MappingProxyType


class BarField(StrEnum):
    OPEN = 'Open'
    HIGH = 'High'
    LOW = 'Low'
    CLOSE = 'Close'
    VOLUME = 'Volume'
    AMOUNT = 'Amount'


def _key(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', value):
        raise ValueError('feature keys require an ASCII identifier')


def _positive_integer(value):
    if type(value) is not int or value < 1:
        raise ValueError('feature window must be a positive integer')


@dataclass(frozen=True, slots=True)
class RawField:
    key: str
    field: BarField

    def __post_init__(self):
        _key(self.key)
        if type(self.field) is not BarField:
            raise TypeError('raw feature requires BarField')


@dataclass(frozen=True, slots=True)
class Lag:
    key: str
    source: str
    bars: int

    def __post_init__(self):
        _key(self.key)
        _key(self.source)
        _positive_integer(self.bars)


@dataclass(frozen=True, slots=True)
class TrueRange:
    key: str
    high: str
    low: str
    close: str

    def __post_init__(self):
        for value in (self.key, self.high, self.low, self.close):
            _key(value)


@dataclass(frozen=True, slots=True)
class Mean:
    key: str
    source: str
    window: int

    def __post_init__(self):
        _key(self.key)
        _key(self.source)
        _positive_integer(self.window)


@dataclass(frozen=True, slots=True)
class SameLocalSlotMedian:
    key: str
    source: str
    sessions: int = 20
    anchor_lag: int = 1
    timezone: str = 'America/New_York'

    def __post_init__(self):
        _key(self.key)
        _key(self.source)
        _positive_integer(self.sessions)
        if type(self.anchor_lag) is not int or self.anchor_lag < 0:
            raise ValueError('same-slot anchor lag must be a nonnegative integer')
        if self.timezone != 'America/New_York':
            raise ValueError('US equity same-slot features require America/New_York')


FeatureNode = RawField | Lag | TrueRange | Mean | SameLocalSlotMedian
_KINDS = {item.__name__: item for item in (RawField, Lag, TrueRange, Mean, SameLocalSlotMedian)}


def dependencies(node):
    if type(node) is RawField:
        return ()
    if type(node) is TrueRange:
        return node.high, node.low, node.close
    return (node.source,)


@dataclass(frozen=True, slots=True)
class FeatureGraph:
    nodes: tuple[FeatureNode, ...] = ()
    outputs: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.nodes) is not tuple or any(type(node) not in _KINDS.values() for node in self.nodes):
            raise TypeError('feature graph requires a tuple of supported typed nodes')
        by_key = {node.key: node for node in self.nodes}
        if len(by_key) != len(self.nodes):
            raise ValueError('duplicate feature key')
        if (type(self.outputs) is not tuple or len(set(self.outputs)) != len(self.outputs)
                or any(type(key) is not str or key not in by_key for key in self.outputs)):
            raise ValueError('feature outputs must reference unique declared nodes')
        visiting, complete = set(), set()

        def visit(key):
            if key in visiting:
                raise ValueError('feature graph contains a cycle')
            if key in complete:
                return
            if key not in by_key:
                raise ValueError('undeclared feature dependency: ' + key)
            visiting.add(key)
            node = by_key[key]
            for source in dependencies(node):
                visit(source)
            if type(node) is SameLocalSlotMedian:
                source = by_key[node.source]
                if type(source) is not RawField or source.field is not BarField.VOLUME:
                    raise ValueError('same-slot median requires a raw Volume node')
            visiting.remove(key)
            complete.add(key)

        for key in by_key:
            visit(key)

    def to_dict(self):
        from dataclasses import asdict
        return {'nodes': [{'kind': type(node).__name__, **asdict(node)} for node in self.nodes],
                'outputs': list(self.outputs), 'numeric_semantics': 'FLOAT64_CHRONOLOGICAL_V1'}

    @classmethod
    def from_dict(cls, value):
        if set(value) != {'nodes', 'outputs', 'numeric_semantics'} or value['numeric_semantics'] != 'FLOAT64_CHRONOLOGICAL_V1':
            raise ValueError('unsupported feature graph contract')
        nodes = []
        for item in value['nodes']:
            fields = dict(item)
            kind = fields.pop('kind')
            if kind not in _KINDS:
                raise ValueError('unsupported feature operator')
            if kind == 'RawField':
                fields['field'] = BarField(fields['field'])
            nodes.append(_KINDS[kind](**fields))
        return cls(tuple(nodes), tuple(value['outputs']))


@dataclass(frozen=True, slots=True)
class ReadyValue:
    value: float

    def __post_init__(self):
        if type(self.value) is not float or not math.isfinite(self.value):
            raise ValueError('ready features require a finite float')


@dataclass(frozen=True, slots=True)
class NotReady:
    reason: str = 'INSUFFICIENT_VISIBLE_HISTORY'


@dataclass(frozen=True, slots=True)
class FeatureView:
    """Immutable current-as-of values; retained views cannot observe later inserts."""
    as_of: datetime
    _values: object

    def __post_init__(self):
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError('feature view requires an aware as-of timestamp')
        values = dict(self._values)
        if any(type(value) not in (ReadyValue, NotReady) for value in values.values()):
            raise TypeError('features require typed readiness values')
        object.__setattr__(self, '_values', MappingProxyType(values))

    def get(self, key: str) -> ReadyValue | NotReady:
        return self._values[key]

    def __reduce__(self):
        return type(self), (self.as_of, dict(self._values))


@dataclass(frozen=True, slots=True)
class _HistoryNode:
    key: int
    row: object
    ready_at: datetime
    left: object = None
    right: object = None
    height: int = 1
    count: int = 1
    latest_ready_at: datetime | None = None


def _height(node):
    return 0 if node is None else node.height


def _count(node):
    return 0 if node is None else node.count


def _node(key, row, ready_at, left=None, right=None):
    latest = max(ready_at, left.latest_ready_at if left is not None else ready_at,
                 right.latest_ready_at if right is not None else ready_at)
    return _HistoryNode(key, row, ready_at, left, right, max(_height(left), _height(right)) + 1,
                        _count(left) + _count(right) + 1, latest)


def _rotate_left(root):
    right = root.right
    return _node(right.key, right.row, right.ready_at,
                 _node(root.key, root.row, root.ready_at, root.left, right.left), right.right)


def _rotate_right(root):
    left = root.left
    return _node(left.key, left.row, left.ready_at, left.left,
                 _node(root.key, root.row, root.ready_at, left.right, root.right))


def _history_insert(root, key, row, ready_at):
    """Persistent AVL insertion: roots retain only observations visible then."""
    if root is None:
        return _node(key, row, ready_at)
    if key == root.key:
        raise ValueError('duplicate visible observation')
    if key < root.key:
        root = _node(root.key, root.row, root.ready_at,
                     _history_insert(root.left, key, row, ready_at), root.right)
    else:
        root = _node(root.key, root.row, root.ready_at, root.left,
                     _history_insert(root.right, key, row, ready_at))
    balance = _height(root.left) - _height(root.right)
    if balance > 1:
        if key > root.left.key:
            root = _node(root.key, root.row, root.ready_at, _rotate_left(root.left), root.right)
        return _rotate_right(root)
    if balance < -1:
        if key < root.right.key:
            root = _node(root.key, root.row, root.ready_at, root.left, _rotate_right(root.right))
        return _rotate_left(root)
    return root


def _history_rows(root, skip=0):
    if root is None or skip >= root.count:
        return
    left_count = _count(root.left)
    if skip < left_count:
        yield from _history_rows(root.left, skip)
    if skip <= left_count:
        yield root.row
    yield from _history_rows(root.right, max(0, skip - left_count - 1))


@dataclass(frozen=True, slots=True)
class HistoryView:
    """Complete visible history; materialization is an explicit independent copy."""
    as_of: datetime
    _root: _HistoryNode | None
    _count: int
    _recent: tuple = ()
    _columns: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None:
            raise ValueError('history view requires an aware as-of timestamp')
        if type(self._count) is not int or self._count < 0 or type(self._recent) is not tuple:
            raise TypeError('history view requires a nonnegative count and immutable recent rows')
        if self._root is not None and type(self._root) is not _HistoryNode:
            raise TypeError('history view requires a persistent visible-history root')
        if _count(self._root) != self._count:
            raise ValueError('history view count differs from its visible snapshot')
        if self._root is not None and self._root.latest_ready_at > self.as_of:
            raise ValueError('history snapshot includes an unavailable observation')

    def __len__(self):
        return self._count

    def last(self, offset: int = 0):
        """Read either of the latest two observed rows without materialization."""
        if type(offset) is not int or offset not in (0, 1):
            raise ValueError('last supports offsets zero and one; use explicit to_frame for larger history')
        if offset >= len(self._recent):
            raise IndexError('requested recent observation is unavailable')
        return self._recent[offset]

    def to_frame(self, *, tail: int | None = None):
        import pandas as pd
        if tail is not None:
            _positive_integer(tail)
        skip = 0 if tail is None else max(0, self._count - tail)
        return pd.DataFrame([dict(row) for row in _history_rows(self._root, skip)], columns=self._columns or None)
