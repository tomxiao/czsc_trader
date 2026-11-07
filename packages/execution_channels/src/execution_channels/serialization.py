"""Explicit record boundary for execution-owned contracts.

Applications project their own domain objects to records before constructing EC
contracts. No strategy/data-source type is imported or accepted as a contract.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from functools import lru_cache
import math
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints


def to_record(value, *, json_safe=False):
    """Project a typed value without invoking custom serialization or I/O."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_record(getattr(value, f.name), json_safe=json_safe)
                for f in fields(value) if f.init}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError('record keys must be strings')
        return {key: to_record(item, json_safe=json_safe) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_record(item, json_safe=json_safe) for item in value]
    if type(value) in (datetime, date, Decimal):
        if type(value) is Decimal and not value.is_finite():
            raise ValueError('record decimals must be finite')
        if not json_safe:
            return value
        return {'$' + type(value).__name__: str(value) if type(value) is Decimal else value.isoformat()}
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise TypeError('unsupported execution record value: ' + type(value).__name__)


def _decode(annotation, value):
    if isinstance(value, Mapping) and len(value) == 1:
        if set(value) == {'$datetime'}:
            value = datetime.fromisoformat(value['$datetime'])
        elif set(value) == {'$date'}:
            value = date.fromisoformat(value['$date'])
        elif set(value) == {'$Decimal'}:
            value = Decimal(value['$Decimal'])
    if annotation in (Any, object):
        return to_record(value)
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        exact = [arg for arg in args if arg is type(value)]
        for arg in (*exact, *(arg for arg in args if arg not in exact)):
            try:
                return _decode(arg, value)
            except (TypeError, ValueError):
                pass
        raise TypeError('execution union field has an incompatible value')
    if annotation is type(None):
        if value is not None:
            raise TypeError('expected null')
        return None
    if origin is tuple:
        if not isinstance(value, (tuple, list)):
            raise TypeError('expected immutable sequence record')
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], item) for item in value)
        if len(args) != len(value):
            raise ValueError('tuple record has incorrect length')
        return tuple(_decode(kind, item) for kind, item in zip(args, value, strict=True))
    if origin in (dict, Mapping) or annotation in (dict, Mapping):
        if not isinstance(value, Mapping):
            raise TypeError('expected a mapping record')
        if not args:
            return to_record(value)
        return {_decode(args[0], key): _decode(args[1], item) for key, item in value.items()}
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value.value if isinstance(value, Enum) else value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        if type(value) is annotation:
            return value
        return from_record(annotation, value)
    if annotation in (datetime, date):
        if type(value) is annotation:
            return value
        if type(value) is str:
            return annotation.fromisoformat(value)
        raise TypeError('expected explicit temporal record')
    if annotation is Decimal:
        if type(value) not in (Decimal, str, int, float):
            raise TypeError('expected explicit monetary record')
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError('nonfinite execution amount')
        return result
    if annotation is float:
        if type(value) not in (float, int) or not math.isfinite(value):
            raise TypeError('expected finite numeric field')
        return value
    if annotation in (str, int, bool):
        if type(value) is not annotation:
            raise TypeError('execution scalar field has incorrect type')
        return value
    raise TypeError('unsupported execution field annotation: ' + str(annotation))


@lru_cache(maxsize=128)
def _contract_fields(contract):
    return frozenset(f.name for f in fields(contract) if f.init), get_type_hints(contract)


def from_record(contract, record):
    """Validate an explicit record into a concrete EC dataclass.

    Unknown fields are rejected. Native values retain their numeric spelling;
    tagged JSON values restore datetime and Decimal without ambiguity.
    """
    if (not isinstance(contract, type) or not is_dataclass(contract)
            or not contract.__module__.startswith('execution_channels.')):
        raise TypeError('record target must be an execution-owned dataclass')
    if not isinstance(record, Mapping):
        raise TypeError('execution boundary requires an explicit mapping')
    names, hints = _contract_fields(contract)
    if set(record) - names:
        raise ValueError('unknown execution fields: ' + ','.join(sorted(set(record) - names)))
    return contract(**{name: _decode(hints[name], value) for name, value in record.items()})
