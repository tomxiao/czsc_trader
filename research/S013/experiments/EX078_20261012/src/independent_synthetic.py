"""One artificial input/statistics comparison; no real frames/cache/data access."""

from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import audit


def main():
    here = Path(__file__).resolve().parent
    main_source = here.parent / "s013-vol-concentration"
    sys.path.insert(0, str(main_source))
    kernel = importlib.import_module("vol_statistics")
    inputs = importlib.import_module("inputs")
    policy_component = importlib.import_module("component")
    assert tuple(kernel.CONTROLS) == audit.CONTROLS and tuple(kernel.HORIZONS) == audit.LABELS
    rng = np.random.default_rng(41)
    warm_axis = pd.bdate_range("2019-10-01", periods=25)
    grid = (
        pd.bdate_range("2020-01-02", periods=90)
        .append(pd.bdate_range("2021-01-04", periods=50))
        .append(pd.bdate_range("2022-01-03", periods=45))
        .as_unit("ns")
    )
    tail = pd.bdate_range(grid[-1] + pd.Timedelta(days=1), periods=6)
    all_axis = warm_axis.append(grid).append(tail).as_unit("ns")
    prices_close = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.014, len(all_axis)))), index=all_axis)
    opening = prices_close.to_numpy() * np.exp(rng.normal(0, 0.003, len(all_axis)))
    prices = pd.DataFrame({"Open": opening, "Close": prices_close}, index=all_axis)
    execution_axis = grid.append(tail)
    fills = []
    for number, (p, side, units) in enumerate(
        ((2, "BUY", 100), (35, "SELL", 50), (40, "BUY", 50), (120, "SELL", 100), (130, "BUY", 100))
    ):
        day = execution_axis[p]
        prior = all_axis[all_axis.get_loc(day) - 1]
        fills.append(
            dict(
                fill_id=f"artificial{number}",
                fill_time=day + pd.Timedelta(hours=9, minutes=30),
                signal_date=prior,
                side=side,
                quantity=units,
                price=float(prices.loc[day, "Open"]),
                fees=0.1,
            )
        )
    fills = pd.DataFrame(fills)
    quantities, position = [], 0
    for day in execution_axis:
        for row in fills.loc[pd.to_datetime(fills.fill_time).dt.normalize() == day].itertuples():
            position += row.quantity if row.side == "BUY" else -row.quantity
        quantities.append(position)
    account = pd.DataFrame(
        {
            "date": execution_axis,
            "quantity_before": [0, *quantities[:-1]],
            "quantity": quantities,
            "close": prices.loc[execution_axis, "Close"].to_numpy(),
        }
    )
    target = np.ones(len(execution_axis), int)
    target[[4, 36, 121]] = 0  # Actual held can differ from current T intent.
    signals = all_axis[all_axis.get_indexer(execution_axis) - 1]
    decisions = pd.DataFrame(
        {"signal_date": signals, "valid_session": execution_axis, "target_position": target}
    )
    execution = SimpleNamespace(account_daily=account, fills=fills, decisions=decisions)
    base = [
        name
        for name in audit.CONTROLS
        if name not in ("holding_age", "entry_mark_pnl", "known_falling", "log_sigma20")
    ]
    old = pd.DataFrame(
        rng.integers(-10, 11, (len(grid), len(base))).astype(float), columns=base, index=grid
    )
    assembled = inputs.assemble(old, prices_close, prices, execution, inputs.original_core())
    input_result = audit.verify_inputs(
        old, prices_close, prices, account, fills, decisions, assembled
    )
    expected_state = audit.held_state(account, fills, decisions, grid)
    assert expected_state.loc[grid[2], "holding_age"] == 1
    assert pd.isna(expected_state.loc[grid[0], "entry_mark_pnl"])
    expected_cost = (float(fills.iloc[0].price) * 50 + float(fills.iloc[2].price) * 50) / 100
    np.testing.assert_allclose(
        expected_state.loc[grid[40], "entry_gross_price"], expected_cost, rtol=0, atol=2e-15
    )
    assert (
        not assembled["scope"].loc[grid[3], audit.SCOPE]
        and expected_state.loc[grid[3], "actual_held"]
    )
    result = kernel.analyze(assembled["features"], assembled["labels"], assembled["scope"])
    statistics_result = audit.verify_statistics(
        assembled["features"], assembled["labels"], assembled["scope"], result
    )
    assert (
        statistics_result["prediction_records"] > 0
        and statistics_result["bootstrap_records"] == 2000
    )
    constant = audit.component(pd.Series(1.0, index=all_axis))
    assert constant.sigma20.iloc[20:].eq(0).all() and constant.vol_concentration.isna().all()
    pd.testing.assert_frame_equal(
        constant, policy_component.construct(pd.Series(1.0, index=all_axis))
    )
    changed = prices_close.copy()
    changed.iloc[-8:] *= 2
    pd.testing.assert_frame_equal(
        audit.component(changed).iloc[:-8], audit.component(prices_close).iloc[:-8]
    )
    tail_labels = audit.continuation_labels(prices, all_axis[-5:])
    assert tail_labels[list(audit.LABELS)].isna().all().all()
    refused = 0
    bad = assembled["scope"].copy()
    bad[audit.SCOPE] = ~bad[audit.SCOPE]
    try:
        audit.verify_statistics(assembled["features"], assembled["labels"], bad, result)
    except AssertionError:
        refused += 1
    else:
        raise AssertionError("scope altered")
    bad_labels = assembled["labels"].copy()
    bad_labels.iloc[2, bad_labels.columns.get_loc("label_end_return_4")] = grid[3]
    bad_output = dict(assembled, labels=bad_labels)
    try:
        audit.verify_inputs(old, prices_close, prices, account, fills, decisions, bad_output)
    except AssertionError:
        refused += 1
    else:
        raise AssertionError("wrong future maturity")
    summary = dict(
        status="PASS",
        artificial_only=True,
        input_audit=input_result,
        statistics_audit=statistics_result,
        focused_checks=8,
        refusals=refused,
        source_files={
            name: sha256((here / name).read_bytes()).hexdigest()
            for name in ("audit.py", "synthetic.py")
        },
        production_sources={
            name: sha256((main_source / name).read_bytes()).hexdigest()
            for name in ("component.py", "inputs.py", "vol_statistics.py")
        },
        real_inputs=0,
        real_statistics=0,
        new_accounts=0,
        publication=0,
    )
    (here / "synthetic.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(summary)


if __name__ == "__main__":
    main()
