"""Read-only finite EX074 native fivechecks and absolute tail comparison."""
# ruff: noqa: E402 -- Set thread limits and locate frozen research modules before imports.

from __future__ import annotations
import os

for n in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[n] = "1"
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import driver as d
import perturbation_driver as p
from strategy_evaluator import AssessmentPanel
from czsc_trader.research_tools.parameter_evaluation import read_parameter_plan
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import (
    serialize_evaluation_evidence,
    validate_evaluation_evidence,
)

WORK, ROOT = d.WORK, d.ROOT


def reuse(ctx, common, item, audit, fee=False):
    cache = ROOT / item["cache_path"]
    assert d.digest(cache) == item["cache_sha256"]
    req, result = common.cache_read(cache)
    assert (
        req.strategy.candidate_id == item["candidate_id"]
        and result.request_hash == item["request_hash"]
        and result.result_hash == item["result_hash"]
    )
    formal = d.read(d.public(item["reference"]))
    validate_evaluation_evidence(formal)
    assert serialize_evaluation_evidence(req, result) == formal
    identity = ctx.runtime.identify(req.strategy, dependencies=req.dependencies)
    assert identity.content_sha256 == item["content_sha256"]
    report = audit.audit(ctx, req, result, formal, new=False, expected_cost=0.002 if fee else 0.001)
    assert report["status"] == "PASS" and report["whole_formal_native_exact"] is True
    report |= {
        "native_reference": item["reference"],
        "cache_sha256": item["cache_sha256"],
        "request_hash": result.request_hash,
        "result_hash": result.result_hash,
        "role": "BASELINE_REUSE_FEE" if fee else "BASELINE_REUSE_STANDARD",
        "financial_new_accounts": 0,
    }
    return (req, result), report


def baseline():
    ctx, exp, path, common, state, method, requests, fee, audit = p.stage()
    d.load(
        "robust_center_draft",
        ROOT / "research/S013/experiments/EX062_20261011/src/robust_center_draft.py",
    )
    plan = read_parameter_plan(
        EvidenceRef.from_dict(method["baseline_reuse"]["plan_reference"]), repository_root=ROOT
    )
    reports = []
    pairs = []
    for i, item in enumerate(
        [method["baseline_reuse"]["center"], *method["baseline_reuse"]["points"]]
    ):
        pair, report = reuse(ctx, common, item, audit)
        if i:
            assert pair[0].lineage.parameter_binding == plan.bind_point(
                EvidenceRef.from_dict(method["baseline_reuse"]["plan_reference"]),
                i - 1,
                repository_root=ROOT,
            )
        pairs.append(pair)
        reports.append(report)
    stress, stressreport = reuse(ctx, common, method["baseline_fee_reuse"], audit, fee=True)
    helper = d.load("economics_reference", path / "src/economics_reference.py")
    checked = helper.assess_native(
        center=helper.NativeEvaluation(*pairs[0]),
        points=tuple(helper.NativeEvaluation(*pair) for pair in pairs[1:]),
        design=plan.design,
        stress=helper.NativeEvaluation(*stress),
    )
    doc = {
        "status": "PASS",
        "actual_new_accounts": 0,
        "baseline_reused_standard": 33,
        "baseline_reused_fee": 1,
        "audits": reports,
        "fee_audit": stressreport,
        "panel": checked.panel.to_dict(),
        "economics": checked.economics,
        "limitations": checked.limitations,
        "parameter_plan_reference": method["baseline_reuse"]["plan_reference"],
        "provider_calls": common.SOURCE_CALLS,
    }
    AssessmentPanel.from_dict(doc["panel"]).validate()
    assert len(reports) == 33 and stressreport["status"] == "PASS"
    assert not common.SOURCE_CALLS
    ref = p.material(
        ctx,
        exp,
        WORK / "baseline_selfchecks.json",
        "pressure-early-exit-baseline-authenticated-latest-fivechecks",
        doc,
    )
    d.write(path / "protocols/baseline_selfchecks_reference.json", ref)
    return {
        "status": "BASELINE34_REUSE_PASS",
        "q10": checked.economics["absolute_q10_cagr"],
        "q90": checked.economics["absolute_q90_drawdown"],
    }


def finalize():
    ctx, exp, path, common, state, method, requests, fee, audit = p.stage()
    assert state["status"] == "FINANCIAL34_COMPLETE"
    pairs = []
    assert set(state["accounts"]) == {*(f"P{i:02}" for i in range(32)), "FEE"}
    for label in [*(f"P{i:02}" for i in range(32)), "FEE"]:
        item = state["accounts"][label]
        assert item["status"] == "AUDITED"
        proof = d.read(d.public(item["audit_reference"]))
        assert proof["status"] == "PASS" and proof["whole_formal_native_exact"] is True
        assert d.digest(ROOT / item["cache"]) == item["cache_sha256"]
        pair = common.cache_read(ROOT / item["cache"])
        assert serialize_evaluation_evidence(*pair) == d.read(d.public(item["reference"]))
        if label == "FEE":
            stress = pair
        else:
            pairs.append(pair)
    center = common.cache_read(WORK / "centre.pkl.gz")
    assert serialize_evaluation_evidence(*center) == d.read(
        d.public(d.read(path / "protocols/centre_reference.json"))
    )
    plan = read_parameter_plan(
        EvidenceRef.from_dict(method["parameter_plan_reference"]), repository_root=ROOT
    )
    helper = d.load("economics_reference", path / "src/economics_reference.py")
    checked = helper.assess_native(
        center=helper.NativeEvaluation(*center),
        points=tuple(helper.NativeEvaluation(*pair) for pair in pairs),
        design=plan.design,
        stress=helper.NativeEvaluation(*stress),
    )
    baseline = d.read(d.public(d.read(path / "protocols/baseline_selfchecks_reference.json")))
    assert baseline["status"] == "PASS" and baseline["actual_new_accounts"] == 0
    assert len(baseline["audits"]) == 33
    assert all(
        x["status"] == "PASS" and x["whole_formal_native_exact"] is True
        for x in [*baseline["audits"], baseline["fee_audit"]]
    )
    AssessmentPanel.from_dict(baseline["panel"]).validate()
    AssessmentPanel.from_dict(checked.panel.to_dict()).validate()
    centre_audit = d.read(
        d.public(d.read(path / "protocols/result_references.json")["verification"])
    )
    assert centre_audit["status"] == "PASS" and centre_audit["whole_formal_native_exact"] is True

    def summary(e):
        points = e["points"]
        gates = list(points[0]["gates"])
        return {
            "q10_cagr": e["absolute_q10_cagr"],
            "q90_full_drawdown": e["absolute_q90_drawdown"],
            "gate_pass_counts": {k: sum(x["gates"][k] for x in points) for k in gates},
            "gate_pass_rates": {k: sum(x["gates"][k] for x in points) / 32 for k in gates},
            "joint_count": sum(x["qualified"] for x in points),
            "joint_rate": sum(x["qualified"] for x in points) / 32,
            "point_count": 32,
            "year_positive_counts": {
                y: sum(x["annual"][y]["return"] > 0 for x in points) for y in points[0]["annual"]
            },
            "center": e["center"],
            "stress": e["stress"],
        }

    analysis = {
        "status": "COMPLETE",
        "rows": {
            "B0": summary(baseline["economics"]),
            "N_PRESSURE_EARLY_EXIT": summary(checked.economics),
        },
        "fivechecks": {
            "B0": {
                "panel": baseline["panel"],
                "economics": baseline["economics"],
                "limitations": baseline["limitations"],
            },
            "N_PRESSURE_EARLY_EXIT": {
                "panel": checked.panel.to_dict(),
                "economics": checked.economics,
                "limitations": checked.limitations,
            },
        },
        "comparison": {
            "paired_geometry": False,
            "baseline_dimensions": 13,
            "new_dimensions": 15,
            "meaning": "Descriptive comparison of each own standard selfcheck; no paired point causal effect or equal coordinate intensity.",
            "q10_difference": checked.economics["absolute_q10_cagr"]
            - baseline["economics"]["absolute_q10_cagr"],
            "q90_difference": checked.economics["absolute_q90_drawdown"]
            - baseline["economics"]["absolute_q90_drawdown"],
        },
        "integer_coverage": method["integer_coverage"],
        "counts": {
            "new_centre": 1,
            "new_standard32": 32,
            "new_fee": 1,
            "new_integer_neighbours": 0,
            "new_financial_total": 34,
            "new_technical_financial": 0,
            "baseline_reuse_standard": 33,
            "baseline_reuse_fee": 1,
            "all_native_accounts_including_reuse": 68,
        },
        "all_new_native_accounts": {
            "CENTRE": d.read(WORK / "execution_complete.json"),
            **state["accounts"],
        },
        "baseline_reuse": method["baseline_reuse"],
        "baseline_fee_reuse": method["baseline_fee_reuse"],
        "method_reference": state["method_reference"],
        "centre_economics": d.read(WORK / "verification.json")["economics"],
        "root_centre_reconciliation_refs": method["root_centre_reconciliation_refs"],
        "scientific_review": "PENDING_ROOT_NO_SELECTION_OR_OVERALL_GOAL_CLAIM",
        "provider_calls": common.SOURCE_CALLS,
    }
    assert (
        set(state["accounts"]) == {*(f"P{i:02}" for i in range(32)), "FEE"}
        and not common.SOURCE_CALLS
    )
    ref = p.material(
        ctx,
        exp,
        WORK / "analysis.json",
        "pressure-early-exit-complete-native-analysis-fivechecks",
        analysis,
    )
    d.write(path / "protocols/analysis_reference.json", ref)
    return {
        "status": "ANALYSIS_COMPLETE",
        "comparison": analysis["comparison"],
        "summaries": {
            k: {n: v for n, v in row.items() if n not in ("center", "stress")}
            for k, row in analysis["rows"].items()
        },
        "counts": analysis["counts"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("baseline", "finalize"))
    args = parser.parse_args()
    print(json.dumps(globals()[args.action](), ensure_ascii=False), flush=True)
