"""Fixed event-level diagnostics reused from EX016; no account simulation."""

from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import tsfresh as tsfresh
import expr_codegen as expr_codegen


def summary(d, f, s, valids, bad, workers):
    records, annual, panels = [], [], []
    valid = f.sell_pressure.notna() & (f.index.year >= 2022)
    badmask = pd.Series([str(t.date()) in bad for t in d.index], index=d.index)
    for h in (1, 3, 5):
        for delay in (0, 2):
            ratio = d.Open.shift(-h - delay - 1) / d.Open.shift(-delay - 1)
            gross = ratio - 1
            clean = ~pd.concat(
                [badmask.shift(-k, fill_value=False) for k in range(h + delay + 2)], axis=1
            ).any(axis=1)
            limit = np.floor((d.Close + 1e-10) / 0.001) * 0.001
            entry = d.Open.shift(-delay - 1)
            fill = entry.where(entry.le(limit), limit.where(d.Low.shift(-delay - 1).le(limit)))
            limitnet = d.Open.shift(-h - delay - 1) / fill * 0.999 / 1.001 - 1
            for fee in (0.001, 0.002):
                net = ratio * (1 - fee) / (1 + fee) - 1
                eligible = valid & net.notna()
                controls = pd.DataFrame(
                    {
                        "year": d.index.year,
                        "r1": f.day_return,
                        "r3": f.return3,
                        "v": f.volume_ratio,
                    },
                    index=d.index,
                )
                # Price/volume rank cells are retrospective matched diagnostics, not inputs.
                cells = controls.groupby("year", group_keys=False)[["r1", "r3", "v"]].transform(
                    lambda x: pd.qcut(x.rank(method="first"), 3, labels=False, duplicates="drop")
                )
                key = pd.Series(
                    [
                        f"{y}_{a}_{b}_{c}"
                        for y, a, b, c in zip(d.index.year, cells.r1, cells.r3, cells.v)
                    ],
                    index=d.index,
                )
                X = f[
                    [
                        "day_return",
                        "return3",
                        "volume_ratio",
                        "range",
                        "location",
                        "momentum20",
                        "volatility20",
                    ]
                ].copy()
                X = X.join(
                    pd.get_dummies(
                        pd.Series(d.index.year, index=d.index), dtype=float, prefix="year"
                    )
                )
                X.insert(0, "constant", 1.0)

                def calc(name):
                    out = []
                    for sensitivity in ("all", "quality_clean"):
                        owneligible = eligible & valids[name]
                        mask = owneligible & s[name]
                        if sensitivity != "all":
                            mask &= clean
                        # Use exactly the same eligibility for retrospective controls.
                        controlmask = owneligible & (clean if sensitivity != "all" else True)
                        base = gross[controlmask].groupby(key[controlmask]).mean()
                        diff = net - key.map(base)
                        fitmask = controlmask & X.notna().all(axis=1)
                        beta = np.linalg.lstsq(
                            X.loc[fitmask].to_numpy(), gross[fitmask].to_numpy(), rcond=None
                        )[0]
                        residual = net - pd.Series(X.to_numpy() @ beta, index=d.index)
                        ids = np.flatnonzero(mask.to_numpy())
                        chosen = []
                        nxt = 0
                        for i in ids:
                            if i >= nxt:
                                chosen.append(int(i))
                                nxt = int(i) + h + 1
                        values = net[mask]
                        yearly = [
                            {
                                "signal": name,
                                "horizon": h,
                                "delay": delay,
                                "fee": fee,
                                "sensitivity": sensitivity,
                                "year": int(y),
                                "events": int((mask & (d.index.year == y)).sum()),
                                "net_mean": number(net[mask & (d.index.year == y)].mean()),
                                "increment": number(diff[mask & (d.index.year == y)].mean()),
                            }
                            for y in sorted(set(d.index.year))
                        ]
                        limitvalues = (
                            (d.Open.shift(-h - delay - 1) / fill * (1 - fee) / (1 + fee) - 1)
                            .iloc[chosen]
                            .dropna()
                        )
                        out.append(
                            (
                                {
                                    "signal": name,
                                    "horizon": h,
                                    "delay": delay,
                                    "fee": fee,
                                    "sensitivity": sensitivity,
                                    "events": len(values),
                                    "net_mean": number(values.mean()),
                                    "increment": number(diff[mask].mean()),
                                    "price_volume_control_increment": number(residual[mask].mean()),
                                    "nonoverlap_events": len(chosen),
                                    "nonoverlap_net": number(net.iloc[chosen].mean()),
                                    "limit_fills": len(limitvalues),
                                    "limit_per60": len(limitvalues) * 60 / len(d),
                                    "limit_net": number(limitvalues.mean()),
                                    "eligible": int(controlmask.sum()),
                                    "without_best5": number(values.sort_values().iloc[:-5].mean())
                                    if len(values) > 5
                                    else None,
                                    "without_2025": number(
                                        net[mask & (d.index.year != 2025)].mean()
                                    ),
                                    "positive_years": sum(
                                        x["increment"] is not None and x["increment"] > 0
                                        for x in yearly
                                    ),
                                },
                                yearly,
                            )
                        )
                    return out

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for results in pool.map(calc, s.columns):
                        for row, years in results:
                            records.append(row)
                            annual.extend(years)
            panel = pd.DataFrame(
                {
                    "net": ratio * 0.999 / 1.001 - 1,
                    "limit_net": limitnet,
                    "clean": clean,
                    "valid": eligible,
                },
                index=d.index,
            )
            panels.append((f"h{h}_delay{delay}", panel))
    # Dependent block permutation of primary-horizon association; adjustment across all signals.
    rng = np.random.default_rng(12015)
    y = panels[4][1]["net"]  # horizon5 delay0
    ic = []
    for name in s:
        mask = valid & y.notna() & valids[name]
        a = s.loc[mask, name].to_numpy(dtype=float)
        b = y[mask].to_numpy()
        observed = abs(spearmanr(a, b).statistic) if a.std() > 0 else 0.0
        years = d.index[mask].year.to_numpy()
        count = 0
        for _ in range(199):
            shuffled = b.copy()
            for year in np.unique(years):
                ids = np.flatnonzero(years == year)
                part = b[ids]
                blocks = [part[i : i + 20] for i in range(0, len(part), 20)]
                shuffled[ids] = np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
            value = abs(spearmanr(a, shuffled).statistic) if a.std() > 0 else 0.0
            count += value >= observed
        ic.append(
            {
                "signal": name,
                "ic": number(spearmanr(a, b).statistic) if a.std() > 0 else None,
                "p": (count + 1) / 200,
            }
        )
    order = sorted(range(len(ic)), key=lambda i: ic[i]["p"])
    q = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        q = min(q, ic[i]["p"] * len(ic) / rank)
        ic[i]["q"] = q
    return records, annual, ic, pd.concat(dict(panels), axis=1)


def number(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None
