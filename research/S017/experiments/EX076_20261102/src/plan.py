"""Zero-account capability and full-neighborhood geometry planning only."""
# Cache settings must precede runtime imports.
# ruff: noqa: E402
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage4-20261102"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / "pycache")

from hashlib import sha256
import json

from czsc_trader.application import RepositoryContext, load_candidate, get_research_overview
from czsc_trader.research_tools import ResearchBatchRef
from strategy_manager import CandidateKey
from strategy_evaluator import (
    AssessmentCandidate, ParameterAxis, RealDomain, BoundedLocalStep,
    RelativeChangeLimit, AbsoluteChangeLimit, ParameterNeighborhoodSpace,
    ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest,
    build_parameter_neighborhood_design, ResearchMetric, MetricBinSpec, BinRounding,
)

KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
NAMES = ("alpha", "initial_fraction", "accepted_fraction", "g_when_u", "g_when_other", "g_when_mf")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    repository = RepositoryContext.discover(ROOT)
    overview = get_research_overview(repository, ResearchBatchRef("S017")).to_dict()
    save(SCRATCH / "overview_before.json", overview)
    assert next(x for x in overview["deliveries"] if x["stage"] == "CANDIDATES")["revision"] == 3
    mapping = {name: {"payload_path": [name], "unit": "atr_multiple" if name == "alpha" else "price_span_fraction"}
               for name in NAMES}
    constraints = {"pure_parameter_constraints": "none beyond declared finite domains", "uses_prices_or_performance": False}
    save(WORK / "protocols/parameter_mapping_proposal.json", mapping)
    save(WORK / "protocols/parameter_constraints_proposal.json", constraints)
    mapping_sha = sha256((WORK / "protocols/parameter_mapping_proposal.json").read_bytes()).hexdigest()
    constraints_sha = sha256((WORK / "protocols/parameter_constraints_proposal.json").read_bytes()).hexdigest()
    results = []
    for key in KEYS:
        candidate = load_candidate(repository, CandidateKey("S017", key))
        params = json.loads(candidate.definition.parameters_json)
        axes = tuple(ParameterAxis(name, float(params[name]), RealDomain(0.0, 2.0 if name == "alpha" else 1.0),
                    BoundedLocalStep(AbsoluteChangeLimit(0.05) if params[name] == 0.0 else RelativeChangeLimit(0.05)),
                    (name,), mapping[name]["unit"]) for name in NAMES)
        result = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
            AssessmentCandidate("S017-" + key, candidate.content_identity.content_sha256),
            ParameterNeighborhoodProtocol(), ParameterNeighborhoodSpace(axes, mapping_sha, constraints_sha)),
            feasibility=lambda values: True)
        assert result.status.value == "COMPLETE", result.to_dict()
        design = result.design
        save(SCRATCH / "proposed_designs" / (key + ".json"), design.to_dict())
        axis_values = {name: sorted({v.value for point in design.points for v in point.values if v.name == name} | {params[name]})
                       for name in NAMES}
        results.append({"candidate": key, "point_count": design.point_count,
            "design_sha256": design.sha256, "comparison_sha256": design.comparison_sha256,
            "parameters": params, "axis_values": axis_values,
            "zero_center_absolute_005_is_proposed_not_confirmed": any(params[n] == 0 for n in NAMES)})
    rejections = {}
    try:
        MetricBinSpec(ResearchMetric.NET_CALMAR, .0001, 0., BinRounding.FLOOR)
    except ValueError as exc:
        rejections["calmar_pareto_bin"] = str(exc)
    try:
        ResearchMetric("PARAMETER_CALMAR_Q10")
    except ValueError as exc:
        rejections["neighbor_calmar_q10_metric"] = str(exc)
    assert len(rejections) == 2
    total = sum(row["point_count"] for row in results)
    assert total == 2829
    assert len({row["comparison_sha256"] for row in results}) == 6
    save(WORK / "others/planning.json", {"status": "PROPOSED_ZERO_COMPUTE_PLANNING",
        "user_confirmed_sorting_changes": ["Pareto NET_CALMAR/DRAWDOWN", "neighbor individual-Calmar LINEAR Q10 first within layer"],
        "public_ranking_supported": False, "constructor_rejections": rejections,
        "zero_center_scale": "PROPOSED absolute 0.05 of natural [0,1] g domain; not user-confirmed",
        "other_nonzero_axes": "relative +/-5%, legal directions only, no clipping or point sampling",
        "designs": results, "total_noncenter_points": total, "separate_pressure_candidate_accounts": 6,
        "center_standard_accounts_reused": 6, "financial_accounts_run_in_planning": 0,
        "unique_comparison_profiles": 6,
        "current_global_ranking": "INCOMPARABLE/PARAMETER_METHODS_DIFFER under REQUIRE_COMPLETE",
        "bulk_neighbors_executed": False, "sealed_prices_accessed": False})
    print("ZERO_COMPUTE_PLAN", [(r["candidate"], r["point_count"]) for r in results], total,
          "six_different_profiles;public_new_ranking_unsupported", flush=True)


if __name__ == "__main__":
    main()
