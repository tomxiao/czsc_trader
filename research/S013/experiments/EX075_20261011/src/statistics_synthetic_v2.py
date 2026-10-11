"""Independent artificial-only checks; never reads a market input."""

import ast
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

import statistics_draft_v2 as s
from component_draft import fee_labels4


def independent_partial(x, y, z):
    keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(z).all(axis=1)
    x, y, z = x[keep], y[keep], z[keep]
    d = np.column_stack([np.ones(len(x)), np.apply_along_axis(rankdata, 0, z)])
    u, singular, _ = np.linalg.svd(d, full_matrices=False)
    rank = int((singular > max(d.shape) * np.finfo(float).eps * singular[0]).sum())
    projection = u[:, :rank] @ u[:, :rank].T
    a, b = rankdata(x), rankdata(y)
    a, b = a - projection @ a, b - projection @ b
    return float(a @ b / np.sqrt((a @ a) * (b @ b))), rank, len(x) - rank


def independent_ridge(x, y, test):
    design = np.column_stack([np.ones(len(x)), x])
    penalty = np.diag([0, *([10] * x.shape[1])])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return np.column_stack([np.ones(len(test)), test]) @ coefficients


def check():
    checks, refusals = [], []
    rng = np.random.default_rng(726)
    z = rng.normal(size=(120, 18))
    x = rng.normal(size=120)
    y = 0.2 * x + 0.3 * z[:, 0] + rng.normal(size=120)
    x[2], z[7, 8], y[11] = np.nan, np.nan, np.nan
    value, rank, df = independent_partial(x, y, z)
    out = s.correlation(x, y, z)
    assert np.isclose(out["value"], value, atol=1e-12)
    assert out["design_rank"] == rank and out["residual_df"] == df
    assert out["finite_positions"] == [i for i in range(120) if i not in (2, 7, 11)]
    good = np.isfinite(x) & np.isfinite(y)
    assert np.isclose(s.correlation(x, y)["value"], spearmanr(x[good], y[good]).statistic)
    checks.append("independent_rank_projection_raw_partial_masks_rank_df")

    dependent = np.tile(np.arange(120)[:, None], (1, 18))
    out = s.correlation(np.arange(120), np.sin(np.arange(120)), dependent)
    assert out["reason"] == "EXPLAINED_COMPONENT" and out["design_rank"] == 2
    out = s.correlation(np.sin(np.arange(120)), np.arange(120), dependent)
    assert out["reason"] == "TARGET_EXPLAINED_OR_CONSTANT"
    assert s.correlation(np.ones(120), y)["reason"] == "CONSTANT_COMPONENT"
    assert (
        s.correlation(np.arange(20), rng.normal(size=20), rng.normal(size=(20, 18)))["reason"]
        == "INSUFFICIENT_RESIDUAL_DF"
    )
    checks.append("duplicate_controls_actual_rank_explained_sides_constant_df_refusal")

    sampled = s.block_indices(120)
    rr = np.random.default_rng(13)
    starts = rr.integers(0, 81, (500, 3))
    independent = np.array([np.concatenate([np.arange(k, k + 40) for k in row]) for row in starts])
    assert np.array_equal(sampled, independent)
    boot = s.bootstrap(x, y, z, sampled)
    assert len(boot["replicates"]) == 500 and sum(boot["status_counts"].values()) == 500
    for pos in (0, 17, 499):
        rows = independent[pos]
        v, r, d = independent_partial(x[rows], y[rows], z[rows])
        item = boot["replicates"][pos]
        assert np.isclose(v, item["value"], atol=1e-11)
        assert item["design_rank"] == r and item["residual_df"] == d
    values = [r["value"] for r in boot["replicates"] if r["value"] is not None]
    assert np.allclose(boot["ic95"], np.percentile(values, [2.5, 97.5]))
    absent = s.bootstrap(x[:39], y[:39], z[:39], s.block_indices(39))
    assert absent["valid"] == 0 and absent["status_counts"] == {"INSUFFICIENT_FULL_AXIS": 500}
    checks.append("fixed500_fullaxis40_seed13_before_missing_filter_all_statuses_ci")

    t = np.array([0.0, 1.0, 1.0, 3.0])
    v = np.array([-1.0, 0.0, 1.0, 2.0, 3.0, 4.0])
    expected = np.array([np.mean((t < a).astype(float) + 0.5 * (t == a)) for a in v])
    assert np.array_equal(s.ecdf(t, v), expected)
    a, b = rng.random((80, 19)), rng.normal(size=80)
    test = rng.random((23, 19))
    assert np.allclose(s.ridge(a, b, test), independent_ridge(a, b, test), atol=1e-12)
    checks.append("train_ecdf_ties_extremes_unpenalized_intercept_fixed_ridge10")

    index = pd.bdate_range("2020-01-01", periods=850)
    all_x = rng.normal(size=(850, 19))
    target = rng.normal(size=850)
    ends = pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    ends.iloc[:-5] = index[5:].to_numpy()
    target[-5:] = np.nan
    all_x[0:20, 17] = np.nan
    all_x[350, -1] = np.nan
    walk = s.walk_forward(index, all_x, target, ends)
    total = 0
    for year, row in walk["yearly"].items():
        if row["reason"] is not None:
            continue
        tr, te = np.array(row["train_positions"]), np.array(row["test_positions"])
        first = index[index.year == int(year)][0]
        expected_tr = np.flatnonzero(
            np.isfinite(all_x).all(axis=1)
            & np.isfinite(target)
            & (index.year >= 2020)
            & (index.year < int(year))
            & (ends < first).to_numpy()
        )
        expected_te = np.flatnonzero(
            np.isfinite(all_x).all(axis=1) & np.isfinite(target) & (index.year == int(year))
        )
        assert np.array_equal(tr, expected_tr) and np.array_equal(te, expected_te)
        assert ends.iloc[tr].max() < first

        def ranked(c, vv):
            return np.array([np.mean((c < aa).astype(float) + 0.5 * (c == aa)) for aa in vv])

        train = np.column_stack([ranked(c, c) for c in all_x[tr].T])
        test = np.column_stack([ranked(c, vv) for c, vv in zip(all_x[tr].T, all_x[te].T)])
        pred_c = independent_ridge(train[:, :18], target[tr], test[:, :18])
        pred_a = independent_ridge(train, target[tr], test)
        records = [r for r in walk["records"] if pd.Timestamp(r["signaldate"]).year == int(year)]
        assert np.allclose(pred_c, [r["controls"] for r in records], atol=1e-12)
        assert np.allclose(pred_a, [r["augmented"] for r in records], atol=1e-12)
        assert np.allclose(target[tr].mean(), [r["pastmean"] for r in records])
        total += len(te)
    assert total == len(walk["records"])
    ys = np.array([r["target"] for r in walk["records"]])
    for name in ("controls", "augmented", "pastmean"):
        predictions = np.array([r[name] for r in walk["records"]])
        assert walk["aggregate"]["mse_" + name] == float(np.mean((ys - predictions) ** 2))
    assert (
        walk["aggregate"]["delta_controls"]
        == walk["aggregate"]["mse_controls"] - walk["aggregate"]["mse_augmented"]
    )
    assert (
        walk["aggregate"]["delta_pastmean"]
        == walk["aggregate"]["mse_pastmean"] - walk["aggregate"]["mse_augmented"]
    )
    checks.append("independent_mature_common19_masks_both_ridges_pastmean_pooled_rowweighted_mse")

    future = index.year >= 2022
    mutated_x, mutated_y = all_x.copy(), target.copy()
    mutated_x[future] = rng.normal(size=(future.sum(), 19)) * 500
    mutated_y[future] = rng.normal(size=future.sum())
    mutated_y[-5:] = np.nan
    changed = s.walk_forward(index, mutated_x, mutated_y, ends)
    old = [r for r in walk["records"] if pd.Timestamp(r["signaldate"]).year == 2021]
    new = [r for r in changed["records"] if pd.Timestamp(r["signaldate"]).year == 2021]
    assert old == new
    prefix = index.year <= 2021
    trimmed = s.walk_forward(index[prefix], all_x[prefix], target[prefix], ends[prefix])
    assert trimmed["yearly"]["2021"] == walk["yearly"]["2021"]
    checks.append("future_feature_label_mutation_and_prefix_unchanged_earlier_predictions")

    smallindex = index[:120]
    frame = pd.DataFrame(
        rng.normal(size=(120, 19)), index=smallindex, columns=[*s.CONTROLS, s.COMPONENT]
    )
    end = pd.Series(pd.NaT, index=smallindex, dtype="datetime64[ns]")
    end.iloc[:-5] = smallindex[5:].to_numpy()
    labels = pd.DataFrame(
        {
            "return4_net": rng.normal(size=120) * 0.01,
            "downside4_oc": rng.random(120) * 0.1,
            "label_end4": end,
        },
        index=smallindex,
    )
    labels.iloc[-5:, :2] = np.nan
    result = s.analyze(frame, labels, smallindex)
    for name in s.LABELS:
        panel = result["labels"][name]
        assert (
            len(panel["phases"]) == 5
            and panel["walk_forward"]["aggregate"]["reason"] == "INSUFFICIENT_TEST_SAMPLE"
        )
        assert len(panel["partial_bootstrap"]["replicates"]) == 500
        for phase in range(5):
            mask = np.arange(120) % 5 == phase
            p = panel["phases"][str(phase)]["partial"]
            assert p["n"] == int((mask & labels[name].notna().to_numpy()).sum())
            assert p["value"] is None and p["reason"] == "INSUFFICIENT_RESIDUAL_DF"
    checks.append("two_fixed_labels_five_original_axis_phases_thin_nulls_no_oos_zero")

    calendar = index[:121]
    independent_prices = pd.DataFrame(
        {"Open": 100 + np.arange(121) * 0.2, "Close": 100 + np.arange(121) * 0.15},
        index=calendar,
    )
    tail_labels = fee_labels4(independent_prices, smallindex)
    assert tail_labels.loc[smallindex[115], "label_end4"] == calendar[120]
    assert calendar[120] not in frame.index
    s.validate(frame, tail_labels, calendar)
    analyzed = s.analyze(frame, tail_labels, calendar)
    assert analyzed["full_axis_n"] == 120
    assert analyzed["labels"]["return4_net"]["raw"]["n"] == 116
    assert s.block_indices(len(frame)).shape == (500, 120)
    subset = smallindex[::2]
    subset_labels = fee_labels4(independent_prices, subset)
    s.validate(frame.loc[subset], subset_labels, calendar)
    assert subset_labels.loc[subset[2], "label_end4"] == calendar[9]
    assert subset[2] == calendar[4]
    for dates in (None, calendar[::2], calendar[::-1], calendar.append(calendar[-1:])):
        try:
            s.validate(frame, tail_labels, dates)
        except ValueError:
            pass
        else:
            raise AssertionError("missing completecalendar refusal")
    try:
        s.validate(frame, tail_labels, smallindex)
    except ValueError:
        pass
    else:
        raise AssertionError("extra-tail label cannot be authenticated by truncated price calendar")
    checks.append(
        "price_tail_beyond_signal_axis_subset_holes_completecalendar_maturity_signalaxis_bootstrap"
    )

    cases = []
    bad = labels.copy()
    bad.iloc[0, 2] = smallindex[4]
    cases.append((frame, bad, "wrong_h4_maturity"))
    bad = labels.copy()
    bad.iloc[0, 1] = -1
    cases.append((frame, bad, "negative_downside"))
    bad = frame.copy()
    bad["return4_net"] = 0.0
    cases.append((bad, labels, "future_column"))
    bad = frame.copy()
    bad.iloc[0, 0] = np.inf
    cases.append((bad, labels, "infinite_control"))
    cases.append((frame.drop(columns=s.CONTROLS[0]), labels, "missing_fixed_control"))
    cases.append((frame.iloc[::-1], labels.iloc[::-1], "unordered_axis"))
    for f, lab, name in cases:
        try:
            s.validate(f, lab, smallindex)
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError("missing refusal " + name)
    parsed = ast.parse(Path(s.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(parsed):
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in {
                "open",
                "read_csv",
                "read_json",
                "read_parquet",
                "read_text",
                "read_bytes",
                "write_text",
                "write_bytes",
                "exec",
                "eval",
                "subprocess",
            }
    checks.append("ast_no_io_or_execution_entrypoint")
    return {
        "status": "PASS_ARTIFICIAL_INPUTS_ONLY",
        "checks": checks,
        "refusals": refusals,
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(s.__file__), Path(__file__))
        },
        "real_data_reads": 0,
        "real_statistics": 0,
        "signals": 0,
        "accounts": 0,
        "allocate": 0,
        "publish": 0,
        "DEV": 0,
    }


if __name__ == "__main__":
    proof = check()
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(proof, ensure_ascii=False))
