"""Durable channel-owned state records and declared state schemas."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import math

StateScalar = bool | int | float | str | datetime | None

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

    def to_dict(self):
        return {'values': [[key, {'datetime': value.isoformat()} if type(value) is datetime else value]
                           for key,value in self.values]}

    @classmethod
    def from_dict(cls,value):
        if type(value) is not dict or set(value)!={'values'} or type(value['values']) is not list:
            raise ValueError('state record requires values')
        pairs=[]
        for entry in value['values']:
            if type(entry) is not list or len(entry)!=2:
                raise ValueError('state values require pairs')
            key,item=entry
            if type(item) is dict:
                if set(item)!={'datetime'} or type(item['datetime']) is not str:
                    raise ValueError('state datetime encoding invalid')
                item=datetime.fromisoformat(item['datetime'])
            pairs.append((key,item))
        return cls(tuple(pairs))

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
class AccountStrategyState(StrategyState):
    event_cursor: int = 0

    def __post_init__(self):
        StrategyState.__post_init__(self)
        if type(self.event_cursor) is not int or self.event_cursor<0:
            raise ValueError('account event cursor must be a nonnegative integer')

    def to_dict(self):
        return {'revision': self.revision, 'account': self.account.to_dict(),
                'cycle': None if self.cycle is None else {
                    'cycle_id': self.cycle.cycle_id, 'entry_at': self.cycle.entry_at.isoformat(),
                    'values': self.cycle.values.to_dict()},
                'binding': self.binding, 'event_cursor': self.event_cursor}

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {'revision', 'account', 'cycle', 'binding', 'event_cursor'}:
            raise ValueError('unsupported account strategy state')
        cycle = value['cycle']
        if cycle is not None:
            if type(cycle) is not dict or set(cycle) != {'cycle_id', 'entry_at', 'values'}:
                raise ValueError('unsupported account cycle state')
            cycle = CycleState(cycle['cycle_id'], datetime.fromisoformat(cycle['entry_at']),
                               StateRecord.from_dict(cycle['values']))
        return cls(value['revision'], StateRecord.from_dict(value['account']), cycle,
                   value['binding'], value['event_cursor'])
