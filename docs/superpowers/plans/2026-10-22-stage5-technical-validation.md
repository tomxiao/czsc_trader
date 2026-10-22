# 阶段五技术检验实施与聚焦验证

实施分支：`codex/stage5-technical-validation`。
依据：[已批准公共契约](../specs/2026-10-22-stage5-public-contracts.md)。

## 交付行为

- 目标A：同一输入实际执行候选与最终格式发布版本，比较信号、决策、委托、成交和经济账本；原回测作为显式可选基准。
- 目标B：共享SRT包认证后，在隔离PTE环境实际运行准备、决策、订单、账户记账和恢复；外部渠道使用明确的离线累计成交模型。
- 检验构造最终版本记录及发布包，冻结复制已经检验的字节；冻结批准绑定精确报告和计划。
- 阶段五不读取前序研究档案，不审计搜索过程。发布、交付验证和冻结只复核保存的显式技术事实，不重新启动策略或PTE。
- 运行控制提供总预算、取消、进度和有限进程终止；保留已完成检查，已发布且已静止的成功、失败及取消运行均清理受管临时根。
- 技术数据库记录`INSPECTION`准入；普通PTE入口拒绝测试数据库。正式版本schema5和发布manifest schema1保持既有格式。

## 接口与旧链路

TDR公共入口为`describe_inspection_environment`、`inspect_candidate`、`record_research_decision`、
`freeze_candidate`和`get_freeze_result`。新请求显式声明输入`data_kind`，不以平台猜测替代数据来源。

选型、计划和检验报告使用schema2；INSPECTION交付使用schema9，阶段一至四继续使用schema8。
旧八项检查、旧`InspectionCheck`类型、旧`InspectionReplay`构造契约及检验对ASSESSMENT/历史研究证据的递归依赖已移除。
旧INSPECTION/schema8仅提供有明确限制的历史概览元数据，完整验证返回`UNSUPPORTED_LEGACY_INSPECTION`。
研究证据及历史冻结原件不重写、不重签。

路径、类型与错误语义见[TDR](../../../src/czsc_trader/README.md)、
[SM](../../../packages/strategy_manager/README.md)、[SRT](../../../packages/strategy_runtime/README.md)、
[PTE](../../../packages/paper_trading_engine/README.md)及公共契约。

## 验证记录

命令均使用仓库`.venv/Scripts/python.exe -m pytest -c pyproject.toml`，临时资产位于`.tmp/`。
涉及真实子进程的用例使用允许Windows管道的执行环境；外部数据和券商渠道均离线。
下表是不同风险范围的执行记录，不应把重复运行的数量相加作为独立用例总数。

| 风险范围 | 聚焦文件 | 结果 |
| --- | --- | --- |
| 请求/协议、输入身份、连续与离散数值、包认证、隔离准入 | `test_stage5_input_comparison_boundaries.py`、SM `test_inspection_v2_contracts.py`、SRT `test_inspection_package.py`、PTE `test_inspection_contracts.py`（控制扩展前） | 32 PASS |
| 保存的PTE证据不可伪造覆盖、检查点、恢复或故障结论 | `test_stage5_pte_evidence.py` | 9 PASS |
| 原运行绑定和冻结事务 | SRT `test_runtime_binding_authentication.py`、`test_runtime_binding_and_execution_plan.py`、SM `test_freeze_transactions.py`、`test_frozen_source_imports.py` | 28 PASS；13个实际发布验收节点按默认标记排除 |
| 原迁移及治理 | `test_runtime_migration.py`、`test_frozen_migration_governance.py` | 65 PASS |
| 交付、历史格式概览及元数据 | `test_research_delivery.py`、`test_delivery_graph_validation.py`、`test_research_overview.py`、`test_stage5_delivery_metadata.py` | 49 PASS；补充跨批次防护后，最后一文件10 PASS |
| 原PTE交易周期 | PTE `test_trading_cycle.py` | 23 PASS |
| PTE控制与隔离边界 | PTE `test_inspection_contracts.py` | 11 PASS，包含真实子进程取消、超时、回调异常及有限终止 |
| TDR控制、留证及清理 | `test_stage5_execution_control.py`、`test_stage5_failure_publication.py` | 最后修正后11 PASS，15.74秒 |
| 真实主链、冻结、价格单位及正式账户绑定 | `test_candidate_freeze.py`、`test_current_contracts.py`、`test_market_replay_integration.py::test_hfq_candidate_inspection_preserves_units_in_prospective_frozen_replay`、PTE `test_account_binding.py` | 最终组33 PASS，182.68秒；11 deselected，其中5个节点前轮已通过，6个实际发布验收节点按默认标记排除 |

真实集成用例还覆盖：移除前序档案后的检验/交付/冻结、精确字节提交和幂等查询、损坏源码/载荷、
独立PTE预期不符、候选/发布环境差异产生不同信号、可选基准、用户决定不可变、重复检验、HFQ价格单位及正式账户绑定。
已修改Python文件的Ruff检查及`git diff --check`均通过。

最终集成组使用以下选择条件，避免重复运行前轮已通过的5个节点：

```text
-k "not test_no_research_archives_needed and not test_stage_five_delivery_publishes and not test_damaged_candidate and not test_wrong_pte_expectation"
```

最终TDR收尾验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -c pyproject.toml tests/functional/test_stage5_execution_control.py tests/functional/test_stage5_failure_publication.py -q --tb=short
```

## 验收范围

本次为DEV软件聚焦验证，不是S015/C0031的新研究检验，不改变其候选资格、历史交付、冻结版本或PTE状态。
合成场景的测试耗时不代表S015实际输入的检验耗时。未执行仓库级全量回归、合并master、打tag、推送或生产变更。

下一步由RSCH使用新实验、新协议及新INSPECTION修订执行C0031技术检验；精确冻结批准、正式部署和账户启用分别处理。
