# CZSC Trader

CZSC Trader 是面向个人量化团队的可审计策略研发与模拟交易项目。它把受控数据、可复核实验、
策略实现、候选体检、版本冻结、历史执行和前瞻观察连接起来。研究证据、治理裁决与模拟盘事实
分别保存；数据不完整、执行结果未知或批次部分成功不得被解释为整体成功。

项目由 TDR 主应用、九个独立 Python 子包及研究、实验、策略治理目录组成。策略研究员（RSCH）
负责研究、自检、技术检验及获批冻结；用户负责阶段审批、候选选择和冻结决定。平台已提供
候选登记、五阶段交付、自检比较、技术检验、用户决定记录和原子冻结公共API。
候选比较核对实际费用与基准口径，交接时核验候选登记；技术检验可使用已封存评价归档跨会话复算。
正式研究执行通过TDR/REX受管入口；研究员负责搜索空间、Optuna、预算和停止条件。
冻结版本部署到 SRT、创建 PTE 账户和生产写入各有独立授权边界。

## 关键文档

| 目的 | 入口 |
| --- | --- |
| 研究资料与各策略批次 | [研究导航](research/README.md)；具体状态见各策略`HANDOFF.md` |
| RSCH 研究方法、权限和交付 | [研究员 Agent](research/RSCH_AGENT.md) |
| TDR实验、候选评价、回测及证据工具 | [TDR使用说明](src/czsc_trader/README.md) |
| 不可变实验档案 | [实验档案说明](experiments/README.md) |
| DEV 跨机跨会话恢复、架构、测试与发布 | [开发运维交接](docs/DEVELOPMENT_HANDOFF.md)；[测试治理](docs/TEST_GOVERNANCE.md) |

## 子包使用说明

以下 README 面向研究员，说明各公共能力的适用场景、入口和边界。研究与策略发布API只支持各对象的当前契约；
历史证据原件及哈希保留供人工查阅，平台不承诺历史数据机器复验。当前版本及证据要求见TDR说明。平台开发、环境恢复、
包级验证与 PTE 运维统一查阅[开发运维交接](docs/DEVELOPMENT_HANDOFF.md)。

| 研究与治理能力 | 执行与观察能力 |
| --- | --- |
| [DFLS：受控数据](packages/dataflows/README.md) | [SRT：策略实现与决策](packages/strategy_runtime/README.md) |
| [FSC：因子和信号定义](packages/factor_signal_catalog/README.md) | [TXE：历史成交与账户](packages/trading_execution_engine/README.md) |
| [STC：策略结构模板](packages/strategy_template_catalog/README.md) | [PTE：前瞻模拟与观察](packages/paper_trading_engine/README.md) |
| [REX：可执行研究实验](packages/research_experiment/README.md) | [SE：数值评价](packages/strategy_evaluator/README.md) |
| [SM：策略身份与治理](packages/strategy_manager/README.md) | — |

`research/`保存研究治理材料、阶段一任务及登记索引；`experiments/`保存实验、阶段二至五交付
和候选实体，最后按实验整体封存；历史原件保持原位。`strategies/`是只由平台工具
写入的治理区。`data/`与`outputs/`中的本地内容不能替代正式证据。运行状态和具体命令以相应
角色说明及平台当前公共入口为准，项目首页不维护版本或账户状态快照。

研究员可以导入各模块公开契约、SE纯计算函数以及独立第三方研究库。正式数据访问、策略运行和
账户评价由TDR/REX受管端口执行；候选登记、阶段交付、决定留痕与冻结通过TDR业务API写入。
平台校验证据和执行一致性，研究员解释与推荐，用户决定阶段推进、候选选择和冻结。
技术检验`PASS`不代表收益保证；冻结仅在`FreezeReceipt.status == COMMITTED`时完成。
