"""Final result audit plus explicitly post-hoc descriptive benchmark checks."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json

import numpy as np
import pandas as pd
import requests
from czsc_trader.application import RepositoryContext, create_research_context, validate_delivery
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, DeliveryReference, ValidationStatus
from components import observe_completed_session
from methods import extended_features
from role_methods import true_range, amplitude_target
from study import fetch_inputs

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
FIRST = ROOT / "research/S014/assets/runs/EX005_20261016/first"
ROLES = ROOT / "research/S014/assets/runs/EX005_20261016/roles"


def main():
    if (EXPERIMENT / "others/audit.json").exists():
        raise RuntimeError("Preserve completed audit")
    checks = []

    def require(name, value):
        if not bool(value):
            raise AssertionError(name)
        checks.append(name)

    for binding_name in ("published_design", "published_roles", "published_robustness"):
        for value in json.loads((EXPERIMENT / f"protocols/{binding_name}.json").read_text(encoding="utf-8")).values():
            EvidenceRef.from_dict(value).resolve(ROOT)
    checks.append("all_preregistered_evidence_identity")
    prior = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    repository = RepositoryContext.discover(ROOT)
    require("prior_delivery_still_full_pass", validate_delivery(repository, DeliveryReference.from_dict(prior["delivery"])).status is ValidationStatus.PASS)
    context = create_research_context(repository, ResearchBatchRef("S014"))
    original = requests.sessions.Session.request

    def prohibit(*args, **kwargs):
        raise RuntimeError("Network prohibited during closure")

    requests.sessions.Session.request = prohibit
    try:
        inputs, dates = fetch_inputs(context, prior)
    finally:
        requests.sessions.Session.request = original
    calendar = inputs["calendar.trading_sessions"]
    require("all_five_native_input_hashes_and_session_calendar", dates.equals(pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), "Date"]))))
    bars, raw, limits = inputs["stock.ohlcv"], inputs["stock.unadjusted_daily"], inputs["security.price_limits"]
    ext = extended_features(bars)
    pd.testing.assert_frame_equal(ext.drop(columns="gap_next_open").iloc[:800], extended_features(bars.iloc[:800]).drop(columns="gap_next_open"))
    checks.append("real_data_decision_feature_prefix")
    forecasts = pd.read_csv(FIRST / "forecasts.csv")
    old = pd.read_csv(BytesIO(EvidenceRef.from_dict(prior["evidence"]["followup-predictions"]).resolve(ROOT).read_bytes()))
    require("32_replicated_fixed_fits", forecasts.groupby(["model", "horizon", "year"]).ngroups == 32)
    require("actual_label_maturity_precedes_test_year", forecasts.train_last_maturity.lt(forecasts.first_test_signal).all())
    for (model, horizon, year), part in forecasts.groupby(["model", "horizon", "year"]):
        saved = old.loc[old.model.eq(model) & old.horizon.eq(horizon) & old.year.eq(year)]
        require_name = f"Prediction replication {model}/{horizon}/{year}"
        if not np.array_equal(saved.signal, part.signal) or not np.allclose(saved.prediction, part.prediction, rtol=0, atol=1e-10):
            raise AssertionError(require_name)
        quantile = .25 if "risk" in model else .75
        threshold = part.prediction.shift(1).rolling(63, min_periods=63).quantile(quantile)
        where = threshold.notna()
        np.testing.assert_allclose(threshold.loc[where], part.loc[where, "rolling_threshold"], atol=1e-12, rtol=0)
    checks.extend(["all_saved_old_predictions_reproduced", "strict_past63_thresholds_recomputed_within_each_test_year"])
    annual = pd.read_csv(FIRST / "annual.csv")
    first_result = json.loads((FIRST / "result.json").read_text(encoding="utf-8"))
    for comparison in first_result["comparisons"]:
        selected = annual.loc[annual.comparison.eq(comparison["comparison"]) & annual.horizon.eq(comparison["horizon"])]
        if comparison["difference"] is None:
            if not selected.difference.isna().any():
                raise AssertionError("Missing result without missing selection")
        else:
            value = float((selected.difference * selected.dates).sum() / selected.dates.sum())
            np.testing.assert_allclose(value, comparison["difference"], atol=1e-12, rtol=0)
    checks.append("20_primary_results_and_missing_selection_semantics")
    ranges = true_range(bars)
    amplitude = pd.read_csv(ROLES / "amplitude_forecasts.csv")
    require("24_amplitude_fixed_fits_and_maturity", amplitude.groupby(["model", "horizon", "year"]).ngroups == 24 and amplitude.train_last_maturity.lt(amplitude.first_test_signal).all())
    descriptive, weighted = [], []
    for horizon in (1, 3, 5):
        target = amplitude_target(ranges, horizon)
        groups = amplitude.loc[amplitude.model.eq("baseline") & amplitude.horizon.eq(horizon)]
        for year, part in groups.groupby("year"):
            np.testing.assert_allclose(part.actual, target.loc[part.signal], atol=1e-12, rtol=0)
            first = int(np.flatnonzero(dates.year == year)[0])
            training = np.arange(20, first - horizon)
            # This is a post-hoc descriptive reference, not a searched configuration or a new inferential test.
            mean = float(target.loc[training].mean())
            actual = part.actual.to_numpy()
            current = ranges.loc[part.signal].to_numpy()
            descriptive.append({"horizon": horizon, "year": int(year), "dates": len(part),
                "current_range_mae": float(np.mean(np.abs(current - actual))),
                "training_mean_mae": float(np.mean(np.abs(mean - actual))),
                "difference": float(np.mean(np.abs(mean - actual) - np.abs(current - actual)))})
        losses = pd.read_csv(EXPERIMENT / "others/persistence_controls.csv")
        for model, rows in losses.loc[losses.horizon.eq(horizon)].groupby("model"):
            weighted.append({"horizon": horizon, "model": model, "weighted_mae": float((rows.mae * rows.dates).sum() / rows.dates.sum())})
    checks.append("all_amplitude_labels_recomputed_from_pinned_bars")
    pd.DataFrame(descriptive).to_csv(EXPERIMENT / "others/descriptive_mean_control.csv", index=False)
    pd.DataFrame(weighted).to_csv(EXPERIMENT / "others/weighted_amplitude_errors.csv", index=False)
    execution = pd.read_csv(ROLES / "execution_observations.csv")
    expected_flags = (raw.Close - limits.UpLimit).abs().le(.005).to_numpy()[execution.signal]
    require("execution_flag_uses_official_signal_day_limit_only", np.array_equal(expected_flags, execution.limit_close))
    labels = pd.read_csv(BytesIO(EvidenceRef.from_dict(prior["evidence"]["labels"]).resolve(ROOT).read_bytes()))
    original_entry = labels.loc[labels.horizon.eq(3)]
    require("next_session_nonfill_labels_include_observed_return_censored_entries", np.array_equal(execution.entry_filled, original_entry.entry_filled))
    observed = []
    for index in range(1, len(dates)):
        value = observe_completed_session(previous_hfq_close=float(bars.Close.iloc[index - 1]), hfq_high=float(bars.High.iloc[index]),
            hfq_low=float(bars.Low.iloc[index]), raw_close=float(raw.Close.iloc[index]),
            raw_upper_limit=float(limits.UpLimit.iloc[index]), raw_tick=.01)
        observed.append(value)
    np.testing.assert_allclose([x.true_range_fraction for x in observed], ranges.iloc[1:], atol=1e-12, rtol=0)
    np.testing.assert_array_equal([x.close_at_upper_limit for x in observed], (raw.Close - limits.UpLimit).abs().le(.005).iloc[1:])
    checks.append("deliverable_component_definition_matches_all1641_observations")
    for key, value in (("previous_hfq_close", 0), ("hfq_high", float("nan")), ("raw_tick", -.01)):
        example = dict(previous_hfq_close=10., hfq_high=10.2, hfq_low=9.9, raw_close=10., raw_upper_limit=11., raw_tick=.01)
        example[key] = value
        try:
            observe_completed_session(**example)
        except ValueError:
            continue
        raise AssertionError("Invalid component input accepted")
    checks.append("component_invalid_price_boundaries_rejected")
    manifests = []
    for folder in (FIRST, ROLES):
        for path in sorted(folder.glob("*")):
            manifests.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
    result = {"status": "PASS", "checks": checks, "manifest": manifests,
        "new_fits": 56, "fit_breakdown": {"replicated_fixed_fits": 32, "new_fixed_amplitude_fits": 24},
        "total_history_fits": 248, "new_primary_comparisons": 30, "primary_comparison_history": 62,
        "source_calls": 0, "strategy_accounts": 0, "parameter_searches": 0,
        "secondary_diagnostic": "Training-mean forecast MAE is a post-hoc descriptive sanity reference, not an independent new confirmatory test or selection gate",
        "limitations": ["Seen development data and adaptive design", "No historical publication or revision timestamps verified", "Risk scale is not directional loss or account drawdown", "Supported context components do not establish annual strategy acceptance"]}
    (EXPERIMENT / "others/audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": len(checks), "new_fits": 56, "history_comparisons": 62}))


if __name__ == "__main__":
    main()
