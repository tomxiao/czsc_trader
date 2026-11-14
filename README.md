# CZSC Trader

## 项目介绍

CZSC Trader 是面向 A 股、美股的量化策略研究与模拟交易平台，支持数据准备、策略计算、历史回放、绩效评价、策略发布和模拟盘运行。

项目由 TDR 研究主应用和七个独立 Python 子包组成。TDR 与 PTE 共用数据准备、策略计算和订单规则；EC 分别处理历史回放盘、A 股模拟盘和美股模拟盘的执行与账户。

## 关键文档定位

| 文档 | 谁来阅读 | 作用 |
| --- | --- | --- |
| [RSCH 工作指南](research/RSCH_AGENT.md) | 研究员、研究负责人 | 明确研究方法、阶段流程、职责与交付要求 |
| [A 股研究补充](research/guides/CN_RESEARCH.md)／[美股研究补充](research/guides/US_RESEARCH.md) | 对应市场的研究员 | 查阅市场特有的数据、交易及研究约束 |
| [DEV 工作指南](docs/DEV_AGENT.md) | 平台开发者、技术评审者 | 明确工程原则、模块边界、依赖关系和修改权限 |
| [TDR 使用说明](src/czsc_trader/README.md) | 研究员、平台开发者 | 查阅研究工具的公共 API、调用契约和使用示例 |
| [测试治理](docs/TEST_GOVERNANCE.md) | 平台开发者、测试维护者 | 确定用例范围、执行方式及精简原则 |
| [PTE 运维手册](docs/PTE_OPERATIONS.md) | 发布与运维人员 | 执行部署、账户维护、在线验证和故障恢复 |
| [研究目录说明](research/README.md) | 研究员、交接接手者 | 定位批次材料、数据、成果及 `HANDOFF.md` 接续入口 |
| [历史实验说明](experiments/README.md) | 历史研究查阅者 | 理解旧实验原件的保存边界和使用限制 |

## 路径导航

### 代码与模块说明

模块 README 面向模块使用者和开发者，说明职责、公共契约及使用方式。

RSCH 编写 V5 策略时，先看 [SRT 策略与说明入口](packages/strategy_runtime/README.md#v5-策略编写与逐轮取数)，
再用 [TDR 回放示例](src/czsc_trader/README.md#us-equity-api)准备输入、执行回放并发布证据。
交付前参照 [PTE 前瞻图验收](packages/paper_trading_engine/README.md#前瞻事实怎样产生)核对信号和事件。

| 模块入口 | 主要内容 |
| --- | --- |
| [TDR · src/czsc_trader/](src/czsc_trader/README.md) | 研究编排、历史评价、证据交付及冻结升级 |
| [DFLS · packages/dataflows/](packages/dataflows/README.md) | 数据资产获取、校验与来源身份 |
| [SRT · packages/strategy_runtime/](packages/strategy_runtime/README.md) | 共享数据准备、策略计算、决策提案与观察快照 |
| [EC · packages/execution_channels/](packages/execution_channels/README.md) | 市场规则、订单规划、渠道执行与账户处理 |
| [SE · packages/strategy_evaluator/](packages/strategy_evaluator/README.md) | 绩效评价、自检及账本比较 |
| [SM · packages/strategy_manager/](packages/strategy_manager/README.md) | 研究身份、候选、发布记录及生命周期 |
| [PTE · packages/paper_trading_engine/](packages/paper_trading_engine/README.md) | 模拟盘调度、策略编排、Web 运维与前瞻观察 |
| [SC · packages/strategy_chart/](packages/strategy_chart/README.md) | 回测与前瞻共享图表 |

### 资料与工程目录

| 路径 | 内容 |
| --- | --- |
| [research/](research/) | 按批次组织的研究材料、实验、数据资产和正式成果 |
| [strategies/](strategies/) | 策略运行版本、发布包、部署身份及历史修订 |
| [experiments/](experiments/) | 旧流程产生的历史实验原件 |
| [docs/](docs/) | 开发、测试与运维文档 |
| [tests/](tests/) | 仓库级测试；模块测试另见各子包目录 |
| [scripts/](scripts/) | 测试、构建、发布及维护脚本 |
| `.tmp/` | 临时文件、隔离验证及一次性工具产物 |
