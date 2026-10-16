"""Discriminate a gap-repair clue from ordinary up candles and event overlap."""
import json
import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from features import BASE
from inputs import ROOT, EXPERIMENT, RUN, load


def contrasts(part, value):
    gap, session = part.gap.to_numpy(), part.intraday.to_numpy()
    masks = [(gap < 0) & (session > 0), (gap < 0) & (session <= 0),
             (gap >= 0) & (session > 0), (gap >= 0) & (session <= 0)]
    means = [float(value[m].mean()) if m.any() else np.nan for m in masks]
    a, b, c, d = means
    return np.array([a - c, (a - b) - (c - d), a - value.mean(), a - b]), masks


def main():
    if (EXPERIMENT / "others/followup_result.json").exists():
        raise RuntimeError("Preserve completed follow-up")
    binding = json.loads((EXPERIMENT / "protocols/followup_published.json").read_text(encoding="utf-8"))
    for name, value in binding.items():
        path = EXPERIMENT / ("protocols/followup_design.json" if name == "followup-design" else "src/followup.py")
        if EvidenceRef.from_dict(value).resolve(ROOT).read_bytes() != path.read_bytes():
            raise RuntimeError("Follow-up source changed")
    data, dates, observation, _, _, _ = load()
    prices = observation[1]
    initial = json.loads((EXPERIMENT / "others/computation_result.json").read_text(encoding="utf-8"))
    splits = {(r["horizon"], r["year"]): r for r in initial["splits"]}
    frame = pd.read_csv(RUN / "predictions.csv")
    market = pd.read_csv(RUN / "features.csv")
    labels = pd.read_csv(RUN / "labels.csv")
    rows, matches, cash, counter, comparisons = [], [], [], [], []
    rng = np.random.default_rng(13)
    for h in (1, 3):
        selected = frame.loc[frame.horizon.eq(h)].sort_values("signal").reset_index(drop=True)
        for mode in ("raw", "residual"):
            distribution = np.zeros((5000, 4))
            valid = np.ones(5000, dtype=bool)
            point, no26, drop3 = np.zeros(4), np.zeros(4), np.zeros(4)
            all_n, no26_n = len(selected), int(selected.year.ne(2026).sum())
            for year, part in selected.groupby("year", sort=True):
                y = part.net_return.to_numpy()
                if mode == "residual":
                    y = y - part.prediction_ridge_base.to_numpy()
                estimate, masks = contrasts(part, y)
                point += estimate * len(part) / all_n
                if year != 2026:
                    no26 += estimate * len(part) / no26_n
                # Removing favorable A outcomes is deliberately adverse to the clue.
                a = masks[0]
                a_values = np.sort(y[a])[::-1][3:]
                means = [float(y[m].mean()) for m in masks]
                trimmed_a = float(a_values.mean())
                drop3 += np.array([trimmed_a - means[2], (trimmed_a - means[1]) - (means[2] - means[3]),
                                  trimmed_a - float(y.mean()), trimmed_a - means[1]]) * len(part) / all_n
                sessions = part.signal.to_numpy(dtype=int)
                first, last = sessions.min(), sessions.max()
                grid = np.zeros((last - first + 1, 10))
                grid[sessions - first] = np.column_stack([*[y * m for m in masks], *masks, y, np.ones(len(part))])
                n = len(grid)
                for batch in range(0, 5000, 100):
                    origins = rng.integers(0, n, (100, int(np.ceil(n / 20))))
                    idx = ((origins[:, :, None] + np.arange(20)) % n).reshape(100, -1)[:, :n]
                    sums = grid[idx].sum(axis=1)
                    good = (sums[:, 4:8] > 0).all(axis=1)
                    valid[batch:batch + 100] &= good
                    m = np.divide(sums[:, :4], sums[:, 4:8], out=np.full((100, 4), np.nan), where=sums[:, 4:8] > 0)
                    va, vb, vc, vd = m.T
                    v = np.column_stack([va - vc, (va - vb) - (vc - vd), va - sums[:, 8] / sums[:, 9], va - vb])
                    distribution[batch:batch + 100] += v * len(part) / all_n
                if mode == "raw":
                    for cell, mask in zip("ABCD", masks):
                        g = part.loc[mask]
                        rows.append({"horizon": h, "year": int(year), "cell": cell, "n": len(g), "fills": int(g.entry_filled.sum()),
                            "net_mean": float(g.net_return.mean()), "ret1_mean": float(g.ret1.mean()),
                            "range_mean": float(g.range.mean()), "intraday_mean": float(g.intraday.mean())})
                    for diagnostic, eligible in (("exclude-cap-touch", part.loc[part.upper_close.eq(0) & part.upper_failure.eq(0) & part.lower_recovery.eq(0) & part.lower_close.eq(0)]),
                                                   ("decluster-11", part)):
                        if diagnostic == "decluster-11":
                            pieces = []
                            for mask in masks:
                                last_origin = -999
                                keep = []
                                for i, s in zip(part.index[mask], part.loc[mask, "signal"]):
                                    if s - last_origin > 10:
                                        keep.append(i)
                                        last_origin = s
                                pieces.append(part.loc[keep])
                            eligible = pd.concat(pieces).sort_values("signal")
                        effect, cells = contrasts(eligible, eligible.net_return.to_numpy())
                        counter.append({"horizon": h, "year": int(year), "diagnostic": diagnostic,
                            "counts": [int(x.sum()) for x in cells], "A-C": float(effect[0]), "interaction": float(effect[1]),
                            "A-all": float(effect[2]), "A-B": float(effect[3])})
            for j, name in enumerate(("A-C", "interaction", "A-all", "A-B")):
                draws = distribution[valid, j]
                comparisons.append({"horizon": h, "mode": mode, "comparison": name, "difference": float(point[j]),
                    "without2026": float(no26[j]), "drop3A_per_year": float(drop3[j]),
                    "interval95": np.quantile(draws, [.025, .975]).tolist(),
                    "interval_history296": np.quantile(draws, [.05 / 592, 1 - .05 / 592]).tolist(), "valid_fraction": float(valid.mean())})
        # Same-year covariate matching is an explanation diagnostic, never a trade input.
        for year, part in selected.groupby("year", sort=True):
            _, masks = contrasts(part, part.net_return.to_numpy())
            a, c = part.loc[masks[0]], part.loc[masks[2]]
            train = labels.loc[labels.horizon.eq(h) & labels.signal.ge(60) & labels.maturity.ge(0) &
                labels.maturity.lt(splits[(h, year)]["first_test_signal"])]
            cols = BASE + ["intraday"]
            historical = market.iloc[train.signal.astype(int)][cols].to_numpy()
            scale = historical.std(axis=0)
            scale[scale < 1e-12] = 1.
            distance = np.sqrt((((a[cols].to_numpy()[:, None, :] - c[cols].to_numpy()[None, :, :]) / scale) ** 2).sum(axis=2))
            best = distance.argmin(axis=1)
            for i, (_, row) in enumerate(a.iterrows()):
                if distance[i, best[i]] <= 1:
                    control = c.iloc[best[i]]
                    matches.append({"horizon": h, "year": int(year), "signal_A": int(row.signal), "signal_C": int(control.signal),
                        "distance": float(distance[i, best[i]]), "net_A": row.net_return, "net_C": control.net_return,
                        "difference": row.net_return - control.net_return})
            for _, row in part.iterrows():
                if not row.entry_filled:
                    continue
                e, q = int(row.entry), int(row.quantity)
                first_day = q * (prices[e, 3] - row.entry_price) / 100000
                later = q * (row.exit_price - prices[e, 3]) / 100000
                fees = q * (row.entry_price + row.exit_price) * .001 / 100000
                assert abs(first_day + later - fees - row.net_return) < 1e-11
                cash.append({"horizon": h, "year": int(year), "signal": int(row.signal), "A": bool(row.gap_down_repair),
                    "first_holding_day_price_effect": float(first_day), "later_price_effect": float(later),
                    "fees": float(fees), "actual_net": row.net_return})
    pd.DataFrame(rows).to_csv(EXPERIMENT / "others/followup_cells.csv", index=False, lineterminator="\n")
    pd.DataFrame(matches).to_csv(RUN / "matched_controls.csv", index=False, lineterminator="\n")
    pd.DataFrame(cash).to_csv(RUN / "cash_attribution.csv", index=False, lineterminator="\n")
    result = {"comparisons": comparisons, "counterevidence": counter, "matches": len(matches),
        "cash_identities": len(cash), "new_nominal_contrasts": 16, "nominal_history": 296,
        "new_fits": 0, "source_calls": 0, "strategy_accounts": 0,
        "limitations": "Adaptive mechanism follow-up on seen pool; matching reuses C controls and may use later same-year covariates for analysis only; no signal uses matches; no causal or independent validation claim"}
    (EXPERIMENT / "others/followup_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("comparisons", "counterevidence")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
