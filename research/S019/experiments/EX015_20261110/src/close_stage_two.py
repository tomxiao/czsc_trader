"""Close the authorized ten rounds without launching another evaluation."""
from hashlib import sha256
import json
from pathlib import Path
import sys

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    get_research_overview, publish_evidence, update_research_intent,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from strategy_runtime import equity_source_hash

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT / "research/S019"
CONCLUSION = "十轮31个新增策略账户全部完成，0个通过全部中心硬门。建议发展C0035，阶段三等待用户批准。"
CONTROLS = {
    "C0010": "C0007", "C0011": "C0007", "C0012": "C0011", "C0013": "C0012",
    "C0014": "C0012", "C0015": "C0013", "C0016": "C0012", "C0017": "C0016",
    "C0018": "C0012", **{f"C{i:04}": "C0017" for i in range(19, 30)},
    "C0030": "C0028", **{f"C{i:04}": "C0017" for i in range(31, 35)},
    "C0035": "C0022", "C0036": "C0035", "C0037": "C0035",
    **{f"C{i:04}": "C0035" for i in range(38, 41)},
}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def rows():
    old = BATCH / "experiments/EX005_20261110"
    result = [(old, "common", "C0007", read(old / "others/summary.json")["common"]["runs"]["candidate"])]
    for n in range(6, 16):
        work = BATCH / f"experiments/EX{n:03}_20261110"
        summary = read(work / "others/summary.json")
        assert read(work / "protocols/config.json")["round"] == n - 5
        for name, row in summary.items():
            assert not row["candidate"]["eligible"]
            result.append((work, name, row["id"], row["candidate"]))
    assert len(result) == 32 and len({r[2] for r in result}) == 32
    return result


def prepare():
    budget = read(WORK / "others/budget.json")
    assert (budget["used_rounds"], budget["remaining_rounds"], budget["candidate_accounts"],
            budget["benchmark_accounts"], budget["eligible_prototypes"]) == (10, 0, 31, 10, 0)
    template = (BATCH / "materials/ten_rounds_summary.md").read_text(encoding="utf-8")
    template = template.split("<!-- GENERATED_RESULTS -->")[0].rstrip()
    lines = [template, "", "<!-- GENERATED_RESULTS -->", "", "## 附录：全部完整账户", "",
             "表内顺序为实验顺序；当前达标集合为空。C0007为本轮复用的旧基线，其余31个为新增策略账户。",
             "", "|实验|原型|NAR|日末回撤|Calmar|60日闭合中位数|至少3笔覆盖率|未通过中心门槛|",
             "|---|---|---:|---:|---:|---:|---:|---|"]
    labels = {"nar": "NAR", "calmar": "Calmar", "absolute_dd": "绝对回撤",
              "relative_dd": "相对回撤", "frequency_median": "频率中位数", "frequency_coverage": "频率覆盖"}
    for work, _, cid, m in rows():
        failed = "、".join(labels[k] for k, v in m.get("gates", {}).items() if not v) or "NAR、Calmar、绝对回撤"
        lines.append(f"|[{work.name[:5]}](../experiments/{work.name}/report.md)|{cid}|{m['nar']:.4%}|"
                     f"{m['drawdown']:.4%}|{m['calmar']:.4f}|{m['frequency_median']:g}|"
                     f"{m['frequency_coverage']:.4%}|{failed}|")
    lines += ["", "## 附录：正式证据与可恢复性", "",
              "每个实验的 report_ref.json 指向不可变报告，报告绑定源代码、精确配置、账户证据、运行统计及必要分析。"
              "原型面板保留32个账户身份（31个新增及1个旧基线）、完整定义、源码和31项显式账户比较。"
              "组件采用完整函数作为联合检验单位，具体条件的增量由比较解释，避免将整体效果归因给单一组件。",
              "", "[额度核对](../experiments/EX015_20261110/others/budget.json) · "
              "[C0035及日级退出逐决定复核](../experiments/EX015_20261110/others/semantic_audit.json) · "
              "[基础确认与相对强弱逐决定复核](../experiments/EX013_20261110/others/semantic_audit.json)", "",
              "数据资产和正式证据由本批次DFLS/TDR本地资产空间管理；远端资产同步状态尚未核验。"
              "源码、材料及报告保存在研究分支；恢复研究同时需要相应本地数据与证据资产。", ""]
    (BATCH / "materials/ten_rounds_summary.md").write_bytes("\n".join(lines).encode())
    print("PREPARED", len(rows()), flush=True)


def publish():
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    experiment = d.ExperimentRef("S019", WORK.name)
    assert not (BATCH / "deliveries/PROTOTYPES/1/receipt.json").exists(), "Inspect existing delivery before retry"
    overview = get_research_overview(repo, batch)
    save(WORK / "others/closing_overview.json", overview.to_dict())
    materials = {}

    def material(path):
        key = path.relative_to(ROOT).as_posix()
        if key not in materials:
            ext = path.suffix[1:]
            materials[key] = publish_evidence(context, d.MaterialEvidenceWrite(
                experiment, f"closure-{len(materials):03}-{path.stem}", path.read_bytes(),
                {"json": "application/json", "md": "text/markdown", "py": "text/x-python"}[ext], ext))
        return materials[key]

    prototypes, components, comparisons, reports = [], [], [], []
    refs, protocols, summaries, narratives = {}, {}, {}, {}
    for work, name, cid, m in rows():
        definition_path = work / f"others/{name}_definition.json"
        definition = read(definition_path)
        ref = d.EvidenceRef.from_dict(read(work / f"others/{name}_account.json"))
        content = ref.resolve(ROOT).read_bytes()
        assert sha256(content).hexdigest() == ref.sha256
        head = json.loads(content)
        assert head["request"]["candidate_id"] == cid
        assert head["request"]["candidate_definition"] == definition
        assert equity_source_hash(work / "src", tuple(definition["source_files"])) == definition["source_sha256"]
        proto_definition = d.ExperimentDefinitionRef(material(definition_path), definition["entrypoint"])
        protocol = material(work / ("protocols/prototypes.md" if cid == "C0007" else "protocols/plan.md"))
        source = tuple(material(work / "src" / path) for path in definition["source_files"])
        summary = material(work / "others/summary.json")
        publication = read(work / "others/publication.json")
        assert publication["validation"]["status"] == "PASS"
        report = d.EvidenceRef.from_dict(publication["report"])
        if report not in reports:
            reports.append(report)
        interpretation = read(work / "others/interpretation.json") if cid != "C0007" else {
            "conclusion": "旧行业筛选短持有基线NAR33.08%、回撤43.26%、Calmar0.76，中心门槛未通过。",
            "findings": "检验行业共同下跌后短期恢复是否可兑现；保留为持有期限比较的原账户。"}
        judgment = (f"NAR{m['nar']:.4%}，回撤{m['drawdown']:.4%}，Calmar{m['calmar']:.4f}。"
                    + interpretation["conclusion"])
        chosen = cid == "C0035"
        retain = cid in {"C0007", "C0017", "C0022", "C0034", "C0036"}
        disposition = (d.PrototypeDisposition.DEVELOP if chosen else d.PrototypeDisposition.INVESTIGATE
                       if retain else d.PrototypeDisposition.STOP)
        component_id = f"F_{cid}"
        evidence = (ref, summary, report, *source)
        components.append(d.ComponentEntry(
            component_id, proto_definition, "完整目标仓位函数的联合检验", name,
            "30分钟决定；精确持有和辅助观察期限见绑定定义", CONTROLS.get(cid, "旧EX005每日短持有基线"),
            "仅使用决策时已完成柱；可得性、账户反馈与实际成交分别核验", "HFQ；日末账户权益回撤",
            "MU只做多、无杠杆；2022-01-03至2026-10-30已见历史", judgment,
            (d.ComponentTestResult(f"account_{cid}", work.name, protocol, d.ComponentTestStatus.INEFFECTIVE,
                                   "完整账户未通过全部中心硬门；支持及反例详见相应对照，机制认识继续保留。",
                                   (ref, summary, report)),)))
        prototypes.append(d.PrototypeEntry(
            cid, d.CandidateIdentityRef(CandidateKey("S019", cid), head["request"]["content_sha256"]),
            proto_definition, interpretation["findings"],
            (d.PrototypeComponentUse(component_id, "联合入场、仓位、持有及退出", "通过完整账户观察可兑现净收益"),),
            (d.EvaluationEvidenceRef(ref, (head["evaluation_id"],)),), disposition, judgment,
            ("全部窗口已见并反复用于结构选择", "中心硬门未全部通过；正式五项自检尚未执行",
             "数据可得性和历史停牌覆盖沿用EX003披露的研究假设",
             "固定5日结果对持有期限敏感；C0035末段回撤截至窗口末端仍未修复"),
            "等待阶段三批准后完善回撤控制及检验期限敏感性" if chosen else
            "保留现有账户作为后续对照" if retain else "停止当前结构的继续扩展，保留负面证据",
            evidence))
        refs[cid], protocols[cid], summaries[cid], narratives[cid] = ref, protocol, summary, interpretation
    for cid, control in CONTROLS.items():
        comparisons.append(d.PrototypeComparison(
            f"{cid}_vs_{control}", cid, control, "相同账户条件下，当前协议所改变的机制是否改善完整账户？",
            protocols[cid], tuple(dict.fromkeys((refs[cid], refs[control], summaries[cid], summaries[control]))),
            narratives[cid]["conclusion"] + " 该判断覆盖本实验声明的结构对照；具体数值与改变项见协议和两端定义。"))
    for path in (WORK / "src/close_stage_two.py", WORK / "others/budget.json", WORK / "others/semantic_audit.json",
                 WORK / "others/closing_overview.json", BATCH / "materials/ten_rounds_summary.md"):
        material(path)
    predecessor = d.DeliveryReference.from_dict(read(BATCH / "deliveries/MANDATE/2/receipt.json")["reference"])
    report_text = (BATCH / "materials/ten_rounds_summary.md").read_text(encoding="utf-8")
    report_text = report_text.replace("../experiments/", "../../../experiments/").replace("../deliveries/MANDATE/", "../../MANDATE/")
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.PROTOTYPES, 1, (predecessor,)),
        d.DeliveryContent(d.PrototypePanel(tuple(prototypes), tuple(components), tuple(comparisons), CONCLUSION),
            d.DeliveryStatus.COMPLETE, (), (), report=report_text, evidence=tuple([*reports, *materials.values()])))
    save(WORK / "others/stage_publication.json", result.to_dict())
    finalize()


def finalize():
    """Finish intent bookkeeping from an already saved, successful assembly."""
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef("S019")
    result = d.DeliveryAssemblyResult.from_dict(read(WORK / "others/stage_publication.json"))
    assert result.validation.status is d.ValidationStatus.PASS, result.validation
    reference = result.receipt.reference
    assert read(BATCH / "deliveries/PROTOTYPES/1/receipt.json")["reference"] == reference.to_dict()
    intent = read(ROOT / "research/registrations/S019/family.json")["research_intent"]
    intent.update(stage="STAGE_TWO", stage_two_status="COMPLETE", stage_three_approval="PENDING",
                  stage_two_delivery=reference.to_dict(),
                  latest_experiment_report=read(WORK / "others/publication.json")["report"],
                  experiment_budget=read(WORK / "others/budget.json"),
                  next_action="建议以C0035为主原型进入阶段三，处理Calmar缺口与期限敏感性；等待用户批准及新增额度。")
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
                           reason="完成获批十轮阶段二研究及正式原型交付，保留未达标结论并等待下一阶段批准")
    print("DELIVERY", reference.content_sha256, result.validation.status.value, flush=True)


if __name__ == "__main__":
    {"prepare": prepare, "publish": publish, "finalize": finalize}[sys.argv[1]]()
