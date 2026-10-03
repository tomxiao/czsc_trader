"""Record selection, preflight, inspect once and publish the approval-ready delivery."""

from dataclasses import fields, is_dataclass
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
import traceback

from dataflows import Dataflows, DataRequest, Dataset, LocalCacheConfig
from research_experiment import (
    load_experiment,
    experiment_source_sha256,
    ExperimentResources,
    ExperimentWorkspace,
)
from strategy_manager import (
    CandidateEvidence,
    ResearchEvidenceRef,
    CandidateKey,
    ResearchDecision,
    DecisionAction,
    CandidateSelectionSubject,
    CandidateInspectionReport,
    InspectionStatus,
)
from czsc_trader.application import (
    RepositoryContext,
    record_research_decision,
    assemble_delivery,
    validate_delivery,
)
from czsc_trader.research_tools import (
    preflight_experiment,
    create_formal_experiment_context,
    execute_experiment,
)
from czsc_trader.research_tools import delivery as d
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def file_ref(path):
    return CandidateEvidence(
        path.relative_to(REPO).as_posix(), sha256(path.read_bytes()).hexdigest()
    )


def references(value):
    if isinstance(value, ResearchEvidenceRef):
        yield value
    elif is_dataclass(value):
        for field in fields(value):
            yield from references(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from references(item)


class Deliverable(d.ResearchDeliverable):
    def __init__(self, definition, content):
        self._definition, self.content = definition, content

    @property
    def definition(self):
        return self._definition

    def build(self):
        return self.content


def publish(context, inputs, result):
    report = CandidateInspectionReport.from_dict(read(ROOT / "artifacts/inspection_report.json"))
    selection = ResearchDecision.from_dict(read(report.selection.evidence.resolve(context.root)))
    attached = {}
    for ref in (report.reference, selection.confirmation_source, *references(report)):
        path = ref.resolve(context.root)
        attached[ref.sha256] = d.EvidenceFile(
            path.relative_to(REPO).as_posix(),
            d.EvidenceRef(f"attachments/{ref.sha256}", ref.sha256, "application/octet-stream"),
        )
    assessment = d.DeliveryReceipt.from_dict(read(REPO / inputs["assessment_receipt"])).reference
    current = d.ExperimentEvidenceRef(
        ROOT.name,
        (ROOT / "artifacts").relative_to(REPO).as_posix(),
        result.receipt.sha256,
        d.ExperimentEvidenceUse.CURRENT_EVALUATION,
    )
    definition = d.DeliveryDefinition(
        d.ExperimentOwner("S011", ROOT.name),
        d.DeliveryStage.INSPECTION,
        1,
        predecessors=(assessment,),
        experiments=(current,),
    )
    passed = report.status is InspectionStatus.PASS
    pending = (
        (f"是否批准按计划{report.plan.sha256}将当前C0618冻结为S011-v1？",)
        if passed
        else ("技术检验存在失败或未完成项，须处理后重新检验。",)
    )
    payload = d.CandidateInspectionDelivery(
        assessment,
        report,
        attached[report.reference.sha256].reference,
        (),
        None,
        pending,
    )
    value = d.DeliveryContent(
        payload=payload,
        status=d.DeliveryStatus.COMPLETE if passed else d.DeliveryStatus.BLOCKED,
        facts=(),
        explanations=(
            d.Explanation(
                d.ExplanationKind.RESEARCH_JUDGMENT,
                "本交付完成冻结前技术检验并呈现精确计划；用户已选择C0618，尚未批准该计划冻结。选择数据截止日2026-09-30，拟前瞻起点2026-10-08。前瞻起点仅为计划边界，不代表部署、实盘启用或资格晋级。",
            ),
        ),
        reproduction=d.ReproductionSpec(
            "依据本实验inputs.json的原评价引用及experiment.py通过公开inspect_candidate执行技术一致性检验。报告与计划、来源及复算证据均附于交付。",
            (),
            "既有DFLS授权数据及缓存；原账户窗口2025-02-06至2026-09-28，共403交易日。",
            "标准及20bp成本压力两场景；候选内容/数据/协议身份一致；信号与完整经济账本绝对容差1e-7、相对容差0。",
        ),
        incomplete_items=() if passed else ("技术检验未通过，不能申请冻结。",),
        attachments=tuple(attached.values()),
    )
    receipt = assemble_delivery(context, Deliverable(definition, value))
    print("DELIVERY_ASSEMBLED", flush=True)
    checked = validate_delivery(context, receipt.reference)
    write(ROOT / "delivery_validation.json", checked.to_dict())
    if checked.status is not d.ValidationStatus.PASS:
        raise RuntimeError(str(checked.issues))
    (ROOT / "04_conclusion.md").write_text(
        f"# 阶段五技术检验\n\n检验状态：{report.status.value}。交付验证：PASS。\n\n"
        f"候选S011-C0618；拟冻结S011-v1；计划哈希`{report.plan.sha256}`。\n\n"
        "[检验报告](deliveries/INSPECTION/1/report.md)。尚未批准冻结，未生成冻结版本或部署。\n\n"
        "执行回执与本修订已固定；阶段五实验等待冻结决定，整体暂不封存，以便获批后追加交付修订。\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {"delivery": receipt.reference.to_dict(), "status": checked.status.value},
            ensure_ascii=False,
        ),
        flush=True,
    )


def main():
    if (ROOT / "artifacts").exists():
        raise FileExistsError("Executed experiment cannot be rerun")
    context = RepositoryContext.discover(REPO)
    inputs = read(ROOT / "inputs.json")
    print("VALIDATING_SELECTION_AND_ASSESSMENT", flush=True)
    selection = record_research_decision(
        context,
        ResearchDecision(
            "S011-C0618-selection-20261003",
            "S011",
            DecisionAction.APPROVE,
            CandidateSelectionSubject(
                file_ref(REPO / inputs["assessment_receipt"]),
                CandidateKey("S011", "C0618"),
                inputs["content_sha256"],
            ),
            file_ref(ROOT / "user_selection.json"),
            "用户明确选择C0618并授权继续阶段五技术检验；精确冻结计划尚待批准。",
        ),
    )
    inputs["selection"] = selection.to_dict()
    write(ROOT / "inputs.json", inputs)
    names = (
        "experiment.py",
        "run_experiment.py",
        "inputs.json",
        "user_selection.json",
        "01_goal.md",
        "02_design.md",
    )
    write(
        ROOT / "experiment_binding.json",
        {
            "schema_version": 3,
            "module": "experiment",
            "qualname": "Experiment",
            "source_files": list(names),
            "source_sha256": experiment_source_sha256(ROOT, names),
            "dependencies": inputs["dependencies"],
        },
    )
    loaded = load_experiment(ROOT)
    resources = ExperimentResources(2, 20261003, 1)
    cache = LocalCacheConfig(
        REPO / ".tmp/s011-regeneration/cache", "S011-20260928-regeneration-v1", timedelta(days=1)
    )
    flows = Dataflows(env_file=REPO / ".env", cache=cache)
    requests = tuple(
        DataRequest(d, s, start, "2026-09-28", "2026-09-28", freq)
        for d, s, start, freq in (
            (Dataset.ETF_OHLCV, "159326.SZ", "2024-12-26", "daily"),
            (Dataset.ETF_OHLCV, "159326.SZ", "2024-12-26", "30m"),
            (Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ", "2024-12-26", "daily"),
            (Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, "000300.SH", "2024-12-26", "daily"),
            (Dataset.GLOBAL_INDEX_DAILY, "SPX", "2024-12-16", "daily"),
            (Dataset.TRADING_CALENDAR, "SSE", "2025-02-06", "daily"),
        )
    )
    print("PREFLIGHT", flush=True)
    preflight = preflight_experiment(
        loaded, resources=resources, dataflows=flows, data_requests=requests
    )
    write(ROOT / "preflight.json", preflight.to_dict())
    preflight.require_pass()
    workspace = ExperimentWorkspace(REPO / ".tmp/s011-stage5/workspaces" / ROOT.name, REPO)
    execution = create_formal_experiment_context(
        loaded.definition,
        repository_root=REPO,
        resources=resources,
        workspace=workspace,
        cache=cache,
    )
    print("FORMAL_INSPECTION", flush=True)
    try:
        result = execute_experiment(loaded, execution)
    except Exception:
        workspace.path("technical_failure.txt").write_text(
            traceback.format_exc(), encoding="utf-8", newline="\n"
        )
        shutil.copytree(workspace.root, ROOT / "artifacts")
        raise
    shutil.copytree(workspace.root, ROOT / "artifacts")
    (ROOT / "03_execution.md").write_text(
        f"# 执行\n\n正式回执`{result.receipt.sha256}`；结果{result.outcome.value}。标准和压力场景均经TDR检验入口；无搜索或额外候选登记。\n",
        encoding="utf-8",
        newline="\n",
    )
    print("PUBLISHING_INSPECTION", flush=True)
    publish(context, inputs, result)


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
