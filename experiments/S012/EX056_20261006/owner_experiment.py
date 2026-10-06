"""Source-bound existing-evidence aggregation; zero new accounts or market reads."""
from datetime import date
from pathlib import Path

from research_experiment import (
    ResearchExperiment, ExperimentDefinition, ExperimentMode, ExperimentDataScope,
    ExperimentCapabilities, ExperimentCapability, ExperimentProtocol, ExperimentStage,
    ExperimentResult, ExperimentOutcome, ExperimentPrecheckResult,
    ExperimentPreflightCheck, ExperimentPreflightStatus,
)
from .owner_contract import (
    read, require, validate_plan, digest, verify_references, authenticate_predecessors,
)


def write(path, value):
    import json
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def frozen_plan(exp):
    identity = read(exp / "owner_identity.json")
    require(digest(exp / "plan.json") == identity["plan_sha256"], "frozen plan SHA changed")
    plan = validate_plan(read(exp / "plan.json"), identity["owner_eid"])
    for item in plan["frozen_files"]:
        require(digest(exp / "frozen" / item["target_name"]) == item["sha256"], "frozen evidence changed")
    return identity, plan


class Experiment(ResearchExperiment):
    @property
    def definition(self):
        identity, plan = frozen_plan(Path(__file__).resolve().parent)
        return ExperimentDefinition(
            schema_version=2, experiment_id=identity["owner_eid"], strategy_id="S012", mode=ExperimentMode.FORMAL,
            research_question="经认证的现有研究结果、选择链及人工收口说明能否形成一致、可复算的阶段三交付输入？",
            hypothesis="本轮仅聚合主会话已完成并冻结的证据，不生成新账户、参数搜索或候选内容。",
            falsification_conditions=("前驱回执、源闭包、冻结文件或原三门身份有差异即拒绝聚合。",
                                     "计划未COMPLETE、有未完成事项或缺少科学收口说明即拒绝执行。"),
            development_cutoff=date(2026, 9, 30), random_seed=identity["seed"],
            allowed_datasets=tuple(plan["allowed_datasets"]), data_scope=ExperimentDataScope.DEVELOPMENT,
            subjects=("518850.SH",), dependencies=(),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            protocol=ExperimentProtocol(ExperimentStage.PROTOTYPE,
                ("原三门同时成立，净年化优先；全部窗口已观察。",),
                ("仅已有完整REX与冻结证据，经公开加载器认证。",),
                ("形成最终公共交付的聚合owner，科学收口由冻结的主会话说明承担。",),
                ("认证状态与文件身份；零新增账户、评价、搜索提案、候选。",),
                ("复制frozen证据为受管artifact，保留前驱与原始路径映射。",
                 "最终完整审计和publicdelivery在owner完成后追加artifacts，执行回执不追加执行。"),
                predecessor_experiment_ids=tuple(plan["predecessor_receipts"])) )

    def synthetic_precheck(self):
        frozen_plan(Path(__file__).resolve().parent)
        return ExperimentPrecheckResult((ExperimentPreflightCheck("OWNER_PLAN_AND_FROZEN_FILES",
            ExperimentPreflightStatus.PASS, "local frozen structure matches; no real predecessor claim made"),),
            ExperimentResult(ExperimentOutcome.INCONCLUSIVE, {"synthetic_only": True, "new_accounts": 0}, {}))

    def execute(self, context):
        root, exp = Path.cwd().resolve(), Path(__file__).resolve().parent
        identity, plan = frozen_plan(exp)
        require(exp == root / "experiments/S012" / identity["owner_eid"], "actual owner must be root-allocated S012 path")
        context.record_capability(ExperimentCapability.READ_REAL_RETURNS)
        verify_references(root, plan)
        inputs, predecessors = authenticate_predecessors(root, plan)
        require({item.experiment_id: item.receipt_sha256 for item in inputs}
                == {eid: item.receipt_sha256 for eid, item in context.predecessors.items()},
                "actual authenticated predecessors differ from public context")
        artifacts, links = [], []
        for item in plan["frozen_files"]:
            name = "frozen/" + item["target_name"]
            target = context.workspace.path(name)
            require(not target.exists(), "owner workspace already contains frozen artifact")
            with target.open("xb") as stream:
                stream.write((exp / "frozen" / item["target_name"]).read_bytes())
            require(digest(target) == item["sha256"], "managed frozen copy differs")
            artifacts.append(context.workspace.register_artifact(name, "frozen_existing_evidence"))
            links.append({"source_path": item["path"], "bound_source_path": name,
                          "managed_artifact_path": name, "sha256": item["sha256"]})
        verification = {"schema_version": 1, "status": "PASS", "experiment_id": identity["owner_eid"],
            "role": "EXISTING_EVIDENCE_AGGREGATION_ONLY", "plan_sha256": identity["plan_sha256"],
            "predecessors": predecessors, "links": links, "source_evidence": plan["source_evidence"],
            "three_goals": plan["three_goals"], "priority": plan["priority"], "all_window_seen": True,
            "root_research_decision": plan["research_decision"], "new_accounts": 0,
            "new_evaluations": 0, "new_search_proposals": 0, "new_candidate_content": 0}
        for name, payload, kind in (("trials.json", [], "zero_new_evaluation_trials"),
                                    ("verification.json", verification, "existing_evidence_authentication")):
            target = context.workspace.path(name)
            require(not target.exists(), "owner workspace is not fresh")
            write(target, payload)
            artifacts.append(context.workspace.register_artifact(name, kind))
        return ExperimentResult(ExperimentOutcome.PASS,
            {"aggregation_complete": True, "new_accounts": 0, "new_evaluations": 0,
             "new_search_proposals": 0, "new_candidate_content": 0, "scientific_plan_status": plan["status"]},
            {"role": "AGGREGATION_NOT_NEW_ECONOMIC_EVIDENCE", "root_decision_is_frozen_input": True},
            artifacts=tuple(artifacts))
