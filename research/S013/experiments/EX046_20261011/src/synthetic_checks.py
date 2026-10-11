"""EX046 prototype causal contracts; entirely synthetic, no market/account reads."""

# ruff: noqa: E402
import ast
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from strategy_evaluator import (
    AssessmentCandidate,
    ParameterCoordinate,
    ParameterCoordinateKind,
    ParameterDesignRequest,
    ParameterPerturbationProtocol,
    ParameterSpace,
    build_parameter_perturbation_design,
)

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
OLD = ROOT / "research/S013/experiments/EX043_20261011/src"
sys.path.insert(0, str(SRC))
NEW_ENUM = "MEAN_BEAR_TIME_BELOW_SEGMENT_CLOSE"
OLD_ENUM = "MEAN_BEAR_TIME_BELOW_CLOSE"


def load(path, name, package=False):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same(actual, expected):
    for key in set(actual.columns) & set(expected.columns):
        pd.testing.assert_series_equal(
            actual[key], expected[key], check_exact=True, check_dtype=False, check_names=False
        )


def state_oracle(oracle_path, p, bars, dates, regimes, score, positions):
    # Execute the independent oracle's complete state loop using controlled causal features.
    # Neither production formulas nor production transition functions are called here.
    tree = ast.parse(oracle_path.read_text("utf-8"))
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_reconstruct"
    )
    start = next(
        i
        for i, n in enumerate(function.body)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(a, ast.Tuple)
            and any(isinstance(v, ast.Name) and v.id == "holding" for v in a.elts)
            for a in n.targets
        )
    )
    code = ast.fix_missing_locations(ast.Module(body=function.body[start:-1], type_ignores=[]))
    env = {
        "np": np,
        "pd": pd,
        "mechanism": p["mechanism"],
        "p": p,
        "c": p["confirmation"],
        "dates": dates,
        "regimes": np.array(regimes),
        "positions": positions,
        "centered_acf": pd.Series(0.0, index=dates),
        "raw_acf": pd.Series(0.0, index=dates),
        "is_mean": True,
        "momentum20": pd.Series(0.0, index=dates),
        "score": pd.Series(score, index=dates),
        "signal_close": bars.Close.reindex(dates),
        "direction": bars.Close.gt(bars.Close.shift()).reindex(dates).to_numpy(),
        "expected": pd.DataFrame(index=dates),
        "_exit_category": lambda close, anchor: (
            "BELOW" if close < anchor else "ABOVE" if close > anchor else "EQUAL"
        ),
    }
    exec(compile(code, str(oracle_path), "exec"), env)
    return env["expected"]


def synthetic(plan=None, source=None):
    import common as current_common

    assert Path(current_common.__file__).resolve() == SRC / "common.py"
    assert current_common.EXPERIMENT.experiment_id == "EX046_20261011"
    assert not current_common.SOURCE_CALLS
    source = SRC / "strategy_runtime" if source is None else Path(source)
    assert source.resolve() == (SRC / "strategy_runtime").resolve()
    if plan:
        assert len(plan["configurations"]) == 1
    package = source / "strategies"
    load(package / "__init__.py", "ex046_proto", True)
    native = importlib.import_module("ex046_proto.mechanism_range")
    load(OLD / "strategy_runtime/strategies/__init__.py", "ex043_legacy_proto", True)
    oldnative = importlib.import_module("ex043_legacy_proto.mechanism_range")
    oracle = load(SRC / "direction_oracle.py", "ex046_independent_proto")
    oldoracle = load(OLD / "direction_oracle.py", "ex043_independent_proto")
    for name in (
        "range_reversion.py",
        "adaptive_range.py",
        "confirmed_range.py",
        "reentry_confirmed_range.py",
        "__init__.py",
    ):
        assert (package / name).read_bytes() == (
            OLD / "strategy_runtime/strategies" / name
        ).read_bytes()
    oldast, newast = (
        ast.parse((path / "direction_oracle.py").read_text("utf-8")) for path in (OLD, SRC)
    )

    def date_node(tree):
        return next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_audit_dates"
        )

    assert ast.dump(date_node(oldast)) == ast.dump(date_node(newast))
    assert not any(
        isinstance(n, (ast.Import, ast.ImportFrom))
        and any(
            "strategy_runtime" in value
            for value in (
                [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            )
        )
        for n in ast.walk(newast)
    )
    declaration = json.loads((OLD.parent / "protocols/plan.json").read_text("utf-8-sig"))
    parent = next(c for c in declaration["configurations"] if c["label"] == "N0")
    p0 = deepcopy(parent["payload"]["parameters"])
    assert parent["candidate_id"] == "C4900" and p0["mechanism"] == OLD_ENUM
    geometry = json.loads(
        (ROOT / "research/S013/experiments/EX015_20261011/protocols/geometry.json").read_text(
            "utf-8-sig"
        )
    )

    def get(p, key):
        for part in key.split("."):
            p = p[part]
        return p

    space = ParameterSpace(
        tuple(
            ParameterCoordinate(
                name, float(get(p0, name)), low, high, ParameterCoordinateKind(kind)
            )
            for name, low, high, kind in geometry["coordinates"]
        ),
        "1" * 64,
        "2" * 64,
    )
    design = build_parameter_perturbation_design(
        ParameterDesignRequest(
            AssessmentCandidate("S013-C4900", "3" * 64),
            ParameterPerturbationProtocol(**geometry["protocol"]),
            space,
        ),
        feasibility=lambda v: v[1] < v[2] and v[5] < v[6],
    ).design
    rng = np.random.default_rng(13)
    days = pd.bdate_range("2019-01-01", periods=430)
    close = 100 * np.exp(
        np.cumsum(0.006 * np.sin(np.arange(430) * 0.12) + rng.normal(0, 0.003, 430))
    )
    opening = close * np.exp(rng.normal(0, 0.003, 430))
    bars = pd.DataFrame(
        {
            "Date": days,
            "Open": opening,
            "Close": close,
            "High": np.maximum(close, opening) * 1.005,
            "Low": np.minimum(close, opening) * 0.995,
            "Amount": np.exp(rng.normal(16, 0.2, 430)),
            "Volume": np.exp(rng.normal(12, 0.2, 430)),
        },
        index=days,
    )
    dates = days[200:420]
    audited = legacy = 0
    for point in design.points:
        p = deepcopy(p0)
        for (name, _, _, kind), value in zip(
            geometry["coordinates"], point.coordinates, strict=True
        ):
            parts = name.split(".")
            target = p
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = int(value) if kind == "INTEGER" else float(value)
        p["mechanism"] = NEW_ENUM
        actual = native.MechanismRange(ParameterSet(p)).calculate_history({"daily": bars}, dates)
        expected = oracle._reconstruct(bars, dates, p)
        same(actual, expected)
        audited += 1
    for enum in sorted(oldoracle.MECHANISMS):
        p = deepcopy(p0)
        p["mechanism"] = enum
        actual = native.MechanismRange(ParameterSet(p)).calculate_history({"daily": bars}, dates)
        old = oldnative.MechanismRange(ParameterSet(p)).calculate_history({"daily": bars}, dates)
        pd.testing.assert_frame_equal(actual, old, check_exact=True)
        same(actual, oracle._reconstruct(bars, dates, p))
        same(actual, oldoracle._reconstruct(bars, dates, p))
        legacy += 1
    # Controlled fixtures separate state causality from the feature-formula audits above.
    controlled = 0

    def fixture(closes, regimes, hold, score=None, bull_eligible=False, bear_positions=None):
        nonlocal controlled
        q = deepcopy(p0)
        q["regime_window"] = 5
        q["regime_threshold"] = 0.05
        q["bull"].update(
            range_window=21, entry=0.95 if bull_eligible else 0.4, exit=0.99, max_hold=hold
        )
        q["bear"].update(range_window=22, entry=0.8, exit=0.99, max_hold=hold, acf_min=-0.1)
        q["confirmation"]["threshold"] = 0.0
        n = len(closes)
        ds = pd.bdate_range("2020-01-01", periods=160 + n)
        signals = ds[160:]
        prices = np.full(160 + n, 100.0)
        for i, (value, regime) in enumerate(zip(closes, regimes, strict=True)):
            prices[160 + i] = value
            prices[155 + i] = value / (1.1 if regime == "bull" else 1.0)
        data = pd.DataFrame(
            {
                "Date": ds,
                "Open": prices,
                "Close": prices,
                "High": prices * 1.01,
                "Low": prices * 0.99,
                "Amount": 10000.0,
                "Volume": 1000.0,
            },
            index=ds,
        )
        scores = np.zeros(n) if score is None else np.array(score, dtype=float)
        positions = {
            "bull": pd.Series(0.9, index=signals),
            "bear": pd.Series(0.3 if bear_positions is None else bear_positions, index=signals),
        }

        def components(_, window):
            controlled_position = pd.Series(0.9 if window == 21 else 0.3, index=ds)
            controlled_position.loc[signals] = positions["bull" if window == 21 else "bear"]
            return pd.DataFrame(
                {
                    "range_position": controlled_position,
                    "acf1": 0.0,
                    "close": data.Close,
                    "momentum20": 0.0,
                },
                index=ds,
            )

        def confirmed(*_):
            norm = pd.DataFrame({"acf": 0.0, "turnover": 0.0, "volume": 0.0}, index=ds)
            norm.loc[signals, "acf"] = scores * 2
            return None, norm

        original = (native.components, native.confirmation_features)
        native.components, native.confirmation_features = components, confirmed
        results = {}
        try:
            for enum in (OLD_ENUM, NEW_ENUM):
                q["mechanism"] = enum
                actual = native.MechanismRange(ParameterSet(q)).calculate_history(
                    {"daily": data}, signals
                )
                expected = state_oracle(
                    SRC / "direction_oracle.py", q, data, signals, regimes, scores, positions
                )
                same(actual, expected)
                results[enum] = actual
                controlled += 1
        finally:
            native.components, native.confirmation_features = original
        return results[OLD_ENUM], results[NEW_ENUM]

    # Continuous bear segment: original memory and refusal remain exact.
    a, b = fixture([100.0, 99.0, 99.0, 98.0], ["bear"] * 4, 1)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    assert (
        b.signal_reason.iloc[2] == "entry_direction_rejected"
        and b.last_exit_category.iloc[2] == "BELOW"
    )
    # Flat bull clears only category on that T; reason/route/score context remain.
    a, b = fixture([100.0, 99.0, 99.0, 101.0, 100.0], ["bear", "bear", "bear", "bull", "bear"], 1)
    assert a.last_exit_category.iloc[3] == "BELOW" and b.last_exit_category.iloc[3] is None
    assert a.signal_reason.iloc[3] == b.signal_reason.iloc[3] == "flat"
    for name in ("last_exit_reason", "last_exit_route", "confirmation_exit_context"):
        assert a[name].iloc[3] == b[name].iloc[3]
    assert (
        a.signal_reason.iloc[4] == "entry_direction_rejected" and b.signal_reason.iloc[4] == "entry"
    )
    # Holding bear TIME takes priority over regime change, yet bull T disarms category immediately.
    a, b = fixture([100.0, 90.0, 99.0, 98.0], ["bear", "bear", "bull", "bear"], 2)
    assert a.signal_reason.iloc[2] == b.signal_reason.iloc[2] == "time"
    assert a.last_exit_category.iloc[3] == "BELOW" and b.last_exit_category.iloc[3] is None
    assert b.last_exit_reason.iloc[3] == "time" and b.last_exit_route.iloc[3] == "bear"
    assert (
        b.signal_reason.iloc[3] == "entry" and a.signal_reason.iloc[3] == "entry_direction_rejected"
    )
    # Flat bull clears each strict classification, while preserving unrelated memory.
    categories = set()
    for exit_price, category in ((99.0, "BELOW"), (100.0, "EQUAL"), (101.0, "ABOVE")):
        a, b = fixture(
            [100.0, exit_price, exit_price, 102.0, 101.0],
            ["bear", "bear", "bear", "bull", "bear"],
            1,
            [0.0, 0.0, -0.3, 0.0, 0.0],
        )
        assert a.last_exit_category.iloc[3] == category and b.last_exit_category.iloc[3] is None
        for name in ("last_exit_reason", "last_exit_route", "confirmation_exit_context"):
            assert a[name].iloc[3] == b[name].iloc[3]
        categories.add(category)
    a, b = fixture([101.0, 100.0], ["bull", "bear"], 1)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    assert b.last_exit_category.iloc[0] is None and b.confirmation_exit_context.iloc[0] == "initial"
    categories.add("NONE")
    # Range remains ahead of TIME and regime on the same held signal.
    a, b = fixture(
        [100.0, 99.0, 98.0], ["bear", "bull", "bear"], 1, bear_positions=[0.3, 0.995, 0.3]
    )
    assert a.signal_reason.iloc[1] == b.signal_reason.iloc[1] == "range"
    assert a.last_exit_category.iloc[2] is None and b.last_exit_category.iloc[2] is None
    # Bull entry remains an immediate original opportunity, and clears every exit memory.
    a, b = fixture(
        [100.0, 99.0, 99.0, 101.0, 100.0],
        ["bear", "bear", "bear", "bull", "bear"],
        1,
        bull_eligible=True,
    )
    assert a.signal_reason.iloc[3] == b.signal_reason.iloc[3] == "entry"
    assert not a.entry_direction_gate_applies.iloc[3] and not b.entry_direction_gate_applies.iloc[3]
    for name in ("last_exit_reason", "last_exit_route", "last_exit_category"):
        assert a[name].iloc[4] is None and b[name].iloc[4] is None
    # Reset never bypasses the existing confirmation gate.
    a, b = fixture(
        [100.0, 99.0, 99.0, 101.0, 100.0],
        ["bear", "bear", "bear", "bull", "bear"],
        1,
        [0.0, 0.0, 0.0, 0.0, -0.3],
    )
    assert b.signal_reason.iloc[-1] == "confirmation_rejected" and b.target_position.iloc[-1] == 0
    p = deepcopy(p0)
    p["mechanism"] = NEW_ENUM
    actual = native.MechanismRange(ParameterSet(p)).calculate_history({"daily": bars}, dates)
    altered = bars.copy()
    altered.loc[days[320:], "Close"] *= 1.2
    altered.loc[days[320:], "Open"] *= 1.1
    altered.loc[days[320:], "High"] = (
        np.maximum(altered.loc[days[320:], "Close"], altered.loc[days[320:], "Open"]) * 1.01
    )
    altered.loc[days[320:], "Low"] = (
        np.minimum(altered.loc[days[320:], "Close"], altered.loc[days[320:], "Open"]) * 0.99
    )
    future = native.MechanismRange(ParameterSet(p)).calculate_history({"daily": altered}, dates)
    pd.testing.assert_frame_equal(actual.iloc[:120], future.iloc[:120], check_exact=True)
    pd.testing.assert_frame_equal(
        oracle._reconstruct(bars, dates, p).iloc[:120],
        oracle._reconstruct(altered, dates, p).iloc[:120],
        check_exact=True,
    )
    assert (
        p["confirmation"]["lookback"] == p0["confirmation"]["lookback"]
        and p["bull"] == p0["bull"]
        and p["bear"] == p0["bear"]
    )
    rejected = 0
    for change in (
        lambda p: p.update(mechanism="UNKNOWN"),
        lambda p: p["confirmation"].update(enabled=False),
        lambda p: p["confirmation"].update(lookback=0),
        lambda p: p["confirmation"].update(threshold=float("nan")),
        lambda p: p["bear"].update(max_hold=0),
        lambda p: p.update(regime_window=0),
    ):
        q = deepcopy(p)
        change(q)
        try:
            native.MechanismRange(ParameterSet(q))
        except (AssertionError, ValueError, TypeError):
            rejected += 1
        else:
            raise AssertionError("Invalid parameter accepted")
    # Insufficient strictly past baseline/score is rejected without padding/shortening.
    for data in (bars.iloc[70:], bars.assign(Open=float("nan"))):
        try:
            native.MechanismRange(ParameterSet(p)).calculate_history({"daily": data}, dates)
        except (AssertionError, ValueError, TypeError):
            rejected += 1
        else:
            raise AssertionError("Incomplete causal inputs accepted")
    for data in (bars.iloc[70:], bars.assign(Open=float("nan"))):
        try:
            oracle._reconstruct(data, dates, p)
        except (AssertionError, ValueError, TypeError):
            rejected += 1
        else:
            raise AssertionError("Independent oracle accepted incomplete causal inputs")
    assert not current_common.SOURCE_CALLS
    result = {
        "status": "PURE_PASS",
        "new_account_evaluations": 0,
        "new_account_preparations": 0,
        "parameter_points": 32,
        "full_numeric_dimensions": 13,
        "independent_formula_audits": audited,
        "old_four_enum_exact_checks": legacy,
        "controlled_native_independent_state_audits": controlled,
        "observed_categories_and_absence": sorted(categories),
        "invalid_parameter_input_warmup_rejections": rejected,
        "same_experiment_common_bound": True,
        "future_prefix_rows_exact": 120,
        "calendar_oracle_AST_exact_to_EX043": True,
        "five_parent_files_byte_exact": True,
        "oracle_imports_SRT": False,
        "causal_changes": [
            "Flat current rawbull clears only exit category before current decision.",
            "Final held bear TIME on current rawbull preserves reason/route but stores no category.",
            "All entry resets, score, coupled past-L baseline, H and exit priority unchanged.",
        ],
        "limits": "Prototype synthetic features/state contracts only; no market accounts, cash replay or profit forecast.",
        "source_files": {
            str(path.relative_to(SRC)): digest(path)
            for path in [
                SRC / "direction_oracle.py",
                SRC / "synthetic_checks.py",
                *sorted(package.glob("*.py")),
            ]
        },
    }
    return result


if __name__ == "__main__":
    value = synthetic()
    (ROOT / ".tmp/ex046-synthetic").mkdir(parents=True, exist_ok=True)
    (ROOT / ".tmp/ex046-synthetic/focused.json").write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(value)
