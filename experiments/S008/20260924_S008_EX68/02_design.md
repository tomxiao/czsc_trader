# S008 EX68 设计

## 固定前序

- 前序实验：`20260924_S008_EX67`
- 前序receipt：`b5677eb58d844166dd8e255a4afa04e9c07569ab3b613b54a360da6af784056b`
- 加载入口：`research_experiment.load_experiment_input`

## 唯一修正

结果归档改用平台`build_experiment_manifest`和`validate_experiment_archive`，manifest明确声明：

- `strategy_id=S008`
- `symbol=518880.SH`
- `development_cutoff=2024-12-31`
- `credential_id=SGC-S008-001`

## 裁决

前序receipt、前序决策和关键事实完全匹配，且新档案通过平台验证时，裁决
`PROCEED_TO_UPSIDE_PARTICIPATION_INFORMATION_AUDIT`；任何不一致均立即失败。
