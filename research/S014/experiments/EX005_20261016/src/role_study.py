"""Follow the distinct amplitude and next-session execution hypotheses."""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from multiprocessing import get_context
from pathlib import Path
import json
import time

import numpy as np
import pandas as pd
import requests
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvidenceRef, EvaluationResources
from methods import association
from role_methods import true_range, amplitude_target, fit_amplitude, error_interval
from study import fetch_inputs, read_frame

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX005_20261016/roles"


def main():
    started = time.monotonic()
    if (RUN / "result.json").exists():
        raise RuntimeError("Completed followup must be preserved")
    binding = json.loads((EXPERIMENT / "protocols/published_roles.json").read_text(encoding="utf-8"))
    for key, path in (("role-protocol", EXPERIMENT / "protocols/role_followup.json"), ("role-methods", EXPERIMENT / "src/role_methods.py"), ("role-study", Path(__file__))):
        ref = EvidenceRef.from_dict(binding[key])
        ref.resolve(ROOT)
        if sha256(path.read_bytes()).hexdigest() != ref.sha256:
            raise RuntimeError("Published followup changed")
    prior = json.loads((ROOT / "research/S014/experiments/EX004_20261016/others/result.json").read_text(encoding="utf-8"))
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"), resources=EvaluationResources(2, 1, 13))
    original = requests.sessions.Session.request

    def prohibit(*args, **kwargs):
        raise RuntimeError("No source calls authorized for this experiment")

    requests.sessions.Session.request = prohibit
    try:
        inputs, dates = fetch_inputs(context, prior)
    finally:
        requests.sessions.Session.request = original
    features = read_frame(prior, "features").set_index("signal")
    bars = inputs["stock.ohlcv"]
    ranges = true_range(bars)
    prefix = true_range(bars.iloc[:800])
    np.testing.assert_allclose(ranges.iloc[:800], prefix, equal_nan=True, rtol=0, atol=0)
    for horizon in (1, 3, 5):
        np.testing.assert_allclose(amplitude_target(ranges, horizon).iloc[:800 - horizon],
                                   amplitude_target(prefix, horizon).iloc[:800 - horizon], equal_nan=True)
    features["atr20"] = ranges.rolling(20, min_periods=20).mean()
    base = ["ret_1", "ret_5", "ret_20", "range_1", "volume_ratio_5_20"]
    forecasts, tasks, annual, comparisons = [], [], [], []
    RUN.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        synthetic = (np.arange(120).reshape(40, 3).astype(float), np.arange(30).reshape(10, 3).astype(float), np.linspace(0, .1, 40))
        np.testing.assert_allclose(fit_amplitude(synthetic)[1], pool.submit(fit_amplitude, synthetic).result()[1], atol=1e-12, rtol=0)
        for horizon in (1, 3, 5):
            target = amplitude_target(ranges, horizon)
            eligible = np.flatnonzero((np.arange(len(dates)) >= 20) & target.notna().to_numpy())
            for year in (2023, 2024, 2025, 2026):
                first = int(np.flatnonzero(dates.year == year)[0])
                train = eligible[eligible + horizon < first]
                test = eligible[dates[eligible].year == year]
                assert (train + horizon < first).all()
                for model, columns in (("baseline", base), ("atr20", base + ["atr20"])):
                    task = (features.loc[train, columns].to_numpy(), features.loc[test, columns].to_numpy(), target.loc[train].to_numpy())
                    tasks.append((model, horizon, year, train, test, target, first, pool.submit(fit_amplitude, task)))
        for model, horizon, year, train, test, target, first, future in tasks:
            training_scores, scores = future.result()
            thresholds = np.quantile(training_scores, [.25, .75])
            part = pd.DataFrame({"signal": test, "signal_date": dates[test], "year": year, "horizon": horizon,
                "model": model, "prediction": scores, "actual": target.loc[test].to_numpy(),
                "train_rows": len(train), "train_last_maturity": int((train + horizon).max()), "first_test_signal": first,
                "low_score": scores <= thresholds[0], "high_score": scores >= thresholds[1]})
            forecasts.append(part)
            low, high = part.loc[part.low_score], part.loc[part.high_score]
            annual.append({"model": model, "horizon": horizon, "year": year, "dates": len(test),
                "mean_absolute_error": float((part.prediction - part.actual).abs().mean()),
                "spearman": association(scores, part.actual), "low_count": len(low), "high_count": len(high),
                "low_mean_amplitude": float(low.actual.mean()) if len(low) else None,
                "high_mean_amplitude": float(high.actual.mean()) if len(high) else None})
        forecast_frame = pd.concat(forecasts, ignore_index=True)
        jobs = []
        for horizon in (1, 3, 5):
            groups = []
            for year in (2023, 2024, 2025, 2026):
                base_rows = forecast_frame.loc[forecast_frame.model.eq("baseline") & forecast_frame.horizon.eq(horizon) & forecast_frame.year.eq(year)].set_index("signal")
                augmented = forecast_frame.loc[forecast_frame.model.eq("atr20") & forecast_frame.horizon.eq(horizon) & forecast_frame.year.eq(year)].set_index("signal")
                assert base_rows.index.equals(augmented.index)
                groups.append(((base_rows.prediction - base_rows.actual).abs() - (augmented.prediction - augmented.actual).abs()).to_numpy())
            jobs.append((horizon, pool.submit(error_interval, (groups, 13 + horizon))))
        for horizon, future in jobs:
            result = future.result()
            result.update(horizon=horizon, metric="absolute_amplitude_forecast_error_reduction")
            comparisons.append(result)
    # The next-session fill label is observed even if its later return horizon is censored.
    labels = read_frame(prior, "labels")
    entry = labels.loc[labels.horizon.eq(3), ["signal", "signal_date", "entry_filled", "entry_reason"]].copy()
    raw, bounds = inputs["stock.unadjusted_daily"], inputs["security.price_limits"]
    entry["limit_close"] = (raw.Close - bounds.UpLimit).abs().le(.005).to_numpy()[entry.signal]
    entry["year"] = pd.to_datetime(entry.signal_date).dt.year
    execution = []
    for period, frame in [("training2020-2022", entry.loc[entry.year < 2023]), ("test2023-2026", entry.loc[entry.year >= 2023])]:
        for group_name, where in (("limit_close", frame.limit_close), ("other", ~frame.limit_close)):
            part = frame.loc[where]
            execution.append({"period": period, "group": group_name, "count": len(part), "nonfills": int((~part.entry_filled).sum()),
                              "nonfill_rate": float((~part.entry_filled).mean()) if len(part) else None})
    for year, frame in entry.loc[entry.year >= 2023].groupby("year"):
        for group_name, where in (("limit_close", frame.limit_close), ("other", ~frame.limit_close)):
            part = frame.loc[where]
            execution.append({"period": str(year), "group": group_name, "count": len(part), "nonfills": int((~part.entry_filled).sum()),
                              "nonfill_rate": float((~part.entry_filled).mean()) if len(part) else None})
    for name, frame in (("amplitude_forecasts", forecast_frame), ("amplitude_annual", pd.DataFrame(annual)),
                        ("execution_observations", entry), ("execution_summary", pd.DataFrame(execution)),
                        ("amplitude_features", features[["atr20"]].assign(signal_date=dates, true_range=ranges))):
        frame.to_csv(RUN / f"{name}.csv", index_label="row")
    result = {"status": "COMPUTED", "comparisons": comparisons, "execution_summary": execution, "model_fits": len(tasks),
        "primary_comparisons": 4, "total_new_primary_comparisons": 24, "parameter_searches": 0, "strategy_accounts": 0, "new_source_calls": 0,
        "workers": 2, "native_threads_per_worker": 1, "seconds": time.monotonic() - started,
        "precheck": "Native pinned identity, serial/spawn amplitude predictions, range/target prefix and all label maturities PASS",
        "limits": "Adaptive same-development-pool role separation; market amplitude is not account loss; execution proportions do not prove profit benefit"}
    for path in (RUN / "result.json", EXPERIMENT / "others/role_result.json"):
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
