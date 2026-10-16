"""Preregistered adaptive component removal and fixed-expression controls."""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from multiprocessing import get_context
from pathlib import Path
import json
import time

import numpy as np
import pandas as pd
from followup_models import fit, interval

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX004_20261016/first"


def main():
    started = time.monotonic()
    if (RUN / "followup_result.json").exists():
        raise RuntimeError("Review prior followup output before another run")
    binding = json.loads((EXPERIMENT / "protocols/published_followup.json").read_text(encoding="utf-8"))
    for name, path in (("followup-protocol", EXPERIMENT / "protocols/followup_protocol.json"),
                       ("followup_models.py", EXPERIMENT / "src/followup_models.py"),
                       ("followup_study.py", EXPERIMENT / "src/followup_study.py")):
        if sha256(path.read_bytes()).hexdigest() != binding[name]["sha256"]:
            raise RuntimeError("Followup changed after publication")
    protocol = json.loads((EXPERIMENT / "protocols/component_protocol.json").read_text(encoding="utf-8"))
    frame = pd.read_csv(RUN / "features.csv", index_col="signal")
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date))
    labels = pd.read_csv(RUN / "labels.csv")
    original = pd.read_csv(RUN / "predictions.csv")
    base = protocol["features"]["baseline"]
    models = {"tree-return-base": ("tree", "net_return", base, (3, 5, 10, 20)),
              "tree-risk-base": ("tree", "adverse", base, (3, 5, 10, 20))}
    comparisons = []
    for family in ("trend", "reversal", "risk"):
        target = "adverse" if family == "risk" else "net_return"
        name = "tree-" + family
        models[name] = ("tree", target, base + protocol["features"][family], (3, 5, 10, 20))
        comparisons.extend((name, horizon, "tree-risk-base" if family == "risk" else "tree-return-base", target) for horizon in (3, 5, 10, 20))
    for index, feature in enumerate(protocol["features"]["reversal"]):
        single, removal = f"reversal-single-{index}", f"reversal-remove-{index}"
        models[single] = ("ridge", "net_return", base + [feature], (3,))
        models[removal] = ("ridge", "net_return", base + [x for x in protocol["features"]["reversal"] if x != feature], (3,))
        comparisons.extend(((single, 3, "return-base", "net_return"), (removal, 3, "return-base", "net_return")))
    outputs, tasks = [original], []
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        task = ("tree", np.arange(120).reshape(40, 3).astype(float), np.arange(18).reshape(6, 3).astype(float), np.arange(40).astype(float))
        np.testing.assert_allclose(fit(task)["prediction"], pool.submit(fit, task).result()["prediction"], rtol=0, atol=1e-12)
        for name, (estimator, target, columns, horizons) in models.items():
            for horizon in horizons:
                eligible = labels.loc[labels.horizon.eq(horizon) & labels.maturity.ge(0)]
                for year in (2023, 2024, 2025, 2026):
                    first = int(np.flatnonzero(dates.year == year)[0])
                    train = eligible.loc[eligible.maturity.lt(first)]
                    test = eligible.loc[pd.to_datetime(eligible.signal_date).dt.year.eq(year)]
                    task = (estimator, frame.loc[train.signal, columns].to_numpy(), frame.loc[test.signal, columns].to_numpy(), train[target].to_numpy())
                    tasks.append((name, target, horizon, year, test, pool.submit(fit, task)))
        for name, target, horizon, year, test, future in tasks:
            result = future.result()
            threshold = float(np.quantile(result["train_prediction"], .25 if target == "adverse" else .75))
            selected = result["prediction"] <= threshold if target == "adverse" else result["prediction"] >= threshold
            out = test[["signal", "signal_date", "entry_filled", "net_return", "adverse", "exit_delay"]].copy()
            outputs.append(out.assign(model=name, horizon=horizon, year=year, prediction=result["prediction"], threshold=threshold, selected=selected))
        predictions = pd.concat(outputs, ignore_index=True)
        predictions.to_csv(RUN / "followup_predictions.csv", index=False)
        annual, jobs = [], []
        for name, horizon, baseline, target in comparisons:
            groups, yearly = [], []
            for year in (2023, 2024, 2025, 2026):
                left = predictions.loc[predictions.model.eq(name) & predictions.horizon.eq(horizon) & predictions.year.eq(year)].set_index("signal")
                right = predictions.loc[predictions.model.eq(baseline) & predictions.horizon.eq(horizon) & predictions.year.eq(year)].set_index("signal")
                assert left.index.equals(right.index)
                a, b = left.selected.to_numpy(), right.selected.to_numpy()
                row = {"model": name, "horizon": horizon, "year": year, "selected": int(a.sum()), "baseline_selected": int(b.sum())}
                if a.sum() == 0 or b.sum() == 0:
                    row.update(status="INSUFFICIENT_DATA", difference=None)
                else:
                    values = left[target].to_numpy() * (a / a.mean() - b / b.mean()) * (-1 if target == "adverse" else 1)
                    row.update(difference=float(values.mean()), mean_net_return=float(left.loc[a, "net_return"].mean()),
                               baseline_mean_net_return=float(right.loc[b, "net_return"].mean()),
                               fill_rate=float(left.loc[a, "entry_filled"].mean()))
                    groups.append(values)
                annual.append(row)
                yearly.append(row)
            jobs.append((name, horizon, yearly, pool.submit(interval, (groups, 13 + horizon)) if len(groups) == 4 else None))
        comparisons_out = []
        for name, horizon, yearly, future in jobs:
            values = future.result() if future else {"status": "INSUFFICIENT_DATA", "difference": None, "interval_95": None, "interval_familywise": None}
            values.update(model=name, horizon=horizon, positive_years=sum(x["difference"] is not None and x["difference"] > 0 for x in yearly))
            comparisons_out.append(values)
    pd.DataFrame(annual).to_csv(RUN / "followup_annual.csv", index=False)
    result = {"status": "ADAPTIVE_DIAGNOSTIC_COMPLETE", "comparisons": comparisons_out, "model_fits": len(tasks),
              "total_model_fits": 80 + len(tasks), "total_comparisons": 32, "seconds": time.monotonic() - started,
              "new_source_calls": 0, "strategy_account_evaluations": 0, "parameter_searches": 0,
              "precheck": "Fixed-tree serial/spawn predictions agree within 1e-12; original causal features and mature-label split reused.",
              "adaptive_selection": "Horizon-3 ablations and fixed-tree expression check chosen after initial weak results; same seen development sample."}
    (RUN / "followup_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (EXPERIMENT / "others/followup_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
