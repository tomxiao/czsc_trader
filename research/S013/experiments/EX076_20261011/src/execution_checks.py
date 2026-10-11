"""Synthetic fixed-input and reading guard checks. Never invoke analyze."""
# ruff: noqa: E402 -- limits before numeric imports.
import os
for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"
import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd
import component
import driver
import input_authentication as adapter
import labels as label_formula
import reading
import curvature_statistics as statistics

HERE = Path(__file__).resolve().parent
checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)


def reject(name, fn):
    try:
        fn()
    except (ValueError, AssertionError, TypeError):
        checks.append(name)
    else:
        raise AssertionError(name)


def main():
    rng = np.random.default_rng(13)
    possible = pd.bdate_range("2020-01-02", "2026-09-30").as_unit("ns")
    sessions = possible[np.linspace(0, len(possible)-1, 1636, dtype=int)]
    grid = sessions[:-1].rename("signal_date")
    anchor = pd.Timestamp("2019-12-31")
    warm_axis = pd.bdate_range("2019-04-10", "2019-12-30").append(pd.DatetimeIndex([anchor])).append(grid)
    close = 5*np.exp(np.cumsum(rng.normal(0, .01, len(warm_axis))))
    warm = pd.DataFrame({"Open": close*np.exp(rng.normal(0, .005, len(close))), "Close": close}, index=warm_axis)
    warm.index.name = "signal_date"
    full_axis = pd.DatetimeIndex([anchor]).append(sessions).rename("signal_date")
    prices = warm.reindex(full_axis).copy()
    prices.iloc[-1] = prices.iloc[-2].to_numpy()*1.01
    native = pd.DataFrame({"open": prices.Open/.2803, "high": np.maximum(prices.Open, prices.Close)/.2803*1.01,
                           "low": np.minimum(prices.Open, prices.Close)/.2803*.99, "close": prices.Close/.2803,
                           "vol": np.full(len(prices), 500.0), "amount": np.full(len(prices), 2000.0)}, index=full_axis)
    daily = native.reset_index().rename(columns={"signal_date": "dt"})
    daily["dt"] = daily.dt.dt.as_unit("us")
    old66 = pd.DataFrame(rng.normal(size=(len(grid), 14)), index=grid, columns=statistics.CONTROLS[:14])
    observation = component.build_features(warm).reindex(grid)
    old66["volatility20"] = observation.volatility20
    old61 = old66.join(pd.DataFrame(rng.normal(size=(len(grid), 2)), index=grid, columns=statistics.CONTROLS[14:16]))
    old69 = old61.join(observation[["short_stretch4"]])
    old66["late_weakness"], old66["early_reclaim_weakness"] = -old61.late_recovery, -old61.early_volume_reclaim
    labels = label_formula.fee_labels4(native.rename(columns={"open": "Open", "close": "Close"}), grid)
    old_labels = labels.rename(columns={"return4_net": "return_4", "label_end4": "label_end_return_4"})
    decisions = pd.DataFrame({"signal_date": sessions.as_unit("s"),
                              "target_position": rng.integers(0, 2, len(sessions)).astype(float),
                              "entry_eligible": rng.integers(0, 2, len(sessions)).astype(bool)})
    decisions["confirmation_opportunity"] = decisions.entry_eligible.to_numpy() & np.r_[True, decisions.target_position.to_numpy()[:-1] == 0]
    pricing = {"basis": "HFQ_RESEARCH", "quantity_unit": "RESEARCH_UNIT", "anchor_date": "2019-12-31", "anchor_factor": .2803}
    args = [old66, old61, old69, warm, native, old_labels, daily, sessions, decisions, pricing]
    features, targets, flat, calendar, proof = adapter.construct(*args)
    check("Synthetic complete1636 prefix assembles exact17 controls+curvature", len(features)==1635 and list(features)==[*statistics.CONTROLS, "curvature4"] and proof["status"]=="PASS")
    check("Native all six OHLCV/amount columns remain exact", proof["all_native_prices_volume_amount_exact"])
    check("Lossless us/s datetime metadata preserved in original inputs", str(daily.dt.dtype)=="datetime64[us]" and str(decisions.signal_date.dtype)=="datetime64[s]" and calendar.unit=="ns")
    check("Policy predicate shifts complete prefix before auxiliary reindex", np.array_equal(flat, decisions.confirmation_opportunity.iloc[:-1]))
    check("Four uncompleted last signals stay missing without extrapolation", targets.iloc[-4:].isna().all().all())

    def mutation(position, change):
        values = [x.copy(deep=True) if isinstance(x, pd.DataFrame) else deepcopy(x) for x in args]
        change(values[position])
        return lambda: adapter.construct(*values)

    reject("Altered native price refuses", mutation(6, lambda f: f.__setitem__("open", f.open+.0001)))
    reject("Altered native amount refuses", mutation(6, lambda f: f.__setitem__("amount", f.amount+.01)))
    reject("Old14 control difference refuses", mutation(1, lambda f: f.__setitem__("acf1", f.acf1+.01)))
    reject("Old EX061 tail difference refuses", mutation(1, lambda f: f.__setitem__("late_recovery", f.late_recovery+.01)))
    reject("Negated stretch refuses", mutation(2, lambda f: f.__setitem__("short_stretch4", -f.short_stretch4)))
    reject("Changed original price units refuse", mutation(9, lambda p: p.__setitem__("anchor_factor", .28)))
    reject("N0 inconsistent opportunity refuses", mutation(8, lambda d: d.__setitem__("confirmation_opportunity", ~d.confirmation_opportunity)))
    reject("N0 missing target refuses", mutation(8, lambda d: d.__setitem__("target_position", d.target_position.mask(d.index==4))))
    reject("Non-midnight datetime is never normalized", lambda: adapter.exact_datetime(pd.date_range("2000-01-03 00:01", periods=3)))
    reject("Timezone datetime refuses", lambda: adapter.exact_datetime(pd.date_range("2000-01-03", periods=3, tz="UTC")))
    panel = {"partial": {"n": 100, "residual_df": 82, "reason": None, "value": .1},
             "partial_bootstrap": {"ic95": [.01, .2], "valid": 500},
             "walk_forward": {"aggregate": {"n": 100, "reason": None, "mse_controls": 2., "mse_augmented": 1., "mse_pastmean": 3.}}}
    check("Positive CI and both lower MSE only LIMITED_INCREMENT", reading.classify(panel)["status"]=="LIMITED_INCREMENT")
    opposite = deepcopy(panel)
    opposite["partial_bootstrap"]["ic95"] = [-.2, -.01]
    check("Opposite direction cannot rescue and retains counterevidence", reading.classify(opposite)["status"]=="OPPOSITE_DIRECTION_COUNTEREVIDENCE")
    weak = deepcopy(panel)
    weak["partial_bootstrap"]["ic95"] = [-.01, .2]
    check("Uncertain direction with both MSE gains retains predictive-only status", reading.classify(weak)["status"]=="INCONCLUSIVE_PREDICTIVE_ONLY")
    tied = deepcopy(panel)
    tied["walk_forward"]["aggregate"]["mse_augmented"] = 2.
    check("Supported direction without MSE gain retains correlation-only status", reading.classify(tied)["status"]=="CORRELATED_WITHOUT_CONFIRMED_PREDICTIVE_INCREMENT")
    thin = deepcopy(panel)
    thin["partial"]["residual_df"] = 9
    check("Thin residual sample returns INSUFFICIENT", reading.classify(thin)["status"]=="INSUFFICIENT")
    explained = deepcopy(panel)
    explained["partial"]["reason"] = "EXPLAINED_COMPONENT"
    check("Explained component never becomes increment via ridge", reading.classify(explained)["status"]=="NO_INCREMENT")
    bad = deepcopy(panel)
    bad["partial_bootstrap"]["ic95"] = [2., 1.]
    reject("Invalid CI ordered schema refuses", lambda: reading.classify(bad))
    refs = {k: {"type": "EvidenceRef", "experiment": {"type": "ExperimentRef", "strategy_id": "S013", "experiment_id": ex},
                 "sha256": "a"*64, "evidence_id": "a"*64+(".json" if k=="native_ref" else ".csv"),
                 "media_type": media, "schema": schema, "schema_version": 6 if k=="native_ref" else None}
            for k, (ex, media, schema) in driver.REFERENCE_SCHEMA.items()}
    driver.reference_schema(refs)
    check("Exact seven old authorized reference schemas", len(refs)==7)
    bad_refs = deepcopy(refs)
    bad_refs["native_ref"]["experiment"]["strategy_id"] = "S003"
    reject("Other research namespace refuses", lambda: driver.reference_schema(bad_refs))
    tree = ast.parse((HERE/"driver.py").read_text())
    forbidden = {"fetch", "prepare", "evaluate", "evaluate_many", "publish_evidence", "create_experiment", "assemble_delivery", "analyze"}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = [n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id if isinstance(n.func, ast.Name) else "" for n in calls]
    check("Driver source has no provider/financial/publication APIs; single analyze only", [name for name in names if name in forbidden]==["analyze"])
    source_files = {n: sha256((HERE/n).read_bytes()).hexdigest() for n in ("input_authentication.py", "reading.py", "driver.py", "execution_checks.py")}
    proof = {"status": "SOURCE_ONLY_PURE_READY", "check_count": len(checks), "checks": checks,
             "source_files": source_files, "actual_analyze_calls": 0, "real_input_authentication_calls": 0,
             "fixture": "synthetic OHLCV/amount and1636 decision prefix; no account financial fields", "provider_calls": 0, "new_accounts": 0}
    with (HERE/"execution_pureproof.json").open("x", encoding="utf-8") as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("SOURCE_ONLY_PURE_READY", len(checks))


if __name__ == "__main__":
    main()
