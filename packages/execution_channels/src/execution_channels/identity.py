"""Deterministic execution identities and immutable JSON facts."""
from collections.abc import Mapping
from types import MappingProxyType
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any
from hashlib import sha256
import hashlib
import json
import math
import pandas as pd
import numpy as np
from .instruments import utc
from .errors import RuntimeContractError

def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        _thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _freeze_json(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _text(key, f"{field_name} key"): _freeze_json(item, field_name)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item, field_name) for item in value)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise RuntimeContractError(f"{field_name} must contain only finite JSON values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def _json_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be a mapping")
    return _freeze_json(value, field_name)

def equity_hash(value):
    def default(item):
        if type(item) is datetime and item.tzinfo is UTC:
            return item.isoformat()
        if isinstance(item, (datetime, pd.Timestamp)):
            return utc(item.to_pydatetime() if isinstance(item, pd.Timestamp) else item).isoformat()
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"unserializable equity identity {type(item)}")
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False, default=default).encode()).hexdigest()


def freeze(value):
    return _freeze_json(value, 'execution facts')
