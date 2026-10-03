"""Fixed evaluations in one managed experiment with bounded process concurrency."""

from datetime import date
from hashlib import sha256
import json

import numpy as np
from strategy_runtime import StrategyCandidate, StrategyRuntime, ImplementationDependency
from strategy_manager import (
    CandidateKey,
    CandidateEvidence,
    CandidateDerivation,
    CandidateDerivationKind,
)
from czsc_trader.application import RepositoryContext, load_candidate
from czsc_trader.research_tools import (
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationBenchmark,
    EvaluationLineage,
    build_assessment_evidence,
)
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.backtesting.metrics import calculate_metrics


def evaluate_fixed(context, root, inputs):
    repo = root.parents[2]
    repository = RepositoryContext.discover(repo)
    dependencies = tuple(ImplementationDependency(**x) for x in inputs["dependencies"])
    runtime = StrategyRuntime()
    start, end = date(2025, 2, 6), date(2026, 9, 28)
    data = prepare_backtest_execution_data(
        srt_data_root=repo / ".tmp/s011-current/data" / root.name,
        symbol="159326.SZ",
        asset_type="etf",
        start=start,
        end=end,
        dataflows=context.data,
    )
    assert len(data.evaluation_sessions) == 403
    artifacts, records, summaries, relations = [], [], [], []

    def save(name, value):
        context.workspace.path(name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        artifacts.append(context.workspace.register_artifact(name, "fixed_evaluation"))

    specs = inputs.get("neighbors", inputs["centers"])
    for offset in range(0, len(specs), 16):
        requests = []
        for spec in specs[offset : offset + 16]:
            relation = None
            if "parent_candidate_id" in spec:
                parent = load_candidate(
                    repository, CandidateKey("S011", spec["parent_candidate_id"])
                )
                payload = json.loads(json.dumps(dict(parent.payload), default=dict))
                payload["parameters"] = spec["parameters"]
                candidate = StrategyCandidate(
                    "S011", spec["candidate_id"], payload, parent.source_root
                )
                evidence = (
                    repo / inputs["center_workspace"] / "records" / f"{parent.candidate_id}.json"
                )
                relation = CandidateDerivation(
                    CandidateKey("S011", parent.candidate_id),
                    runtime.identify(parent, dependencies=dependencies).content_sha256,
                    CandidateKey("S011", candidate.candidate_id),
                    runtime.identify(candidate, dependencies=dependencies).content_sha256,
                    CandidateDerivationKind.PARAMETERS,
                    {
                        key: {"before": parent.payload["parameters"][key], "after": value}
                        for key, value in spec["parameters"].items()
                        if value != parent.payload["parameters"][key]
                    },
                    spec["protocol_sha256"],
                    CandidateEvidence(
                        evidence.relative_to(repo).as_posix(),
                        sha256(evidence.read_bytes()).hexdigest(),
                    ),
                )
                relations.append(
                    {
                        "slot": spec["slot"],
                        "candidate_id": candidate.candidate_id,
                        "derivation": relation.to_dict(),
                    }
                )
            else:
                candidate = load_candidate(repository, CandidateKey("S011", spec["candidate_id"]))
            costs = (EvaluationCost("standard", 0.001, "FORMAL"),)
            if relation is None:
                costs += (EvaluationCost("fee_20bp", 0.002, "STRESS"),)
            requests.append(
                EvaluationRequest(
                    repository_root=repo,
                    experiment_id=root.name,
                    strategy=candidate,
                    runtime_binding={
                        "candidate_id": candidate.reference_id,
                        "source_files": list(candidate.payload["runtime"]["source_files"]),
                        "implementation_sha256": candidate.payload["runtime"]["source_sha256"],
                    },
                    symbol="159326.SZ",
                    asset_type="etf",
                    windows=(EvaluationWindow("full", start, end),),
                    data_cutoff=end,
                    initial_cash=1_000_000,
                    costs=costs,
                    execution_data=data,
                    benchmark=EvaluationBenchmark.from_dict(inputs["benchmark"]),
                    workers=1,
                    frequency_window_days=60,
                    dependencies=dependencies,
                    lineage=EvaluationLineage(relation) if relation else None,
                )
            )
        outcomes = context.evaluation.evaluate_many(tuple(requests))
        for request, outcome in zip(requests, outcomes, strict=True):
            record, result = outcome.record, outcome.result
            if result is None:
                raise RuntimeError(f"{record.candidate_id}: {record.to_dict()}")
            candidate = request.strategy
            records.append(record.to_dict())
            save(f"records/{candidate.candidate_id}.json", record.to_dict())
            save(
                f"assessment/{candidate.candidate_id}.json",
                [x.to_dict() for x in build_assessment_evidence(request, result)],
            )
            for run in result.runs:
                account = run.execution.account_daily
                assert np.allclose(
                    account.cash + account.quantity * account.close,
                    account.equity,
                    rtol=0,
                    atol=1e-6,
                )
                assert account.quantity.mod(100).eq(0).all() and account.cash.ge(-1e-6).all()
                metrics = calculate_metrics(run.execution, 1_000_000)
                benchmark = run.buyhold.metrics
                cagr = run.observation.net_cagr
                bcagr = (1 + benchmark["return"]) ** (252 / len(account)) - 1
                frequency = 60 * metrics["closed_trades"] / len(account)
                targets = {
                    "return_multiple": cagr >= 1.5 * bcagr,
                    "positive_if_nonpositive": bcagr > 0 or (cagr > 0 and cagr > bcagr),
                    "strict_drawdown": abs(metrics["max_drawdown"])
                    < abs(benchmark["max_drawdown"]),
                    "frequency": 4 <= frequency <= 6,
                }
                summaries.append(
                    dict(
                        candidate_id=candidate.reference_id,
                        scenario=run.scenario_id,
                        metrics=metrics,
                        cagr=cagr,
                        benchmark_cagr=bcagr,
                        benchmark_metrics=benchmark,
                        frequency=frequency,
                        targets=targets,
                        all_targets_met=all(targets.values()),
                        evaluation_id=run.identity.evaluation_id,
                        content_sha256=run.identity.content_sha256,
                    )
                )
            print(f"{root.name}: {len(records)}/{len(specs)} completed", flush=True)
        del outcomes, requests
    save("summaries.json", summaries)
    save("derivations.json", relations)
    save("evaluation_records.json", records)
    return artifacts
