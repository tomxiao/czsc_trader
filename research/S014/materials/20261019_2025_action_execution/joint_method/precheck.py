"""Synthetic fixed-joint source checks; no real accounts, inputs or network."""
import ast
import importlib.util
from dataclasses import fields, replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys

import pandas as pd
import requests
from strategy_runtime import (ImplementationRef, ParameterSet, RuntimeContractError,
                              RuntimeDefinition, StrategyDefinition, materialize_observation)

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "pyproject.toml").exists())
EARLY = HERE.parent / "early_cycle_method"
# No original or predecessor file is modified.


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


NEW = HERE / "prototype_runtime/strategies/joint_action_review.py"
OLD = ROOT / "research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py"
PREVIOUS = EARLY / "prototype_runtime/strategies/early_cycle_review.py"


def main():
    destination = HERE / "synthetic_precheck.json"
    if destination.exists():
        raise RuntimeError("Preserve existing receipt")
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("No network in pure synthetic precheck")

    requests.sessions.Session.request = blocked
    socket.socket.connect = blocked
    socket.create_connection = blocked
    support = module("joint_fixture_helpers", EARLY / "precheck.py")
    old = module("joint_original", OLD)
    previous = module("joint_predecessor", PREVIOUS)
    new = module("joint_prototype", NEW)
    checks = []

    def check(name, condition):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(name)

    def equal(name, left, right):
        pd.testing.assert_frame_equal(left, right, check_exact=True)
        checks.append(name)

    def rejected(name, function, kind=ValueError):
        try:
            function()
        except kind:
            checks.append(name)
        else:
            raise AssertionError(name)

    def config(mode):
        return new.JointConfig.parse(dict(mode=mode, entry_execution_date="2025-05-30",
                                         force_decision_date="2025-06-19"))

    # Start from the predecessor toy fixture, then make the next actual entry June19.
    args = support.fixture()
    for i, frame in enumerate(args):
        extra = frame.iloc[[-1]].copy()
        extra = pd.concat([extra] * 6, ignore_index=True)
        extra["Date"] = pd.to_datetime(["2025-07-01", "2025-07-02", "2025-07-03", "2025-07-04", "2025-07-07", "2025-07-08"])
        args[i] = pd.concat([frame, extra], ignore_index=True)
    for frame in args[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-16")), ["Close", "Low"]] = [8., 7.9]
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-17")), ["Close", "Low"]] = [7., 6.9]
        frame.loc[frame.Date.eq(pd.Timestamp("2025-07-04")), ["Close", "Low"]] = [6., 5.9]
    tables = {mode: new.history(*args, config(mode)) for mode in ["NOOP", "HOLD_ORIGINAL_CYCLE_H10", "JOINT"]}
    baseline = old.history(*args, "support_exit_reserve_H10")
    predecessor = previous.history(*args, previous.EarlyCycleConfig.parse(dict(mode="HOLD_ORIGINAL_CYCLE_H10", entry_execution_date="2025-05-30")))
    noop, h10, joint = [tables[m] for m in ["NOOP", "HOLD_ORIGINAL_CYCLE_H10", "JOINT"]]
    equal("NOOP complete original observed/history/target exact", noop[baseline.columns], baseline)
    equal("retained H10 complete predecessor source-state exact", h10[predecessor.columns], predecessor)
    equal("JOINT original prefix through pre-May30 exact", joint.loc[:"2025-05-29", baseline.columns], baseline.loc[:"2025-05-29"])
    equal("JOINT pre-June19 complete H10 prefix exact", joint.loc[:"2025-06-18", predecessor.columns], predecessor.loc[:"2025-06-18"])
    entry = joint.index.get_loc(pd.Timestamp("2025-05-30"))
    june = joint.index.get_loc(pd.Timestamp("2025-06-19"))
    check("May30 actual entry same-day truthful support break suppressed", joint.loc["2025-05-30"].buy_filled_today and joint.loc["2025-05-30"].support_break and joint.loc["2025-05-30"].support_exit_suppressed == 1)
    check("May30 fixed original clocks and deadline sale", joint.loc["2025-06-13"].deadline_index == entry + 9 and joint.loc["2025-06-16"].sell_filled_today and joint.loc["2025-06-16"].reservation_index == entry + 10)
    check("June19 actual same-day BUY original HOLD eligibility", h10.loc["2025-06-19"].buy_filled_today and h10.loc["2025-06-19"].held_at_close and h10.loc["2025-06-19"].target_position == 1 and not h10.loc["2025-06-19"].exit_pending and joint.loc["2025-06-19"].joint_node_eligible == 1)
    unchanged = [c for c in predecessor.columns if c not in ("target_position", "exit_pending")]
    equal("June19 filled state/raw features/old clocks equal H10 before intent change", joint.loc[["2025-06-19"], unchanged], predecessor.loc[["2025-06-19"], unchanged])
    check("one fixed June19 trigger changes only intended target/pending", joint.joint_trigger_today.sum() == 1 and joint.loc["2025-06-19"].target_position == 0 and joint.loc["2025-06-19"].exit_pending)
    check("June20 actual next-session sale completes real June cycle", joint.loc["2025-06-20"].sell_filled_today and joint.loc["2025-06-20"].joint_actual_sale_today == 1 and joint.loc["2025-06-20"].joint_target_cycle_completed == 1)
    check("June cycle original deadline and reservation frozen", joint.loc["2025-06-20"].joint_target_deadline_index == june + 9 and joint.loc["2025-06-20"].reservation_index == june + 10 and joint.loc["2025-07-03"].reservation_index == june + 10)
    check("no premature replacement buy before original June reservation", not joint.loc["2025-06-20":"2025-07-02"].entry_signal.any())
    check("ordinary policy restores after sale and reservation", joint.loc["2025-07-03"].entry_signal and joint.loc["2025-07-04"].buy_filled_today and joint.loc["2025-07-04"].support_break and joint.loc["2025-07-04"].exit_pending and joint.loc["2025-07-07"].sell_filled_today)
    check("raw support definitions exact under both branches", joint.support_break.equals(h10.support_break) and joint.support_floor.equals(h10.support_floor))

    delayed_args = [frame.copy() for frame in args]
    delayed_args[3].loc[delayed_args[3].Date.eq(pd.Timestamp("2025-06-20")), "Status"] = "SUSPENDED"
    for frame in delayed_args[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-23")), ["Open", "High", "Low", "Close"]] = 5.
    delayed = new.history(*delayed_args, config("JOINT"))
    check("forced sale suspension keeps pending and original June clocks", delayed.loc["2025-06-20"].joint_sale_blocked == 1 and delayed.loc["2025-06-20"].exit_pending and delayed.loc["2025-06-20"].deadline_index == june + 9 and delayed.loc["2025-06-20"].reservation_index == june + 10)
    check("forced sale limit-down also keeps pending", delayed.loc["2025-06-23"].joint_sale_blocked == 1 and delayed.loc["2025-06-23"].held_at_close and delayed.loc["2025-06-23"].exit_pending)
    check("first tradable sale completes joint without second trigger", delayed.loc["2025-06-24"].joint_actual_sale_today == 1 and delayed.joint_trigger_today.sum() == 1)
    equal("NOOP blocked-market original exact", new.history(*delayed_args, config("NOOP"))[baseline.columns], old.history(*delayed_args, "support_exit_reserve_H10"))
    equal("H10 blocked-market predecessor exact", new.history(*delayed_args, config("HOLD_ORIGINAL_CYCLE_H10"))[predecessor.columns], previous.history(*delayed_args, previous.EarlyCycleConfig.parse(dict(mode="HOLD_ORIGINAL_CYCLE_H10", entry_execution_date="2025-05-30"))))
    prolonged_args = [frame.copy() for frame in args]
    prolonged_args[3].loc[prolonged_args[3].Date.between("2025-06-20", "2025-07-03"), "Status"] = "SUSPENDED"
    prolonged = new.history(*prolonged_args, config("JOINT"))
    check("forced pending survives original deadline and expired reservation", prolonged.loc["2025-07-03"].held_at_close and prolonged.loc["2025-07-03"].exit_pending and not prolonged.loc["2025-07-03"].entry_signal and prolonged.loc["2025-07-03"].deadline_index == june + 9 and prolonged.loc["2025-07-03"].reservation_index == june + 10)
    check("prolonged blocked sale executes when first allowed", prolonged.loc["2025-07-04"].joint_actual_sale_today == 1 and prolonged.loc["2025-07-04"].joint_target_cycle_completed == 1)
    # The pre-June19 prefix cannot depend on future availability or quotes.
    prefix = [frame.loc[frame.Date <= pd.Timestamp("2025-06-18")].copy() for frame in args]
    equal("pre-June19 prefix recomputation exact", new.history(*prefix, config("JOINT")), joint.loc[:"2025-06-18"])
    for name, change in [
        ("no same-day fill", "failed"), ("older held cycle", "older"),
        ("already original support exit", "support"), ("absent June19 session", "missing"),
    ]:
        invalid = [frame.copy() for frame in args]
        if change == "missing":
            invalid = [frame.loc[frame.Date.ne(pd.Timestamp("2025-06-19"))].copy() for frame in invalid]
        else:
            for frame in invalid[:2]:
                if change == "failed":
                    frame.loc[frame.Date.eq(pd.Timestamp("2025-06-19")), ["Open", "High", "Low", "Close"]] = [12., 12.1, 11.5, 11.7]
                elif change == "older":
                    frame.loc[frame.Date.eq(pd.Timestamp("2025-06-17")), ["Close", "Low"]] = [10., 9.8]
                else:
                    frame.loc[frame.Date.eq(pd.Timestamp("2025-06-19")), ["Close", "Low"]] = [6., 5.9]
        rejected("unsupported fixed June19 " + name, lambda invalid=invalid: new.history(*invalid, config("JOINT")), new.UnsupportedJointNodeError)

    check("original prewindow is not support/warmup history", joint.iloc[0].warmup_sessions == 0 and joint.loc["2025-05-29"].warmup_sessions == 60)
    may_blocked = support.fixture()
    may_blocked[3].loc[may_blocked[3].Date.eq(pd.Timestamp("2025-06-16")), "Status"] = "SUSPENDED"
    for frame in may_blocked[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-17")), ["Open", "High", "Low", "Close"]] = 5.
        frame.loc[frame.Date.eq(pd.Timestamp("2025-06-13")), ["Close", "Low"]] = [6., 5.9]
    may_joint = new.history(*may_blocked, config("JOINT"))
    check("May30 deadline priority despite simultaneous support break", may_joint.loc["2025-06-13"].support_break and may_joint.loc["2025-06-13"].exit_pending and may_joint.loc["2025-06-13"].support_exit_suppressed == 0)
    check("May30 expiry sale suspension pending retained", may_joint.loc["2025-06-16"].protected_sell_blocked == 1 and may_joint.loc["2025-06-16"].exit_pending)
    check("May30 expiry sale limit-down pending retained", may_joint.loc["2025-06-17"].protected_sell_blocked == 1 and may_joint.loc["2025-06-17"].exit_pending and may_joint.loc["2025-06-17"].reservation_index == entry + 10)
    check("May30 actual delayed sale closes selected cycle", may_joint.loc["2025-06-18"].sell_filled_today and may_joint.loc["2025-06-18"].target_cycle_completed == 1)
    missing_may = [frame.copy() for frame in args]
    for frame in missing_may[:2]:
        frame.loc[frame.Date.eq(pd.Timestamp("2025-05-30")), ["Open", "High", "Low", "Close"]] = [12., 12.1, 11.5, 11.7]
    rejected("missing actual May30 fill never creates protected cycle", lambda: new.history(*missing_may, config("HOLD_ORIGINAL_CYCLE_H10")))

    old_ast, new_ast = ast.parse(OLD.read_text(encoding="utf-8")), ast.parse(NEW.read_text(encoding="utf-8"))
    for name in ["calendar_request", "derive_calculation_scope"]:
        def extract(tree):
            return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        check("original data-request AST exact " + name, ast.dump(extract(old_ast)) == ast.dump(extract(new_ast)))
    for name in ["InputContract", "DecisionContract", "ExecutionPolicy", "MonitoringPolicy", "RequiredCapabilities"]:
        def extract(tree):
            return next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name)
        check("original economic contract AST exact " + name, ast.dump(extract(old_ast)) == ast.dump(extract(new_ast)))
    materializations = 0
    for mode, history in tables.items():
        strategy = new.JointActionStrategy(ParameterSet(dict(mode=mode, entry_execution_date="2025-05-30", force_decision_date="2025-06-19")))
        definition = strategy.definition
        original = old.RepairStrategy(ParameterSet(dict(variant="support_exit_reserve_H10"))).definition
        for field in ["tradable_symbol", "inputs", "decision", "execution", "monitoring", "capabilities"]:
            check(mode + " original contract " + field, getattr(definition, field) == getattr(original, field))
        table = strategy.calculate_history(dict(zip(["market", "raw", "limits", "status"], args)), history.index)
        check(mode + " every observed diagnostic dtype float", all(table[c].dtype.kind == "f" for c in strategy._observed))
        runtime = RuntimeDefinition(schema_version=3, strategy_family_id="S014", version="v1", release_id="S014-v1", release_hash="a" * 64,
                    implementation=ImplementationRef("prototype_runtime.strategies.joint_action_review", "JointActionStrategy", 1, sha256(NEW.read_bytes()).hexdigest()),
                    **{f.name: getattr(definition, f.name) for f in fields(StrategyDefinition)})
        for _, row in table.iterrows():
            evidence = {name: row[name].item() if hasattr(row[name], "item") else row[name] for name in strategy._observed}
            plan = support.observed_plan(runtime, evidence)
            materialize_observation(runtime, plan)
            materializations += 1
        check(mode + " actual SRT Observation all rows accepted", True)
        bad = {name: float(table.iloc[june][name]) for name in strategy._observed}
        plan = support.observed_plan(runtime, bad)
        rejected(mode + " actual SRT bool diagnostic negative control", lambda: materialize_observation(runtime, replace(plan, evidence={**bad, "joint_trigger_today": True})), RuntimeContractError)
    for values in [dict(mode=True, entry_execution_date="2025-05-30", force_decision_date="2025-06-19"),
                   dict(mode="JOINT", entry_execution_date="2025-05-30", force_decision_date="2025-06-20"),
                   dict(mode="JOINT", entry_execution_date="2025-05-30", force_decision_date=date(2025, 6, 19)),
                   dict(mode="JOINT", entry_execution_date="2025-05-30", force_decision_date="2025-6-19"),
                   dict(mode="JOINT", entry_execution_date="2025-05-29", force_decision_date="2025-06-19"),
                   dict(mode="JOINT", entry_execution_date="2025-05-30", force_decision_date="2025-06-19", extra=True)]:
        rejected("strict parameter rejection " + repr(values), lambda values=values: new.JointConfig.parse(values))
    check("zero network attempts", not attempts)
    result = dict(status="PASS_PURE_SYNTHETIC_ONLY", checks_count=len(checks), checks=checks,
                  actual_SRT_observation_materializations=materializations, network_attempts=len(attempts),
                  new_account_dispatches=0, real_market_inputs_read=False, real_NOOP="NOT_EXECUTED",
                  source_sha256=sha256(NEW.read_bytes()).hexdigest(), predecessor_source_sha256=sha256(PREVIOUS.read_bytes()).hexdigest(),
                  original_source_sha256=sha256(OLD.read_bytes()).hexdigest(), precheck_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  limitation="Toy source-state equivalence and actual public numeric boundary only; not real complete-account equivalence; no formal release identity created")
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ["status", "checks_count", "actual_SRT_observation_materializations", "source_sha256"]}))


if __name__ == "__main__":
    main()
