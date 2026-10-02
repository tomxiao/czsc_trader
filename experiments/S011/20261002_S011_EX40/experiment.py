"""One fixed candidate, one confirmed development window and explicit benchmark."""

from datetime import date
from hashlib import sha256
from pathlib import Path
import json

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
from strategy_runtime import StrategyRuntime, ImplementationDependency
from strategy_manager import CandidateKey
from czsc_trader.application import RepositoryContext, load_candidate
from czsc_trader.research_tools import (
    EvaluationRequest,
    EvaluationWindow,
    EvaluationCost,
    EvaluationBenchmark,
    build_assessment_evidence,
)
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data
from czsc_trader.backtesting.metrics import calculate_metrics

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
START, END = date.fromisoformat(INPUTS["start"]), date.fromisoformat(INPUTS["cutoff"])
DEPS = tuple(ImplementationDependency(**x) for x in INPUTS["dependencies"])
BENCHMARK = EvaluationBenchmark.from_dict(INPUTS["benchmark"])


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
            random_seed=40,
            subjects=("159326.SZ",),
            research_question="Does fixed C0621 meet the confirmed full-development targets under the current platform contract?",
            hypothesis="The fixed candidate can produce authenticated current-content account and benchmark evidence.",
            falsification_conditions=(
                "Identity or execution semantics differ",
                "Any confirmed economic target fails",
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
                ExperimentStage.CANDIDATE,
                ("Current content requires its own evaluation evidence",),
                ("DFLS -> SRT signal -> TDR/TXE account -> explicit LimitBuyHold comparison",),
                (
                    "Evaluate one fixed candidate without parameter search or stage-five advancement",
                ),
                (
                    "Return, drawdown, closed trades, Calmar, win/loss ratio, win rate; confirmed CAGR and frequency targets",
                ),
                (
                    "One full-window standard-cost evaluation; generic chart deferred because it adds an unrequested next-open benchmark",
                ),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        for relative, digest in INPUTS["source_evidence"].items():
            assert sha256((REPO / relative).read_bytes()).hexdigest() == digest
        candidate = load_candidate(RepositoryContext.discover(REPO), CandidateKey("S011", "C0621"))
        runtime = StrategyRuntime()
        definition = runtime.describe(candidate)
        assert (
            runtime.identify(candidate, dependencies=DEPS).content_sha256
            == INPUTS["content_sha256"]
        )
        assert definition.execution.settings["instrument"]["lot_size"] == INPUTS["lot_size"]
        assert definition.execution.settings["capital"]["fee_rate"] == INPUTS["one_way_cost"]
        assert BENCHMARK.execution.lot_size == 100 and BENCHMARK.execution.premium == 0.003
        assert definition.observation.series[0].key == "score"
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "FIXED_IDENTITY",
                    ExperimentPreflightStatus.PASS,
                    "Current candidate, observation and explicit benchmark contracts match confirmed inputs",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"candidate": "S011-C0621"}, {}),
        )

    def execute(self, context):
        repository = RepositoryContext.discover(REPO)
        candidate = load_candidate(repository, CandidateKey("S011", "C0621"))
        artifacts = []

        def save(name, value):
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "evaluation_evidence"))

        data = prepare_backtest_execution_data(
            srt_data_root=REPO / ".tmp/s011-c0621-evaluation/data",
            symbol="159326.SZ",
            asset_type="etf",
            start=START,
            end=END,
            dataflows=context.data,
        )
        assert len(data.evaluation_sessions) == 403
        request = EvaluationRequest(
            repository_root=REPO,
            experiment_id=ROOT.name,
            strategy=candidate,
            runtime_binding={
                "candidate_id": candidate.reference_id,
                "source_files": list(candidate.payload["runtime"]["source_files"]),
                "implementation_sha256": candidate.payload["runtime"]["source_sha256"],
            },
            symbol="159326.SZ",
            asset_type="etf",
            windows=(EvaluationWindow("full", START, END),),
            data_cutoff=END,
            initial_cash=INPUTS["initial_cash"],
            costs=(EvaluationCost("standard", INPUTS["one_way_cost"]),),
            execution_data=data,
            benchmark=BENCHMARK,
            workers=1,
            frequency_window_days=60,
            dependencies=DEPS,
        )
        result = context.evaluation.evaluate(request)
        assert len(result.runs) == 1
        run = result.runs[0]
        save(
            "assessment_evidence.json",
            [x.to_dict() for x in build_assessment_evidence(request, result)],
        )
        metrics = calculate_metrics(run.execution, INPUTS["initial_cash"])
        baseline = run.buyhold.metrics
        n = len(run.execution.account_daily)
        cagr = run.observation.net_cagr
        baseline_cagr = (1 + baseline["return"]) ** (252 / n) - 1
        frequency = 60 * metrics["closed_trades"] / n
        targets = {
            "return_multiple": bool(cagr >= 1.5 * baseline_cagr),
            "positive_and_excess_if_benchmark_nonpositive": bool(
                baseline_cagr > 0 or (cagr > 0 and cagr > baseline_cagr)
            ),
            "strict_drawdown": bool(abs(metrics["max_drawdown"]) < abs(baseline["max_drawdown"])),
            "full_frequency": bool(4 <= frequency <= 6),
        }
        summary = {
            "candidate_id": candidate.reference_id,
            "content_sha256": INPUTS["content_sha256"],
            "start": START.isoformat(),
            "end": END.isoformat(),
            "sessions": n,
            "initial_cash": INPUTS["initial_cash"],
            "benchmark": BENCHMARK.to_dict(),
            "strategy_metrics": metrics,
            "benchmark_metrics": baseline,
            "strategy_cagr": cagr,
            "benchmark_cagr": baseline_cagr,
            "closed_trades_per_60_sessions": frequency,
            "targets": targets,
            "all_targets_met": all(targets.values()),
            "attempt_id": result.attempt_id,
            "evaluation_id": run.identity.evaluation_id,
            "result_hash": result.result_hash,
            "limitations": [
                "Previously seen development data; no independent validation or new selection evidence",
                "Neighborhood/stress diagnostics not rerun; no stage-five authorization",
                "Historical adjusted-data publication timing remains unverified; scheduled updates do not prove historical availability",
            ],
        }
        save("evaluation_summary.json", summary)
        save("evaluation_record.json", context.trace.evaluations[-1].to_dict())
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return ExperimentResult(
            ExperimentOutcome.PASS if all(targets.values()) else ExperimentOutcome.FAIL,
            summary,
            {
                "chart_status": "DEFERRED_BENCHMARK_CONTRACT_MISMATCH",
                "stage_five_authorized": False,
            },
            tuple(artifacts),
        )
