# CZSC Trader

CZSC Trader 面向量化策略研究与模拟交易，连接受控数据、策略计算、账户评价、候选比较、技术检验和版本发布。
研究员（RSCH）负责发现收益机会、检验机制、组织搜索和解释结论；用户负责研究目标、阶段推进、候选选择及冻结批准。
平台负责公共契约、数据与账户计算正确性、证据身份和原子发布。

项目由 TDR 主应用和七个独立 Python 子包组成。研究统一使用批次上下文，独立取数、候选评价、回测和技术检验
共用该批次的 DFLS 数据空间。计算结果通过显式接口留存，阶段交付只保存结论与选定证据；实验工作材料允许继续修正。
首次冻结、同版本发布包升级、SRT 部署、PTE 账户和生产写入分别遵循相应授权边界。

## 关键文档

| 目的 | 入口 |
| --- | --- |
| 研究批次、目录职责与交接 | [研究导航](research/README.md)；具体状态见批次 `HANDOFF.md` |
| RSCH 目标、研究方法、权限和交付 | [研究员 Agent](research/RSCH_AGENT.md) |
| 批次上下文、评价、回测、证据、冻结及升级 API | [TDR 使用说明](src/czsc_trader/README.md) |
| 信号解释声明与回测／前瞻图复用 | [SRT 观察契约](packages/strategy_runtime/README.md)；[SC 共享图表](packages/strategy_chart/README.md) |
| 旧实验原件的保存边界 | [历史实验说明](experiments/README.md) |
| DEV 工作流程、工程约束、技术沟通与开发环境 | [DEV 工作指南](docs/DEV_AGENT.md)；[测试治理](docs/TEST_GOVERNANCE.md) |
| PTE 发布、账户、服务与恢复 | [PTE 运维手册](docs/PTE_OPERATIONS.md) |

## 子包使用说明

模块 README 面向研究员说明公共能力及使用边界。研究与策略发布 API 接受当前契约；历史格式原件保留供人工查阅。

| 模块 | 职责 |
| --- | --- |
| [DFLS](packages/dataflows/README.md) | 取数、数据校验与资产身份 |
| [SM](packages/strategy_manager/README.md) | 研究身份、候选、发布记录及生命周期 |
| [SE](packages/strategy_evaluator/README.md) | 确定性数值评价、自检及账本比较 |
| [SRT](packages/strategy_runtime/README.md) | 共享数据准备、策略计算、决策提案与观察快照 |
| [EC](packages/execution_channels/README.md) | 共享市场规则与订单规划；CN/US 模拟盘及历史盘执行与账户 |
| [PTE](packages/paper_trading_engine/README.md) | 模拟盘调度、发布绑定、策略编排、Web运维与前瞻观察；调用EC执行和管理渠道账户 |
| [SC](packages/strategy_chart/README.md) | 回测与前瞻共享图表，展示观察快照和执行事实 |

## 模块协作与依赖

TDR和PTE是两类宿主：TDR组织研究与历史评价，PTE组织模拟盘运行。两者共用SRT的数据准备与策略计算，
以及EC的静态市场规则与订单规划；交易执行和账户处理由EC内的CN模拟盘、US模拟盘、历史回放盘分别承担。

| 调用方 | 直接使用的项目模块 |
| --- | --- |
| TDR | DFLS、SRT、EC、SE、SM、SC；技术检验另调用PTE隔离能力 |
| PTE | DFLS、SRT、EC、SM、SC |
| SRT | DFLS；候选键及发布身份检查局部使用SM |
| DFLS、EC、SE、SM、SC | 均不依赖其他项目模块 |

DFLS是策略数据资产的统一来源，后复权行情返回供应商直供／DFLS计算的获取方法；EC内部`market_rules`拥有静态交易规则。SRT只读取后复权行情，返回目标仓位、解释与观察，
宿主把提案及动态执行事实显式投影到EC类型，由EC规划订单、确认成交并更新渠道账户。
SRT与EC互不依赖，EC不访问DFLS；账户反馈通过宿主交回策略计算。TDR将账户事实交给SE评价，
TDR和PTE分别向SC提供同一展示契约。契约由各业务模块拥有，不设通用公共契约子包。

富途模拟盘独立使用未复权执行参考价，以渠道确认的成交、现金及持仓为准；未知非交易现金进入平账账户，未知数量变化由EC对账。历史盘统一使用后复权价格报价、成交及记账，数量为整数模拟单位，不处理公司行动事件；资金不足以购买最小单位时明确阻断。
静态规则与策略逻辑共用，渠道成交和账户事实分别处理。完整约束见[DEV模块边界](docs/DEV_AGENT.md#module-boundaries)。
独立MRS、TXE、FSC、STC及其旧接口已退役，历史研究原件保留，重跑前迁移调用。

## 研究资料与运行发布

新研究集中在 `research/<批次>/`：`assets/data/` 保存批次数据，`experiments/<实验>/` 内的
`src/`、`protocols/`、`others/` 保存研究工作材料，根 `report.md` 提供实验结论入口。
`assets/evidence/<实验>/` 保存显式发布的证据；`deliveries/<阶段>/<修订>/` 提供阶段报告和回执，
完整交付包保存在 `assets/deliveries/<阶段>/<修订>/`。阶段二原型使用 `PROTOTYPES` 交付，组件证据使用 `COMPONENTS`。
`decisions/` 保存用户决定，`freeze_requests/` 保存冻结事务事实。研究身份和候选登记集中在 `research/registrations/`。

`strategies/` 保存由 SM/SRT 管理的运行版本、发布包与部署身份；`strategies/revisions/` 保存升级前的发布原件及审计链。
历史 `experiments/` 和旧数据空间保留原位，
新目录规则不迁移或重签原件。批次 DFLS 数据按现有 Git 规则忽略；仅同步 Git 或准备引用不能恢复丢失的数据资产。
正式证据的保存与跨机器交接见[研究导航](research/README.md)。

研究员可直接使用公开契约、SE 纯计算函数及获准的第三方研究库，自主组织阶段二、三的探索和搜索。
平台验证产物与数值一致性，研究员核对授权、因果时点、适用边界和反面证据。技术检验 `PASS` 表示技术检查通过；
冻结仅在 `FreezeReceipt.status == COMMITTED` 时完成。

## 信号解释与发布包升级

RSCH 在策略实现中同步声明信号解释，使用当次计算的条件、数值和参数，验证文案与实际决策分支一致。
SRT 校验观察类型、引用与身份并固化解释快照；TDR 回测和 PTE 前瞻观察通过 SC 复用同一展示，
顺序为价格、持仓、信号、事件，回测复盘位于绩效指标之后。历史文案使用原快照，不用当前策略重新推断。
观察计算失败可独立显示为不可用；交易计算、资金、订单与身份校验继续严格执行。

同版本升级使用 TDR 的 `prepare_frozen_runtime_upgrade` 和 `apply_frozen_runtime_upgrade`。
TDR 负责源码与发布身份、授权及证据留痕、旧包归档和提交一致性；修改合理性、解释正确性及等价性验证由 RSCH 负责。
升级不强制候选登记、研究选型或技术检验 PASS，也不限制观察声明必须位于入口类。
`COMMITTED` 表示发布事务完成，不表示策略通过研究验收或已获准生产运行。

同版本升级保留版本号及历史日期，生成新的内容身份；新身份资格为 `RESEARCH`，旧身份的资格不自动转移。
PTE 账户继续绑定精确发布身份，准入、账户改绑和生产生效须分别处理，见 [PTE 运维手册](docs/PTE_OPERATIONS.md)。
