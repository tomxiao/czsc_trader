import json
from pathlib import Path
from hashlib import sha256
import numpy as np
import pandas as pd

b = Path("research/S014/experiments/EX036_20261019")
p = pd.read_csv(b / "others/event_panel.csv").sort_values("decision_date").reset_index(drop=True)
s = json.loads((b / "others/statistics.json").read_bytes())
design = json.loads((b / "protocols/design.json").read_bytes())
pred = pd.read_csv(b / "others/model_predictions.csv")


def eq(x, y):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        assert y is None or pd.isna(y), (x, y)
    else:
        assert np.isclose(x, y, rtol=1e-10, atol=1e-11), (x, y)


for binding in s["input_bindings"]:
    assert sha256(Path(binding["path"]).read_bytes()).hexdigest() == binding["sha256"]
blocks = []
ends = p[["price_end_date", "planned_exit_date", "actual_exit_date"]].fillna("").max(axis=1)
for i, r in p.iterrows():
    if not blocks or r.entry_date > blocks[-1]["end"]:
        blocks.append(dict(start=r.entry_date, end=ends[i], indices=[i]))
    else:
        blocks[-1]["end"] = max(blocks[-1]["end"], ends[i])
        blocks[-1]["indices"].append(i)
    p.loc[i, "block"] = len(blocks) - 1
assert len(blocks) == len(s["dependency_blocks"]) == 21
for x, y in zip(blocks, s["dependency_blocks"], strict=True):
    assert x["indices"] == y["indices"] and x["start"] == y["start"] and x["end"] == y["end"]
p["block"] = p.block.astype(int)
draw = np.random.default_rng(13).integers(0, len(blocks), (10000, len(blocks)))
weights = np.array([np.bincount(d, minlength=len(blocks)) for d in draw])
effects = []
for c in s["contrasts"]:
    spec = next(x for x in design["primary_contrasts"] if x["id"] == c["id"])
    pop = p[p.F1.eq(1)] if spec.get("population") == "F1-positive" else p
    left = pop[pop[spec.get("flag", "F1")].eq(1)]
    right = pop[pop.PARENT.eq(1)] if c["id"] == "F1_VS_PARENT" else pop[pop[spec["flag"]].eq(0)]
    target = spec["target"]
    means = []
    bootmeans = []
    bootblocks = []
    for arm, name in [(left, "first"), (right, "second")]:
        reported = c["point"][name]
        assert reported["event_ids"] == arm.event_id.tolist()
        assert reported["events"] == len(arm)
        eq(arm[target].mean(), reported["event_weighted_mean"])
        bm = arm.groupby("block")[target].mean().reindex(range(len(blocks)))
        eq(bm.mean(), reported["block_equal_mean"])
        assert bm.notna().sum() == reported["blocks_present"]
        means.append(arm[target].mean())
        evw = weights[:, arm.block.to_numpy()]
        with np.errstate(invalid="ignore", divide="ignore"):
            bootmeans.append((evw @ arm[target].to_numpy()) / evw.sum(axis=1))
            bootblocks.append(
                (weights @ bm.fillna(0).to_numpy()) / (weights @ bm.notna().to_numpy())
            )
    eq(means[0] - means[1], c["point"]["event_weighted_difference"])
    eq(
        left.groupby("block")[target].mean().mean() - right.groupby("block")[target].mean().mean(),
        c["point"]["block_equal_difference"],
    )
    for method, m in [("event_weighted", bootmeans), ("block_equal", bootblocks)]:
        dif = m[0] - m[1]
        v = dif[np.isfinite(dif)]
        rep = c["bootstrap"][method]
        assert len(v) == rep["valid_resamples"]
        assert 10000 - len(v) == rep["invalid_missing_group_resamples"]
        np.testing.assert_allclose(
            np.quantile(v, [0.025, 0.975]), rep["percentile95"], rtol=1e-10, atol=1e-11
        )
        # Shared-arm resamples can be exactly tied mathematically; summation
        # order may change machine-epsilon signs without changing intervals.
        assert (
            abs((v > 0).mean() - rep["bootstrap_positive_fraction_descriptive"])
            <= np.mean(abs(v) < 1e-12) + 1e-12
        )

    def check_subset(result, keep):
        for arm, name in [(left, "first"), (right, "second")]:
            chosen = arm.loc[arm.index.intersection(keep)]
            eq(chosen[target].mean(), result[name]["event_weighted_mean"])
            eq(chosen.groupby("block")[target].mean().mean(), result[name]["block_equal_mean"])

    for result in c["influence"]["leave_one_dependency_block_out"]:
        omitted = int(result["omitted_block"][1:]) - 1
        check_subset(result, p.index[p.block.ne(omitted)])
    ranked = (
        pop.sort_values([target, "decision_date"])
        if False
        else sorted(
            pop.index,
            key=lambda i: (-abs(p.loc[i, target]), p.loc[i, "decision_date"], p.loc[i, "event_id"]),
        )
    )
    for count, result in zip([1, 3], c["influence"]["remove_top_absolute_target"], strict=True):
        assert result["removed_event_ids"] == p.loc[ranked[:count], "event_id"].tolist()
        check_subset(result, p.index.difference(ranked[:count]))
    for result in c["influence"]["by_decision_year"]:
        check_subset(result, p.index[p.decision_date.str[:4].astype(int).eq(result["year"])])
    result = c["influence"]["exclude_2026_complete_endpoint_only"]
    keep = p.index[(p.decision_date <= "2025-12-31") & (ends <= "2025-12-31")]
    assert (
        result["retained_event_ids"] == pop.loc[pop.index.intersection(keep), "event_id"].tolist()
    )
    check_subset(result, keep)
    effects.append(
        {
            "id": c["id"],
            "first_n": len(left),
            "second_n": len(right),
            "difference": means[0] - means[1],
        }
    )

specs = {x["id"]: x for x in design["fixed_models"]["models"]}
indexed = p.set_index("event_id", drop=False)


def certify(rep, ids, model):
    spec = specs[model]
    train = indexed.loc[ids]
    features = spec["x"]
    x = train[features].to_numpy(float)
    y = train[spec["target"]].to_numpy(float)
    means = np.array(
        [
            x[:, j].mean() if f in ["stock_trailing20", "sector_trailing20"] else 0
            for j, f in enumerate(features)
        ]
    )
    std = np.array(
        [
            x[:, j].std(ddof=0) if f in ["stock_trailing20", "sector_trailing20"] else 1
            for j, f in enumerate(features)
        ]
    )
    np.testing.assert_allclose(means, list(rep["feature_mean"].values()), atol=1e-13)
    np.testing.assert_allclose(std, list(rep["feature_std_ddof0"].values()), atol=1e-13)
    X = np.column_stack([np.ones(len(train)), (x - means) / std])
    coef = np.array([rep["standardized_coefficients"][f] for f in ["intercept", *features]])
    assert np.linalg.matrix_rank(X) == X.shape[1] == rep["rank"]
    # Full rank plus normal-equation residual certifies unique OLS optimum;
    # no additional model fits or parameter search are executed by this audit.
    assert np.max(np.abs(X.T @ (y - X @ coef))) < 1e-10
    raw = coef[1:] / std
    expected = np.r_[coef[0] - raw @ means, raw]
    np.testing.assert_allclose(
        expected,
        [rep["raw_unit_coefficients"][f] for f in ["intercept", *features]],
        rtol=1e-10,
        atol=1e-11,
    )
    assert len(train) == rep["training_events"]
    return coef, means, std


for full in s["models"]["full_sample_descriptive_models"]:
    assert full["common_family_training_event_ids"] == p.event_id.tolist()
    certify(full, full["common_family_training_event_ids"], full["model_id"])
walks = {(f["model_id"], f["test_event_id"]): f for f in s["models"]["walk_forward_fits"]}
for r in pred.to_dict("records"):
    ids = json.loads(r["training_event_ids"])
    expected = p.loc[
        (ends < r["decision_date"]) & (p.decision_date < r["decision_date"]), "event_id"
    ].tolist()
    assert ids == expected and len(ids) == r["training_events"]
    maxend = ends.loc[p.event_id.isin(ids)].max() if ids else None
    assert (pd.isna(r["max_training_label_end"]) and maxend is None) or r[
        "max_training_label_end"
    ] == maxend
    if len(ids) < 12:
        assert r["status"] == "UNAVAILABLE_MINIMUM_12_TRAINING_EVENTS" and pd.isna(r["prediction"])
        continue
    rep = walks[r["model_id"], r["event_id"]]
    coef, mean, std = certify(rep, ids, r["model_id"])
    spec = specs[r["model_id"]]
    x = indexed.loc[r["event_id"], spec["x"]].to_numpy(float)
    eq(np.r_[1, (x - mean) / std] @ coef, r["prediction"])
    eq(indexed.loc[r["event_id"], spec["target"]], r["observed"])
assert (
    s["models"]["attempted_fits"]
    == s["models"]["actual_successful_fits"]
    == len(walks) + len(specs)
    == 70
)
assert len(pred) == 125 and len(walks) == 65
for pair in s["models"]["paired_identical_test_set_metrics"]:
    chosen = pred[pred.event_id.isin(pair["same_test_event_ids"])]
    for model, key in [
        (pair["baseline"], "baseline_metrics"),
        (pair["alternative"], "alternative_metrics"),
    ]:
        sub = chosen[chosen.model_id.eq(model)]
        err = sub.prediction - sub.observed
        assert len(sub) == pair[key]["events"]
        eq(err.abs().mean(), pair[key]["mae"])
        eq(np.sqrt(np.mean(err**2)), pair[key]["rmse"])
    a = chosen[chosen.model_id.eq(pair["baseline"])].set_index("event_id")
    z = chosen[chosen.model_id.eq(pair["alternative"])].set_index("event_id")
    for event in a.index:
        assert a.loc[event, "training_event_ids"] == z.loc[event, "training_event_ids"]
print(
    json.dumps(
        {
            "contrasts": effects,
            "dependency_blocks": len(blocks),
            "bootstrap_recomputed_per_contrast": 10000,
            "OLS_optimality_certificates": 70,
            "new_model_fits_in_audit": 0,
            "forward_predictions": 65,
            "immature_unavailable_predictions": 60,
            "paired_test_events": 13,
            "all_numeric_and_causal_checks": "PASS",
            "new_API_calls": 0,
        }
    )
)
