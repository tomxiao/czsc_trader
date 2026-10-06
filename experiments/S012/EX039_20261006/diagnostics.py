"""Same-fee forward-event contrasts, calendar block uncertainty, all negatives."""

import numpy as np
import pandas as pd
from .mechanisms import HYPOTHESES

CONTROL_COLS = ["etf5", "etf20", "vol20", "own_day"]


def finite(x):
    return float(x) if np.isfinite(x) else None


def avg(values):
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    return finite(a.mean()) if len(a) else None


def anchors(mask, spacing):
    chosen = []
    nextpos = 0
    for p in np.flatnonzero(mask):
        if p >= nextpos:
            chosen.append(int(p))
            nextpos = int(p) + spacing
    return np.asarray(chosen, dtype=int)


def labels(d, h, delay, fee):
    entry = d.Open.shift(-1 - delay)
    exit_price = d.Open.shift(-1 - delay - h)
    gross = exit_price / entry
    net = gross * (1 - fee) / (1 + fee) - 1
    limit = np.floor((d.Close + 1e-10) / 0.001) * 0.001
    buy = entry.where(entry <= limit, limit.where(d.Low.shift(-1 - delay) <= limit))
    limit_net = exit_price / buy * (1 - fee) / (1 + fee) - 1
    intraday = sum(
        np.log(d.Close.shift(-1 - delay - j) / d.Open.shift(-1 - delay - j)) for j in range(h)
    )
    overnight = sum(
        np.log(d.Open.shift(-2 - delay - j) / d.Close.shift(-1 - delay - j)) for j in range(h)
    )
    valid = np.isfinite(gross) & np.isfinite(intraday) & np.isfinite(overnight)
    np.testing.assert_allclose(
        (intraday + overnight)[valid], np.log(gross[valid]), atol=1e-12, rtol=1e-12
    )
    return pd.DataFrame(
        {
            "net": net,
            "limit_net": limit_net,
            "gross": gross - 1,
            "intraday_log": intraday,
            "overnight_log": overnight,
        },
        index=d.index,
    )


def matched_residual(y, f, mask):
    # Retrospective diagnostic, not a training set or a decision threshold.
    x = f.loc[mask]
    v = x.vol20
    tercile = v.groupby(v.index.year).transform(
        lambda s: pd.Series(np.digitize(s, s.quantile([1 / 3, 2 / 3])), index=s.index)
    )
    keys = pd.MultiIndex.from_arrays(
        [
            x.index.year,
            (x.etf5 > 0).astype(int),
            tercile,
            (x.own_day > 0).astype(int),
        ]
    )
    yy = pd.Series(y[mask].to_numpy(), index=keys)
    baseline = yy.groupby(level=list(range(4))).transform("mean").to_numpy()
    residual = pd.Series(np.nan, index=f.index)
    residual.loc[mask] = y.loc[mask].to_numpy() - baseline
    return residual


def ols(y, f, mask, signal, extra=()):
    cols = [*CONTROL_COLS, *extra]
    mask = mask & f[cols].notna().all(axis=1).to_numpy()
    x = f.loc[mask, cols].to_numpy(dtype=float)
    if len(x) < 20 or np.std(signal[mask]) == 0:
        return None
    means = x.mean(axis=0)
    std = x.std(axis=0)
    std[std == 0] = 1.0
    years = f.index[mask].year
    design = np.column_stack(
        [
            np.ones(len(x)),
            signal[mask].astype(float),
            (x - means) / std,
            *[(years == yr).astype(float) for yr in np.unique(years)[1:]],
        ]
    )
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return None
    return finite(np.linalg.lstsq(design, y[mask].to_numpy(), rcond=None)[0][1])


def bootstrap(y, residual, signal, mask, seed, repetitions=999):
    selected = signal & mask
    if selected.sum() < 6:
        return {"net_ci": None, "increment_ci": None, "reason": "少于6事件"}
    rng = np.random.default_rng(seed)
    n = len(mask)
    block = 20
    starts = rng.integers(0, n, size=(repetitions, int(np.ceil(n / block))))
    ids = ((starts[..., None] + np.arange(block)) % n).reshape(repetitions, -1)[:, :n]
    good = selected[ids]
    nn = good.sum(axis=1)
    yy = np.nan_to_num(y.to_numpy(), nan=0.0)[ids]
    rr = np.nan_to_num(residual.to_numpy(), nan=0.0)[ids]
    net = (yy * good).sum(axis=1) / np.maximum(nn, 1)
    inc = (rr * good).sum(axis=1) / np.maximum(nn, 1)
    return {
        "net_ci": [float(v) for v in np.quantile(net[nn > 0], [0.025, 0.975])],
        "increment_ci": [float(v) for v in np.quantile(inc[nn > 0], [0.025, 0.975])],
        "block_sessions": block,
        "repetitions": repetitions,
        "reason": None,
    }


def shift_p(residual, signal, mask, seed, repetitions=399):
    if (signal & mask).sum() < 6:
        return None
    rng = np.random.default_rng(seed)
    y = residual.to_numpy()
    obs = abs(avg(y[signal & mask]))
    values = []
    groups = [
        np.flatnonzero(mask & (residual.index.year == year))
        for year in np.unique(residual.index.year)
    ]
    for _ in range(repetitions):
        shifted = np.zeros(len(mask), dtype=bool)
        for ids in groups:
            if len(ids) < 50:
                continue
            offset = int(rng.integers(21, len(ids) - 20))
            shifted[ids] = np.roll(signal[ids], offset)
        m = avg(y[shifted & mask])
        if m is not None:
            values.append(abs(m))
    return (1 + sum(v >= obs for v in values)) / (1 + len(values)) if values else None


def bh(values):
    p = np.asarray(values)
    order = np.argsort(p)
    q = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    out = np.empty(len(p))
    out[order] = np.minimum(q, 1)
    return out


def row(panel, f, signal, valid, parent, h, delay, fee, name):
    controls = f[CONTROL_COLS].notna().all(axis=1)
    mask = valid.to_numpy() & panel.net.notna().to_numpy() & controls.to_numpy()
    hit = signal.to_numpy(dtype=bool) & mask
    par = parent.to_numpy(dtype=bool) & mask
    residual = matched_residual(panel.net, f, mask)
    parent_residual = matched_residual(panel.net, f, par)
    risk_mask = mask & f[["pair_vix", "pair_gvz"]].notna().all(axis=1).to_numpy()
    chosen = anchors(hit, h + 1)
    filled = chosen[np.isfinite(panel.limit_net.to_numpy()[chosen])]
    kept = (signal.to_numpy(dtype=bool))[anchors(par, h + 1)]
    parent_anchors = anchors(par, h + 1)
    yy = panel.net.to_numpy()
    ly = panel.limit_net.to_numpy()
    parent_limit = np.nan_to_num(ly[parent_anchors], nan=0.0)
    parent_delta = np.where(kept, parent_limit, 0.0) - parent_limit
    # No-fill parents contribute zero; do not reschedule after filtering.
    contribution = np.full(len(panel), np.nan)
    contribution[parent_anchors] = parent_delta
    base = avg(yy[mask])
    event = avg(yy[hit])
    parent_net = avg(yy[par])
    return (
        {
            "signal": name,
            "horizon": h,
            "delay": delay,
            "fee": fee,
            "eligible_days": int(mask.sum()),
            "events": int(hit.sum()),
            "parent_events": int(par.sum()),
            "net_mean": event,
            "unconditional_same_fee": base,
            "parent_same_fee": parent_net,
            "parent_lift": None if event is None or parent_net is None else event - parent_net,
            "matched_increment": avg(residual[hit]),
            "parent_matched_increment": avg(parent_residual[hit]),
            "ols_increment": ols(panel.net, f, mask, signal.to_numpy(dtype=bool)),
            "parent_ols_increment": ols(panel.net, f, par, signal.to_numpy(dtype=bool)),
            "ols_same_risk_window": ols(panel.net, f, risk_mask, signal.to_numpy(dtype=bool)),
            "ols_with_both_risks": ols(
                panel.net, f, mask, signal.to_numpy(dtype=bool), ("pair_vix", "pair_gvz")
            ),
            "nonoverlap_events": len(chosen),
            "nonoverlap_net": avg(yy[chosen]),
            "limit_potential_fills": len(filled),
            "limit_potential_net": avg(ly[filled]),
            "potential_per60_original1535": len(filled) * 60 / len(panel),
            "intraday_log_mean": avg(panel.intraday_log[hit]),
            "overnight_log_mean": avg(panel.overnight_log[hit]),
            "fixed_parent_filtered_contribution": avg(np.where(kept, yy[parent_anchors], 0.0)),
            "fixed_parent_base_contribution": avg(yy[parent_anchors]),
            "fixed_parent_limit_base": avg(parent_limit),
            "fixed_parent_limit_filtered": avg(np.where(kept, parent_limit, 0.0)),
            "fixed_parent_limit_delta": avg(parent_delta),
            "fixed_parent_limit_slots": len(parent_anchors),
            "fixed_parent_limit_base_fills": int(np.isfinite(ly[parent_anchors]).sum()),
            "fixed_parent_limit_kept_fills": int((kept & np.isfinite(ly[parent_anchors])).sum()),
        },
        mask,
        residual,
    )


def run(d, f, signals, valids, seed=12039):
    specs = {k: (h, parent, role, title) for k, h, parent, role, title in HYPOTHESES}
    rows = []
    annual = []
    inference = []
    all_labels = {}
    for h in (1, 3, 5):
        for delay in (0, 1, 2):
            for fee in (0.001, 0.002):
                panel = labels(d, h, delay, fee)
                all_labels[f"h{h}_d{delay}_f{fee}"] = panel.add_prefix(f"h{h}_d{delay}_f{fee}__")
                for name in signals:
                    parent_name = specs[name][1] if name in specs else None
                    parent = signals[parent_name] if parent_name else pd.Series(True, index=d.index)
                    valid = valids[name] & (valids[parent_name] if parent_name else True)
                    r, mask, residual = row(
                        panel, f, signals[name], valid, parent, h, delay, fee, name
                    )
                    rows.append(r)
                    if name in specs and h == specs[name][0] and delay == 0 and fee == 0.001:
                        pmask = mask & parent.to_numpy(dtype=bool)
                        parent_residual = matched_residual(panel.net, f, pmask)
                        pa = anchors(pmask, h + 1)
                        raw_limit = panel.limit_net.to_numpy()
                        before = np.nan_to_num(raw_limit[pa], nan=0.0)
                        delta = np.where(signals[name].to_numpy()[pa], before, 0.0) - before
                        contribution = pd.Series(np.nan, index=d.index)
                        contribution.iloc[pa] = delta
                        cmask = contribution.notna().to_numpy()
                        cb = bootstrap(
                            contribution, contribution, cmask, cmask, seed + 400 + len(inference)
                        )
                        parent_bs = bootstrap(
                            panel.net,
                            parent_residual,
                            signals[name].to_numpy(),
                            pmask,
                            seed + 200 + len(inference),
                        )
                        bs = bootstrap(
                            panel.net,
                            residual,
                            signals[name].to_numpy(),
                            mask,
                            seed + len(inference),
                        )
                        p = shift_p(
                            residual, signals[name].to_numpy(), mask, seed + 100 + len(inference)
                        )
                        inference.append(
                            {
                                "signal": name,
                                "horizon": h,
                                "p": p,
                                **bs,
                                "parent_increment_ci": parent_bs["increment_ci"],
                                "fixed_limit_delta_ci": cb["net_ci"],
                            }
                        )
                    for year in np.unique(d.index.year):
                        m = mask & (d.index.year == year)
                        hit = m & signals[name].to_numpy()
                        pa = anchors(mask & parent.to_numpy(dtype=bool), h + 1)
                        lp = np.nan_to_num(panel.limit_net.to_numpy()[pa], nan=0.0)
                        ld = np.where(signals[name].to_numpy()[pa], lp, 0.0) - lp
                        ay = d.index[pa].year == year
                        parent_residual = matched_residual(
                            panel.net, f, mask & parent.to_numpy(dtype=bool)
                        )
                        annual.append(
                            {
                                "signal": name,
                                "horizon": h,
                                "delay": delay,
                                "fee": fee,
                                "year": int(year),
                                "eligible_days": int(m.sum()),
                                "events": int(hit.sum()),
                                "net_mean": avg(panel.net[hit]),
                                "matched_increment": avg(residual[hit]),
                                "parent_matched_increment": avg(parent_residual[hit]),
                                "fixed_parent_limit_delta": avg(ld[ay]),
                                "fixed_parent_limit_base": avg(lp[ay]),
                                "fixed_parent_limit_slots": int(ay.sum()),
                            }
                        )
    valid = [r for r in inference if r["p"] is not None]
    q = bh([r["p"] for r in valid])
    for r, v in zip(valid, q, strict=True):
        r["q"] = float(v)
    for r in inference:
        r.setdefault("q", None)
    return rows, annual, inference, pd.concat(all_labels.values(), axis=1)
