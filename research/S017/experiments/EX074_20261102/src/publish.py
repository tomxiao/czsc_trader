"""Publish the stage-two result, preserving prior evidence and eligibility."""
from hashlib import sha256
import copy
import re

from reassess import ROOT, WORK, PRIOR, SCRATCH, read, save, digest
from dataflows import ProviderConfig
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, assemble_delivery, create_research_context,
    get_research_overview, publish_evidence, update_research_intent, validate_experiment,
)
from czsc_trader import research_tools as d
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources

R = RepositoryContext.discover(ROOT)
B = d.ResearchBatchRef("S017")
E = d.ExperimentRef("S017", WORK.name)


def main():
    analysis = read(WORK / "others/analysis.json")
    assert analysis["status"] == "PASS" and analysis["authenticated_unique_accounts"] == 25
    qualified = analysis["new_training_center_qualifiers"]
    assert len(qualified) == 6
    rows = {row["candidate_id"]: row for row in analysis["results"]}
    overview = get_research_overview(R, B).to_dict()
    old_prototype = next(x["reference"] for x in overview["deliveries"] if x["stage"] == "PROTOTYPES")
    mandate = next(x["reference"] for x in overview["deliveries"] if x["stage"] == "MANDATE")
    assert old_prototype["revision"] == 12 and mandate["revision"] == 7
    sources = []
    for experiment in ("EX071_20261101", "EX072_20261102", "EX073_20261102"):
        checked = validate_experiment(R, d.ExperimentValidationRequest(
            d.ExperimentRef("S017", experiment), d.ExperimentValidationScope.REPORT_PUBLICATION))
        assert checked.status is d.ValidationStatus.PASS, checked.to_dict()
        sources.append(checked.report)
    hashes = {}
    for folder in (ROOT / "research/S017/deliveries/PROTOTYPES/12", ROOT / "research/S017/deliveries/CANDIDATES/2",
                   ROOT / "research/S017/deliveries/MANDATE/7"):
        hashes.update({path.relative_to(ROOT).as_posix(): digest(path) for path in folder.iterdir() if path.is_file()})
    for path in (PRIOR / "report.md", PRIOR / "others/search_trials.json", PRIOR / "others/all_accounts.json",
                 ROOT / "research/S017/experiments/EX073_20261102/report.md"):
        hashes[path.relative_to(ROOT).as_posix()] = digest(path)
    save(SCRATCH / "historical_before_publication.json", hashes)
    context = create_research_context(R, B, providers=ProviderConfig(bindings={}),
                                     resources=ExecutionResources(4, 1, 17))
    refs = {}

    def material(name, path):
        suffix = path.suffix[1:]
        result = publish_evidence(context, d.MaterialEvidenceWrite(E, name, path.read_bytes(),
            {"md": "text/markdown", "json": "application/json", "py": "text/x-python"}[suffix], suffix))
        refs[name] = result
        return result

    for name, path in (
        ("protocol", WORK / "protocols/design.md"), ("new-goal-account-analysis", WORK / "others/analysis.json"),
        ("se-comparison", WORK / "others/se_comparison.json"),
        ("reassessment-source", WORK / "src/reassess.py"), ("publication-source", WORK / "src/publish.py"),
        ("prior-ex072-report-text", PRIOR / "report.md"),
        ("prior-ex073-counterevidence", ROOT / "research/S017/experiments/EX073_20261102/report.md"),
    ):
        material(name, path)
    definitions = {key: material("definition-" + key, WORK / "others/definitions" / (key + ".json")) for key in qualified}
    accounts = {key: d.EvidenceRef.from_dict(rows[key]["record"]["evidence"]) for key in qualified}
    table = []
    for key in qualified:
        c = rows[key]["candidate"]
        table.append(f"|{key}|{c['net_calmar']:.6f}|{100*c['annualized_return']:.4f}%|{100*c['bar_max_drawdown']:.4f}%|{c['closed_cycles']}|{c['rolling_60_closed_cycle_median']}|{c['covered_windows']}/{c['frequency_windows']}|")
    bh = rows["C0342"]["benchmark"]
    report = """# EX074：新目标下已取得训练五门达标完整原型

阶段二本次目标已达成：认证EX072全部25份原公共训练账户后，确认六个同机制参数表达同时满足MANDATE/7中心Calmar、双回撤及双频率五门。C342是较高收益的机制代表，C352提供较低回撤、较低收益/频率的另一取舍；未开展正式标准排序，不能称最终优选策略。

本轮零新账户、零搜索、零新外部数据、零候选登记，2026价格与策略绩效继续封存。已有完整机制、对照与反证足以承接新目标，继续重复账户或盲搜价值有限；不是把首次过门当作研究充分。旧目标下FAIL、旧CANDIDATES/2空集及所有旧资格保持。

## 做了哪些尝试

以已获准的自主阶段二和MANDATE/7为依据，对25点公共V4逐份核验哈希、所有者、请求、定义/六参数、行情输入与同合同BH，固定4进程、各1线程。独立重算502实际交易日、6490估值点、443个完整60日窗的净年化/回撤/闭合及覆盖，并与原指标和SE逐项目标一致性核对。没有调用evaluate、RESUME或私有缓存兜底。

SE请求保留全部11个外层目标，中心五门结果单列；邻域及费用压力未检就记证据不足，不以删目标得到“全部通过”。复用标准账本产生的诊断只用于证据复核，不发布ASSESSMENT、不执行正式阶段四选型或统计验收。两处读取脚本接口/字段预检问题修正后完成认证，未改变金融策略或原账，未产生新的金融失败计算。

## 有哪些收获

|配置|净Calmar|净年化|BAR_CLOSE最大回撤|闭合数|60日闭合中位|至少3笔窗口|
|---|---:|---:|---:|---:|---:|---:|
""" + "\n".join(table) + f"""

同合同BH净Calmar为{bh['net_calmar']:.8f}、净年化{100*bh['annualized_return']:.4f}%、回撤{100*bh['bar_max_drawdown']:.4f}%；严格Calmar门为{rows['C0342']['calmar_boundary']:.8f}。绝对回撤门25%，相对回撤门{100*.8*bh['bar_max_drawdown']:.4f}%，中位≥6且至少90%窗≥3。六点五门均通过；其余19点逐项失败原因均保留在分析中，不只展示best_trials。C352收益低于BH但Calmar与风险符合已确认目标，不另加收益否决门。

达标来自目标修订后的既有训练结果重评，不是新发现六个独立收益机制。C338与旧C337、C339与旧C336的经济等价历史继续披露。全25点新认证与经济核对不等于全25点都新增逐状态策略复原；原完整逐状态复原只覆盖旧研究实际审计的代表。

### 完整机制及组件职责

入口E0：前完成柱是负实体，当前完成Close突破前High，并严格超过alpha×ATR13[t−2]的收复距离；M006是实际门，M005额外量/波幅条件仅记录解释，不是入口过滤。U为前Close>前MA65>前MA260；MF为连续至少两根负实体整串被当前Close完整收复。MF/U只分配推进保护g，不删除E0。

空仓提出全可用资金限价买入，真实成交才激活cycle，冻结入场背景与g；持仓中新背景不重新路由或加仓。初始失效线F0=S0+a(R−S0)，S0取信号与前柱低点较小者，R为前High。真实fill低于信号结构也不事后删除。

持有中通过当时已完成的三柱低点确认形成pending；三柱最早BarStart必须严格晚于实际入场，整个入场区间排除。pending不抬退出线，低点破坏或已不高于有效线则取消；Close严格越过候选H才接受。接受后的线为F=L+b(H−L)+g·max(0,P−H)，P是接受以来最高完成Close；新线不能下降，新的L/H接受须严格抬线。完成Close<F才锁存退出，下一执行区间卖出，受阻时持续退出到真实清仓；等于线保持，不设timer，不把识别前的跳空说成可避免。

六参数完整定义及两份实际源码随各原型定义包保存。C338—342固定其余参数，只改变g_MF，完整资金路径包含退出及资本传播；C352的六参数共同变化，alpha更高使市场E0从209变为81，闭合从94变为53，不能当作同入口纯MF保护对照。C342相对C338净年化只增加约3.91个百分点、回撤几乎不变；它是有限完整用途，不能称普遍独立保护alpha。

### 最强反证与边界

EX073仍有效：C342主回撤约86.97%发生在ACCEPTED阶段，但该状态全期也贡献正增长；NON_MF_OTHER承担主回撤，同时贡献约72.83%净log增长。不能由此直接删入口或统一收紧退出。C352最大五笔盈利贡献约60.82%，C342约47.81%，集中性风险仍需正式检查；它们不是新增硬门。C356的较高净年化约205.57%伴随34.75%回撤，仍违反绝对回撤门，不能用收益抵消。

开发池经过多轮选择，全部结果只属于反复使用的2024—2025训练；阶段一修订、无前视重算和分年复核都不恢复独立性。费用压力、完整适用参数邻域及正式五项自检未完成，六个中心达标点在全部11目标上的总验收仍为INDETERMINATE；不能称完整策略验收或未来有效。2026只保留原有元信息/经营信息暴露披露，未读取封存价格与绩效。

## 下一步建议是什么

阶段二已具可承接的训练达标完整原型，当前不再追加MF常数搜索或为了改名阶段制造新机制。建议经用户批准后进入阶段三，先整理和登记现有六个训练达标配置、核对恢复与可加载性，不新增搜索；随后另获阶段四授权做全部适用稳健性与标准比较，再由用户选型。当前不自动登记、进入阶段四、开封测试或冻结。

## 有什么依据

[固定方案](protocols/design.md)、[25点原账与逐门结果](others/analysis.json)、[完整SE目标检查](others/se_comparison.json)、[执行源码](src/reassess.py)。全部六个新中心达标原型均有精确实现身份、源代码/参数恢复包及原公共账户；旧控制和机制来源由PROTOTYPES/12及EX071/072承接，EX073反证随新交付保存。技术完整性通过只认证实际材料与账户，不代替稳健性或独立检验。
"""
    (WORK / "report.md").write_text(report, encoding="utf-8", newline="\n")
    report_ref = publish_evidence(context, d.ExperimentReportWrite(E, sha256(report.encode()).hexdigest(),
        d.ExperimentOutcome.COMPLETED, tuple((*refs.values(), *accounts.values(), *sources))))
    definition = d.ExperimentDefinitionRef(definitions["C0342"], "strategy:step")

    def component(key, role, label, judgment):
        return d.ComponentEntry(key, definition, role, label, "完成30m观察，下一可执行区间生效",
            "EX071原固定对照及EX072/EX073真实完整账户；C352联合变化不可单项归因",
            "只用当时已完成RAW柱、真实BUY与严格postfill状态；不读未来或事后回撤标签", "RAW",
            "已反复使用2024—2025训练，2026sealed", judgment,
            (d.ComponentTestResult(key + "-whole-prototype-role", E.experiment_id, refs["protocol"],
                d.ComponentTestStatus.SUPPORTED, "认证完整原型中的用途；不是组件单独收益或独立因果证明",
                (refs["new-goal-account-analysis"], refs["prior-ex073-counterevidence"], *accounts.values())),))

    components = (
        component("E0-RECLAIM", "入场", "前负实体High收复及alpha波幅余量", "有完整原型用途，M005量条件不是实际门；未证明入口独立alpha"),
        component("CONFIRMED-STRUCTURE", "持有与失效", "初始结构、严格postfill低点确认及ACCEPTED支撑", "同一收入/风险承担框架；主回撤不能简单归因入口或退出"),
        component("FROZEN-PROGRESS", "入场冻结背景与推进保护", "MF覆盖U分配g，真实BUY冻结整个cycle", "有限完整用途；MF轴只带来小幅改善，联合参数不作单因归因"),
    )
    uses = tuple(d.PrototypeComponentUse(c.component_id, c.role, c.judgment) for c in components)
    prior = d.DeliveryReference.from_dict(old_prototype)
    entries = []
    for key in qualified:
        record = rows[key]["record"]
        source_key = "C0336" if key == "C0339" else "C0337"
        entries.append(d.PrototypeEntry(key,
            d.CandidateIdentityRef(CandidateKey("S017", key), record["evaluation_identity"]["content_sha256"]),
            d.ExperimentDefinitionRef(definitions[key], "strategy:step"),
            "完成价收复后，已确认上行结构及入场冻结的推进保护协作，争取收益并限制失效风险；同一机制参数表达。",
            uses, (d.EvaluationEvidenceRef(accounts[key], (record["evaluation_id"],)),),
            d.PrototypeDisposition.DEVELOP if key == "C0342" else d.PrototypeDisposition.INVESTIGATE,
            "新训练中心五门达标；C342为机制代表，其他点保留对照/取舍；不是正式标准排序或最终采用。",
            ("反复使用训练、已见目标后重评，不是独立验证", "邻域、压力及全部11目标尚未完整验收",
             "旧MF机制用途有限，不能把会计回撤归因当可预测损失", "保留旧交付判断和候选资格，不回写旧FAIL"),
            "请用户批准阶段三整理登记六个既有训练达标配置；不新增搜索，不自动阶段四或封存测试。",
            (definitions[key], refs["new-goal-account-analysis"], refs["protocol"], accounts[key], refs["prior-ex073-counterevidence"]),
            sources=(d.PrototypeReference(prior, source_key),)))
    comparisons = (
        d.PrototypeComparison("mf1-vs-mf075", "C0342", "C0338", "固定其余五参数，MF保护1相对.75的完整用途与代价？",
            refs["protocol"], (refs["new-goal-account-analysis"], accounts["C0342"], accounts["C0338"]),
            "净年化约+3.91pp、回撤几乎不变；有限完整资金路径增量，含资本传播，不是普遍成熟保护。"),
        d.PrototypeComparison("joint-risk-return-tradeoff", "C0352", "C0342", "另一个训练达标联合配置呈现什么收益/风险取舍？",
            refs["protocol"], (refs["new-goal-account-analysis"], accounts["C0352"], accounts["C0342"]),
            "C352收益、回撤及频率均更低；alpha与另五参数一起变化，不能解释为纯MF或纯入口因果。"),
    )
    panel = d.PrototypePanel(tuple(entries), components, comparisons,
        "阶段二取得六个同机制参数表达的训练中心五门达标完整原型；正式全目标/稳健性未完成，旧资格不变。")
    published_report = report
    mapping = {"protocols/design.md": refs["protocol"].path, "others/analysis.json": refs["new-goal-account-analysis"].path,
               "others/se_comparison.json": refs["se-comparison"].path, "src/reassess.py": refs["reassessment-source"].path}
    for source, target in mapping.items():
        published_report = published_report.replace("](" + source + ")", "](" + target + ")")
    assembled = assemble_delivery(R, d.DeliveryDefinition(B, d.DeliveryStage.PROTOTYPES, 13,
        (prior, d.DeliveryReference.from_dict(mandate))),
        d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report=published_report,
            evidence=tuple((*refs.values(), *accounts.values(), *sources, report_ref))),
        resources=ExecutionResources(4, 1, 17))
    assert assembled.validation.status is d.ValidationStatus.PASS
    checked = validate_experiment(R, d.ExperimentValidationRequest(E, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert checked.status is d.ValidationStatus.PASS
    save(WORK / "others/publication.json", {"report": report_ref.to_dict(), "experiment_validation": checked.to_dict(),
        "delivery": assembled.receipt.to_dict(), "delivery_validation": assembled.validation.to_dict(),
        "new_real_account_compute": 0, "registered_candidates": 0, "training_center_qualified": qualified,
        "full_economic_acceptance": "INCOMPLETE_NOT_STAGE_FOUR"})
    for path, expected in hashes.items():
        assert digest(ROOT / path) == expected, path
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_two_calmar_20261102"].update({"status": "COMPLETE_TRAINING_QUALIFIED_PROTOTYPES",
        "prototype_delivery": assembled.receipt.reference.to_dict(), "latest_report": report_ref.to_dict(),
        "training_center_qualifiers": qualified, "authenticated_public_accounts": 25,
        "new_real_account_compute": 0, "new_searches": 0, "registered_candidates": 0,
        "full_economic_acceptance": "INCOMPLETE_NEIGHBORHOOD_AND_STRESS_NOT_RUN",
        "stage_three_authorized": False, "stage_four_authorized": False, "sealed_test_authorized": False})
    intent["next_action"] = "阶段二已取得六个新中心五门达标原型；建议获用户批准后阶段三仅整理登记现有六点，不新增搜索；正式阶段四自检与2026封存测试另行授权。"
    update_research_intent(R, B, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="自主阶段二复用全部25原公共训练账户完成，六个同机制参数原型通过MANDATE/7中心五门；PROTOTYPES/13 FULL通过，无新账户或搜索，旧资格保持")
    after = get_research_overview(R, B).to_dict()
    assert next(x for x in after["deliveries"] if x["stage"] == "PROTOTYPES")["reference"] == assembled.receipt.reference.to_dict()
    assert next(x for x in after["deliveries"] if x["stage"] == "CANDIDATES") == next(x for x in overview["deliveries"] if x["stage"] == "CANDIDATES")
    root = ROOT / "research/S017/assets/deliveries/PROTOTYPES/13"
    assert all((root / link).is_file() for link in re.findall(r"\]\(([^)]+)\)", published_report))
    save(WORK / "others/final_verification.json", {"status": "PASS", "historical_files_unchanged": len(hashes),
        "original_candidates_delivery_unchanged": True, "prototypes": 6, "one_shared_mechanism_family": True,
        "full_goal_acceptance_not_claimed": True, "new_account_computes": 0, "sealed_test_accessed": False})
    print("PROTOTYPES_13_FULL_PASS", assembled.receipt.reference.content_sha256, flush=True)


if __name__ == "__main__":
    main()
