# S018 研究交接

## 当前阶段二结论

[EX010](experiments/EX010_20261103/report.md) 仅改变 M022 月初资金流时点效应独立触发且第五日盈利仓位的持有期。新增授权已使用 1/10 轮，历史 8 轮单列。频率和相对回撤通过，净 Calmar 与绝对回撤未达标。保留 C9005 作为结构对照，下一轮检验回撤控制机制。

[EX009](experiments/EX009_20261103/report.md) 完成既有账户归因。累计 8/10 轮，主要相对差距出现在空仓上涨，最大回撤主要来自持仓损失。

[EX008](experiments/EX008_20261103/report.md) 验证三机制合并账户。累计 7/10 轮，双频率通过，经济与回撤失败。

[EX007](experiments/EX007_20261103/report.md) 完成三机制重合复核。累计 6/10 轮。机会密度值得进行一个固定规则账户检验，回撤与Calmar仍需由账户核验。

[EX006](experiments/EX006_20261103/report.md) 新增 M007–M024 的固定普查。当前累计 5/10 轮，完整索引包含 24 种机制。

[PROTOTYPES/2](deliveries/PROTOTYPES/2/report.md) 已发布并通过完整校验。已用 4/10 轮，按[机制索引](materials/mechanism_index.json)统一编号加中文全称。六机制扩展普查完成，保留稀少线索及负证，当前无阶段三推荐。

## 当前阶段一约定

[MANDATE/3](deliveries/MANDATE/3/report.md) 已完整发布并通过校验。阶段一完成，下一步等待阶段二授权开展日线收益持续能力普查。以下初始记录保留各自历史时点。

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
