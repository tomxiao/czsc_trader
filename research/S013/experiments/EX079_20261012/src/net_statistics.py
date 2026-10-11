"""Fixed original-information net-opportunity diagnostics. No account/market IO."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import inputs

MODELS = ("training_mean", "confirmation_only", "original14_joint")
SOURCE_REL = "research/S013/experiments/EX066_20261011/src/opportunity_statistics.py"
SOURCE_SHA = "565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a"
METHOD = {
    "version": "s013-original14-net-opportunity-fixedh4-v1",
    "features": list(inputs.FEATURES),
    "models": list(MODELS),
    "label": "Open[T+5]/Open[T+1]*(.999/1.001)-1, matureT+5; fractional nextOpen proxy, not native fill/account",
    "training": "All14complete/finite target;2020<=year<testyear; label_end strictly before first full-axis testT; common rows,train40",
    "prediction": "2021..26 annual fixedmodels; testfeaturecomplete>=20; predict everycompletefeatureT independent of futurelabels, including immaturetail;2020 unavailable",
    "transform": "trainingECDF midpoint ties; fixedalpha10/unpenalized intercept; originalEX066 numerical methods authenticated bysourceSHA",
    "groups": "positive score>0,nonpositive<=0,all;zero explicit;falsepositive truth<=0;futurelabel onlyevaluation",
    "panels": "all/year2020..26/originalaxisposmod5/causalconfirmation_opportunity auxiliary only; no subgroup fitting",
    "bootstrap": "SharedfullTaxis500overlap40 seed13 once; group aftersampling existingOOS predictions;8fixedquantities;originalandrep requiredgroupn>=20,400valid LINEAR95CI,all500statuses",
    "quantities": [
        "training_mean_positive_mean",
        "confirmation_only_positive_mean",
        "original14_joint_positive_mean",
        "training_mean_positive_minus_all",
        "confirmation_only_positive_minus_all",
        "original14_joint_positive_minus_all",
        "joint_minus_confirmation_positive",
        "joint_minus_training_mean_positive",
    ],
    "reuse": "Actual study requires exact EX066 fullscope return4 controls prediction records (original14 and original16 finite masks equal). Matured joint14/mean predictions are copied, not refitted; yearly training_dates/maturity/target/baseline checked. Only missing feature-only2026tail joint scores use samefixed training coefficient reconstruction; mean tail copies prior sameyearbaseline. Only confirmation model newlyfit.",
    "limits": "Positiveproxymean alone notalpha. No full2020forecasts, no110closed/nativeprofit/DD/4gates/32Q10Q90proof. Adaptive seenpool, no sign/window/threshold/model search or account escalation. MSE/IC/group/concentration are diagnostic,notnew economicgates.",
    "delivery": "FromEX079 root closeout copies formaldelivery report byte-exact to experiment others/report.md withSHAcomparison; no extraEX/round",
    "numeric_dependency": {SOURCE_REL: SOURCE_SHA},
}


def legacy():
    root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
    path = root / SOURCE_REL
    if sha256(path.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("immutable original numerical source drift")
    name = "s013_base_net_original_numeric"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def score_model(model, train_x, train_y, test_x):
    old = legacy()
    if model == "training_mean":
        return np.full(len(test_x), float(train_y.mean()))
    columns = (
        [inputs.FEATURES.index("confirmation_score")]
        if model == "confirmation_only"
        else list(range(14))
        if model == "original14_joint"
        else None
    )
    if columns is None:
        raise ValueError("only three fixed models allowed")
    ranked_train = np.column_stack([old._cdf_apply(col, col) for col in train_x[:, columns].T])
    ranked_test = np.column_stack(
        [
            old._cdf_apply(col, values)
            for col, values in zip(train_x[:, columns].T, test_x[:, columns].T)
        ]
    )
    return old._ridge_predict(ranked_train, train_y, ranked_test)


def forecasts(features, labels, prior14_records):
    axis = features.index
    x, y = features.to_numpy(float), labels.return_4.to_numpy(float)
    ends = labels.label_end_return_4
    feature_complete = np.isfinite(x).all(axis=1)
    scores = pd.DataFrame(np.nan, index=axis, columns=MODELS)
    reasons = pd.Series("NO_PROSPECTIVE_2020_FORECAST", index=axis, dtype="string")
    yearly = {}
    if not isinstance(prior14_records, list):
        raise ValueError("exact original fullscope return4 controls records required")
    records = {}
    for record in prior14_records:
        day = pd.Timestamp(record["signaldate"])
        if (
            day not in axis
            or day in records
            or day.year not in range(2021, 2027)
            or not np.isfinite([record["target"], record["prediction"], record["baseline"]]).all()
        ):
            raise ValueError("unique aligned original OOS numeric records required")
        records[day] = record
    for year in range(2021, 2027):
        year_axis = axis[axis.year == year]
        first = year_axis[0] if len(year_axis) else None
        test = feature_complete & (axis.year == year)
        train = (
            feature_complete
            & np.isfinite(y)
            & (axis.year >= 2020)
            & (axis.year < year)
            & ((ends < first).to_numpy(bool) if first is not None else False)
        )
        reason = (
            "NO_TEST_YEAR"
            if first is None
            else "INSUFFICIENT_TRAIN_SAMPLE"
            if train.sum() < 40
            else "INSUFFICIENT_FEATURE_TEST_SAMPLE"
            if test.sum() < 20
            else None
        )
        yearly[str(year)] = {
            "first_test_signal": first.isoformat() if first is not None else None,
            "common_train_n": int(train.sum()),
            "feature_test_n": int(test.sum()),
            "latest_train_maturity": ends[train].max().isoformat() if train.any() else None,
            "reason": reason,
            "reuse": {},
        }
        reasons.loc[axis.year == year] = "INCOMPLETE_FEATURES"
        reasons.loc[test] = reason if reason else pd.NA
        if reason:
            continue
        known = test & np.isfinite(y)
        expected_days = set(axis[known])
        provided_days = {day for day in records if day.year == year}
        if expected_days != provided_days:
            raise ValueError("original mature OOS record rows differ from current14 common rows")
        yearly[str(year)]["common_training_dates"] = [day.isoformat() for day in axis[train]]
        baseline = float(y[train].mean())
        for day in axis[known]:
            record = records[day]
            if (
                float(record["target"]) != float(labels.loc[day, "return_4"])
                or float(record["baseline"]) != baseline
            ):
                raise ValueError("original target or mature shared training mean differs")
            scores.loc[day, "training_mean"] = record["baseline"]
            scores.loc[day, "original14_joint"] = record["prediction"]
        missing = test & ~known
        if missing.any():
            # Only unlabelled native tail extension, never silently repair an old score.
            if (
                year != 2026
                or not known.any()
                or not labels.loc[axis[missing], "return_4"].isna().all()
            ):
                raise ValueError("only unlabelled2026 tail prediction extension allowed")
            scores.loc[missing, "training_mean"] = records[axis[known][0]]["baseline"]
            scores.loc[missing, "original14_joint"] = score_model(
                "original14_joint", x[train], y[train], x[missing]
            )
        scores.loc[test, "confirmation_only"] = score_model(
            "confirmation_only", x[train], y[train], x[test]
        )
        yearly[str(year)]["reuse"] = {
            "matured_mean_joint_reused_n": int(known.sum()),
            "new_confirmation_predictions_n": int(test.sum()),
            "mean_tail_from_existing_baseline_n": int(missing.sum()),
            "joint_tail_coefficient_reconstruction_n": int(missing.sum()),
            "new_mean_joint_models": 0,
        }
    if any(not np.isfinite(scores.loc[day, "original14_joint"]) for day in records):
        raise ValueError("prior record supplied for unavailable yearly forecast")
    return scores, reasons, yearly


def group(y, prediction, eligible, selected):
    forecast = eligible & np.isfinite(prediction)
    selected_forecast = forecast & selected
    valid = selected_forecast & np.isfinite(y)
    n = int(valid.sum())
    gains = np.sort(y[valid & (y > 0)])[::-1]
    return {
        "forecast_eligible_n": int(forecast.sum()),
        "forecast_selected_n": int(selected_forecast.sum()),
        "forecast_coverage": float(selected_forecast.sum() / forecast.sum())
        if forecast.any()
        else None,
        "evaluation_n": n,
        "truth_missing_n": int((selected_forecast & ~np.isfinite(y)).sum()),
        "true_net_mean": float(y[valid].mean()) if n >= 20 else None,
        "positive_truth_n": int((valid & (y > 0)).sum()),
        "positive_truth_rate": float((y[valid] > 0).mean()) if n >= 20 else None,
        "nonpositive_truth_n": int((valid & (y <= 0)).sum()),
        "nonpositive_truth_rate": float((y[valid] <= 0).mean()) if n >= 20 else None,
        "zero_score_n": int((selected_forecast & (prediction == 0)).sum()),
        "strict_negative_score_n": int((selected_forecast & (prediction < 0)).sum()),
        "positive_proxy_gain_concentration": float(
            gains[: int(np.ceil(0.1 * len(gains)))].sum() / gains.sum()
        )
        if len(gains)
        else None,
        "reason": None if n >= 20 else "INSUFFICIENT_EVALUATION_SAMPLE",
    }


def quantities(y, scores, row):
    finite = np.isfinite(y[row]) & np.isfinite(scores[row]).all(axis=1)
    values = y[row][finite]
    predictions = scores[row][finite]
    overall = float(values.mean()) if len(values) >= 20 else None
    means, counts = {}, {}
    for i, model in enumerate(MODELS):
        selected = values[predictions[:, i] > 0]
        counts[model] = len(selected)
        means[model] = float(selected.mean()) if len(selected) >= 20 else None
    result = {}
    for model in MODELS:
        result[model + "_positive_mean"] = means[model]
        result[model + "_positive_minus_all"] = (
            means[model] - overall if means[model] is not None and overall is not None else None
        )
    for other, key in (
        ("confirmation_only", "joint_minus_confirmation_positive"),
        ("training_mean", "joint_minus_training_mean_positive"),
    ):
        result[key] = (
            means["original14_joint"] - means[other]
            if means["original14_joint"] is not None and means[other] is not None
            else None
        )
    return result, {"all": len(values), **counts}


def paired_bootstrap(y, scores):
    old = legacy()
    original, original_n = quantities(y, scores, np.arange(len(y)))
    samples = old._bootstrap_indices(len(y))
    records = []
    for replicate in range(500):
        vals, ns = (
            quantities(y, scores, samples[replicate])
            if samples is not None
            else ({key: None for key in original}, {})
        )
        records.append(
            {
                "replicate": replicate,
                "n": ns,
                "values": vals,
                "status": {
                    key: "VALID" if val is not None else "INSUFFICIENT_REQUIRED_GROUP"
                    for key, val in vals.items()
                },
            }
        )
    summary = {}
    for key, value in original.items():
        valid = [record["values"][key] for record in records if record["values"][key] is not None]
        ok = value is not None and len(valid) >= 400
        summary[key] = {
            "original": value,
            "valid_replicates": len(valid),
            "ci95": np.quantile(valid, [0.025, 0.975], method="linear").tolist() if ok else None,
            "reason": None
            if ok
            else "INSUFFICIENT_ORIGINAL_GROUP"
            if value is None
            else "INSUFFICIENT_VALID_REPLICATES",
        }
    return {
        "original_n": original_n,
        "summary": summary,
        "records": records,
        "requested_replicates": 500,
        "shared_full_axis_sampling": True,
        "refitted_models": 0,
    }


def analyze(features, labels, aux_mask, prior14_records):
    features, labels, aux_mask = inputs.validate(features, labels, aux_mask)
    scores, reasons, yearly = forecasts(features, labels, prior14_records)
    axis, y = features.index, labels.return_4.to_numpy(float)
    pred = scores.to_numpy(float)
    common = np.isfinite(y) & np.isfinite(pred).all(axis=1)
    quality = {}
    for model in MODELS:
        metrics = legacy()._prediction_metrics(
            y[common], scores[model].to_numpy()[common], scores.training_mean.to_numpy()[common]
        )
        quality[model] = metrics
    masks = {
        "all": np.ones(len(axis), bool),
        **{"year_" + str(year): axis.year == year for year in range(2020, 2027)},
        **{"phase_" + str(phase): np.arange(len(axis)) % 5 == phase for phase in range(5)},
        "original_policy_flat_confirmation_opportunity": aux_mask.to_numpy(bool),
    }
    panels = {}
    for name, mask in masks.items():
        panels[name] = {}
        for model in MODELS:
            p = scores[model].to_numpy(float)
            panels[name][model] = {
                "all": group(y, p, mask, np.ones(len(axis), bool)),
                "positive": group(y, p, mask, p > 0),
                "nonpositive": group(y, p, mask, p <= 0),
            }
            positive = panels[name][model]["positive"]
            positive["false_positive_n"] = positive["nonpositive_truth_n"]
            positive["false_positive_rate_among_positive_predictions"] = positive[
                "nonpositive_truth_rate"
            ]
    records = []
    for i, day in enumerate(axis):
        record = {
            "signal_date": day.isoformat(),
            "original_axis_phase5": i % 5,
            "target": float(y[i]) if np.isfinite(y[i]) else None,
            "label_end": labels.label_end_return_4.iloc[i].isoformat()
            if pd.notna(labels.label_end_return_4.iloc[i])
            else None,
            "truth_missing": not bool(np.isfinite(y[i])),
            "feature_complete": bool(np.isfinite(features.iloc[i].to_numpy()).all()),
            "forecast_unavailable_reason": str(reasons.iloc[i])
            if pd.notna(reasons.iloc[i])
            else None,
            "confirmation_opportunity": bool(aux_mask.iloc[i]),
            "scores": {
                model: float(scores[model].iloc[i]) if np.isfinite(scores[model].iloc[i]) else None
                for model in MODELS
            },
        }
        records.append(record)
    return {
        "method": METHOD,
        "method_sha256": sha256(
            json.dumps(METHOD, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "signal_n": len(axis),
        "forecasts": records,
        "fit_years": yearly,
        "quality": quality,
        "panels": panels,
        "paired_mean_bootstrap": paired_bootstrap(y, pred),
        "accounts": 0,
        "scientific_judgment": "NOT_PREJUDGED",
        "old_baseline_MSE_is_not_new_evidence": True,
    }
