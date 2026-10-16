"""Predeclared walk-forward holding information study; no strategy account."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import time

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from components import BASE, GROUPS, MODELS, market_features, holding_features, fit_predict
from inputs import ROOT, EXPERIMENT, RUN, load


def check_binding():
    binding = json.loads((EXPERIMENT / "protocols/published_design.json").read_text(encoding="utf-8"))
    for name, ref_dict in binding.items():
        ref = EvidenceRef.from_dict(ref_dict)
        path = EXPERIMENT / ("protocols/design.json" if name == "design" else f"src/{name}.py")
        if path.read_bytes() != ref.resolve(ROOT).read_bytes():
            raise RuntimeError(f"Predeclared source changed: {name}")


def build_frame(data, dates, observation, decisions, labels):
    anchor, prices = observation[:2]
    market = market_features(data["stock.ohlcv"])
    # ATR and close must use identical normalized units for holding-path features.
    normalized_close = prices[:, 3]
    subset = decisions.loc[decisions.common & decisions.horizon.isin([5, 10, 20]) & decisions.checkpoint.eq("midpoint") & decisions.decision.ge(60)].copy()
    reference = labels.set_index(["signal", "horizon"])
    rows = []
    for row in subset.to_dict("records"):
        d, e, h, s = (int(row[k]) for k in ("decision", "entry", "horizon", "signal"))
        source = reference.loc[(s, h)]
        features = market.iloc[d].to_dict()
        features.update(holding_features(normalized_close, e, d, float(source.entry_price),
            int(source.quantity), float(market.atr.iloc[d]) / anchor))
        if abs(features["mark"] - row["known_mark_net"]) > 1e-11:
            raise AssertionError("Inherited mark does not replicate")
        a, m = int(row["earlier_exit"]), int(row["maturity"])
        earliest_price = (row["earlier_net"] * 100000 / source.quantity + source.entry_price * 1.001) / .999
        future_prices = np.r_[prices[a:m, 3], float(source.exit_price)]
        downside = min(0., float(future_prices.min() / earliest_price - 1))
        rows.append({**row, **features, "target": row["fixed_net"] - row["earlier_net"],
            "continuation_downside": downside, "decision_date": dates[d], "maturity_date": dates[m],
            "quantity": int(source.quantity), "entry_price": float(source.entry_price)})
    frame = pd.DataFrame(rows)
    if not np.isfinite(frame[BASE + sum(GROUPS.values(), [])].to_numpy()).all():
        raise AssertionError("Unexpected missing feature after warmup")
    return frame, market


def paired_intervals(frame, models):
    """Resample paired observations in chronological within-year blocks."""
    rng = np.random.default_rng(13)
    size = len(frame)
    names = [(name, comparator) for name in models for comparator in ("always-hold", "ridge-base")]
    deltas = np.column_stack([frame[f"chosen_{name}"].to_numpy() -
        (frame.fixed_net.to_numpy() if comparator == "always-hold" else frame.chosen_ridge_base.to_numpy())
        for name, comparator in names])
    distribution = np.zeros((5000, len(names)))
    for _, positions in frame.groupby("decision_year", sort=True).indices.items():
        n = len(positions)
        values = deltas[positions]
        for start in range(0, 5000, 100):
            origins = rng.integers(0, n, (100, int(np.ceil(n / 20))))
            indices = ((origins[:, :, None] + np.arange(20)) % n).reshape(100, -1)[:, :n]
            distribution[start:start + 100] += values[indices].sum(axis=1) / size
    rows = []
    for j, (name, comparator) in enumerate(names):
        v = deltas[:, j]
        no26 = frame.decision_year.ne(2026).to_numpy()
        ordered = np.sort(v)[::-1]
        rows.append({"model": name, "comparator": comparator, "n": size,
            "mean_difference": float(v.mean()), "without2026": float(v[no26].mean()),
            "drop_best3": float(ordered[3:].mean()),
            "interval95": np.quantile(distribution[:, j], [.025, .975]).tolist(),
            "interval_history156": np.quantile(distribution[:, j], [.05 / 312, 1 - .05 / 312]).tolist()})
    return rows


def precheck(data):
    source = data["stock.ohlcv"]
    complete = market_features(source)
    pd.testing.assert_frame_equal(complete.iloc[:800], market_features(source.iloc[:800]))
    changed = source.copy()
    for c in ("Open", "High", "Low", "Close", "Volume"):
        changed.loc[801:, c] *= 2
    pd.testing.assert_frame_equal(complete.iloc[:801], market_features(changed).iloc[:801])
    up = holding_features(np.array([10., 11., 12.]), 0, 2, 10., 100, 1.)
    down = holding_features(np.array([10., 9., 8.]), 0, 2, 10., 100, 1.)
    assert up["mark"] > 0 and up["mark_drawdown"] == 0
    assert down["mark"] < 0 and down["mark_drawdown"] > 0
    return ["feature_prefix", "future_price_volume_perturbation", "synthetic_gain_loss_path"]


def main():
    start = time.monotonic()
    if RUN.exists():
        raise RuntimeError("Preserve previous run")
    check_binding()
    data, dates, observation, decisions, labels, prior = load()
    checks = precheck(data)
    frame, market = build_frame(data, dates, observation, decisions, labels)
    # Restore the current experiment to the import front before spawning.
    import sys
    sys.path.insert(0, str(EXPERIMENT / "src"))
    output, splits, fits = [], [], 0
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        task = ("ridge-base", np.arange(24).reshape(8, 3), np.ones((2, 3)), np.arange(8))
        np.testing.assert_allclose(fit_predict(task), pool.submit(fit_predict, task).result(), rtol=0, atol=0)
        checks.append("serial_spawn_equal")
        for horizon in (5, 10, 20):
            available = frame.loc[frame.horizon.eq(horizon)].sort_values("decision")
            for year in (2023, 2024, 2025, 2026):
                test = available.loc[available.decision_year.eq(year)].copy()
                cutoff = test.decision.min()
                train = available.loc[available.maturity.lt(cutoff)]
                assert len(train) and train.maturity.max() < test.decision.min()
                splits.append({"horizon": horizon, "year": year, "train": len(train), "test": len(test),
                    "last_training_maturity": int(train.maturity.max()), "first_test_decision": int(cutoff)})
                jobs = {name: pool.submit(fit_predict, (name, train[cols].to_numpy(), test[cols].to_numpy(), train.target.to_numpy()))
                        for name, cols in MODELS.items()}
                predictions = {name: job.result() for name, job in jobs.items()}
                fits += len(jobs)
                predictions.update({"training-mean": np.full(len(test), train.target.mean()),
                    "rule-trend": np.where(test.trend_preserved, 1., -1.),
                    "rule-support": np.where(test.support_intact, 1., -1.)})
                for name, pred in predictions.items():
                    key = name.replace("-", "_")
                    test[f"prediction_{key}"] = pred
                    test[f"continue_{key}"] = pred > 0
                    test[f"chosen_{key}"] = np.where(pred > 0, test.fixed_net, test.earlier_net)
                output.append(test)
    predicted = pd.concat(output, ignore_index=True)
    names = [x.replace("-", "_") for x in [*MODELS, "training-mean", "rule-trend", "rule-support"]]
    annual, comparisons = [], []
    for h, part in predicted.groupby("horizon"):
        comparisons.extend({"horizon": int(h), **r} for r in paired_intervals(part.sort_values("decision").reset_index(drop=True), names))
        for year, group in [("ALL", part), *list(part.groupby("decision_year"))]:
            for name in names:
                cont = group[f"continue_{name}"]
                chosen, base = group[f"chosen_{name}"], group.chosen_ridge_base
                annual.append({"horizon": int(h), "year": str(year), "model": name, "n": len(group),
                    "continue_n": int(cont.sum()), "exit_n": int((~cont).sum()),
                    "mean_choice": float(chosen.mean()), "mean_fixed": float(group.fixed_net.mean()),
                    "difference_hold": float((chosen - group.fixed_net).mean()), "difference_base": float((chosen - base).mean()),
                    "mae": float((group[f"prediction_{name}"] - group.target).abs().mean()) if not name.startswith("rule_") else None,
                    "continue_label": float(group.loc[cont, "target"].mean()) if cont.any() else None,
                    "exit_label": float(group.loc[~cont, "target"].mean()) if (~cont).any() else None,
                    "forgone_positive_gain": float(np.where(~cont, group.target.clip(lower=0), 0).mean()),
                    "avoided_negative_gain": float(np.where(~cont, -group.target.clip(upper=0), 0).mean()),
                    "chosen_downside": float(np.where(cont, group.continuation_downside, 0).mean()),
                    "always_hold_downside": float(group.continuation_downside.mean())})
    RUN.mkdir(parents=True)
    frame.to_csv(RUN / "observations.csv", index=False)
    market.to_csv(RUN / "market_features.csv", index_label="session")
    predicted.to_csv(RUN / "predictions.csv", index=False)
    pd.DataFrame(annual).to_csv(EXPERIMENT / "others/annual.csv", index=False)
    result = {"status": "COMPUTED", "observations": len(frame), "test_observations": len(predicted),
        "fits": fits, "comparisons": comparisons, "splits": splits, "prechecks": checks,
        "new_source_calls": 0, "strategy_accounts": 0, "new_nominal_contrasts": len(comparisons),
        "nominal_history": 78 + len(comparisons), "seconds": time.monotonic() - start,
        "limits": "Adaptively designed on fully seen development pool; overlapping independent holding decisions, no account/economic acceptance; source publication and revision history unverified"}
    assert fits == 120 and len(comparisons) == 78 and result["seconds"] < 7200
    (EXPERIMENT / "others/computation_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("comparisons", "splits")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
