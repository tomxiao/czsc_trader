"""Fixed complete-cohort diagnostics through a process-owned formal context."""

from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import time

import numpy as np
from dataflows import Dataset
from research_experiment import (
    ResearchExperiment,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentDataScope,
    ExperimentStage,
    ExperimentProtocol,
    ExperimentDependency,
    ExperimentCapabilities,
    ExperimentResult,
    ExperimentOutcome,
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
)
from strategy_runtime import StrategyRuntime, StrategyCandidate, ImplementationDependency
from strategy_manager import (
    CandidateKey,
    CandidateDerivation,
    CandidateDerivationKind,
    CandidateEvidence,
)
from czsc_trader.application import (
    RepositoryContext,
    load_candidate,
)
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

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
DEPS = tuple(ImplementationDependency(**x) for x in INPUTS["dependencies"])
START, END = date(2025, 2, 6), date(2026, 9, 28)


def child(spec, parent):
    payload = json.loads(json.dumps(dict(parent.payload), default=dict))
    payload["parameters"] = spec["parameters"]
    return StrategyCandidate("S011", spec["candidate_id"], payload, parent.source_root)


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id=ROOT.name,
            strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=END,
            random_seed=20261002,
            subjects=("159326.SZ",),
            research_question="Do all existing centers and their fixed neighborhoods retain their current-content account evidence?",
            hypothesis="Current-content diagnostics can quantify local degradation without changing center implementations.",
            falsification_conditions=(
                "Identity or account semantics differ",
                "A declared slot fails without retained evidence",
            ),
            allowed_datasets=tuple(
                x.value
                for x in (
                    Dataset.ETF_OHLCV,
                    Dataset.ETF_UNADJUSTED_DAILY,
                    Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY,
                    Dataset.GLOBAL_INDEX_DAILY,
                    Dataset.TRADING_CALENDAR,
                )
            ),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(
                ExperimentStage.ROBUSTNESS,
                ("Seen development data, original fixed design",),
                ("DFLS, SRT, TDR managed evaluation, TXE accounts, typed SE evidence",),
                ("Fixed inputs; no adaptive selection or retries",),
                ("Joint parameter and cost sensitivity; diagnostics are not new economic gates",),
                ("Process-owned context, worker=1 and native thread=1",),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        context = RepositoryContext.discover(REPO)
        runtime = StrategyRuntime()
        for path, digest in INPUTS["source_evidence"].items():
            assert sha256((REPO / path).read_bytes()).hexdigest() == digest
        for spec in INPUTS["centers"]:
            item = load_candidate(context, CandidateKey("S011", spec["candidate_id"]))
            assert runtime.identify(item, dependencies=DEPS).content_sha256 == spec["content_sha256"]
            runtime.describe(item)
        for spec in INPUTS["neighbors"]:
            parent = load_candidate(context, CandidateKey("S011", spec["parent_candidate_id"]))
            assert runtime.identify(parent, dependencies=DEPS).content_sha256 == spec["parent_content_sha256"]
            item = child(spec, parent)
            assert runtime.identify(item, dependencies=DEPS).content_sha256 == spec["content_sha256"]
            runtime.describe(item)
            previous = load_candidate(context, CandidateKey("S011", spec["previous_candidate_id"]))
            assert dict(item.payload["parameters"]) == dict(previous.payload["parameters"])
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "FIXED_INPUTS",
                    ExperimentPreflightStatus.PASS,
                    "Current parent, fixed neighborhood, dependency and predecessor evidence match",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"slots": len(INPUTS["neighbors"])}, {}),
        )

    def execute(self, context):
        started = time.time()
        repository = RepositoryContext.discover(REPO)
        data = prepare_backtest_execution_data(
            srt_data_root=REPO / ".tmp/s011-full-redelivery/data" / ROOT.name,
            symbol="159326.SZ",
            asset_type="etf",
            start=START,
            end=END,
            dataflows=context.data,
        )
        assert len(data.evaluation_sessions) == 403
        artifacts, summaries, links, records = [], [], [], []

        def save(name, value):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "selfcheck_evidence"))

        def evaluate(item, costs, relation=None):
            request = EvaluationRequest(
                repository_root=REPO,
                experiment_id=ROOT.name,
                strategy=item,
                runtime_binding={
                    "candidate_id": item.reference_id,
                    "source_files": list(item.payload["runtime"]["source_files"]),
                    "implementation_sha256": item.payload["runtime"]["source_sha256"],
                },
                symbol="159326.SZ",
                asset_type="etf",
                windows=(EvaluationWindow("full", START, END),),
                data_cutoff=END,
                initial_cash=1_000_000,
                costs=costs,
                execution_data=data,
                benchmark=EvaluationBenchmark.from_dict(INPUTS["benchmark"]),
                workers=1,
                frequency_window_days=60,
                dependencies=DEPS,
                lineage=None if relation is None else EvaluationLineage(relation),
            )
            result = context.evaluation.evaluate(request)
            save(
                f"assessment/{item.candidate_id}.json",
                [e.to_dict() for e in build_assessment_evidence(request, result)],
            )
            records.append(context.trace.evaluations[-1].to_dict())
            save(f"records/{item.candidate_id}.json", records[-1])
            print(json.dumps({"experiment": ROOT.name, "completed": len(records), "candidate": item.reference_id}), flush=True)
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
                b = run.buyhold.metrics
                cagr = run.observation.net_cagr
                bcagr = (1 + b["return"]) ** (252 / len(account)) - 1
                frequency = 60 * metrics["closed_trades"] / len(account)
                targets = {
                    "return_multiple": cagr >= 1.5 * bcagr,
                    "positive_if_nonpositive": bcagr > 0 or (cagr > 0 and cagr > bcagr),
                    "strict_drawdown": abs(metrics["max_drawdown"]) < abs(b["max_drawdown"]),
                    "frequency": 4 <= frequency <= 6,
                }
                summaries.append(
                    dict(
                        candidate_id=item.reference_id,
                        scenario=run.scenario_id,
                        metrics=metrics,
                        cagr=cagr,
                        benchmark_cagr=bcagr,
                        benchmark_metrics=b,
                        frequency=frequency,
                        targets=targets,
                        all_targets_met=all(targets.values()),
                        evaluation_id=run.identity.evaluation_id,
                        content_sha256=run.identity.content_sha256,
                    )
                )
            return result

        if INPUTS["role"] == "center":
            for spec in INPUTS["centers"]:
                parent = load_candidate(repository, CandidateKey("S011", spec["candidate_id"]))
                evaluate(parent, (EvaluationCost("standard", 0.001, "FORMAL"),
                                  EvaluationCost("fee_20bp", 0.002, "STRESS")))
        else:
            for spec in INPUTS["neighbors"]:
                parent = load_candidate(repository, CandidateKey("S011", spec["parent_candidate_id"]))
                proof = REPO / spec["parent_record_path"]
                item = child(spec, parent)
                relation = CandidateDerivation(
                    CandidateKey("S011", spec["parent_candidate_id"]),
                    spec["parent_content_sha256"],
                    CandidateKey("S011", item.candidate_id),
                    spec["content_sha256"],
                    CandidateDerivationKind.PARAMETERS,
                    {
                        k: {"before": parent.payload["parameters"][k], "after": v}
                        for k, v in spec["parameters"].items()
                        if v != parent.payload["parameters"][k]
                    },
                    spec["perturbation_protocol_sha256"],
                    CandidateEvidence(
                        proof.relative_to(REPO).as_posix(), sha256(proof.read_bytes()).hexdigest()
                    ),
                )
                registered = load_candidate(repository, CandidateKey("S011", item.candidate_id))
                assert StrategyRuntime().identify(registered, dependencies=DEPS).content_sha256 == spec["content_sha256"]
                evaluate(registered, (EvaluationCost("standard", 0.001, "FORMAL"),), relation)
                links.append(
                    dict(
                        slot=spec["slot"],
                        previous_candidate_id=spec["previous_candidate_id"],
                        candidate_id=item.candidate_id,
                        derivation=relation.to_dict(),
                    )
                )
        save("summaries.json", summaries)
        save("derivations.json", links)
        save("evaluation_records.json", records)
        save(
            "process.json",
            dict(
                pid=os.getpid(), started=started, finished=time.time(), workers=1, native_threads=1
            ),
        )
        return ExperimentResult(
            ExperimentOutcome.PASS,
            {"completed_accounts": len(summaries), "candidate_unchanged": True},
            {
                "development_only": True,
                "economic_pass_count": sum(x["all_targets_met"] for x in summaries),
            },
            tuple(artifacts),
        )
