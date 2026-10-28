# S017 研究交接

## 当前进展（2026-10-28，RSCH）

本轮阶段二趋势启动、移动止损及风险保护研究已完成，策略目标未达成。较小初始风险距离带来主要改善，成本线保护有小幅增益；本轮新表达中净年化最高、回撤最低的C0029仍只有20.86%净年化、42.14%最大回撤及60日闭合中位数1，暂不建议进入阶段三。

本轮EX004/EX005共9个新配置（含仅初始止损诊断控制）、9份正式评价、18条实际账户回放及12组公共损益诊断。S017累计19个配置（1个独立买入持有、18个择时表达，含诊断控制）、19份评价、38条回放、24组诊断；重复基准和重叠开发样本不代表独立假设或独立验证。

- [最新结论](deliveries/PROTOTYPES/4/report.md)、[回执](deliveries/PROTOTYPES/4/receipt.json)、[发布校验](experiments/EX005_20261028/others/publication.json)：FULL证据和实验报告发布校验均PASS。
- [趋势与移动止损首组](deliveries/PROTOTYPES/3/report.md)、[事前设计](experiments/EX004_20261028/protocols/design.md)、[分析](experiments/EX004_20261028/others/analysis.json)。
- [初始风险与成本保护补证设计](experiments/EX005_20261028/protocols/design.md)、[分析](experiments/EX005_20261028/others/analysis.json)、[净值回撤图](experiments/EX005_20261028/others/equity_drawdown.png)、[实际止损路径](experiments/EX005_20261028/others/trailing_path.png)。
- [原首轮结论](deliveries/PROTOTYPES/2/report.md)及其前驱保留不变；当前结果不改写旧账户、旧报告或历史资格。
- [研究约定确认](deliveries/MANDATE/3/report.md)、[本轮续研授权](experiments/EX004_20261028/protocols/authorization.md)。

|配置|净年化|30分钟收盘最大回撤|滚动60交易日闭合中位数|
|---|---:|---:|---:|
|C0000|36.32%|67.34%|0|
|C0025|15.64%|55.77%|1|
|C0027|20.41%|43.67%|1|
|C0028|16.09%|55.50%|1|
|C0029|20.86%|42.14%|1|

目标仍为净年化≥正基准1.5倍（本窗口54.48%）、回撤≤基准80%且≤25%、滚动60日闭合中位数≥6并至少90%窗口≥3笔。原型整体建议与局部组件判断分开，不用一项目标的改善抵消其他硬条件。

基本面仅启发价格行为假设，交易条件只读取当时可见价格及真实持仓，无财报、订单、指引或年度开关。固定单边0.1%、1%买入限价溢价，只做多不加杠杆；止损按完成Close确认并在下一执行区间卖出，成本线不保证扣费后保本。

预热2018-11/12，开发2019-01-02—2025-12-31；当前准备23298根含预热，全OBSERVED，5根已知中断，无拆股。2026-01-02—2026-10-27行情与策略绩效未读取；此前行业检索已返回2026公开经营信息，必须保留此已见边界，不能笼统称完全盲验。

正式参数邻域、压力费率、统计选择偏差量化及2026策略验证未执行，不标通过。技术校验不代表经济目标达标；没有登记候选、冻结版本、PTE或生产操作。

当前分支`codex/s017-research`。本轮仅修改S017研究材料、注册意图和研究导航，未改平台或A股实现。正式行情、账户及依赖位于批次assets并被Git忽略，交接和备份须同时保留；仅复制Git不能恢复完整研究证据。

下一步建议：建议下一轮阶段二优先检验价格结构对上涨启动的确认能力，例如突破后回踩守住、低点抬高；保留本轮风险管理作为固定控制。先由用户确认续研方向及长持有与原频率目标的取舍，未确认前不新增账户、不访问2026行情或推进阶段三；原目标保持不变。

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
