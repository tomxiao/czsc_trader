"""Fixed EX039 loss-risk study. Offline only; explicit --run-fits is required.

All returns are decimal attempt returns, never account returns. Missing external
features are excluded identically within a family, never filled with zero.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
import multiprocessing as mp
import os
from pathlib import Path
import socket

for _key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS"):
    os.environ[_key] = "1"

import numpy as np  # noqa: E402 -- BLAS thread limits must precede NumPy import.
import pandas as pd  # noqa: E402 -- BLAS thread limits must precede NumPy import.

YEARS = (2023, 2024, 2025, 2026)
ALPHA, FIT_CAP, BOOTSTRAPS, SEED = 10.0, 28, 2000, 13
ETF_CONTROLS = ["etf_price_ret1", "etf_price_ret5"]
OPT_CONTROLS = ["opt_ret1", "opt_rv20", "opt_vol_ratio", "opt_log_oi", "opt_log_volume", "opt_share_Q", "opt_dte"]


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def block_network(*args, **kwargs):
    raise RuntimeError("EX039 fixed analysis forbids network access")


def offline():
    socket.socket.connect = block_network
    socket.create_connection = block_network


def boolean(values, name, allow_missing=False):
    result = values.astype("string").str.lower().map({"true": True, "false": False, "1": True, "0": False, "1.0": True, "0.0": False})
    if (values.notna() & result.isna()).any() or (not allow_missing and result.isna().any()):
        raise ValueError(f"{name}: missing or invalid boolean")
    return result.astype("boolean") if allow_missing else result.astype(bool)


def model_spec(b65):
    e0 = b65 + ETF_CONTROLS
    o0 = b65 + OPT_CONTROLS
    j0 = b65 + ETF_CONTROLS + OPT_CONTROLS
    return {"ETF": {"E0": e0, "E1": e0 + ["etf_z"], "E2": e0 + ["etf_z_late"]},
            "OPTION": {"O0": o0, "O1": o0 + ["opt_delta_put"]},
            "JOINT": {"J0": j0, "J1": j0 + ["etf_z", "opt_delta_put"]}}


def prepare(ex, b65):
    source = ex / "others/model_inputs.csv"
    frame = pd.read_csv(source)
    if frame.signal.duplicated().any():
        raise ValueError("duplicate input signal")
    calendar = pd.read_csv(ex / "others/calendar.csv")
    if calendar.signal.duplicated().any() or calendar.date.duplicated().any():
        raise ValueError("duplicate calendar signal/date")
    dates = pd.to_datetime(calendar.set_index("signal").date)
    frame["date"] = pd.to_datetime(frame.date)
    if not frame.date.equals(pd.to_datetime(frame.signal.map(dates)).rename("date")):
        raise ValueError("input/calendar date mismatch")
    frame["A"] = boolean(frame.A, "A")
    frame["entry_filled"] = boolean(frame.entry_filled, "entry_filled", allow_missing=True)
    frame["maturity_date"] = pd.to_datetime(frame.maturity.map(dates))
    frame["entry_index"] = pd.to_numeric(frame.entry, errors="coerce")
    frame["maturity_index"] = pd.to_numeric(frame.maturity, errors="coerce")
    frame["L"] = np.maximum(-pd.to_numeric(frame.Y3, errors="coerce"), 0)
    labels = pd.read_csv(ex / "others/labels.csv")
    labels = labels[labels.horizon == 3].copy()
    if labels.signal.duplicated().any():
        raise ValueError("duplicate H3 label signal")
    lab = labels.set_index("signal")
    ready = frame.Y3.notna()
    expected = frame.loc[ready, "signal"].map(lab.net_return)
    if not np.isfinite(expected).all() or not np.allclose(frame.loc[ready, "Y3"], expected, rtol=0, atol=1e-12):
        raise ValueError("immutable H3 return mismatch")
    expected_mat = frame.loc[ready, "signal"].map(lab.maturity)
    if not np.array_equal(frame.loc[ready, "maturity"], expected_mat):
        raise ValueError("immutable H3 maturity mismatch")
    if "entry" in lab and not np.array_equal(frame.loc[ready, "entry"], frame.loc[ready, "signal"].map(lab.entry)):
        raise ValueError("immutable H3 entry index mismatch")
    expected_fill = boolean(frame.loc[ready, "signal"].map(lab.entry_filled), "label entry_filled")
    if not np.array_equal(frame.loc[ready, "entry_filled"], expected_fill):
        raise ValueError("immutable H3 fill mismatch")
    if (frame.loc[ready, "maturity_date"] <= frame.loc[ready, "date"]).any():
        raise ValueError("nonfuture maturity")
    if frame.loc[ready, "maturity_date"].isna().any():
        raise ValueError("finite H3 maturity absent from calendar")
    filled = ready & frame.entry_filled.fillna(False)
    if (frame.loc[filled, "entry_index"] <= frame.loc[filled, "signal"]).any() or (frame.loc[filled, "entry_index"] > frame.loc[filled, "maturity_index"]).any():
        raise ValueError("invalid realized entry/maturity interval")
    parent = frame[frame.A].copy()
    coverage = {"input_rows": len(frame), "parent_rows": len(parent), "family_years": {}, "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "input_hashes": {name: sha256((ex / "others" / name).read_bytes()).hexdigest() for name in ("model_inputs.csv", "calendar.csv", "labels.csv")}}
    specifications = model_spec(b65)
    tasks = []
    for family, models in specifications.items():
        columns = list(dict.fromkeys(c for v in models.values() for c in v))
        missing_columns = [c for c in columns if c not in parent]
        finite = np.zeros(len(parent), dtype=bool) if missing_columns else np.isfinite(parent[columns].to_numpy(float)).all(axis=1)
        required_flags = ["etf_ready"] if family == "ETF" else ["opt_ready"] if family == "OPTION" else ["etf_ready", "opt_ready"]
        absent_flags = [c for c in required_flags if c not in parent]
        if absent_flags:
            finite[:] = False
            missing_columns += absent_flags
        else:
            for flag in required_flags:
                finite &= boolean(parent[flag], flag, allow_missing=True).fillna(False).to_numpy(bool)
        finite &= np.isfinite(parent.Y3.to_numpy(float)) & parent.maturity_date.notna().to_numpy() & parent.entry_filled.notna().to_numpy()
        for year in YEARS:
            jan = pd.Timestamp(year, 1, 1)
            in_year = parent.date.dt.year.eq(year)
            train = parent[finite & parent.date.lt(jan) & parent.maturity_date.lt(jan)]
            test = parent[finite & in_year]
            key = f"{family}_{year}"
            coverage["family_years"][key] = {"missing_feature_columns": missing_columns, "all_A": int(in_year.sum()),
                "A_finite_Y3": int((in_year & np.isfinite(parent.Y3.to_numpy(float))).sum()), "common_evaluable_A": len(test),
                "train_common": len(train), "missing_or_unmatured_A": int(in_year.sum()) - len(test),
                "train_max_maturity": None if train.empty else train.maturity_date.max().isoformat(),
                "train_max_decision": None if train.empty else train.date.max().isoformat(),
                "finite_label_missing": int((in_year & ~np.isfinite(parent.Y3.to_numpy(float))).sum()),
                "feature_nonfinite_by_column": {c: int((in_year & ~np.isfinite(parent[c].to_numpy(float))).sum()) for c in columns if c in parent},
                "quality_not_ready": {c: int((in_year & ~boolean(parent[c], c, allow_missing=True).fillna(False)).sum()) for c in required_flags if c in parent},
                "exclusions": [{"signal": int(r.signal), "date": r.date.isoformat(), "maturity": None if pd.isna(r.maturity) else int(r.maturity)} for r in parent.loc[in_year & ~finite, ["signal", "date", "maturity"]].itertuples()]}
            for name, cols in models.items():
                tasks.append({"family": family, "model": name, "year": year, "columns": cols,
                    "train_X": train[cols].to_numpy(float) if not missing_columns else np.empty((0, len(cols))),
                    "train_y": train.L.to_numpy(float), "test_X": test[cols].to_numpy(float) if not missing_columns else np.empty((0, len(cols))),
                    "test_signals": test.signal.astype(int).tolist(), "train_signals": train.signal.astype(int).tolist(),
                    "missing_columns": missing_columns})
    return parent, tasks, coverage


def fit_one(task):
    """One counted deterministic ridge fit; no retries or alternate models."""
    offline()
    if task["missing_columns"] or not len(task["train_y"]) or not len(task["test_signals"]):
        return {"status": "INSUFFICIENT_DATA", "missing_columns": task["missing_columns"], "train_n": len(task["train_y"]), "test_n": len(task["test_signals"])}
    x, y, test = task["train_X"], task["train_y"], task["test_X"]
    mu, scale = x.mean(axis=0), x.std(axis=0, ddof=0)
    scale[scale < 1e-12] = 1.0
    z = (x - mu) / scale
    intercept = float(y.mean())
    coef = np.linalg.solve(z.T @ z + ALPHA * np.eye(x.shape[1]), z.T @ (y - intercept))
    scores = (test - mu) / scale @ coef + intercept
    threshold = float(np.quantile(z @ coef + intercept, 0.75, method="linear"))
    if not np.isfinite(scores).all() or not np.isfinite(coef).all():
        raise ValueError("nonfinite ridge output")
    return {"status": "SUCCESS", "train_n": len(y), "test_n": len(test), "columns": task["columns"],
        "means": mu.tolist(), "scales": scale.tolist(), "standardized_coefficients": coef.tolist(),
        "intercept": intercept, "threshold_q75": threshold, "threshold_rule": "keep score < train_q75; equality excluded",
        "test_signals": task["test_signals"], "train_signals": task["train_signals"], "scores": scores.tolist(),
        "keep": (scores < threshold).tolist()}


def execute_fits(tasks, output):
    slots = output / "fit_slots"
    if slots.exists() and list(slots.glob("*.json")):
        raise RuntimeError("Existing fit slots prohibit rerun/retry; preserve run and obtain explicit new authorization")
    slots.mkdir(parents=True, exist_ok=True)
    if len(tasks) != FIT_CAP:
        raise ValueError("fixed task count must be exactly 28")
    results = {}
    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context("spawn")) as pool:
        futures = {}
        for number, task in enumerate(tasks, 1):
            key = f"{task['family']}_{task['model']}_{task['year']}"
            path = slots / f"{number:02d}_{key}.json"
            record = {"slot": number, "key": key, "status": "RESERVED_COUNTED", "reserved_at": datetime.now(timezone.utc).isoformat(),
                "family": task["family"], "model": task["model"], "year": task["year"], "alpha": ALPHA}
            dump(path, record)
            if task["missing_columns"] or not len(task["train_y"]) or not len(task["test_signals"]):
                result = fit_one(task)
                dump(path, {**record, **result, "fit_attempted": False})
                results[key] = result
            else:
                try:
                    futures[pool.submit(fit_one, task)] = (key, path, record)
                except Exception as exc:
                    result = {"status": "TECHNICAL_FAILURE", "error": f"{type(exc).__name__}: {exc}"}
                    dump(path, {**record, **result, "fit_attempted": True})
                    results[key] = result
        for future in as_completed(futures):
            key, path, record = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"status": "TECHNICAL_FAILURE", "error": f"{type(exc).__name__}: {exc}"}
            dump(path, {**record, **result, "fit_attempted": True})
            results[key] = result
    return results


def wm(values, weights):
    return None if not weights.sum() else float(np.dot(values, weights) / weights.sum())


def metrics(f, base, new, weights=None):
    w = np.ones(len(f)) if weights is None else np.asarray(weights, float)
    y, loss = f.Y3.to_numpy(float), f.L.to_numpy(float)
    kb, kn = f[f"keep_{base}"].to_numpy(bool), f[f"keep_{new}"].to_numpy(bool)
    psb, psn = f[f"score_{base}"].to_numpy(float), f[f"score_{new}"].to_numpy(float)
    delta = y * (kn.astype(int) - kb.astype(int))
    removed, added = kb & ~kn, kn & ~kb
    return {"n": len(f), "weight": float(w.sum()), "mse_improvement": wm((loss - psb)**2 - (loss - psn)**2, w),
        "allocation_difference_per_evaluable_A": wm(delta, w), "base_allocation": wm(y * kb, w), "new_allocation": wm(y * kn, w),
        "base_keep_rate": wm(kb.astype(float), w), "new_keep_rate": wm(kn.astype(float), w),
        "reduced_losses_removed": wm(np.maximum(-y, 0) * removed, w), "foregone_positive_removed": wm(np.maximum(y, 0) * removed, w),
        "added_positive": wm(np.maximum(y, 0) * added, w), "added_losses": wm(np.maximum(-y, 0) * added, w),
        "removed_n": int(removed.sum()), "added_n": int(added.sum()),
        "base_selected_mean": wm(y[kb], w[kb]), "new_selected_mean": wm(y[kn], w[kn]),
        "base_selected_negative_rate": wm((y[kb] < 0).astype(float), w[kb]), "new_selected_negative_rate": wm((y[kn] < 0).astype(float), w[kn]),
        "raw_loss_mean": wm(loss, w), "raw_Y3_mean": wm(y, w), "raw_negative_rate": wm((y < 0).astype(float), w)}


def clusters(f):
    membership, number, last = {}, 0, None
    for r in f[f.entry_filled.astype(bool)].sort_values(["entry_index", "maturity_index", "signal"]).itertuples():
        if last is None or r.entry_index > last:
            number += 1
            last = r.maturity_index
        else:
            last = max(last, r.maturity_index)
        membership[r.signal] = number
    for signal in f.loc[~f.entry_filled.astype(bool), "signal"]:
        number += 1
        membership[signal] = number
    return f.signal.map(membership).to_numpy(int)


def diagnostic(f, base, new, all_a, exposure):
    main = metrics(f, base, new)
    main["all_A_count"] = int(all_a)
    main["allocation_difference_per_all_A"] = None if not all_a else main["allocation_difference_per_evaluable_A"] * len(f) / all_a
    main["denominator_note"] = "All-A scaling sums only observed common-row differences. Missing external rows have no estimated policy effect; this is not an executable missing-data rule."
    if not len(f):
        return main
    residual = f.L - f[f"score_{base}"]
    state = f[exposure].to_numpy(float) > 0
    main["residual_positive_state_minus_other"] = None if state.all() or not state.any() else float(residual[state].mean() - residual[~state].mean())
    main["state_split"] = "exposure > 0 versus <= 0, descriptive fixed direction"
    main["state_counts"] = {"positive": int(state.sum()), "other": int((~state).sum())}
    membership = clusters(f)
    unique = np.unique(membership)
    main["cluster_count"] = len(unique)
    main["leave_one_cluster_out"] = [{"omitted": int(c), **metrics(f[membership != c], base, new)} for c in unique]
    delta = f.Y3.to_numpy(float) * (f[f"keep_{new}"].to_numpy(int) - f[f"keep_{base}"].to_numpy(int))
    sums = np.array([delta[membership == c].sum() for c in unique])
    main["largest_cluster_share_of_absolute_allocation_contribution"] = None if not np.abs(sums).sum() else float(np.max(np.abs(sums)) / np.abs(sums).sum())
    largest = unique[int(np.argmax(np.abs(sums)))]
    main["largest_absolute_allocation_cluster_removed"] = {"omitted_cluster": int(largest), **metrics(f[membership != largest], base, new)}
    sizes = {c: int((membership == c).sum()) for c in unique}
    main["equal_cluster"] = metrics(f, base, new, np.array([1.0 / sizes[c] for c in membership]))
    selected, last_exit = [], -np.inf
    for row in f.sort_values("signal", kind="stable").itertuples():
        if not row.entry_filled:
            selected.append(row.signal)
        elif row.entry_index > last_exit:
            selected.append(row.signal)
            last_exit = row.maturity_index
    main["chronological_nonoverlap"] = {"status": "DESCRIPTIVE_USES_REALIZED_EXIT_NOT_TRADABLE_RULE", **metrics(f[f.signal.isin(selected)], base, new), "signals": [int(v) for v in selected]}
    rng = np.random.default_rng(SEED)
    sampled = {"mse_improvement": [], "allocation_difference_per_evaluable_A": []}
    for _ in range(BOOTSTRAPS):
        chosen = rng.choice(unique, len(unique), replace=True)
        ids, counts = np.unique(chosen, return_counts=True)
        count_map = dict(zip(ids, counts))
        w = np.array([count_map.get(c, 0) for c in membership], float)
        values = metrics(f, base, new, w)
        for name in sampled:
            sampled[name].append(values[name])
    main["cluster_bootstrap"] = {"replicates": BOOTSTRAPS, "seed": SEED, "sampling": "resample inclusive entry-through-maturity connected clusters, keep cluster rows; unfilled attempts singleton", "intervals": {k: np.quantile(v, [0.025, 0.975]).tolist() for k, v in sampled.items()}, "status": "INSUFFICIENT_INDEPENDENT_CLUSTERS" if len(unique) < 2 else "DESCRIPTIVE_DEVELOPMENT_INTERVAL"}
    # Equal-participation count is known after observing new selection: diagnostic only.
    matched = np.zeros(len(f), bool)
    for year, g in f.groupby(f.date.dt.year):
        number = int(g[f"keep_{new}"].sum())
        order = g.sort_values([f"score_{base}", "signal"], kind="stable").index[:number]
        matched[f.index.get_indexer(order)] = True
    main["posthoc_matched_participation"] = {"status": "POSTHOC_DIAGNOSTIC_NOT_TRADABLE_RULE", "tie_break": "baseline score ascending then signal", "count": int(matched.sum()), "new_minus_matched_allocation": float((f.Y3.to_numpy(float) * (f[f"keep_{new}"].to_numpy(int) - matched.astype(int))).mean())}
    return main


def assemble(parent, results, coverage):
    report, predictions = {}, []
    for family, pairs, exposure in (("ETF", [("E0", "E1"), ("E0", "E2")], "etf_z"), ("OPTION", [("O0", "O1")], "opt_delta_put"), ("JOINT", [("J0", "J1")], "opt_delta_put")):
        models = sorted({m for pair in pairs for m in pair})
        frames, years = [], {}
        for year in YEARS:
            rr = {m: results[f"{family}_{m}_{year}"] for m in models}
            if any(r["status"] != "SUCCESS" for r in rr.values()):
                years[str(year)] = {"status": "INCOMPLETE_FAMILY", "model_statuses": {m: r["status"] for m, r in rr.items()}}
                continue
            ids = rr[models[0]]["test_signals"]
            if any(r["test_signals"] != ids for r in rr.values()):
                raise ValueError("family test rows differ")
            f = parent.set_index("signal", drop=False).loc[ids].copy().reset_index(drop=True)
            coefficients = {}
            for m, r in rr.items():
                f[f"score_{m}"] = r["scores"]
                f[f"keep_{m}"] = r["keep"]
                coefficients[m] = dict(zip(r["columns"], r["standardized_coefficients"]))
            years[str(year)] = {"status": "AVAILABLE", "coefficients": coefficients, "comparisons": {f"{n}_minus_{b}": diagnostic(f, b, n, coverage["family_years"][f"{family}_{year}"]["all_A"], "etf_z_late" if n == "E2" else exposure) for b, n in pairs}}
            frames.append(f)
            for m in models:
                for r in f.itertuples():
                    predictions.append({"family": family, "model": m, "year": year, "signal": int(r.signal), "date": r.date.isoformat(), "Y3": r.Y3, "L": r.L, "score": getattr(r, f"score_{m}"), "keep": bool(getattr(r, f"keep_{m}"))})
        report[family] = {"years": years, "comparisons": {}}
        if not frames:
            report[family]["status"] = "NO_ESTIMABLE_YEAR"
            continue
        full = pd.concat(frames, ignore_index=True)
        report[family]["status"] = "AVAILABLE" if len(frames) == len(YEARS) else "PARTIAL_YEARS"
        views = {"all_evaluation": full, "without_2026": full[full.date.dt.year < 2026], "filled_only": full[full.entry_filled.astype(bool)]}
        if family in ("OPTION", "JOINT"):
            for flag, meaning in (("opt_roll", "exclude_roll"), ("opt_active_pair", "active_pair_only")):
                if flag not in full or full[flag].isna().any():
                    report[family][meaning] = {"status": "INSUFFICIENT_DATA", "missing_flag": flag}
                else:
                    good = boolean(full[flag], flag)
                    views[meaning] = full[~good if flag == "opt_roll" else good]
        for view, f in views.items():
            selected_years = sorted(f.date.dt.year.unique())
            all_a = int(parent[parent.date.dt.year.isin(selected_years)].shape[0])
            report[family]["comparisons"][view] = {f"{n}_minus_{b}": diagnostic(f, b, n, all_a, "etf_z_late" if n == "E2" else exposure) for b, n in pairs}
    return report, pd.DataFrame(predictions)


def main():
    offline()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline-protocol", type=Path, default=Path(__file__).resolve().parents[2] / "EX032_20261018/protocols/design.json")
    parser.add_argument("--run-fits", action="store_true")
    args = parser.parse_args()
    ex = args.experiment_dir.resolve()
    b65 = json.loads(args.baseline_protocol.read_text(encoding="utf-8"))["baseline_columns"]
    if len(b65) != 65 or len(set(b65)) != 65:
        raise ValueError("B65 identity mismatch")
    parent, tasks, coverage = prepare(ex, b65)
    coverage["baseline_protocol_sha256"] = sha256(args.baseline_protocol.read_bytes()).hexdigest()
    coverage["analysis_source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    output = ex / "others/fixed_analysis"
    dump(output / "input_validation.json", {"status": "PASS", "fitting_requested": args.run_fits, **coverage})
    if not args.run_fits:
        print("INPUT_VALIDATION_PASS; no fits executed")
        return
    results = execute_fits(tasks, output)
    report, predictions = assemble(parent, results, coverage)
    predictions.to_csv(output / "predictions.csv", index=False)
    dump(output / "analysis.json", {"status": "COMPLETE_FIXED_ATTEMPT_NOT_ECONOMIC_ACCEPTANCE", "reserved_slots": len(results), "completed_fits": sum(v["status"] == "SUCCESS" for v in results.values()), "technical_failures": sum(v["status"] == "TECHNICAL_FAILURE" for v in results.values()), "fit_statuses": {k: v["status"] for k, v in results.items()}, "families": report, "coverage": coverage, "risk_target": "L=max(-Y3,0)", "keep_rule": "score < train_q75", "independent_validation": False, "continuous_accounts": 0})
    print("FIXED_ANALYSIS_SAVED")


if __name__ == "__main__":
    main()
