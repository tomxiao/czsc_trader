"""Synthetic causal state and label accounting tests only."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
import continuation_core as c
import opportunity_statistics as s
from independent_inputs import verify_inputs
import ast


def fixture():
    dates = pd.bdate_range("2020-01-02", periods=20)
    quantity = [100] * 5 + [0] * 4 + [100] * 5 + [0] * 3 + [100] * 3
    ledger = pd.DataFrame(
        {
            "date": dates,
            "quantity_before": [0] + quantity[:-1],
            "quantity": quantity,
            "close": np.arange(100.0, 120.0),
        }
    )
    fills = []
    for i, side, price in (
        (0, "BUY", 100.0),
        (5, "SELL", 105.0),
        (9, "BUY", 110.0),
        (14, "SELL", 114.0),
        (17, "BUY", 116.0),
    ):
        fills.append(
            {
                "fill_id": str(i),
                "fill_time": dates[i],
                "signal_date": dates[i] - pd.offsets.BDay(),
                "side": side,
                "quantity": 100,
                "price": price,
                "fees": price * 0.1,
            }
        )
    signals = pd.DatetimeIndex([dates[0] - pd.offsets.BDay(), *dates])
    valid = pd.DatetimeIndex([*dates, dates[-1] + pd.offsets.BDay()])
    target = [int(q > 0) for q in quantity] + [1]
    target[6] = 1  # Known desired position with unfilled BUY, still actually flat.
    decisions = pd.DataFrame(
        {"signal_date": signals, "valid_session": valid, "target_position": target}
    )
    return dates, ledger, pd.DataFrame(fills), decisions


def run():
    checks = []
    dates, ledger, fills, decisions = fixture()
    state = c.build_known_state(ledger, fills, decisions, dates)
    assert (
        state.actual_held.iloc[0]
        and state.holding_age.iloc[0] == 1
        and state.entry_mark_pnl.iloc[0] == 0.0
    )
    checks.append("T_close_includes_T_buy")
    assert (
        not state.actual_held.iloc[5]
        and np.isnan(state.holding_age.iloc[5])
        and np.isnan(state.entry_mark_pnl.iloc[5])
    )
    checks.append("T_close_sell_is_flat_no_zero_imputation")
    assert not state.actual_held.iloc[6] and state.signal_held_before.iloc[6]
    checks.append("unfilled_buy_signal_not_actual_position")
    assert state.actual_held.iloc[4] and not state.signal_held_after.iloc[4]
    checks.append("pending_next_day_sell_not_current_flat")
    assert state.holding_age.iloc[9] == 1 and state.entry_gross_price.iloc[9] == 110.0
    checks.append("reentry_uses_only_actual_buy_price")
    for end in (4, 10, 17):
        subset = dates[:end]
        cutoff = subset[-1]
        prefix = c.build_known_state(
            ledger.iloc[:end],
            fills.loc[pd.to_datetime(fills.fill_time) <= cutoff],
            decisions,
            subset,
        )
        pd.testing.assert_frame_equal(prefix, state.iloc[:end], check_exact=True)
        checks.append("state_prefix_" + str(end))
    future_fills = fills.copy()
    future_fills.loc[future_fills.fill_time >= dates[9], "price"] *= 1.5
    changed = c.build_known_state(ledger, future_fills, decisions, dates)
    pd.testing.assert_frame_equal(changed.iloc[:9], state.iloc[:9], check_exact=True)
    checks.append("future_entry_price_no_past_pnl_leak")
    future_decisions = decisions.copy()
    future_decisions.loc[
        pd.to_datetime(future_decisions.signal_date) > dates[8], "target_position"
    ] = 0
    changed = c.build_known_state(ledger, fills, future_decisions, dates)
    pd.testing.assert_frame_equal(changed.iloc[:9], state.iloc[:9], check_exact=True)
    checks.append("future_decisions_no_past_state_leak")
    misleading = ledger.assign(signal_date=pd.to_datetime(ledger.date) + pd.Timedelta(days=100))
    pd.testing.assert_frame_equal(
        c.build_known_state(misleading, fills, decisions, dates), state, check_exact=True
    )
    checks.append("account_date_used_not_previous_plan_signal_date")
    prices = pd.DataFrame(
        {"Open": np.arange(100.0, 120.0), "Close": np.arange(101.0, 121.0)}, index=dates
    )
    labels = c.build_labels(prices, dates)
    assert np.isclose(labels.return_4.iloc[0], 105.0 / 101.0 - 1.0)
    assert labels.label_end_return_4.iloc[0] == dates[5]
    assert labels.label_end_return_8.iloc[0] == dates[9]
    checks.append("next_open_four_eight_complete_session_endpoints")
    assert np.isclose(labels.marked_close_net_4.iloc[0], 0.999 * 105.0 / 101.0 - 1.0)
    assert np.isclose(labels.increment_mark_4.iloc[0], 0.999 * (105.0 - 101.0) / 101.0)
    checks.append("remaining_hold_one_sell_fee_no_sunk_buy_fee")
    old_fresh = 105.0 / 101.0 * 0.999 / 1.001 - 1.0
    assert np.isclose(labels.return_4.iloc[0], (old_fresh + 1.0) * 1.001 / 0.999 - 1.0)
    checks.append("fresh_and_continue_returns_affine_not_new_ranking")
    shock = prices.copy()
    shock.iloc[0] = [100.0, 100.0]
    shock.iloc[1:6] = [90.0, 90.0]
    shocked = c.build_labels(shock, dates)
    assert shocked.return_4.iloc[0] == 0.0 and shocked.downside_4.iloc[0] == 0.0
    assert np.isclose(shocked.marked_close_net_4.iloc[0], -0.1009) and np.isclose(
        shocked.risk_close_4.iloc[0], 0.1
    )
    checks.append("unavoidable_first_overnight_separated_from_continuation")
    last_open = prices.copy()
    last_open.iloc[5, 0] = 50.0
    assert np.isclose(c.build_labels(last_open, dates).downside_4.iloc[0], 1.0 - 50.0 / 101.0)
    checks.append("final_exit_open_gap_in_observed_risk")
    lowclose = prices.copy()
    lowclose.iloc[3, 1] = 60.0
    assert np.isclose(c.build_labels(lowclose, dates).downside_4.iloc[0], 1.0 - 60.0 / 101.0)
    checks.append("future_close_in_observed_risk")
    pd.testing.assert_frame_equal(
        c.build_labels(prices.assign(High=np.nan, Low=-999.0), dates), labels, check_exact=True
    )
    checks.append("High_Low_unused")
    assert labels.return_4.iloc[-5:].isna().all() and labels.return_8.iloc[-9:].isna().all()
    checks.append("immature_tail_remains_missing")
    scaled = c.build_labels(prices * 12.0, dates)
    for name in labels.select_dtypes("number"):
        np.testing.assert_allclose(scaled[name], labels[name], equal_nan=True, atol=1e-13)
    checks.append("label_scale_invariant")
    assert (
        "late_recovery" not in s.CONTROLS
        and len(s.CONTROLS) == 22
        and s.COMPONENTS == ("late_weakness",)
    )
    checks.append("self_opposite_excluded_22controls_single_component")
    rng = np.random.default_rng(13)
    stats_dates = pd.bdate_range("2020-01-02", periods=100).append(
        pd.bdate_range("2021-01-04", periods=45)
    )
    features = pd.DataFrame(
        rng.normal(size=(145, 23)), index=stats_dates, columns=[*s.CONTROLS, *s.COMPONENTS]
    )
    target = 0.01 * features.late_weakness.to_numpy() + rng.normal(0.0, 0.005, 145)
    ends = pd.Series(stats_dates + pd.Timedelta(days=10), index=stats_dates)
    out = s._walk_forward(stats_dates, features, target, ends, np.ones(145, bool))
    assert tuple(out["aggregate_models"]) == ("controls", "controls+late")
    assert len({v["n"] for v in out["aggregate_models"].values()}) == 1
    assert pd.Timestamp(out["yearly"]["2021"]["latest_train_label_end"]) < stats_dates[100]
    checks.append("two_fixed_models_same_rows_mature_train")
    thin = s._ic(rng.normal(size=30), rng.normal(size=30), rng.normal(size=(30, 22)))
    assert (
        thin["value"] is None
        and thin["residual_df"] == 7
        and thin["reason"] == "INSUFFICIENT_RESIDUAL_DF"
    )
    checks.append("partial_residual_df_guard")
    for n, available in ((32, False), (33, True)):
        output = s._ic(rng.normal(size=n), rng.normal(size=n), rng.normal(size=(n, 22)))
        assert output["design_rank"] == 23 and output["residual_df"] == n - 23
        assert (output["value"] is not None) == available
        checks.append("df_exact_boundary_" + str(n))
    rankdeficient = s._ic(
        rng.normal(size=20), rng.normal(size=20), np.column_stack([np.arange(20.0)] * 22)
    )
    assert rankdeficient["design_rank"] == 2 and rankdeficient["residual_df"] == 18
    checks.append("actual_rank_not_nominal_control_count")
    fresh = labels.copy()
    for h in (4, 8):
        fresh["return_" + str(h)] = (labels["return_" + str(h)] + 1) * 0.999 / 1.001 - 1
    independent = verify_inputs(ledger, fills, decisions, state, prices, labels, fresh)
    assert independent["affine_paired_rows"] == {"4": 15, "8": 11}
    checks.append("independent_real_check_path_on_synthetic_fills_and_labels")
    damaged = labels.copy()
    damaged.iloc[0, damaged.columns.get_loc("return_4")] += 0.001
    try:
        verify_inputs(ledger, fills, decisions, state, prices, damaged, fresh)
    except AssertionError:
        checks.append("independent_label_corruption_rejected")
    else:
        raise AssertionError("independent checker accepted corrupt label")
    assert s.METHOD["walk_forward"]["models"] == ["controls", "controls+late"]
    assert tuple(s.HORIZONS) == ("return_4", "return_8", "downside_4", "downside_8")
    for path in Path(__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        compile(tree, str(path), "exec")
    checks.append("all_final_sources_parse_compile")
    refusals = []
    invalid = ledger.copy()
    invalid.loc[1, "quantity"] = 99
    try:
        c.build_known_state(invalid, fills, decisions, dates)
    except ValueError:
        refusals.append("inconsistent_quantity")
    else:
        raise AssertionError("quantity inconsistency accepted")
    invalid_prices = prices.copy()
    invalid_prices.iloc[0, 0] = 0.0
    try:
        c.build_labels(invalid_prices, dates)
    except ValueError:
        refusals.append("invalid_price")
    else:
        raise AssertionError("invalid price accepted")
    invalid_fills = fills.copy()
    invalid_fills.loc[0, "signal_date"] = invalid_fills.loc[0, "fill_time"]
    try:
        c.build_known_state(ledger, invalid_fills, decisions, dates)
    except ValueError:
        refusals.append("same_day_signal_fill")
    else:
        raise AssertionError("same day signal accepted")
    return {
        "status": "PASS",
        "synthetic_only": True,
        "checks": checks,
        "refusals": refusals,
        "market_reads": 0,
        "statistics_runs": 0,
        "new_accounts": 0,
        "experiment_allocations": 0,
        "source_hashes": {
            p.name: sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")
        },
    }


if __name__ == "__main__":
    result = run()
    Path(__file__).with_name("focused_checks.json").write_text(
        json.dumps(result, indent=2), "utf-8"
    )
    print({"status": "PASS", "checks": len(result["checks"]), "refusals": len(result["refusals"])})
