# 策略运行时（Strategy Runtime，SRT）

本文面向策略研究员（RSCH）和首席投资官（CIO）。安装、源码维护及包级验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

SRT 是研究、回测、模拟交易及未来实盘共用的策略计算锚点。它把一个候选或冻结策略转换为
`StrategyInstance`，由实例自主准备计算数据、执行策略计算，并输出与渠道无关的执行计划。

SRT 不管理策略生命周期，不评价策略优劣，也不记录成交和账户账本。SM 管理策略身份与治理，
SE 负责数值评估，TXE 和 PTE 分别负责历史执行与模拟交易执行。

RSCH在候选包中实现策略并复用同一实例进行研究评价；CIO通过TDR体检和部署冻结版本，不手工
修改SRT源码或治理区。候选与冻结代码的提交位置及binding要求见
[候选包契约](../../research/CANDIDATE_PACKAGE.md)。

## 公共门面

调用方只需要使用以下入口：

- `StrategyRuntime.describe(source, symbol=None)`：校验策略及源码绑定，返回只读
  `RuntimeDefinition`；
- `StrategyRuntime.create(StrategyInit(...))`：创建一个不可变的 `StrategyInstance`；
- `StrategyInstance.prepare_data()`：显式准备并认证该实例所需的全部数据；
- `StrategyInstance.plan_at(...)`：结合调用方提供的资金、持仓和执行状态，生成单个交易日的
  `ExecutionPlan`；
- `StrategyInstance.run_window(executor=...)`：在交易窗口内连续计算，并把计划回调给调用方提供的
  `WindowExecutor`；
- `inspect_signals()`、`inspect_price_history()`：测试和诊断使用的只读接口。

`StrategyRuntime` 是实例工厂，不持有运行中的策略状态。业务行为、数据和缓存均归属于创建出来的
`StrategyInstance`。

## 实例初始化

```python
from datetime import date
from pathlib import Path

from strategy_runtime import StrategyInit, StrategyRuntime, TradableWindow

# source 是已校验的 StrategyCandidate 或 StrategyRelease。
instance = StrategyRuntime().create(
    StrategyInit(
        source=source,
        tradable_window=TradableWindow(date(2026, 9, 21), date(2026, 9, 21)),
        data_dir=Path("state/srt/S007-v1/2026-09-21"),
    )
)
prepared = instance.prepare_data()
```

初始化参数的业务语义：

- `source`：带实现身份和参数的候选，或 SM 发布的冻结版本；
- `tradable_window`：需要生成执行计划的闭区间，端点必须是可交易日；
- `data_dir`：由主调方分配、可写且与其他实例隔离的数据空间；
- `symbol`：仅用于冻结版本的显式标的绑定；不支持候选策略静默换标的；
- `execution_policy`：只允许在保持原策略执行策略类型不变时覆盖，用于受控复算。

调用方不需要理解策略依赖哪些数据集，也不传入“初始信号日”或“回看窗口”。这些范围由策略实现
根据交易窗口和交易日历自行推导。

## 策略实现契约

每个策略实现必须派生 `StrategyImplementation`，并实现四项职责：

1. `definition`：声明不可变身份、参数、输入、决策、执行和能力契约；
2. `calendar_window(...)`：推导解析交易窗口所需的交易日历范围；
3. `derive_calculation_scope(...)`：推导信号日、初始计算日及每项输入的准确范围；
4. `calculate_history(...)`：使用已准备输入计算渠道无关的目标仓位和诊断信息。

候选实现只从 `strategy_runtime` 顶层导入策略编写合同。稳定的编写接口包括：

- 定义合同：`CutoffRule`、`InputRequirement`、`InputContract`、`ImplementationRef`、
  `ParameterSet`、`HistoryPolicy`、`DecisionContract`、`ExecutionPolicy`、`MonitoringPolicy`、
  `RequiredCapabilities`和`RuntimeDefinition`；
- 跨市场对齐：`AlignmentRule`、`InputAlignment`、`AlignedInput`和
  `align_input_history`；
- 计算范围：`CalendarWindow`、`CalculationScope`、`InputRange`、
  `next_session_calendar_window`和`next_session_calculation_scope`；
- 实现与身份：`StrategyImplementation`、`StrategyCandidate`和`implementation_sha256`；
- 运行错误：`RuntimeContractError`和`RuntimeCompatibilityError`。

候选代码只从`strategy_runtime`顶层导入公共符号，不依赖`StrategyLoader`或各内部子模块。
候选由`StrategyRuntime.create(StrategyInit(...))`加载和运行。

策略实现负责自身的因果滞后、特征构造、预热、状态推导和目标仓位。

跨市场或跨频率输入应在`InputRequirement.alignment`声明源时间列、源日历、决策日历、最大
陈旧天数和同日值规则，再调用`align_input_history(...)`。`STRICT_PRIOR`对每个决策时点选择
严格更早的最新源观测；`LATEST_AVAILABLE`由合同明确是否允许同日值；`EXACT`只接受同时点值。
返回的`AlignedInput.dataframe`始终携带`decision_time`、`source_time`和`staleness_days`，策略
必须保留这些审计列，禁止通过重索引后`shift(1)`替代跨市场对齐。

## 数据准备

`prepare_data()` 是显式阶段。调用方可以在进入决策或执行前处理数据准备异常。实例内部会：

1. 根据 `tradable_window` 请求交易日历；
2. 调用策略实现推导计算日期、信号日期和每项输入范围；
3. 通过 DFLS 获取并验证所有声明输入；
4. 生成覆盖策略身份、运行身份、窗口和全部输入身份的 `data_identity`；
5. 保存可验证的实例准备结果。

再次使用同一目录时，SRT校验身份与内容后才加载。实例目录属于SRT私有格式，调用方不得
解析其内部文件。`prepare_data()`成功证明已声明输入完整可用，仍不代表策略有效或订单已成交。

## 执行计划

`plan_at(...)` 接收调用方权威的 `PortfolioSnapshot`、`ExecutionState` 和 `TradingPoint`，输出
`ExecutionPlan`。计划包括：

- 策略、信号、计划和输入数据身份；
- 实际数量、目标数量和周期目标数量；
- 资金模式、分配比例、费用和未分配现金；
- 普通订单，或带时点和成交依赖的多环节计划；
- 所需订单类型及检查点能力。

SRT 计算目标仓位、订单数量、委托类型、委托价和生效时点。执行宿主只负责校验自身能力并执行
计划。执行结果必须通过 `ExecutionOutcome` 返回，计划生成成功不代表订单已经成交。

`run_window(...)` 面向 TDR 等连续执行场景。调用方注册 `WindowExecutor`，由 SRT 逐交易日获取
账户快照、生成计划并回调执行器。PTE 使用 `plan_at(...)`，以自己的事务和券商回报管理单日执行。

## 身份与冻结版本

运行身份由以下内容共同决定：

- SM 冻结版本的 `release_hash`；
- 策略实现及其声明源码闭包的 `source_sha256`；
- 参数身份和完整运行定义。

三者形成 `runtime_sha256`。源码、资源文件或绑定发生变化时，冻结版本必须重新签署；加载时任何
哈希不一致都会失败。

冻结binding还包含两类展示契约：`charts`锁定TDR回测图实现及其源码闭包，`observation`声明
SRT决策需要输出的展示无关观察序列。SRT只负责校验并物化观察事实；PTE使用自己的统一渲染器
生成前瞻观察图，不调用策略回测图代码，也不读取未冻结候选包。

冻结版本的可用性以当前治理事实和`strategy info`查询为准，不以本说明中的历史版本清单判断。
