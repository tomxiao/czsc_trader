# S011 研究交接

## 当前身份

- 策略族：`S011 / 电网设备ETF单标的收益型策略研究（S011）`；
- 初始范围：`["159326.SZ"]`；
- 研究状态：`RESEARCHING`；
- 按用户批准，将阶段四调整为“核心绩效排序＋完整风险画像＋研究员取舍建议”。当前状态仍为`SELF_CHECK_COMPLETE_PENDING_USER_DECISION`；正式入口为[迭代03结构化决策包](stage4/iteration_03/manifest.json)、[阅读视图](stage4/iteration_03/README.md)、[研究建议](stage4/iteration_03/recommendations.json)和[用户决定](stage4/iteration_03/decision.json)。阶段四不设自检硬门、不自动淘汰或晋升。平台修改继续后置。
- 本轮仅重算排序、精度敏感性和行为组展示；完整风险、10/20/40日区块各5000次重抽样及PBO/DSR按哈希沿用[迭代02](stage4/iteration_02/manifest.json)，没有新增参数搜索或均衡联合扰动，未重跑统计抽样。阶段三[结构化输入子包](stage4/iteration_02/stage3_input/manifest.json)、原阶段三[迭代02](stage3/iteration_02/README.md)和EX13—EX27均保持不变。新版以文档快照验证旧合同身份，当前RSCH文档的后继修订不被误报为历史实验变化。
- [配置注册表](configurations.json)仍有666个配置：96个EX14不可比历史配置、570个当前可比配置；36个达标配置对应35组参数、26种标准账户。35个证据完整配置按标准净年化、回撤和双倍成本净年化排序，第一层4个配置、2种行为；`S011-CFG-000193`仍缺少同源码版本成本证据，未排序，不淘汰、不借用其他源码结果。原27/7/1分层作为历史六维口径完整保留。ID及注册表均未改写，`first_reference`继续表示登记来源。
- 第一层收益组为`S011-CFG-000618/000624`，低回撤组为`S011-CFG-000621/000628`；分别以000624/000628作阅读代表，年化49.8061%/43.1067%、回撤幅度7.2506%/6.1548%、双倍成本年化42.5468%/36.1726%。组内选择只得到不均匀近邻诊断的有限支持，全部成员仍可选择。原`S011-CFG-000649`现为核心第三层，保留连续性对照，无自动晋升。
- 年化0.1个百分点、回撤0.01个百分点的分辨率有明确经济解释，不代表统计显著性。精细、较细、较粗、分箱平移及分别移除一个收益目标的6种敏感性中，第一层4个ID均不变；后续层级较敏感。11项聚焦测试与[独立排序核验](stage4/iteration_03_verification/ranking.json)通过；两组代表的公共SRT/TXE重放五张账本一致，见[000624](stage4/iteration_03_verification/replay_CFG000624.json)、[000628](stage4/iteration_03_verification/replay_CFG000628.json)。旧[独立统计核验](stage4/iteration_02_verification/statistics.json)保留为继承证据，不宣称本轮新增统计验证。
- 搜索选择风险仍明显：8/10块PBO分别62.8571%/53.5714%，529种非恒定收益行为参与，1种恒定现金行为单列；DSR同时报告588/685次已归档评价口径与相关结构有效次数约3.016。它们不覆盖全部S010/S011机制研究选择，也不表示未来获利/亏损概率。未补做均衡联合扰动、盘口/容量/延迟、跨标的及新组件消融，均在assessment中披露。
- 原`S011-EX15T040`及其[首次交接](stage3/README.md)保留为历史基线；原文件的阶段四建议不替代本轮继续阶段三的用户指令。
- 当前尚未形成阶段五/CIO候选包、冻结版本或PTE账户；研究员未批准任何配置晋升。
- 下一步请用户依据完整多维比较，选择具体配置晋升、要求补充研究或暂不晋升。只有明确批准具体配置后才进入阶段五。平台、prod、合并、tag或推送执行授权均未取得。

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
