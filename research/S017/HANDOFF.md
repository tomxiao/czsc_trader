# S017 研究交接

## 当前进展（2026-10-28，RSCH）

本轮阶段二已完成，策略达标目标未达成。10个配置包含1个买入持有控制和9个择时配置，正式评价请求10份、实际账户回放20条（每份包含策略及基准）、公共损益诊断12组；重复基准不计独立发现。未形成值得进入阶段三的完整原型，停止当前趋势、回落及均价缓冲表达，不继续加密本组参数。

- [最新阶段二报告](deliveries/PROTOTYPES/2/report.md)、[回执](deliveries/PROTOTYPES/2/receipt.json)、[发布校验](experiments/EX003_20261028/others/publication.json)：FULL关联证据及实验报告发布校验均PASS。
- [首轮报告](deliveries/PROTOTYPES/1/report.md)保留原有判断和追加缓冲对照依据；最新修订显式承接，不改写旧版。
- [首轮事前协议](experiments/EX002_20261028/protocols/design.md)、[分析](experiments/EX002_20261028/others/analysis.json)、[信号核对](experiments/EX002_20261028/others/signal_audit.json)。
- [缓冲补证事前协议](experiments/EX003_20261028/protocols/design.md)、[分析](experiments/EX003_20261028/others/analysis.json)、[净值与回撤图](experiments/EX003_20261028/others/equity_drawdown.png)。
- [阶段一确认完成](deliveries/MANDATE/3/report.md)、[本轮授权依据](experiments/EX002_20261028/protocols/authorization.md)。MANDATE/1、MANDATE/2及EX001历史证据保持不变。

买入持有净年化36.32%、最大回撤67.34%。本次目标要求净年化至少54.48%（正基准的1.5倍），回撤同时不高于基准的80%和25%，滚动60交易日闭合次数中位数至少6且至少90%窗口有3笔。
择时中净年化最高的C0013为26.22%、回撤58.77%、60日中位数2；回撤最小的C0006仍有51.29%、净年化-0.84%。缓冲降低费用，但收益、回撤及频率没有同时改善，不能用局部组件效果替代策略成立。

预热2018-11-01至2018-12-31（40日、508根）；开发池2019-01-02至2025-12-31（1760日、22790根）。单边0.1%费用、固定1%买入限价溢价、只做多不加杠杆；5根已知中断K线按整段不成交。2026-01-02至2026-10-27保留，本轮未读取或评价。2025已纳入开发选择历史，不能称为独立验证；EX003也不是独立验证。

每侧0.2%费用压力、正式参数邻域、统计选择偏差量化及2026验证均未执行，不标通过。技术PASS表示材料、身份及计算证据可核验，不表示经济目标达标或适合部署。没有登记候选、冻结版本或PTE账户。

研究分支为`codex/s017-research`。本轮只修改S017研究材料、注册意图和研究导航，未修改平台或A股实现。正式数据、账户及依赖资产位于批次assets，被Git忽略；交接和备份必须同时保留资产，仅复制Git仓库不能恢复研究证据。

下一步建议：在阶段二先将高回撤期损益区分为隔夜跳空、常规时段下跌和退出再入场损耗，再判断是否存在可由当时信息识别的风险退出/再入场机制。当前交付建议停止本组规则，由用户决定是否继续这个新方向或结束本轮；阶段三、2026保留样本、冻结、PTE及生产操作均未获本轮授权。

## 初始注册快照（历史记录，不代表当前准备状态）

## 当前身份

- 策略族：`S017 / LITE美股个股30分钟只做多择时研究`；
- 初始范围：`["US.LITE"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "objective": "LITE 美股个股30分钟只做多择时研究",
  "instrument": {
    "market": "US",
    "asset_class": "STOCK",
    "symbol": "LITE",
    "currency": "USD"
  },
  "confirmed_direction": {
    "position": "LONG_ONLY",
    "leverage": false,
    "decision_frequency": "30m",
    "session": "RTH",
    "timezone": "America/New_York"
  },
  "stage": "STAGE_1_MANDATE",
  "authorization": {
    "date": "2026-10-28",
    "user_statement": "同意，请注册为S017",
    "scope": "注册LITE新研究批次，开展阶段一目标、执行假设、基准及样本边界约定",
    "mechanism_research_authorized": false,
    "parameter_search_authorized": false,
    "freeze_or_deployment_authorized": false
  },
  "data_readiness": {
    "status": "READY_UNDER_EXPLICIT_RESEARCH_ASSUMPTIONS",
    "checked_window": [
      "2018-11-01",
      "2026-10-27"
    ],
    "sessions": 2006,
    "bars": 25976,
    "missing_bars": 0,
    "zero_volume_bars": 0,
    "known_interruption_bars": 5,
    "source_result_sha256": "87efce05be6fbfb32a740b2703a5a1a434368dec5892591054b879f031934955",
    "prior_preparation_reference": {
      "space_id": "f01da8ad-27b2-4839-a866-3639dc0329c6",
      "preparation_id": "c3cb4452-9ab8-4227-9c52-93b100a51c37",
      "manifest_sha256": "50d7af9bb5fc5a6e70c530c657b45efd6c45784ee02d50a72a8e73d1de0b0a64"
    },
    "batch_data_prepared": false,
    "limits": "立项前核验引用不是S017正式数据资产；无空白不证明无短暂停牌；未评价策略或收益。"
  },
  "accepted_gap_assumption": "完整取数后缺失及零量区间不成交、不进入信号历史；沿用最近有效价并标记陈旧；已知中断另外阻断；不称为完整历史停牌事实。",
  "policy_reference": "research/RSCH_AGENT.md#research-policy",
  "market_guidance": "research/guides/US_RESEARCH.md",
  "next_action": "完成阶段一研究约定及开发池选择留证，提交用户确认后进入机制研究。",
  "materials": [
    "research/S017/materials/registration_20261028.md",
    "research/S017/materials/pre_registration_readiness.json"
  ]
}
```

研究意图是可演化的人类语义。阶段目标和推进由用户确认；完成技术检验并取得用户对冻结计划的明确批准后，通过TDR公共冻结接口发布策略版本。
