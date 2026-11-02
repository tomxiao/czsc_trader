"""Prepare one source plan via public TDR APIs; never start account workers."""
# ruff: noqa: E402
from run_bounded_stage4_v1 import ROOT, WORK, OUT, read, save, require
from neighborhoods import request_for, context_for, child_candidate, E, KEYS
import argparse
from time import perf_counter
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("center", choices=KEYS)
    key = parser.parse_args().center
    begun = perf_counter()
    path = OUT / "plans" / (key + ".json")
    require(not path.exists(), "Existing source plan requires explicit review")
    repository = RepositoryContext.discover(ROOT)
    center = load_candidate(repository, CandidateKey("S017", key))
    context = context_for(repository, center)
    context.evaluation.resources = ExecutionResources(1, 1, 17)
    old = d.ParameterEvaluationPlan.from_dict(read(WORK / "others/parameter_plans" / (key + ".json")))
    old_entry = read(WORK / "others/parameter_plans" / (key + "-reference.json"))
    proposal = read(WORK / "others/bounded_parameter_check_proposal.json")["centers"][key]
    require(old.design.sha256 == proposal["source_full_design_sha256"], "Source geometry differs")
    with d.ResearchExecutionSession(context, experiment=E) as execution:
        central = context.evaluation.prepare(request_for(center), execution=execution)
        children = []
        for index in range(old.design.point_count):
            children.append(context.evaluation.prepare(request_for(child_candidate(center, old.design,
                index, old_entry["start"])), execution=execution))
            if (index + 1) % 64 == 0:
                print("SOURCE_PLAN_PREPARED", key, index + 1, old.design.point_count, flush=True)
        plan = d.ParameterEvaluationPlan.create(old.design, central, tuple(children),
            mapping_evidence=old.mapping_evidence, feasibility_evidence=old.feasibility_evidence,
            dataflows=context.data, execution=execution)
        save(path, plan.to_dict())
        reference = publish_evidence(context, d.MaterialEvidenceWrite(E, "bounded-v1-plan-" + key,
            path.read_bytes(), "application/json", "json"), execution=execution)
        save(OUT / "plans" / (key + "-reference.json"), {"reference": reference.to_dict(),
            "start": old_entry["start"], "N": old.design.point_count,
            "selected_N": proposal["proposed_N"], "design_sha256": old.design.sha256,
            "center_request_sha256": plan.center_request_sha256,
            "preparation_elapsed_seconds": perf_counter() - begun,
            "account_replays": execution.equity_statistics.candidate_runs,
            "worker_processes_started": execution.stats.pool_starts})
    print("SOURCE_PLAN_READY", key, perf_counter() - begun, flush=True)


if __name__ == "__main__":
    main()
