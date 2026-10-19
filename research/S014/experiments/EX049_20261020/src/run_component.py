"""Frozen local component workflow. There is no account evaluation interface."""
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import ExperimentRef, MaterialEvidenceWrite

from local_cycle import Action, label, simulate, state_at_D
import prepared_reader as R

ROOT = R.ROOT
EX = Path(__file__).resolve().parents[1]
M = ROOT / "research/S014/materials/20261020_shock_state_diagnosis"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def public(path, name):
    ctx = R.context()
    media = {".json": "application/json", ".py": "text/x-python", ".csv": "text/csv", ".md": "text/markdown"}
    ref = publish_evidence(ctx, MaterialEvidenceWrite(ExperimentRef("S014", EX.name), name,
                                                     path.read_bytes(), media[path.suffix], path.suffix[1:]))
    assert ref.resolve(ROOT).read_bytes() == path.read_bytes()
    return ref.to_dict()


def population():
    review = read(M / "accounting/original_shock_population_review.json")
    item = next(v for v in review["outputs"] if v["path"].endswith("original_shock_population.csv"))
    path = ROOT / item["path"]
    assert digest(path) == item["sha256"]
    values = pd.read_csv(path, dtype=str).to_dict("records")
    assert len(values) == len({r["cycle_id"] for r in values}) == 21
    return values


def validate_lock():
    lock = read(EX / "protocols/execution_lock.json")
    for path, expected in lock["source_hashes"].items():
        assert digest(EX / path) == expected, path
    for path, expected in lock["external_source_hashes"].items():
        assert digest(ROOT / path) == expected, path
    ref = R.EvidenceRef.from_dict(read(EX / "protocols/published_lock.json"))
    assert ref.resolve(ROOT).read_bytes() == (EX / "protocols/execution_lock.json").read_bytes()
    assert read(EX / "others/accounts_index.json")["records"] == []
    assert read(EX / "others/accounts_index.json")["dispatched_count"] == 0
    return lock


def check_gate(name):
    gate = read(EX / ("others/" + name + ".json"))
    assert gate["status"] == "PASS" and gate["source_lock_sha256"] == digest(EX / "protocols/execution_lock.json")
    assert len(gate["reviews"]) == 2 and {v["reviewer"] for v in gate["reviews"]} == {"A", "B"}
    assert len({v["sha256"] for v in gate["reviews"]}) == 2
    for entry in gate["reviews"]:
        review = R.published(entry["ref"])
        assert review["status"].startswith("PASS")
        assert entry["sha256"] == entry["ref"]["sha256"]
        if name == "gate_ON_independent":
            assert review["source_lock_sha256"] == gate["source_lock_sha256"]
            assert review["ON_ref"] == gate["ON_ref"]
        else:
            assert review["reviewed_hashes"]["research/S014/experiments/EX049_20261020/src/run_component.py"] == digest(EX / "src/run_component.py")
    return gate


def build():
    design = read(EX / "protocols/design.json")
    assert design["new_funded_account_budget"] == 0
    for path, expected in design["external_source_hashes"].items():
        assert digest(ROOT / path) == expected
    precheck = read(EX / "others/synthetic_precheck.json")
    assert precheck["status"] == "PASS_PURE_SYNTHETIC_ONLY" and precheck["checks_count"] == 32
    for name, expected in precheck["source_hashes"].items():
        assert digest(EX / "src" / name) == expected
    paths = [EX / "protocols/design.json", EX / "others/synthetic_precheck.json", *sorted((EX / "src").glob("*.py"))]
    refs = {path.relative_to(EX).as_posix(): public(path, "ex049-source-" + path.name) for path in paths}
    for path in design["external_source_hashes"]:
        refs[path] = public(ROOT / path, "ex049-upstream-" + Path(path).stem)
    write(EX / "protocols/published_sources.json", refs)
    lock = {"status": "LOCKED_COMPONENT_BEFORE_ON_AND_OFF", "source_hashes": {p.relative_to(EX).as_posix(): digest(p) for p in paths},
            "external_source_hashes": design["external_source_hashes"], "new_funded_account_budget": 0,
            "component_event_count": 21, "original_candidate": "C9461",
            "published_sources_sha256": digest(EX / "protocols/published_sources.json"),
            "OFF_requires_independent_ON_control": True, "new_fits": 0, "new_supplier_calls": 0}
    write(EX / "protocols/execution_lock.json", lock)
    write(EX / "protocols/published_lock.json", public(EX / "protocols/execution_lock.json", "ex049-component-source-lock"))
    path = EX / "others/accounts_index.json"
    write(path, {"records": [], "dispatched_count": 0, "component_only": True, "new_fits": 0,
                 "new_supplier_calls": 0, "formal_candidate_registrations": 0})
    write(EX / "others/accounts_index_ref.json", public(path, "ex049-explicit-empty-funded-index"))
    print("LOCKED_COMPONENT_NO_FUNDED_ACCOUNTS", digest(EX / "protocols/execution_lock.json"), flush=True)


def on_exact(seed, event, result, account):
    assert result["status"] == "CLOSED" and result["exit_E"] == event["actual_exit_fill_E"]
    ledgers = account["runs"][0]["ledgers"]
    decisions = {str(r["signal_date"])[:10]: r for r in ledgers["decisions"]["data"]}
    expected_D = sorted(D for D in decisions if seed.entry_E <= D < result["exit_E"])
    assert [r["D"] for r in result["trace"]] == expected_D
    checked = 0
    for row in result["trace"]:
        old = decisions[row["D"]]
        assert row["valid_E"] == str(old["valid_session"])[:10]
        for key in ("target_position", "held_at_close", "entry_index", "deadline_index", "reservation_index", "holding_age",
                    "pending_inherited", "deadline_exit", "profit_exit_eligible", "shock_condition", "selected_shock_exit",
                    "selected_cost_exit", "selected_risk_exit", "ordinary_support_exit", "entry_grace_eligible",
                    "entry_grace_applied", "support_exit_suppressed", "support_break", "net_profit", "cost_loss_price", "exit_pending"):
            assert row[key] == old[key], (seed.event_id, row["D"], key, row[key], old[key])
            checked += 1
    orders = sorted((r for r in ledgers["orders"]["data"] if r["cycle_id"] == seed.cycle_id and r["side"] == "SELL"), key=lambda r: r["execution_date"])
    fills = {r["order_id"]: r for r in ledgers["fills"]["data"]}
    assert len(orders) == len(result["attempts"])
    for attempt, order in zip(result["attempts"], orders, strict=True):
        actual = fills.get(order["order_id"])
        assert attempt["D"] == str(order["signal_date"])[:10] and attempt["E"] == str(order["execution_date"])[:10]
        assert attempt["quantity"] == order["quantity"] and attempt["filled"] == (actual is not None)
        if actual:
            assert attempt["price"] == actual["price"] and attempt["trigger"] == actual["trigger"]
            assert pd.Timestamp(attempt["filled_at"]) == pd.Timestamp(actual["fill_time"])
            assert attempt["time_precision"] == actual["time_precision"]
            assert result["exit_fee"] == actual["fees"] and result["quantity"] == actual["quantity"]
        checked += 8
    return checked


def on():
    validate_lock()
    check_gate("gate_source_review")
    assert not (EX / "others/on_controls.json").exists()
    rows = []
    try:
        receipt, account, binding = R.identities()
        inputs, manifest = R.fetch_inputs(account, binding)
        for event in population():
            seed = R.seed_from_event(event, account, inputs)
            result = simulate(seed, inputs, Action.ON)
            checks = on_exact(seed, event, result, account)
            states = state_at_D(inputs, event["D"])
            rows.append({"origin_actual_event": event, "seed": asdict(seed), "D_known_states": states,
                         "original_ON_MODELLED_control": result, "exact_control_checks": checks})
    except Exception as exc:
        path = EX / "others/on_failure.json"
        write(path, {"status": "TECHNICAL_FAILURE_NO_OFF_LABELS", "error": repr(exc), "completed_controls": rows})
        public(path, "ex049-retained-on-failure")
        raise
    value = {"status": "PASS_ORIGINAL_ON_COMPONENT_CONTROLS", "source_lock_sha256": digest(EX / "protocols/execution_lock.json"),
             "origin_actual_account_ref": receipt["evidence"], "origin_actual_result_hash": account["result_hash"],
             "original_binding_ref": receipt["binding_ref"], "prepared_content_identities": manifest,
             "rows": rows, "N": len(rows), "total_exact_checks": sum(r["exact_control_checks"] for r in rows),
             "new_OFF_labels": 0, "new_funded_accounts": 0, "new_supplier_calls": 0}
    path = EX / "others/on_controls.json"
    write(path, value)
    write(EX / "others/on_controls_ref.json", public(path, "ex049-on-component-control-and-D-known-states"))
    print("ON_COMPONENT_CONTROLS_PASS", len(rows), value["total_exact_checks"], flush=True)


def aggregate(rows, state, year=None, age_kind=None, remaining=None):
    group = [r for r in rows if (year is None or int(r["origin_actual_event"]["year_of_D"]) == year)
             and (age_kind is None or (int(float(r["origin_actual_event"]["holding_age_D"])) == 0) == (age_kind == "age0"))
             and (remaining is None or int(float(r["origin_actual_event"]["remaining_D_sessions_to_deadline"])) == remaining)]
    cells = []
    for value in (True, False, None):
        selected = [r for r in group if r["D_known_states"][state] is value]
        labels = [r["label_POSTHOC"]["advantage"] for r in selected if r["label_POSTHOC"]["advantage"] is not None]
        cells.append({"state_value": value, "N": len(selected), "closed_label_n": len(labels),
                      "censored_n": sum(r["alternative_MODELLED_POSTHOC"]["status"] == "CENSORED" for r in selected),
                      "positive_n": sum(v > 0 for v in labels), "zero_n": sum(v == 0 for v in labels), "negative_n": sum(v < 0 for v in labels),
                      "mean_advantage": sum(labels) / len(labels) if labels else None,
                      "median_advantage": float(pd.Series(labels).median()) if labels else None})
    common = [r for r in group if r["D_known_states"][state] is not None and r["label_POSTHOC"]["advantage"] is not None]
    always_hold = [r["label_POSTHOC"]["advantage"] for r in common]
    conditioned = [r["label_POSTHOC"]["advantage"] if r["D_known_states"][state] else 0.0 for r in common]
    return {"state": state, "year": year, "age_kind": age_kind, "exact_remaining": remaining, "N": len(group), "cells": cells,
            "same_closed_known_cohort_reference": {"N": len(common),
                "always_exit_mean": 0.0 if common else None,
                "always_hold_mean": sum(always_hold) / len(common) if common else None,
                "frozen_true_hold_false_exit_mean": sum(conditioned) / len(common) if common else None}}


def off():
    validate_lock()
    check_gate("gate_source_review")
    gate = check_gate("gate_ON_independent")
    original = R.published(gate["ON_ref"])
    on_ref = R.EvidenceRef.from_dict(gate["ON_ref"])
    assert on_ref.resolve(ROOT).read_bytes() == (EX / "others/on_controls.json").read_bytes()
    assert original["status"] == "PASS_ORIGINAL_ON_COMPONENT_CONTROLS" and gate["ON_ref"] == read(EX / "others/on_controls_ref.json")
    assert not (EX / "others/off_labels.json").exists()
    rows = []
    try:
        _, account, binding = R.identities()
        inputs, manifest = R.fetch_inputs(account, binding)
        assert manifest == original["prepared_content_identities"]
        for old in original["rows"]:
            event = old["origin_actual_event"]
            seed = R.seed_from_event(event, account, inputs)
            result = simulate(seed, inputs, Action.OFF_LOCAL_CYCLE)
            actual_exit = float(event["actual_exit_price_ledger"])
            actual_fee = float(event["actual_exit_fee"])
            advantage = label(seed, actual_exit, actual_fee, result)
            choices = {"always_exit": 0.0, "always_hold": advantage["advantage"]}
            for state in ("PRIOR_TREND_ESTABLISHED", "NON_FINAL_DAY_DOMINATED"):
                known_state = old["D_known_states"][state]
                choices[state + "_TRUE_HOLD_FALSE_EXIT"] = (advantage["advantage"] if known_state else 0.0) if known_state is not None else None
            rows.append({**old, "alternative_MODELLED_POSTHOC": result, "label_POSTHOC": advantage,
                         "frozen_local_choices_POSTHOC": choices})
    except Exception as exc:
        path = EX / "others/off_failure.json"
        write(path, {"status": "TECHNICAL_FAILURE_RETAIN_PARTIAL_LABELS", "error": repr(exc), "rows": rows})
        public(path, "ex049-retained-off-failure")
        raise
    summaries = []
    for state in ("PRIOR_TREND_ESTABLISHED", "NON_FINAL_DAY_DOMINATED"):
        summaries.append(aggregate(rows, state))
        summaries.extend(aggregate(rows, state, year=y) for y in range(2020, 2027))
        summaries.extend(aggregate(rows, state, age_kind=k) for k in ("age0", "later"))
        summaries.extend(aggregate(rows, state, remaining=k) for k in range(10))
    value = {"status": "COMPLETE_MODELLED_COMPONENT_LABELS_PENDING_INDEPENDENT_AUDIT", "N": len(rows),
             "source_lock_sha256": digest(EX / "protocols/execution_lock.json"), "origin_ON_control_ref": gate["ON_ref"],
             "rows": rows, "summaries": summaries, "new_funded_accounts": 0, "new_fits": 0, "new_supplier_calls": 0,
             "meaning": "Equal-weight fixed original cycle liquidation differences only; modelled fills, not new funded trades or an additive annual account return"}
    path = EX / "others/off_labels.json"
    write(path, value)
    write(EX / "others/off_labels_ref.json", public(path, "ex049-off-modelled-local-cycle-labels"))
    print("OFF_COMPONENT_LABELS", len(rows), "funded_accounts=0", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("build", "on", "off"))
    phase = parser.parse_args().phase
    {"build": build, "on": on, "off": off}[phase]()
