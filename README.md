# CZSC Trader

CZSC Trader 是面向个人量化团队的可审计策略研发与模拟交易项目。它把受控数据、可复核实验、
策略实现、候选体检、版本冻结、历史执行和前瞻观察连接起来。研究证据、治理裁决与模拟盘事实
分别保存；数据不完整、执行结果未知或批次部分成功不得被解释为整体成功。

项目由 TDR 主应用、九个独立 Python 子包及研究、实验、策略治理目录组成。策略研究员（RSCH）
提出并检验假设、实现候选；首席投资官（CIO）使用平台工具独立体检和裁决。冻结版本部署到 SRT、
创建 PTE 账户和生产写入各有独立授权边界。

## 关键文档

| 目的 | 入口 |
| --- | --- |
| 研究资料与各策略批次 | [研究导航](research/README.md)；具体状态见各策略`HANDOFF.md` |
| RSCH 研究方法、权限和交付 | [研究员 Agent](research/RSCH_AGENT.md) |
| CIO 体检、裁决、冻结和部署 | [首席投资官 Agent](research/CIO_AGENT.md) |
| 候选提交包格式 | [候选包契约](research/CANDIDATE_PACKAGE.md) |
| 不可变实验档案 | [实验档案说明](experiments/README.md) |
| DEV 跨机跨会话恢复、架构、测试与发布 | [开发运维交接](docs/DEVELOPMENT_HANDOFF.md)；[测试治理](docs/TEST_GOVERNANCE.md) |

## 子包使用说明

以下 README 面向 RSCH、CIO，说明各公共能力的适用场景、入口和边界；平台开发、环境恢复、
包级验证与 PTE 运维统一查阅[开发运维交接](docs/DEVELOPMENT_HANDOFF.md)。

| 研究与治理能力 | 执行与观察能力 |
| --- | --- |
| [DFLS：受控数据](packages/dataflows/README.md) | [SRT：策略实现与决策](packages/strategy_runtime/README.md) |
| [FSC：因子和信号定义](packages/factor_signal_catalog/README.md) | [TXE：历史成交与账户](packages/trading_execution_engine/README.md) |
| [STC：策略结构模板](packages/strategy_template_catalog/README.md) | [PTE：前瞻模拟与观察](packages/paper_trading_engine/README.md) |
| [REX：可执行研究实验](packages/research_experiment/README.md) | [SE：数值评价](packages/strategy_evaluator/README.md) |
| [SM：策略身份与治理](packages/strategy_manager/README.md) | — |

`research/`保存研究意图、交接和候选；`experiments/`保存不可变实验；`strategies/`是只由平台工具
写入的治理区。`data/`与`outputs/`中的本地内容不能替代正式证据。运行状态和具体命令以相应
角色说明及平台当前公共入口为准，项目首页不维护版本或账户状态快照。
