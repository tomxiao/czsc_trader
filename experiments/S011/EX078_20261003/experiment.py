"""Inspect the user-selected candidate through the formal public TDR entry."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from dataflows import Dataset
from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentStage, ExperimentProtocol, ExperimentDependency, ExperimentCapabilities,
    ExperimentResult, ExperimentOutcome, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus,
)
from strategy_runtime import StrategyRuntime, ImplementationDependency
from strategy_manager import (
    CandidateKey, CandidateEvidence, DecisionReference, InspectionProtocol,
    InspectionCoordinate, InspectionStatus,
)
from czsc_trader.application import (
    RepositoryContext, load_candidate, inspect_candidate, CandidateInspectionRequest,
    InspectionReplay, EvaluationEvidenceReference,
)
from czsc_trader.research_tools import EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark
from czsc_trader.research_tools.delivery import ExperimentEvidenceRef, ExperimentEvidenceUse
from czsc_trader.backtesting.execution_data import prepare_backtest_execution_data

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))
START, END = date(2025, 2, 6), date(2026, 9, 28)
DEPS = tuple(ImplementationDependency(**x) for x in INPUTS["dependencies"])


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2, experiment_id=ROOT.name, strategy_id="S011",
            mode=ExperimentMode.FORMAL, data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=date(2026, 9, 30), random_seed=20261003,
            subjects=("159326.SZ",),
            research_question="Can selected C0618 be reproduced and packaged without execution changes?",
            hypothesis="Candidate and prospective v1 retain source, signals and economic ledger semantics.",
            falsification_conditions=("Identity or reproduction differs", "Any required check fails or is incomplete"),
            allowed_datasets=tuple(x.value for x in (
                Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY,
                Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, Dataset.GLOBAL_INDEX_DAILY,
                Dataset.TRADING_CALENDAR,
            )),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(
                ExperimentStage.CANDIDATE,
                ("User selected C0618; immutable stage-four baseline",),
                ("Pinned assessment and EX58 account evidence through inspect_candidate",),
                ("Technical deliverability and consistency; no search or economic reselection",),
                ("Eight checks and exact window/scenario coverage",),
                ("Formal candidate and prospective release replay; absolute tolerance 1e-7",),
            ),
        )

    def synthetic_precheck(self):
        candidate = load_candidate(RepositoryContext.discover(REPO), CandidateKey("S011", "C0618"))
        assert StrategyRuntime().identify(candidate, dependencies=DEPS).content_sha256 == INPUTS["content_sha256"]
        assert sha256((REPO / INPUTS["assessment_receipt"]).read_bytes()).hexdigest() == INPUTS["assessment_receipt_sha256"]
        record = INPUTS["baseline_record"]
        CandidateEvidence(record["result_artifact"]["path"], record["result_artifact"]["sha256"]).resolve(REPO / INPUTS["baseline_workspace"])
        StrategyRuntime().describe(candidate)
        DecisionReference.from_dict(INPUTS["selection"])
        return ExperimentPrecheckResult(
            (ExperimentPreflightCheck("PINNED_SELECTION", ExperimentPreflightStatus.PASS, "Candidate, selection and baseline files verified"),),
            ExperimentResult(ExperimentOutcome.PASS, {"candidate": "S011-C0618"}, {}),
        )

    def execute(self, context):
        repository = RepositoryContext.discover(REPO)
        candidate = load_candidate(repository, CandidateKey("S011", "C0618"))
        data = prepare_backtest_execution_data(
            srt_data_root=REPO / ".tmp/s011-stage5/data" / ROOT.name,
            symbol="159326.SZ", asset_type="etf", start=START, end=END, dataflows=context.data,
        )
        assert len(data.evaluation_sessions) == 403
        request = EvaluationRequest(
            repository_root=REPO, experiment_id=ROOT.name, strategy=candidate,
            runtime_binding={"candidate_id": candidate.reference_id,
                             "source_files": list(candidate.payload["runtime"]["source_files"]),
                             "implementation_sha256": candidate.payload["runtime"]["source_sha256"]},
            symbol="159326.SZ", asset_type="etf", windows=(EvaluationWindow("full", START, END),),
            data_cutoff=END, initial_cash=1_000_000,
            costs=(EvaluationCost("standard", 0.001, "FORMAL"), EvaluationCost("fee_20bp", 0.002, "STRESS")),
            execution_data=data, benchmark=EvaluationBenchmark.from_dict(INPUTS["benchmark"]),
            workers=2, frequency_window_days=60, dependencies=DEPS,
        )
        record = INPUTS["baseline_record"]
        reference = EvaluationEvidenceReference(
            ExperimentEvidenceRef(record["experiment_id"], INPUTS["baseline_workspace"], INPUTS["baseline_receipt_sha256"], ExperimentEvidenceUse.CURRENT_EVALUATION),
            record["attempt_id"], tuple(record["evaluation_ids"]),
            CandidateEvidence(record["result_artifact"]["path"], record["result_artifact"]["sha256"]),
        )
        report = inspect_candidate(repository, CandidateInspectionRequest(
            candidate=CandidateKey("S011", "C0618"), selection=DecisionReference.from_dict(INPUTS["selection"]),
            protocol=InspectionProtocol((InspectionCoordinate("full", "standard"), InspectionCoordinate("full", "fee_20bp")), INPUTS["tolerance"]),
            execution=context, replays=(InspectionReplay(reference, request),),
            version=INPUTS["version"], parent_version=INPUTS["parent_version"],
            change_summary="用户选择现有C0618，按现行契约检验并拟冻结首版；源码、参数及交易规则不变。",
            selection_data_cutoff=INPUTS["selection_data_cutoff"], forward_start=INPUTS["forward_start"],
            remaining_risks=tuple(INPUTS["remaining_risks"]),
        ))
        context.workspace.path("inspection_report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        artifact = context.workspace.register_artifact("inspection_report.json", "inspection_report")
        print(json.dumps({"inspection": report.status.value, "plan": report.plan.sha256}, ensure_ascii=False), flush=True)
        return ExperimentResult(
            ExperimentOutcome.PASS if report.status is InspectionStatus.PASS else ExperimentOutcome.FAIL,
            {"inspection_status": report.status.value, "inspection_sha256": report.sha256,
             "plan_sha256": report.plan.sha256, "candidate": "S011-C0618", "freeze": "NOT_REQUESTED"},
            {}, (artifact,),
        )
