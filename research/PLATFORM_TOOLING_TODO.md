# 研究平台与工具优化 TODO

本文记录策略研究过程中发现的平台与工具改进需求。它不是S008研究协议、实验结论或当前DEV实施
授权。S008在EX66后曾恢复信息审计，现已于EX90后无候选终止；后续由用户组织RSCH与DEV评审
范围、优先级和是否实施。
平台改造不得反向改变S008的目标、搜索空间或证据。

## 1. 背景与原则

S008从EX11开始建立第一性原理、数据与因果门、信息路径、原型实现、联合搜索和差距归因链路。
研究方法有效提高了审计性，但多个正式实验被数据时间语义、SRT/TXE评价边界和自定义执行脚本的
技术问题阻断。优化目标是降低技术失败率和重复代码，同时保持不可变实验、密封验证、角色隔离和
完整执行口径。

原则：

- 平台为研究提供可靠基线，不限定可以提出的金融假设；
- 优先解决会影响正确性或反复阻断研究的问题；
- 公共能力只封装稳定的技术语义，不把S008专属因子和规则上移为平台标准；
- 新能力先通过合成场景和独立功能测试，再由新的研究实验采用；
- 不修改既有实验档案，不用平台改造反向解释已经看到的研究结果。

## 2. S008可复现证据基线

既有实验档案保持不可变，不直接重跑或改写。平台优化应从下列档案提取最小合同与合成夹具，在
`tests/fixtures/s008_research_cases/`建立独立复现场景；复现测试只证明软件问题，不重新解释Alpha。

| 案例 | S008证据 | 可复现场景 | 应阻断或证明的事实 |
| --- | --- | --- | --- |
| C01 数据集合同漂移 | `experiments/S008/20260923_S008_EX56/03_execution.md` | 输入合同声明不存在的`market.trading_calendar` | 在准备数据前返回未知数据集及当前合法枚举 |
| C02 公共结果字段漂移 | `experiments/S008/20260923_S008_EX57/03_execution.md` | 代码读取旧字段`dataset_identity`，当前公共字段为`data_identity` | 静态合同或预检在正式运行前报告字段不兼容 |
| C03 跨市场严格前值 | EX61、EX63、EX64的执行记录 | 中国长假期间FXCM继续交易，决策日取严格早于当日的最新报价 | 保留外盘报价、源日期和陈旧度，禁止重索引后再`shift(1)` |
| C04 Pandas时间差错误 | `experiments/S008/20260923_S008_EX62/03_execution.md` | Series时间差错误使用`.days`而非`.dt.days` | 证据计算在技术预检中完整运行并返回结构化结果 |
| C05 评价起点硬编码 | `experiments/S008/20260923_S008_EX65/03_execution.md` | 首个双特征有效信号为2014-01-22，首个执行日应为2014-01-23 | 评价起点从有效信号和交易日历推导，禁止脚本常量 |
| C06 搜索与完整账户等价 | `experiments/S008/20260923_S008_EX66/03_execution.md` | 1,500次trial、8个worker、SRT/TXE等价门和10bp/30bp成本 | 固定种子下搜索可复现，完整账本与加速评价逐日一致 |

每个复现场景必须包含输入夹具、预期机器状态、预期错误码或逐日等价断言，以及它所保护的公共API。
禁止把整个S008策略、贵金属因子或目标门槛复制到平台测试；只提取跨策略稳定的软件语义。

## 3. P0：正确性与公共API

### 3.1 补全SRT策略编写公共API

**证据：** EX56至EX64的研究期策略实现需要直接导入`strategy_runtime.calculation`、
`strategy_runtime.errors`和`strategy_runtime.models`；实验脚本还导入`strategy_runtime.loader`、
`strategy_runtime.implementation_identity`和`strategy_runtime.contracts`。这与RSCH只能依赖公共API
的规则冲突，也使候选实现绑定内部目录结构。

**平台需求：** 修改`packages/strategy_runtime`，从顶层`strategy_runtime`稳定导出策略编写所需的：

- `CutoffRule`、`InputRequirement`、`InputContract`；
- `ImplementationRef`、`ParameterSet`、`HistoryPolicy`、`DecisionContract`；
- `MonitoringPolicy`、`RequiredCapabilities`、`RuntimeDefinition`；
- `next_session_calendar_window`、`next_session_calculation_scope`；
- `implementation_sha256`。

研究员通过`StrategyRuntime.create(StrategyInit(...))`加载候选，不新增或公开`StrategyLoader`。同时
修改`packages/strategy_runtime/README.md`的公共API章节，并增加功能测试，禁止候选示例导入上述
内部模块。

**验收：** 用C01/C02夹具实现最小`StrategyImplementation`，源码只能从顶层`strategy_runtime`
导入公共符号；完成合成数据准备、决策和TXE窗口执行；现有冻结策略等价测试继续通过。

### 3.2 新增正式实验技术预检

**证据：** C01、C02、C04和C05均在协议冻结后、读取目标收益前暴露纯技术错误，分别产生了不可变
后继实验。

**平台需求：** 在根项目新增公共包`src/czsc_trader/research_tools/`，首先提供：

```python
check_experiment(request: ExperimentCheckRequest) -> ExperimentCheckResult
```

上述函数和请求/结果类型统一从`czsc_trader.research_tools`导出；子模块保留实现细节，不要求实验
直接导入内部文件。

该API只使用合成数据、结构性夹具和合同元数据，检查数据集与字段、SRT候选装载、数据准备、完整
信号、T+1执行映射、TXE成本场景、BuyHold同窗口基准、参数空间合法数量、依赖闭包及manifest
可封存性。结果状态只允许`READY`或`BLOCKED`，`BLOCKED`必须返回稳定错误码和失败阶段。

修改`src/czsc_trader/cli/research_commands.py`，只新增一个入口：

```text
czsc-trader research experiment check <EXPERIMENT_DIR>
```

第一阶段不增加`run`和`finalize`命令，避免平台过早接管实验脚本和不可变档案写入。更新
`research/RSCH_AGENT.md`与根CLI帮助，说明预检不产生金融证据。

**验收：** C01、C02、C04、C05分别在读取真实收益前返回明确`BLOCKED`；修正后的夹具返回
`READY`；命令不修改实验目录、受管数据或治理区。

### 3.3 统一跨市场时间对齐合同

**证据：** EX61把`PREVIOUS_SESSION`误解释为中国上一交易日；EX63在重索引到中国日历后再
`shift(1)`，丢失中国休市期间的FXCM报价；EX64使用严格前值`merge_asof`后才通过因果和7日陈旧度
检查。

**平台需求：** 协同修改`packages/dataflows`与`packages/strategy_runtime`：

- 在SRT公共API增加`AlignmentRule`、`InputAlignment`和`align_input_history(...)`；
- `AlignmentRule`至少表达`EXACT`、`STRICT_PRIOR`和`LATEST_AVAILABLE`；
- `InputAlignment`声明源时间列、源日历、决策日历、最大陈旧天数和是否允许同日值；
- `InputRequirement`可选绑定`InputAlignment`，并把合同纳入运行身份；
- DFLS成功结果稳定提供原始源时间，`DataIdentity.metadata`对`source_calendar`和`available_at`
  形成受验证的公共语义；
- 对齐结果同时返回值、`source_time`和`staleness_days`，禁止策略自行丢弃来源时间。

`AlignmentRule`、`InputAlignment`、`AlignedInput`和`align_input_history`统一从顶层
`strategy_runtime`导出。

更新两个包级README和公共API导出。平台不内置S008的金银特征，只提供跨市场、跨频率通用对齐。

**验收：** C03覆盖普通交易日、中国长假、外盘缺口、同日值禁止和最大陈旧度超限；输出值与EX64
口径一致，且每个决策日都能追溯源日期和对齐规则。

### 3.4 新增统一SRT/TXE研究评价Harness

**证据：** EX56至EX66重复实现准备窗口、信号窗口、执行窗口、指标窗口、10bp/30bp成本、BuyHold
和完整/加速等价；EX65的评价起点硬编码说明这些边界尚未形成公共语义。

**平台需求：** 在`src/czsc_trader/research_tools/evaluation.py`提供公共API：

```python
evaluate_strategy(request: EvaluationRequest) -> EvaluationResult
validate_accelerated_equivalence(request: EquivalenceRequest) -> EquivalenceResult
```

`EvaluationRequest`必须接收策略source、交易窗口、初始资金、主/压力成本、执行行情和基准；评价
起点由首个有效信号的下一可执行交易日推导。`EvaluationResult`返回数据身份、决策、订单、成交、
费用、逐日账户、交易、BuyHold和指标，不允许只返回聚合收益。Harness内部只能通过SRT公开API和
TXE `HistoricalExecutor`执行。

修改`src/czsc_trader/candidate_evaluation.py`、`src/czsc_trader/application/evaluation_service.py`、
`src/czsc_trader/application/evaluation_evidence.py`和`src/czsc_trader/application/review_data.py`，使
TDR候选体检复用同一Harness；高频参数搜索直接调用Python API，不新增逐trial CLI。API及请求/
结果类型从`czsc_trader.research_tools`统一导出。

**验收：** C05推导出2014-01-23；C06选取固定代表参数，完整路径和加速路径的目标仓位、账户净值
及指标逐日一致；研究与TDR使用相同输入时产生相同账本身份。

## 4. P1：效率与可观察性

### 4.1 公共Optuna搜索执行器

**证据：** EX60至EX66重复实现`InMemoryStorage`、Windows `spawn`、固定种子、分批`ask/tell`、
约束失败、worker并发、trial ledger和裁决摘要。

**平台需求：** 在`src/czsc_trader/research_tools/search.py`公开：

```python
run_search(contract: SearchContract, evaluate: TrialEvaluator) -> SearchResult
```

`SearchContract`声明sampler、种子、参数空间、目标、约束、预算、批次大小和worker数；worker默认
为逻辑CPU的一半。主进程独占Study并按trial编号执行确定性`ask/tell`，worker只计算冻结参数。
`SearchResult`必须包含全部trial、失败类型、Pareto集合、可行点数量、耗时和实际并发配置。
`SearchContract`、`SearchResult`、`TrialEvaluator`和`run_search`从`czsc_trader.research_tools`
统一导出。

第一阶段只支持`InMemoryStorage`，明确不支持断点恢复，不新增搜索CLI。正式实验代码调用Python
API并保存返回账本。

**验收：** C06在1个和8个worker下产生相同trial编号、参数及裁决；异常trial进入账本且不会汇总为
成功；进度输出包含已完成数、可行点数和ETA。

### 4.2 研究状态只读入口

**证据：** EX56至EX66包含技术后继、协议后继和最终金融结论，仅查看HANDOFF容易遗漏最新权威
manifest或把技术失败误判为机制失败。

**平台需求：** 在`src/czsc_trader/research_tools/status.py`提供只读派生API，并修改
`src/czsc_trader/cli/research_commands.py`新增：

```python
derive_research_status(context, strategy_id: str) -> ResearchStatus
```

函数和`ResearchStatus`从`czsc_trader.research_tools`导出。CLI新增：

```text
czsc-trader research status S008
```

输出最近有效实验、前驱/后继关系、技术或金融状态、最终机器裁决、污染边界、候选状态和下一阶段
门。信息全部从不可变manifest、结论和候选目录派生，不修改HANDOFF。

**验收：** 对S008返回EX66、`STOP_PRECIOUS_METAL_PREFERENCE_NO_FEASIBLE_REGION`、无候选，并将
EX56、EX57、EX61、EX62、EX63、EX65识别为技术阻断而非负Alpha证据。

### 4.3 DFLS能力只读查询

**证据：** C01来自研究协议使用了不存在的数据集标识；研究员需要在冻结协议前发现当前数据集、
字段和权限能力。

**平台需求：** 在`packages/dataflows`增加`Dataflows.capabilities()`公共只读API，返回数据集标识、
频率、关键字段、来源、所需权限、时间语义和当前环境是否可请求；在根CLI增加：

```text
czsc-trader data capabilities [--dataset <DATASET>]
```

命令不得返回Token、账户信息或原始凭据。同步更新`packages/dataflows/README.md`。
结构化返回项定义为`DataCapability`并从顶层`dataflows`导出。

**验收：** C01查询能列出`calendar.trading_sessions`并明确拒绝`market.trading_calendar`；缺失权限
返回结构化不可用原因，不发起数据下载或修改本地数据。

### 4.4 S008研究链路合成回归

在`tests/functional/research_tools/`增加C01至C06，每个测试只依赖
`tests/fixtures/s008_research_cases/`的最小合成数据。覆盖ETF与外盘日频、中国长假、首个有效信号、
T+1执行、成本压力、完整/加速等价和确定性搜索。测试名称和失败信息必须指向所保护的公共合同，
不得运行或修改`experiments/S008/`。

## 5. 第三方库需求

RSCH当前需要的第三方库限定为能够直接提升信息发现或正式搜索效率、且可以从冻结策略运行时剥离
的工具。2026-09-24本机环境核对结果为：Optuna 4.9.0、tsfresh 0.21.1可用，`expr_codegen`尚未
安装。

| 库 | 紧迫度 | 研究阶段 | 具体用途 | 平台需求 |
| --- | --- | --- | --- | --- |
| Optuna 4.9.0 | 已在使用，必须保留 | 正式联合搜索 | 多参数、多目标、约束搜索及完整trial ledger | 保留在根`pyproject.toml`的`research` extra，由4.1公共执行器统一使用 |
| tsfresh 0.21.1 | 已具备，近期需要 | 数据门后、原型收敛前 | 在有机制依据的序列和窗口上发现候选时序形态 | 保留在`research` extra，提供半数逻辑CPU的默认并行模板和发现/确认期示例 |
| `expr_codegen` | 急需补齐 | 基础组件形成后、原型冻结前 | 把受限变量、算子、滞后和窗口组合成可去重、可审计的表达式树，并生成普通确定性代码 | 确认提供`expr_codegen`模块的准确distribution和版本，完成兼容性验证后加入`research` extra |

### 5.1 `expr_codegen`接入要求

修改根`pyproject.toml`，只把经验证的distribution加入`[project.optional-dependencies].research`，继续
使用仓库唯一`.venv`，不创建第二套研究环境。DEV需要增加
`tests/functional/test_research_dependencies.py`，至少验证：

- Python 3.12及项目当前NumPy、Pandas依赖可以共同解析并通过`pip check`；
- `import expr_codegen`成功，实际版本和公共API可记录；
- 相同表达式输入产生相同规范树、身份和生成代码；
- 非法算子、未来数据引用、超限窗口和过高复杂度明确失败；
- 生成的普通策略代码不依赖`expr_codegen`即可运行，并与研究表达式逐值一致。

同步更新`research/RSCH_AGENT.md`中的环境准备说明和`docs/DEVELOPMENT_HANDOFF.md`的研究依赖清单。
该库只进入研究环境，不进入候选源码闭包、冻结SRT或PTE生产依赖。

当前没有其他急需引入的第三方库。新的依赖需求必须先给出金融机制、预期信息增量、现有工具缺口、
兼容性和可复现场景，再进入本TODO。

## 6. P2：有触发条件后再实施

| 项目 | 当前决定 | 启动条件 | 预期位置 |
| --- | --- | --- | --- |
| Optuna断点恢复 | 延后 | 单次正式搜索耗时或失败成本达到用户确认阈值 | `research_tools/search.py`增加持久化storage合同 |
| worker数据共享与进程初始化优化 | 延后 | C06基准证明序列化或重复装载是主要瓶颈 | `research_tools/search.py`及性能测试 |
| 研究环境依赖快照 | 延后 | 出现环境无法重建或依赖漂移证据 | `research environment show`只读命令 |
| 实验归档清理 | 延后 | archive验证发现缓存反复进入正式档案 | archive finalize能力与独立测试 |

没有可复现证据或明确触发条件的第三方依赖，不进入平台TODO。

## 7. DEV评审与实施顺序

建议按下列顺序逐项评审，每项都需要用户授权DEV实施：

1. 确认并接入`expr_codegen`研究依赖；
2. SRT策略编写公共API与C01/C02夹具；
3. 跨市场时间合同与C03；
4. SRT/TXE评价Harness与C05/C06；
5. 正式实验技术预检与C01、C02、C04、C05；
6. Optuna执行器与C06；
7. `research status`和`data capabilities`只读入口；
8. 全部C01至C06合成回归及包级文档。

每个DEV方案必须明确修改包、公共导出、命令字、错误状态、兼容性和不实现范围。平台改造不修改
既有S008档案，也不改变EX66结论；首次采用应放在用户确认的新研究实验或后续策略批次。
