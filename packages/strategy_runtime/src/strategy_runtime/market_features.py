"""Account-independent calculations on already visible market windows."""
from collections import OrderedDict
from datetime import date, datetime
from functools import lru_cache
from math import isfinite
from threading import RLock
from types import FunctionType

from .equity_features import _history_rows


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


def _validate_result(value):
    if type(value) is tuple:
        for item in value:
            _validate_result(item)
    elif type(value) not in (type(None), bool, int, float, str, date, datetime):
        raise TypeError('market feature results must be immutable scalars or tuples')
    elif type(value) is float and not isfinite(value):
        raise ValueError('market feature results must be finite')


class _MarketWindowCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = RLock()

    def get(self, key, compute):
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key]
            value = compute()
            _validate_result(value)
            self.entries[key] = value
            if len(self.entries) > 32768:
                self.entries.popitem(last=False)
            return value


@lru_cache(maxsize=4)
def _market_cache(prepared_identity, source_sha256, dependencies):
    return _MarketWindowCache()


def _market_feature(candidate, prepared, context, function, windows, parameters):
    from .equity_source_runtime import active_invocation

    bound = active_invocation(candidate)
    if (bound is None or type(function) is not FunctionType or function.__closure__ is not None
            or function.__qualname__ != function.__name__ or not function.__module__.startswith(bound.prefix)):
        raise TypeError('market feature requires a top-level function in the active strategy source')
    if type(windows) is not tuple or not windows or type(parameters) is not tuple:
        raise TypeError('market feature requires explicit windows and a parameter tuple')
    histories, identities = [], []
    for name, length in windows:
        if type(length) is not int or length <= 0:
            raise ValueError('market feature windows require a positive length')
        view = context.history if name is None else context.auxiliary_histories[name]
        count = len(view)
        # Visibility only grows within one prepared input. Its size uniquely
        # identifies the visible set even when rows arrive out of source order.
        identities.append((name, length, count))
        histories.append((view, max(0, count - length)))
    identity = (function.__module__[len(bound.prefix):], function.__name__, tuple(identities),
                _parameter_key(parameters))
    cache = _market_cache(prepared.identity, candidate.definition.source_sha256, candidate.definition.dependencies)
    return cache.get(identity, lambda: function(
        tuple(tuple(_history_rows(view._root, skip)) for view, skip in histories), *parameters))
