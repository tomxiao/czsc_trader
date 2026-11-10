# S019 研究交接

阶段一接续入口为[研究约定审阅稿](materials/stage1_agreement.md)。中心目标已确认，新增稳健性建议和阶段二推进待审阅。

## 当前身份

- 策略族：`S019 / MU独立多周期只做多择时研究`；
- 初始范围：`["US.MU"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "stage": "STAGE_ONE",
  "stage_one_status": "DRAFT_PENDING_REVIEW",
  "objective": "独立经济假设；中心净年化收益至少55%，净卡玛至少5；达标后优先提高净年化。",
  "confirmed_center_targets": {
    "net_annual_return_min": 0.55,
    "net_calmar_min": 5.0,
    "drawdown_max": 0.25,
    "drawdown_buyhold_multiplier_max": 0.8,
    "frequency_window_sessions": 60,
    "frequency_median_min": 6,
    "frequency_coverage_min_cycles": 3,
    "frequency_coverage_min_fraction": 0.9
  },
  "decision_interval": {
    "minimum": "30m",
    "maximum": "daily"
  },
  "branch": "codex/mu-independent-research",
  "reference_release": {
    "strategy_version": "S018-v1",
    "runtime_candidate": "C9397",
    "release_hash": "80a7ca699f5814ad3e9162de1828d9848b5a0e7077857eb92002aec10c3f631e"
  },
  "prior_sample_exposure": "2022为S018已用预热；2023-01-03至2026-10-30为反复使用开发池；2026-11-06存在决策视觉预览记录。",
  "authorization_source": "当前会话用户明确提出独立研究，确认55%与卡玛5及默认回撤/频率，并指示新开研究分支，然后继续。",
  "next_action": "完成阶段一草案审阅，确认自定义稳健性、数据及样本安排后申请阶段二推进。"
}
```

研究意图是可演化的人类语义。阶段目标和推进由用户确认；完成技术检验并取得用户对冻结计划的明确批准后，通过TDR公共冻结接口发布策略版本。
