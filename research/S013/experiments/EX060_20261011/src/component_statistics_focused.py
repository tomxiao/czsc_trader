"""Synthetic-only focused checks for fixed chronological component statistics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import component_statistics as s


def run() -> dict:
    checks = []
    refusals = []

    def checked(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def refused(name: str, call) -> None:
        try:
            call()
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError(name)

    rng = np.random.default_rng(7)
    index = pd.bdate_range("2020-01-02", "2023-03-31")
    n = len(index)
    cols = [*s.CONTROLS, *s.COMPONENTS]
    features = pd.DataFrame(rng.normal(size=(n, len(cols))), index=index, columns=cols)
    target = rng.normal(size=n)
    ends = pd.Series(index + pd.offsets.BDay(6), index=index)
    scope = np.ones(n, dtype=bool)
    train, test, start = s._year_train_mask(index, ends, scope, 2021)
    checked("year_2020_initial_training_only", bool((index[train].year == 2020).all()))
    checked("cross_year_unmatured_labels_excluded", bool((ends[train] < start).all()) and
            int(train.sum()) < int((index.year == 2020).sum()))
    boundary = ends.copy()
    boundary.loc[index[index.year == 2020][-1]] = start
    boundary_train, _, _ = s._year_train_mask(index, boundary, scope, 2021)
    checked("equal_boundary_label_strictly_excluded", not bool(boundary_train[index.get_loc(index[index.year == 2020][-1])]))
    checked("test_year_first_actual_signaldate", start == index[index.year == 2021][0] and
            bool((index[test].year == 2021).all()))
    values = s._cdf_apply(np.array([1., 2., 2., 4.]), np.array([-100., 2., 100.]))
    checked("test_extreme_ranks_use_training_cdf", bool(np.array_equal(values, [0., .5, 1.])))
    checked("train_tie_ranks_midpoint", bool(np.array_equal(s._cdf_apply(np.array([2., 2.]), np.array([2.])), [.5])))
    first = s._walk_forward(index, features, target, ends, scope)
    future_features = features.copy()
    future_features.loc[index.year >= 2022, :] = 1000 + rng.normal(size=(int((index.year >= 2022).sum()), len(cols)))
    future_target = target.copy()
    future_target[index.year >= 2022] = -2000.
    second = s._walk_forward(index, future_features, future_target, ends, scope)
    for name in first["prediction_records"]:
        before = [r for r in first["prediction_records"][name] if r["signaldate"].startswith("2021-")]
        after = [r for r in second["prediction_records"][name] if r["signaldate"].startswith("2021-")]
        checked(f"future_year_no_effect_{name}", bool(before) and before == after)
    checked("all_four_models_identical_test_rows", len({len(v) for v in first["prediction_records"].values()}) == 1)
    checked("constant_correlation_is_not_zero", s._ic(np.ones(40), np.arange(40))["value"] is None)
    checked("small_sample_correlation_is_not_zero", s._ic(np.arange(19), np.arange(19))["value"] is None)
    checked("control_explained_residual_is_not_zero", s._ic(np.arange(50), np.arange(50), np.arange(50)[:, None])["value"] is None)
    explained = rng.normal(size=(80, len(s.CONTROLS)))
    checked("one_control_explains_component_without_fake_partial_ic", s._ic(
        explained[:, 0], rng.normal(size=80), explained)["value"] is None)
    checked("short_bootstrap_unavailable", s._bootstrap_indices(39) is None)
    sampled = s._bootstrap_indices(80)
    checked("bootstrap_shape_and_determinism", sampled.shape == (500, 80) and np.array_equal(sampled, s._bootstrap_indices(80)))
    checked("bootstrap_contiguous_40_session_blocks", bool((np.diff(sampled[:, :40], axis=1) == 1).all()))
    checked("baseline_prediction_is_training_mean", all(
        abs(r["baseline"] - target[train].mean()) < 1e-14
        for r in first["prediction_records"]["controls"] if r["signaldate"].startswith("2021-")))
    constant = s._walk_forward(index, features, np.ones(n), ends, scope)
    checked("constant_train_target_does_not_fake_forecast", constant["yearly"]["2021"]["models"]["controls"]["mse"] is None)
    checked("missing_test_year_preserved", first["yearly"]["2026"]["models"]["controls"]["reason"] == "INSUFFICIENT_TRAIN_SAMPLE")

    # This full interface check is ten synthetic rows: all statistics explicitly unavailable.
    short_features = features.iloc[:10].copy()
    short_index = short_features.index
    labels = pd.DataFrame(index=short_index)
    for label, h in s.HORIZONS.items():
        labels[label] = np.arange(10, dtype=float) / 100 if label != "negative_gap_next" else np.arange(10) % 2
        labels[f"label_end_{label}"] = short_index + pd.offsets.BDay(h + 1)
    opportunity = pd.Series(np.arange(10) % 2 == 0, index=short_index)
    small = s.analyze(short_features, labels, opportunity)
    checked("all_labels_and_opportunity_results_retained", set(small["scopes"]) == {"all", "opportunity"} and
            set(small["scopes"]["all"]["labels"]) == set(s.HORIZONS))
    checked("small_full_interface_ic_explicit_none", all(
        item["spearman"]["value"] is None for entry in small["scopes"]["all"]["labels"].values()
        for item in entry["components"].values()))
    pcounts = small["scopes"]["opportunity"]["labels"]["return_3"]["components"][s.COMPONENTS[0]]["nonoverlap_phases"]
    checked("opportunity_phase_positions_not_reindexed", [pcounts[str(i)]["spearman"]["n"] for i in range(4)] == [3, 0, 2, 0])
    leak = short_features.copy()
    leak["return_3"] = 1.
    refused("future_label_in_feature_frame", lambda: s.analyze(leak, labels))
    bad_ends = labels.copy()
    bad_ends["label_end_return_3"] = short_index
    refused("non_future_maturity", lambda: s.analyze(short_features, bad_ends))
    missing_end = labels.copy()
    missing_end.loc[short_index[0], "label_end_return_3"] = pd.NaT
    refused("finite_label_without_maturity", lambda: s.analyze(short_features, missing_end))
    bad_downside = labels.copy()
    bad_downside.loc[short_index[0], "downside_3"] = -.1
    refused("negative_downside_magnitude", lambda: s.analyze(short_features, bad_downside))
    bad_binary = labels.copy()
    bad_binary.loc[short_index[0], "negative_gap_next"] = 2.
    refused("nonbinary_gap", lambda: s.analyze(short_features, bad_binary))
    refused("misaligned_opportunity", lambda: s.analyze(short_features, labels, opportunity.iloc[::-1]))
    refused("non_boolean_opportunity", lambda: s.analyze(short_features, labels, opportunity.astype(int)))
    bad_inf = short_features.copy()
    bad_inf.iloc[0, 0] = np.inf
    refused("infinite_feature", lambda: s.analyze(bad_inf, labels))
    return {"status": "PASS", "synthetic_only": True, "checks": checks, "refusals": refusals,
            "source_sha256": hashlib.sha256(Path(s.__file__).read_bytes()).hexdigest(),
            "method_sha256": small["method_sha256"]}


if __name__ == "__main__":
    out = Path(__file__).parent
    proof = run()
    (out / "component_statistics_focused.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    s.write_method(out / "component_statistics_method.json")
    print(json.dumps({"status": proof["status"], "checks": len(proof["checks"]),
                      "refusals": len(proof["refusals"]), "source_sha256": proof["source_sha256"]}))
