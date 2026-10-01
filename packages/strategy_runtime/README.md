# 策略运行时（Strategy Runtime，SRT）

本文面向策略研究员（RSCH）。安装、源码维护及包级验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

SRT 是研究、回测、模拟交易及未来实盘共用的策略计算锚点。它把一个候选或冻结策略转换为
`StrategyInstance`，由实例自主准备计算数据、执行策略计算，并输出与渠道无关的执行计划。

SRT 不管理策略生命周期，不评价策略优劣，也不记录成交和账户账本。SM 管理策略身份与治理，
SE 负责数值评估，TXE 和 PTE 分别负责历史执行与模拟交易执行。

RSCH通过显式源码绑定构造`StrategyCandidate`并复用同一实现进行研究评价。冻结版本及部署凭据保持原样；部署需要独立授权。新冻结能力尚未提供，详见[RSCH契约](../../research/RSCH_AGENT.md)。

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

`StrategyRuntime`是实例工厂，不持有运行中的策略状态；可通过关键字参数`dataflows`
接收宿主配置的DFLS。策略状态、准备结果及信号缓存归属于`StrategyInstance`，
原始请求的本地缓存由DFLS管理。

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
- `tradable_window`：需要生成执行计划的闭区间，端点必须是`date`类型的可交易日，拒绝字符串和`datetime`；
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

`StrategyCandidate`支持标准库pickle及进程spawn传输，重建时重新验证候选合同并保持嵌套参数
不可变、源码根目录和身份不变。该能力仅覆盖候选对象；调用方仍须验证自己的完整worker载荷，
并在子进程显式配置数据入口。源码绑定继续由SRT加载路径核验。

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

需要跨实例复用DFLS请求时，使用`StrategyRuntime(dataflows=flows)`；`flows`由宿主构造，
配置示例见[DFLS本地缓存](../dataflows/README.md#dev配置本地缓存)。已有实例准备结果仍按原身份加载，
DFLS的`REFRESH`策略不会重写它。需要重新准备时，为新实例分配独立目录。

## 信号历史语义

`SignalHistoryMode`是公共枚举，接口拒绝同名字符串。

| 模式 | 计算语义 | 默认入口 |
| --- | --- | --- |
| `CONTINUOUS` | 调用`calculate_history`，使用完整计算范围，延续预热阶段状态 | `plan_at(..., history_mode=SignalHistoryMode.CONTINUOUS)` |
| `WINDOW` | 调用`calculate_window_history`，按窗口信号日期计算 | `inspect_signals(history_mode=SignalHistoryMode.WINDOW)`；`run_window`固定使用此模式 |

策略可覆盖`calculate_window_history`定义窗口初始化行为；基类实现将窗口信号日期传给`calculate_history`。
比较逐日计划与窗口回放时，调用方必须显式对齐历史模式。两类历史分别缓存，诊断接口返回副本。
历史必须使用有序且唯一的`DatetimeIndex`并覆盖所需日期；窗口历史日期必须精确匹配。
`target_position`必须为有限数值且位于策略声明的仓位边界内，违规时抛出`RuntimeContractError`。

## 执行计划

`plan_at(...)` 接收调用方权威的 `PortfolioSnapshot`、`ExecutionState` 和 `TradingPoint`，输出
`ExecutionPlan`。计划包括：

- 策略、信号、计划和输入数据身份；
- 实际数量、目标数量和周期目标数量；
- 资金模式、分配比例、费用和未分配现金；
- 普通订单，或带时点和成交依赖的多环节计划；
- 所需订单类型及检查点能力。

SRT 计算目标仓位、订单数量、委托类型、委托价和生效时点。执行宿主只负责校验自身能力并执行
计划。`TradingPoint.trading_date`必须为`date`，`calculation_time`必须是带时区的`datetime`。
`ExecutionCapabilities.order_types`必须是由`OrderType`枚举组成的元组。

执行结果必须返回`ExecutionOutcome`：`status`显式使用`ExecutionOutcomeStatus.SETTLED`或
`FAILED`，`portfolio`和`state`分别使用`PortfolioSnapshot`和`ExecutionState`，
`plan_identity`必须对应当前计划。`SETTLED`表示执行已完成并对账，可以包含未成交订单；
成交情况仍由订单与成交明细表达。

`run_window(...)` 面向 TDR 等连续执行场景。调用方注册 `WindowExecutor`，由 SRT 逐交易日获取
账户快照、生成计划并回调执行器。PTE 使用 `plan_at(...)`，以自己的事务和券商回报管理单日执行。

`run_window`在首次读取账户快照前校验执行器的订单类型及检查点能力，并保留逐计划检查。
执行器返回非`ExecutionOutcome`、错误计划身份或非`SETTLED`状态时立即失败，不生成成功窗口结果。

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

冻结版本的可用性以当前治理事实和TDR `strategy_info` API查询为准，不以本说明中的历史版本清单判断。
