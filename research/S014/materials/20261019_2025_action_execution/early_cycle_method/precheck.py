"""Pure synthetic original-cycle checks, including the actual SRT observation boundary."""
import ast
import importlib.util
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys

import pandas as pd
import requests
from strategy_runtime import (
    ExecutionCapabilities, ExecutionPlan, ImplementationRef, ParameterSet, PriceReference, RuntimeContractError, RuntimeDefinition, StrategyDefinition,
    StrategyIdentity, TradableWindow, materialize_observation,
)
from strategy_runtime.contracts import plan_identity_for, signal_identity_for

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").exists())
OLD = ROOT / "research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py"
NEW = HERE / "prototype_runtime/strategies/early_cycle_review.py"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def fixture():
    # Past dates are toy sessions; future dates explicitly include the June2 holiday gap.
    past = pd.bdate_range(end="2025-05-29", periods=60)
    future = pd.to_datetime(["2025-05-30", "2025-06-03", "2025-06-04", "2025-06-05", "2025-06-06",
                            "2025-06-09", "2025-06-10", "2025-06-11", "2025-06-12", "2025-06-13",
                            "2025-06-16", "2025-06-17", "2025-06-18", "2025-06-19", "2025-06-20",
                            "2025-06-23", "2025-06-24", "2025-06-25", "2025-06-26", "2025-06-27",
                            "2025-06-30"])
    dates = pd.DatetimeIndex([pd.Timestamp("2019-12-31"), *past, *future])
    raw = pd.DataFrame(dict(Date=dates, Open=10., High=10.2, Low=9.8, Close=10.,
                            Volume=100000., Amount=1000000.))
    raw.loc[raw.Date.eq(pd.Timestamp("2025-05-30")), ["Close", "Low"]] = [9., 8.9]
    raw.loc[raw.Date.eq(pd.Timestamp("2025-06-17")), ["Close", "Low"]] = [8., 7.9]
    limits = pd.DataFrame(dict(Date=dates, DownLimit=5., UpLimit=20.))
    status = pd.DataFrame(dict(Date=dates, Status="TRADING"))
    return [raw.copy(), raw, limits, status]


def synthetic_runtime(definition):
    # In-memory identity only: no candidate, release, account or publication is created.
    return RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1",
        release_id="S014-v1", release_hash="a" * 64,
        implementation=ImplementationRef("prototype_runtime.strategies.early_cycle_review",
                                       "EarlyCycleStrategy", 1, sha256(NEW.read_bytes()).hexdigest()),
        **{field.name: getattr(definition, field.name) for field in fields(StrategyDefinition)})


def observed_plan(definition, evidence):
    strategy = StrategyIdentity(definition.strategy_family_id, definition.release_id,
                                definition.release_hash, definition.runtime_sha256, definition.tradable_symbol)
    signal = dict(strategy=strategy, signal_date=date(2025, 5, 30), target_position=0.,
                  input_identities={"synthetic_input": "a" * 64}, price_identities={"synthetic_price": "b" * 64})
    execution = dict(signal_identity=signal_identity_for(**signal), actual_quantity=0, target_quantity=0,
                     cycle_target_quantity=0, plan_mode="NONE", capital_mode="full_available_cash",
                     allocation_fraction=Decimal(1), orders=(), legs=())
    return ExecutionPlan(**signal, **execution, plan_identity=plan_identity_for(**execution),
                         symbol=definition.tradable_symbol, trading_date=date(2025, 6, 3),
                         generated_at=datetime(2025, 5, 30, tzinfo=timezone.utc),
                         expected_portfolio_revision=0, expected_state_revision=0, action="WAIT",
                         available_cash=Decimal(100000), fee_rate=Decimal(".001"), estimated_order_cost=Decimal(0),
                         unallocated_cash=Decimal(100000), references=PriceReference(Decimal(1), Decimal(1), "hfq", "raw"),
                         required_capabilities=ExecutionCapabilities(()), evidence=evidence)


def main():
    destination = HERE / "synthetic_precheck.json"
    if destination.exists():
        raise RuntimeError("Preserve existing synthetic receipt")
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append("ATTEMPTED")
        raise RuntimeError("Synthetic-only network prohibition")

    requests.sessions.Session.request = blocked
    socket.socket.connect = blocked
    socket.create_connection = blocked
    old, new = module("early_cycle_original", OLD), module("early_cycle_prototype", NEW)
    checks = []

    def check(name, value):
        if not bool(value):
            raise AssertionError(name)
        checks.append(name)

    def reject(name, fn):
        try:
            fn()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError(name)

    configs = {mode: new.EarlyCycleConfig.parse({"mode": mode, "entry_execution_date": "2025-05-30"})
               for mode in ["NOOP", "HOLD_ORIGINAL_CYCLE_H10"]}
    args = fixture()
    baseline = old.history(*args, "support_exit_reserve_H10")
    noop = new.history(*args, configs["NOOP"])
    held = new.history(*args, configs["HOLD_ORIGINAL_CYCLE_H10"])
    pd.testing.assert_frame_equal(baseline, noop[baseline.columns], check_exact=True)
    check("NOOP every original history column and target exact", True)
    check("prewindow excluded from warmup and original support", noop.iloc[0].warmup_sessions == 0
          and noop.loc[pd.Timestamp("2025-05-29")].warmup_sessions == 60)
    target = held.index.get_loc(pd.Timestamp("2025-05-30"))
    before = held.index < pd.Timestamp("2025-05-30")
    pd.testing.assert_frame_equal(held.loc[before, baseline.columns], baseline.loc[before], check_exact=True)
    check("protected-mode original prefix exact before real entry", True)
    check("same-day filled entry remains true raw support break", held.iloc[target].buy_filled_today
          and held.iloc[target].support_break and held.iloc[target].support_exit_suppressed == 1
          and not held.iloc[target].exit_pending and held.iloc[target].target_position == 1)
    check("original NOOP support exit is next session after holiday", noop.loc["2025-05-30"].exit_pending
          and noop.loc["2025-06-03"].sell_filled_today and not held.loc["2025-06-03"].sell_filled_today)
    pd.testing.assert_series_equal(held.support_break, baseline.support_break, check_exact=True)
    pd.testing.assert_series_equal(held.support_floor, baseline.support_floor, check_exact=True)
    check("raw support observations never falsified by cycle exception", True)
    check("entry-fixed H10 and reservation not reset", held.loc["2025-06-13"].deadline_index == target + 9
          and held.loc["2025-06-13"].reservation_index == target + 10
          and held.loc["2025-06-16"].reservation_index == target + 10)
    check("mandatory deadline issues pending despite protection", held.loc["2025-06-13"].deadline_exit_pending == 1
          and held.loc["2025-06-13"].exit_pending and held.loc["2025-06-13"].target_position == 0
          and held.loc["2025-06-16"].sell_filled_today)
    check("ordinary reservation permits reentry after actual target-cycle exit", held.loc["2025-06-16"].entry_signal
          and held.loc["2025-06-17"].buy_filled_today and held.loc["2025-06-17"].entry_index != target)
    check("new cycle restores original support exit immediately", held.loc["2025-06-17"].support_break
          and held.loc["2025-06-17"].exit_pending and held.loc["2025-06-17"].support_exit_suppressed == 0
          and held.loc["2025-06-17"].protected_cycle_active == 0 and held.loc["2025-06-18"].sell_filled_today)

    blocked_args = [x.copy() for x in args]
    blocked_args[3].loc[blocked_args[3].Date.eq(pd.Timestamp("2025-06-16")), "Status"] = "SUSPENDED"
    for frame in blocked_args[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-17")), ["Open", "High", "Low", "Close"]] = 5.
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-13")), ["Close", "Low"]] = [6., 5.9]
    delayed = new.history(*blocked_args, configs["HOLD_ORIGINAL_CYCLE_H10"])
    check("deadline priority when support break also true", delayed.loc["2025-06-13"].support_break
          and delayed.loc["2025-06-13"].exit_pending and delayed.loc["2025-06-13"].support_exit_suppressed == 0)
    check("suspended expiry sale remains pending", delayed.loc["2025-06-16"].protected_sell_blocked == 1
          and delayed.loc["2025-06-16"].held_at_close and delayed.loc["2025-06-16"].exit_pending)
    check("limit-down expiry sale remains pending", delayed.loc["2025-06-17"].protected_sell_blocked == 1
          and delayed.loc["2025-06-17"].held_at_close and delayed.loc["2025-06-17"].exit_pending)
    check("blocked sale retains old clocks and no replacement buy", delayed.loc["2025-06-17"].deadline_index == target + 9
          and delayed.loc["2025-06-17"].reservation_index == target + 10 and not delayed.loc["2025-06-17"].entry_signal)
    check("first allowed sale completes target cycle and restores policy", delayed.loc["2025-06-18"].sell_filled_today
          and delayed.loc["2025-06-18"].target_cycle_completed == 1
          and delayed.loc["2025-06-18"].protected_cycle_active == 0
          and delayed.loc["2025-06-18"].protected_sell_blocked == 0)
    pd.testing.assert_frame_equal(old.history(*blocked_args, "support_exit_reserve_H10"),
                                  new.history(*blocked_args, configs["NOOP"])[baseline.columns], check_exact=True)
    check("NOOP exact under suspension and limit-down inputs", True)

    repeated = [x.copy() for x in args]
    for frame in repeated[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-04")), ["Close", "Low"]] = [8., 7.9]
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-09")), ["Close", "Low"]] = [7., 6.9]
    many = new.history(*repeated, configs["HOLD_ORIGINAL_CYCLE_H10"])
    check("multiple support breaks belong to one fixed cycle not multiple interventions",
          many.support_exit_suppressed.sum() >= 3 and many.loc["2025-06-13"].deadline_index == target + 9)
    missing = [x.copy() for x in args]
    for frame in missing[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-05-30")), ["Open", "High", "Low", "Close"]] = [12., 12.1, 11.5, 11.7]
    reject("fixed entry not filled rejects rather than targeting later entry",
           lambda: new.history(*missing, configs["HOLD_ORIGINAL_CYCLE_H10"]))
    prefix = [frame.loc[frame.Date <= pd.Timestamp("2025-05-29")].copy() for frame in args]
    pre = new.history(*prefix, configs["HOLD_ORIGINAL_CYCLE_H10"])
    pd.testing.assert_frame_equal(pre, held.loc[pre.index], check_exact=True)
    check("pre-target history prefix has no future dependence", True)

    original_definition = old.RepairStrategy(ParameterSet({"variant": "support_exit_reserve_H10"})).definition
    old_ast, new_ast = ast.parse(OLD.read_text(encoding="utf-8")), ast.parse(NEW.read_text(encoding="utf-8"))
    for name in ["calendar_request", "derive_calculation_scope"]:
        def extract(tree):
            return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        check("original data-request AST exact " + name,
              ast.dump(extract(old_ast), include_attributes=False) == ast.dump(extract(new_ast), include_attributes=False))
    for name in ["InputContract", "DecisionContract", "ExecutionPolicy", "MonitoringPolicy", "RequiredCapabilities"]:
        def extract(tree):
            return next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name)
        check("original contract AST exact " + name,
              ast.dump(extract(old_ast), include_attributes=False) == ast.dump(extract(new_ast), include_attributes=False))
    observations = 0
    for mode in configs:
        strategy = new.EarlyCycleStrategy(ParameterSet({"mode": mode, "entry_execution_date": "2025-05-30"}))
        definition = strategy.definition
        for field in ["tradable_symbol", "inputs", "decision", "execution", "monitoring", "capabilities"]:
            check(f"{mode} original economic definition {field} exact",
                  getattr(definition, field) == getattr(original_definition, field))
        check(f"{mode} original observation series declarations unchanged",
              definition.observation.series[:len(new.OBSERVED)] == original_definition.observation.series)
        table = strategy.calculate_history(dict(zip(["market", "raw", "limits", "status"], args)), held.index)
        check(f"{mode} all declared old and diagnostic columns are float", all(
            table[c].dtype.kind == "f" for c in strategy._observed))
        runtime = synthetic_runtime(definition)
        for _, row in table.iterrows():
            # Mirror SRT generate_signal scalar normalization (strategy.py:318).
            evidence = {name: row[name].item() if hasattr(row[name], "item") else row[name]
                        for name in strategy._observed}
            observation = materialize_observation(runtime, observed_plan(runtime, evidence))
            check_numeric = all(type(series.value) in (float, int) and not isinstance(series.value, bool)
                                for series in observation.series)
            if not check_numeric:
                raise AssertionError("Actual observation series nonnumeric")
            observations += 1
        check(f"{mode} actual SRT materialize_observation accepts every synthetic row", True)
        evidence = {name: float(table.iloc[target][name]) for name in strategy._observed}
        plan = observed_plan(runtime, evidence)
        try:
            materialize_observation(runtime, replace(plan, evidence={**evidence, "support_exit_suppressed": True}))
        except RuntimeContractError:
            check(f"{mode} actual Observation rejects bool diagnostic negative control", True)
        else:
            raise AssertionError("Observation bool boundary not exercised")
        window = TradableWindow(date(2020, 1, 2), date(2020, 1, 10))
        calendar = (date(2019, 12, 31), *pd.bdate_range("2020-01-02", "2020-01-10").date)
        check(f"{mode} original calculation prewindow contract exact",
              strategy.derive_calculation_scope(window, calendar)
              == old.RepairStrategy(ParameterSet({"variant": "support_exit_reserve_H10"})).derive_calculation_scope(window, calendar))
    for values in [
        {"mode": True, "entry_execution_date": "2025-05-30"},
        {"mode": "NOOP", "entry_execution_date": date(2025, 5, 30)},
        {"mode": "INVALID", "entry_execution_date": "2025-05-30"},
        {"mode": "NOOP", "entry_execution_date": "2025-5-30"},
        {"mode": "NOOP", "entry_execution_date": "2025-05-29"},
        {"mode": "NOOP", "entry_execution_date": "2025-05-30", "variant": "support_exit_reserve_H10"},
    ]:
        reject("strict parameter rejection " + repr(values), lambda values=values: new.EarlyCycleConfig.parse(values))
    reject("untyped config rejected", lambda: new.EarlyCycleConfig("NOOP", date(2025, 5, 30)))
    check("no network attempts", not attempts)
    result = {"status": "PASS_PURE_SYNTHETIC_ONLY", "checks_count": len(checks), "checks": checks,
              "actual_SRT_observation_materializations": observations,
              "evidence_scalar_normalization": "Same numpy scalar .item() conversion as SRT generate_signal; bool negative control remains bool",
              "source_sha256": sha256(NEW.read_bytes()).hexdigest(),
              "original_source_sha256": sha256(OLD.read_bytes()).hexdigest(),
              "precheck_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "network_attempts": len(attempts), "real_market_inputs_read": False,
              "real_strategy_account_runs": 0, "real_NOOP_equivalence": "NOT_EXECUTED",
              "new_counterfactual_results": 0,
              "scope": "Toy source-state/definition/actual numeric-observation boundary; no complete account or real C0056 source-output equivalence"}
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks_count": len(checks),
                      "actual_SRT_observation_materializations": observations,
                      "source_sha256": result["source_sha256"]}))


if __name__ == "__main__":
    main()
