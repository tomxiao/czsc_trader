"""Matured-outcome online learning; fixed memory contrasts, no parameter search."""
import json
import time

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from components import market_features
from inputs import ROOT, EXPERIMENT, RUN, load

FEATURES = ["ret1", "ret5", "ret20", "tr", "volume_ratio"]
MODELS = ["annual", "expanding", "recent126", "recent252", "mean126", "mean252"]


def weighted_predict(x, y, current, weights, mean_only=False):
    center = float(np.average(y, weights=weights))
    if mean_only:
        return center
    mean = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average((x - mean) ** 2, axis=0, weights=weights))
    scale[scale < 1e-12] = 1.
    left, right = (x - mean) / scale, (current - mean) / scale
    coefficient = np.linalg.solve((left * weights[:, None]).T @ left + 10 * np.eye(x.shape[1]),
                                  left.T @ ((y - center) * weights))
    return float(right @ coefficient + center)


def main():
    start = time.monotonic()
    if (EXPERIMENT / "others/online_result.json").exists():
        raise RuntimeError("Preserve completed result")
    binding = json.loads((EXPERIMENT / "protocols/followup_published.json").read_text(encoding="utf-8"))
    for name, ref in binding.items():
        path = EXPERIMENT / ("protocols/followup_design.json" if name == "followup-design" else "src/online.py")
        if path.read_bytes() != EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes():
            raise RuntimeError("Online design or source changed")
    data, dates, _, _, labels, _ = load()
    market = market_features(data["stock.ohlcv"])
    rows, split_rows, fits = [], [], 0
    for horizon in (5, 10):
        frame = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0) & labels.signal.ge(60)].sort_values("signal").copy()
        x = market.iloc[frame.signal.astype(int)][FEATURES].to_numpy()
        y = frame.net_return.to_numpy()
        signals, maturity = frame.signal.to_numpy(dtype=int), frame.maturity.to_numpy(dtype=int)
        years = np.array([dates[i].year for i in signals])
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise AssertionError("Nonfinite mature entry input")
        annual = {}
        for year in (2023, 2024, 2025, 2026):
            first = int(signals[years == year].min())
            annual[year] = maturity < first
        for i in np.flatnonzero(years >= 2023):
            s, yr = int(signals[i]), int(years[i])
            matured = maturity < s
            age = s - signals[matured]
            pred = {}
            for name in MODELS:
                mask = annual[yr] if name == "annual" else matured
                weights = np.ones(int(mask.sum()))
                if name.endswith("126") or name.endswith("252"):
                    half_life = 126 if name.endswith("126") else 252
                    weights = np.exp2(-age / half_life)
                pred[name] = weighted_predict(x[mask], y[mask], x[i], weights, name.startswith("mean"))
                if not name.startswith("mean"):
                    fits += 1
            split_rows.append({"signal": s, "horizon": horizon, "latest_maturity": int(maturity[matured].max()),
                "latest_annual_maturity": int(maturity[annual[yr]].max()), "year_first_signal": int(signals[years == yr].min()),
                "train": int(matured.sum()), "annual_train": int(annual[yr].sum())})
            record = {"signal": s, "signal_date": dates[s], "year": yr, "horizon": horizon,
                "net": float(y[i]), "filled": bool(frame.iloc[i].entry_filled), "maturity": int(maturity[i]),
                "occupation": int(maturity[i] - s) if bool(frame.iloc[i].entry_filled) else 0}
            for name, value in pred.items():
                record[f"pred_{name}"] = value
                record[f"take_{name}"] = value > 0
                record[f"chosen_{name}"] = float(y[i]) if value > 0 else 0.
            rows.append(record)
    output = pd.DataFrame(rows)
    summaries, contrasts = [], []
    rng = np.random.default_rng(13)
    for h, part in output.groupby("horizon", sort=True):
        part = part.sort_values("signal").reset_index(drop=True)
        # All contrasts use common origin sessions and the same resampling weights.
        keys = [(model, comparator) for model in MODELS for comparator in ("always-enter", "annual", "local-mean")]
        deltas = np.column_stack([part[f"chosen_{model}"].to_numpy() -
            (part.net.to_numpy() if comparator == "always-enter" else part.chosen_annual.to_numpy() if comparator == "annual"
             else part[f"chosen_mean{252 if model.endswith('252') else 126}"].to_numpy()) for model, comparator in keys])
        distribution = np.zeros((5000, len(keys)))
        counts = np.zeros(5000)
        for _, positions in part.groupby("year", sort=True).indices.items():
            first, last = int(part.signal.iloc[positions].min()), int(part.signal.iloc[positions].max())
            grid = np.zeros((last - first + 1, len(keys)))
            observed = np.zeros(len(grid))
            slots = part.signal.iloc[positions].to_numpy(dtype=int) - first
            grid[slots] = deltas[positions]
            observed[slots] = 1
            n = len(grid)
            for start_block in range(0, 5000, 100):
                origins = rng.integers(0, n, (100, int(np.ceil(n / 20))))
                idx = ((origins[:, :, None] + np.arange(20)) % n).reshape(100, -1)[:, :n]
                distribution[start_block:start_block + 100] += grid[idx].sum(axis=1)
                counts[start_block:start_block + 100] += observed[idx].sum(axis=1)
        distribution /= counts[:, None]
        for j, (model, comparator) in enumerate(keys):
            delta = deltas[:, j]
            contrasts.append({"horizon": int(h), "model": model, "comparator": comparator,
                "n": len(part), "difference": float(delta.mean()),
                "without2026": float(delta[part.year.ne(2026)].mean()),
                "drop_best3": float(np.sort(delta)[::-1][3:].mean()),
                "interval95": np.quantile(distribution[:, j], [.025, .975]).tolist(),
                "interval_history192": np.quantile(distribution[:, j], [.05 / 384, 1 - .05 / 384]).tolist()})
        for year, g in [("ALL", part), *list(part.groupby("year"))]:
            for model in MODELS:
                take = g[f"take_{model}"]
                summaries.append({"horizon": int(h), "year": str(year), "model": model, "n": len(g),
                    "take_n": int(take.sum()), "filled_n": int((take & g.filled).sum()),
                    "mean_chosen": float(g[f"chosen_{model}"].mean()), "mean_always_enter": float(g.net.mean()),
                    "difference_enter": float((g[f"chosen_{model}"] - g.net).mean()),
                    "difference_annual": float((g[f"chosen_{model}"] - g.chosen_annual).mean()),
                    "mae": float((g[f"pred_{model}"] - g.net).abs().mean()),
                    "selected_net": float(g.loc[take, "net"].mean()) if take.any() else None,
                    "mean_occupation": float(np.where(take, g.occupation, 0).mean())})
    output.to_csv(RUN / "online_predictions.csv", index=False)
    pd.DataFrame(split_rows).to_csv(RUN / "online_splits.csv", index=False)
    pd.DataFrame(summaries).to_csv(EXPERIMENT / "others/online_annual.csv", index=False)
    result = {"fits": fits, "contrast_count": len(contrasts), "nominal_history": 192,
        "comparisons": contrasts, "rows": len(output), "seconds": time.monotonic() - start,
        "source_calls": 0, "strategy_accounts": 0, "no_parameter_search": True,
        "limits": "Adaptively selected mechanism on seen development pool, half-life sensitivity not independent validation; independent attempts not a continuous account"}
    assert len(contrasts) == 36
    (EXPERIMENT / "others/online_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "comparisons"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
