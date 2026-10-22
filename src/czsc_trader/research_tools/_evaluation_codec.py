"""Closed JSON codec for resumable evaluation facts (never executable objects)."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from functools import lru_cache
import math
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd


@lru_cache(maxsize=1)
def _records():
    from dataflows import Dataset
    from strategy_evaluator import MetricObservation, MetricStatus
    from strategy_manager import CandidateKey
    from trading_execution_engine import ExecutionResult
    from ..backtesting.models import StrategyIdentity, StrategySnapshot
    from ..backtesting.signal_replay import SignalReplay
    from ..backtesting.benchmarks import BuyHoldReplay
    from ..backtesting.result import BacktestResult
    from ..backtesting.benchmark_contracts import EvaluationBenchmark, LimitBuyHold, NextOpenBuyHold
    from .evaluation import EvaluationResult, EvaluationRun, EvaluationIdentity

    return {cls.__name__: cls for cls in (
        Dataset, MetricObservation, MetricStatus, CandidateKey, ExecutionResult, StrategyIdentity,
        StrategySnapshot, SignalReplay, BuyHoldReplay, EvaluationBenchmark,
        LimitBuyHold, NextOpenBuyHold, EvaluationResult, EvaluationRun, EvaluationIdentity, BacktestResult,
    )}


def _dtype(dtype):
    if isinstance(dtype, pd.CategoricalDtype):
        return {"category": encode(dtype.categories), "ordered": dtype.ordered}
    if isinstance(dtype, pd.StringDtype):
        return {"string_storage": dtype.storage, "na_value": encode(dtype.na_value)}
    return str(dtype)


def _restore_dtype(value, request):
    if isinstance(value, dict):
        if set(value) == {"category", "ordered"}:
            return pd.CategoricalDtype(decode(value["category"], request), value["ordered"])
        if set(value) == {"string_storage", "na_value"}:
            return pd.StringDtype(storage=value["string_storage"], na_value=decode(value["na_value"], request))
        raise ValueError("unsupported checkpoint dtype")
    return pd.api.types.pandas_dtype(value)


def encode(value):
    """Encode only the closed set of evaluation facts; reject unknown objects."""
    from strategy_runtime import StrategyObservation

    if type(value) is StrategyObservation:
        return {"tag": "strategy_observation", "value": value.to_dict()}
    if value is pd.NA:
        return {"tag": "NA"}
    if value is pd.NaT:
        return {"tag": "NaT"}
    if isinstance(value, Enum):
        if _records().get(type(value).__name__) is not type(value):
            raise TypeError(f"unsupported checkpoint enum: {type(value).__name__}")
        return {"tag": "enum", "type": type(value).__name__, "value": value.value}
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, np.generic):
        if isinstance(value, np.datetime64):
            return encode(pd.Timestamp(value))
        if isinstance(value, np.timedelta64):
            return encode(pd.Timedelta(value))
        return encode(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else {"tag": "float", "value": repr(value)}
    if isinstance(value, pd.Timestamp):
        return {"tag": "timestamp", "value": value.isoformat()}
    if isinstance(value, datetime):
        return {"tag": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"tag": "date", "value": value.isoformat()}
    if isinstance(value, pd.Timedelta):
        return {"tag": "timedelta", "value": value.value}
    if isinstance(value, timedelta):
        return {"tag": "python_timedelta", "days": value.days,
                "seconds": value.seconds, "microseconds": value.microseconds}
    if isinstance(value, Path):
        return {"tag": "path", "value": str(value)}
    if isinstance(value, pd.DataFrame):
        return {"tag": "frame", "index": encode(value.index), "columns": encode(value.columns),
                "dtypes": [_dtype(dtype) for dtype in value.dtypes],
                "data": [[encode(cell) for cell in value.iloc[:, i].array]
                         for i in range(len(value.columns))], "attrs": encode(value.attrs)}
    if isinstance(value, pd.MultiIndex):
        return {"tag": "multi_index", "levels": [encode(level) for level in value.levels],
                "codes": [code.tolist() for code in value.codes], "names": encode(value.names)}
    if isinstance(value, pd.RangeIndex):
        return {"tag": "range_index", "start": value.start, "stop": value.stop,
                "step": value.step, "name": encode(value.name)}
    if isinstance(value, pd.Index):
        return {"tag": "index", "data": [encode(cell) for cell in value],
                "dtype": _dtype(value.dtype), "name": encode(value.name),
                "freq": value.freqstr if isinstance(value, (pd.DatetimeIndex, pd.TimedeltaIndex)) else None}
    if type(value) in (list, tuple):
        return {"tag": type(value).__name__, "items": [encode(item) for item in value]}
    if type(value) in (dict, MappingProxyType):
        return {"tag": "mappingproxy" if type(value) is MappingProxyType else "dict",
                "items": [[encode(key), encode(item)] for key, item in value.items()]}
    if is_dataclass(value) and _records().get(type(value).__name__) is type(value):
        # Worker computation paths are disposable and differ between identical
        # runs. They are rebound to the prepared caller context on restoration.
        omitted = {"EvaluationResult": {"execution_data"},
                   "SignalReplay": {"strategy_source", "data_dir"}}
        return {"tag": "record", "type": type(value).__name__, "fields": {
            field.name: encode(getattr(value, field.name)) for field in fields(value)
            if field.name not in omitted.get(type(value).__name__, set())}}
    raise TypeError(f"unsupported checkpoint value: {type(value).__name__}")


def decode(value, request):
    """Reattach runtime inputs exclusively from the freshly prepared request."""
    if value is None or type(value) in (str, int, bool, float):
        return value
    if type(value) is not dict or "tag" not in value:
        raise ValueError("invalid checkpoint value")
    tag = value["tag"]
    if tag == "strategy_observation":
        from strategy_runtime import StrategyObservation
        return StrategyObservation.from_dict(value["value"])
    if tag in ("NA", "NaT"):
        return pd.NA if tag == "NA" else pd.NaT
    if tag == "float":
        if value["value"] not in ("nan", "inf", "-inf"):
            raise ValueError("invalid checkpoint float")
        return float(value["value"])
    constructors = {"timestamp": pd.Timestamp, "datetime": datetime.fromisoformat,
                    "date": date.fromisoformat, "path": Path, "timedelta": pd.Timedelta}
    if tag in constructors:
        return constructors[tag](value["value"])
    if tag == "python_timedelta":
        return timedelta(**{key: value[key] for key in ("days", "seconds", "microseconds")})
    if tag in ("list", "tuple"):
        items = [decode(item, request) for item in value["items"]]
        return tuple(items) if tag == "tuple" else items
    if tag in ("dict", "mappingproxy"):
        items = [(decode(key, request), decode(item, request)) for key, item in value["items"]]
        result = dict(items)
        if len(result) != len(items):
            raise ValueError("duplicate checkpoint dictionary keys")
        return MappingProxyType(result) if tag == "mappingproxy" else result
    if tag == "range_index":
        return pd.RangeIndex(value["start"], value["stop"], value["step"], name=decode(value["name"], request))
    if tag == "multi_index":
        return pd.MultiIndex(levels=[decode(item, request) for item in value["levels"]],
                             codes=value["codes"], names=decode(value["names"], request))
    if tag == "index":
        result = pd.Index([decode(item, request) for item in value["data"]],
                          dtype=_restore_dtype(value["dtype"], request), name=decode(value["name"], request))
        if value["freq"] is not None:
            if not isinstance(result, (pd.DatetimeIndex, pd.TimedeltaIndex)):
                raise ValueError("checkpoint frequency requires temporal index")
            result.freq = value["freq"]
        return result
    if tag == "frame":
        columns, index = decode(value["columns"], request), decode(value["index"], request)
        if len(columns) != len(value["data"]) or len(columns) != len(value["dtypes"]):
            raise ValueError("checkpoint frame shape differs")
        series = []
        for data, dtype in zip(value["data"], value["dtypes"], strict=True):
            if len(data) != len(index):
                raise ValueError("checkpoint frame row count differs")
            series.append(pd.Series([decode(item, request) for item in data],
                                    dtype=_restore_dtype(dtype, request)))
        result = pd.concat(series, axis=1) if series else pd.DataFrame(index=range(len(index)))
        result.columns, result.index = columns, index
        result.attrs = decode(value["attrs"], request)
        return result
    if tag in ("record", "enum"):
        cls = _records().get(value["type"])
        if cls is None or (tag == "enum") != issubclass(cls, Enum):
            raise ValueError("unapproved checkpoint record type")
        if tag == "enum":
            return cls(value["value"])
        expected = {field.name for field in fields(cls)}
        omitted = {"EvaluationResult": {"execution_data"},
                   "SignalReplay": {"strategy_source", "data_dir"}}
        if set(value["fields"]) != expected - omitted.get(cls.__name__, set()):
            raise ValueError("checkpoint record fields differ")
        kwargs = {name: decode(item, request) for name, item in value["fields"].items()}
        if cls.__name__ == "EvaluationResult":
            kwargs["execution_data"] = request.execution_data
        if cls.__name__ == "SignalReplay":
            from ..backtesting.srt_bridge import srt_data_directory
            kwargs["strategy_source"] = request.strategy
            kwargs["data_dir"] = srt_data_directory(
                request.execution_data.root, kwargs["snapshot"], request.symbol)
        return cls(**kwargs)
    raise ValueError(f"unsupported checkpoint tag: {tag}")
