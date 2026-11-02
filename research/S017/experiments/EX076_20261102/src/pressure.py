"""Run only the six already-authorized fee-stress scenarios, using pinned local data."""
# Environment and caches must precede numerical/runtime imports.
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".tmp/s017-stage4-20261102"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / "pycache")
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

from dataclasses import asdict
from datetime import date, datetime
from hashlib import sha256
import copy
import json
import math
from uuid import UUID
from zoneinfo import ZoneInfo

from dataflows import ProviderConfig, PreparedDataRef, SourceRef, TimeInterval
from czsc_trader.application import (
    RepositoryContext, create_research_context, load_candidate, publish_evidence_many,
    update_research_intent, ResearchIntentUpdate,
)
from czsc_trader.research_tools import (
    ResearchBatchRef, ExperimentRef, EquityEvaluationRequest, EquitySources,
    EvaluationBenchmark, EquityBuyHold, ResearchExecutionSession, ExecutionCheckpointRequest,
    EvaluationEvidenceWrite, build_assessment_evidence,
)
from czsc_trader.research_tools.equity_replay import materialize_equity
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources

KEYS = ("C0338", "C0339", "C0340", "C0341", "C0342", "C0352")
R = RepositoryContext.discover(ROOT)
B = ResearchBatchRef("S017")
E = ExperimentRef("S017", WORK.name)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def summary(run):
    points, daily = run["account_points"], run["account_daily"]
    assert len(points) == 6490 and len(daily) == 502
    assert daily[0]["session"] == "2024-01-02" and daily[-1]["session"] == "2025-12-31"
    high, dd = 100000., 0.
    for point in points:
        high = max(high, point["equity"])
        dd = max(dd, 1 - point["equity"] / high)
    annual = (points[-1]["equity"] / 100000.) ** (252 / 502) - 1
    assert math.isclose(annual, run["metrics"]["annualized_return"], rel_tol=1e-11, abs_tol=1e-10)
    assert math.isclose(dd, run["metrics"]["bar_max_drawdown"], rel_tol=1e-11, abs_tol=1e-10)
    return {"annualized_return": annual, "drawdown": dd, "ending_equity": points[-1]["equity"],
            "ending_quantity": points[-1]["quantity"], "closed_cycles": sum(t["status"] == "CLOSED" for t in run["trades"])}


def main():
    outpath = WORK / "others/pressure.json"
    if outpath.exists():
        raise RuntimeError("Existing pressure attempt requires explicit state review; no blind rerun")
    values = read(ROOT / "research/S017/experiments/EX072_20261102/others/data_preparation.json")["reference"]
    assert values["manifest_sha256"] == "a671f92acb0723e4054b26247bca52d39186c3a0f87e25e70a133b48987a242d"
    prepared = PreparedDataRef(UUID(values["space_id"]), UUID(values["preparation_id"]), values["manifest_sha256"])
    candidates = tuple(load_candidate(R, CandidateKey("S017", key)) for key in KEYS)
    research = create_research_context(R, B, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=candidates[0].definition.execution_spec, resources=ExecutionResources(4, 1, 17))
    source = SourceRef("futu", "s017-development-gap-known-interruptions-v1-20261028")
    rules = SourceRef("s017-research-rules", "same-approved-us-assumptions-v4-ex032-v1")
    zone = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2024, 1, 2, 9, 30, tzinfo=zone), datetime(2025, 12, 31, 16, tzinfo=zone))
    requests = tuple(EquityEvaluationRequest(E, candidate, window, date(2023, 11, 1),
        EquitySources(source, source, source, rules), 100000., .002, prepared=prepared,
        benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
        window_id="TRAIN_2024_2025", scenario_id="PRESSURE", measurement_tier="STRESS",
        drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE", frequency_window_days=60) for candidate in candidates)
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_four_20261102"] = {
        "status": "RANKING_REVIEW_AND_SEPARATE_PRESSURE_RUNNING", "candidates": list(KEYS),
        "user_stage_four_authorization": "批准这6个配置进入阶段四，请你主导执行自检与排序",
        "user_sorting_confirmation": "同意：Calmar/DD分层及逐点Calmar Q10第一项，其他顺序不变",
        "new_ranking_platform_implementation": "PENDING_SEPARATE_DEV_AUTHORIZATION",
        "neighborhood_comparability_and_zero_scale": "PROPOSED_NOT_CONFIRMED",
        "planned_neighbors": 2829, "neighbors_executed": 0,
        "authorized_independent_pressure_candidates": 6, "sealed_test_authorized": False,
    }
    update_research_intent(R, B, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="阶段四及两项排序调整已确认；先做零账户邻域规划与既定独立费用压力，DEV及新比较口径待决定，不运行大邻域")
    record = {"status": "RUNNING", "candidate_budget": 6, "fee_rate": .002,
              "checkpoint": "EX076-pressure-v1", "sealed_prices_accessed": False, "records": {}}
    save(outpath, record)
    source_hashes = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in (
        WORK / "src/pressure.py", WORK / "protocols/pressure.md")}
    facts = []
    with ResearchExecutionSession(research, experiment=E, checkpoint=ExecutionCheckpointRequest("EX076-pressure-v1"),
        on_progress=lambda event: print("PRESSURE_PROGRESS", event.phase.value, event.completed, event.total, flush=True)) as execution:
        handles = tuple(research.evaluation.prepare(request, execution=execution) for request in requests)
        outcomes = research.evaluation.evaluate_many(handles, execution=execution)
        if any(outcome.status.value != "SUCCEEDED" or outcome.result is None for outcome in outcomes):
            record.update(status="FAILED_EXPLICIT_NO_RETRY", outcomes=[{
                "candidate": key, "status": outcome.status.value,
                "error": None if outcome.error is None else {"code": outcome.error.code, "message": outcome.error.message}}
                for key, outcome in zip(KEYS, outcomes, strict=True)])
            save(outpath, record)
            raise RuntimeError("Pressure evaluation incomplete; explicit review required")
        publications = publish_evidence_many(research, tuple(EvaluationEvidenceWrite(E, "pressure-" + key,
            handle, outcome.result) for key, handle, outcome in zip(KEYS, handles, outcomes, strict=True)), execution=execution)
        if any(publication.status.value != "PUBLISHED" for publication in publications):
            record.update(status="PUBLICATION_INCOMPLETE_NO_RETRY", publications=[p.to_dict() for p in publications])
            save(outpath, record)
            raise RuntimeError("Pressure publication incomplete; inspect exact states")
        for key, handle, outcome, publication in zip(KEYS, handles, outcomes, publications, strict=True):
            payload = materialize_equity(outcome.result).payload
            assert payload["request"]["fee_rate"] == .002 and payload["request"]["scenario_id"] == "PRESSURE"
            candidate, benchmark = summary(payload["runs"]["candidate"]), summary(payload["runs"]["buy_hold"])
            checks = {"positive_return": candidate["annualized_return"] > 0,
                      "relative_return": candidate["annualized_return"] > benchmark["annualized_return"],
                      "relative_drawdown": candidate["drawdown"] < benchmark["drawdown"] if benchmark["drawdown"] > 0 else candidate["drawdown"] <= 0,
                      "absolute_drawdown": candidate["drawdown"] <= .25}
            fact, = build_assessment_evidence(handle, outcome.result, execution=execution)
            facts.append(fact.to_dict())
            record["records"][key] = {"candidate": candidate, "benchmark": benchmark, "checks": checks,
                "pressure_all_pass": all(checks.values()), "evidence": publication.reference.to_dict(),
                "evaluation_id": payload["evaluation_id"], "evaluation_identity": payload["evaluation_identity"],
                "request_hash": payload["request_hash"], "content_sha256": handle.candidate.content_identity.content_sha256}
            save(outpath, record)
            print("PRESSURE_RESULT", key, candidate, checks, flush=True)
        record["execution_stats"] = {"session": asdict(execution.stats), "equity": asdict(execution.equity_statistics)}
    assert all(sha256((ROOT / path).read_bytes()).hexdigest() == value for path, value in source_hashes.items())
    save(SCRATCH / "pressure_facts.json", facts)
    record.update(status="COMPLETED", source_hashes=source_hashes, new_candidate_accounts=6,
                  approved_neighbors_executed=0, new_searches=0)
    save(outpath, record)
    print("ALL_PRESSURE_SCENARIOS_PUBLISHED", [key for key in KEYS if record["records"][key]["pressure_all_pass"]], flush=True)


if __name__ == "__main__":
    main()
