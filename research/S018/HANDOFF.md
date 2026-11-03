# S018 研究交接

## 当前阶段一约定

[MANDATE/2](deliveries/MANDATE/2/report.md) 为当前约定，已通过完整校验。剩余工作为交易日历、公司行动及最小日线账户核验。以下初始意图及 MANDATE/1 记录保留立项时状态。

## 当前身份

- 策略族：`S018 / MU美股日线只做多择时研究`；
- 初始范围：`["US.MU"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "objective": "MU 日线只做多择时。以同窗同条件买持为基准改善净 Calmar 和回撤。",
  "development": {
    "start": "2023-01-03",
    "end": "2026-10-30",
    "history_start": "2022-01-03"
  },
  "development_observation_groups": [
    "2023–2024",
    "2025–2026-10-30"
  ],
  "known_user_case": [
    "2025-12",
    "2026-06"
  ],
  "final_validation": {
    "kind": "PROSPECTIVE",
    "sessions": 252,
    "starts_after_rule_and_criteria_fixed": true
  },
  "stage_one_status": "PARTIAL",
  "next_action": "核对公司行动支付时点、交易日历和日线账户，明确自检经济门后完成阶段一。"
}
```

研究意图是可演化的人类语义。阶段目标和推进由用户确认；完成技术检验并取得用户对冻结计划的明确批准后，通过TDR公共冻结接口发布策略版本。

## 阶段一交付

[MANDATE/1](deliveries/MANDATE/1/report.md) 已发布并通过完整校验，研究约定状态为 PARTIAL。待核验正式数据、最小日线账户和阶段四经济门。
