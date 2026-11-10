"""Preserve the participation mechanism handoff under delegated stage authority."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, ResearchIntentUpdate, assemble_delivery,
    create_research_context, publish_evidence, update_research_intent)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT / "research/S019"


def read(path):
    return json.loads(path.read_bytes())


def main():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    exp = d.ExperimentRef("S019", WORK.name)
    assert not (BATCH / "deliveries/PROTOTYPES/2/receipt.json").exists(), "Inspect existing publication before retry"
    materials = {}

    def material(path):
        if path not in materials:
            ext = path.suffix[1:]
            materials[path] = publish_evidence(context, d.MaterialEvidenceWrite(exp,
                f"mechanism-{len(materials):02}-{path.stem}", path.read_bytes(),
                {"py": "text/x-python", "json": "application/json", "md": "text/markdown"}[ext], ext))
        return materials[path]

    entries, components, comparisons, refs = [], [], [], {}
    for ex, name, cid, hypothesis in (
        ("EX024_20261110", "trail2p5", "C0067", "下跌后的早期恢复及季度相对走势配置，作为保留基线"),
        ("EX027_20261110", "quiet50", "C0074", "开盘参与度帮助区分恢复过程的风险，低参与减半"),
        ("EX028_20261110", "prior_volume", "C0078", "此前交易参与状态同样提供恢复质量信息"),
        ("EX029_20261110", "maximum", "C0080", "近期状态或当日新增参与任一正常即充分参与，避免共同筛选损失机会"),
    ):
        work = BATCH / "experiments" / ex
        ref = d.EvidenceRef.from_dict(read(work / f"others/{name}_account.json"))
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        head = json.loads(raw)
        definition = read(work / f"others/{name}_definition.json")
        assert definition == head["request"]["candidate_definition"]
        definition_ref = d.ExperimentDefinitionRef(material(work / f"others/{name}_definition.json"), definition["entrypoint"])
        protocol, summary, source = (material(work / "protocols/plan.md"), material(work / "others/summary.json"), material(work / "src/strategy.py"))
        m = read(work / "others/summary.json")[name]["candidate"]
        judgment = f"NAR{m['nar']:.4%}、MDD{m['drawdown']:.4%}、Calmar{m['calmar']:.4f}，频率达标，中心Calmar未达5。"
        comp = "F_" + cid
        components.append(d.ComponentEntry(comp, definition_ref, "完整目标仓位函数及参与风险配置", hypothesis,
            "30分钟决定、5日持有上限", "保留C0067及单信息完整账户", "仅使用已完成开盘柱和此前日线", "HFQ与日末账户MDD",
            "MU已见2022-01-03至2026-10-30", judgment,
            (d.ComponentTestResult("account_" + cid, ex, protocol, d.ComponentTestStatus.SUPPORTED,
                "支持作为可复核完整基线或发展结构；中心全部达标及稳健性仍待后续检验", (summary,)),)))
        entries.append(d.PrototypeEntry(cid, d.CandidateIdentityRef(CandidateKey("S019", cid), head["request"]["content_sha256"]),
            definition_ref, hypothesis, (d.PrototypeComponentUse(comp, "完整交易与风险配置", "收益和损失共同由账户检验"),),
            (d.EvaluationEvidenceRef(ref, (head["evaluation_id"],)),),
            d.PrototypeDisposition.DEVELOP if cid in {"C0078", "C0080"} else d.PrototypeDisposition.INVESTIGATE,
            judgment, ("同一已见历史的机制选择", "Calmar中心门槛未达，正式五项自检未做", "数据与执行限制继承MANDATE/2"),
            "依据用户自主授权转阶段三完善低参与风险投入", (source, summary, protocol)))
        refs[cid] = (ref, protocol, summary)
    for subject, control in (("C0074", "C0067"), ("C0078", "C0074"), ("C0080", "C0074"), ("C0080", "C0078")):
        comparisons.append(d.PrototypeComparison(subject + "_vs_" + control, subject, control,
            "参与信息及协作是否改善收益、MDD且保留交易频率？", refs[subject][1],
            (refs[subject][2], refs[control][2]), "改善与代价详见两端完整账户和EX026—EX029报告，全部中心门槛仍待满足。"))
    for path in (WORK / "src/publish_mechanisms.py", BATCH / "experiments/EX026_20261110/protocols/authorization.md",
                 BATCH / "experiments/EX026_20261110/others/diagnosis.json", BATCH / "experiments/EX026_20261110/src/diagnose.py"):
        material(path)
    report = """# S019 成交参与机制交付

新增十轮的前四轮用于阶段二，完成1轮既有账户诊断及3轮完整账户对照，共10个新策略和3个共享买持。中心全门达标0个。C0067保留为基线；C0074、C0078、C0080显示参与信息有助于减少MDD，C0080为NAR71.16%、MDD15.40%、Calmar4.62，频率达标。

开盘波幅未复现参与度的作用，前日参与也有价值；任一参与正常的组合优于共同筛选或共同折减。支持近期状态与新增参与的互补解释，2025年度反例和全部替代结果保留。上述关系仍来自反复使用的历史，因果解释和稳健性尚待检验。

依据用户明确授权“自行决定用于阶段二还是阶段三以及具体研究什么问题”，从新增第5轮转入阶段三，比较单前日参与和任一参与结构的风险强度。原目标、样本、费用及80%扰动要求保持。该自主转换在第5轮启动前已通过方案和会话说明，当前交付补全结构化成果。

[授权](../../../experiments/EX026_20261110/protocols/authorization.md) · [机制诊断](../../../experiments/EX026_20261110/report.md) · [开盘参与](../../../experiments/EX027_20261110/report.md) · [信息替代](../../../experiments/EX028_20261110/report.md) · [信息协作](../../../experiments/EX029_20261110/report.md)

恢复需要本批次本地数据和账户资产，远端同步状态尚未核验。
"""
    predecessor = d.DeliveryReference.from_dict(read(BATCH / "deliveries/MANDATE/2/receipt.json")["reference"])
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.PROTOTYPES, 2, (predecessor,)),
        d.DeliveryContent(d.PrototypePanel(tuple(entries), tuple(components), tuple(comparisons),
            "保留成交参与结构，依据用户自主授权转阶段三完善"), d.DeliveryStatus.COMPLETE, (), (),
            report=report, evidence=tuple(materials.values())))
    (WORK / "others/mechanism_delivery.json").write_bytes((json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n").encode())
    assert result.validation.status is d.ValidationStatus.PASS
    intent = read(ROOT / "research/registrations/S019/family.json")["research_intent"]
    intent.update(stage="STAGE_THREE", extension_status="IN_PROGRESS", extension_mechanism_delivery=result.receipt.reference.to_dict(),
        extension_budget={"authorized_rounds": 10, "used_rounds": 5, "remaining_rounds": 5, "completed_rounds": 4},
        next_action="承接成交参与机制，在新增第5轮及后续额度内完善仓位配置，原目标保持。")
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="用户明确授权阶段二/三自主选择；依据完整账户机制比较转入阶段三")
    print("MECHANISM_DELIVERY", result.receipt.reference.content_sha256, result.validation.status.value, flush=True)


if __name__ == "__main__":
    main()
