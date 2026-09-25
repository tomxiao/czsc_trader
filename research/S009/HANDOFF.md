# S009 研究交接

## 当前身份

- 策略族：`S009 / 黄金ETF机会参与策略研究`；
- 初始范围：`["518880.SH"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "asset_type": "黄金商品ETF",
  "research_symbol": "518880.SH",
  "portfolio_role": "研究518880.SH单标的策略如何识别并参与可交易机会，同时改善同期BuyHold的回撤",
  "evaluation_objective": {
    "hard_gates": {
      "annualized_return": "候选同口径年化收益 >= BuyHold同口径年化收益 * 1.5",
      "maximum_drawdown": "候选最大回撤幅度 < BuyHold同口径最大回撤幅度"
    },
    "comparison_policy": "候选与BuyHold使用相同标的、评价窗口、初始权益、执行时点和成本口径",
    "observations": {
      "closed_trade_frequency": "观察闭合交易的数量、滚动频率与证据积累速度，不参与机器阻断",
      "calmar_ratio": "观察指标，不参与机器阻断",
      "profit_factor": "观察指标，不参与机器阻断",
      "turnover_and_cost_sensitivity": "观察换手、费用和滑点压力下的表现变化",
      "yearly_consistency": "观察年度和滚动窗口的一致性，不自动作为硬门",
      "market_exposure": "观察持仓暴露及收益对黄金大行情的依赖",
      "upside_capture_and_missed_upside": "拆解已捕获上涨与漏涨",
      "downside_avoidance_and_false_defense": "拆解规避下跌与错误避险",
      "return_concentration": "观察收益是否集中于少数交易、年份或市场状态",
      "statistical_diagnostics": "PBO、DSR、区块Bootstrap和参数邻域仅作为诊断，除非后续由用户或EvaluationMandate明确升级为硬门"
    }
  },
  "prior_evidence_policy": "S008的EX01至EX90及其失败档案均视为已见且不可变的先验研究证据；不得把相同数据、价格规则、多源信息路径或已拒绝参数空间的重复搜索包装成独立验证。新路径必须说明新增机制、新增信息或实质不同的策略结构及其证伪价值",
  "competing_explanation_policy": "每条主假设必须同时登记最强竞争解释、零假设、反转状态和可推翻观察",
  "research_method": "从黄金定价锚、参与者行为和可交易机会出发，依次完成先验知识审计、数据与因果门、低成本证伪、信息增量、原型实现门、完整账户评价、差距诊断和候选判断",
  "first_experiment": "只核验新研究所需数据、因果可用时间、执行数据和身份边界，不读取目标收益、不选择信号或参数",
  "data_source_boundary": "默认优先使用Tushare及当前已授权本地受管数据；引入其他外部数据源前必须取得用户授权",
  "unconfirmed_terms": {
    "position_and_leverage": "做多/空仓、仓位粒度、杠杆和做空边界待确认",
    "execution": "决策时点、成交时点、订单类型、初始资金、基准成本和压力成本待正式实验前冻结",
    "development_and_validation_windows": "开发窗口、密封验证或外部复现边界须在首次读取收益前冻结",
    "minimum_trade_frequency": "闭合交易频率当前仅为观察指标，不设置最低门槛"
  },
  "governance_boundary": "RSCH可在研究区建立实验和候选；冻结、SRT部署、PTE账户及生产操作均需独立授权"
}
```

研究意图是可演化的人类语义。准确评价目标只在候选进入冻结流程时，通过EvaluationMandate正式确定。

## 当前研究进展（2026-09-25）

S009明确按收益型策略主导：核心任务是识别并参与仍可交易的上涨，回撤改善为第二项硬门。正式
组件面板必须至少包含有证据的`OPPORTUNITY`组件；单纯避险、降低仓位或风险过滤不能构成面板成功。

`20260925_S009_EX01`与`EX02`分别因暖机覆盖顺序和运行器随机种子绑定问题封存为技术失败，均未
读取未来收益。`EX03`作为不可变技术后继完成跨市场人民币黄金传导与ETF份额数据门：七项DFLS
请求全部通过，形成2,780行因果面板、2,660行完整样本和21项冻结候选特征，机器裁决为
`PROCEED_TO_PARITY_INFORMATION_AUDIT`。

`20260925_S009_EX04`仅读取截至2024-12-31的已见开发期收益，按2019—2024逐年向前方式检验
21项特征在5/20/60日三个期限相对价格基线的增量，共63项预注册比较。全局BH校正后FDR支持0项、
名义支持0项，只有2项方向稳定：20日的目标未确认超涨属于`RISK_CONTEXT`，不能作为收益组件；
60日的国内传导差虽属`OPPORTUNITY`，但不在冻结的20日主组件期限。20日收益机会路径合格数为0，
机器裁决为`STOP_NO_SUPPORTED_OPPORTUNITY_INFORMATION`。因此当前没有组件面板、策略原型、候选、
冻结版本或PTE账户；2025年以后封存验证区未读取。

继续研究需要新增实质不同的信息来源或策略结构。不得把上述风险线索改名为机会组件，也不得在
已见63条路径上事后改方向、选年份或调门槛。
