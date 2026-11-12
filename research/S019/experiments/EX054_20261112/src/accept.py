"""S019 acceptance of goal-driven equity evaluation on the approved history."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "research/RSCH_AGENT.md").is_file())
BATCH = ROOT / "research/S019"
SCRATCH = ROOT / ".tmp/s019-objective-acceptance"
SCRATCH.mkdir(exist_ok=True)
os.environ.update(TMP=str(SCRATCH), TEMP=str(SCRATCH))
sys.dont_write_bytecode = True
sys.path.insert(0, str(BATCH / "experiments/EX048_20261111/src"))

import batch_runner as core
from czsc_trader.application import create_experiment, ExperimentRequest, get_research_overview
from czsc_trader.research_tools.equity_replay import build_equity_assessment, materialize_equity
from strategy_evaluator import assess_candidates, research_models as m
from strategy_evaluator.equity_assessment import equity_performance
from strategy_evaluator.research_acceptance import check_target
from strategy_manager import CandidateKey


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def accepted_targets():
    mandate = read(BATCH / "assets/deliveries/MANDATE/2/delivery.json")
    return m.ResearchTargets.from_dict({
        "type": "ResearchTargets", "frequency_window_days": 60,
        "requirements": next(x["requirement"]["targets"] for x in mandate["content"]["payload"]["items"]
                             if x["item_id"] == "targets"),
    })


def replay(context, execution, request, name):
    prepared = context.evaluation.prepare(request, execution=execution)
    outcome, = context.evaluation.evaluate_many((prepared,), execution=execution)
    if outcome.result is None:
        raise RuntimeError(outcome.error)
    ref = core.publish_evidence(context,
        core.d.EvaluationEvidenceWrite(request.experiment, name, prepared, outcome.result), execution=execution)
    print(name, outcome.result.payload["schema"], "published", flush=True)
    return prepared, outcome.result, ref


def account(facts):
    annual, drawdown = equity_performance(facts)
    return {"nar": annual, "mdd": drawdown, "calmar": annual / drawdown,
            "sessions": len(facts.account), "closed_cycles": len(facts.closed_cycles)}


def output_checks(targets, row):
    result = {}
    for target in targets:
        check = check_target(target, row, 60)
        result[target.target_id] = check.to_dict()
        if isinstance(check, m.TargetCheck):
            result[target.target_id]["distance_to_bound"] = check.distance_to_bound
    return result


def main():
    repo = core.RepositoryContext.discover(ROOT, explicit_root=ROOT)
    overview = get_research_overview(repo, core.d.ResearchBatchRef("S019"))
    print("S019", overview.registered_state.value, len(overview.experiments), flush=True)
    candidate = core.load_candidate(repo, CandidateKey("S019", "C4477"))
    freeze = read(BATCH / "experiments/EX053_20261112/others/behavior_comparison.json")
    assert candidate.content_identity.content_sha256 == freeze["after"]
    context = core.replay_context(repo, candidate.definition.execution_spec)
    run_ref = SCRATCH / "experiment.json"
    if run_ref.exists():
        experiment = core.d.ExperimentRef.from_dict(read(run_ref))
    else:
        experiment = create_experiment(context, ExperimentRequest(
            "S019 按研究目标配置评价参照的验收",
            "在既定样本核对固定阈值、同条件买持和 S018-v1 参照，以及候选账户在两种请求下的一致性。",
            date(2026, 11, 12)))
        save(run_ref, experiment.to_dict())
    work = experiment.resolve(ROOT)
    if Path(__file__).resolve() != (work / "src/accept.py").resolve():
        shutil.copyfile(__file__, work / "src/accept.py")
    print(experiment.experiment_id, flush=True)
    request = core.request_for(experiment, candidate)
    pressure = replace(request, fee_rate=.002, scenario_id="STRESS", measurement_tier="STRESS")
    previous_ref = core.d.EvidenceRef.from_dict(read(BATCH / "experiments/EX052_20261112/others/stage4_reference.json"))
    previous = read(previous_ref.resolve(ROOT))
    assert previous["status"] == "COMPLETE" and previous["pass_all"]
    identity = read(BATCH / "experiments/EX003_20261110/others/reference_identity.json")
    assert identity["origin"]["runtime_candidate_id"] == "C9397"
    reference = core.d.EvidenceRef.from_dict(read(BATCH / "experiments/EX003_20261110/others/reference_account.json"))
    old_ref = core.d.EvidenceRef.from_dict(read(BATCH / "experiments/EX050_20261111/others/C1010_center_ref.json"))
    confirmed = accepted_targets().requirements
    standard_targets = tuple(x for x in confirmed if isinstance(x, m.FrequencyCoverageTarget)
                             or isinstance(x, m.ResearchTarget) and x.scope is m.TargetScope.STANDARD)
    stress_targets = tuple(x for x in confirmed if isinstance(x, m.ResearchTarget) and x.scope is m.TargetScope.STRESS)
    assert len(confirmed) == 12 and len(standard_targets) == 6
    protocol = m.NeighborhoodSelfCheckProtocol(
        "s019-goal-based-api-acceptance", "FULL", "STANDARD", "STRESS",
        252, 21, m.QuantileMethod.LINEAR, 1, 10000, 21, 20261110, 1e-8,
        m.ParameterNeighborhoodProtocol(), frequency_min_closed_cycles=3)
    save(work / "protocols/acceptance.json", {
        "mandate": "MANDATE/2", "candidate": candidate.content_identity.content_sha256,
        "window": previous["window"], "confirmed_targets": [x.to_dict() for x in confirmed],
        "protocol": protocol.to_dict(), "incumbent": reference.to_dict(), "new_parameter_replays": 0,
    })
    mode = core.d.CheckpointMode.RESUME if (SCRATCH / "started").exists() else core.d.CheckpointMode.CREATE
    checkpoint = core.d.ExecutionCheckpointRequest("s019-research-goals-v1", mode)
    with core.d.ResearchExecutionSession(context, experiment=experiment, checkpoint=checkpoint) as execution:
        (SCRATCH / "started").touch()
        _, absolute, absolute_ref = replay(context, execution, replace(request, benchmark=None), "absolute")
        assert execution.equity_statistics.benchmark_runs == 0
        mixed_handle, mixed, mixed_ref = replay(context, execution, request, "mixed")
        assert mixed.payload["candidate_ref"] == absolute.payload["candidate_ref"]
        assert mixed.payload["input_ref"] == absolute.payload["input_ref"]
        assert len(mixed.artifacts) == 3 and len(absolute.artifacts) == 2
        _, stressed, stressed_ref = replay(context, execution, pressure, "stress")
        print("replays", execution.equity_statistics.candidate_runs,
              execution.equity_statistics.benchmark_runs, "reused", execution.stats.reused_results, flush=True)
        mixed_fact, = core.d.build_assessment_evidence(mixed_handle, mixed, execution=execution)
        comparator = None
        reference_error = None
        try:
            comparator = core.d.build_assessment_reference(mixed_handle, mixed, reference, execution=execution)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            reference_error = f"{type(exc).__name__}: {exc}"
            print("reference failed", reference_error, flush=True)
        absolute_fact, = build_equity_assessment(absolute)
        stress_fact, = build_equity_assessment(stressed)
        row, = assess_candidates(m.CandidateAssessmentRequest(
            (mixed_fact.candidate,), protocol, (), (mixed_fact, stress_fact),
            include_absolute_time_stability=True,
            references=() if comparator is None else (comparator,))).rows
        absolute_row, = assess_candidates(m.CandidateAssessmentRequest(
            (absolute_fact.candidate,), protocol, (), (absolute_fact,))).rows
        assert row.absolute_time_stability.nar_interval == absolute_row.absolute_time_stability.nar_interval
        checks = output_checks((*standard_targets, *stress_targets), row)
        abs_checks = output_checks(standard_targets, absolute_row)
        assert {name for name, result in checks.items() if result["status"] != "PASSED"} == {"stress-zero-risk"}
        assert checks["stress-zero-risk"]["status"] == "NOT_APPLICABLE"
        assert abs_checks["center-relative-risk"]["reason"] == "MISSING_BOUND_BENCHMARK"
        for target in ("center-nar", "center-calmar", "center-risk"):
            assert checks[target]["status"] == abs_checks[target]["status"] == "PASSED"
            assert checks[target]["observed"] == abs_checks[target]["observed"]
        own, pressured = account(mixed_fact), account(stress_fact)
        for scenario, actual in (("standards", own), ("stress", pressured)):
            for metric in ("nar", "mdd", "calmar"):
                assert math.isclose(actual[metric], previous[scenario]["after"][metric], abs_tol=1e-12, rel_tol=1e-12)

        def legacy_account(ref):
            path = ref.resolve(ROOT)
            def resolve(dep):
                return path.with_name(dep["sha256"] + ".json").read_bytes()
            view = materialize_equity(path.read_bytes(), resolve)
            facts, = build_equity_assessment(view)
            assert facts.result_sha256 == ref.sha256
            return account(facts)

        old = legacy_account(old_ref)
        assert math.isclose(old["nar"], previous["standards"]["before"]["nar"], abs_tol=1e-12)
        observed = None
        if comparator is not None:
            value = comparator.performance
            target = m.ResearchTarget("diagnostic-s018-nar", m.ResearchMetric.NET_ANNUAL_RETURN,
                lower=m.BenchmarkBound(1., True), reference_evaluation_id=value.evaluation_id)
            routed = output_checks((target,), row)[target.target_id]
            assert routed["resolved_lower"] == value.annual_return
            assert value.evaluation_id in routed["evaluation_ids"]
            observed = {"nar": value.annual_return, "mdd": value.drawdown,
                "calmar": value.annual_return / value.drawdown, "diagnostic_routing": routed}
        neighborhood = previous["neighborhood"]
        assert neighborhood["status"] == "PASSED"
        assert neighborhood["joint_passes"] == neighborhood["all_point_passes"] == neighborhood["planned_points"] == 728
        summary = {"status": "PASS" if comparator is not None else "PARTIAL", "standard": own,
            "stress": pressured, "legacy_C1010": old, "incumbent": observed,
            "reference_error": reference_error, "mixed_checks": checks, "absolute_checks": abs_checks,
            "absolute_time_stability": row.absolute_time_stability.to_dict(),
            "buyhold_relative_nar_interval": row.uncertainty.to_dict(),
            "checkpoint_recovery": {"reused_results": execution.stats.reused_results,
                "candidate_runs": execution.equity_statistics.candidate_runs,
                "benchmark_runs": execution.equity_statistics.benchmark_runs},
            "prior_interval_research": {key: neighborhood[key] for key in
                ("planned_points", "minimum_joint_passes", "joint_passes", "all_point_passes", "status")},
            "evidence": {name: ref.to_dict() for name, ref in
                (("absolute", absolute_ref), ("mixed", mixed_ref), ("stress", stressed_ref),
                 ("legacy_C1010", old_ref), ("previous_interval", previous_ref), ("incumbent", reference))}}
        save(work / "others/acceptance.json", summary)
        print("RESULT", summary["status"], own, pressured, observed, flush=True)


if __name__ == "__main__":
    main()
