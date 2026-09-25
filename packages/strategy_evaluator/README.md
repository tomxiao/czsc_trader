# 策略评估器（Strategy Evaluator，SE）

本文面向策略研究员（RSCH）和首席投资官（CIO）。平台实现、安装及包级验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

SE是确定性、渠道无关的数值评估包。它接收结构化候选、收益序列、交易账本和评价策略，输出
可复现的筛选、排名与稳健性数值证据。SE没有语义理解能力，也不读取仓库、加载行情、运行策略、
管理StrategyFamily/SGC/StrategyVersion或连接PTE。

## 如何使用评价证据

RSCH优先通过TDR的`research evaluate`及`czsc_trader.research_tools.evaluate_strategy`取得
同一SRT/TXE账户口径的研究评价，再用SE数值结果解释候选差异；CIO通过`candidate evaluate`
独立体检。直接调用SE纯函数适用于已经持有合格输入账本的分析，不负责补齐数据和执行事实。

SE公开的纯函数链为`validate_protocol`→`screen_candidates`→`rank_candidates`→
`finalize_evaluation`→`render_summary`。筛选只执行评价协议中已声明的硬目标；卡玛、盈亏比、
稳健性统计等未被协议明确指定为门槛时只能用于观察或诊断。

在筛选和排名后，SE可对TDR提供的事实执行PBO、DSR、绝对及配对区块Bootstrap、参数邻域、
成本压力和外部复现等确定性计算。`FAVORABLE`、`MIXED`、`WEAK`、`ADVERSE`是数值证据标签，
不等于人工投资判断或正式冻结裁决。

完整冻结体检由TDR依据EvaluationMandate组织：TDR指定评价窗口并调用SRT准备和认证策略数据，
再核验TXE成交账本、证据身份、SRT运行时、监测方案及所有必需审计项，并把SE的数值结果纳入
AdjudicationReport。

评价协议由 TDR 根据已批准的研究协议和 `EvaluationMandate` 显式传入。SE 只执行协议中声明的
硬门槛；PBO、DSR、Bootstrap、参数邻域和成本压力等结果在未被协议指定为门槛时属于诊断证据，
不能自行升级为冻结否决条件。

数值标签和完整账户目标应一同阅读；若缺少交易账本、成本情景或封存数据，SE输出不能证明
候选达到冻结资格。
