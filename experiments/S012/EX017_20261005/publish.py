"""Consolidated stage-two content; publishing is explicit in the external driver."""

from hashlib import sha256
import json
from pathlib import Path
from research_experiment import load_experiment
from czsc_trader.research_tools import (
    ComponentEntry,
    ComponentTestResult,
    ComponentTestStatus,
    ExperimentDefinitionRef,
    EvidenceFile,
    EvidenceRef,
    FactValue,
    FactStatus,
    Explanation,
    ExplanationKind,
)
from .delivery import ConsolidatedStageTwoDelivery, experiment_evidence


def create_delivery(root: Path):
    base = "experiments/S012/EX017_20261005/"

    def attachment(source, name, media="text/markdown"):
        return EvidenceFile(
            source,
            EvidenceRef(
                "attachments/current/" + name,
                sha256((root / source).read_bytes()).hexdigest(),
                media,
            ),
        )

    files = [
        attachment(f"experiments/S012/EX{i:03d}_20261005/02_design.md", f"EX{i:03d}_protocol.md")
        for i in (15, 16, 17)
    ]
    report = attachment(base + "04_conclusion.md", "stage2_report.md")
    files.extend(
        (
            report,
            attachment(base + "publish.py", "publish.py", "text/x-python"),
            attachment(base + "delivery.py", "delivery.py", "text/x-python"),
            attachment(
                "research/S012/materials/autonomous_stage2_authorization_20261005.json",
                "authorization.json",
                "application/json",
            ),
            attachment(
                "research/S012/materials/autonomous_independent_verification_20261005.json",
                "independent_verification.json",
                "application/json",
            ),
            attachment(
                "research/S012/materials/normal_independent_verification_20261005.json",
                "normal_independent_verification.json",
                "application/json",
            ),
            attachment(
                base + "research_coverage.json", "research_coverage.json", "application/json"
            ),
        )
    )
    protocols = {15: files[0].reference, 16: files[1].reference, 17: files[2].reference}

    def read(eid, name):
        return json.loads(
            (root / f"experiments/S012/{eid}/artifacts/rex/{name}").read_text(encoding="utf-8")
        )

    rows = {i: read(f"EX{i:03d}_20261005", "opportunities.json") for i in (15, 16, 17)}
    entries = []
    facts = []
    definitions = {}
    for i, entrypoint in (
        (15, "analysis.make_signals"),
        (16, "mechanism.extend"),
        (17, "mechanism.make_states"),
    ):
        loaded = load_experiment(root / f"experiments/S012/EX{i:03d}_20261005")
        definitions[i] = ExperimentDefinitionRef(
            f"EX{i:03d}_20261005",
            loaded.definition.sha256,
            loaded.binding.source_sha256,
            entrypoint,
        )
    specs = (
        (
            "N01_LATE_VOLUME",
            15,
            "late_volume_low",
            "低尾盘成交占比的弱机会线索",
            "INSUFFICIENT_DATA",
            "5日匹配增量0.0619%、OLS0.0114%；延迟两日匹配转负，筛查48信号q=1，保留候选线索。",
        ),
        (
            "N02_DRY_PULLBACK",
            15,
            "dry_pullback",
            "趋势内缩量回调的机会诊断",
            "INSUFFICIENT_DATA",
            "24事件，匹配增量0.1166%；排异常匹配转负、剔除最佳5次均值负，样本弱。",
        ),
        (
            "N03_LONG_CLOSURE",
            15,
            "pre_long_closure",
            "假期持有补偿与后续修复的竞争解释",
            "INEFFECTIVE",
            "T+1休市前最后开市日入场，1/3日净收益负；5日正结果不能证明假期补偿，最佳5次剔除后负。",
        ),
        (
            "N04_THIN_IMPACT",
            15,
            "thin_impact_low",
            "低量冲击结构的稀疏线索",
            "INSUFFICIENT_DATA",
            "9事件、4非重叠事件，2025/2026无事件；EX016四事件循环块区间退化，无有效区间证据。",
        ),
        (
            "N05_PEER_ABSORPTION",
            15,
            "peer_lag_absorbed",
            "同类价格落后后吸收的机制反证",
            "INEFFECTIVE",
            "5日匹配与OLS增量均负；成交子集净收益不能代替因果预测或相对真值。",
        ),
        (
            "N06_INTRADAY_SHAPE_CENSUS",
            15,
            "shock_time_low",
            "日内顺序、趋势效率与tsfresh形态的广泛对照",
            "INSUFFICIENT_DATA",
            "所有48信号完整台账；多数匹配增量负，tsfresh形态未支持独立收益；主方向q全1。代表时点统计仅为入口，完整族见协议及台账。",
        ),
        (
            "N07_ACTUAL_VWAP_DISCOUNT",
            16,
            "actual_vwap_low",
            "收盘低于实际成交重心的修复假设",
            "INEFFECTIVE",
            "278事件，5日净均值-0.0033%、匹配增量-0.3588%；8实际VWAP方向已测，不能把低于均价自动视为便宜。",
        ),
        (
            "N08_NORMAL_PRICING_STATE",
            17,
            "actual_vwap_mid",
            "正常定价状态的候选用途",
            "INSUFFICIENT_DATA",
            "538事件绝对均值正，但匹配和OLS增量负；不能单独作为有收益增量的机会。",
        ),
        (
            "N09_NORMAL_PRICING_MOMENTUM",
            17,
            "mid_momentum_positive",
            "正常定价下短期上涨的条件性机会候选",
            "SUPPORTED",
            "298事件，5日净0.4956%、匹配增量0.1396%、OLS0.1705%；限价2.658次/60日。支持开发池条件线索；q=0.407、双倍费用/延迟转负，账户目标未验证。",
        ),
        (
            "N10_O01_MID_FILTER",
            17,
            "o01_mid",
            "O01正常定价过滤的竞争解释",
            "INEFFECTIVE",
            "O01从79事件缩为35，5日净0.0086%、匹配增量-0.4275%；当前不建议将中段机械叠加于O01。",
        ),
    )
    for cid, i, name, role, status, judgment in specs:
        eid = f"EX{i:03d}_20261005"
        main = next(
            r
            for r in rows[i]
            if r["signal"] == name
            and r["horizon"] == 5
            and r["delay"] == 0
            and r["fee"] == 0.001
            and r["sensitivity"] == "all"
        )
        evidence = (
            experiment_evidence(root, eid, "opportunities.json"),
            experiment_evidence(root, eid, "annual.json"),
            experiment_evidence(root, eid, "multiplicity.json"),
        )
        ids = []
        for field, unit in (
            ("events", "count"),
            ("net_mean", "fraction"),
            ("increment", "fraction"),
            ("price_volume_control_increment", "fraction"),
            ("limit_per60", "events_per_60_sessions"),
            ("limit_net", "fraction"),
        ):
            factid = cid + "__" + field
            value = main[field]
            ids.append(factid)
            facts.append(
                FactValue(
                    factid,
                    value,
                    unit,
                    FactStatus.AVAILABLE if value is not None else FactStatus.INSUFFICIENT_DATA,
                    (evidence[0],),
                    None if value is not None else "无可评价事件",
                )
            )
        test = ComponentTestResult(
            cid + "_EVIDENCE",
            eid,
            protocols[i],
            ComponentTestStatus(status),
            judgment,
            evidence,
            tuple(ids),
        )
        entries.append(
            ComponentEntry(
                cid,
                definitions[i],
                role,
                "T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证",
                "5日主标签；完整主及敏感性见协议",
                "年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照",
                "T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证",
                "不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例",
                "518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明",
                judgment,
                (test,),
            )
        )
    coverage = attachment(
        base + "research_coverage.json", "coverage_reference.json", "application/json"
    )
    files.append(coverage)
    for name, value in (
        ("new_diagnostic_paths", 1752),
        ("new_unique_signal_definitions", 64),
        ("new_experiments", 3),
    ):
        facts.append(FactValue(name, value, "count", FactStatus.AVAILABLE, (coverage.reference,)))
    confirmation = read("EX017_20261005", "confirmation.json")
    union = next(
        r for r in confirmation["unions"] if r["signals"] == ["o01", "mid_momentum_positive"]
    )
    evidence = experiment_evidence(root, "EX017_20261005", "confirmation.json")
    facts.extend(
        (
            FactValue(
                "o01_normal_union_capacity60",
                union["limit_per60"],
                "events_per_60_sessions",
                FactStatus.AVAILABLE,
                (evidence,),
            ),
            FactValue(
                "o01_normal_union_limit_net",
                union["limit_net"],
                "fraction",
                FactStatus.AVAILABLE,
                (evidence,),
            ),
        )
    )
    return ConsolidatedStageTwoDelivery(
        root,
        owner="EX017_20261005",
        current_experiments=("EX015_20261005", "EX016_20261005", "EX017_20261005"),
        new_components=tuple(entries),
        new_facts=tuple(facts),
        current_attachments=tuple(files),
        conclusion="本轮阶段二汇总交付完成：延续三风险/状态组件及O01，新增正常定价下短期上涨的条件性机会候选；所有弱、无效及重复信息留证。收益与机会密度仍不足以证明账户三个目标，下一阶段需用户批准。",
        current_protocol=protocols[17],
        current_report=report.reference,
        extra_explanations=(
            Explanation(
                ExplanationKind.RESEARCH_JUDGMENT,
                "N09支持条件性开发线索，不意味着已确认独立Alpha；所有区间、q和年度切片仍属已见开发池。",
                supporting=(report.reference,),
            ),
            Explanation(
                ExplanationKind.RESEARCH_JUDGMENT,
                "全部前驱保留；EX015真实VWAP覆盖描述由EX016承接纠正；EX016稀疏四事件区间不可解释，EX017少于6事件显式不报区间。",
                supporting=(report.reference,),
            ),
            Explanation(
                ExplanationKind.RESEARCH_JUDGMENT,
                "历史三风险指标未本轮重算；技术FULL与研究员COMPLETE分别表示核验及交付完整度，不代表收益或账户达标。",
                supporting=(report.reference,),
            ),
        ),
    )
