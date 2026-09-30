# 策略管理器（SM）

SM管理策略族、历史冻结版本、生命周期与绩效证据。公共入口见[__init__.py](src/strategy_manager/__init__.py)，研究员使用API，用户回测使用TDR CLI。

## 当前能力

| 能力 | API |
| --- | --- |
| 身份查询 | `StrategyRegistry.list_families/get_family/get_version/versions` |
| 研究登记 | TDR `create_research_batch/update_research_intent`，内部使用SM登记能力 |
| 历史治理验证 | `validate_version_governance`、`validate_all` |
| 证据与生命周期 | `evidence/lifecycle_events/current_qualification`；获准后使用`record_evidence/promote_version/downgrade_version/retire_version` |

旧候选包送审、裁定及冻结写入已删除。`CandidateSnapshot`、`EvaluationMandate`、`AdjudicationReport`不再公开；历史格式解析位于内部只读模块。新冻结能力待CAP-07实现，不提供旧流程回退。

## 不可变存储与权限

- `strategies/SXX/versions/`及`releases/`保存版本身份、源码和文件闭包。
- `credentials/`、`freeze_approvals.jsonl`、`lifecycle.jsonl`及`evidence.jsonl`保留历史治理事实。
- `strategies/deployments/`保存SRT部署凭据，部署API需独立授权。
- `release_hash`及已有证据关联不得静默改变；读验历史记录不授予新的治理决定权。
- 当前历史版本可通过其唯一的治理接纳事件验证，不重写原版本、不重新批准历史冻结。
- SM不计算绩效、不执行回测、不操作PTE账户。平台不能认证研究结论正确。

操作须遵守[RSCH契约](../../research/RSCH_AGENT.md)和[开发安全边界](../../docs/DEVELOPMENT_HANDOFF.md)。
