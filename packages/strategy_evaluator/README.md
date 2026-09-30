# 策略评估器（Strategy Evaluator，SE）

本文面向策略研究员（RSCH）。平台实现、安装及包级验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

新研究流程按[RSCH契约](../../research/RSCH_AGENT.md)执行。下文涉及CIO、`candidate evaluate`及EvaluationMandate的冻结体检描述保留为旧治理实现参考，不构成新流程授权；新冻结能力仍待CAP-07增强。

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

## `pareto_layers`：输入适配

先阅读[公共导出](src/strategy_evaluator/__init__.py)，核对`CandidateProfile`和[分层实现](src/strategy_evaluator/pareto.py)。函数按`worst_scores`执行各指标越大越好的帕累托分层，返回带`pareto_layer`的配置；不自带研究目标核验、层内排序或缺失值政策。

| 检查 | 调用方要求 |
| --- | --- |
| 指标集合 | 每个配置的指标键必须一致；当前实现按双方键的交集比较 |
| 数值 | 参与分层的数值必须有限 |
| 方向 | 越大越好；收益／回撤双指标分层传入净年化及负的最大回撤幅度 |
| 缺失 | 影响比较的缺失值标记不可比，不填零或静默丢弃指标 |
| 政策 | 研究目标核验及层内排序由调用方按已冻结协议执行 |

最小适配测试应覆盖指标键不一致、非有限值、完全并列及已知支配关系。工具分层结果不替代研究员解释或用户选型。
