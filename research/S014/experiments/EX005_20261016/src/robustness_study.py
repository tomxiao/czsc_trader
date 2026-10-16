"""Challenge the new bounded roles with simpler controls and event concentration."""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from multiprocessing import get_context
from pathlib import Path
import json

import numpy as np
import pandas as pd
from czsc_trader.research_tools import EvidenceRef
from methods import association
from role_methods import amplitude_target
from robustness_methods import error_interval62, execution_interval

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = ROOT / "research/S014/assets/runs/EX005_20261016/roles"


def main():
    if (EXPERIMENT / "others/robustness_result.json").exists():
        raise RuntimeError("Robustness result already preserved")
    binding = json.loads((EXPERIMENT / "protocols/published_robustness.json").read_text(encoding="utf-8"))
    for key, path in (("robustness-protocol", EXPERIMENT / "protocols/robustness.json"),
                      ("robustness-methods", EXPERIMENT / "src/robustness_methods.py"), ("robustness-study", Path(__file__))):
        reference = EvidenceRef.from_dict(binding[key])
        reference.resolve(ROOT)
        if sha256(path.read_bytes()).hexdigest() != reference.sha256:
            raise RuntimeError("Robustness design changed")
    for key, filename in (("amplitude-inputs", "amplitude_features.csv"), ("amplitude-forecasts", "amplitude_forecasts.csv"), ("execution-inputs", "execution_observations.csv")):
        reference = EvidenceRef.from_dict(binding[key])
        if (RUN / filename).read_bytes() != reference.resolve(ROOT).read_bytes():
            raise RuntimeError("Input output changed after publication")
    inputs = pd.read_csv(RUN / "amplitude_features.csv", index_col="row")
    forecasts = pd.read_csv(RUN / "amplitude_forecasts.csv")
    annual, results, jobs = [], [], []
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        sample = [np.linspace(-.01, .02, 60), np.linspace(0, .01, 60)]
        assert error_interval62((sample, 13)) == pool.submit(error_interval62, (sample, 13)).result()
        for horizon in (1, 3, 5):
            target = amplitude_target(inputs.true_range, horizon)
            all_groups = {"atr20-vs-current": [], "fitted-vs-atr20": [], "fitted-vs-baseline": []}
            for year in (2023, 2024, 2025, 2026):
                base = forecasts.loc[forecasts.model.eq("baseline") & forecasts.horizon.eq(horizon) & forecasts.year.eq(year)].set_index("signal")
                fitted = forecasts.loc[forecasts.model.eq("atr20") & forecasts.horizon.eq(horizon) & forecasts.year.eq(year)].set_index("signal")
                signal = base.index
                actual = target.loc[signal].to_numpy()
                np.testing.assert_allclose(actual, base.actual, atol=1e-12, rtol=0)
                options = {"current": inputs.loc[signal, "true_range"].to_numpy(), "atr20": inputs.loc[signal, "atr20"].to_numpy(),
                           "fitted": fitted.prediction.to_numpy(), "baseline": base.prediction.to_numpy()}
                losses = {name: np.abs(values - actual) for name, values in options.items()}
                for name, values in options.items():
                    annual.append({"model": name, "horizon": horizon, "year": year, "dates": len(signal),
                                   "mae": float(losses[name].mean()), "spearman": association(values, actual)})
                all_groups["atr20-vs-current"].append(losses["current"] - losses["atr20"])
                all_groups["fitted-vs-atr20"].append(losses["atr20"] - losses["fitted"])
                all_groups["fitted-vs-baseline"].append(losses["baseline"] - losses["fitted"])
            for name, groups in all_groups.items():
                jobs.append((name, horizon, pool.submit(error_interval62, (groups, 13 + horizon))))
        for name, horizon, future in jobs:
            result = future.result()
            result.update(comparison=name, horizon=horizon)
            results.append(result)
    entry = pd.read_csv(RUN / "execution_observations.csv")
    test = entry.loc[entry.year >= 2023]
    groups = [(part.limit_close.to_numpy(), ~part.entry_filled.to_numpy()) for _, part in test.groupby("year")]
    execution = execution_interval(groups)
    execution["difference"] = float((~test.loc[test.limit_close, "entry_filled"]).mean() - (~test.loc[~test.limit_close, "entry_filled"]).mean())
    execution["leave_one_year_out"] = {}
    for year in (2023, 2024, 2025, 2026):
        remaining = test.loc[test.year != year]
        execution["leave_one_year_out"][str(year)] = float((~remaining.loc[remaining.limit_close, "entry_filled"]).mean() - (~remaining.loc[~remaining.limit_close, "entry_filled"]).mean())
    pd.DataFrame(annual).to_csv(EXPERIMENT / "others/persistence_controls.csv", index=False)
    result = {"status": "COMPUTED", "comparisons": results, "execution": execution,
              "new_comparisons": 6, "rechecked_comparisons": 4, "primary_comparison_history": 62,
              "new_model_fits": 0, "source_calls": 0, "parameter_searches": 0, "strategy_accounts": 0,
              "precheck": "Serial/spawn paired interval equality and published exact input bytes PASS",
              "limits": "Family62 intervals do not remove adaptive-selection or data-publication limitations"}
    (EXPERIMENT / "others/robustness_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
