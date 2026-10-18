"""Fixed-score offline EX031 diagnostics; no fits, accounts or network calls.

Uncertainty is conditional on the twelve supplied fitted score series. Calendar
resampling retains empty days, recomputes parent/group denominators, and uses
year-stratified, nonoverlapping blocks (including the short final block).
"""

from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

EX = Path(__file__).resolve().parents[1]
MODELS = ("B", "Bz", "Bold")
YEARS = (2023, 2024, 2025, 2026)
SEED = 13
REPLICATES = 2000


def boolean(series, name):
    mapping = {
        True: True,
        False: False,
        1: True,
        0: False,
        "True": True,
        "False": False,
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        1.0: True,
        0.0: False,
    }
    out = series.map(mapping)
    if out.isna().any():
        raise ValueError(f"{name}: missing or invalid boolean")
    return out.astype(bool)


def number(value):
    return None if pd.isna(value) else float(value)


def mean(values, weights):
    denom = float(np.sum(weights))
    return None if denom <= 0 else float(np.dot(values, weights) / denom)


def subtract(a, b):
    return None if a is None or b is None else float(a - b)


def distribution(values):
    v = np.asarray(values, dtype=float)
    if not len(v):
        return dict(
            n=0,
            mean=None,
            median=None,
            q10=None,
            positive_contribution=None,
            negative_contribution=None,
        )
    return dict(
        n=len(v),
        mean=float(v.mean()),
        median=float(np.median(v)),
        q10=float(np.quantile(v, 0.1)),
        positive_contribution=float(np.maximum(v, 0).mean()),
        negative_contribution=float(np.minimum(v, 0).mean()),
    )


def describe(frame, target="Y3", weights=None, residual_baseline=True):
    """All rows must be the common parent population, including unfilled zeros."""
    f = frame
    n = len(f)
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    assert len(w) == n and np.isfinite(w).all() and (w >= 0).all()
    y = f[target].to_numpy(dtype=float)
    assert np.isfinite(y).all()
    z = f.z.to_numpy(dtype=bool)
    residual = y - f.score_B.to_numpy(dtype=float) if residual_baseline else y
    delta = y * (f.sel_Bz.to_numpy(dtype=int) - f.sel_B.to_numpy(dtype=int))
    out = dict(
        n=n,
        parent_weight=float(w.sum()),
        target=target,
        entry_filled=int(f.entry_filled.sum()),
        entry_unfilled=int((~f.entry_filled).sum()),
        parent=distribution(y),
        weighted_parent_mean=mean(y, w),
        groups={},
        models={},
        comparisons={},
    )
    for label, mask in [("up", z), ("not_up", ~z)]:
        out["groups"][label] = dict(
            raw=distribution(y[mask]),
            weight=float(w[mask].sum()),
            weighted_raw_mean=mean(y[mask], w[mask]),
            residual_mean=mean(residual[mask], w[mask]),
        )
    out["raw_group_difference"] = subtract(
        out["groups"]["up"]["weighted_raw_mean"], out["groups"]["not_up"]["weighted_raw_mean"]
    )
    out["D1"] = subtract(
        out["groups"]["up"]["residual_mean"], out["groups"]["not_up"]["residual_mean"]
    )
    out["D2"] = mean(delta, w)
    out["D1_status"] = "AVAILABLE" if out["D1"] is not None else "MISSING_GROUP"
    out["D2_status"] = "AVAILABLE" if n and w.sum() > 0 else "NO_PARENT"
    for model in MODELS:
        selected = f["sel_" + model].to_numpy(dtype=bool)
        allocation = mean(y * selected, w)
        out["models"][model] = dict(
            selected_count=int(selected.sum()),
            selection_rate=None if not n else float(selected.mean()),
            selected_weight=float(w[selected].sum()),
            selected_return=distribution(y[selected]),
            weighted_selected_mean=mean(y[selected], w[selected]),
            allocation_per_parent=allocation,
            allocation_minus_all_parent=subtract(allocation, out["weighted_parent_mean"]),
        )
    for new, base in [("Bz", "B"), ("Bold", "B"), ("Bz", "Bold")]:
        ns = f["sel_" + new].to_numpy(dtype=bool)
        bs = f["sel_" + base].to_numpy(dtype=bool)
        groups = {}
        for label, mask in [
            ("both", ns & bs),
            ("added", ns & ~bs),
            ("removed", ~ns & bs),
            ("neither", ~ns & ~bs),
        ]:
            contribution = y * (ns.astype(int) - bs.astype(int))
            groups[label] = dict(
                n=int(mask.sum()),
                weight=float(w[mask].sum()),
                returns=distribution(y[mask]),
                parent_return_contribution=mean(y * mask, w),
                new_allocation_contribution=mean(y * mask * ns, w),
                base_allocation_contribution=mean(y * mask * bs, w),
                difference_contribution=mean(contribution * mask, w),
            )
        out["comparisons"][new + "_minus_" + base] = dict(
            allocation_difference=mean(y * (ns.astype(int) - bs.astype(int)), w), groups=groups
        )
    return out


def main_metrics(frame, weights=None):
    if weights is None:
        weights = np.ones(len(frame))
    w = np.asarray(weights, float)
    y = frame.Y3.to_numpy(float)
    z = frame.z.to_numpy(bool)
    r = y - frame.score_B.to_numpy(float)
    return dict(
        D1=subtract(mean(r[z], w[z]), mean(r[~z], w[~z])),
        D2=mean(y * (frame.sel_Bz.to_numpy(int) - frame.sel_B.to_numpy(int)), w),
        n=len(frame),
        parent_weight=float(w.sum()),
        up_n=int(z.sum()),
        not_up_n=int((~z).sum()),
    )


def holding_diagnostics(frame):
    """Connected components use realised inclusive entry-to-maturity intervals."""
    f = frame.copy()
    cluster = {}
    c = 0
    end = None
    filled = f[f.entry_filled].sort_values(
        ["entry_index", "maturity_index", "signal"], kind="stable"
    )
    for r in filled.itertuples():
        if end is None or r.entry_index > end:
            c += 1
            end = r.maturity_index
        else:
            end = max(end, r.maturity_index)
        cluster[r.signal] = c
    # An unfilled attempt has no holding interval: retain its zero return as its
    # own unit, rather than deleting it or artificially connecting two holdings.
    for r in f[~f.entry_filled].sort_values("signal").itertuples():
        c += 1
        cluster[r.signal] = c
    f["cluster"] = f.signal.map(cluster).astype(int)
    sizes = f.groupby("cluster").size()
    weights = 1.0 / f.cluster.map(sizes).to_numpy(float)
    omissions = []
    clusters = []
    for key, group in f.groupby("cluster", sort=True):
        clusters.append(
            dict(
                cluster=int(key),
                signals=group.signal.astype(int).tolist(),
                metrics=main_metrics(group),
            )
        )
        omissions.append(
            dict(
                omitted_cluster=int(key),
                omitted_n=len(group),
                metrics=main_metrics(f[f.cluster != key]),
            )
        )
    chosen = []
    last_end = -np.inf
    for r in f.sort_values("signal", kind="stable").itertuples():
        if not r.entry_filled:
            chosen.append(r.signal)
        elif r.entry_index > last_end:
            chosen.append(r.signal)
            last_end = r.maturity_index
    dedup = f[f.signal.isin(chosen)]
    return dict(
        cluster_count=len(sizes),
        cluster_sizes={str(k): int(v) for k, v in sizes.items()},
        equal_cluster=describe(f, weights=weights),
        clusters=clusters,
        leave_one_cluster_out=omissions,
        chronological_deduplicated=describe(dedup),
        chronological_signals=dedup.signal.astype(int).tolist(),
        rule="Actual filled entry/maturity intervals form inclusive overlap components; unfilled zero-return attempts are separate units. Cluster weights=1/cluster size; within-group D1 denominators recomputed. Chronological actual-interval dedup is retrospective, not a tradable schedule or frequency claim.",
    )


def trim_favorable(frame):
    """Separate fixed diagnostic for each main statistic; never select a winner."""
    out = {}
    y = frame.Y3.to_numpy(float)
    z = frame.z.to_numpy(bool)
    residual = y - frame.score_B.to_numpy(float)
    d1 = np.zeros(len(frame))
    if z.any():
        d1[z] = residual[z] / z.sum()
    if (~z).any():
        d1[~z] = -residual[~z] / (~z).sum()
    contributions = {"D1": d1, "D2": y * (frame.sel_Bz.to_numpy(int) - frame.sel_B.to_numpy(int))}
    for key, contribution in contributions.items():
        ranked = frame.assign(contribution=contribution)
        dropped = []
        for _, group in ranked.groupby("year", sort=True):
            # Fixed removal of the three largest signed contributions per year,
            # even where the third is zero/negative. Ties resolved by date.
            top = group.sort_values(
                ["contribution", "signal"], ascending=[False, True], kind="stable"
            ).head(3)
            dropped.extend(top.signal.astype(int).tolist())
        remainder = frame[~frame.signal.isin(dropped)]
        out[key] = dict(
            removed_signals=dropped,
            removed_n=len(dropped),
            metrics=main_metrics(remainder),
            description="Each year removes three largest signed contributions for this statistic, then all denominators are recomputed; diagnostic only.",
        )
    return out


def bootstrap(frame, calendar, block_length, replicates=REPLICATES):
    """Joint resampling of calendar blocks within year, preserving empty days."""
    cal = calendar[calendar.year.isin(YEARS)].sort_values("signal").copy()
    assert cal.signal.is_unique
    mapping = {int(v): i for i, v in enumerate(cal.signal)}
    if not set(frame.signal).issubset(mapping):
        raise ValueError("Parent signal absent from full evaluation calendar")
    daily = np.zeros((len(cal), 6), float)
    y = frame.Y3.to_numpy(float)
    z = frame.z.to_numpy(bool)
    residual = y - frame.score_B.to_numpy(float)
    delta = y * (frame.sel_Bz.to_numpy(int) - frame.sel_B.to_numpy(int))
    for j, signal in enumerate(frame.signal):
        daily[mapping[int(signal)]] = (
            1,
            z[j],
            not z[j],
            residual[j] if z[j] else 0,
            residual[j] if not z[j] else 0,
            delta[j],
        )
    rng = np.random.default_rng(SEED)
    aggregates = np.zeros((replicates, 6))
    year_blocks = []
    for year in YEARS:
        indices = np.flatnonzero(cal.year.to_numpy() == year)
        if not len(indices):
            raise ValueError(f"Missing calendar year {year}")
        blocks = [
            daily[indices[i : i + block_length]].sum(axis=0)
            for i in range(0, len(indices), block_length)
        ]
        sums = np.asarray(blocks)
        draws = rng.integers(0, len(blocks), (replicates, len(blocks)))
        aggregates += sums[draws].sum(axis=1)
        year_blocks.append(
            dict(
                year=year,
                calendar_days=len(indices),
                blocks=len(blocks),
                last_block_days=len(indices) % block_length or block_length,
                empty_nonparent_days=int((daily[indices, 0] == 0).sum()),
            )
        )
    d1_valid = (aggregates[:, 1] > 0) & (aggregates[:, 2] > 0)
    d2_valid = aggregates[:, 0] > 0
    joint = d1_valid & d2_valid
    draws = np.full((replicates, 2), np.nan)
    draws[d1_valid, 0] = (
        aggregates[d1_valid, 3] / aggregates[d1_valid, 1]
        - aggregates[d1_valid, 4] / aggregates[d1_valid, 2]
    )
    draws[d2_valid, 1] = aggregates[d2_valid, 5] / aggregates[d2_valid, 0]
    result = dict(
        block_length=block_length,
        replicates=replicates,
        seed=SEED,
        calendar_days=len(cal),
        parent_days=len(frame),
        year_blocks=year_blocks,
        failed_missing_z_group=int((~d1_valid).sum()),
        failed_no_parent=int((~d2_valid).sum()),
        jointly_valid=int(joint.sum()),
        jointly_invalid=int((~joint).sum()),
        ordinary_95={},
        simultaneous_two_main_95={},
        method="Nonoverlapping calendar blocks, sampled with replacement separately within each year; the short final block is a block. Number of blocks sampled per year equals observed blocks. Empty days retained; group and parent denominators recomputed. Ordinary percentile95 uses available statistic replicates; simultaneous Bonferroni percentile intervals use joint-valid replicates at1.25/98.75 percentiles (97.5% marginal each). No refits, training uncertainty or selection adjustment.",
    )
    estimates = main_metrics(frame)
    for j, key in enumerate(("D1", "D2")):
        values = draws[np.isfinite(draws[:, j]), j]
        shared = draws[joint, j]
        result["ordinary_95"][key] = dict(
            estimate=estimates[key],
            valid=len(values),
            low=None if not len(values) else float(np.quantile(values, 0.025)),
            high=None if not len(values) else float(np.quantile(values, 0.975)),
        )
        result["simultaneous_two_main_95"][key] = dict(
            estimate=estimates[key],
            valid=len(shared),
            low=None if not len(shared) else float(np.quantile(shared, 0.0125)),
            high=None if not len(shared) else float(np.quantile(shared, 0.9875)),
        )
    return result


def temporal_index(series, calendar, name, allow_missing=False):
    numeric = pd.to_numeric(series, errors="coerce")
    nonmissing = series.notna()
    if numeric[nonmissing].notna().all():
        values = numeric
    else:
        dates = pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")
        values = dates.map(dict(zip(calendar.date, calendar.signal)))
    if not allow_missing and values.isna().any():
        raise ValueError(f"{name}: missing or outside calendar")
    if not values.dropna().isin(calendar.signal).all():
        raise ValueError(f"{name}: date index outside calendar")
    return values


def raw_descriptive():
    """Full-period raw labels are not mixed into conditional 2023+ comparisons."""
    path = EX / "others/descriptive.csv"
    q = pd.read_csv(path)
    assert q.signal.is_unique
    for key in ("A", "z", "roll", "entry_filled"):
        q[key] = boolean(q[key], key)
    assert q.A.all() and q.year.between(2020, 2026).all()
    assert np.isfinite(q.Y3).all()

    def group_stats(f, target="Y3"):
        f = f[f[target].notna()]
        up, down = f[f.z], f[~f.z]
        a, b = distribution(up[target]), distribution(down[target])
        return dict(
            n=len(f),
            entry_unfilled=int((~f.entry_filled).sum()),
            parent=distribution(f[target]),
            up=a,
            not_up=b,
            raw_difference=subtract(a["mean"], b["mean"]),
        )

    years = {str(y): group_stats(q[q.year == y]) for y in range(2020, 2027)}
    return dict(
        status="COMPLETE",
        full_H3=group_stats(q),
        annual=years,
        before_2023=group_stats(q[q.year < 2023]),
        through_2025=group_stats(q[q.year <= 2025]),
        H1_among_H3_mature=group_stats(q, "Y1"),
        note="Full-period parent opportunities with valid methanol and mature H3 labels; 2020-2022 are raw descriptions only. H1 independent full-maturity inventory is delivered separately by root; this file alone cannot reconstruct H1-only signals.",
    )


def load_inputs():
    p = pd.read_csv(EX / "others/predictions.csv")
    c = pd.read_csv(EX / "others/calendar.csv")
    required = {
        "signal",
        "date",
        "year",
        "A",
        "z",
        "z_old5",
        "roll",
        "environment",
        "Y3",
        "Y1",
        "maturity",
        "entry",
        "entry_filled",
    }
    required |= {"score_" + m for m in MODELS} | {"sel_" + m for m in MODELS}
    if not required.issubset(p.columns):
        raise ValueError(f"Missing prediction columns {sorted(required - set(p.columns))}")
    for f in (p, c):
        f["date"] = pd.to_datetime(f.date).dt.strftime("%Y-%m-%d")
        f["signal"] = pd.to_numeric(f.signal, errors="raise").astype(int)
        f["year"] = pd.to_numeric(f.year, errors="raise").astype(int)
        assert f.signal.is_unique and f.date.is_unique
        assert (pd.to_datetime(f.date).dt.year == f.year).all()
    p = p.sort_values("signal").reset_index(drop=True)
    c = c.sort_values("signal").reset_index(drop=True)
    assert p.year.isin(YEARS).all()
    assert c.date.is_monotonic_increasing and p.date.is_monotonic_increasing
    lookup = c.set_index("signal")
    assert set(p.signal).issubset(lookup.index)
    assert p.date.tolist() == lookup.loc[p.signal, "date"].tolist()
    for key in ("A", "z", "z_old5", "roll", "entry_filled", *("sel_" + m for m in MODELS)):
        p[key] = boolean(p[key], key)
    assert p.environment.isin(["high", "low", "unready"]).all()
    for key in ("Y3", "Y1", *("score_" + m for m in MODELS)):
        p[key] = pd.to_numeric(p[key], errors="raise")
        if key != "Y1":
            assert np.isfinite(p[key]).all(), key
        else:
            assert np.isfinite(p[key].dropna()).all(), key
    p["entry_index"] = temporal_index(p.entry, c, "entry", allow_missing=True)
    p["maturity_index"] = temporal_index(p.maturity, c, "maturity")
    assert p.loc[p.entry_filled, "entry_index"].notna().all()
    assert (p.loc[p.entry_filled, "entry_index"] > p.loc[p.entry_filled, "signal"]).all()
    assert (p.loc[p.entry_filled, "maturity_index"] >= p.loc[p.entry_filled, "entry_index"]).all()
    assert (p.loc[~p.entry_filled, "Y3"] == 0).all()
    assert (p.loc[~p.entry_filled & p.Y1.notna(), "Y1"] == 0).all()
    return p, c


def selfcheck():
    f = pd.DataFrame(
        dict(
            signal=[1, 2, 3, 4],
            year=[2023] * 4,
            z=[True, False, True, False],
            Y3=[0.1, -0.1, 0.2, 0.0],
            Y1=[0.02, -0.02, 0.04, 0.0],
            score_B=[0.01] * 4,
            score_Bz=[0.02] * 4,
            score_Bold=[0.03] * 4,
            sel_B=[True, True, False, False],
            sel_Bz=[True, False, True, False],
            sel_Bold=[False, True, True, False],
            entry_filled=[True, True, True, False],
            entry_index=[2, 3, 8, np.nan],
            maturity_index=[5, 6, 10, 5],
        )
    )
    checks = 0
    r = describe(f)
    assert np.isclose(r["D1"], 0.2) and np.isclose(r["D2"], 0.075)
    checks += 2
    assert np.isclose(r["models"]["Bz"]["allocation_per_parent"], 0.075)
    checks += 1
    assert np.isclose(
        sum(
            v["difference_contribution"] for v in r["comparisons"]["Bz_minus_B"]["groups"].values()
        ),
        r["D2"],
    )
    checks += 1
    assert describe(f[f.z])["D1"] is None
    checks += 1
    assert describe(f.iloc[:0])["D2"] is None
    checks += 1
    h = holding_diagnostics(f)
    assert h["cluster_count"] == 3 and h["chronological_signals"] == [1, 3, 4]
    checks += 2
    assert np.isclose(h["equal_cluster"]["parent_weight"], 3)
    checks += 1
    t = trim_favorable(f)
    assert t["D2"]["removed_n"] == 3
    checks += 1
    c = pd.DataFrame(
        [
            dict(signal=y * 100 + i, date=f"{y}-01-{i + 1:02d}", year=y)
            for y in YEARS
            for i in range(25)
        ]
    )
    g = pd.concat([f.assign(signal=[y * 100 + i for i in (1, 2, 3, 4)], year=y) for y in YEARS])
    b = bootstrap(g, c, 20, replicates=50)
    assert b["calendar_days"] == 100 and b["parent_days"] == 16
    checks += 2
    assert b["jointly_valid"] + b["jointly_invalid"] == 50
    checks += 1
    assert sum(v["empty_nonparent_days"] for v in b["year_blocks"]) == 84
    checks += 1
    all_up = bootstrap(g[g.z], c, 20, replicates=50)
    assert all_up["jointly_valid"] == 0 and all_up["ordinary_95"]["D1"]["low"] is None
    checks += 2
    assert all_up["ordinary_95"]["D2"]["valid"] > 0
    checks += 1
    assert boolean(pd.Series(["False", "True", 0, 1]), "test").tolist() == [
        False,
        True,
        False,
        True,
    ]
    checks += 1
    return dict(status="PASS", checks=checks, fits=0, accounts=0, source_calls=0)


def main():
    if "--selfcheck" in sys.argv:
        print(json.dumps(selfcheck()))
        return
    if (EX / "others/analysis.json").exists():
        raise RuntimeError("Preserve completed analysis")
    tests = selfcheck()
    p, calendar = load_inputs()
    f = p[p.A].copy()
    annual = {str(year): describe(f[f.year == year]) for year in YEARS}
    h1 = f[f.Y1.notna()].copy()
    paired_h3, paired_h1 = describe(h1), describe(h1, target="Y1")
    h1["Y_delta"] = h1.Y3 - h1.Y1
    duration = dict(
        common_n=len(h1),
        H3_mature_n=len(f),
        H3_only_n=len(f) - len(h1),
        H1_full_mature_population="Not reconstructable from H3-mature prediction rows; separate root label-identity inventory required.",
        H3_on_common=paired_h3,
        H1_on_common=paired_h1,
        H3_minus_H1=describe(h1, target="Y_delta", residual_baseline=False),
        D1_H3_minus_H1=subtract(paired_h3["D1"], paired_h1["D1"]),
        D2_H3_minus_H1=subtract(paired_h3["D2"], paired_h1["D2"]),
        note="H1 uses the same fixed H3 scores and masks, no H1 fit. H1 residual D1 subtracts the fixed H3 baseline score; paired D1 differences cancel that baseline. Delta target is not a separately fitted forecast.",
    )
    result = dict(
        status="COMPLETE",
        selfcheck=tests,
        signal_count=len(p),
        parent_count=len(f),
        main=describe(f),
        annual=annual,
        through_2025=describe(f[f.year <= 2025]),
        leave_one_year_out={str(y): describe(f[f.year != y]) for y in YEARS},
        exclude_roll=describe(f[~f.roll]),
        roll_only=describe(f[f.roll]),
        environment={e: describe(f[f.environment == e]) for e in ("high", "low", "unready")},
        duration=duration,
        holding=holding_diagnostics(f),
        favorable_trimming=trim_favorable(f),
        bootstrap={str(k): bootstrap(f, calendar, k) for k in (20, 60)},
        fits=0,
        accounts=0,
        source_calls=0,
        full_period_raw=raw_descriptive(),
        limits=[
            "All previously seen development data; component labels are overlapping attempts, not investable account returns.",
            "Intervals condition on supplied fitted scores, not training uncertainty; Bonferroni bootstrap intervals do not correct historical model/feature selection.",
            "D1 is conditional association with the fixed baseline, not a causal commodity effect.",
            "D2 recomputes allocation per all parent opportunities, including unfilled zero returns and unselected opportunities.",
            "Realised-interval clustering and chronological dedup use future exits for diagnosis only, never a deployable scheduling or frequency claim.",
        ],
    )
    paths = [
        Path(__file__),
        EX / "others/predictions.csv",
        EX / "others/calendar.csv",
        EX / "others/descriptive.csv",
        EX / "protocols/approved_proposal.md",
    ]
    root = EX.parents[3]
    result["source_sha256"] = {
        q.relative_to(root).as_posix(): sha256(q.read_bytes()).hexdigest() for q in paths
    }
    annual_rows = []
    for year, r in annual.items():
        annual_rows.append(
            dict(
                year=int(year),
                n=r["n"],
                up_n=r["groups"]["up"]["raw"]["n"],
                not_up_n=r["groups"]["not_up"]["raw"]["n"],
                raw_difference=r["raw_group_difference"],
                D1=r["D1"],
                D2=r["D2"],
                parent_mean=r["parent"]["mean"],
                **{f"{m}_selected": r["models"][m]["selected_count"] for m in MODELS},
                **{f"{m}_allocation": r["models"][m]["allocation_per_parent"] for m in MODELS},
            )
        )
    output = EX / "others/annual.csv"
    output.write_text(
        pd.DataFrame(annual_rows).to_csv(index=False, lineterminator="\n"),
        encoding="utf-8",
        newline="\n",
    )
    result["annual_sha256"] = sha256(output.read_bytes()).hexdigest()
    (EX / "others/analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "parent_count": len(f),
                "D1": result["main"]["D1"],
                "D2": result["main"]["D2"],
                "fits": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
