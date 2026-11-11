"""Account-independent calculations on already visible market windows."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from math import isfinite
import re
from threading import RLock
from types import FunctionType


@dataclass(frozen=True, slots=True)
class MarketWindow:
    """A fixed-size, causal input to a declared market calculation."""

    source: str | None
    rows: int
    table: bool = False

    def __post_init__(self):
        if self.source is not None and (type(self.source) is not str or not self.source):
            raise TypeError('market window source requires a declared input name or None')
        if type(self.rows) is not int or self.rows < 1:
            raise ValueError('market window requires a positive fixed row count')
        if type(self.table) is not bool or (self.table and self.source is None):
            raise ValueError('table windows require an explicit observation name')


@dataclass(frozen=True, slots=True)
class MarketFeature:
    """Source-owned function with fixed inputs, parameter dependencies and result size."""

    name: str
    entrypoint: str
    windows: tuple[MarketWindow, ...]
    parameters: tuple[str, ...] = ()
    session_date: bool = False
    max_values: int = 1

    def __post_init__(self):
        if type(self.name) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', self.name):
            raise ValueError('market feature name requires an ASCII identifier')
        if type(self.entrypoint) is not str or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', self.entrypoint):
            raise ValueError('market feature entrypoint requires module:function')
        if type(self.windows) is not tuple or not self.windows or any(type(item) is not MarketWindow for item in self.windows):
            raise TypeError('market features require declared MarketWindow inputs')
        if (type(self.parameters) is not tuple or any(type(name) is not str or not name for name in self.parameters)
                or len(set(self.parameters)) != len(self.parameters)):
            raise TypeError('market feature parameter names must be a unique tuple')
        if type(self.session_date) is not bool or type(self.max_values) is not int or self.max_values < 1:
            raise ValueError('market feature requires an explicit positive result bound')

    @classmethod
    def from_dict(cls, value):
        return cls(**{**value, 'windows': tuple(MarketWindow(**item) for item in value['windows']),
                      'parameters': tuple(value['parameters'])})


def _parameter_key(value):
    if type(value) is tuple:
        return tuple(_parameter_key(item) for item in value)
    if type(value) not in (type(None), bool, int, float, str, date):
        raise TypeError('market feature parameters must be immutable scalars or tuples')
    if type(value) is float:
        if not isfinite(value):
            raise ValueError('market feature parameters must be finite')
        return (float, value.hex())
    return (type(value), value)


def _validate_result(value, max_values):
    values = value if type(value) is tuple else (value,)
    if len(values) > max_values:
        raise ValueError('market feature result exceeds its declared size')
    for item in values:
        if type(item) not in (type(None), bool, int, float, str, date, datetime):
            raise TypeError('market feature results must be immutable scalars or a flat tuple')
        if type(item) is float and not isfinite(item):
            raise ValueError('market feature results must be finite')


class _MarketWindowCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = RLock()

    def get(self, key, compute, max_values):
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key]
            value = compute()
            _validate_result(value, max_values)
            self.entries[key] = value
            if len(self.entries) > 32768:
                self.entries.popitem(last=False)
            return value


@lru_cache(maxsize=4)
def _market_cache(prepared_identity, source_sha256, dependencies):
    return _MarketWindowCache()


def _market_feature(candidate, prepared, declaration, history, auxiliary, tables, session):
    from .equity_source_runtime import active_invocation

    bound = active_invocation(candidate)
    if bound is None:
        raise RuntimeError('market features require the loaded strategy scope')
    parameters = tuple(candidate.definition.parameters[name] for name in declaration.parameters)
    if declaration.session_date:
        parameters = (session.session_date, *parameters)
    inputs, counts = [], []
    for window in declaration.windows:
        view = tables[window.source] if window.table else (history if window.source is None else auxiliary[window.source])
        inputs.append((view, window.rows))
        # Visibility only grows within one prepared input. Its size uniquely
        # identifies the visible set even when rows arrive out of source order.
        counts.append(len(view))
    identity = (declaration, tuple(counts), _parameter_key(parameters))
    cache = _market_cache(prepared.identity, candidate.definition.source_sha256, candidate.definition.dependencies)
    return cache.get(identity, lambda: bound.market_functions[declaration.name](
        tuple(view._tail(rows) for view, rows in inputs), *parameters), declaration.max_values)


def resolve_market_function(function, module_name, function_name):
    if (type(function) is not FunctionType or function.__closure__ is not None
            or function.__qualname__ != function_name or function.__module__ != module_name):
        raise TypeError('market feature requires its declared top-level strategy function')
    return function
