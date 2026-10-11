"""Synthetic focused checks. No real frame/cache/financial/statistical study reads."""

import ast
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import component
import inputs
import vol_statistics as stats


def run():
    here = Path(__file__).resolve().parent
    checks = []
    axis = pd.bdate_range("2020-01-02", periods=66)
    returns = np.tile([0.01, -0.02, 0.015, -0.005, 0.008], 13)
    prices = pd.Series(np.exp(np.r_[0.0, np.cumsum(returns)]), index=axis)
    observed = component.construct(prices)
    assert observed.vol_concentration.iloc[:20].isna().all()
    assert np.isfinite(observed.vol_concentration.iloc[20:]).all()
    assert observed.log_sigma20.equals(observed.sigma20.where(observed.sigma20.gt(0)))
    checks.append("20complete returns need21Close; nuisance is sigma OF logreturns")
    changed = prices.copy()
    changed.iloc[45:] *= 3
    pd.testing.assert_frame_equal(
        observed.iloc[:45], component.construct(changed).iloc[:45], check_exact=True
    )
    checks.append("future mutation prefixexact")
    zero = component.construct(pd.Series(1.0, index=axis))
    assert zero.vol_concentration.isna().all() and zero.log_sigma20.isna().all()
    assert zero.unavailable_reason.iloc[20:].eq("ZERO_SIGMA20").all()
    flat_tail = prices.copy()
    flat_tail.iloc[-5:] = float(prices.iloc[-5])
    assert component.construct(flat_tail).vol_concentration.iloc[-1] == 0
    checks.append("zero denominator unavailable; zero4 numerator ratio0")
    r1 = np.r_[np.tile([0.005, -0.005], 8), [0.04, -0.04, 0.04, -0.04]]
    r2 = np.r_[[0.04, -0.04, 0.04, -0.04], np.tile([0.005, -0.005], 8)]
    short = axis[:21]
    a = component.construct(pd.Series(np.exp(np.r_[0, np.cumsum(r1)]), index=short)).iloc[-1]
    b = component.construct(pd.Series(np.exp(np.r_[0, np.cumsum(r2)]), index=short)).iloc[-1]
    assert abs(r1.sum() - r2.sum()) < 1e-15
    np.testing.assert_allclose(a.sigma20, b.sigma20, rtol=1e-12, atol=1e-15)
    assert a.vol_concentration > b.vol_concentration
    checks.append("same cumulative change/total20sigma different concentration")
    microseconds = prices.copy()
    microseconds.index = microseconds.index.as_unit("us")
    pd.testing.assert_frame_equal(observed, component.construct(microseconds), check_exact=True)
    refused = 0
    for invalid in (
        prices.set_axis(axis + pd.Timedelta(hours=1)),
        prices.set_axis(axis[::-1]),
        prices.mask(prices.index == axis[4], 0),
        prices.mask(prices.index == axis[4], np.nan),
    ):
        try:
            component.construct(invalid)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("invalid input accepted")
    assert refused == 4
    checks.append("lossless ns/us dates; intraday/reverse/nonpositive/missing refuses")
    core = inputs.original_core()
    account_axis = axis[1:]
    quantities = np.where(np.arange(len(account_axis)) >= 2, 100, 0)
    account = pd.DataFrame(
        {
            "date": account_axis,
            "quantity_before": np.r_[0, quantities[:-1]],
            "quantity": quantities,
            "close": prices.loc[account_axis].to_numpy(),
        }
    )
    fills = pd.DataFrame(
        {
            "fill_time": [axis[3]],
            "fill_id": ["artificial_buy"],
            "quantity": [100],
            "price": [float(prices.iloc[3])],
            "fees": [0.1],
            "side": ["BUY"],
            "signal_date": [axis[2]],
        }
    )
    targets = np.ones(len(axis) - 1, dtype=int)
    targets[6] = 0
    decisions = pd.DataFrame(
        {"valid_session": axis[1:], "signal_date": axis[:-1], "target_position": targets}
    )
    execution = SimpleNamespace(account_daily=account, fills=fills, decisions=decisions)
    grid = axis[1:60]
    old = pd.DataFrame(
        {
            name: np.linspace(-0.02, 0.03, len(grid))
            for name in stats.CONTROLS
            if name not in ("holding_age", "entry_mark_pnl", "known_falling", "log_sigma20")
        },
        index=grid,
    )
    native_prices = pd.DataFrame({"Open": prices, "Close": prices * 1.001}, index=axis)
    output = inputs.assemble(old, prices, native_prices, execution, core)
    assert tuple(output["scope"].columns) == ("actual_signal_continue",)
    assert (
        not output["scope"].iloc[0, 0]
        and output["scope"].loc[axis[3]].iloc[0]
        and not output["scope"].loc[axis[6]].iloc[0]
    )
    assert output["state"].loc[axis[3], "holding_age"] == 1
    assert (
        output["features"].loc[axis[1], "holding_age"]
        != output["features"].loc[axis[1], "holding_age"]
    )
    assert len(stats.CONTROLS) == 24 and tuple(output["features"].columns) == (
        *stats.CONTROLS,
        "vol_concentration",
    )
    assert set(stats.HORIZONS) == {"return_4", "downside_4"}
    assert tuple(output["labels"].columns) == (
        "return_4",
        "label_end_return_4",
        "downside_4",
        "label_end_downside_4",
    )
    for day in grid:
        pos = axis.get_loc(day)
        if pos + 5 < len(axis):
            assert output["labels"].loc[day, "label_end_return_4"] == axis[pos + 5]
            assert output["labels"].loc[day, "return_4"] == float(
                native_prices.Open.iloc[pos + 5] / native_prices.Open.iloc[pos + 1] - 1
            )
    tail_labels = core.build_labels(native_prices, axis[-5:])
    assert tail_labels.return_4.isna().all() and tail_labels.label_end_return_4.isna().all()
    checks.append("actual T fills/current T intention only; h4T+5/NaT tails unchanged")
    # Scope/label/maturity semantics only, not a synthetic full statistics run.
    train, test, first = stats._year_train_mask(
        pd.bdate_range("2020-12-21", periods=30),
        pd.Series(pd.bdate_range("2020-12-21", periods=30) + pd.Timedelta(days=8)),
        np.ones(30, bool),
        2021,
    )
    index = pd.bdate_range("2020-12-21", periods=30)
    ends = pd.Series(index + pd.Timedelta(days=8))
    assert np.array_equal(train, (index.year == 2020) & (ends < first).to_numpy())
    assert np.array_equal(test, index.year == 2021)
    checks.append("strict yearly label maturation train40/test20 unchanged")
    original = (
        here.parents[1] / "research/S013/experiments/EX071_20261011/src/opportunity_statistics.py"
    )
    tree_old, tree_new = (
        ast.parse(original.read_text(encoding="utf-8")),
        ast.parse((here / "vol_statistics.py").read_text(encoding="utf-8")),
    )
    functions_old = {
        n.name: ast.dump(n, include_attributes=False)
        for n in tree_old.body
        if isinstance(n, ast.FunctionDef)
    }
    functions_new = {
        n.name: ast.dump(n, include_attributes=False)
        for n in tree_new.body
        if isinstance(n, ast.FunctionDef)
    }
    untouched = [name for name in functions_old if name not in ("_walk_forward", "analyze")]
    for name in untouched:
        assert functions_old[name] == functions_new[name], name
    checks.append("EX071 numerical functions AST exact inclrankDF/bootstrap500x40/maturity/ridge10")
    return {
        "status": "PASS",
        "checks": checks,
        "input_refusals": refused,
        "unchanged_numeric_functions": untouched,
        "source_sha256": {
            n: sha256((here / n).read_bytes()).hexdigest()
            for n in ("component.py", "inputs.py", "vol_statistics.py", "focused_checks.py")
        },
        "dependencies": {
            str(inputs.CORE_PATH): inputs.CORE_SHA256,
            "research/S013/experiments/EX071_20261011/src/opportunity_statistics.py": sha256(
                original.read_bytes()
            ).hexdigest(),
        },
        "real_data_reads": 0,
        "real_statistics": 0,
        "new_accounts": 0,
        "new_experiments": 0,
        "publication": 0,
    }


if __name__ == "__main__":
    result = run()
    Path(__file__).with_name("focused_checks.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
