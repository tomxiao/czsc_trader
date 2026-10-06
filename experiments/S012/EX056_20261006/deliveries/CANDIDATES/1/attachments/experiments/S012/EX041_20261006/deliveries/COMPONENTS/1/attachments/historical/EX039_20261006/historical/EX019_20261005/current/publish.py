"""Stage-two successor publication with role-specific confirmation findings."""

import json
from pathlib import Path
from research_experiment import load_experiment
from czsc_trader.research_tools import (
    ComponentEntry,
    ComponentTestResult,
    ComponentTestStatus,
    ExperimentDefinitionRef,
    FactValue,
    FactStatus,
    Explanation,
    ExplanationKind,
)
from .delivery import ConsolidatedStageTwoDelivery, attachment, experiment_evidence

SPECS = (
    (
        "Q01_AFTERNOON_SUPPORT",
        "afternoon_positive",
        18,
        "下午转涨的确认反证",
        ("INEFFECTIVE", "INEFFECTIVE"),
        "O01条件增量负；N09均值微升但固定父及限价贡献明显下降，不作为推荐确认门。",
    ),
    (
        "Q02_LAST_HOUR_SUPPORT",
        "last_hour_positive",
        18,
        "尾盘转涨的确认反证",
        ("INEFFECTIVE", "INEFFECTIVE"),
        "两个机会主5日条件均值及固定父、限价贡献均下降，缺少确认支持。",
    ),
    (
        "Q03_UPPER_HALF_CLOSE",
        "close_upper_half",
        18,
        "强收盘位置的条件确认诊断",
        ("INSUFFICIENT_DATA", "INSUFFICIENT_DATA"),
        "O01条件均值上升但固定父与限价贡献下降；N09均值增量很小，区间及执行不足。",
    ),
    (
        "Q04_SHOCK_RECOVERY",
        "recovered_after_shock",
        18,
        "最差分钟变动后恢复的条件诊断",
        ("INSUFFICIENT_DATA", "INEFFECTIVE"),
        "O01条件均值略升但固定贡献及执行恶化；N09条件增量负。恢复不是最低价后反弹或主动买单。",
    ),
    (
        "Q05_PEER_PRICE_SUPPORT",
        "peer_positive",
        18,
        "同类日内方向的确认候选",
        ("INSUFFICIENT_DATA", "INSUFFICIENT_DATA"),
        "同类正向有条件均值增量，但共同底层黄金资产及自身方向混淆；EX019不一致小子组/区间不足，不能登记为第二个独立确认。",
    ),
    (
        "Q06_VOLUME_PARTICIPATION",
        "volume_participation",
        18,
        "成交量参与的确认诊断",
        ("INSUFFICIENT_DATA", "INSUFFICIENT_DATA"),
        "O01主限价贡献提高但原事件贡献下降且去2025条件增量负；N09固定父及限价贡献下降，未形成可推荐门。",
    ),
    (
        "Q07_OWN_INTRADAY_SUPPORT",
        "own_intraday_positive",
        19,
        "O01回调后的日内修复确认",
        ("SUPPORTED", "INSUFFICIENT_DATA"),
        "仅O01主5日有条件支持：79至30事件，净1.6977%，条件提升0.9192pp，固定父贡献+0.2308pp、限价+0.1619pp。q=.24、贡献区间跨0、容量下降及延迟执行反证保留；N09无推荐强制门。",
    ),
)


def create_delivery(root: Path):
    owner = "EX019_20261005"
    base = f"experiments/S012/{owner}/"
    files = []
    protocols = {}
    for n in (18, 19):
        item = attachment(
            root, f"experiments/S012/EX{n:03d}_20261005/02_design.md", f"EX{n:03d}_protocol.md"
        )
        files.append(item)
        protocols[n] = item.reference
        files.append(
            attachment(
                root,
                f"experiments/S012/EX{n:03d}_20261005/04_conclusion.md",
                f"EX{n:03d}_report.md",
            )
        )
    report = files[3].reference
    for source, name, media in (
        (base + "publish.py", "publish.py", "text/x-python"),
        (base + "delivery.py", "delivery.py", "text/x-python"),
        (base + "role_coverage.json", "role_coverage.json", "application/json"),
        (base + "selection_trigger.json", "selection_trigger.json", "application/json"),
        (
            "research/S012/materials/confirmation_stage2_authorization_20261005.json",
            "authorization.json",
            "application/json",
        ),
        (
            "research/S012/materials/confirmation_independent_verification_20261005.json",
            "EX018_independent_verification.json",
            "application/json",
        ),
        (
            "research/S012/materials/confirmation_competition_verification_20261005.json",
            "EX019_independent_verification.json",
            "application/json",
        ),
    ):
        files.append(attachment(root, source, name, media))
    components, facts = [], []
    data = {}
    definitions = {}
    for n in (18, 19):
        eid = f"EX{n:03d}_20261005"
        data[n] = json.loads(
            (root / f"experiments/S012/{eid}/artifacts/rex/confirmation.json").read_text(
                encoding="utf-8"
            )
        )
        loaded = load_experiment(root / f"experiments/S012/{eid}")
        definitions[n] = ExperimentDefinitionRef(
            eid,
            loaded.definition.sha256,
            loaded.binding.source_sha256,
            "mechanism.make_gates" if n == 18 else "mechanism.make_inputs",
        )
    for cid, gate, n, role, statuses, judgment in SPECS:
        eid = f"EX{n:03d}_20261005"
        evidence = tuple(
            experiment_evidence(root, eid, name)
            for name in ("confirmation.json", "annual.json", "inference.json")
        )
        if gate == "peer_positive":
            evidence += tuple(
                experiment_evidence(root, owner, name)
                for name in ("confirmation.json", "inference.json")
            )
        tests = []
        for b, status in zip(("o01", "mid_momentum_positive"), statuses):
            row = next(
                r
                for r in data[n]
                if r["base"] == b
                and r["gate"] == gate
                and r["horizon"] == 5
                and r["delay"] == 0
                and r["fee"] == 0.001
                and r["quality"] == "all"
            )
            ids = []
            for field, unit in (
                ("parent_events", "count"),
                ("passed_events", "count"),
                ("passed_net", "fraction"),
                ("conditional_lift", "fraction_difference"),
                ("fixed_contribution_delta", "fraction_per_parent_event"),
                ("fixed_limit_contribution_delta", "fraction_per_parent_event"),
                ("kept_limit_fills", "count"),
                ("rescheduled_limit_per60", "potential_fills_per_60_sessions"),
            ):
                fact_id = f"{cid}__{b}__{field}"
                ids.append(fact_id)
                value = row[field]
                facts.append(
                    FactValue(
                        fact_id,
                        value,
                        unit,
                        FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA,
                        (evidence[0],),
                        None if value is not None else "无可评价事件",
                    )
                )
            tests.append(
                ComponentTestResult(
                    f"{cid}__{b}",
                    eid,
                    protocols[n],
                    ComponentTestStatus(status),
                    b + "条件作用；" + judgment,
                    evidence,
                    tuple(ids),
                )
            )
        components.append(
            ComponentEntry(
                cid,
                definitions[n],
                role,
                "同父机会中通过/全部/未通过同费用净收益，固定父时间表贡献及5日不利移动",
                "主5日，1/3日、费用、延迟、质量、年度及极值反证完整保留",
                "同一父机会输入有效池；自身方向竞争解释；固定父时间表和筛后重排分别计数",
                "T17:00完整观察、T+1执行；历史供应商逐日发布时点未核验",
                "目标及参考不复权价格；日线Low限价触价代理非真实成交",
                "S012全上市历史开发池，2022起阈值可得；Q07支持仅O01主5日，N09不设推荐强制门",
                judgment,
                tuple(tests),
            )
        )
    coverage = next(f for f in files if f.reference.path.endswith("role_coverage.json"))
    for name, value in (
        ("independent_supported_role_components", 6),
        ("opportunity_components", 2),
        ("risk_components", 3),
        ("conditional_confirmation_components", 1),
        ("component_ledger_records", 39),
        ("confirmation_paths_this_round", 480),
    ):
        facts.append(FactValue(name, value, "count", FactStatus.AVAILABLE, (coverage.reference,)))
    return ConsolidatedStageTwoDelivery(
        root,
        owner=owner,
        current_experiments=("EX018_20261005", owner),
        new_components=tuple(components),
        new_facts=tuple(facts),
        current_attachments=tuple(files),
        conclusion="阶段二后继交付完成：39研究记录，去重后6个有职责支持的独立组件，2机会、3风险/状态及1个仅O01主5日有边界的确认。N09无推荐强制门；完整账户三个经济目标未验证，阶段三等待用户批准。",
        current_protocol=protocols[19],
        current_report=report,
        extra_explanations=(
            Explanation(
                ExplanationKind.RESEARCH_JUDGMENT,
                "R01重复汇总三风险不计新增；每父机会测试不计独立组件。确认数量按支持作用而非39条台账计算。",
                supporting=(report,),
            ),
            Explanation(
                ExplanationKind.RESEARCH_JUDGMENT,
                "Q07支持O01条件确认，固定贡献区间跨0、q=.24、2024反证、延迟限价贡献负和容量下降均保留。N09不推荐机械过滤。",
                supporting=(report,),
            ),
            Explanation(
                ExplanationKind.RESEARCH_JUDGMENT,
                "历史风险定义和证据保持；EX018原价中位视图为短周期机会内上下文，不能自动将风险指标转换为确认门。",
                supporting=(report,),
            ),
        ),
    )
