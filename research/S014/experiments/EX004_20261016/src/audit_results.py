"""Audit saved component results and add descriptive controls, without refitting."""
from hashlib import sha256
from pathlib import Path
import json

import numpy as np
import pandas as pd
from followup_models import interval

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX004_20261016/first"


def main():
    if (EXPERIMENT / "others/audit.json").exists():
        raise RuntimeError("Audit already preserved; publish a new revision for changes")
    features = pd.read_csv(RUN / "features.csv", index_col="signal")
    labels = pd.read_csv(RUN / "labels.csv")
    predictions = pd.read_csv(RUN / "followup_predictions.csv")
    dates = pd.DatetimeIndex(pd.to_datetime(features.signal_date))
    initial = json.loads((RUN / "result.json").read_text(encoding="utf-8"))
    followup = json.loads((RUN / "followup_result.json").read_text(encoding="utf-8"))
    checks = []

    def check(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    check("unique_signal_horizon_labels", not labels.duplicated(["signal", "horizon"]).any())
    closed = labels.loc[labels.status.eq("CLOSED")]
    check("closed_after_entry_and_planned_exit", ((closed.maturity >= closed.planned_exit) & (closed.entry > closed.signal)).all())
    expected = closed.quantity * (closed.exit_price * .999 - closed.entry_price * 1.001) / 100000
    check("exact_both_sides_fee_and_cash_denominator", np.allclose(expected, closed.net_return, atol=1e-12, rtol=0))
    check("lot_and_cash_limits", (closed.quantity.mod(100).eq(0) & closed.quantity.gt(0) &
                                 (closed.quantity * closed.entry_price * 1.001 <= 100000 + 1e-7)).all())
    unfilled = labels.loc[labels.status.eq("UNFILLED")]
    check("unfilled_explicit_zero", (unfilled.net_return.eq(0) & unfilled.adverse.eq(0) & ~unfilled.entry_filled).all())
    censored = labels.loc[labels.status.eq("RIGHT_CENSORED")]
    check("right_censored_not_liquidated", (censored.maturity.eq(-1) & censored.net_return.isna() & censored.adverse.isna()).all())
    check("192_distinct_fixed_model_fits", predictions.groupby(["model", "horizon", "year"]).ngroups == 192)
    label_index = labels.set_index(["signal", "horizon"])
    original = pd.read_csv(RUN / "predictions.csv")
    check("training_maturity_before_test", original.train_last_maturity.lt(original.test_first_signal).all())
    for (model, horizon, year), part in predictions.groupby(["model", "horizon", "year"]):
        eligible = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0)]
        first = int(np.flatnonzero(dates.year == year)[0])
        train = eligible.loc[eligible.maturity.lt(first)]
        expected_signals = eligible.loc[pd.to_datetime(eligible.signal_date).dt.year.eq(year), "signal"]
        if not np.array_equal(part.signal.to_numpy(), expected_signals.to_numpy()):
            raise AssertionError(f"Missing or different eligible samples: {model}/{horizon}/{year}")
        if not train.maturity.lt(first).all() or len(train) < 200:
            raise AssertionError("Invalid chronological training split")
        selected_by_score = (part.prediction <= part.threshold if "risk" in model else part.prediction >= part.threshold)
        if not np.array_equal(selected_by_score, part.selected):
            raise AssertionError("Selection does not match frozen training threshold")
        outcomes = label_index.loc[list(zip(part.signal, part.horizon, strict=True))]
        if not np.allclose(outcomes.net_return, part.net_return, rtol=0, atol=1e-12):
            raise AssertionError("Prediction outcome mismatches saved execution label")
    checks.extend(["all_192_temporal_splits_and_sample_identity", "all_192_score_threshold_selections", "all_prediction_labels_match_execution_labels"])
    comparisons = []
    definitions = [(x["family"], x["horizon"], x) for x in initial["comparisons"]]
    definitions += [(x["model"], x["horizon"], x) for x in followup["comparisons"]]
    for model, horizon, saved in definitions:
        target = "adverse" if "risk" in model else "net_return"
        baseline = ("tree-" if model.startswith("tree-") else "") + ("risk-base" if target == "adverse" else "return-base")
        contributions = []
        for year in (2023, 2024, 2025, 2026):
            left = predictions.loc[predictions.model.eq(model) & predictions.horizon.eq(horizon) & predictions.year.eq(year)].set_index("signal")
            right = predictions.loc[predictions.model.eq(baseline) & predictions.horizon.eq(horizon) & predictions.year.eq(year)].set_index("signal")
            if not left.index.equals(right.index) or not left.selected.any() or not right.selected.any():
                raise AssertionError("Unmatched or empty comparison selections")
            a, b = left.selected.to_numpy(), right.selected.to_numpy()
            contributions.append(left[target].to_numpy() * (a / a.mean() - b / b.mean()) * (-1 if target == "adverse" else 1))
        result = interval((contributions, 13 + horizon))
        if not np.isclose(result["difference"], saved["difference"], atol=1e-12, rtol=0):
            raise AssertionError("Aggregate comparison does not reproduce")
        comparisons.append({"model": model, "horizon": horizon, "difference": result["difference"],
                            "low95": result["interval_95"][0], "high95": result["interval_95"][1],
                            "low_family32": result["interval_familywise"][0], "high_family32": result["interval_familywise"][1],
                            "positive_years": sum(float(x.mean()) > 0 for x in contributions)})
    pd.DataFrame(comparisons).to_csv(EXPERIMENT / "others/comparisons_32.csv", index=False)
    checks.append("all_32_comparison_aggregates_reproduced_with_common_family32_intervals")
    descriptive = []
    for model in ("return-base", "reversal", "tree-risk-base", "tree-risk"):
        for (horizon, year), part in predictions.loc[predictions.model.eq(model)].groupby(["horizon", "year"]):
            selected = part.loc[part.selected]
            filled = selected.loc[selected.entry_filled]
            descriptive.append({"model": model, "horizon": int(horizon), "year": int(year), "eligible": len(part),
                                "selected": len(selected), "selection_rate": float(part.selected.mean()),
                                "filled": len(filled), "fill_rate": float(selected.entry_filled.mean()),
                                "mean_net_return": float(selected.net_return.mean()), "mean_adverse": float(selected.adverse.mean()),
                                "filled_only_adverse": float(filled.adverse.mean()) if len(filled) else None,
                                "unconditional_net_return": float(part.net_return.mean())})
    pd.DataFrame(descriptive).to_csv(EXPERIMENT / "others/descriptive_controls.csv", index=False)
    paths = (RUN / name for name in ("features.csv", "labels.csv", "predictions.csv", "coefficients.csv", "annual_comparisons.csv",
                                    "followup_predictions.csv", "followup_annual.csv", "result.json", "followup_result.json"))
    manifest = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
                 "sha256": sha256(path.read_bytes()).hexdigest()} for path in paths]
    result = {"status": "PASS", "checks": checks, "label_rows": len(labels), "prediction_rows": len(predictions),
              "model_fits": 192, "comparisons": 32, "common_familywise_count": 32,
              "positive_common_familywise_intervals": sum(x["low_family32"] > 0 for x in comparisons),
              "source_calls": 0, "new_model_fits": 0, "new_comparisons": 0, "manifest": manifest,
              "limits": ["Audit does not establish source publication timing or economic strategy acceptance",
                         "Family intervals are approximate dependent development-sample diagnostics; adaptive selection remains disclosed",
                         "Selection fractions normalize evaluation means only and differ between models; tree ties can select more than 25 percent",
                         "All annual component groups use signal year, not continuous-account annual profit or drawdown"]}
    (EXPERIMENT / "others/audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": len(checks), "positive_family_intervals": result["positive_common_familywise_intervals"]}))


if __name__ == "__main__":
    main()
