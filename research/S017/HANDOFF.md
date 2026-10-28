# S017 研究交接

## 当前进展（2026-10-28，RSCH）

阶段一材料及S017批次数据准备完成，正式交付`MANDATE/1`的FULL校验、实验报告发布校验均PASS；**等待用户确认执行与评价提案并批准阶段二**。
没有运行策略、收益计算、因子筛选或参数搜索，没有候选、冻结版本或PTE账户。

- [阶段一正式报告](deliveries/MANDATE/1/report.md)、[回执](deliveries/MANDATE/1/receipt.json)
- [完整协议](experiments/EX001_20261028/protocols/mandate.md)、[强类型合同](experiments/EX001_20261028/protocols/contract.json)
- [数据准备引用](experiments/EX001_20261028/others/data_preparation.json)、[发布与校验结果](experiments/EX001_20261028/others/publication.json)

交付内容哈希：`aac6941864710f035420f457c2c88690095cb251abe97097b88c61193121f37c`。
新提案保持PROPOSED，技术PASS不代表用户批准。原始注册凭据和历史发布证据不改写。

预热2018-11-01至2018-12-31（40日、508根）；开发池2019-01-02至2024-12-31（1510日、19558根）；缺失及零量均0，5根已知中断K线按整段不成交。
2025-01-02至2026-10-27保留，本阶段不读取、不评价；此前覆盖核验已见信息见协议。
正式数据已通过公共入口准备到`assets/data/`，不复用注册前临时空间引用。批次资产和机器证据被Git忽略，接续与备份必须保留资产，只有Git文档无法恢复行情。

待确认提案：100000美元、固定1%买入溢价、下一段市价卖出、每侧0.1%费用（压力0.2%）、额外滑点0、1股/0.01美元步长、卖出款即时可用研究假设、BAR_CLOSE回撤验收，以及完整沿用指南的经济、双频率和稳健性条件。
下一步请用户确认协议并批准阶段二；获准后先形成机制及竞争解释、事前对照、期限和停止条件，再运行开发池实验。保留样本、冻结、PTE和生产操作须另行授权。
本轮在master完成阶段一材料和数据准备；新的重量级机制研究开始前按仓库规则确认是否新开研究分支。

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
