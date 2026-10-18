"""Independently check EX031 fixed-score statistics, without fitting models."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd

EX = Path(__file__).resolve().parents[1]
ROOT = EX.parents[3]
OUT = EX / "others"


def main():
    def prohibited(*args, **kwargs):
        raise RuntimeError("Statistical audit forbids network and fitting")

    socket.socket.connect = prohibited
    socket.create_connection = prohibited
    np.linalg.solve = prohibited
    np.linalg.lstsq = prohibited
    target = OUT / "independent_statistics_audit.json"
    assert not target.exists(), "Preserve completed statistics audit"
    result = json.loads((OUT / "analysis.json").read_text(encoding="utf-8"))
    checks = []

    def ck(name, actual, expected=True):
        if expected is None or actual is None:
            good = expected is None and actual is None
        elif isinstance(expected, (float, np.floating)):
            good = bool(np.isclose(actual, expected, rtol=0, atol=2e-13))
        else:
            good = actual == expected
        if not good:
            raise AssertionError((name, actual, expected))
        checks.append(name)

    for relative, expected in result["source_sha256"].items():
        ck("source_hash_" + relative, sha256((ROOT / relative).read_bytes()).hexdigest(), expected)
    p = pd.read_csv(OUT / "predictions.csv")
    f = p.loc[p.A].copy()
    calendar = pd.read_csv(OUT / "calendar.csv")
    ck("parent_count", len(f), 216)

    def avg(values, weights):
        return float(np.average(values, weights=weights)) if np.sum(weights) > 0 else None

    def minus(a, b):
        return a - b if a is not None and b is not None else None

    def distribution(label, values, obj):
        values = np.asarray(values, float)
        ck(label + "_n", obj["n"], len(values))
        expected = {
            "mean": float(np.mean(values)) if len(values) else None,
            "median": float(np.median(values)) if len(values) else None,
            "q10": float(np.quantile(values, .1)) if len(values) else None,
            "positive_contribution": float(np.maximum(values, 0).mean()) if len(values) else None,
            "negative_contribution": float(np.minimum(values, 0).mean()) if len(values) else None,
        }
        for key, value in expected.items():
            ck(label + "_" + key, obj[key], value)

    def verify(label, rows, obj, column="Y3", weights=None, subtract_baseline=True):
        n = len(rows)
        w = np.ones(n) if weights is None else np.asarray(weights)
        y = rows[column].to_numpy(float)
        z = rows.z.to_numpy(bool)
        residual = y - rows.score_B.to_numpy(float) if subtract_baseline else y
        ck(label + "_n", obj["n"], n)
        ck(label + "_weight", obj["parent_weight"], float(w.sum()))
        ck(label + "_unfilled", obj["entry_unfilled"], int((~rows.entry_filled).sum()))
        distribution(label + "_parent", y, obj["parent"])
        raw_difference = minus(avg(y[z], w[z]), avg(y[~z], w[~z]))
        d1 = minus(avg(residual[z], w[z]), avg(residual[~z], w[~z]))
        d2 = avg(y * (rows.sel_Bz.to_numpy(int) - rows.sel_B.to_numpy(int)), w)
        ck(label + "_rawdiff", obj["raw_group_difference"], raw_difference)
        ck(label + "_D1", obj["D1"], d1)
        ck(label + "_D2", obj["D2"], d2)
        for name, mask in (("up", z), ("not_up", ~z)):
            group = obj["groups"][name]
            distribution(label + name, y[mask], group["raw"])
            ck(label + name + "_residual", group["residual_mean"], avg(residual[mask], w[mask]))
        for model in ("B", "Bz", "Bold"):
            mask = rows["sel_" + model].to_numpy(bool)
            sub = obj["models"][model]
            ck(label + model + "_count", sub["selected_count"], int(mask.sum()))
            ck(label + model + "_rate", sub["selection_rate"], float(mask.mean()) if n else None)
            allocation = avg(y * mask, w)
            ck(label + model + "_allocation", sub["allocation_per_parent"], allocation)
            ck(label + model + "_vs_all", sub["allocation_minus_all_parent"], minus(allocation, avg(y, w)))
        for new, base in (("Bz", "B"), ("Bold", "B"), ("Bz", "Bold")):
            ns, bs = rows["sel_" + new].to_numpy(bool), rows["sel_" + base].to_numpy(bool)
            sub = obj["comparisons"][new + "_minus_" + base]
            delta = y * (ns.astype(int) - bs.astype(int))
            ck(label + new + base + "_difference", sub["allocation_difference"], avg(delta, w))
            for name, mask in (("both", ns & bs), ("added", ns & ~bs),
                               ("removed", ~ns & bs), ("neither", ~ns & ~bs)):
                group = sub["groups"][name]
                ck(label + new + base + name + "_count", group["n"], int(mask.sum()))
                for key, values in (("parent_return_contribution", y * mask),
                                    ("new_allocation_contribution", y * mask * ns),
                                    ("base_allocation_contribution", y * mask * bs),
                                    ("difference_contribution", delta * mask)):
                    ck(label + new + base + name + key, group[key], avg(values, w))

    verify("main", f, result["main"])
    for year in (2023, 2024, 2025, 2026):
        verify(str(year), f.loc[f.year.eq(year)], result["annual"][str(year)])
        verify("omit" + str(year), f.loc[f.year.ne(year)], result["leave_one_year_out"][str(year)])
    verify("through2025", f.loc[f.year.le(2025)], result["through_2025"])
    verify("noroll", f.loc[~f.roll], result["exclude_roll"])
    verify("roll", f.loc[f.roll], result["roll_only"])
    for environment in ("high", "low", "unready"):
        verify(environment, f.loc[f.environment.eq(environment)], result["environment"][environment])
    common = f.loc[f.Y1.notna()].copy()
    verify("H3common", common, result["duration"]["H3_on_common"])
    verify("H1common", common, result["duration"]["H1_on_common"], "Y1")
    common["delta"] = common.Y3 - common.Y1
    verify("durationdelta", common, result["duration"]["H3_minus_H1"], "delta", subtract_baseline=False)

    # Independent resampling from calendar rows rather than preaggregated blocks.
    cal = calendar.loc[calendar.year.isin((2023, 2024, 2025, 2026))].sort_values("signal")
    source = f.set_index("signal")
    daily = np.zeros((len(cal), 6))
    for i, signal in enumerate(cal.signal):
        if signal not in source.index:
            continue
        row = source.loc[signal]
        residual = row.Y3 - row.score_B
        daily[i] = (1, bool(row.z), not bool(row.z), residual if row.z else 0,
                    residual if not row.z else 0, row.Y3 * (int(row.sel_Bz) - int(row.sel_B)))
    for length in (20, 60):
        stored = result["bootstrap"][str(length)]
        rng = np.random.default_rng(13)
        total = np.zeros((2000, 6))
        for year in (2023, 2024, 2025, 2026):
            indices = np.flatnonzero(cal.year.to_numpy() == year)
            chunks = [indices[start:start + length] for start in range(0, len(indices), length)]
            selection = rng.integers(0, len(chunks), size=(2000, len(chunks)))
            for rep in range(2000):
                selected_rows = np.concatenate([chunks[k] for k in selection[rep]])
                total[rep] += daily[selected_rows].sum(0)
            meta = next(item for item in stored["year_blocks"] if item["year"] == year)
            ck(f"boot{length}_{year}_calendar", meta["calendar_days"], len(indices))
            ck(f"boot{length}_{year}_empty", meta["empty_nonparent_days"], int((daily[indices, 0] == 0).sum()))
            ck(f"boot{length}_{year}_tail", meta["last_block_days"], len(chunks[-1]))
        valid1 = (total[:, 1] > 0) & (total[:, 2] > 0)
        valid2 = total[:, 0] > 0
        joint = valid1 & valid2
        values = np.full((2000, 2), np.nan)
        values[valid1, 0] = total[valid1, 3] / total[valid1, 1] - total[valid1, 4] / total[valid1, 2]
        values[valid2, 1] = total[valid2, 5] / total[valid2, 0]
        ck(f"boot{length}_joint", stored["jointly_valid"], int(joint.sum()))
        ck(f"boot{length}_missing_groups", stored["failed_missing_z_group"], int((~valid1).sum()))
        ck(f"boot{length}_no_parent", stored["failed_no_parent"], int((~valid2).sum()))
        for j, key in enumerate(("D1", "D2")):
            for mode, observations, probabilities in (
                ("ordinary_95", values[np.isfinite(values[:, j]), j], [.025, .975]),
                ("simultaneous_two_main_95", values[joint, j], [.0125, .9875]),
            ):
                bounds = np.quantile(observations, probabilities)
                ck(f"boot{length}{mode}{key}_low", stored[mode][key]["low"], float(bounds[0]))
                ck(f"boot{length}{mode}{key}_high", stored[mode][key]["high"], float(bounds[1]))

    # Degenerate bootstrap populations must remain missing, never become zero.
    spec = importlib.util.spec_from_file_location("ex031_locked_statistics", EX / "src/analyze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for label, rows in (("no_parent", f.iloc[:0]), ("up_only", f.loc[f.z.eq(1)])):
        edge = module.bootstrap(rows, calendar, 20, replicates=30)
        ck(label + "_no_joint", edge["jointly_valid"], 0)
        ck(label + "_D1_missing", edge["ordinary_95"]["D1"]["low"], None)
        if not len(rows):
            ck(label + "_D2_missing", edge["ordinary_95"]["D2"]["low"], None)
        else:
            ck(label + "_D2_available", edge["ordinary_95"]["D2"]["valid"], 30)
    ck("budget_no_stats_fits", result["fits"], 0)
    ck("budget_no_stats_accounts", result["accounts"], 0)
    environment = json.loads((OUT / "environment_annual.json").read_text(encoding="utf-8"))
    for row in environment["rows"]:
        group = f.loc[f.environment.eq(row["environment"])]
        if row["year"] == "WITHOUT2026":
            group = group.loc[group.year.ne(2026)]
        elif row["year"] != "ALL":
            group = group.loc[group.year.eq(int(row["year"]))]
        label = "envyear_" + row["environment"] + row["year"]
        up = group.z.eq(1)
        residual = group.Y3 - group.score_B
        d1 = float(residual[up].mean() - residual[~up].mean()) if up.any() and (~up).any() else None
        d2 = float((group.Y3 * (group.sel_Bz.astype(int) - group.sel_B.astype(int))).mean())
        for key, expected in (("n", len(group)), ("up_n", int(up.sum())),
                              ("not_up_n", int((~up).sum())), ("D1", d1), ("D2", d2),
                              ("changed_decisions", int(group.sel_Bz.ne(group.sel_B).sum()))):
            ck(label + key, row[key], expected)
    low_changes = f.loc[f.environment.eq("low") & f.sel_Bz.ne(f.sel_B)]
    ck("low_environment_three_changes", len(low_changes), 3)
    ck("low_environment_changes_only2025", low_changes.year.unique().tolist(), [2025])
    inventory = json.loads((OUT / "label_inventory.json").read_text(encoding="utf-8"))
    inputs = pd.read_csv(OUT / "inputs.csv").set_index("signal")
    labels = pd.read_csv(OUT / "labels.csv")
    populations = {
        "full_methanol": inputs.A & inputs.z.notna(),
        "common_features": inputs.A & inputs.feature_ready,
        "evaluation2023plus": inputs.A & inputs.feature_ready & inputs.year.ge(2023),
    }
    expected_exclusions = set()
    for row in inventory["inventory"]:
        scope, year, horizon = row["scope"], row["year"], row["horizon"]
        values = labels.loc[labels.horizon.eq(horizon)].set_index("signal").reindex(inputs.index)
        group = values.loc[populations[scope] & inputs.year.eq(year)]
        mature = group.loc[group.maturity.ge(0)]
        expected = {
            "parent": len(group), "missing_label": int(group.status.isna().sum()),
            "mature": len(mature), "filled_closed": int(group.status.eq("CLOSED").sum()),
            "unfilled": int(group.status.eq("UNFILLED").sum()),
            "right_censored": int(group.maturity.lt(0).sum()),
            "raw_mature_mean": float(mature.net_return.mean()) if len(mature) else None,
        }
        for key, value in expected.items():
            ck(f"inventory_{scope}_{year}_{horizon}_{key}", row[key], value)
        for signal, item in group.loc[group.status.isna() | group.maturity.lt(0)].iterrows():
            reason = "NO_HISTORICAL_LABEL" if pd.isna(item.status) else "RIGHT_CENSORED"
            expected_exclusions.add((scope, year, horizon, int(signal), inputs.loc[signal, "date"], reason))
    actual_exclusions = {(x["scope"], x["year"], x["horizon"], x["signal"], x["date"], x["reason"])
                         for x in inventory["excluded"]}
    ck("inventory_exclusions", actual_exclusions, expected_exclusions)
    ck("inventory_H1_only_parent", inventory["H1_only_mature_parent_signals"], [1639])
    ck("inventory_H1_only_date", inventory["H1_only_dates"], ["2026-10-13"])
    audit = {
        "status": "PASS", "checks_count": len(checks), "checks": checks,
        "main_D1": result["main"]["D1"], "main_D2": result["main"]["D2"],
        "scope": "Independent main/group/model-four-way/annual/leave-year/roll/environment/duration arithmetic; environment-by-year and H1/H3 label inventories; independent calendar-row reconstruction of both bootstrap intervals; empty and single-group boundary checks",
        "new_model_fits": 0, "new_accounts": 0, "new_source_calls": 0,
        "static_warning": "Locked analyze.py has four Ruff F601 duplicate numeric/boolean literal-key warnings; Python True==1==1.0 and False==0==0.0 map to identical values. Nonblocking and original published source preserved.",
        "analysis_sha256": sha256((OUT / "analysis.json").read_bytes()).hexdigest(),
        "environment_annual_sha256": sha256((OUT / "environment_annual.json").read_bytes()).hexdigest(),
        "label_inventory_sha256": sha256((OUT / "label_inventory.json").read_bytes()).hexdigest(),
        "audit_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    target.write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in ("status", "checks_count", "main_D1", "main_D2", "new_model_fits")}))


if __name__ == "__main__":
    main()
