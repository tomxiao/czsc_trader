"""Reuse the twelve published center accounts; report unrun neighborhoods explicitly."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage4-20261102"
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
sys.pycache_prefix = str(SCRATCH / "pycache")
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"

from hashlib import sha256
import json

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity, build_equity_assessment
from strategy_evaluator import assess_candidates, compare_candidates
from strategy_evaluator import research_models as m
from strategy_evaluator.equity_assessment import EquityCertificationScope

KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def authenticate(value, key, scenario, cost):
    ref = EvidenceRef.from_dict(value)
    assert ref.schema == "equity_research" and ref.schema_version == 4
    path = ref.resolve(ROOT)
    data = path.read_bytes()
    assert sha256(data).hexdigest() == ref.sha256
    envelope = json.loads(data)
    owned = {(envelope[name]["kind"], envelope[name]["sha256"])
             for name in ("input_ref", "candidate_ref", "benchmark_ref")}

    def resolve(item):
        assert (item["kind"], item["sha256"]) in owned
        payload = (path.parent / (item["sha256"] + ".json")).read_bytes()
        assert sha256(payload).hexdigest() == item["sha256"]
        return payload

    view = materialize_equity(data, resolve)
    request = view.payload["request"]
    assert request["scenario_id"] == scenario and request["fee_rate"] == cost
    assert request["window_id"] == "TRAIN_2024_2025" and request["initial_cash"] == 100000.
    assert request["window"] == {"start": "2024-01-02T14:30:00+00:00", "end": "2025-12-31T21:00:00+00:00"}
    assert request["history_start"] == "2023-11-01" and request["drawdown_basis"] == "BAR_CLOSE"
    fact, = build_equity_assessment(view)
    assert fact.candidate.candidate_id == "S017-" + key
    print("AUTHENTICATED_EXISTING", key, scenario, flush=True)
    return fact


def main():
    standard = read(ROOT / "research/S017/experiments/EX072_20261102/others/all_accounts.json")
    pressure = read(WORK / "others/pressure.json")
    assert pressure["status"] == "COMPLETED"
    with EquityCertificationScope():
        facts = tuple(authenticate(source, key, scenario, cost)
                      for key in KEYS for source, scenario, cost in (
                          (standard[key]["evidence"], "STANDARD", .001),
                          (pressure["records"][key]["evidence"], "PRESSURE", .002)))
        centers = tuple(fact.candidate for fact in facts[::2])
        designs = tuple(m.ParameterNeighborhoodDesign.from_dict(
            read(SCRATCH / "proposed_designs" / (key + ".json"))) for key in KEYS)
        assert sum(design.point_count for design in designs) == 2829
        protocol = m.NeighborhoodSelfCheckProtocol("s017-stage4-confirmed-calmar-v1", "TRAIN_2024_2025",
            "STANDARD", "PRESSURE", 252, 21, m.QuantileMethod.LINEAR, 1, 1000, 20, 17, 1e-7,
            parameter_protocol=m.ParameterNeighborhoodProtocol(), pbo_blocks=10, frequency_min_closed_cycles=3)
        request = m.CandidateAssessmentRequest(centers, protocol, (), facts, parameter_designs=designs)
        panel = assess_candidates(request)
        targets = m.ResearchTargets.from_dict(read(ROOT / "research/S017/materials/STAGE1_FINAL_CONTRACT_20261102.json")["targets"])
        metrics = (m.ResearchMetric.NET_CALMAR, m.ResearchMetric.DRAWDOWN_MAGNITUDE,
                   *m.CALMAR_WITHIN_LAYER_METRICS, m.ResearchMetric.FREQUENCY_MEDIAN)
        bins = tuple(m.MetricBinSpec(metric, .5 if metric is m.ResearchMetric.FREQUENCY_MEDIAN else .0001,
                                    0., m.BinRounding.FLOOR) for metric in metrics)
        policy = m.ComparisonPolicy("s017-calmar-v1", bins, m.ParetoBasis.RAW,
                                   m.MissingEvidencePolicy.REQUIRE_COMPLETE, formula_version="research-ranking-v5")
        contract = m.CommonNeighborhoodComparisonContract(m.RelativeChangeLimit(.05), tuple(
            m.ZeroCenterAbsoluteLimit(name, m.AbsoluteChangeLimit(.05))
            for name in ("g_when_u", "g_when_other", "g_when_mf")))
        comparison = compare_candidates(m.CalmarComparisonRequest(centers, targets, panel, policy, designs, contract))
        save(WORK / "others/partial_selfcheck_panel.json", panel.to_dict())
        save(WORK / "others/partial_comparison.json", comparison.to_dict())
        rows = [{"candidate": row.candidate.candidate_id, "acceptance": row.acceptance_status.value,
                 "comparison_status": row.status.value, "pareto_layer": row.pareto_layer,
                 "target_checks": [{"target": check.target.target_id, "status": check.status.value}
                                   for check in row.target_checks]} for row in comparison.rows]
        assert all(row["pareto_layer"] is None for row in rows)
        save(WORK / "others/partial_selfcheck_summary.json", {
            "status": "PARTIAL_NOT_STAGE4_COMPLETE", "new_accounts": 0, "reused_accounts": 12,
            "neighbors_prescribed": 2829, "neighbors_run": 0,
            "family_selection_evidence": "INSUFFICIENT: six centers are not complete S017 selection history",
            "full_neighborhood_status": "NOT_RUN_PENDING_BOUNDED_FACTS_DEV_AUTHORIZATION",
            "rankable_candidates": [], "rows": rows, "sealed_prices_accessed": False})
        print("PARTIAL_SELFCHECK", rows, flush=True)


if __name__ == "__main__":
    main()
