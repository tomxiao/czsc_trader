# CZSC Trader

CZSC Trader 面向量化策略研究与模拟交易，连接受控数据、策略计算、账户评价、候选比较、技术检验和版本发布。
研究员（RSCH）负责发现收益机会、检验机制、组织搜索和解释结论；用户负责研究目标、阶段推进、候选选择及冻结批准。
平台负责公共契约、数据与账户计算正确性、证据身份和原子发布。

项目由 TDR 主应用和八个独立 Python 子包组成。研究统一使用批次上下文，独立取数、候选评价、回测和技术检验
共用该批次的 DFLS 数据空间。计算结果通过显式接口留存，阶段交付只保存结论与选定证据；实验工作材料允许继续修正。
冻结、SRT 部署、PTE 账户和生产写入分别遵循相应授权边界。

## 关键文档

| 目的 | 入口 |
| --- | --- |
| 研究批次、目录职责与交接 | [研究导航](research/README.md)；具体状态见批次 `HANDOFF.md` |
| RSCH 目标、研究方法、权限和交付 | [研究员 Agent](research/RSCH_AGENT.md) |
| 批次上下文、评价、回测、证据及冻结 API | [TDR 使用说明](src/czsc_trader/README.md) |
| 旧实验原件的保存边界 | [历史实验说明](experiments/README.md) |
| DEV 架构与工程决策、开发环境 | [DEV Agent](docs/DEV_AGENT.md)；[测试治理](docs/TEST_GOVERNANCE.md) |
| PTE 发布、账户、服务与恢复 | [PTE 运维手册](docs/PTE_OPERATIONS.md) |

## 子包使用说明

模块 README 面向研究员说明公共能力及使用边界。研究与策略发布 API 接受当前契约；历史格式原件保留供人工查阅。

| 研究与治理能力 | 执行与观察能力 |
| --- | --- |
| [DFLS：取数、校验与数据资产](packages/dataflows/README.md) | [SRT：策略实现与决策](packages/strategy_runtime/README.md) |
| [FSC：因子、信号及复用因子计算](packages/factor_signal_catalog/README.md) | [TXE：成交与账户计算](packages/trading_execution_engine/README.md) |
| [STC：策略结构模板](packages/strategy_template_catalog/README.md) | [PTE：模拟交易与前瞻观察](packages/paper_trading_engine/README.md) |
| [SM：研究身份、候选及运行发布](packages/strategy_manager/README.md) | [SE：确定性数值评价](packages/strategy_evaluator/README.md) |

## 研究资料与运行发布

新研究集中在 `research/<批次>/`：`data/` 保存批次数据，`experiments/<实验>/work/` 保存可修改材料，
`experiments/<实验>/evidence/` 保存明确发布的证据，`deliveries/<阶段>/<修订>/` 保存结论及选定证据快照。
`decisions/` 保存用户决定，`freeze_requests/` 保存冻结事务事实。研究身份和候选登记集中在 `research/registrations/`。

`strategies/` 保存由 SM/SRT 管理的运行版本、发布包与部署身份。历史 `experiments/` 和旧数据空间保留原位，
新目录规则不迁移或重签原件。批次 DFLS 数据按现有 Git 规则忽略；仅同步 Git 或准备引用不能恢复丢失的数据资产。
正式证据的保存与跨机器交接见[研究导航](research/README.md)。

研究员可直接使用公开契约、SE 纯计算函数及获准的第三方研究库，自主组织阶段二、三的探索和搜索。
平台验证产物与数值一致性，研究员核对授权、因果时点、适用边界和反面证据。技术检验 `PASS` 表示技术检查通过；
冻结仅在 `FreezeReceipt.status == COMMITTED` 时完成。
