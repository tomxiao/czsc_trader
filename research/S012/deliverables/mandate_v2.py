"""S012 mandate incorporating confirmed economic targets and availability evidence."""

from hashlib import sha256
import json
from pathlib import Path

from strategy_evaluator import BenchmarkBound, ConstantBound, ResearchMetric, ResearchTarget
from czsc_trader.research_tools import (
    BenchmarkRequirement, ConfirmationRecord, ConfirmationStatus, DeliveryContent,
    DeliveryDefinition, DeliveryReference, DeliveryStage, DeliveryStatus,
    EvaluationBenchmark, EvidenceFile, EvidenceRef, Explanation, ExplanationKind,
    FactStatus, FactValue, MandateItem, MandateItemKind, MandateOwner,
    NextOpenBuyHold, NumericRequirement, PerformanceRequirement, ReproductionSpec,
    ResearchDeliverable, ResearchMandate,
)


class S012MandateV2(ResearchDeliverable[ResearchMandate]):
    def __init__(self, repository_root: Path):
        self.root = repository_root

    @property
    def definition(self) -> DeliveryDefinition:
        previous = json.loads((self.root / "research/S012/materials/mandate_v1_validation.json").read_text(encoding="utf-8"))
        return DeliveryDefinition(
            MandateOwner("S012"), DeliveryStage.MANDATE, 2,
            predecessors=(DeliveryReference.from_dict(previous["reference"]),),
        )

    def build(self) -> DeliveryContent[ResearchMandate]:
        def attachment(relative):
            path = f"research/S012/{relative}"
            return EvidenceFile(path, EvidenceRef(
                f"attachments/{relative}", sha256((self.root / path).read_bytes()).hexdigest(),
                "application/json" if path.endswith(".json") else "text/x-python",
            ))

        authorization = attachment("materials/stage1_start_authorization.json")
        answers = attachment("materials/user_confirmation_20261004_01.json")
        dates = attachment("materials/user_confirmation_20261004_02.json")
        coverage = attachment("materials/data_coverage_v1.json")
        checker = attachment("deliverables/check_data_coverage.py")
        implementation = attachment("deliverables/mandate_v2.py")
        defaults = attachment("materials/research_defaults.json")
        initial = ConfirmationRecord(ConfirmationStatus.CONFIRMED, authorization.reference)
        confirmed = ConfirmationRecord(ConfirmationStatus.CONFIRMED, answers.reference)
        dates_confirmed = ConfirmationRecord(ConfirmationStatus.CONFIRMED, dates.reference)
        proposed = ConfirmationRecord(ConfirmationStatus.PROPOSED)
        targets = (
            ResearchTarget("net_annual_return", ResearchMetric.NET_ANNUAL_RETURN,
                           lower=BenchmarkBound(1.5, True)),
            ResearchTarget("drawdown", ResearchMetric.DRAWDOWN_MAGNITUDE,
                           upper=BenchmarkBound(1.0, False)),
            ResearchTarget("frequency", ResearchMetric.FULL_SAMPLE_FREQUENCY,
                           lower=ConstantBound(5.0, True)),
        )
        items = (
            MandateItem("tradable_symbol", MandateItemKind.TRADABLE_SYMBOL, "S012研究518850.SH。", initial),
            MandateItem("stage_scope", MandateItemKind.CONSTRAINT, "注册S012并开展阶段一任务与评价合同确认。", initial),
            MandateItem("success_targets", MandateItemKind.OBJECTIVE,
                        "三项同时满足：扣除成本后净年化收益≥BuyHold净年化收益×1.5；最大回撤幅度严格小于BuyHold；全区间闭合交易总数×60÷评价交易日数≥5。", confirmed,
                        PerformanceRequirement(targets)),
            MandateItem("frequency_window", MandateItemKind.HORIZON,
                        "交易频率以60个交易日折算平均值；未闭合持仓不计数。", confirmed,
                        NumericRequirement("frequency_window_days", "trading_days", 60.0, 60.0)),
            MandateItem("history_policy", MandateItemKind.HORIZON,
                        "使用全部可用历史；核验覆盖后由用户确认具体起止日期。", confirmed),
            MandateItem("evaluation_dates", MandateItemKind.HORIZON,
                        "评价范围：2020-06-05至2026-09-30，共1535个交易日；组件预热减少起始区间时须披露，策略与基准采用相同实际评价区间。", dates_confirmed),
            MandateItem("benchmark_policy", MandateItemKind.EXECUTION,
                        "以518850.SH买入持有为可投资基准，在评价首个可成交日开盘买入并持有。", confirmed),
            MandateItem("benchmark", MandateItemKind.BENCHMARK,
                        "建议完整基准执行合同为NextOpenBuyHold(lot_size=100)；尽量满仓买入并预留买入成本，保留余款，期末按市值评价。100份交易单位及资金待确认。", proposed,
                        BenchmarkRequirement(EvaluationBenchmark(NextOpenBuyHold(100)))),
            MandateItem("trading_rules", MandateItemKind.EXECUTION,
                        "单标的择时、只做多、不加杠杆、每侧成交额0.1%成本、限价买入、市价卖出。", confirmed),
            MandateItem("initial_capital", MandateItemKind.EXECUTION,
                        "建议策略与BuyHold初始资金均为100000元，交易单位100份。", proposed,
                        NumericRequirement("initial_capital", "CNY", 100000.0, 100000.0)),
            MandateItem("execution_details", MandateItemKind.EXECUTION,
                        "建议决策周期、限价公式、订单有效期及仓位规则由研究确定，每次实验前显式声明；新增或改变已确认约束仍须用户批准。", proposed),
            MandateItem("research_scope", MandateItemKind.OBJECTIVE,
                        "建议围绕黄金ETF收益和风险机制检验竞争解释；三个成功标准共同约束，不增设其他经济硬门。", proposed),
            MandateItem("data_scope", MandateItemKind.DATA_PERMISSION,
                        "建议使用既有获授权DFLS/Tushare数据和公开文献；全部已查看历史属于开发池。新增外部数据源或依赖另行申请。", proposed),
            MandateItem("resources", MandateItemKind.RESOURCE,
                        "建议沿用RSCH默认本机半核并发预算；阶段一仅核验可用性，不筛选因子或搜索参数。", proposed),
        )
        facts = (
            FactValue("confirmed_target_count", 3, "count", FactStatus.AVAILABLE, (answers.reference,)),
            FactValue("daily_coverage", "2020-06-05/2026-09-30", "date_range", FactStatus.AVAILABLE, (coverage.reference,)),
            FactValue("daily_sessions", 1535, "trading_days", FactStatus.AVAILABLE, (coverage.reference,)),
            FactValue("daily_missing_sessions", 0, "count", FactStatus.AVAILABLE, (coverage.reference,)),
        )
        return DeliveryContent(
            payload=ResearchMandate(items), status=DeliveryStatus.PARTIAL, facts=facts,
            explanations=(
                Explanation(ExplanationKind.FACT, "用户已确认三个经济目标和默认交易口径；资金及完整执行合同继续确认。", ("confirmed_target_count",)),
                Explanation(ExplanationKind.FACT, "DFLS日历、不复权日线及后复权日线均READY；两种价格序列覆盖全部1535个开市日，无缺失、额外或重复日期。", ("daily_coverage", "daily_sessions", "daily_missing_sessions")),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "本次仅核对数据可用性，未计算策略或基准绩效。正式实验必须重新绑定数据身份和实际截止日；本次READY不代表所有研究输入因果可用。", supporting=(coverage.reference,)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "后复权因子的历史发布时间及修订历史未经核实；若用作信号输入，应先核验决策时点可得性。不复权价格用于实际成交与账户估值。", supporting=(coverage.reference,)),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "频率使用平台FULL_SAMPLE_FREQUENCY；滚动窗口中位数及低分位频率仅作诊断。收益目标按用户给定倍数直接计算，未额外添加基准正收益条件。"),
                Explanation(ExplanationKind.RESEARCH_JUDGMENT, "当前会话包含平台开发背景及少量其他研究摘要；未直接读取其他策略批次档案，不将这些背景作为S012证据或复用其机制参数。"),
            ),
            reproduction=ReproductionSpec(
                "调用validate_delivery核验本修订和前驱；核对用户原始回复、数据身份与日历差集。覆盖核验代码再次运行必须使用后继输出，不覆盖既有审计文件。",
                (defaults.reference, checker.reference, implementation.reference),
                "本次通过DFLS公共Dataflows.fetch访问既有Tushare行情和SSE日历，仅保存覆盖与来源元数据；正式研究输入将在受管实验中获取并留证。",
                "合同及附件哈希确定；供应商数据可能修订，后继核验应记录新身份。无绩效计算。",
            ),
            incomplete_items=(
                "用户确认策略与基准初始资金、100份交易单位及基准余款和期末估值方式。",
                "用户确认策略执行细节由研究决定的范围，或指定固定参数。",
                "用户确认研究机制、开发池、数据及资源范围。",
            ),
            attachments=(authorization, answers, dates, coverage, checker, implementation, defaults),
        )
