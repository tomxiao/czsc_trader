"""Small artificial price sequences only. Production output is audited, not expected."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from math import log
from pathlib import Path

import numpy as np
import pandas as pd

import independent_policy_audit as audit


def main():
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "artificial_production_policy", here / "policy.py"
    )
    production = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(production)
    prices = [128.0, 128.0, 128.0, 8.0, 8.0, 8.0, 4.0] + [4.0] * 25 + [8.0] * 6 + [4.0]
    axis = pd.bdate_range("2000-01-03", periods=len(prices)).as_unit("ns")
    close, signals = pd.Series(prices, index=axis), axis[5:]
    expected = audit.online(close, signals, lookback=2, distance=1.0)
    actual = production.decisions(close, signals, lookback=2, distance=1.0)
    comparison = audit.compare(actual, expected)
    centre_comparison = audit.compare(
        production.decisions(close, signals, lookback=20, distance=1.0),
        audit.online(close, signals, lookback=20, distance=1.0),
    )
    assert audit.population_sigma([0.0, log(2)]) == log(2) / 2
    assert expected.iloc[0].state_before == expected.iloc[0].state_after == "FLAT"
    assert expected.iloc[0].known_peak == 8  # Historic128 must not seed price-event peak.
    arm = expected.iloc[1]
    assert arm.state_after == "ARMED" and arm.target_position == 0
    assert log(8) - log(4) == 2 * arm.sigma_current  # Exact arm >= boundary fixture.
    assert arm.sigma_locked == arm.sigma_current
    wait = expected.loc[axis[7:32]]
    assert wait.state_after.eq("ARMED").all() and wait.target_position.eq(0).all()
    assert wait.sigma_current.eq(0).any() and wait.sigma_locked.eq(arm.sigma_locked).all()
    held = expected.loc[axis[32:38]]
    assert held.state_after.eq("HELD").all() and held.target_position.eq(1).all()
    assert held.sigma_current.eq(0).any() and held.sigma_locked.eq(arm.sigma_locked).all()
    assert expected.iloc[-1].state_after == "FLAT"
    assert pd.isna(expected.iloc[-1].sigma_locked) and pd.isna(expected.iloc[-1].known_trough)
    # Independent online prefix equality: valid future prices never change prior decisions.
    for end in (7, 16, 32, 35, len(axis)):
        prefix = audit.online(close.iloc[:end], axis[5:end], lookback=2, distance=1.0)
        audit.compare(prefix, expected.iloc[: end - 5])
    # Synthetic failed fills do not feed the policy. Target1 can coexist with quantity0.
    artificial_actual_quantity = pd.Series(0, index=signals)
    assert ((expected.target_position == 1) & (artificial_actual_quantity == 0)).any()
    refused = 0
    corrupt = deepcopy(actual)
    corrupt.loc[held.index, "target_position"] = 0
    try:
        audit.compare(corrupt, expected)
    except AssertionError:
        refused += 1
    else:
        raise AssertionError("actual position cannot replace policy target")
    for kwargs in (
        dict(lookback=True),
        dict(lookback=1),
        dict(distance=1),
        dict(distance=float("nan")),
    ):
        try:
            audit.online(close, signals, **kwargs)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("invalid full-domain type accepted")
    try:
        audit.online(close, signals.delete(2), lookback=2, distance=1.0)
    except ValueError:
        refused += 1
    else:
        raise AssertionError("state prefix gap accepted")
    try:
        audit.verify_native_policy(close, signals, actual)
    except ValueError:
        refused += 1
    else:
        raise AssertionError("subset artificial axis became original native prefix")
    bad_price = close.copy()
    bad_price.iloc[0] = np.nan
    try:
        audit.online(bad_price, signals, lookback=2, distance=1.0)
    except ValueError:
        refused += 1
    else:
        raise AssertionError("missing warmup repaired")
    result = dict(
        status="PASS",
        artificial_only=True,
        fixture_prices=len(close),
        signal_rows=len(signals),
        checks=[
            "hand_population_sigma",
            "warm_not_state_seed",
            "arm_boundary_no_same_day_buy",
            "locked_sigma_and_no_armed_expiry",
            "held_rolling_zero_keeps_locked_sigma",
            "exit_clears_episode",
            "causal_prefix",
            "intent_separate_from_failed_fills",
        ],
        refusals=refused,
        comparison=comparison,
        fixed_centre20_distance1_comparison=centre_comparison,
        independent_sources={
            name: sha256((here / name).read_bytes()).hexdigest()
            for name in ("independent_policy_audit.py", "independent_policy_proof.py")
        },
        production_policy_sha256=sha256((here / "policy.py").read_bytes()).hexdigest(),
        limitations="Independent math.log/fsum population arithmetic can differ at machine-exact boundaries; states remain exact-required, no epsilon or tolerated state rescue.",
        real_prices=0,
        real_signals=0,
        prepare=0,
        evaluate=0,
        experiment=0,
        publication=0,
    )
    (here / "independent_policy_proof.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
    )
    print(result)


if __name__ == "__main__":
    main()
