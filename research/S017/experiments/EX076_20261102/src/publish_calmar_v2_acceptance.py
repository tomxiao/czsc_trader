"""Publish the confirmed rule revision and bounded RSCH capability acceptance."""
# ruff: noqa: E402
from partial_selfcheck import ROOT, WORK, read, save

from dataclasses import replace
from hashlib import sha256
import copy

from dataflows import ProviderConfig
from strategy_evaluator import research_models as m
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources
from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    publish_evidence, assemble_delivery, validate_experiment, update_research_intent,
    ResearchIntentUpdate, get_research_overview)
from czsc_trader import research_tools as d


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    acceptance = read(WORK / "others/calmar_v2_rsch_acceptance.json")
    assert acceptance["status"] == "PASS_CALCULATION_CAPABILITY_ACCEPTANCE"
    assert acceptance["new_research_accounts"] == 0 and acceptance["reused_published_accounts"] == 16
    assert read(WORK / "others/neighborhood_execution.json")["status"] == "PAUSED_BY_USER_SELF_CHECK_STANDARD_REVIEW"
    repository = RepositoryContext.discover(ROOT)
    batch, experiment = d.ResearchBatchRef("S017"), d.ExperimentRef("S017", WORK.name)
    candidate = load_candidate(repository, CandidateKey("S017", "C0338"))
    context = create_research_context(repository, batch, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(1, 1, 17))
    overview = get_research_overview(repository, batch).to_dict()
    source = d.DeliveryReference.from_dict(next(item["reference"] for item in overview["deliveries"] if item["stage"] == "MANDATE"))
    assert source.revision == 7 and source.content_sha256 == "a743a1d92ec1b94991378ec1d794c58ede11ee96b77a64a765eb22c4d9d3f8d0"
    previous_content = d.DeliveryContent.from_dict(read(ROOT / "research/S017/assets/deliveries/MANDATE/7/delivery.json")["content"])
    preserved = {path.relative_to(ROOT).as_posix(): digest(path)
                 for folder in (ROOT / "research/S017/deliveries/MANDATE/7", ROOT / "research/S017/deliveries/CANDIDATES/3")
                 for path in folder.iterdir() if path.is_file()}
    refs = {}

    def material(name, path):
        mime = {".json": "application/json", ".md": "text/markdown", ".py": "text/x-python"}[path.suffix]
        result = publish_evidence(context, d.MaterialEvidenceWrite(experiment, name, path.read_bytes(), mime, path.suffix[1:]))
        refs[name] = result
        return result

    policy_ref = d.EvidenceRef.from_dict(read(WORK / "others/selfcheck_v2_confirmation_publication.json")["reference"])
    assert policy_ref.resolve(ROOT).read_bytes() == (WORK / "protocols/confirmed_calmar_selfcheck_v2.json").read_bytes()
    for name, path in (
        ("calmar-v2-compute-request", WORK / "protocols/calmar_v2_compute_request.md"),
        ("calmar-v2-dev-authorization", WORK / "others/calmar_v2_dev_authorization.json"),
        ("calmar-v2-dev-completion", WORK / "others/calmar_v2_dev_completion.json"),
        ("calmar-v2-rsch-acceptance", WORK / "others/calmar_v2_rsch_acceptance.json"),
        ("calmar-v2-targets", WORK / "others/calmar_v2_targets.json"),
        ("calmar-v2-acceptance-panel", WORK / "others/calmar_v2_acceptance_panel.json"),
        ("calmar-v2-acceptance-comparison", WORK / "others/calmar_v2_acceptance_comparison.json"),
        ("calmar-v2-acceptance-source", WORK / "src/accept_calmar_v2.py"),
        ("calmar-v2-publication-source", WORK / "src/publish_calmar_v2_acceptance.py"),
    ):
        material(name, path)
    resource_ref = material("user-12-worker-authorization-and-pause", WORK / "others/reconfiguration_12.json")
    rules = m.ResearchTargets.from_dict(read(WORK / "others/calmar_v2_targets.json"))
    owners = {target.target_id: item.item_id for item in previous_content.payload.items
              if isinstance(item.requirement, d.PerformanceRequirement) for target in item.requirement.targets}
    owners["stress-net-calmar"] = owners["stress-relative-return"]
    confirmed = d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, policy_ref)
    items = []
    for item in previous_content.payload.items:
        if isinstance(item.requirement, d.PerformanceRequirement):
            values = tuple(target for target in rules.requirements if owners[target.target_id] == item.item_id)
            assert values
            item = replace(item, statement="统一Calmar目标及原回撤/频率/完整邻域要求；不设独立年化收益门",
                           confirmation=confirmed, requirement=d.PerformanceRequirement(values))
        elif item.item_id == "resources":
            item = replace(item, statement="自检现按用户指令暂停；获明确恢复指令后，在内存允许时使用最多12个独立工作进程、每进程1线程，有界批次发布；不嵌套超额并发",
                           confirmation=d.ConfirmationRecord(d.ConfirmationStatus.CONFIRMED, resource_ref))
        items.append(item)
    items.append(d.MandateItem("calmar-selfcheck-protocol-v2", d.MandateItemKind.EXECUTION,
        "CalmarSelfCheckProtocol/v8及v6排序；滚动252实际交易日、步长21、窗口前末净值及逐柱DD，逐窗Calmar差LINEAR Q10；压力下降量为标准C减压力C；RSCH最终核验硬门，TDR按明确输入计算",
        confirmed))
    mandate = d.ResearchMandate(tuple(items))
    actual = tuple(target for item in mandate.items if isinstance(item.requirement, d.PerformanceRequirement)
                   for target in item.requirement.targets)
    assert {target.target_id: target for target in actual} == {target.target_id: target for target in rules.requirements}
    statement = """# S017：统一Calmar自检约定修订

用户已确认统一Calmar标准及RSCH制定/最终核验硬门、TDR按显式输入计算与排序的分工，并授权DEV补齐能力后由RSCH验收。本修订替代旧参数及压力年化收益门，保留MANDATE/7、原始账户及旧规则结果，不改写历史。

中心Calmar严格>同合同买持1.5倍，DD≤买持0.8倍且≤25%。完整邻域至少ceil(13N/16)点同时满足Calmar≥买持1.25倍、DD≤买持0.9倍；全部点DD≤25%。压力每侧0.2%时Calmar严格>同场景买持，保留相对/绝对DD规则。原双频率要求、2024—2025训练和2026封存边界不变。Calmar须DD>1e-12且商有限，缺失不补值、不删点。

新版排序以中心Calmar/DD分层，同层依次为邻域Calmar Q10、邻域DD Q90、滚动超额Calmar Q10、压力Calmar下降量、最大单笔盈利贡献及60日闭合中位。原数值精度及方向保持，不以旧年化指标替代。时间/集中度/统计不确定性不新增硬门。

DEV的236项SE、110项TDR聚焦检查通过；RSCH复用16个已发布账户验证新目标及逐柱公式，零新回放。4个旧年化邻域门失败点均通过新Calmar点条件；6压力Calmar目标均通过。完整N仍不足，不能称策略或阶段四已通过，当前无正式选型排名。

252个已发布邻点保留，2577个未运行点仍暂停；12并发尚未启动。研究目标由用户确认，RSCH对规则和最终研究结论负责；平台的类型、身份、时间、资源、证据及数值验证不替代研究验收。技术能力验收通过不自动恢复研究、打开封存样本或授权冻结/生产/远端操作。
"""
    links = "\n".join(f"- [{name}]({ref.path})" for name, ref in refs.items())
    assembled = assemble_delivery(repository, d.DeliveryDefinition(batch, d.DeliveryStage.MANDATE, 8, (source,)),
        d.DeliveryContent(mandate, d.DeliveryStatus.COMPLETE, (), (), report=statement + "\n依据：\n\n" + links,
                          evidence=(policy_ref, *refs.values())), resources=ExecutionResources(1, 1, 17))
    assert assembled.validation.status is d.ValidationStatus.PASS
    values = acceptance["independently_verified_centers"]
    table = "\n".join(f"|{row['candidate']}|{row['rolling_excess_calmar_q10']:.6f}|{row['pressure_calmar']:.6f}|{row['pressure_calmar_loss']:.6f}|通过|"
                      for row in values)
    report = """# EX076：统一Calmar计算能力已补齐并由RSCH验收，自检仍暂停

本次用户授权的RSCH提需求→DEV补能力→RSCH验收目标已达成。DEV提交d6b846ac4；236项SE和110项TDR聚焦检查、Ruff及diff检查通过，未运行全仓回归。新MANDATE/8为COMPLETE，FULL验证PASS；这只确认新约定及必要证据，不代表策略验收。

## 做了哪些尝试

RSCH明确了完整Calmar自检规则和逐窗公式。DEV新增CalmarSelfCheckProtocol/v8与v6排序，参数/压力支持显式Calmar条件，TDR schema14认证新版本并保持旧版本读取。平台不选择倍数或添加正年化门；RSCH对目标输入及最终研究验收负责。未修改策略、撮合、费用、原账或账本存储表示。

RSCH随后完整认证六标准、六压力及四个已发布邻点，共16个既有账户；从逐柱账本独立复算每中心12个滚动252日/步长21窗口Calmar差Q10，及标准C减压力C，并与新面板和排序分箱一致性核对。零新研究账户，不恢复剩余自检。已有252邻点仍保留，原计数及年化门结果仅属于旧规则，不作为新目标最终否决。

## 有哪些收获

|配置|滚动超额Calmar Q10|压力净Calmar|压力Calmar下降量|压力Calmar硬门|
|---|---:|---:|---:|---|
""" + table + """

4个旧年化邻域门失败点，在新Calmar点条件下均通过，说明计算链没有额外继承年化否决门。六中心的新压力Calmar目标也均通过，包括旧相对年化门失败的配置。它们仍须完整邻域及其余适用要求；本验收面板仅纳入4个既有邻点，六点完整目标状态均为INDETERMINATE，无Pareto名次，不宣称252点或2829点已全部按新规则认证。

这些是反复使用训练样本中的规则修订重评及数值能力验收，不是新的独立验证。时间、集中性和统计不确定性仍按研究约定披露，族内选择偏差资料不足不伪造通过；2026价格和策略绩效未读取。历史报告、旧FAIL及旧交付保留，当前以新约定解释后续输入。

## 下一步建议是什么

等待用户明确恢复阶段四，再核对并复用252份已发布邻点，按新约定完成剩余2577点及完整比较。在内存允许时上限12个独立进程，每进程1线程，逐批发布并退出；不直接沿用旧脚本的年化joint_pass作新规则资格判据。本次不自动恢复，不开封测试或进入选型冻结。

## 有什么依据

[计算需求](protocols/calmar_v2_compute_request.md)、[用户确认与分工](protocols/confirmed_calmar_selfcheck_v2.json)、[DEV完成记录](others/calmar_v2_dev_completion.json)、[RSCH验收](others/calmar_v2_rsch_acceptance.json)、[新显式目标](others/calmar_v2_targets.json)、[验收面板](others/calmar_v2_acceptance_panel.json)、[对应比较](others/calmar_v2_acceptance_comparison.json)、[新约定](../../deliveries/MANDATE/8/report.md)。正式账户及依赖仍在批次assets中，须与Git材料共同保留。
"""
    (WORK / "report.md").write_text(report, encoding="utf-8", newline="\n")
    previous = d.EvidenceRef.from_dict(read(WORK / "report_ref.json")["report"])
    sources = tuple(d.EvidenceRef.from_dict(row["evidence"]) for row in acceptance["sources"])
    report_ref = publish_evidence(context, d.ExperimentReportWrite(experiment, sha256(report.encode()).hexdigest(),
        d.ExperimentOutcome.INCOMPLETE, (policy_ref, *refs.values(), *sources), previous=previous))
    validated = validate_experiment(repository, d.ExperimentValidationRequest(experiment, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validated.status is d.ValidationStatus.PASS
    assert all(digest(ROOT / path) == expected for path, expected in preserved.items())
    save(WORK / "others/calmar_v2_acceptance_publication.json", {"status": "PASS_CAPABILITY_ACCEPTED_RESEARCH_PAUSED",
        "report": report_ref.to_dict(), "experiment_validation": validated.to_dict(),
        "mandate": assembled.receipt.to_dict(), "mandate_validation": assembled.validation.to_dict(),
        "historical_public_files_unchanged": len(preserved), "research_accounts_replayed": 0,
        "stage_four_complete": False, "remaining_replays_resumed": False})
    intent = copy.deepcopy(read(ROOT / "research/registrations/S017/family.json")["research_intent"])
    intent["active_stage_four_20261102"].update(status="CALMAR_V2_CAPABILITY_ACCEPTED_EXECUTION_PAUSED",
        current_mandate=assembled.receipt.reference.to_dict(), capability_acceptance_report=report_ref.to_dict(),
        calmar_v2_dev_commit="d6b846ac40fa275b9ddebdffecaf5de7931d3048", execution_paused_by_user=True,
        current_calmar_capability_support="IMPLEMENTED_346_FOCUSED_TESTS_AND_RSCH_EXISTING_ACCOUNT_ACCEPTANCE_PASS",
        new_goal_acceptance="INDETERMINATE_COMPLETE_NEIGHBORHOOD_PENDING", old_annual_failures_not_new_goal_veto=True)
    intent["next_action"] = "用户明确恢复后，RSCH按MANDATE/8及v8/v6新规则核验复用252已发布邻点，内存允许时最多12并发完成剩余2577点；当前保持暂停，不开封或冻结。"
    update_research_intent(repository, batch, ResearchIntentUpdate(research_intent=intent), actor="RSCH",
        reason="用户授权的RSCH需求、DEV能力补齐及RSCH验收完成；新Calmar约定MANDATE/8 FULL通过，346项聚焦检查与16既有账户复核通过，阶段四回放仍按用户暂停")
    print("MANDATE_8_FULL_PASS", assembled.receipt.reference.content_sha256, "RSCH_CAPABILITY_ACCEPTED_EXECUTION_PAUSED", flush=True)


if __name__ == "__main__":
    main()
