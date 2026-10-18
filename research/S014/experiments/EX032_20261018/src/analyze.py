"""EX032 fixed interaction diagnostics: supplied scores, no fits or new labels.

Returns and differences use decimal return units, not percentage points. All
attempts, including unfilled zero returns, remain in parent denominators.
"""

from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

EX = Path(__file__).resolve().parents[1]
MODELS = ("M0", "M1", "M2")
YEARS = (2023, 2024, 2025, 2026)
METRICS = ("D", "D_residual_M1", "allocation_M2_minus_M1", "allocation_M1_minus_M0")
CELLS = ((1, 1, 1), (0, 1, -1), (1, 0, -1), (0, 0, 1))
SEED = 13
REPLICATES = 2000


def boolean(series, name, allow_missing=False):
    out = (
        series.astype("string")
        .str.lower()
        .map({"true": True, "false": False, "1": True, "0": False, "1.0": True, "0.0": False})
    )
    if (series.notna() & out.isna()).any() or (not allow_missing and out.isna().any()):
        raise ValueError(f"{name}: missing or invalid boolean")
    return out.astype("boolean") if allow_missing else out.astype(bool)


def mean(values, weights):
    denom = float(np.sum(weights))
    return None if denom <= 0 else float(np.dot(values, weights) / denom)


def subtract(a, b):
    return None if a is None or b is None else float(a - b)


def distribution(values):
    v = np.asarray(values, dtype=float)
    return dict(
        n=len(v),
        mean=None if not len(v) else float(v.mean()),
        median=None if not len(v) else float(np.median(v)),
        q10=None if not len(v) else float(np.quantile(v, 0.1)),
        positive_contribution=None if not len(v) else float(np.maximum(v, 0).mean()),
        negative_contribution=None if not len(v) else float(np.minimum(v, 0).mean()),
    )


def four_cells(frame, target="Y3", weights=None, z_column="z", residual=True):
    w = np.ones(len(frame)) if weights is None else np.asarray(weights, float)
    y = frame[target].to_numpy(float)
    z = frame[z_column].to_numpy(bool)
    s = frame.S.to_numpy(bool)
    r = y - frame.score_M1.to_numpy(float) if residual else y
    cells = {}
    for zv, sv, _ in CELLS:
        mask = (z == zv) & (s == sv)
        cells[f"z{zv}_S{sv}"] = dict(
            n=int(mask.sum()),
            weight=float(w[mask].sum()),
            entry_unfilled=int((~frame.entry_filled.to_numpy(bool)[mask]).sum()),
            raw=distribution(y[mask]),
            weighted_mean=mean(y[mask], w[mask]),
            residual_mean=mean(r[mask], w[mask]),
            allocation_per_all_parent=mean(y * mask, w),
        )
    complete = all(c["weight"] > 0 for c in cells.values())
    d = (
        sum(sign * cells[f"z{zv}_S{sv}"]["weighted_mean"] for zv, sv, sign in CELLS)
        if complete
        else None
    )
    dr = (
        sum(sign * cells[f"z{zv}_S{sv}"]["residual_mean"] for zv, sv, sign in CELLS)
        if complete
        else None
    )
    return dict(
        n=len(frame),
        cells=cells,
        D=d,
        D_residual_M1=dr,
        status="AVAILABLE" if complete else "MISSING_CELL",
        missing_cells=[k for k, v in cells.items() if v["weight"] <= 0],
        z_effect_S1=subtract(cells["z1_S1"]["weighted_mean"], cells["z0_S1"]["weighted_mean"]),
        z_effect_S0=subtract(cells["z1_S0"]["weighted_mean"], cells["z0_S0"]["weighted_mean"]),
    )


def main_metrics(frame, weights=None, target="Y3", residual=True):
    w = np.ones(len(frame)) if weights is None else np.asarray(weights, float)
    cells = four_cells(frame, target, w, residual=residual)
    y = frame[target].to_numpy(float)
    out = dict(
        n=len(frame),
        parent_weight=float(w.sum()),
        D=cells["D"],
        D_residual_M1=cells["D_residual_M1"],
        missing_cells=cells["missing_cells"],
    )
    for new, base in (("M2", "M1"), ("M1", "M0")):
        out[f"allocation_{new}_minus_{base}"] = mean(
            y * (frame[f"sel_{new}"].to_numpy(int) - frame[f"sel_{base}"].to_numpy(int)), w
        )
    return out


def describe(frame, target="Y3", weights=None, residual=True):
    f = frame
    w = np.ones(len(f)) if weights is None else np.asarray(weights, float)
    assert len(w) == len(f) and np.isfinite(w).all() and (w >= 0).all()
    y = f[target].to_numpy(float)
    assert np.isfinite(y).all()
    z, s = f.z.to_numpy(bool), f.S.to_numpy(bool)
    out = main_metrics(f, w, target, residual)
    out.update(
        target=target,
        entry_filled=int(f.entry_filled.sum()),
        entry_unfilled=int((~f.entry_filled).sum()),
        parent=distribution(y),
        weighted_parent_mean=mean(y, w),
        four_cells=four_cells(f, target, w, residual=residual),
        participation={},
        comparisons={},
        stock_state_groups={},
    )
    masks = {m: f[f"sel_{m}"].to_numpy(bool) for m in MODELS}
    masks.update(all_parent=np.ones(len(f), bool), simple_z1_S1=z & s, stock_S1=s)
    for name, selected in masks.items():
        out["participation"][name] = dict(
            selected_count=int(selected.sum()),
            selected_weight=float(w[selected].sum()),
            selected_returns=distribution(y[selected]),
            weighted_selected_mean=mean(y[selected], w[selected]),
            allocation_per_parent=mean(y * selected, w),
            allocation_minus_all=subtract(mean(y * selected, w), mean(y, w)),
            unselected_return_contribution=mean(y * ~selected, w),
        )
    for sv in (0, 1):
        mask = s == sv
        out["stock_state_groups"][f"S{sv}"] = dict(
            raw=distribution(y[mask]),
            weighted_mean=mean(y[mask], w[mask]),
            z1_minus_all_within_S=subtract(mean(y[mask & z], w[mask & z]), mean(y[mask], w[mask])),
            simple_z1_allocation_within_S=mean((y * z)[mask], w[mask]),
            simple_minus_all_allocation_within_S=subtract(
                mean((y * z)[mask], w[mask]), mean(y[mask], w[mask])
            ),
        )
    for new, base in (("M2", "M1"), ("M1", "M0"), ("M2", "simple_z1_S1")):
        ns, bs = masks[new], masks[base]
        delta = y * (ns.astype(int) - bs.astype(int))
        parts = {}
        for label, mask in (
            ("both", ns & bs),
            ("added", ns & ~bs),
            ("removed", ~ns & bs),
            ("neither", ~ns & ~bs),
        ):
            parts[label] = dict(
                n=int(mask.sum()),
                returns=distribution(y[mask]),
                difference_contribution=mean(delta * mask, w),
                new_contribution=mean(y * ns * mask, w),
                base_contribution=mean(y * bs * mask, w),
                signals=f.loc[mask, "signal"].astype(int).tolist(),
            )
        out["comparisons"][f"{new}_minus_{base}"] = dict(
            allocation_difference=mean(delta, w), groups=parts
        )
    out["cell_model_allocations"] = {}
    for zv, sv, _ in CELLS:
        mask = (z == zv) & (s == sv)
        out["cell_model_allocations"][f"z{zv}_S{sv}"] = {
            name: dict(
                selected_n=int((mask & selected).sum()),
                selected_mean=mean(y[mask & selected], w[mask & selected]),
                allocation_within_cell=mean((y * selected)[mask], w[mask]),
                allocation_per_all_parent=mean(y * selected * mask, w),
            )
            for name, selected in masks.items()
        }
    return out


def holding_diagnostics(frame):
    f = frame.copy()
    cluster, c, end = {}, 0, None
    for r in (
        f[f.entry_filled]
        .sort_values(["entry_index", "maturity_index", "signal"], kind="stable")
        .itertuples()
    ):
        if end is None or r.entry_index > end:
            c += 1
            end = r.maturity_index
        else:
            end = max(end, r.maturity_index)
        cluster[r.signal] = c
    for r in f[~f.entry_filled].sort_values("signal").itertuples():
        c += 1
        cluster[r.signal] = c
    f["cluster"] = f.signal.map(cluster).astype(int)
    sizes = f.groupby("cluster").size()
    weights = 1 / f.cluster.map(sizes).to_numpy(float)
    chosen, last_end = [], -np.inf
    for r in f.sort_values("signal", kind="stable").itertuples():
        if not r.entry_filled:
            chosen.append(r.signal)
        elif r.entry_index > last_end:
            chosen.append(r.signal)
            last_end = r.maturity_index
    return dict(
        cluster_count=len(sizes),
        cluster_sizes={str(k): int(v) for k, v in sizes.items()},
        clusters=[
            dict(cluster=int(k), signals=g.signal.astype(int).tolist(), metrics=main_metrics(g))
            for k, g in f.groupby("cluster")
        ],
        equal_cluster=describe(f, weights=weights),
        leave_one_cluster_out=[
            dict(omitted_cluster=int(k), omitted_n=int(n), metrics=main_metrics(f[f.cluster != k]))
            for k, n in sizes.items()
        ],
        chronological_signals=chosen,
        chronological_deduplicated=describe(f[f.signal.isin(chosen)]),
        rule="Inclusive realised entry/maturity connected components; unfilled zero attempts are singleton units. Equal-cluster row weight=1/cluster size, group denominators recomputed. Dedup uses realised future exits, is diagnostic only, not a tradable schedule or frequency capacity proof.",
    )


def trim_favorable(frame):
    y = frame.Y3.to_numpy(float)
    r = y - frame.score_M1.to_numpy(float)
    z, s = frame.z.to_numpy(bool), frame.S.to_numpy(bool)
    contributions = {k: np.zeros(len(frame)) for k in METRICS[:2]}
    for zv, sv, sign in CELLS:
        mask = (z == zv) & (s == sv)
        if mask.any():
            contributions["D"][mask] = sign * y[mask] / mask.sum()
            contributions["D_residual_M1"][mask] = sign * r[mask] / mask.sum()
    for new, base in (("M2", "M1"), ("M1", "M0")):
        contributions[f"allocation_{new}_minus_{base}"] = y * (
            frame[f"sel_{new}"].to_numpy(int) - frame[f"sel_{base}"].to_numpy(int)
        )
    out = {}
    for key, values in contributions.items():
        ranked = frame.assign(contribution=values)
        out[key] = {}
        for scope in ("global", "each_year"):
            out[key][scope] = {}
            for count in (1, 3, 5):
                groups = (
                    [ranked]
                    if scope == "global"
                    else [g for _, g in ranked.groupby("year", sort=True)]
                )
                dropped = []
                for g in groups:
                    dropped.extend(
                        g.sort_values(
                            ["contribution", "signal"], ascending=[False, True], kind="stable"
                        )
                        .head(count)
                        .signal.astype(int)
                        .tolist()
                    )
                out[key][scope][str(count)] = dict(
                    removed_signals=dropped,
                    removed_n=len(dropped),
                    metrics=main_metrics(frame[~frame.signal.isin(dropped)]),
                )
    return dict(
        results=out,
        rule="Each statistic ranks its own signed contribution to the original full-parent statistic; remove top 1/3/5 globally and within each year, even if zero/negative; signal date resolves ties. Recompute every denominator; missing cells remain invalid. Sensitivity only, never choose a preferred specification.",
    )


def bootstrap(frame, calendar, replicates=REPLICATES):
    cal = calendar[calendar.year.isin(YEARS)].sort_values("signal")
    mapping = {int(v): i for i, v in enumerate(cal.signal)}
    assert cal.signal.is_unique and set(frame.signal).issubset(mapping)
    # parent count, four cell counts, four Y sums, four residual sums, two allocation sums
    daily = np.zeros((len(cal), 15))
    y = frame.Y3.to_numpy(float)
    r = y - frame.score_M1.to_numpy(float)
    for j, row in enumerate(frame.itertuples()):
        i = mapping[int(row.signal)]
        cell = [(a, b) for a, b, _ in CELLS].index((int(row.z), int(row.S)))
        daily[i, 0] = 1
        daily[i, 1 + cell] = 1
        daily[i, 5 + cell] = y[j]
        daily[i, 9 + cell] = r[j]
        daily[i, 13] = y[j] * (int(row.sel_M2) - int(row.sel_M1))
        daily[i, 14] = y[j] * (int(row.sel_M1) - int(row.sel_M0))
    rng = np.random.default_rng(SEED)
    sums = np.zeros((replicates, 15))
    years = []
    for year in YEARS:
        indices = np.flatnonzero(cal.year.to_numpy() == year)
        if not len(indices):
            raise ValueError(f"Missing calendar year {year}")
        blocks = np.asarray(
            [daily[indices[i : i + 20]].sum(axis=0) for i in range(0, len(indices), 20)]
        )
        draws = rng.integers(0, len(blocks), (replicates, len(blocks)))
        sums += blocks[draws].sum(axis=1)
        years.append(
            dict(
                year=year,
                calendar_days=len(indices),
                blocks=len(blocks),
                last_block_days=len(indices) % 20 or 20,
                empty_nonparent_days=int((daily[indices, 0] == 0).sum()),
            )
        )
    complete = (sums[:, 1:5] > 0).all(axis=1)
    parent = sums[:, 0] > 0
    values = np.full((replicates, 4), np.nan)
    signs = np.array([v[2] for v in CELLS])
    values[complete, 0] = ((sums[complete, 5:9] / sums[complete, 1:5]) * signs).sum(axis=1)
    values[complete, 1] = ((sums[complete, 9:13] / sums[complete, 1:5]) * signs).sum(axis=1)
    values[parent, 2] = sums[parent, 13] / sums[parent, 0]
    values[parent, 3] = sums[parent, 14] / sums[parent, 0]
    estimates = main_metrics(frame)
    result = dict(
        seed=SEED,
        replicates=replicates,
        block_length=20,
        calendar_days=len(cal),
        parent_days=len(frame),
        year_blocks=years,
        failed_missing_cell=int((~complete).sum()),
        failed_no_parent=int((~parent).sum()),
        jointly_valid=int((complete & parent).sum()),
        ordinary_95={},
        simultaneous_primary_two_95={},
        method="Year-stratified nonoverlapping 20-trading-day calendar blocks; short last block retained; draw original block count per year. Empty days retained. All denominators recomputed. Fixed-score conditional percentile intervals; no training uncertainty or historical selection adjustment. Main pair: raw D and M2-minus-M1 allocation, Bonferroni 1.25/98.75 percentiles on joint-valid draws.",
    )
    for j, key in enumerate(METRICS):
        v = values[np.isfinite(values[:, j]), j]
        result["ordinary_95"][key] = dict(
            estimate=estimates[key],
            valid=len(v),
            invalid=replicates - len(v),
            low=None if not len(v) else float(np.quantile(v, 0.025)),
            high=None if not len(v) else float(np.quantile(v, 0.975)),
        )
        if j in (0, 2):
            v = values[complete & parent, j]
            result["simultaneous_primary_two_95"][key] = dict(
                estimate=estimates[key],
                valid=len(v),
                invalid=replicates - len(v),
                low=None if not len(v) else float(np.quantile(v, 0.0125)),
                high=None if not len(v) else float(np.quantile(v, 0.9875)),
            )
    return result


def load_inputs():
    p = pd.read_csv(EX / "others/predictions.csv")
    c = pd.read_csv(EX / "others/calendar.csv")
    required = {
        "signal",
        "date",
        "year",
        "A",
        "z",
        "S",
        "zs",
        "stock_cumulative_return",
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
        raise ValueError(f"Missing columns: {sorted(required - set(p.columns))}")
    for f in (p, c):
        f["date"] = pd.to_datetime(f.date).dt.strftime("%Y-%m-%d")
        for key in ("signal", "year"):
            v = pd.to_numeric(f[key], errors="raise")
            assert np.isfinite(v).all() and (v == np.floor(v)).all()
            f[key] = v.astype(int)
        assert f.signal.is_unique and f.date.is_unique
        assert (pd.to_datetime(f.date).dt.year == f.year).all()
        f.sort_values("signal", inplace=True)
        f.reset_index(drop=True, inplace=True)
        assert f.date.is_monotonic_increasing
    assert p.year.isin(YEARS).all()
    lookup = c.set_index("signal")
    assert set(p.signal).issubset(lookup.index)
    assert p.date.tolist() == lookup.loc[p.signal, "date"].tolist()
    for key in ("A", "z", "S", "zs", "roll", "entry_filled", *("sel_" + m for m in MODELS)):
        p[key] = boolean(p[key], key)
    p["z_old5"] = boolean(p.z_old5, "z_old5", allow_missing=True)
    assert p.environment.isin(["high", "low", "unready"]).all()
    for key in ("Y3", "Y1", "stock_cumulative_return", *("score_" + m for m in MODELS)):
        p[key] = pd.to_numeric(p[key], errors="raise")
        assert np.isfinite(p[key].dropna()).all(), key
        if key != "Y1":
            assert p[key].notna().all(), key
    assert (p.S == (p.stock_cumulative_return <= 0)).all()
    assert (p.zs == (p.z & p.S)).all()
    for key in ("entry", "maturity"):
        v = pd.to_numeric(p[key], errors="raise")
        assert (v.dropna() == np.floor(v.dropna())).all()
        assert v.dropna().isin(c.signal).all()
        p[key + "_index"] = v
    assert p.maturity_index.notna().all()
    assert (p.maturity_index > p.signal).all()
    assert p.loc[p.entry_filled, "entry_index"].notna().all()
    assert (p.loc[p.entry_filled, "entry_index"] > p.loc[p.entry_filled, "signal"]).all()
    assert (p.loc[p.entry_filled, "maturity_index"] >= p.loc[p.entry_filled, "entry_index"]).all()
    assert (p.loc[~p.entry_filled, "Y3"] == 0).all()
    assert (p.loc[~p.entry_filled & p.Y1.notna(), "Y1"] == 0).all()
    return p, c


def full_period_raw(raw=None):
    """Existing full-window labels, without B65 completeness or fitted scores."""
    raw = pd.read_csv(EX / "others/inputs.csv") if raw is None else raw.copy()
    assert raw.signal.is_unique and raw.year.between(2020, 2026).all()
    for key in ("A", "label_ready"):
        raw[key] = boolean(raw[key], key)
    for key in ("z", "S", "entry_filled"):
        raw[key] = boolean(raw[key], key, allow_missing=True)
    for key in ("Y3", "maturity"):
        raw[key] = pd.to_numeric(raw[key], errors="raise")
    assert (raw.label_ready == (raw.Y3.notna() & raw.maturity.ge(0))).all()
    parent = raw[raw.A].copy()
    state_ready = parent.z.notna() & parent.S.notna()
    selected = state_ready & parent.label_ready
    f = parent[selected].copy()
    for key in ("z", "S", "entry_filled"):
        f[key] = boolean(f[key], key)
    assert np.isfinite(f.Y3).all()
    assert (f.loc[~f.entry_filled, "Y3"] == 0).all()

    def summarize(group):
        result = four_cells(group, residual=False)
        result.pop("D_residual_M1")
        for cell in result["cells"].values():
            cell.pop("residual_mean")
        mask = group.z & group.S
        simple = group[mask]
        result.update(
            parent=distribution(group.Y3),
            unfilled_n=int((~group.entry_filled).sum()),
            simple_z1_S1=dict(
                attempts=len(simple),
                filled=int(simple.entry_filled.sum()),
                unfilled=int((~simple.entry_filled).sum()),
                returns=distribution(simple.Y3),
                allocation_per_parent=mean(
                    group.Y3.to_numpy(float) * mask.to_numpy(bool), np.ones(len(group))
                ),
                signals=simple.signal.astype(int).tolist(),
                filled_signals=simple.loc[simple.entry_filled, "signal"].astype(int).tolist(),
            ),
        )
        return result

    def signals(mask):
        return parent.loc[mask, "signal"].astype(int).tolist()

    missing_label = parent.maturity.isna() & ~parent.label_ready
    censored = parent.maturity.lt(0) & ~parent.label_ready
    other_unready = ~parent.label_ready & ~missing_label & ~censored
    return dict(
        status="COMPLETE",
        input_rows=len(raw),
        full_calendar_days=len(raw),
        raw_parent_count=len(parent),
        mature_state_complete_parent_count=len(f),
        full=summarize(f),
        annual={str(y): summarize(f[f.year == y]) for y in range(2020, 2027)},
        before_2023=summarize(f[f.year < 2023]),
        through_2025=summarize(f[f.year <= 2025]),
        inventory=dict(
            parent_missing_state_signals=signals(~state_ready),
            parent_label_not_generated_signals=signals(missing_label),
            parent_censored_signals=signals(censored),
            parent_other_unready_label_signals=signals(other_unready),
            parent_missing_label_before_2023=signals(missing_label & parent.year.lt(2023)),
            parent_censored_2026=signals(censored & parent.year.eq(2026)),
            excluded_parent_signals=signals(~selected),
            annual={
                str(y): dict(
                    parent_n=int((parent.year == y).sum()),
                    missing_state=int(((parent.year == y) & ~state_ready).sum()),
                    label_not_generated=int(((parent.year == y) & missing_label).sum()),
                    censored=int(((parent.year == y) & censored).sum()),
                    other_unready=int(((parent.year == y) & other_unready).sum()),
                )
                for y in range(2020, 2027)
            },
            definitions="Existing maturity NaN=label not generated; maturity<0=censored marker; other label-unready rows separate. State exclusions and label exclusions may overlap. No outcomes generated or filled.",
        ),
        capacity_note="Simple z1&S1 mature filled attempts are an optimistic upper bound on completed trades among these existing mature opportunities. Overlap, capital occupation and execution sequencing can reduce feasible trades. This is not executable frequency; censored/missing-label opportunities remain separate and are not claimed impossible. No B65 completeness requirement. 2020-2022 are already-seen raw descriptions, not independently validated trading years.",
    )


def selfcheck():
    f = pd.DataFrame(
        dict(
            signal=[1, 2, 3, 4],
            year=[2023] * 4,
            z=[True, False, True, False],
            S=[True, True, False, False],
            Y3=[0.10, 0.02, 0.04, 0],
            Y1=[0.05, 0.01, 0.02, 0],
            score_M1=[0.01, 0.02, 0.03, 0.05],
            sel_M0=[False] * 4,
            sel_M1=[False, True, True, False],
            sel_M2=[True, False, True, False],
            entry_filled=[True, True, True, False],
            entry_index=[2, 3, 8, np.nan],
            maturity_index=[5, 6, 10, 5],
        )
    )
    r = describe(f)
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    check("four-cell signs", np.isclose(r["D"], 0.04))
    check("residual four-cell", np.isclose(r["D_residual_M1"], 0.03))
    check("allocation parent divisor", np.isclose(r["allocation_M2_minus_M1"], 0.02))
    check("additive comparison", np.isclose(r["allocation_M1_minus_M0"], 0.015))
    check(
        "simple allocation",
        np.isclose(r["participation"]["simple_z1_S1"]["allocation_per_parent"], 0.025),
    )
    check(
        "decomposition",
        np.isclose(
            sum(
                v["difference_contribution"]
                for v in r["comparisons"]["M2_minus_M1"]["groups"].values()
            ),
            0.02,
        ),
    )
    check("missing cell invalid", describe(f.iloc[:3])["D"] is None)
    check("empty invalid", describe(f.iloc[:0])["allocation_M2_minus_M1"] is None)
    check(
        "weighted denominator",
        np.isclose(describe(f, weights=[2, 1, 1, 1])["allocation_M2_minus_M1"], 0.036),
    )
    h = holding_diagnostics(f)
    check("inclusive clusters and unfilled singleton", h["cluster_count"] == 3)
    check("equal cluster mass", np.isclose(h["equal_cluster"]["parent_weight"], 3))
    check("realised dedup", h["chronological_signals"] == [1, 3, 4])
    t = trim_favorable(f)
    check(
        "top1 removal",
        t["results"]["allocation_M2_minus_M1"]["global"]["1"]["removed_signals"] == [1],
    )
    check("top removal missing group", t["results"]["D"]["global"]["1"]["metrics"]["D"] is None)
    cal = pd.DataFrame([dict(signal=y * 100 + i, year=y) for y in YEARS for i in range(25)])
    g = pd.concat([f.assign(signal=[y * 100 + i for i in (1, 2, 3, 4)], year=y) for y in YEARS])
    b = bootstrap(g, cal, replicates=50)
    check(
        "calendar zeros",
        b["calendar_days"] == 100
        and sum(v["empty_nonparent_days"] for v in b["year_blocks"]) == 84,
    )
    check(
        "bootstrap validity count",
        b["ordinary_95"]["D"]["valid"] + b["ordinary_95"]["D"]["invalid"] == 50,
    )
    b = bootstrap(g[g.z], cal, replicates=50)
    check(
        "missing cell bootstrap",
        b["failed_missing_cell"] == 50 and b["ordinary_95"]["D"]["low"] is None,
    )
    check("allocation independently valid", b["ordinary_95"]["allocation_M2_minus_M1"]["valid"] > 0)
    check(
        "optional old direction",
        boolean(pd.Series([True, None, 0]), "old", True).isna().tolist() == [False, True, False],
    )
    h1 = describe(f, target="Y1")
    delta = f.assign(Y_delta=f.Y3 - f.Y1)
    check(
        "paired H3 H1 cancellation",
        np.isclose(
            subtract(r["D_residual_M1"], h1["D_residual_M1"]),
            describe(delta, target="Y_delta", residual=False)["D"],
        ),
    )
    raw = f.assign(A=True, label_ready=True, maturity=f.maturity_index, feature_ready=False)
    extra = pd.DataFrame(
        dict(
            signal=[11, 12, 13],
            year=[2020, 2026, 2020],
            A=[True] * 3,
            z=[True] * 3,
            S=[True, True, None],
            Y3=[np.nan, np.nan, 0.01],
            label_ready=[False, False, True],
            maturity=[np.nan, -1, 15],
            entry_filled=[None, True, True],
            feature_ready=[False] * 3,
        )
    )
    raw_result = full_period_raw(pd.concat([raw, extra], ignore_index=True))
    check(
        "raw does not require B65 readiness", raw_result["mature_state_complete_parent_count"] == 4
    )
    check("raw simple filled upper bound", raw_result["full"]["simple_z1_S1"]["filled"] == 1)
    check("raw no adjusted score claim", "D_residual_M1" not in raw_result["full"])
    check(
        "raw missing label inventory",
        raw_result["inventory"]["parent_label_not_generated_signals"] == [11],
    )
    check("raw censored inventory", raw_result["inventory"]["parent_censored_signals"] == [12])
    check(
        "raw missing state inventory",
        raw_result["inventory"]["parent_missing_state_signals"] == [13],
    )
    return dict(
        status="PASS",
        checks=len(checks),
        check_names=checks,
        fits=0,
        accounts=0,
        source_calls=0,
        new_labels=0,
    )


def main():
    if "--selfcheck" in sys.argv:
        result = selfcheck()
        result["source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
        if "--write-precheck" in sys.argv:
            path = EX / "others/analysis_precheck.json"
            if path.exists():
                raise RuntimeError("Preserve existing analysis precheck")
            path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(result))
        return
    if (EX / "others/analysis.json").exists() or (EX / "others/annual.csv").exists():
        raise RuntimeError("Preserve completed analysis outputs")
    tests = selfcheck()
    p, calendar = load_inputs()
    f = p[p.A].copy()
    annual = {str(y): describe(f[f.year == y]) for y in YEARS}
    h1 = f[f.Y1.notna()].copy()
    h3paired, h1paired = describe(h1), describe(h1, target="Y1")
    delta = h1.assign(Y_delta=h1.Y3 - h1.Y1)
    old = f[f.z_old5.notna()].copy()

    def old_summary(group):
        return four_cells(group, z_column="z_old5")

    result = dict(
        status="COMPLETE",
        units="decimal returns; multiply by 100 for percentage points",
        selfcheck=tests,
        signal_count=len(p),
        parent_count=len(f),
        full_period_raw=full_period_raw(),
        main=describe(f),
        annual=annual,
        without_2026=describe(f[f.year != 2026]),
        leave_one_year_out={str(y): describe(f[f.year != y]) for y in YEARS},
        exclude_roll=describe(f[~f.roll]),
        roll_only=describe(f[f.roll]),
        environment={e: describe(f[f.environment == e]) for e in ("high", "low", "unready")},
        duration=dict(
            common_n=len(h1),
            H3_mature_n=len(f),
            H1_missing_signals=f.loc[f.Y1.isna(), "signal"].astype(int).tolist(),
            H3_on_common=h3paired,
            H1_on_common=h1paired,
            H3_minus_H1=describe(delta, target="Y_delta", residual=False),
            metric_differences={k: subtract(h3paired[k], h1paired[k]) for k in METRICS},
            note="Existing H1 labels, identical fixed H3 model scores and selections; no H1 refit or horizon replacement. Residual differences cancel score_M1. Does not recover H1-only opportunities absent from H3-mature predictions.",
        ),
        old5_counterevidence=dict(
            valid_n=len(old),
            excluded_signals=f.loc[f.z_old5.isna(), "signal"].astype(int).tolist(),
            main=old_summary(old),
            annual={str(y): old_summary(old[old.year == y]) for y in YEARS},
            without_2026=old_summary(old[old.year != 2026]),
            note="Old direction does not determine the primary common queue; same S and existing Y3, descriptive only. Residual subtracts existing one-day-z M1, not an old5 fitted baseline.",
        ),
        holding=holding_diagnostics(f),
        favorable_trimming=trim_favorable(f),
        bootstrap=bootstrap(f, calendar),
        inventory=dict(
            parent_signals=f.signal.astype(int).tolist(),
            unfilled_parent_signals=f.loc[~f.entry_filled, "signal"].astype(int).tolist(),
            maturity_records=f[["signal", "entry", "maturity", "entry_filled"]]
            .astype(object)
            .where(pd.notna(f[["signal", "entry", "maturity", "entry_filled"]]), None)
            .to_dict("records"),
            calendar_signals_absent_from_predictions=calendar.loc[
                calendar.year.isin(YEARS) & ~calendar.signal.isin(p.signal), "signal"
            ]
            .astype(int)
            .tolist(),
            note="Predictions contain complete mature common rows only. Missing calendar rows are listed, not automatically called censored. Preparation inventory supplies reasons and the immutable full maturity/truncation inventory; no labels reconstructed here.",
        ),
        fits=0,
        accounts=0,
        source_calls=0,
        new_labels=0,
        limits=[
            "Already-seen adaptive development hypothesis, not independent confirmation or causal commodity effect.",
            "Opportunity labels and allocations are not continuous account returns; realised overlap is diagnostic, not an executable schedule.",
            "Conditional fixed-score intervals omit training uncertainty and historical hypothesis selection; missing groups never filled.",
            "Relative loss reduction alone does not establish a useful long entry; compare absolute, all-parent and stock-only participation.",
            "No year-specific positivity gate, new economic acceptance gate, new threshold, direction, horizon or model selection.",
        ],
    )
    paths = [
        Path(__file__),
        EX / "others/predictions.csv",
        EX / "others/calendar.csv",
        EX / "others/inputs.csv",
        EX / "protocols/design.json",
        EX / "protocols/approved_proposal.md",
    ]
    root = EX.parents[3]
    result["source_sha256"] = {
        q.relative_to(root).as_posix(): sha256(q.read_bytes()).hexdigest() for q in paths
    }
    rows = [
        dict(
            year=int(year),
            n=r["n"],
            **{k: r[k] for k in METRICS},
            parent_mean=r["parent"]["mean"],
            **{f"{m}_selected": r["participation"][m]["selected_count"] for m in MODELS},
            **{f"{m}_allocation": r["participation"][m]["allocation_per_parent"] for m in MODELS},
            **{f"{k}_n": v["n"] for k, v in r["four_cells"]["cells"].items()},
        )
        for year, r in annual.items()
    ]
    output = EX / "others/annual.csv"
    output.write_text(
        pd.DataFrame(rows).to_csv(index=False, lineterminator="\n"), encoding="utf-8", newline="\n"
    )
    result["annual_sha256"] = sha256(output.read_bytes()).hexdigest()
    (EX / "others/analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            dict(
                status="COMPLETE",
                parent_count=len(f),
                **{k: result["main"][k] for k in METRICS},
                fits=0,
            )
        )
    )


if __name__ == "__main__":
    main()
