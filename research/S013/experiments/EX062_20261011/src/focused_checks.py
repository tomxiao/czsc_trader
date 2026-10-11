"""Pure EX062 checks. No cache, formal-account, market, prepare/evaluate reads."""

from dataclasses import dataclass
from hashlib import sha256
import inspect
import json
from pathlib import Path

import optuna
from strategy_manager import CandidateDerivation, CandidateDerivationKind, CandidateEvidence, CandidateKey
from czsc_trader.research_tools import EvaluationLineage
from czsc_trader.research_tools.parameter_evaluation import ParameterEvaluationPlan
import robust_center_draft as draft
from czsc_trader.research_tools.evidence import EvidenceRef


def run():
    checks = []
    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    proposals, coordinates, _, record = draft.metadata_queue()
    check("nine frozen full-vector centers", len(proposals) == 9)
    check("three native centers preserved", [p.existing_candidate for p in proposals[:3]] == ["C8880", "C8840", "C8860"])
    check("six new centers", all(p.existing_candidate is None for p in proposals[3:]))
    check("payload duplicates removed", len({p.parameters_json for p in proposals}) == 9)
    check("protocol exact", draft.PROTOCOL.radius == .05 and draft.PROTOCOL.point_count == 32 and draft.PROTOCOL.seed == 13)
    mapping, feasibility = (EvidenceRef.from_dict(record[name]) for name in ("mapping_evidence", "feasibility_evidence")) if "mapping_evidence" in record else (None, None)
    # Design accepts only evidence SHA fields here; these are pure fixtures, not published refs.
    @dataclass(frozen=True)
    class RefHash:
        sha256: str
    mapping, feasibility = mapping or RefHash("1" * 64), feasibility or RefHash("2" * 64)
    @dataclass(frozen=True)
    class StrategyFixture:
        reference_id: str
        payload: dict
    @dataclass(frozen=True)
    class IdentityFixture:
        content_sha256: str
    designs = []
    for index, proposal in enumerate(proposals):
        strategy = StrategyFixture(f"S013-C{1000+index:04}", {"parameters": proposal.parameters})
        design = draft.design_for(strategy, IdentityFixture(sha256(proposal.parameters_json.encode()).hexdigest()),
                                  coordinates, mapping, feasibility)
        designs.append(design)
        check(f"center {index} full32", len(design.points) == 32)
        check(f"center {index} original domains", [(c.name, c.lower, c.upper, c.kind.value) for c in design.space.coordinates] == [tuple(c) for c in coordinates])
        for point in design.points:
            materialized = draft.materialize(proposal.parameters, coordinates, point.coordinates)
            check(f"center {index} point {point.index} valid all13", draft.feasible(point.coordinates) and materialized["mechanism"] == draft.MECHANISM)
    check("new center design recenters", designs[0].points != designs[1].points and designs[0].points != designs[2].points)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = draft.queue_study(proposals)
    for index in range(9):
        trial = study.ask()
        check(f"Optuna queue {index}", trial.suggest_int("center_index", 0, 8) == index)
        study.tell(trial, (index, index / 100, .2 - index / 100))
    check("three objective directions", [d.name for d in study.directions] == ["MAXIMIZE", "MAXIMIZE", "MINIMIZE"])
    derivation = CandidateDerivation(CandidateKey("S013", "C8880"), "1" * 64,
        CandidateKey("S013", "C8840"), "2" * 64, CandidateDerivationKind.PARAMETERS,
        {"bear.max_hold": {"before": 4, "after": 5}}, "3" * 64,
        CandidateEvidence("research/S013/evidence/fake.json", "4" * 64))
    @dataclass(frozen=True)
    class NativeFixture:
        lineage: EvaluationLineage | None
        original_identity: str = "unchanged"
    # A sentinel represents an old typed binding for view-only transformation.
    old = NativeFixture(None)
    old_lineage = object.__new__(EvaluationLineage)
    object.__setattr__(old_lineage, "derivation", derivation)
    object.__setattr__(old_lineage, "parameter_binding", object())
    object.__setattr__(old, "lineage", old_lineage)
    view = draft.plan_center_view(old)
    check("native binding remains untouched", old.lineage.parameter_binding is not None)
    check("view removes only point binding", view.lineage.derivation == derivation and view.lineage.parameter_binding is None and view.original_identity == old.original_identity)
    check("public API binding guard exists", "create the prospective plan before adding point bindings" in inspect.getsource(ParameterEvaluationPlan.create))
    row = {"net_cagr": .2, "drawdown": .15, "gates": dict.fromkeys(draft.GATES, True)}
    points = [dict(row, net_cagr=.1 + index / 1000, drawdown=.2 + index / 1000) for index in range(32)]
    summary = draft.summarize_panel(row, points)
    check("complete full32 quantiles", summary["complete_points"] == 32 and abs(summary["q10_cagr"] - .1031) < 1e-12 and abs(summary["q90_drawdown"] - .2279) < 1e-12)
    check("joint gates all four", summary["joint_pass_count"] == 32)
    points[0]["gates"] = {**row["gates"], "frequency": False}
    check("failed neighbor remains included", draft.summarize_panel(row, points)["joint_pass_count"] == 31)
    poor_center = {**row, "gates": {**row["gates"], "return": False}}
    check("unqualified center still complete32", not draft.summarize_panel(poor_center, points)["center_qualified"])
    baseline = {**summary, "label": "BASE", "queue_index": 0}
    candidate = {**summary, "label": "BETTER", "queue_index": 1, "q10_cagr": .11, "q90_drawdown": .22}
    unqualified = {**candidate, "label": "DIAGNOSTIC", "queue_index": 2, "center_qualified": False, "q10_cagr": .5}
    selected = draft.selection([baseline, candidate, unqualified])
    check("old four gates alone qualify", selected["qualified_labels"] == ["BASE", "BETTER"] and selected["preferred"] == "BETTER")
    check("all-center Pareto retains diagnostic", "DIAGNOSTIC" in selected["pareto_all"])
    failures = 0
    for bad in (points[:31], points + [row]):
        try:
            draft.summarize_panel(row, bad)
        except ValueError:
            failures += 1
    vector = [draft.get_path(proposals[0].parameters, name) for name, *_ in coordinates]
    for value in (float("nan"), float("inf"), -1, True, 21.5):
        try:
            draft.materialize(proposals[0].parameters, coordinates, [value, *vector[1:]])
        except ValueError:
            failures += 1
    check("incomplete and invalid fixtures refused", failures == 7)
    root = Path(__file__).resolve().parent
    result = {"status": "PURE_PASS", "checks": len(checks), "check_names": checks,
              "new_account_evaluations": 0, "preparations": 0, "publications": 0,
              "native_cache_reads": 0, "market_reads": 0, "provider_calls": 0,
              "source_hashes": {p.name: sha256(p.read_bytes()).hexdigest() for p in (root / "robust_center_draft.py", Path(__file__))}}
    (root / "focused.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks)}))


if __name__ == "__main__":
    run()
