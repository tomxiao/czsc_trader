"""Caller-supplied authenticated S013 frames/native pair; no provider/cache/file IO."""

from hashlib import sha256
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import component
import vol_statistics

CORE_PATH = Path("research/S013/experiments/EX071_20261011/src/continuation_core.py")
CORE_SHA256 = "752ebc55ce9cd401645410d57508fc0a2633df3ac1a1f386ae9bcd0df50cc2cf"


def original_core():
    # Source-only dependency authentication; import does not read any data.
    root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
    path = root / CORE_PATH
    if sha256(path.read_bytes()).hexdigest() != CORE_SHA256:
        raise ValueError("immutable EX071 core SHA mismatch")
    name = "s013_vol_original_continuation_core"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def construct(old, warm69, bound, result):
    """Root authenticates public SHA/cache serialize pair BEFORE this pure assembly.

    old: EX071 plan's original EX069 features; warm69: EX076 declared warm69 O/C.
    No future exit, future maturity or label availability can select scope.
    """
    expected_pricing = {
        "basis": "HFQ_RESEARCH",
        "quantity_unit": "RESEARCH_UNIT",
        "anchor_date": "2019-12-31",
        "anchor_factor": 0.2803,
    }
    if (
        bound.strategy.candidate_id != "C8880"
        or bound.execution_data.pricing.to_dict() != expected_pricing
        or len(result.runs) != 1
    ):
        raise ValueError("authenticated original C8880 HFQ native pair required")
    grid = component.canonical_dates(old.index)
    prices = (
        bound.execution_data.execution_daily.set_index("dt")[["open", "close"]]
        .rename(columns={"open": "Open", "close": "Close"})
        .copy()
    )
    prices.index = component.canonical_dates(pd.DatetimeIndex(prices.index))
    prices.attrs = {}
    sessions = component.canonical_dates(
        pd.DatetimeIndex(pd.to_datetime(bound.execution_data.evaluation_sessions))
    )
    if (
        len(prices) != 1637
        or prices.index[0] != pd.Timestamp("2019-12-31")
        or len(sessions) != 1636
        or not prices.index[1:].equals(sessions)
        or len(grid) != 1635
        or not grid.equals(sessions[:-1])
        or grid[0] != pd.Timestamp("2020-01-02")
        or grid[-1] != pd.Timestamp("2026-09-29")
    ):
        raise ValueError("original1637 native/1636 execution/1635 grid required")
    execution = result.runs[0].execution
    signal_dates = component.canonical_dates(
        pd.DatetimeIndex(pd.to_datetime(execution.decisions.signal_date))
    )
    if not signal_dates.equals(prices.index[:-1]):
        raise ValueError("native decisions must use anchor-prefix before execution")
    warm = warm69.loc[:, ["Open", "Close"]].copy()
    warm.index = component.canonical_dates(warm69.index)
    if (
        warm.index[0] != pd.Timestamp("2019-04-10")
        or warm.index[-1] != pd.Timestamp("2026-09-29")
        or not prices.index[:-1].isin(warm.index).all()
    ):
        raise ValueError("exact original warm69 endpoints/native overlap required")
    values = warm.to_numpy(float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("positive finite warm O/C required")
    overlap = prices.index[:-1]
    np.testing.assert_allclose(
        warm.loc[overlap].to_numpy(float) / prices.loc[overlap].to_numpy(float),
        0.2803,
        rtol=1e-13,
        atol=1e-13,
    )
    output = assemble(old.set_axis(grid), warm.Close, prices, execution, original_core())
    return (
        output["features"],
        output["labels"],
        output["scope"],
        output["state"],
        prices,
        output["metadata"],
    )


def assemble(old, warm_close, prices, execution, core):
    """Pure same-frame assembler, also supports artificial fixture axes."""
    grid = old.index
    state = core.build_known_state(
        execution.account_daily, execution.fills, execution.decisions, grid
    )
    observed = component.construct(warm_close).reindex(grid)
    base = [
        n
        for n in vol_statistics.CONTROLS
        if n not in ("holding_age", "entry_mark_pnl", "known_falling", "log_sigma20")
    ]
    features = old.loc[:, base].copy()
    features["holding_age"] = state.holding_age
    features["entry_mark_pnl"] = state.entry_mark_pnl
    features["known_falling"] = old.momentum20.lt(0).astype(float)
    features["log_sigma20"] = observed.log_sigma20
    features["vol_concentration"] = observed.vol_concentration
    features = features.loc[:, [*vol_statistics.CONTROLS, *vol_statistics.COMPONENTS]]
    labels_all = core.build_labels(prices, grid)
    names = [n for label in vol_statistics.HORIZONS for n in (label, "label_end_" + label)]
    labels = labels_all.loc[:, names]
    scopes = pd.DataFrame(
        {"actual_signal_continue": state.actual_held & state.signal_held_after}, index=grid
    )
    info = {
        "scope_n": int(scopes.actual_signal_continue.sum()),
        "missing": features.isna().sum().to_dict(),
        "signal_n": len(grid),
        "future_exit_used": False,
        "future_label_used_for_scope": False,
    }
    return {
        "features": features,
        "labels": labels,
        "scope": scopes,
        "state": state,
        "component": observed,
        "metadata": info,
    }
