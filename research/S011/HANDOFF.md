# S011 研究交接

## 当前身份

- 策略族：`S011 / 电网设备ETF单标的收益型策略研究（S011）`；
- 初始范围：`["159326.SZ"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "asset_type": "境内A股电网设备主题ETF",
  "research_symbol": "159326.SZ",
  "portfolio_role": "单标的收益型择时，与同标的可执行BuyHold比较",
  "research_direction": "优先寻找可交易Alpha；优先研究量价序列及可能影响量价的外围指标。暂停企业基本面调研属于研究建议，不收窄竞争机制和因子枚举。",
  "evaluation_objective": {
    "comparison_policy": "策略与BuyHold使用相同标的、评价窗口、初始权益、执行时点和成本口径",
    "hard_gates": {
      "annualized_return": "完整账户CAGR >= 同期BuyHold CAGR的1.5倍；若BuyHold CAGR <= 0，策略还须CAGR > 0且超额收益 > 0",
      "maximum_drawdown": "完整账户最大回撤幅度严格小于同期BuyHold",
      "closed_trade_frequency": "60 × 完整账户闭合交易笔数 ÷ 完整评价样本交易日数，结果在[4,6]含边界；不按逐个60日窗口判定"
    },
    "execution_defaults": {
      "position": "只做多、不加杠杆；用户可明确覆盖",
      "one_way_cost": "每侧成交额10 bp；用户可明确覆盖",
      "buy_order": "LIMIT；用户可明确覆盖",
      "sell_order": "MARKET；用户可明确覆盖",
      "causality": "T日收盘信息只能驱动之后的可执行订单"
    },
    "observations": "卡玛比率、盈亏比、平均持仓日、收益集中、漏涨、成本占收益和年度表现仅作诊断，未经用户确认不成为硬门"
  },
  "data_source_boundary": "正式实验通过DFLS取得受管数据并记录来源、身份、可得时点与完整性；价格口径遵守RSCH_AGENT.md；新增外部数据源、第三方库或平台能力须另行授权。",
  "prior_evidence_policy": "S010 EX01—EX21及重叠2024—2026行情均属已见开发信息。S010历史假设、组件和结果仅作问题线索与偏差披露，不自动成为S011有效组件、策略证据或独立验证。S010 EX21的分钟数据实际为后复权，预登记未复权合同未满足；新研究须先核对价格口径及下游影响。更早已注销的原S010、原S011档案亦仅作历史已见信息。",
  "initial_gate": "先只读审计S010各实验输入、标签、复权因子与PCF名义金额口径，逐项评估既有证据可用性；在口径与因果时间合同明确、数据门核验通过前，不认定新组件或启动策略原型。",
  "formal_experiment_policy": "S011正式实验从EX01独立编号；首次运行前冻结合同并运行preflight，保留完整不可变结果和失败路径。",
  "governance_boundary": "RSCH可在研究区登记并开展研究；平台治理、候选冻结、SRT部署和PTE/prod操作需要相应角色或独立授权。"
}
```

研究意图是可演化的人类语义。准确评价目标只在候选进入冻结流程时，通过EvaluationMandate正式确定。
