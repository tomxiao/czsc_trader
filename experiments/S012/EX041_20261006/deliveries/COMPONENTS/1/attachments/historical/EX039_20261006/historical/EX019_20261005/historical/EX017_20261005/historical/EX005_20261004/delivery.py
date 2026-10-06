"""Stage-two panel backed by the complete census and successor robustness evidence."""
import json
from hashlib import sha256
from pathlib import Path
from czsc_trader.research_tools import (
    ComponentDefinitionRef, ComponentEntry, ComponentPanel, ComponentTestResult, ComponentTestStatus,
    DeliveryContent, DeliveryDefinition, DeliveryReference, DeliveryStage, DeliveryStatus,
    EvidenceFile, EvidenceRef, ExperimentDefinitionRef, ExperimentEvidenceRef, ExperimentEvidenceUse,
    ExperimentOwner, Explanation, ExplanationKind, FactStatus, FactValue,
    ReproductionSpec, ResearchDeliverable,
)


class S012Components(ResearchDeliverable[ComponentPanel]):
    def __init__(self, repository_root: Path):
        self.root = repository_root
        self.directory = self.root / "experiments/S012/EX005_20261004"

    def read(self, path):
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    @property
    def definition(self):
        mandate = self.read("research/S012/materials/mandate_v3_validation.json")["reference"]
        refs = []
        for eid in ("EX001_20261004", "EX003_20261004", "EX004_20261004", "EX005_20261004"):
            workspace = f"experiments/S012/{eid}/artifacts/rex"
            receipt = self.read(f"{workspace}/execution_receipt.json")
            use = ExperimentEvidenceUse.CURRENT_EVALUATION if eid in ("EX004_20261004", "EX005_20261004") else ExperimentEvidenceUse.HISTORICAL_REFERENCE
            refs.append(ExperimentEvidenceRef(eid, workspace, receipt["receipt_sha256"], use))
        return DeliveryDefinition(ExperimentOwner("S012", "EX005_20261004"), DeliveryStage.COMPONENTS, 1,
            predecessors=(DeliveryReference.from_dict(mandate),), experiments=tuple(refs))

    def build(self):
        def attached(source, name, media="application/json"):
            return EvidenceFile(source, EvidenceRef(f"attachments/{name}", sha256((self.root/source).read_bytes()).hexdigest(), media))
        attachments = (
            attached("experiments/S012/EX004_20261004/02_design.md", "census_protocol.md", "text/markdown"),
            attached("experiments/S012/EX005_20261004/02_design.md", "robustness_protocol.md", "text/markdown"),
            attached("experiments/S012/EX005_20261004/04_conclusion.md", "research_report.md", "text/markdown"),
            attached("experiments/S012/EX002_20261004/artifacts/rex/execution_failure.json", "EX002_technical_failure.json"),
            attached("experiments/S012/EX003_20261004/artifacts/result.json", "EX003_zero_tests.json"),
            attached("research/S012/materials/stage2_authorization_20261004.json", "stage2_authorization.json"),
            attached("experiments/S012/EX005_20261004/delivery.py", "delivery.py", "text/x-python"),
        )
        def experiment_evidence(eid, path, media="application/json"):
            original = self.root / f"experiments/S012/{eid}/artifacts/rex/{path}"
            return EvidenceRef(f"experiments/{eid}/{path}", sha256(original.read_bytes()).hexdigest(), media)
        census = experiment_evidence("EX004_20261004", "component_metrics.json")
        folds = experiment_evidence("EX004_20261004", "fold_metrics.json")
        robust = experiment_evidence("EX005_20261004", "robustness.json")
        redundant = experiment_evidence("EX005_20261004", "redundancy.json")
        interactions = experiment_evidence("EX005_20261004", "interactions.json")
        source = self.read("experiments/S012/EX004_20261004/artifacts/rex/execution_receipt.json")
        definition = ExperimentDefinitionRef("EX004_20261004", source["definition_sha256"], source["source_sha256"], "analysis.build_features")
        # Status is a research judgment about the declared role, not a user economic gate.
        specifications = (
            ("C01_VOL20", "volatility_20", "风险尺度与仓位/退出输入", "未来3/5/10/20日最大不利价格幅度", "SUPPORTED",
             "控制动量与年份后仍有风险信息；5日IC=0.182、延迟2日=0.160。不能直接推出最优减仓。"),
            ("C02_MOM20", "momentum_20", "上涨后的回撤风险状态", "未来3/5/10/20日最大不利价格幅度", "SUPPORTED",
             "控制波动与年份后仍有风险信息；20日IC=0.226、延迟2日=0.198。强趋势同时可能贡献收益，不机械反向交易。"),
            ("C03_KURT60", "fresh60_return__kurtosis", "冲击集中后的风险/收益状态过滤", "未来10/20日收益及不利价格幅度", "SUPPORTED",
             "20日收益IC=-0.279、普查q=0.047；延迟2日=-0.282，非重叠及留一年方向稳定。较长标签用于状态判断，不限定实际持仓期限。"),
            ("C04_REV1", "reversal_1", "候选短期入场信息", "未来3/5/10日开盘到开盘收益", "INSUFFICIENT_DATA",
             "5日IC=0.064，但普查多重调整q约0.331；可进入受控策略比较，不能宣称独立Alpha成立。"),
            ("C05_MOM3", "momentum_3反向", "候选短期入场信息", "未来3/5/10日开盘到开盘收益", "INSUFFICIENT_DATA",
             "5日IC=-0.089，延迟2日=-0.065；多重调整q约0.371，期限稳定性弱于状态组件。"),
            ("C06_GAP", "opening_gap", "与反转比较的短期信息", "未来3/5/10日收益及3/5日下行风险", "REDUNDANT",
             "与1日反转秩相关约-0.81；5日收益IC延迟2日从-0.061降至-0.007，下行风险方向反转，不叠加为独立核心组件。"),
            ("C07_RANGE", "range_5", "替代风险尺度", "未来3/5/10日不利价格幅度", "REDUNDANT",
             "与20日波动相关约0.68，控制后增量区间跨零，优先使用较简单的20日波动。"),
            ("C08_AUTOCORR", "fresh20_return__autocorrelation__lag_2", "收益自相关的正向延续解释", "未来10/20日收益", "INEFFECTIVE",
             "预设正方向被反证；负方向相关的区间仍跨零，保留全部结果，当前不作为核心组件。"),
            ("C09_MACRO", "real_yield/nominal_yield/fx/vix/shibor各水平与变化", "宏观方向与风险信息", "3/5/10/20日收益及下行风险", "INSUFFICIENT_DATA",
             "当前日频滞后与控制口径下未见明确增量；不能从本轮结果推断经济机制不存在。"),
            ("C10_RELATIVE", "ETF/SGE相对价格、SGE动量、期货基差与曲线", "价格偏离和境内市场状态", "3/5/10/20日收益及下行风险", "INSUFFICIENT_DATA",
             "未纳入核心面板。ETF/现货价格比不是ETF净值溢价，期货不使用换月拼接收益。"),
            ("C11_FLOWS", "shares_level/shares_change_5/shares_change_20", "份额变化与资金流线索", "3/5/10/20日收益及下行风险", "INSUFFICIENT_DATA",
             "年度事件均值存在差异，但控制趋势波动后证据不足；份额变化不等于可交易的即时资金冲击。"),
            ("C12_REMAINDER", "其余价量路径与tsfresh形态定义，完整列名见feature_definitions.json", "广泛普查及去冗余对照", "3/5/10/20日收益及下行风险", "INSUFFICIENT_DATA",
             "完整保留63个特征和504路径；标准差等与原有波动同义的特征不重复计为新证据，其余未形成足够独立增量。"),
        )
        entries = []
        for cid, feature, role, label, status, judgment in specifications:
            tests = [ComponentTestResult(f"{cid}_CENSUS", "EX004_20261004", attachments[0].reference,
                ComponentTestStatus(status), f"{feature}：{judgment}", (census, folds))]
            if cid in {f"C{i:02d}_{suffix}" for i, suffix in ((1,"VOL20"),(2,"MOM20"),(3,"KURT60"),(4,"REV1"),(5,"MOM3"),(6,"GAP"),(7,"RANGE"),(8,"AUTOCORR"))}:
                tests.append(ComponentTestResult(f"{cid}_ROBUSTNESS", "EX005_20261004", attachments[1].reference,
                    ComponentTestStatus(status), judgment, (robust, redundant, interactions)))
            entries.append(ComponentEntry(cid, definition, role, label, "详见标签和各次固定检验；全期开发池",
                "20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。",
                "ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。",
                "ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。",
                "仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。",
                judgment, tuple(tests)))
        facts = (
            FactValue("features", 63, "count", FactStatus.AVAILABLE, (census,)),
            FactValue("census_paths", 504, "count", FactStatus.AVAILABLE, (census,)),
            FactValue("robustness_paths", 96, "count", FactStatus.AVAILABLE, (robust,)),
            FactValue("interaction_cells", 51, "count", FactStatus.AVAILABLE, (interactions,)),
            FactValue("vol20_risk5_ic", 0.181756, "rank_correlation", FactStatus.AVAILABLE, (robust,)),
            FactValue("mom20_risk20_ic", 0.225989, "rank_correlation", FactStatus.AVAILABLE, (robust,)),
            FactValue("kurt60_return20_ic", -0.279206, "rank_correlation", FactStatus.AVAILABLE, (robust,)),
        )
        return DeliveryContent(ComponentPanel(tuple(entries),
            "阶段二完成：交付三个有明确状态/风险职责的核心组件和两项证据较弱的短期入场候选，连同无效、冗余及技术失败记录。详见附件research_report.md。建议获批后进入阶段三检验完整可证伪策略。"),
            DeliveryStatus.COMPLETE, facts,
            (
                Explanation(ExplanationKind.FACT, "普查及复核覆盖63特征、504条主检验、96条复核及51个互补分组。", ("features", "census_paths", "robustness_paths", "interaction_cells")),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "状态组件通过多个方向稳定性诊断；收益方向性仍较弱，用户三个经济目标尚未证明可同时达到。", supporting=(robust,), contrary=(census, interactions)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "低风险过滤与反转简单叠加未稳定改善；高峰度下5日反转在40bp费用压力时平均净事件收益约-0.084%。事件重叠，不是账户收益。", contrary=(interactions,)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "全部年度/留一年/非重叠切片仍属于开发池；后继候选选择来自EX004，区间未修正选择偏差。统计诊断不新增用户经济硬门。"),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "两次技术失败均保留；EX003平台PASS对应零有效检验，未用于有效性判断。", contrary=(attachments[3].reference, attachments[4].reference)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "现有DFLS能力足以完成本阶段，未修改平台。未来策略使用外部字段仍需核验实际可得性；历史来源修订风险保留。"),
            ),
            ReproductionSpec("先校验EX001至EX005档案及当前交付；核对源码绑定、EX004全路径台账和EX005复核。复算须通过后继REX实验沿用固定公式和绑定前驱，禁止覆盖已封存实验。",
                (attachments[0].reference, attachments[1].reference, attachments[6].reference),
                "实际数据经DFLS/Tushare受管取得并保存于artifacts/rex/data；本次复核逐文件校验已绑定前驱。Git忽略原始制品，跨机器恢复须同步完整制品和前驱链。",
                "种子12002/12005；tsfresh固定统计函数；环境版本见绑定及环境记录。研究统计允许机器浮点微小差异，身份哈希严格核验。"),
            attachments=attachments)
