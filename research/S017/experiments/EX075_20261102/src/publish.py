"""Publish the full registered stage-three candidate handoff; no new evaluation."""
# Cache settings must precede runtime imports.
# ruff: noqa: E402
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.pycache_prefix = str(ROOT / ".tmp/s017-stage3-candidates-20261102/pycache")

from hashlib import sha256
import copy
import re

from register import WORK, SCRATCH, R, B, E, PRIOR, KEYS, read, save, digest
from dataflows import ProviderConfig
from czsc_trader.application import (
    assemble_delivery, create_research_context, get_research_overview, load_candidate,
    publish_evidence, update_research_intent, ResearchIntentUpdate, validate_experiment,
)
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources


def main():
    registrations = read(WORK / "others/registrations.json")
    assert registrations["status"] == "PASS" and set(registrations["records"]) == set(KEYS)
    analysis = read(PRIOR / "others/analysis.json")
    rows = {row["candidate_id"]: row for row in analysis["results"]}
    assert analysis["new_training_center_qualifiers"] == list(KEYS)
    overview = get_research_overview(R, B).to_dict()
    sources = {item["stage"]: d.DeliveryReference.from_dict(item["reference"]) for item in overview["deliveries"]}
    assert (sources["CANDIDATES"].revision, sources["PROTOTYPES"].revision, sources["MANDATE"].revision) == (2, 13, 7)
    prior_report = d.EvidenceRef.from_dict(read(PRIOR / "others/publication.json")["report"])
    prior_report.resolve(ROOT)
    historical = {}
    for folder in (ROOT / "research/S017/deliveries/CANDIDATES/2", ROOT / "research/S017/deliveries/PROTOTYPES/13",
                   ROOT / "research/S017/deliveries/MANDATE/7"):
        historical.update({p.relative_to(ROOT).as_posix(): digest(p) for p in folder.iterdir() if p.is_file()})
    for file in (PRIOR / "report.md", PRIOR / "others/analysis.json", PRIOR / "others/se_comparison.json"):
        historical[file.relative_to(ROOT).as_posix()] = digest(file)
    save(SCRATCH / "historical_before_publication.json", historical)
    context = create_research_context(R, B, providers=ProviderConfig(bindings={}),
                                     resources=ExecutionResources(4, 1, 17))
    evidence = {}

    def material(name, path):
        suffix = path.suffix[1:]
        ref = publish_evidence(context, d.MaterialEvidenceWrite(E, name, path.read_bytes(),
            {"md": "text/markdown", "json": "application/json", "py": "text/x-python"}[suffix], suffix))
        evidence[name] = ref
        return ref

    for name, path in (
        ("stage-three-protocol", WORK / "protocols/design.md"),
        ("exact-goal-recheck", WORK / "others/preflight.json"),
        ("candidate-registrations-and-loads", WORK / "others/registrations.json"),
        ("registration-source", WORK / "src/register.py"),
        ("candidate-delivery-source", WORK / "src/publish.py"),
        ("inherited-training-results", PRIOR / "others/analysis.json"),
        ("full-target-checks", PRIOR / "others/se_comparison.json"),
    ):
        material(name, path)
    accounts = {key: d.EvidenceRef.from_dict(rows[key]["record"]["evidence"]) for key in KEYS}
    table = []
    for key in KEYS:
        result = rows[key]["candidate"]
        table.append(f"|{key}|{result['net_calmar']:.6f}|{100*result['annualized_return']:.4f}%|{100*result['bar_max_drawdown']:.4f}%|{result['rolling_60_closed_cycle_median']}|{result['covered_windows']}/{result['frequency_windows']}|PASS|")
    report = """# EX075：自主阶段三完成，六个正式候选已产出

阶段三本次目标已达成：C0338、C0339、C0340、C0341、C0342、C0352全部通过MANDATE/7训练中心五门，已由TDR公共API登记并验证独立源码快照可加载；完整六点进入CANDIDATES/3交接。它们是同一机制的六个参数表达，不是六个独立收益发现，也不是正式排序后已选定的六个生产策略。

本轮没有新增搜索或金融账户，保留原候选键、实现/参数/执行合同、原账户所有者及旧FAIL。正式候选符合本阶段中心经济/频率和工程交接要求，参数邻域、费用压力及正式五项自检仍未完成，全部11项目标的总验收保持INDETERMINATE；COMPLETE只表示本阶段交付完成。2026价格及策略绩效继续封存，无冻结或生产动作。

## 做了哪些尝试

首先用SE公开compare_candidates复算EX074的25点完整目标检查，确认11项目标与MANDATE/7完全一致、全部原比较结果精确复现、只有六点同时通过中心五门。没有只按某个指标挑C342，也没有因为其他点在原型面板标为INVESTIGATE就遗漏。承接范围是用户本次批准推进的PROTOTYPES/13及其25点来源；不把旧窗口或其他历史机制未经核对混入该交接。

随后逐点以原定义和原源码创建强类型候选，校验六参数、源闭包、依赖、特征/状态定义、content identity及正式V4账户。登记使用EX075作为新的候选登记来源，账户仍明确来自EX072，没有克隆或重签为新账户。对每点使用load_candidate读取登记后的独立源码快照，再verify并进入公开bind_replay作用域：两份源文件可编译、相对依赖可导入、strategy:step可调用，作用域结束清理模块。没有invoke/account_step调用，因此不冒称新增金融回放、行为等价或生产执行检验通过。

## 有哪些收获

|候选|净Calmar|净年化|BAR_CLOSE最大回撤|60日闭合中位|至少3笔窗口|登记/快照加载|
|---|---:|---:|---:|---:|---:|---|
""" + "\n".join(table) + """

同窗BH净Calmar3.08504244，严格门4.62756366；相对/绝对回撤、中位≥6、至少90%完整60交易日窗≥3笔均通过。训练为2024-01-02—2025-12-31，502实际交易日；原成本、1%限价、fresh初始账户及BAR_CLOSE合同不变。

C342是较高收益的机制代表；C352提供回撤更低但收益/频率也更低的另一取舍，收益低于BH仍符合已确认Calmar目标，不额外设收益门。它们尚未经过完整标准排序。C352的六参数共同变化并改变入口人口，不能把较低回撤单独归因于MF保护。C338/339与更早控制的经济等价关系、MF轴有限增量、EX073收入与回撤同源的反证、集中性风险全部继承，不因登记恢复独立证据身份。

### 为什么本次没有继续搜索

用户已明确阶段三可据证据决定是否搜索，本次没有把“不搜索”设为硬约束。复核后已有完整六点满足中心目标，没有必须优化才能交接的缺口；剩余主要问题是这些优势对参数、成本、时间及选择偏差是否稳健。继续盲加试验不会回答这些问题，因此本轮不增加搜索预算或为提高门槛余量添加新目标。

历史EX072真实Optuna搜索为5固定锚加20六维联合提案，共25成功唯一点、25候选计算与2次共享BH；这些是历史工作，不记作本轮新增计算。原alpha域及自然比例端点保持，未发现原上界改善触发；有限25点不代表域内或域外最优。g_MF=0/1是自然端点，不以越过合法域“扩边”。原频率必要界、未覆盖联合组合和已知等价点继续披露。若正式稳健性暴露新缺口，应围绕具体问题决定后继优化，而不是预先承诺永不搜索。

## 下一步建议是什么

阶段三在现有证据下已产出完整六点候选交接，建议用户批准进入阶段四：覆盖全部六点，按MANDATE/7与原标准核验完整适用局部邻域、0.2%每侧费用压力、时间稳定性、集中性及统计不确定性，并按既定标准排序。未授权前不自动执行；参数项不适用须真实留证，不能靠未检、缺失或失败取得豁免。正式比较完成后再由用户选型，2026测试仍另行授权。

## 有什么依据

[固定方案](protocols/design.md)、[25点目标精确复算](others/preflight.json)、[六份登记与独立加载结果](others/registrations.json)、[登记源码](src/register.py)。本交付精确关联PROTOTYPES/13、MANDATE/7及旧CANDIDATES/2；六个候选均有原正式账户，登记快照保存完整定义/源码/依赖，主体及handoff名单完全一致。原型机制、完整资金路径及负证由EX074和其历史正式来源承接，旧空集及旧资格不覆盖。

技术FULL核验、登记和入口加载只能证明材料/身份及加载契约，不等于11项全部达标、独立测试通过或未来有效。研究族已见选择史继续保留；没有新外部数据、阶段四、封存测试、冻结、PTE或生产变更。本轮仅本地中文提交，不合并、tag或推送。
"""
    (WORK / "report.md").write_text(report, encoding="utf-8", newline="\n")
    report_ref = publish_evidence(context, d.ExperimentReportWrite(E, sha256(report.encode()).hexdigest(),
        d.ExperimentOutcome.COMPLETED, tuple((*evidence.values(), *accounts.values(), prior_report))))
    entries = []
    for key in KEYS:
        record = registrations["records"][key]
        loaded = load_candidate(R, CandidateKey("S017", key))
        assert loaded.content_identity.content_sha256 == record["candidate_content_sha256"]
        entries.append(d.CandidateEntry(
            d.CandidateIdentityRef(loaded.key, loaded.content_identity.content_sha256),
            "E0收复、真实成交冻结背景及已确认结构/推进保护协作的完整只多机制；同机制参数表达。",
            "训练中心五门通过，原内容身份与登记快照可加载；完整11项目标尚缺稳健性，不表示正式优选。",
            (d.EvaluationEvidenceRef(accounts[key], (record["evaluation_id"],)),)))
    history = d.SearchSummary("EX072_20261102",
        "历史Optuna4.9.0六维联合TPE：5固定锚+20模型点；本轮只精确复核并登记，新增搜索0",
        "承接EX074/PROTOTYPES13的全部25点及六个中心达标表达；旧年化门FAIL不回写",
        25, 25, "按MANDATE/7中心五门完整保留C0338/339/340/341/342/352，未按正式稳健性排序选优",
        ("训练反复选择和目标事后修订，不是独立验证", "历史25候选+2共享BH不计本轮新增计算",
         "有限域与自然端点，不称全域最优；阶段四未执行"),
        (evidence["inherited-training-results"], evidence["exact-goal-recheck"], prior_report))
    candidate_set = d.CandidateSet(tuple(entries), tuple(entry.identity.key for entry in entries), (history,),
        "阶段三产出完整六个已登记且可加载的训练中心五门达标候选；全11项尚待阶段四，不自动选型、测试或冻结。")
    formal_report = report
    links = {"protocols/design.md": evidence["stage-three-protocol"].path,
             "others/preflight.json": evidence["exact-goal-recheck"].path,
             "others/registrations.json": evidence["candidate-registrations-and-loads"].path,
             "src/register.py": evidence["registration-source"].path}
    for source, destination in links.items():
        formal_report = formal_report.replace("](" + source + ")", "](" + destination + ")")
    print("ASSEMBLING_CANDIDATES_3_FULL", flush=True)
    assembled = assemble_delivery(R, d.DeliveryDefinition(B, d.DeliveryStage.CANDIDATES, 3,
        (sources["CANDIDATES"], sources["PROTOTYPES"], sources["MANDATE"])),
        d.DeliveryContent(candidate_set, d.DeliveryStatus.COMPLETE, (), (), report=formal_report,
            evidence=tuple((*evidence.values(), *accounts.values(), prior_report, report_ref))),
        resources=ExecutionResources(4, 1, 17),
        on_progress=lambda event: print("DELIVERY_PROGRESS", event.phase.value, event.completed, event.total, flush=True))
    assert assembled.validation.status is d.ValidationStatus.PASS
    checked = validate_experiment(R, d.ExperimentValidationRequest(E, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status is d.ValidationStatus.PASS
    save(WORK / "others/publication.json", {"report": report_ref.to_dict(), "experiment_validation": checked.to_dict(),
        "delivery": assembled.receipt.to_dict(), "delivery_validation": assembled.validation.to_dict(),
        "registered_candidates": list(KEYS), "handoff": list(KEYS), "new_financial_accounts": 0,
        "new_searches": 0, "full_economic_acceptance": "INDETERMINATE_STAGE_FOUR_NOT_RUN"})
    for path, expected in historical.items():
        assert digest(ROOT / path) == expected, path
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_three_candidates_20261102"].update({"status": "COMPLETE_SIX_REGISTERED_CANDIDATES",
        "delivery": assembled.receipt.reference.to_dict(), "report": report_ref.to_dict(),
        "registered_candidates": list(KEYS), "handoff": list(KEYS), "new_financial_accounts": 0,
        "new_searches": 0, "full_economic_acceptance": "INDETERMINATE_STAGE_FOUR_NOT_RUN",
        "stage_four_authorized": False, "sealed_test_authorized": False})
    intent["next_action"] = "阶段三已完整登记并交接六个训练五门达标候选，CANDIDATES/3 FULL通过；请用户批准阶段四，对全六点做适用稳健性与标准比较，不自动开2026测试或冻结。"
    update_research_intent(R, B, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="自主阶段三完成六点登记、独立快照身份及入口加载，CANDIDATES/3 FULL与报告发布通过；不以登记替代全11项稳健性验收")
    after = get_research_overview(R, B).to_dict()
    assert next(x for x in after["deliveries"] if x["stage"] == "CANDIDATES")["reference"] == assembled.receipt.reference.to_dict()
    for stage in ("PROTOTYPES", "MANDATE"):
        assert next(x for x in after["deliveries"] if x["stage"] == stage) == next(x for x in overview["deliveries"] if x["stage"] == stage)
    published = ROOT / "research/S017/assets/deliveries/CANDIDATES/3"
    assert all((published / link).is_file() for link in re.findall(r"\]\(([^)]+)\)", formal_report))
    document = d.DeliveryContent.from_dict(read(published / "delivery.json")["content"])
    assert document.status is d.DeliveryStatus.COMPLETE
    assert tuple(x.candidate_id for x in document.payload.handoff) == KEYS
    assert tuple(x.identity.key.candidate_id for x in document.payload.candidates) == KEYS
    save(WORK / "others/final_verification.json", {"status": "PASS", "historical_files_unchanged": len(historical),
        "candidate_keys": list(KEYS), "handoff_exactly_matches_registered_set": True,
        "source_content_identities_unchanged": True, "public_loads_and_module_imports_pass": 6,
        "strategy_step_invocations": 0, "new_financial_accounts": 0, "new_searches": 0,
        "stage_four_executed": False, "sealed_test_accessed": False})
    save(SCRATCH / "overview_after.json", after)
    print("CANDIDATES_3_FULL_PASS", assembled.receipt.reference.content_sha256, flush=True)


if __name__ == "__main__":
    main()
