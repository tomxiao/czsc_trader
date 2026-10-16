"""Audit attribution identities, chronology and descriptive concentration."""
from hashlib import sha256
from pathlib import Path
import json

import numpy as np
import pandas as pd
import requests
from czsc_trader.application import RepositoryContext, create_research_context, validate_delivery
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, DeliveryReference, ValidationStatus
from study import load_inputs, observations

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX006_20261016/first"


def main():
    if (EXPERIMENT / "others/audit.json").exists():
        raise RuntimeError("Preserve completed audit")
    checks = []

    def require(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    previous = json.loads((ROOT / "research/S014/experiments/EX005_20261016/others/result.json").read_text(encoding="utf-8"))
    repository = RepositoryContext.discover(ROOT)
    require("predecessor_full_pass", validate_delivery(repository, DeliveryReference.from_dict(previous["delivery"])).status is ValidationStatus.PASS)
    binding = json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8"))
    for name, relative in (("design", "protocols/design.json"), ("attribution", "src/attribution.py"), ("paired", "src/paired.py"), ("study", "src/study.py")):
        ref = EvidenceRef.from_dict(binding[name])
        require(f"published_{name}_identity", (EXPERIMENT / relative).read_bytes() == ref.resolve(ROOT).read_bytes())
    initial = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    context = create_research_context(repository, ResearchBatchRef("S014"))
    original = requests.sessions.Session.request

    def prohibit(*args, **kwargs):
        raise RuntimeError("Network prohibited in attribution audit")

    requests.sessions.Session.request = prohibit
    try:
        inputs, dates = load_inputs(context, initial)
    finally:
        requests.sessions.Session.request = original
    anchor, prices, scales, down, up, ticks, features = observations(inputs)
    subset = {key: frame.iloc[:800] for key, frame in inputs.items() if key != "calendar.trading_sessions"}
    np.testing.assert_array_equal(features[:800], observations(subset)[-1])
    checks.extend(["native_input_hashes_calendar_and_status", "real_feature_prefix_causality"])
    paths = pd.read_csv(RUN / "paths.csv")
    decisions = pd.read_csv(RUN / "decisions.csv")
    closed = paths.loc[paths.status.eq("CLOSED")]
    require("unique_signal_horizon", not paths.duplicated(["signal", "horizon"]).any())
    identity = closed.signal_exit_same_quantity_cash - closed.gap_cash - closed.intraday_entry_cash - closed.fees_cash
    require("all_closed_cash_attribution_identities", np.allclose(identity, closed.net_return, rtol=0, atol=1e-12))
    require("all_closed_gross_minus_fees", np.allclose(closed.holding_gross_cash - closed.fees_cash, closed.net_return, rtol=0, atol=1e-12))
    require("lot_and_cash_bounds", (closed.quantity.mod(100).eq(0) & (closed.quantity * closed.entry_price * 1.001 <= 100000 + 1e-7)).all())
    common = paths.loc[paths.common]
    require("identical_common_signals_all_horizons", common.groupby("horizon").signal.apply(set).apply(lambda x: x == set(common.signal)).all())
    unfilled = paths.loc[paths.status.eq("UNFILLED")]
    require("unfilled_zero_cash_no_invented_position", (unfilled.net_return.eq(0) & unfilled.fees_cash.eq(0) & unfilled.entry_price.isna()).all())
    censored = paths.loc[paths.status.eq("RIGHT_CENSORED")]
    require("right_censored_stays_unliquidated", censored.net_return.isna().all() and not censored.common.any())
    require("hindsight_is_bounded_and_later_than_entry", (closed.earlier_hindsight_best.ge(closed.net_return - 1e-12) &
        closed.hindsight_best_exit.gt(closed.entry) & closed.hindsight_best_exit.le(closed.maturity) & closed.candidate_count.eq(closed.horizon)).all())
    require("checkpoints_precede_exit_and_sell_next_session", (decisions.decision.ge(decisions.entry) &
        decisions.decision.lt(decisions.planned_exit) & decisions.earlier_exit.gt(decisions.decision) & decisions.earlier_exit.le(decisions.maturity)).all())
    require("exit_comparison_cash_identity", np.allclose(decisions.earlier_net - decisions.fixed_net, decisions.exit_advantage, rtol=0, atol=1e-12))
    require("condition_uses_known_mark_and_known_daily_return", np.array_equal(decisions.selected, (decisions.known_mark_net > 0) & (decisions.known_ret1 < 0)) and
        np.array_equal(decisions.control, (decisions.known_mark_net > 0) & (decisions.known_ret1 >= 0)))
    lookup = closed.set_index(["signal", "horizon"])
    for row in closed.itertuples():
        marks = row.quantity * (prices[int(row.entry):int(row.maturity), 3] * .999 - row.entry_price * 1.001) / 100000
        if not np.isclose(max(0., float(marks.max())), row.positive_close_mark_peak, atol=1e-12, rtol=0):
            raise AssertionError("Close mark includes wrong sessions")
    for row in decisions.itertuples():
        trade = lookup.loc[(row.signal, row.horizon)]
        mark = trade.quantity * (prices[row.decision, 3] * .999 - trade.entry_price * 1.001) / 100000
        if not np.isclose(mark, row.known_mark_net, atol=1e-12, rtol=0):
            raise AssertionError("Checkpoint mark mismatch")
        if not np.isclose(row.known_ret1, prices[row.decision, 3] / prices[row.decision - 1, 3] - 1, atol=1e-12, rtol=0):
            raise AssertionError("Checkpoint return mismatch")
    checks.extend(["close_marks_exclude_exit_day", "all_checkpoint_features_recomputed_from_native_bars"])
    result = json.loads((EXPERIMENT / "others/computation_result.json").read_text(encoding="utf-8"))
    require("no_new_models_sources_or_strategy_accounts", result["new_model_fits"] == result["new_source_calls"] == result["strategy_accounts"] == result["parameter_searches"] == 0)
    for comparison in result["comparisons"]:
        if comparison["status"] == "COMPUTED":
            years = comparison["years"]
            expected = sum(x["difference"] * x["dates"] for x in years) / sum(x["dates"] for x in years)
            if not np.isclose(expected, comparison["difference"], atol=1e-12, rtol=0):
                raise AssertionError("Annual aggregation mismatch")
    checks.append("all16_primary_annual_aggregations")
    concentration, contribution = [], []
    common_mature = common.loc[common.status.ne("RIGHT_CENSORED")]
    for horizon, all_rows in common_mature.groupby("horizon"):
        for year, rows in [("ALL", all_rows), *list(all_rows.groupby("year"))]:
            ordered = rows.sort_values("net_return", ascending=False)
            positive = rows.loc[rows.net_return.gt(0), "net_return"]
            concentration.append({"horizon": int(horizon), "year": str(year), "attempts": len(rows),
                "median_net_attempt": float(rows.net_return.median()), "mean_net_attempt": float(rows.net_return.mean()),
                "mean_drop_top1": float(ordered.iloc[1:].net_return.mean()), "mean_drop_top3": float(ordered.iloc[3:].net_return.mean()),
                "largest_positive_attempt_share": float(positive.max() / positive.sum()) if len(positive) else None})
        by_year = all_rows.groupby("year").net_return.sum()
        top = by_year.nlargest(2)
        contribution.append({"horizon": int(horizon), "top_two_years": [int(x) for x in top.index],
            "top_two_share_of_net_attempt_sum": float(top.sum() / by_year.sum()),
            "remaining_years_mean": float(all_rows.loc[~all_rows.year.isin(top.index), "net_return"].mean()),
            "note": "Overlapping independent attempts; this sum is descriptive, not actual account profit contribution"})
    pd.DataFrame(concentration).to_csv(EXPERIMENT / "others/concentration.csv", index=False)
    (EXPERIMENT / "others/year_contribution.json").write_text(json.dumps(contribution, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest = [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p.read_bytes()).hexdigest()} for p in sorted(RUN.glob("*"))]
    audit = {"status": "PASS", "checks": checks, "manifest": manifest, "closed_rows": len(closed), "common_attempts_per_horizon": len(common) // 4,
        "common_filled_per_horizon": int(common.loc[common.horizon.eq(3)].entry_filled.sum()), "common_unfilled_per_horizon": int((~common.loc[common.horizon.eq(3)].entry_filled).sum()),
        "new_model_fits": 0, "new_source_calls": 0, "strategy_accounts": 0, "primary_comparisons": 16,
        "secondary_concentration": "Descriptive top-positive-attempt removal and top-year concentration; not independent confirmatory tests, account returns or tradable year labels",
        "limits": "Checks establish identities and declared chronology, not profitable timing or annual economic acceptance"}
    (EXPERIMENT / "others/audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": len(checks), "closed_rows": len(closed)}))


if __name__ == "__main__":
    main()
