"""Opportunity-conditional comparisons with fixed parent execution schedules."""

from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from .mechanism import BASES, GATES, nonoverlap


def number(value):
    return float(value) if np.isfinite(value) else None


def mean(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return number(values.mean()) if len(values) else None


def delta(a, b):
    return None if a is None or b is None else float(a - b)


def labels(d, bad, h, delay, fee):
    entry = d.Open.shift(-1 - delay)
    exit_price = d.Open.shift(-1 - delay - h)
    net = exit_price / entry * (1 - fee) / (1 + fee) - 1
    limit = np.floor((d.Close + 1e-10) / 0.001) * 0.001
    filled = entry.where(entry.le(limit), limit.where(d.Low.shift(-1 - delay).le(limit)))
    limit_net = exit_price / filled * (1 - fee) / (1 + fee) - 1
    badmask = pd.Series([str(t.date()) in bad for t in d.index], index=d.index)
    clean = ~pd.concat(
        [badmask.shift(-j, fill_value=False) for j in range(h + delay + 2)], axis=1
    ).any(axis=1)
    low_path = pd.concat([d.Low.shift(-1 - delay - j) for j in range(h)], axis=1)
    downside = (1 - low_path.min(axis=1, skipna=False) / entry).clip(lower=0)
    return pd.DataFrame(
        {"net": net, "limit_net": limit_net, "clean": clean, "downside": downside},
        index=d.index,
    )


def compare(panel, parent, gate, h):
    y = panel.net.to_numpy()
    ly = panel.limit_net.to_numpy()
    parent = np.asarray(parent, dtype=bool)
    gate = np.asarray(gate, dtype=bool)
    passed, failed = parent & gate, parent & ~gate
    anchors = nonoverlap(parent, h + 1)
    kept = anchors[gate[anchors]]
    dropped = anchors[~gate[anchors]]
    changed = nonoverlap(passed, h + 1)
    known = np.isfinite(ly[anchors])
    kept_known = gate[anchors] & known
    base_mean, pass_mean, fail_mean = mean(y[parent]), mean(y[passed]), mean(y[failed])
    lost = y[dropped]
    loss = lost[lost < 0]
    gain = lost[lost > 0]
    parent_contribution = mean(y[anchors])
    filter_contribution = mean(np.where(gate[anchors], y[anchors], 0.0))
    limit_parent_contribution = mean(np.nan_to_num(ly[anchors], nan=0.0))
    limit_filter_contribution = mean(np.where(kept_known, np.nan_to_num(ly[anchors], nan=0.0), 0.0))
    row = {
        "parent_events": int(parent.sum()),
        "passed_events": int(passed.sum()),
        "rejected_events": int(failed.sum()),
        "retention": int(passed.sum()) / max(int(parent.sum()), 1),
        "parent_net": base_mean,
        "passed_net": pass_mean,
        "rejected_net": fail_mean,
        "conditional_lift": delta(pass_mean, base_mean),
        "pass_minus_reject": delta(pass_mean, fail_mean),
        "parent_downside": mean(panel.downside[parent]),
        "passed_downside": mean(panel.downside[passed]),
        "rejected_downside": mean(panel.downside[failed]),
        "parent_anchors": len(anchors),
        "kept_anchors": len(kept),
        "dropped_anchors": len(dropped),
        "parent_anchor_net": parent_contribution,
        "kept_anchor_net": mean(y[kept]),
        "fixed_parent_contribution": parent_contribution,
        "fixed_filter_contribution": filter_contribution,
        "fixed_contribution_delta": delta(filter_contribution, parent_contribution),
        "lost_profitable_events": int((lost > 0).sum()),
        "lost_profit_sum": float(gain.sum()),
        "avoided_loss_events": int((lost < 0).sum()),
        "avoided_loss_sum": float(-loss.sum()),
        "parent_limit_fills": int(known.sum()),
        "kept_limit_fills": int(kept_known.sum()),
        "parent_limit_per60": int(known.sum()) * 60 / len(panel),
        "kept_limit_per60": int(kept_known.sum()) * 60 / len(panel),
        "parent_limit_net": mean(ly[anchors]),
        "kept_limit_net": mean(ly[kept]),
        "fixed_limit_parent_contribution": limit_parent_contribution,
        "fixed_limit_filter_contribution": limit_filter_contribution,
        "fixed_limit_contribution_delta": delta(
            limit_filter_contribution, limit_parent_contribution
        ),
        "rescheduled_events": len(changed),
        "rescheduled_limit_fills": int(np.isfinite(ly[changed]).sum()),
        "rescheduled_limit_per60": int(np.isfinite(ly[changed]).sum()) * 60 / len(panel),
        "rescheduled_limit_net": mean(ly[changed]),
        "without_best5_passed_net": mean(np.sort(y[passed])[:-5]) if passed.sum() > 5 else None,
        "without_2025_lift": delta(
            mean(y[passed & (panel.index.year != 2025)]),
            mean(y[parent & (panel.index.year != 2025)]),
        ),
    }
    if len(anchors):
        np.testing.assert_allclose(
            row["fixed_contribution_delta"] * len(anchors),
            row["avoided_loss_sum"] - row["lost_profit_sum"],
            atol=1e-12,
        )
    return row, anchors


def conditional_inference(panel, parent, gate, h, seed):
    """Year-preserving event-sequence rotations and calendar-block intervals."""
    y = panel.net.to_numpy()
    parent, gate = np.asarray(parent), np.asarray(gate)
    ids = np.flatnonzero(parent)
    anchors = nonoverlap(parent, h + 1)
    kept, rejected = gate[anchors].sum(), (~gate[anchors]).sum()
    observed = delta(mean(y[parent & gate]), mean(y[parent & ~gate]))
    result = {
        "p": None,
        "q": None,
        "lift_ci_low": None,
        "lift_ci_high": None,
        "contribution_ci_low": None,
        "contribution_ci_high": None,
        "reason": None,
    }
    if kept < 6 or rejected < 6 or observed is None:
        result["reason"] = "固定父机会时间表通过或未通过少于6事件，不解释区间或循环移位。"
        return result
    rng = np.random.default_rng(seed)
    years = panel.index.year.to_numpy()
    pattern = gate[ids].copy()
    groups = [np.flatnonzero(years[ids] == year) for year in np.unique(years[ids])]
    greater = 0
    for _ in range(399):
        shuffled = pattern.copy()
        for positions in groups:
            shuffled[positions] = np.roll(pattern[positions], int(rng.integers(len(positions))))
        effect = mean(y[ids][shuffled]) - mean(y[ids][~shuffled])
        greater += abs(effect) >= abs(observed)
    result["p"] = (greater + 1) / 400
    # Fixed 20-trading-date clusters within each year; resample all clusters, including empty ones.
    cluster = np.zeros(len(panel), dtype=int)
    pools, offset = [], 0
    for year in np.unique(years):
        positions = np.flatnonzero(years == year)
        local = np.arange(len(positions)) // 20
        cluster[positions] = local + offset
        pools.append(np.arange(offset, offset + int(local.max()) + 1))
        offset += int(local.max()) + 1
    weights = np.zeros((999, offset), dtype=int)
    for pool in pools:
        sampled = rng.choice(pool, (999, len(pool)))
        for row, samples in enumerate(sampled):
            weights[row] += np.bincount(samples, minlength=offset)
    parent_weights = weights[:, cluster[ids]]
    pass_weights = parent_weights * gate[ids]
    parent_means = parent_weights @ y[ids] / parent_weights.sum(axis=1)
    denominator = pass_weights.sum(axis=1)
    available = denominator > 0
    lifts = (pass_weights[available] @ y[ids] / denominator[available]) - parent_means[available]
    aw = weights[:, cluster[anchors]]
    usable = aw.sum(axis=1) > 0
    differences = aw[usable] @ np.where(gate[anchors], 0.0, -y[anchors]) / aw[usable].sum(axis=1)
    result["lift_ci_low"], result["lift_ci_high"] = [
        float(v) for v in np.quantile(lifts, [0.025, 0.975])
    ]
    result["contribution_ci_low"], result["contribution_ci_high"] = [
        float(v) for v in np.quantile(differences, [0.025, 0.975])
    ]
    return result


def run(d, f, signals, valid_signals, gates, valid_gates, risk_high, risk_valid, bad, workers):
    records, annual, panels = [], [], {}
    for h in (1, 3, 5):
        for delay in (0, 2):
            for fee in (0.001, 0.002):
                key = f"h{h}_delay{delay}_fee{fee}"
                panel = labels(d, bad, h, delay, fee)
                panels[key] = panel
                for quality in ("all", "quality_clean"):
                    eligible = (d.index.year >= 2022) & panel.net.notna() & f.sell_pressure.notna()
                    if quality == "quality_clean":
                        eligible &= panel.clean
                    for base in BASES:
                        parent_raw = eligible & signals[base] & valid_signals[base]
                        for gate in GATES:
                            parent = parent_raw & valid_gates[gate]
                            row, _ = compare(panel, parent, gates[gate], h)
                            row.update(
                                base=base,
                                gate=gate,
                                horizon=h,
                                delay=delay,
                                fee=fee,
                                quality=quality,
                                unknown_confirmation_events=int(
                                    (parent_raw & ~valid_gates[gate]).sum()
                                ),
                            )
                            records.append(row)
                            for year in sorted(set(d.index.year)):
                                yearly, _ = compare(
                                    panel, parent & (d.index.year == year), gates[gate], h
                                )
                                yearly.update(
                                    base=base,
                                    gate=gate,
                                    horizon=h,
                                    delay=delay,
                                    fee=fee,
                                    quality=quality,
                                    year=int(year),
                                )
                                annual.append(yearly)
    primary = panels["h5_delay0_fee0.001"]
    tasks = []
    for i, base in enumerate(BASES):
        for j, gate in enumerate(GATES):
            parent = (
                (d.index.year >= 2022)
                & primary.net.notna()
                & f.sell_pressure.notna()
                & signals[base]
                & valid_signals[base]
                & valid_gates[gate]
            )
            tasks.append((base, gate, parent, gates[gate], 12018 + i * 100 + j))

    def infer(task):
        base, gate, parent, mask, seed = task
        return {"base": base, "gate": gate, **conditional_inference(primary, parent, mask, 5, seed)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        inference = list(pool.map(infer, tasks))
    ordered = sorted(
        [i for i, r in enumerate(inference) if r["p"] is not None], key=lambda i: inference[i]["p"]
    )
    q = 1.0
    for rank, i in reversed(list(enumerate(ordered, 1))):
        q = min(q, inference[i]["p"] * len(tasks) / rank)
        inference[i]["q"] = q
    risks = []
    for quality in ("all", "quality_clean"):
        eligible = (d.index.year >= 2022) & primary.net.notna() & f.sell_pressure.notna()
        if quality != "all":
            eligible &= primary.clean
        for base in BASES:
            for name in risk_high:
                parent = eligible & signals[base] & valid_signals[base] & risk_valid[name]
                # Low-state gate; original risk definitions are not relabeled as confirmation.
                row, _ = compare(primary, parent, ~risk_high[name], 5)
                row.update(base=base, risk=name, quality=quality)
                risks.append(row)
    return records, annual, inference, risks, pd.concat(panels, axis=1)
