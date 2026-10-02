from datetime import date
from pathlib import Path
from hashlib import sha256
import json
from research_experiment import (
    ResearchExperiment,
    ExperimentDefinition,
    ExperimentMode,
    ExperimentDataScope,
    ExperimentStage,
    ExperimentProtocol,
    ExperimentDependency,
    ExperimentCapabilities,
    ExperimentPrecheckResult,
    ExperimentPreflightCheck,
    ExperimentPreflightStatus,
    ExperimentResult,
    ExperimentOutcome,
)
from strategy_manager import CandidateKey
from czsc_trader.application import RepositoryContext, load_candidate
from strategy_runtime import StrategyRuntime, ImplementationDependency
import czsc_trader.research_tools as d

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
INPUTS = json.loads((ROOT / "inputs.json").read_text(encoding="utf-8"))


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        return ExperimentDefinition(
            schema_version=2,
            experiment_id=ROOT.name,
            strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            data_scope=ExperimentDataScope.DEVELOPMENT,
            development_cutoff=date(2026, 9, 28),
            random_seed=20261002,
            subjects=("159326.SZ",),
            research_question="Can all 36 centers be handed off with current-content evaluation evidence?",
            hypothesis="All fixed centers have valid standard-cost evidence and preserve original targets.",
            falsification_conditions=("Candidate content differs or an original target fails",),
            allowed_datasets=("etf.ohlcv", "etf.unadjusted_daily", "calendar.trading_sessions"),
            dependencies=tuple(ExperimentDependency(**x) for x in INPUTS["dependencies"]),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(
                ExperimentStage.CANDIDATE,
                ("Known development sample",),
                ("Current authenticated center results and historical research records",),
                ("No new parameter search",),
                ("Complete current CandidateSet handoff",),
                ("Aggregate validated predecessors, preserve original history",),
                tuple(INPUTS["predecessors"]),
            ),
        )

    def synthetic_precheck(self):
        source = REPO / INPUTS["historical_delivery"]
        assert sha256(source.read_bytes()).hexdigest() == INPUTS["historical_sha256"]
        old = json.loads(source.read_text(encoding="utf-8"))["content"]["payload"]
        searches = tuple(d.SearchRecord.from_dict(x) for x in old["searches"])
        assert len(searches) == 6 and sum(len(x.trials) for x in searches) == 576
        assert all(t.candidate is None and not t.evaluations for x in searches for t in x.trials)
        return ExperimentPrecheckResult(
            (
                ExperimentPreflightCheck(
                    "SEARCH_HISTORY",
                    ExperimentPreflightStatus.PASS,
                    "573 historical complete proposals and 3 failed proposals retained",
                ),
            ),
            ExperimentResult(ExperimentOutcome.PASS, {"candidate_count": 36}, {}),
        )

    def execute(self, context):
        old = json.loads((REPO / INPUTS["historical_delivery"]).read_text(encoding="utf-8"))[
            "content"
        ]["payload"]
        entries = []
        mapping = []
        summary = []
        repo = RepositoryContext.discover(REPO)
        deps = tuple(ImplementationDependency(**x) for x in INPUTS["dependencies"])
        for ex in INPUTS["predecessors"]:
            source = ROOT.parent / ex / "artifacts"
            records = json.loads((source / "evaluation_records.json").read_text())
            rows = json.loads((source / "summaries.json").read_text())
            for record in records:
                key = CandidateKey("S011", record["candidate_id"].removeprefix("S011-"))
                current = load_candidate(repo, key)
                assert (
                    StrategyRuntime().identify(current, dependencies=deps).content_sha256
                    == record["content_sha256"]
                )
                standard = next(
                    x
                    for x in rows
                    if x["candidate_id"] == record["candidate_id"] and x["scenario"] == "standard"
                )
                assert standard["all_targets_met"]
                identity = d.CandidateIdentityRef(key, record["content_sha256"])
                entries.append(
                    d.CandidateEntry(
                        identity,
                        "市场及尾盘压力排序结合严格前序SPX确认形成短期反转持仓；按退出阈值或最长持有期限退出。",
                        "固定参数当前复算满足原收益、回撤和交易频率目标；属于已见开发池证据，交接阶段四全量自检。",
                        (
                            d.EvaluationEvidenceRef(
                                ex, record["attempt_id"], (standard["evaluation_id"],)
                            ),
                        ),
                    )
                )
                mapping.append(
                    dict(
                        candidate=identity.to_dict(),
                        parameters=dict(current.payload["parameters"]),
                        experiment_id=ex,
                        attempt_id=record["attempt_id"],
                        evaluation_id=standard["evaluation_id"],
                    )
                )
                summary.append(standard)
        entries.sort(key=lambda x: x.identity.key.candidate_id)
        assert len(entries) == 36
        payload = d.CandidateSet(
            tuple(entries),
            tuple(x.identity.key for x in entries),
            tuple(d.SearchRecord.from_dict(x) for x in old["searches"]),
            "完整交接36个当前登记中心；均已在现行契约下满足原标准成本目标。保留573条完成、3条失败历史提议及后续扩展台账，不将复算计作新搜索。阶段四必须覆盖全部36中心。",
        )
        artifacts = []
        for name, value in [
            ("candidate_set.json", payload.to_dict()),
            ("identity_mapping.json", mapping),
            ("center_summary.json", summary),
        ]:
            context.workspace.path(name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            artifacts.append(context.workspace.register_artifact(name, "stage_three_evidence"))
        return ExperimentResult(
            ExperimentOutcome.PASS,
            {"current_centers": 36, "historical_complete": 573, "historical_failed": 3},
            {"development_only": True, "new_parameter_proposals": 0},
            tuple(artifacts),
        )
