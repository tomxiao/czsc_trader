"""EX033 fixed, zero-fit, same-entry action-information test.

No upstream calls, label construction, fitting, or account replay. All returns
are existing EX023 net position returns. Output units are decimal returns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATES = ["entry_date", "decision_date", "R_exit_date", "B_exit_date"]
NUMERIC = ["close_net_of_buy_fee_return", "stock_return", "market_return",
           "sector_return", "amplitude", "remaining_to_H10_sessions",
           "action_delta", "R_position_return", "B_position_return"]
CONFOUNDERS = ["close_net_of_buy_fee_return", "stock_return", "amplitude",
               "remaining_to_H10_sessions"]
ACTIONS = ["R", "B", "P", "candidate"]


def boolean(s: pd.Series) -> np.ndarray:
    mapping = {"true": True, "false": False, "1": True, "0": False}
    x = s.astype(str).str.lower().map(mapping)
    if x.isna().any():
        raise ValueError(f"Missing/invalid boolean {s.name}")
    return x.to_numpy(dtype=bool)


def clusters(df: pd.DataFrame) -> np.ndarray:
    ends = df[["R_exit_date", "B_exit_date"]].max(axis=1)
    order = np.argsort(df.entry_date.to_numpy(), kind="stable")
    labels = np.empty(len(df), dtype=int)
    last_end = None
    cluster = -1
    for i in order:
        if last_end is None or df.entry_date.iloc[i] > last_end:
            cluster += 1
            last_end = ends.iloc[i]
        else:
            last_end = max(last_end, ends.iloc[i])
        labels[i] = cluster
    return labels


def prepare(source: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    df = source.copy().reset_index(drop=True)
    date_col = "trade_date" if "trade_date" in calendar else "date"
    cal = pd.DatetimeIndex(pd.to_datetime(calendar[date_col], errors="raise"))
    if cal.has_duplicates or not cal.is_monotonic_increasing:
        raise ValueError("Calendar must be unique and sorted")
    for c in DATES:
        df[c] = pd.to_datetime(df[c], errors="raise")
        if df[c].isna().any() or not df[c].isin(cal).all():
            raise ValueError(f"Missing or off-calendar {c}")
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="raise")
        if not np.isfinite(df[c]).all():
            raise ValueError(f"Nonfinite {c}")
    if df.entry_date.duplicated().any():
        raise ValueError("Expected one matched pair per unique entry")
    if not ((df.entry_date <= df.decision_date)
            & (df.decision_date < df.R_exit_date)
            & (df.decision_date < df.B_exit_date)).all():
        raise ValueError("Invalid decision/execution chronology")
    if not ((df.remaining_to_H10_sessions > 0)
            & (df.remaining_to_H10_sessions % 1 == 0)).all():
        raise ValueError("Remaining original H10 sessions must be positive integers")
    for c in ["entry_year", "decision_year"]:
        actual = df[c.replace("year", "date")].dt.year
        if c in df and not (df[c].astype(int) == actual).all():
            raise ValueError(f"Incorrect {c}")
        df[c] = actual
    flag = {
        "positive_mark": df.close_net_of_buy_fee_return.to_numpy() > 0,
        "common_decline": ((df.market_return < 0) & (df.sector_return < 0)).to_numpy(),
        "relative_resilient": (df.stock_return >= df.sector_return).to_numpy(),
    }
    flag["hold_P"] = ~flag["positive_mark"]
    flag["hold_candidate"] = flag["hold_P"] & flag["common_decline"] & flag["relative_resilient"]
    for c, a in flag.items():
        if c in df and not np.array_equal(boolean(df[c]), a):
            raise ValueError(f"Input flag differs from fixed rule: {c}")
        df[c] = a
    if not np.allclose(df.action_delta, df.B_position_return - df.R_position_return,
                       atol=1e-12, rtol=0):
        raise ValueError("Existing label action algebra mismatch")
    df["cluster_id"] = clusters(df)
    df["R"] = df.R_position_return
    df["B"] = df.B_position_return
    df["P"] = np.where(df.hold_P, df.B, df.R)
    df["candidate"] = np.where(df.hold_candidate, df.B, df.R)
    df["candidate_minus_R"] = df.candidate - df.R
    df["candidate_minus_P"] = df.candidate - df.P
    df["event_id"] = np.arange(len(df))
    return df


def stats(x) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {"n": 0, "mean": None, "median": None, "negative_n": 0,
                "negative_mean": None, "q10": None, "worst_10pct_mean": None,
                "min": None, "max": None, "sum": 0.0}
    return {"n": len(x), "mean": float(x.mean()), "median": float(np.median(x)),
            "negative_n": int((x < 0).sum()),
            "negative_mean": float(x[x < 0].mean()) if (x < 0).any() else None,
            "q10": float(np.quantile(x, .1)),
            "worst_10pct_mean": float(np.sort(x)[:int(np.ceil(len(x) * .1))].mean()),
            "min": float(x.min()), "max": float(x.max()), "sum": float(x.sum())}


def action_summary(df: pd.DataFrame) -> dict:
    out = {k: stats(df[k]) for k in ACTIONS}
    for name, baseline, changed in [("candidate_minus_R", "R", df.hold_candidate),
                                    ("candidate_minus_P", "P", df.hold_P != df.hold_candidate)]:
        out[name] = {**stats(df[name]), "action_changed_n": int(changed.sum()),
                     "changed_events": stats(df.loc[changed, name]),
                     "baseline": baseline}
    return out


def raw_contrast(df: pd.DataFrame) -> dict:
    eligible = df[df.hold_P & df.common_decline]
    hi = eligible[eligible.relative_resilient]
    lo = eligible[~eligible.relative_resilient]
    return {"resilient": stats(hi.action_delta), "extra_weak": stats(lo.action_delta),
            "difference": (float(hi.action_delta.mean()-lo.action_delta.mean())
                           if len(hi) and len(lo) else None)}


def weighted_mean(x, w):
    return float(np.average(x, weights=w)) if len(x) and np.sum(w) else None


def common_support(df: pd.DataFrame) -> dict:
    eligible = df[df.hold_P & df.common_decline]
    supported = []
    strata = []
    for (year, remaining), sub in eligible.groupby(["decision_year", "remaining_to_H10_sessions"]):
        a, b = sub[sub.relative_resilient], sub[~sub.relative_resilient]
        weight = min(len(a), len(b))
        row = {"decision_year": int(year), "remaining_sessions": int(remaining),
               "n_resilient": len(a), "n_extra_weak": len(b), "weight": weight,
               "resilient_mean": float(a.action_delta.mean()) if len(a) else None,
               "extra_weak_mean": float(b.action_delta.mean()) if len(b) else None,
               "contrast": float(a.action_delta.mean()-b.action_delta.mean()) if weight else None}
        strata.append(row)
        if weight:
            temp = sub.copy()
            temp["support_weight"] = np.where(temp.relative_resilient, weight / len(a), weight / len(b))
            supported.append(temp)
    supp = pd.concat(supported) if supported else eligible.iloc[:0].assign(support_weight=[])
    a, b = supp[supp.relative_resilient], supp[~supp.relative_resilient]
    contrast = (weighted_mean(a.action_delta, a.support_weight)
                - weighted_mean(b.action_delta, b.support_weight)) if len(supp) else None
    conf = {}
    for c in CONFOUNDERS:
        pop_a, pop_b = eligible[eligible.relative_resilient][c], eligible[~eligible.relative_resilient][c]
        denom = len(pop_a) + len(pop_b) - 2
        pooled = (np.sqrt(((len(pop_a)-1)*pop_a.var(ddof=1)
                          + (len(pop_b)-1)*pop_b.var(ddof=1))/denom)
                  if len(pop_a) > 1 and len(pop_b) > 1 and denom > 0 else np.nan)
        ma, mb = weighted_mean(a[c], a.support_weight), weighted_mean(b[c], b.support_weight)
        conf[c] = {"all_eligible_resilient": stats(pop_a), "all_eligible_extra_weak": stats(pop_b),
                   "supported_resilient": stats(a[c]), "supported_extra_weak": stats(b[c]),
                   "weighted_resilient_mean": ma, "weighted_extra_weak_mean": mb,
                   "full_eligible_pooled_sd": float(pooled) if np.isfinite(pooled) else None,
                   "weighted_standardized_mean_difference": ((ma-mb)/pooled
                       if ma is not None and np.isfinite(pooled) and pooled > 0 else None)}
    inside = set(supp.event_id)
    outside = eligible[~eligible.event_id.isin(inside)]
    return {"eligible_n": len(eligible), "supported_n": len(supp),
            "supported_resilient_n": len(a), "supported_extra_weak_n": len(b),
            "matched_strata_n": len(supported), "total_stratum_weight": sum(s["weight"] for s in strata),
            "weighted_contrast": contrast, "strata": strata,
            "supported_event_ids": sorted(inside), "outside_support_event_ids": list(outside.event_id),
            "outside_support_contrast": raw_contrast(outside), "confounders": conf}


def contrast_contributors(df: pd.DataFrame):
    e = df[df.hold_P & df.common_decline].copy()
    na = int(e.relative_resilient.sum())
    nb = len(e) - na
    if not na or not nb:
        return e.iloc[:0]
    e["contribution"] = np.where(e.relative_resilient, e.action_delta / na, -e.action_delta / nb)
    return e.sort_values("contribution", ascending=False, kind="stable")


def robustness(df: pd.DataFrame) -> dict:
    deletions = {}
    for metric in ["candidate_minus_R", "candidate_minus_P", "raw_contrast"]:
        ranked = (contrast_contributors(df) if metric == "raw_contrast"
                  else df.assign(contribution=df[metric]).sort_values("contribution", ascending=False, kind="stable"))
        ranked = ranked[ranked.contribution > 0]
        items = []
        for k in [1, 3, 5]:
            if len(ranked) < k:
                items.append({"k": k, "available": False, "positive_contributors": len(ranked)})
                continue
            removed = list(ranked.head(k).event_id)
            keep = df[~df.event_id.isin(removed)]
            value = raw_contrast(keep)["difference"] if metric == "raw_contrast" else float(keep[metric].mean())
            items.append({"k": k, "available": True, "removed_event_ids": removed,
                          "remaining_n": len(keep), "value": value})
        deletions[metric] = items
    cluster_rows = []
    loo = []
    for cluster, sub in df.groupby("cluster_id"):
        cluster_rows.append({"cluster_id": int(cluster), "n": len(sub),
                             "candidate_minus_R": float(sub.candidate_minus_R.mean()),
                             "candidate_minus_P": float(sub.candidate_minus_P.mean()),
                             "raw_contrast": raw_contrast(sub)["difference"]})
        rest = df[df.cluster_id != cluster]
        loo.append({"omitted_cluster": int(cluster), "remaining_n": len(rest),
                    "candidate_minus_R": float(rest.candidate_minus_R.mean()) if len(rest) else None,
                    "candidate_minus_P": float(rest.candidate_minus_P.mean()) if len(rest) else None,
                    "raw_contrast": raw_contrast(rest)["difference"]})
    # Equal weight each cluster within each contrast arm; need not contain both arms.
    e = df[df.hold_P & df.common_decline]
    a = e[e.relative_resilient].groupby("cluster_id").action_delta.mean()
    b = e[~e.relative_resilient].groupby("cluster_id").action_delta.mean()
    return {"top_positive_deletions": deletions, "cluster_n": len(cluster_rows),
            "cluster_rows": cluster_rows, "leave_one_cluster_out": loo,
            "cluster_equal": {"candidate_minus_R": float(np.mean([r["candidate_minus_R"] for r in cluster_rows])),
                              "candidate_minus_P": float(np.mean([r["candidate_minus_P"] for r in cluster_rows])),
                              "raw_contrast": float(a.mean()-b.mean()) if len(a) and len(b) else None,
                              "resilient_clusters": len(a), "extra_weak_clusters": len(b)}}


def bootstrap(df: pd.DataFrame, calendar: pd.DataFrame, reps=2000) -> dict:
    date_col = "trade_date" if "trade_date" in calendar else "date"
    cal = pd.DataFrame({"date": pd.to_datetime(calendar[date_col])})
    cal["year"] = cal.date.dt.year
    cal["local_block"] = cal.groupby("year").cumcount() // 20
    blocks = list(cal.groupby(["year", "local_block"], sort=True))
    block_map = {date: i for i, (_, rows) in enumerate(blocks) for date in rows.date}
    event_block = df.decision_date.map(block_map).to_numpy(dtype=int)
    years = {int(y): [i for i, (key, _) in enumerate(blocks) if key[0] == y]
             for y in sorted(cal.year.unique())}
    rng = np.random.default_rng(13)
    names = ["candidate_minus_R", "candidate_minus_P", "raw_contrast"]
    values = {n: [] for n in names}
    invalid = {n: 0 for n in names}
    arm_a = (df.hold_P & df.common_decline & df.relative_resilient).to_numpy()
    arm_b = (df.hold_P & df.common_decline & ~df.relative_resilient).to_numpy()
    delta = df.action_delta.to_numpy()
    for _ in range(reps):
        counts = np.zeros(len(blocks), dtype=int)
        for ids in years.values():
            counts += np.bincount(rng.choice(ids, len(ids), replace=True), minlength=len(blocks))
        weights = counts[event_block]
        for name in names[:2]:
            if weights.sum():
                values[name].append(float(np.average(df[name], weights=weights)))
            else:
                invalid[name] += 1
        if weights[arm_a].sum() and weights[arm_b].sum():
            values["raw_contrast"].append(float(np.average(delta[arm_a], weights=weights[arm_a])
                                               - np.average(delta[arm_b], weights=weights[arm_b])))
        else:
            invalid["raw_contrast"] += 1
    results = {}
    for name, v in values.items():
        results[name] = {"valid": len(v), "invalid": invalid[name],
                         "ordinary_95pct_interval": list(np.quantile(v, [.025, .975])) if v else None,
                         "fraction_above_zero": float(np.mean(np.asarray(v) > 0)) if v else None}
    return {"seed": 13, "repetitions": reps, "block_sessions": 20,
            "calendar_sessions": len(cal), "block_n": len(blocks),
            "zero_event_block_n": len(set(range(len(blocks))) - set(event_block)),
            "year_block_n": {y: len(ids) for y, ids in years.items()}, "results": results,
            "scope": "Ordinary descriptive intervals conditional on saved labels and fixed rule; no history-search or account uncertainty adjustment"}


def analyze(df: pd.DataFrame, calendar: pd.DataFrame) -> dict:
    years = range(2020, 2027)
    return {"units": "decimal net position returns; not account returns or annual acceptance",
            "n": len(df), "positive_mark_n": int(df.positive_mark.sum()),
            "candidate_hold_n": int(df.hold_candidate.sum()),
            "actions": action_summary(df), "raw_contrast": raw_contrast(df),
            "decision_year": {str(y): {"actions": action_summary(df[df.decision_year == y]),
                                       "raw_contrast": raw_contrast(df[df.decision_year == y])} for y in years},
            "entry_year": {str(y): {"actions": action_summary(df[df.entry_year == y]),
                                    "raw_contrast": raw_contrast(df[df.entry_year == y])} for y in years},
            "without_2026_decisions": {"actions": action_summary(df[df.decision_year != 2026]),
                                       "raw_contrast": raw_contrast(df[df.decision_year != 2026]),
                                       "common_support": common_support(df[df.decision_year != 2026])},
            "floating_mark_groups": {str(p): {"actions": action_summary(df[df.positive_mark == p]),
                                               "raw_contrast": raw_contrast(df[df.positive_mark == p])}
                                      for p in [False, True]},
            "nonpositive_2x2": {f"C{int(c)}_R{int(r)}": {
                "action_delta": stats(df.loc[df.hold_P & (df.common_decline == c) & (df.relative_resilient == r), "action_delta"]),
                "actions": action_summary(df[df.hold_P & (df.common_decline == c) & (df.relative_resilient == r)])}
                for c in [False, True] for r in [False, True]},
            "common_support": common_support(df), "robustness": robustness(df),
            "bootstrap": bootstrap(df, calendar),
            "caps_actual": {"upstream_calls": 0, "fits": 0, "new_return_labels": 0, "account_runs": 0, "fixed_rules": 1}}


def synthetic():
    cal = pd.DataFrame({"trade_date": pd.bdate_range("2020-01-01", periods=80)})
    rows = []
    for i, (p, m, s, x, delta, rem) in enumerate([
        (0., -.01, -.02, -.02, .03, 3), (-.02, -.01, -.02, -.03, -.01, 3),
        (.01, -.01, -.02, -.01, .04, 3), (-.01, 0., -.02, -.01, -.02, 3),
        (-.01, -.01, 0., .01, .01, 3), (-.01, -.01, -.02, -.01, .02, 2)]):
        start = i * 10
        rows.append({"entry_date": cal.trade_date.iloc[start], "decision_date": cal.trade_date.iloc[start+2],
                     "R_exit_date": cal.trade_date.iloc[start+3], "B_exit_date": cal.trade_date.iloc[start+6],
                     "close_net_of_buy_fee_return": p, "market_return": m, "sector_return": s,
                     "stock_return": x, "amplitude": .04+i*.01, "remaining_to_H10_sessions": rem,
                     "R_position_return": -.01, "B_position_return": -.01+delta, "action_delta": delta})
    return pd.DataFrame(rows), cal


def precheck():
    checks = []
    def ck(condition, name):
        assert condition, name
        checks.append(name)
    source, cal = synthetic()
    df = prepare(source, cal)
    ck(list(df.hold_P) == [True, True, False, True, True, True], "P zero included")
    ck(list(df.hold_candidate) == [True, False, False, False, False, True], "C strict zeros and R equality")
    ck(np.allclose(df.candidate-df.R, df.hold_candidate*df.action_delta), "candidate vs R action algebra")
    ck(np.allclose(df.candidate-df.P, (df.hold_candidate.astype(int)-df.hold_P.astype(int))*df.action_delta), "candidate vs P action algebra")
    ck(abs(raw_contrast(df)["difference"]-.035) < 1e-12, "raw contrast definition")
    support = common_support(df)
    ck(support["supported_n"] == 2 and support["total_stratum_weight"] == 1, "exact year remaining support")
    ck(abs(support["weighted_contrast"]-.04) < 1e-12, "min count support weighting")
    ck(support["outside_support_event_ids"] == [5], "outside support preserved")
    overlapping = df.iloc[:3].copy()
    overlapping.loc[1, "entry_date"] = overlapping.loc[0, "B_exit_date"]
    overlapping.loc[2, "entry_date"] = overlapping.loc[1, "B_exit_date"]
    ck(list(clusters(overlapping)) == [0, 0, 0], "inclusive transitive clusters")
    changed = source.copy()
    changed.loc[0, "B_exit_date"] = cal.trade_date.iloc[9]
    changed.loc[0, "B_position_return"] += .4
    changed.loc[0, "action_delta"] += .4
    ck(list(prepare(changed, cal).hold_candidate) == list(df.hold_candidate), "future outcomes cannot change action")
    for field, value, name in [("decision_date", pd.Timestamp("2020-01-04"), "off calendar fails"),
                               ("stock_return", np.nan, "missing input fails"),
                               ("action_delta", .9, "label mismatch fails"),
                               ("decision_date", pd.NaT, "missing date fails"),
                               ("remaining_to_H10_sessions", 0, "no horizon left fails")]:
        bad = source.copy()
        bad.loc[0, field] = value
        try:
            prepare(bad, cal)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)
    bad = source.copy()
    bad["hold_candidate"] = False
    try:
        prepare(bad, cal)
    except ValueError:
        checks.append("precomputed flags must match")
    else:
        raise AssertionError("flag mismatch accepted")
    sm = action_summary(df)
    ck(sm["candidate_minus_R"]["action_changed_n"] == 2, "change counts reflect actions")
    ck(sm["candidate_minus_R"]["n"] == 6, "all-event effect denominator")
    boot = bootstrap(df, cal, reps=40)
    ck(boot == bootstrap(df, cal, reps=40), "seed determinism")
    ck(boot["block_n"] == 4 and boot["zero_event_block_n"] == 1, "zero event calendar block retained")
    ck(all(v["valid"]+v["invalid"] == 40 for v in boot["results"].values()), "invalid draws counted no replacement")
    rob = robustness(df)
    ck(rob["top_positive_deletions"]["candidate_minus_R"][1]["available"] is False, "insufficient favorable deletion unavailable")
    ck(stats([])["mean"] is None, "empty groups explicit")
    return {"status": "PASS", "synthetic_only": True, "checks": checks, "check_n": len(checks)}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["precheck", "run"])
    args = parser.parse_args()
    out = ROOT / "others"
    out.mkdir(parents=True, exist_ok=True)
    if args.mode == "precheck":
        result = precheck()
        write_json(out / "analysis_precheck.json", result)
        print(json.dumps(result))
        return
    destination = out / "analysis.json"
    if destination.exists():
        raise FileExistsError("Preserve existing analysis; explicit correction identity required")
    result_check = precheck()
    if result_check["status"] != "PASS":
        raise AssertionError("Synthetic precheck failed")
    events_path, cal_path = out / "events.csv", out / "calendar.csv"
    source = pd.read_csv(events_path)
    cal = pd.read_csv(cal_path)
    df = prepare(source, cal)
    if len(df) != 100 or len(cal) != 1642 or int(df.positive_mark.sum()) != 15:
        raise ValueError("Input inventory differs from locked design")
    result = analyze(df, cal)
    result["input_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [events_path, cal_path]}
    result["analysis_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write_json(destination, result)
    df.to_csv(out / "action_results.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame(result["common_support"]["strata"]).to_csv(out / "common_support_strata.csv", index=False)
    pd.DataFrame(result["robustness"]["leave_one_cluster_out"]).to_csv(out / "leave_one_cluster_out.csv", index=False)
    print(json.dumps({"status": "COMPLETE", "n": len(df), "candidate_hold_n": result["candidate_hold_n"],
                      "analysis_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
