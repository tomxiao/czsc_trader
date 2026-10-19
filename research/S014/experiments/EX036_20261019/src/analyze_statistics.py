"""Fixed EX036 block-resampled contrasts and strictly forward OLS diagnostics.

No market/financial acquisition, feature search, tuning, or strategy accounts.
Execution requires published design plus the completed event panel. Existing
result files are protected against accidental replacement.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
from collections import Counter
from datetime import date
from pathlib import Path

for _key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

import numpy as np  # noqa: E402 -- Set native thread limits before NumPy loads.

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[3]
TARGETS = [
    "sector_excess_return20",
    "market_excess_return20",
    "return20",
    "mae20",
    "net_position_return",
]
CONTINUOUS = {"stock_trailing20", "sector_trailing20"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def num(value):
    if value is None or str(value).strip().lower() in {"", "none", "null", "nan", "nat"}:
        return float("nan")
    if str(value).strip().lower() == "true":
        return 1.0
    if str(value).strip().lower() == "false":
        return 0.0
    return float(value)


def day(value):
    value = str(value or "").strip()
    if not value or value.lower() in {"none", "null", "nan", "nat"}:
        return None
    if len(value) >= 10 and value[4] == "-":
        return date.fromisoformat(value[:10])
    if len(value) == 8 and value.isdigit():
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    raise ValueError(f"Unrecognized date: {value!r}")


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_blocks(rows, cutoff):
    spans = []
    for i, row in enumerate(rows):
        start = day(row["entry_date"])
        endpoints = [
            day(row.get(k)) for k in ("price_end_date", "planned_exit_date", "actual_exit_date")
        ]
        if row.get("execution_status") == "OPEN_PENDING":
            endpoints.append(cutoff)
        present = [x for x in endpoints if x is not None]
        if start is None or not present:
            raise ValueError(f"Missing dependency interval: {row['event_id']}")
        end = max(present)
        if end < start:
            raise ValueError(f"Reversed interval: {row['event_id']}")
        row["_interval_end"] = end
        spans.append((start, end, i))
    blocks = []
    for start, end, index in sorted(spans):
        if not blocks or start > blocks[-1]["end"]:
            blocks.append(
                {"id": f"B{len(blocks) + 1:02d}", "start": start, "end": end, "indices": [index]}
            )
        else:
            blocks[-1]["end"] = max(blocks[-1]["end"], end)
            blocks[-1]["indices"].append(index)
        rows[index]["_block"] = len(blocks) - 1
    return blocks


def contrast_population(rows, spec):
    ids, first, second, missing = [], [], [], []
    for i, row in enumerate(rows):
        reason = None
        if spec.get("population") == "F1-positive":
            if not math.isfinite(row["F1"]):
                reason = "F1_UNAVAILABLE"
            elif row["F1"] != 1:
                reason = "OUTSIDE_F1_POSITIVE_POPULATION"
        if reason is None and not math.isfinite(row[spec["target"]]):
            reason = "TARGET_UNAVAILABLE"
        if spec["id"] == "F1_VS_PARENT":
            if reason is None and not all(math.isfinite(row[f]) for f in ("F1", "PARENT")):
                reason = "SELECTION_UNAVAILABLE"
            left, right = row["F1"] == 1, row["PARENT"] == 1
        else:
            flag = spec["flag"]
            if reason is None and not math.isfinite(row[flag]):
                reason = "FLAG_UNAVAILABLE"
            left, right = row[flag] == 1, row[flag] == 0
        if reason:
            missing.append({"event_id": row["event_id"], "reason": reason})
        else:
            ids.append(i)
            first.append(left)
            second.append(right)
    return (
        np.array(ids, dtype=int),
        np.array(first, dtype=bool),
        np.array(second, dtype=bool),
        missing,
    )


def estimate(rows, ids, first, second, target, nblocks):
    values = np.array([rows[i][target] for i in ids], dtype=float)
    blocks = np.array([rows[i]["_block"] for i in ids], dtype=int)
    arm_results = []
    for mask in (first, second):
        block_sum = np.bincount(blocks[mask], weights=values[mask], minlength=nblocks)
        block_count = np.bincount(blocks[mask], minlength=nblocks)
        nonempty = block_count > 0
        block_mean = np.divide(block_sum, block_count, out=np.full(nblocks, np.nan), where=nonempty)
        arm_results.append(
            {
                "events": int(mask.sum()),
                "event_ids": [rows[i]["event_id"] for i in ids[mask]],
                "blocks_present": int(nonempty.sum()),
                "event_weighted_mean": float(values[mask].mean()) if mask.any() else float("nan"),
                "block_equal_mean": float(block_mean[nonempty].mean())
                if nonempty.any()
                else float("nan"),
                "block_sum": block_sum,
                "block_count": block_count,
                "block_mean": block_mean,
            }
        )
    a, b = arm_results
    return {
        "eligible_events": len(ids),
        "overlap_events": int((first & second).sum()),
        "neither_selected_events": int((~first & ~second).sum()),
        "first": {
            k: v for k, v in a.items() if k not in {"block_sum", "block_count", "block_mean"}
        },
        "second": {
            k: v for k, v in b.items() if k not in {"block_sum", "block_count", "block_mean"}
        },
        "event_weighted_difference": a["event_weighted_mean"] - b["event_weighted_mean"],
        "block_equal_difference": a["block_equal_mean"] - b["block_equal_mean"],
    }, arm_results


def bootstrap(arms, draws):
    output = {}
    contributing = int(np.count_nonzero(arms[0]["block_count"] + arms[1]["block_count"]))
    arm_contributing = [int(np.count_nonzero(arm["block_count"])) for arm in arms]
    interval_eligible = min(arm_contributing) >= 2
    for method in ("event_weighted", "block_equal"):
        means = []
        for arm in arms:
            if method == "event_weighted":
                totals = arm["block_sum"][draws].sum(axis=1)
                weights = arm["block_count"][draws].sum(axis=1)
            else:
                cells = arm["block_mean"][draws]
                totals = np.nansum(cells, axis=1)
                weights = np.isfinite(cells).sum(axis=1)
            means.append(
                np.divide(totals, weights, out=np.full(len(draws), np.nan), where=weights > 0)
            )
        differences = means[0] - means[1]
        valid = np.isfinite(differences)
        output[method] = {
            "valid_resamples": int(valid.sum()),
            "invalid_missing_group_resamples": int((~valid).sum()),
            "contributing_dependency_blocks": contributing,
            "arm_contributing_dependency_blocks": arm_contributing,
            "status": "AVAILABLE_DESCRIPTIVE"
            if valid.any() and interval_eligible
            else "UNAVAILABLE_ARM_FEWER_THAN_TWO_BLOCKS"
            if not interval_eligible
            else "UNAVAILABLE_NO_VALID_RESAMPLES",
            "percentile95": np.quantile(differences[valid], [0.025, 0.975]).tolist()
            if valid.any() and interval_eligible
            else None,
            "bootstrap_positive_fraction_descriptive": float((differences[valid] > 0).mean())
            if valid.any() and interval_eligible
            else None,
        }
    return output


def one_contrast(payload):
    rows, spec, nblocks, resamples, seed = payload
    ids, first, second, excluded = contrast_population(rows, spec)
    point, arms = estimate(rows, ids, first, second, spec["target"], nblocks)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, nblocks, size=(resamples, nblocks))
    influences = {}

    def subset(keep):
        result, _ = estimate(rows, ids[keep], first[keep], second[keep], spec["target"], nblocks)
        return result

    block_ids = np.array([rows[i]["_block"] for i in ids])
    influences["leave_one_dependency_block_out"] = [
        {"omitted_block": f"B{b + 1:02d}", **subset(block_ids != b)} for b in range(nblocks)
    ]
    ranked = sorted(
        range(len(ids)),
        key=lambda j: (
            -abs(rows[int(ids[j])][spec["target"]]),
            day(rows[int(ids[j])]["decision_date"]),
            rows[int(ids[j])]["event_id"],
        ),
    )
    influences["remove_top_absolute_target"] = []
    for count in (1, 3):
        removed = ranked[:count]
        keep = np.array([i not in removed for i in range(len(ids))], dtype=bool)
        influences["remove_top_absolute_target"].append(
            {
                "removed_event_ids": [rows[int(ids[j])]["event_id"] for j in removed],
                "ranking_population": "all eligible contrast events, including neither-selected events",
                **subset(keep),
            }
        )
    years = np.array([day(rows[i]["decision_date"]).year for i in ids])
    influences["by_decision_year"] = [
        {"year": int(year), **subset(years == year)} for year in sorted(set(years))
    ]
    cutoff = date(2025, 12, 31)
    keep = np.array(
        [
            day(rows[i]["decision_date"]) <= cutoff
            and rows[i]["_interval_end"] <= cutoff
            and rows[i].get("_actual_exit_known_or_not_entered", False)
            for i in ids
        ],
        dtype=bool,
    )
    influences["exclude_2026_complete_endpoint_only"] = {
        "retained_event_ids": [rows[i]["event_id"] for i in ids[keep]],
        **subset(keep),
    }
    descriptive = {}
    for target in TARGETS:
        valid = np.array([math.isfinite(rows[i][target]) for i in ids])
        descriptive[target] = (
            subset(valid)
            if target == spec["target"]
            else estimate(rows, ids[valid], first[valid], second[valid], target, nblocks)[0]
        )
    return {
        "id": spec["id"],
        "target": spec["target"],
        "declared_direction": spec["direction"],
        "point": point,
        "excluded_events": excluded,
        "bootstrap": bootstrap(arms, draws),
        "influence": influences,
        "fixed_group_descriptive_targets_no_extra_bootstrap": descriptive,
    }


def fit_ols(rows, indices, spec):
    features = spec["x"]
    x = np.array([[rows[i][f] for f in features] for i in indices], dtype=float)
    y = np.array([rows[i][spec["target"]] for i in indices], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        return {"status": "UNAVAILABLE_NONFINITE_TRAINING"}, None
    means = np.zeros(len(features))
    scales = np.ones(len(features))
    for j, feature in enumerate(features):
        if feature in CONTINUOUS:
            means[j] = x[:, j].mean()
            scales[j] = x[:, j].std(ddof=0)
            if scales[j] == 0:
                return {
                    "status": "UNAVAILABLE_CONSTANT_CONTINUOUS_FEATURE",
                    "feature": feature,
                }, None
    standardized = (x - means) / scales
    design = np.column_stack((np.ones(len(indices)), standardized))
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        return {
            "status": "UNAVAILABLE_RANK_DEFICIENT",
            "rank": rank,
            "columns": design.shape[1],
        }, None
    coef, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    if not np.isfinite(coef).all():
        return {"status": "UNAVAILABLE_NONFINITE_COEFFICIENTS"}, None
    raw = coef[1:] / scales
    raw_intercept = coef[0] - float(raw @ means)
    result = {
        "status": "FIT",
        "training_events": len(indices),
        "rank": rank,
        "feature_mean": dict(zip(features, means.tolist(), strict=True)),
        "feature_std_ddof0": dict(zip(features, scales.tolist(), strict=True)),
        "standardized_coefficients": dict(
            zip(["intercept", *features], coef.tolist(), strict=True)
        ),
        "raw_unit_coefficients": dict(
            zip(["intercept", *features], [raw_intercept, *raw.tolist()], strict=True)
        ),
    }
    return result, (coef, means, scales)


def models(rows, design):
    specs = design["fixed_models"]["models"]
    predictions = []
    full = []
    walks = []
    attempts = successes = 0
    failure_counts = Counter()
    families = {
        "RETURN": {
            "target": "sector_excess_return20",
            "features": ["stock_trailing20", "sector_trailing20", "F1", "PARENT"],
        },
        "RISK": {"target": "mae20", "features": ["stock_trailing20", "sector_trailing20", "F2"]},
    }
    for spec in specs:
        family = families[spec["id"].split("_")[0]]
        family_fields = [*family["features"], family["target"]]
        complete_indices = [
            i
            for i, row in enumerate(rows)
            if all(math.isfinite(row[f]) for f in family_fields)
            and row.get("price_label_status") == "COMPLETE"
            and row["_actual_exit_known_or_not_entered"]
        ]
        attempts += 1
        if len(complete_indices) < 12:
            fitted = {"status": "UNAVAILABLE_MINIMUM_12_COMPLETE_TRAINING_EVENTS"}
        else:
            fitted, _ = fit_ols(rows, complete_indices, spec)
        fitted.update({"model_id": spec["id"], "target": spec["target"]})
        fitted["common_family_training_event_ids"] = [rows[i]["event_id"] for i in complete_indices]
        fitted["excluded_incomplete_family_event_ids"] = [
            rows[i]["event_id"] for i in range(len(rows)) if i not in complete_indices
        ]
        full.append(fitted)
        if fitted["status"] == "FIT":
            successes += 1
        else:
            failure_counts[fitted["status"]] += 1
        for i, row in enumerate(rows):
            decision = day(row["decision_date"])
            train = [
                j
                for j in complete_indices
                if rows[j]["_interval_end"] < decision and day(rows[j]["decision_date"]) < decision
            ]
            pred = {
                "model_id": spec["id"],
                "event_id": row["event_id"],
                "decision_date": row["decision_date"],
                "target": spec["target"],
                "observed": row[spec["target"]],
                "prediction": None,
                "training_events": len(train),
                "max_training_label_end": max(
                    (rows[j]["_interval_end"] for j in train), default=None
                ),
                "training_event_ids": [rows[j]["event_id"] for j in train],
            }
            if len(train) < 12:
                pred["status"] = "UNAVAILABLE_MINIMUM_12_TRAINING_EVENTS"
            elif (
                not all(math.isfinite(row[f]) for f in family_fields)
                or row.get("price_label_status") != "COMPLETE"
            ):
                pred["status"] = "UNAVAILABLE_NONFINITE_TEST"
            else:
                attempts += 1
                fitted, parameters = fit_ols(rows, train, spec)
                pred["status"] = fitted["status"]
                if parameters is None:
                    failure_counts[fitted["status"]] += 1
                else:
                    successes += 1
                    coef, means, scales = parameters
                    test = (np.array([row[f] for f in spec["x"]]) - means) / scales
                    pred["prediction"] = float(np.r_[1.0, test] @ coef)
                walks.append({"model_id": spec["id"], "test_event_id": row["event_id"], **fitted})
            predictions.append(pred)
    assert attempts <= design["fixed_models"]["max_fits"], attempts

    def metric(items):
        if not items:
            return {"events": 0, "mae": None, "rmse": None}
        errors = np.array([item["prediction"] - item["observed"] for item in items])
        return {
            "events": len(items),
            "event_ids": [item["event_id"] for item in items],
            "mae": float(abs(errors).mean()),
            "rmse": float(np.sqrt((errors**2).mean())),
        }

    model_metrics = {
        spec["id"]: metric(
            [p for p in predictions if p["model_id"] == spec["id"] and p["prediction"] is not None]
        )
        for spec in specs
    }
    paired = []
    for baseline, alternative in [
        ("RETURN_BASE", "RETURN_F1"),
        ("RETURN_BASE", "RETURN_PARENT"),
        ("RETURN_F1", "RETURN_PARENT"),
        ("RISK_BASE", "RISK_F2"),
    ]:
        a = {
            p["event_id"]: p
            for p in predictions
            if p["model_id"] == baseline and p["prediction"] is not None
        }
        b = {
            p["event_id"]: p
            for p in predictions
            if p["model_id"] == alternative and p["prediction"] is not None
        }
        common = sorted(a.keys() & b.keys())
        ma, mb = metric([a[k] for k in common]), metric([b[k] for k in common])
        paired.append(
            {
                "baseline": baseline,
                "alternative": alternative,
                "same_test_event_ids": common,
                "baseline_metrics": ma,
                "alternative_metrics": mb,
                "mae_alternative_minus_baseline": mb["mae"] - ma["mae"] if common else None,
                "rmse_alternative_minus_baseline": mb["rmse"] - ma["rmse"] if common else None,
            }
        )
    return {
        "attempted_fits": attempts,
        "actual_successful_fits": successes,
        "failed_fit_count": attempts - successes,
        "failed_fit_reasons": dict(failure_counts),
        "prediction_status_counts": dict(Counter(p["status"] for p in predictions)),
        "full_sample_descriptive_models": full,
        "walk_forward_fits": walks,
        "model_metrics": model_metrics,
        "paired_identical_test_set_metrics": paired,
        "training_complete_case_policy": "Shared complete target and union-of-features population within RETURN family and RISK family; shared maturation endpoint, report excluded IDs, no incomplete row imputation",
        "training_endpoint_rule": "max(price_end_date,planned_exit_date,actual_exit_date) strictly before decision; OPEN_PENDING uses cutoff and remains incomplete; NO_TRADE price labels use planned endpoint",
        "small_OLS_execution": "Five fixed tiny models run sequentially in parent process; process overhead exceeds 25-row solves; bootstrap comparisons run with two spawn processes",
        "independence": "All history previously seen; forward ordering is a leakage-control diagnostic, not a new unseen holdout",
    }, predictions


def main():
    protocol = BASE / "protocols/design.json"
    published = BASE / "protocols/published_design.json"
    panel = BASE / "others/event_panel.csv"
    out = BASE / "others/statistics.json"
    pred_out = BASE / "others/model_predictions.csv"
    if not published.exists() or not panel.exists():
        raise RuntimeError(
            "Published design and completed event panel both required before computing outcomes"
        )
    if out.exists() or pred_out.exists():
        raise FileExistsError(
            "Protected results exist; preserve them and explicitly choose a new revision before rerunning"
        )
    design = json.loads(protocol.read_text(encoding="utf-8"))
    published_refs = json.loads(published.read_text(encoding="utf-8"))
    assert published_refs[relative(protocol)]["sha256"] == digest(protocol), (
        "Design differs from published evidence identity"
    )
    with panel.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len({r["event_id"] for r in rows}) == len(rows)
    assert len({r["decision_date"] for r in rows}) == len(rows)
    rows.sort(key=lambda row: (day(row["decision_date"]), row["event_id"]))
    for row in rows:
        for feature in ["F1", "F2", "PARENT", "stock_trailing20", "sector_trailing20", *TARGETS]:
            row[feature] = num(row.get(feature))
        for flag in ("F1", "F2", "PARENT"):
            if math.isfinite(row[flag]) and row[flag] not in {0, 1}:
                raise ValueError(f"Invalid binary flag {flag} for {row['event_id']}")
        row["_actual_exit_known_or_not_entered"] = (
            day(row.get("actual_exit_date")) is not None
            or row.get("execution_status") == "NO_TRADE"
        )
    blocks = build_blocks(rows, day(design["window"][1]))
    specs = design["primary_contrasts"]
    assert len(specs) == 4
    payloads = [
        (
            rows,
            spec,
            len(blocks),
            design["inference"]["bootstrap_resamples"],
            design["resources"]["seed"],
        )
        for spec in specs
    ]
    with mp.get_context("spawn").Pool(processes=2) as pool:
        contrasts = pool.map(one_contrast, payloads)
    model_results, predictions = models(rows, design)
    result = {
        "identity": design["identity"],
        "status": "FIXED_STAGE_TWO_DESCRIPTIVE_STATISTICS",
        "input_bindings": [
            {"path": relative(p), "sha256": digest(p)}
            for p in (protocol, published, panel, Path(__file__))
        ],
        "events": len(rows),
        "dependency_blocks": [
            {**b, "event_ids": [rows[i]["event_id"] for i in b["indices"]]} for b in blocks
        ],
        "block_rule": "Transitive closure of overlapping inclusive entry..max(price_end,planned_exit,actual_exit) intervals across all events; original block identity retained in influence subsets",
        "block_equal_rule": "For each arm, compute each present block's within-arm mean and then mean across present blocks; empty arm-blocks missing, never zero. Entire resample missing either arm is invalid.",
        "implementation_notes": "Conservative fixed interpretation confirmed before results: each arm needs at least two contributing dependency blocks for a descriptive 95% CI. Raw group means/effects remain descriptive; this is not an economic gate.",
        "resampling": {
            "workers": 2,
            "start_method": "spawn",
            "native_threads_per_worker": 1,
            "seed_per_contrast": 13,
            "draws": 10000,
            "common_block_draws_across_contrasts": True,
            "inference": "Descriptive percentile intervals; no additional economic acceptance threshold",
        },
        "contrasts": contrasts,
        "models": model_results,
        "limitations": [
            "Twenty-day price excursion includes full entry-session lows, not certified post-fill intraday path",
            "Event position labels are isolated, not annual or continuous strategy returns",
            "Historical vendor arrival unknown; analysis conditions on public-original-reconciled schedule",
            "In-sample coefficients and forward diagnostics use previously seen history",
            "No-trade and missing execution values remain unavailable; no zero imputation",
        ],
    }
    # Exclusive create prevents accidental overwrite even if another process
    # produces a result after the initial guard.
    with pred_out.open("x", encoding="utf-8", newline="") as stream:
        fields = [
            "model_id",
            "event_id",
            "decision_date",
            "target",
            "observed",
            "prediction",
            "training_events",
            "max_training_label_end",
            "training_event_ids",
            "status",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for prediction in clean(predictions):
            prediction["training_event_ids"] = json.dumps(
                prediction["training_event_ids"], ensure_ascii=False
            )
            writer.writerow(prediction)
    result["model_predictions"] = {
        "path": relative(pred_out),
        "sha256": digest(pred_out),
        "rows": len(predictions),
    }
    with out.open("x", encoding="utf-8") as stream:
        json.dump(clean(result), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            clean(
                {
                    "events": len(rows),
                    "blocks": len(blocks),
                    "fits": model_results["actual_successful_fits"],
                    "failed_fits": model_results["failed_fit_count"],
                    "contrasts": [
                        {
                            "id": c["id"],
                            "difference": c["point"]["event_weighted_difference"],
                            "block_equal_difference": c["point"]["block_equal_difference"],
                            "ci": c["bootstrap"],
                        }
                        for c in contrasts
                    ],
                }
            ),
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
