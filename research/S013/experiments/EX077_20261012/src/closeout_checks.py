"""Artificial fail/pass/unknown typed boundaries, no application calls."""

import ast
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.research_tools import delivery as d
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from postprocess import GATES, ROLES, MANDATE_SHA, build_payload, gate_decision


def main():
    here = Path(__file__).resolve().parent
    exp = ExperimentRef("S013", "EX077_20000103")
    generic = EvidenceRef.from_dict(
        {
            "type": "EvidenceRef",
            "experiment": exp.to_dict(),
            "evidence_id": "a" * 64 + ".json",
            "sha256": "a" * 64,
            "media_type": "application/json",
            "name": "artificial",
            "schema": None,
            "schema_version": None,
        }
    ).to_dict()
    native = {**generic, "schema": "account_evaluation", "schema_version": 6}
    refs = {name: generic for name in ("plan.json", "independent_audit.json", "root_review.json")}
    refs["native.json"] = native
    gates = {name: True for name in GATES}
    gates["frequency"] = False
    economics = {"gates": gates, "qualified": False}
    audit = {
        "status": "PASS",
        "independent_signal_state": "EXACT",
        "new_accounts": 1,
        "technical_financial_repeats": 0,
        "references": {"centre": native, "plan": generic},
        "economics": economics,
        "qualified": False,
        "cash_account": {"quantity_reconciliation": "EXACT_EQUAL", "candidate_id": "C9001"},
        "orders_first_touch": {"status": "PASS"},
    }
    review = {
        "status": "ROOT_SCIENTIFIC_REVIEWED",
        "objective_achieved": False,
        "financial_roles": ROLES,
        "original_four_hard_gates_changed": False,
        "economics": economics,
        "whole_formal_native_exact": True,
        "candidate_identity": d.CandidateIdentityRef(
            d.CandidateKey("S013", "C9001"), "b" * 64
        ).to_dict(),
        "evidence_references": refs,
        "conclusion": "人工fixture失败，无真实结论",
    }
    payload = build_payload(exp, review, audit, refs)
    assert not payload.candidates and not payload.handoff
    assert payload.searches[0].evaluations == payload.searches[0].unique_configurations == 1
    assert d.CandidateSet.from_dict(payload.to_dict()) == payload
    definition = d.DeliveryDefinition(
        d.ResearchBatchRef("S013"),
        d.DeliveryStage.CANDIDATES,
        61,
        (d.DeliveryReference(d.ResearchBatchRef("S013"), d.DeliveryStage.MANDATE, 6, MANDATE_SHA),),
    )
    assert d.DeliveryDefinition.from_dict(definition.to_dict()) == definition
    for failing in GATES:
        values = {name: name != failing for name in GATES}
        assert gate_decision(values) == "CENTRE_FAILED_STOP"
    assert gate_decision({name: True for name in GATES}) == "CENTRE_QUALIFIED_WAIT_ROOT_32_FEE"
    refused = 0
    passed = deepcopy(audit)
    passed["economics"]["gates"] = {name: True for name in GATES}
    try:
        build_payload(exp, review, passed, refs)
    except PermissionError:
        refused += 1
    else:
        raise AssertionError("passed centre must wait root")
    for bad in (
        {},
        {**gates, "frequency": None},
        {**gates, "frequency": 0},
        {**gates, "newgate": False},
    ):
        try:
            gate_decision(bad)
        except ValueError:
            refused += 1
        else:
            raise AssertionError("missing or invented gate became failure")
    for key, value in (("new_accounts", 2), ("status", "FAIL"), ("technical_financial_repeats", 1)):
        bad = deepcopy(audit)
        bad[key] = value
        try:
            build_payload(exp, review, bad, refs)
        except ValueError:
            refused += 1
        else:
            raise AssertionError(key)
    bad = deepcopy(review)
    bad["evidence_references"]["native.json"] = generic
    try:
        build_payload(exp, bad, audit, refs)
    except ValueError:
        refused += 1
    else:
        raise AssertionError("review linked different native")
    tree = ast.parse((here / "postprocess.py").read_text("utf-8"))
    forbidden = {"prepare", "evaluate", "register_candidate", "create_experiment"}
    assert not any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in forbidden
            or isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden
        )
        for node in ast.walk(tree)
    )
    result = dict(
        status="PASS",
        artificial_only=True,
        grouped_checks=6,
        refusals=refused,
        source_files={
            name: sha256((here / name).read_bytes()).hexdigest()
            for name in ("postprocess.py", "checks.py")
        },
        real_inputs=0,
        financial_accounts=0,
        publication=0,
        assembly=0,
        FULL=0,
    )
    (here / "checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(result)


if __name__ == "__main__":
    main()
