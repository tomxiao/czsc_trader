# S017 研究交接

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
