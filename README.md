# CZSC Trader

## 项目介绍

CZSC Trader 是面向个人量化团队的可审计策略研发与模拟交易项目。它把行情准备、策略研究、
候选评估、版本冻结、交易决策、模拟执行和前瞻监测连接成一条可复核的工作流。

项目强调证据边界和执行一致性：研究结论必须能回到不可变实验档案，正式策略必须绑定明确
版本和数据截止，交易决策与渠道执行通过稳定契约衔接，运行异常必须留下可追踪的审计记录。
跨模块状态采用严格成功语义：数据缺失、截止日不符、批次部分完成或执行结果不确定都会
显式失败或进入降级状态，不能被汇总成成功，也不能推进策略决策或账户事实。

本 README 只承担项目介绍、项目目录说明和关键文档索引。安装命令、当前策略状态、运行操作
与研究进度分别由对应文档维护，避免项目首页演变成易过期的操作手册或状态快照。

### 系统组成

| 模块 | 简称 | 位置 | 职责 |
| --- | --- | --- | --- |
| CZSC Trader | TDR | `src/czsc_trader/` | 首席投资官（CIO）执行候选审查、体检和冻结的受控平台入口 |
| Dataflows | DFLS | `packages/dataflows/` | 数据获取、规范化、自校验、按供应商与标的修复和失败阻断 |
| Factor & Signal Catalog | FSC | `packages/factor_signal_catalog/` | 项目级信息族、因子和信号定义目录 |
| Strategy Template Catalog | STC | `packages/strategy_template_catalog/` | 策略函数模板、输入角色和参数边界目录 |
| Strategy Manager | SM | `packages/strategy_manager/` | 策略身份、版本、资格、冻结和证据治理 |
| Strategy Evaluator | SE | `packages/strategy_evaluator/` | 候选比较、统计审计和稳健性数值计算 |
| Strategy Runtime | SRT | `packages/strategy_runtime/` | 策略实例、数据准备、决策计算、参考价、执行计划和运行身份 |
| Trading Execution Engine | TXE | `packages/trading_execution_engine/` | 承接SRT历史执行请求，统一订单、成交、费用和账户账本 |
| Paper Trading Engine | PTE | `packages/paper_trading_engine/` | 虚拟账户、模拟下单、成交对账、运行审计、前瞻观察图和控制台 |
| PTE Watchdog | WDG | PTE包内 | PTE进程托管、健康检查和故障拉起 |

SRT以`StrategyInstance`为运行边界，根据交易窗口自主推导和准备数据，并生成普通调仓计划或
带执行时点、成交依赖的计划。TDR通过`run_window(...)`连接TXE完成历史执行；PTE通过
`plan_at(...)`提供账户事实并执行单日计划。Futu渠道提供订单、成交和持仓回报。SM管理策略
生命周期，SE生成确定性数值证据；二者都不参与运行时下单。

### 核心工作流

```text
用户授权RSCH：研究立项与实验 → 实现策略、binding和回测图 → 组装候选提交包
用户授权CIO：candidate review → candidate evaluate → 审阅体检结果 → candidate freeze
平台工具：封存候选与数据 → 独立复算和完整性阻断 → 生成不可变冻结版本
CIO按当前任务授权：strategy deploy → SRT从策略治理区加载冻结发布包
独立授权：创建PTE虚拟账户 → PTE异步生成前瞻观察图 → 前瞻监测
```

研究诊断、正式裁决和模拟盘表现分别保存，不能用单次成交或未冻结实验替代策略有效性证据。
历史失败、执行异常和修复记录继续保留，避免事后改写研究或交易结果。

策略研究员（RSCH）和首席投资官（CIO）均由用户授权的独立LLM Agent会话承担。RSCH维护
研究区和候选提交包；CIO使用平台工具完成候选审查、体检、冻结与SRT部署。当前平台尚不识别
或鉴权用户及Agent身份，治理印章中的操作者身份保证级别明确记录为`UNVERIFIED`。研究可以
自由选择算法库，最终评价目标在送审时锁定；TDR根据候选实现、封存数据和TXE账本独立复核，
冻结后原样保存同一实现。历史实验保留供人工审阅，当前架构不承诺旧实验脚本重放兼容。

## 项目目录

| 路径 | 内容 | 管理边界 |
| --- | --- | --- |
| `src/czsc_trader/` | TDR主程序、命令入口和应用服务 | 项目核心业务代码 |
| `packages/` | DFLS、FSC、STC、SM、SE、SRT、TXE、PTE八个独立子包 | 各子系统接口、实现和包级测试 |
| `catalog/` | FSC信息族、因子和信号定义 | 项目级定义来源，不保存标的值或Alpha证据 |
| `strategy_templates/` | STC策略函数模板定义 | 项目级结构来源，不保存搜索结果或绩效证据 |
| `strategies/` | 正式策略身份、SGC凭据链、冻结发布包、部署凭据、生命周期和证据 | 独立策略治理区，只由平台工具写入；SRT从此处加载已部署版本 |
| `research/` | 共享研究入口、RSCH/CIO Agent描述、各SXX批次目标、候选和监测方案 | 研究领域入口；目标与批次绑定 |
| `experiments/` | 按策略和实验编号归档的输入、结果及审计证据 | 不可变研究档案，失败实验同样保留 |
| `data/` | 研究池、普通回测执行数据和冻结评审快照 | `raw/`、`backtest/`、`review/`隔离管理；本地数据不随Git分发 |
| `docs/` | 用户、开发、测试治理、事故和历史设计文档 | 非研究领域说明与历史资料入口 |
| `scripts/` | 仓库级并行回归、PTE构建和发布脚本 | 测试、构建与生产发布分离；生产写入需独立授权 |
| `tests/` | TDR端到端功能测试和共享测试支持 | 根项目的行为契约验证 |
| `outputs/` | 本地回测报告、图表和临时导出结果 | Git忽略；正式证据应归档到`experiments/` |
| `pyproject.toml` | 根项目依赖、命令入口、测试与静态检查配置 | Python项目配置来源 |

`.venv/`、`.tmp/`、`.build/`、`state/`、`__pycache__/`及各包的`build/`、`dist/`
属于本机环境、显式开发运行状态或生成物，不构成项目文档和正式证据。PTE生产状态位于独立
发布环境，不从开发仓库读取代码或运行数据。

## 文档索引

### 策略研究员必看

- [RSCH Agent描述](research/RSCH_AGENT.md)：策略研究员Agent的身份、授权边界、研究工作流和
  候选交付要求。
- [策略研究导航](research/README.md)：查找角色契约、各策略交接、实验与治理资料。
- [策略候选包](research/CANDIDATE_PACKAGE.md)：候选实现、binding、回测图代码、前瞻观察语义和
  提交清单的完整契约。

查阅或归档正式实验时，继续阅读[实验档案说明](experiments/README.md)。

### 首席投资官必看

- [CIO Agent描述](research/CIO_AGENT.md)：首席投资官Agent的身份、任务授权范围、候选体检、冻结和
  SRT部署规则。
- [策略候选包](research/CANDIDATE_PACKAGE.md)：通过`candidate review/evaluate/freeze`完成体检与
  冻结，再通过`strategy deploy/list/info`管理SRT已部署策略。
- [策略研究导航](research/README.md)：定位候选来源、批次结论和研究证据。

### 平台开发者必看

- [策略研究导航](research/README.md)：定位研究角色、批次资料和证据权威来源。
- [开发运维交接](docs/DEVELOPMENT_HANDOFF.md)：掌握架构契约、环境恢复、开发规则和PTE发布运维。
- [测试用例治理](docs/TEST_GOVERNANCE.md)：遵循测试分层、边界覆盖和周期性治理规则。
- [DFLS技术说明](packages/dataflows/README.md)：数据包接口和使用方式。
- [FSC技术说明](packages/factor_signal_catalog/README.md)：因子与信号定义目录及查询方式。
- [STC技术说明](packages/strategy_template_catalog/README.md)：策略函数模板、实例化契约及边界。
- [SM技术说明](packages/strategy_manager/README.md)：策略身份、治理凭据、冻结版本和证据账本。
- [SE技术说明](packages/strategy_evaluator/README.md)：候选评估与统计审计接口。
- [SRT技术说明](packages/strategy_runtime/README.md)：候选与冻结策略的数据、决策与执行边界。
- [TXE技术说明](packages/trading_execution_engine/README.md)：统一成交与账户计算口径及其边界。
- [PTE技术说明](packages/paper_trading_engine/README.md)：模拟交易引擎的配置、接口、运行边界和包级开发信息。

排查已确认运行事故时，查阅[事故复盘索引](docs/incidents/README.md)。`docs/superpowers/specs/`
和`docs/superpowers/plans/`用于审计历史设计及实施过程，不代表当前操作入口。

以上重要文档必须在每次版本发布时根据实际变更及时更新，确保文档描述与发布版本一致。
