"""S012 stage-one opening mandate; incomplete terms remain proposed."""

from hashlib import sha256
from pathlib import Path

from czsc_trader.research_tools import (
    ConfirmationRecord, ConfirmationStatus, DeliveryContent, DeliveryDefinition,
    DeliveryStage, DeliveryStatus, EvidenceFile, EvidenceRef, Explanation,
    ExplanationKind, FactStatus, FactValue, MandateItem, MandateItemKind,
    MandateOwner, ReproductionSpec, ResearchDeliverable, ResearchMandate,
)


class S012MandateV1(ResearchDeliverable[ResearchMandate]):
    def __init__(self, repository_root: Path):
        self.root = repository_root

    @property
    def definition(self) -> DeliveryDefinition:
        return DeliveryDefinition(MandateOwner("S012"), DeliveryStage.MANDATE, 1)

    def build(self) -> DeliveryContent[ResearchMandate]:
        def attachment(relative: str) -> EvidenceFile:
            path = f"research/S012/{relative}"
            media_type = "application/json" if relative.endswith(".json") else "text/x-python"
            return EvidenceFile(
                path,
                EvidenceRef(
                    f"attachments/{relative}",
                    sha256((self.root / path).read_bytes()).hexdigest(),
                    media_type,
                ),
            )

        authorization = attachment("materials/stage1_start_authorization.json")
        identity = attachment("materials/instrument_identity.json")
        defaults = attachment("materials/research_defaults.json")
        registration = attachment("materials/registration_request.json")
        implementation = attachment("deliverables/mandate_v1.py")
        confirmed = ConfirmationRecord(ConfirmationStatus.CONFIRMED, authorization.reference)
        proposed = ConfirmationRecord(ConfirmationStatus.PROPOSED)
        items = (
            MandateItem("tradable_symbol", MandateItemKind.TRADABLE_SYMBOL,
                        "研究标的518850.SH（华夏黄金ETF）；用户确认代码，交易所身份由官方资料核对。", confirmed),
            MandateItem("stage_scope", MandateItemKind.CONSTRAINT,
                        "注册S012并启动阶段一；当前授权为研究任务与评价合同确认。", confirmed),
            MandateItem("research_question", MandateItemKind.OBJECTIVE,
                        "建议研究黄金ETF择时能否改善用户关心的收益与回撤；优先级和数值成功标准待确认。", proposed),
            MandateItem("evaluation_horizon", MandateItemKind.HORIZON,
                        "建议评价全部可用历史；起止日期、开发池与后续数据边界待确认及覆盖核验。", proposed),
            MandateItem("trading_rules", MandateItemKind.EXECUTION,
                        "沿用角色默认：单标的择时、只做多、不加杠杆、每侧0.1%成本、限价买入、市价卖出；资金、交易单位、成交时点及限价参数待确认。", proposed),
            MandateItem("data_scope", MandateItemKind.DATA_PERMISSION,
                        "建议使用现有获授权DFLS/Tushare数据及公开资料；具体数据集、范围与新增外部数据需求逐项明确。", proposed),
            MandateItem("resources", MandateItemKind.RESOURCE,
                        "建议采用角色默认本机并发预算；正式实验前声明实际资源，阶段一不进行因子筛选或参数搜索。", proposed),
        )
        pending = (
            "明确研究职责、收益与风险优先级，以及机制探索范围。",
            "确认净年化收益、最大回撤和交易频率目标；频率须说明交易日统计窗口和计数方式。",
            "确认评价区间、数据截止日及开发池范围，并核验可用数据覆盖。",
            "确认518850.SH买入持有基准及其资金、交易单位、首次成交时点和执行参数后，加入强类型BenchmarkRequirement。",
            "明确策略限价买入、市价卖出的执行时点、价格参数、资金和交易单位。",
            "确认具体数据权限及资源范围；完成合同后由用户决定是否进入阶段二。",
        )
        facts = (
            FactValue("strategy_id", "S012", "identifier", FactStatus.AVAILABLE,
                      (authorization.reference, registration.reference)),
            FactValue("tradable_symbol", "518850.SH", "symbol", FactStatus.AVAILABLE,
                      (authorization.reference, identity.reference)),
            FactValue("authorized_stage", "MANDATE", "stage", FactStatus.AVAILABLE,
                      (authorization.reference,)),
        )
        explanations = (
            Explanation(ExplanationKind.FACT,
                        "用户已授权注册S012并启动阶段一。当前修订记录立项事实、默认口径和未确定项。",
                        ("strategy_id", "authorized_stage")),
            Explanation(ExplanationKind.FACT,
                        "标的名称与交易所已按上交所公开公告核对，尚未读取收益样本或开展研究实验。",
                        ("tradable_symbol",), (identity.reference,)),
            Explanation(ExplanationKind.RESEARCH_JUDGMENT,
                        "建议以本ETF买入持有作为可投资基准，拟在评价首个可成交日开盘买入；仅为建议，完整执行合同待用户确认。"),
            Explanation(ExplanationKind.RESEARCH_JUDGMENT,
                        "默认行为依据当前RSCH契约；PROPOSED表示S012合同细节尚未逐项确认，不将默认规则或研究诊断转换为额外经济硬门。",
                        supporting=(defaults.reference,)),
            Explanation(ExplanationKind.RESEARCH_JUDGMENT,
                        "当前会话包含平台开发背景、其他策略名称及少量历史研究摘要；本次未直接读取其他策略批次档案。这些背景不作为S012研究证据，不复用其他策略的机制或参数结论。"),
        )
        return DeliveryContent(
            payload=ResearchMandate(items), status=DeliveryStatus.PARTIAL,
            facts=facts, explanations=explanations,
            reproduction=ReproductionSpec(
                "使用公开validate_delivery核验本修订；对照附件中的原始授权、标的身份、默认规则快照和交付实现。后续确认生成新修订，不覆盖本修订。",
                (defaults.reference, implementation.reference),
                "本次仅访问公开标的身份资料和平台合同，未拉取行情或访问生产状态。",
                "文件和合同哈希确定性校验；本修订不含绩效计算。",
            ),
            incomplete_items=pending,
            attachments=(authorization, identity, defaults, registration, implementation),
        )
