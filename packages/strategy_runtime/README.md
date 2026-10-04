# 策略运行时（Strategy Runtime，SRT）

本文面向策略研究员（RSCH）。安装、源码维护及包级验证见
[DEV Agent](../../docs/DEV_AGENT.md)。

SRT 是研究、回测、模拟交易及未来实盘共用的策略计算锚点。它把一个候选或冻结策略转换为
`StrategyInstance`。实例推导数据需求、认证主调方绑定的数据并执行策略计算，输出与渠道无关的执行计划。

SRT 不管理策略生命周期，不评价策略优劣，也不记录成交和账户账本。SM 管理策略身份与治理，
SE 负责数值评估，TXE 和 PTE 分别负责历史执行与模拟交易执行。

RSCH通过显式源码绑定构造`StrategyCandidate`并复用同一实现进行研究评价。正式研究运行通过
TDR/REX受管入口；候选登记、检验和获批冻结见[TDR说明](../../src/czsc_trader/README.md)。
部署需要独立授权，历史冻结版本及部署凭据保持原样。

## 公共门面

调用方只需要使用以下入口：

- `StrategyRuntime.describe(source, symbol=None)`：校验策略及源码绑定，返回只读
  `RuntimeDefinition`；
- `StrategyRuntime.identify(candidate, *, dependencies)`：校验候选源码和运行定义，返回
  `CandidateContentIdentity`，依赖显式使用`tuple[ImplementationDependency, ...]`；
- `StrategyRuntime.create(StrategyInit(...))`：创建一个不可变的 `StrategyInstance`；
- `StrategyInstance.calendar_request()`：返回推导计算范围所需的日历请求；
- `StrategyInstance.plan_inputs(calendar)`：基于已准备日历返回强类型`StrategyInputPlan`；
- `StrategyInstance.prepare_data(binding=...)`：只读并认证`StrategyInputBinding`指定的输入；
- `StrategyInstance.prepare_data(policy=...)`：按显式`PreparePolicy`完成日历和输入准备；
- `StrategyInstance.plan_at(...)`：结合调用方提供的资金、持仓和执行状态，生成单个交易日的
  `ExecutionPlan`；
- `StrategyInstance.run_window(executor=...)`：在交易窗口内连续计算，并把计划回调给调用方提供的
  `WindowExecutor`；
- `inspect_signals()`、`inspect_price_history()`：测试和诊断使用的只读接口。

`StrategyRuntime`是实例工厂，不持有运行中的策略状态。准备数据时必须通过关键字参数`dataflows`
注入宿主配置的DFLS；纯`describe`和`identify`不需要数据入口。策略状态、计算上下文及信号缓存
归属于`StrategyInstance`，原始数据资产由DFLS的数据空间统一管理。

## 实例初始化

```python
from datetime import date
from pathlib import Path

from dataflows import Dataflows, DataSpace, ProviderConfig, PreparePolicy
from strategy_runtime import StrategyInit, StrategyRuntime, TradableWindow

# repository_root由宿主显式提供；source是已校验的候选或冻结策略。
# 正式研究通过TDR/REX受管入口执行。
flows = Dataflows(
    base_dir=repository_root,
    space=DataSpace(Path("data/research/S900")),
    providers=ProviderConfig(env_file=repository_root / ".env"),
)
runtime = StrategyRuntime(dataflows=flows)
init = StrategyInit(
    source=source,
    tradable_window=TradableWindow(date(2026, 9, 21), date(2026, 9, 21)),
    data_dir=repository_root / ".tmp/srt/S900/2026-09-21",
)
instance = runtime.create(init)
prepared = instance.prepare_data(policy=PreparePolicy.REUSE)
binding = instance.input_binding
```

初始化参数的业务语义：

- `source`：带实现身份和参数的候选，或 SM 发布的冻结版本；
- `tradable_window`：需要生成执行计划的闭区间，端点必须是`date`类型的可交易日，拒绝字符串和`datetime`；
- `data_dir`：由主调方分配的可写计算工作目录，保存输入绑定与计算上下文；原始数据存放在DFLS数据空间；
- `symbol`：仅用于冻结版本的显式标的绑定；不支持候选策略静默换标的；
- `execution_policy`：只允许在保持原策略执行策略类型不变时覆盖，用于受控复算；
- `source_root/runtime_binding`：用于平台在隔离空间加载拟冻结发布，分别使用源码根目录和
  强类型`RuntimeBinding`；候选拒绝这两项覆盖，普通部署按已认证的发布包加载。

输入范围由策略实现根据交易窗口和交易日历推导。主调方可取得具名请求，与成交回放等业务请求
合并准备；初始信号日和回看窗口仍由SRT负责计算。

## 策略实现契约

每个策略实现必须派生`StrategyImplementation`，并实现五项职责：

1. 类方法`from_parameters(parameters: ParameterSet)`：从显式参数构造同一业务实现，返回本类实例；
2. 只读`definition`：返回`StrategyDefinition`，声明参数、输入、决策、执行、能力、历史及观察契约；
3. `calendar_window(...)`：推导解析交易窗口所需的交易日历范围；
4. `derive_calculation_scope(...)`：推导信号日、初始计算日及每项输入的准确范围；
5. `calculate_history(...)`：使用已准备输入计算渠道无关的目标仓位和诊断信息。

候选和冻结版本通过同一构造方法执行；定义参数必须与输入`ParameterSet`一致。
`StrategyDefinition.observation`必填，使用`ObservationDefinition`绑定解释序列、事实及展示语义。
SRT加载器将业务定义与候选或发布身份组装为`RuntimeDefinition`，策略实现不自行构造运行身份。
支持部署时换标的的实现须显式覆盖`from_parameters_for_symbol`；默认实现明确拒绝换标的。

候选实现只从 `strategy_runtime` 顶层导入策略编写合同。稳定的编写接口包括：

- 定义合同：`CutoffRule`、`InputRequirement`、`InputContract`、`ImplementationRef`、
  `ParameterSet`、`HistoryPolicy`、`DecisionContract`、`ExecutionPolicy`、`MonitoringPolicy`、
  `RequiredCapabilities`、`StrategyDefinition`和`ObservationDefinition`；
- 跨市场对齐：`AlignmentRule`、`InputAlignment`、`AlignedInput`和
  `align_input_history`；
- 计算范围：`CalendarWindow`、`CalculationScope`、`InputRange`、
  `next_session_calendar_window`和`next_session_calculation_scope`；
- 实现与身份：`StrategyImplementation`、`StrategyCandidate`和`implementation_sha256`；
- 运行错误：`RuntimeContractError`和`RuntimeCompatibilityError`。

候选代码只从`strategy_runtime`顶层导入公共符号，不依赖`StrategyLoader`或各内部子模块。
候选由`StrategyRuntime.create(StrategyInit(...))`加载和运行。
候选编号为`C`加四位数字，例如`C0001`；完整引用包含策略ID，例如`S900-C0001`。

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

主调方负责数据空间、取数策略及业务输入清单。SRT公开需求计划，DFLS通过`prepare`将数据写入空间，
通过`fetch(request, prepared=reference)`只读指定准备版本。三个调用场景使用相同接口。

需要把策略输入和成交输入统一准备时，对新建实例执行：

```python
from strategy_runtime import StrategyInputBinding

instance = runtime.create(init)
calendar_request = instance.calendar_request()
calendar_batch = flows.prepare((calendar_request,), policy=PreparePolicy.REUSE)
if not calendar_batch.ready:
    raise RuntimeError(calendar_batch.items)
calendar = flows.fetch(calendar_request, prepared=calendar_batch.reference)
plan = instance.plan_inputs(calendar)

# 主调方可在此合并本次运行的其他数据请求。
batch = flows.prepare(tuple(plan.requests.values()), policy=PreparePolicy.REUSE)
if not batch.ready:
    raise RuntimeError(batch.items)
binding = StrategyInputBinding(plan, batch.reference)
prepared = instance.prepare_data(binding=binding)
```

`StrategyInputPlan`包含具名请求、日历内容身份和计算日期。SRT消费绑定时重新读取其日历，
独立推导并核对整个计划；日历内容、策略身份、窗口或输入需求不同立即失败。固定哈希的本地证据
随发布包改变物理根目录时，仍读取原绑定资产；相对来源路径、来源哈希及其他请求字段必须保持一致，
绑定消费不重新打开物化后的文件。历史深度按首个信号日之前及当日的独立交易日计数，分钟条数不能
替代交易日数。

`prepare_data`必须且只能指定`binding`或`policy`之一。`policy`入口完成上述编排；`binding`入口
不访问供应商。准备成功后，实例固定使用该绑定；同一实例可以再次传入相同绑定，刷新数据则创建新实例。
`data_identity`覆盖策略身份、运行身份、窗口和输入内容。成功只表示声明输入完整可用。

`StrategyInputBinding.to_dict()`和`from_mapping()`供业务清单持久化及跨进程传递。重放时宿主打开
原数据空间、注入DFLS，再显式传入已保存绑定；资产缺失即失败。业务方负责保留被引用的资产。

SRT工作目录只追加可校验的绑定及计算上下文，不另存原始行情CSV，也不按目录或日期自动选择旧版本。
历史文件保留原样，新接口不读取旧准备格式。数据空间及资产管理见[DFLS说明](../dataflows/README.md)。

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

候选`CandidateContentIdentity`包含`content_sha256/source_sha256/dependency_sha256`。
内容身份覆盖参数、输入、决策、执行、监控、能力、历史模式、交易标的、源码闭包、依赖和
扩展载荷，排除机器绝对路径及候选编号。内容相同的不同编号仍有各自登记键；身份计算不写SM。

运行身份由以下内容共同决定：

- SM 冻结版本的 `release_hash`；
- 策略实现及其声明源码闭包的 `source_sha256`；
- 参数身份和完整运行定义。

三者形成`runtime_sha256`。`RuntimeDefinition`只接受schema 3，按完整运行定义及观察定义计算身份。
源码、资源文件或绑定发生变化时须通过获准的当前检验与冻结流程形成新发布；原冻结证据保持不可变。
加载时任何哈希不一致都会失败。

`RuntimeBindingSpec`使用schema 2，绑定`source_files/implementation_sha256/install_files/observation_sha256`；
`RuntimeBinding`再绑定发布ID和哈希。平台从候选定义生成绑定，加载时核对观察定义哈希。
SRT物化`strategy_observation.v1`事实；TDR和PTE各自统一渲染回测及前瞻图，冻结包不绑定策略绘图代码。

冻结版本的可用性以当前治理事实和TDR `strategy_info` API查询为准，不以本说明中的历史版本清单判断。

`StrategyRelease.from_mapping`只接受显式整数`schema_version=5`；旧版本、缺失、
布尔值、字符串或未知版本立即失败。发布记录保存来源实验、候选编号和固定策略载荷；研究检验、
批准与冻结日志独立保存。部署加载核对版本、发布包、运行绑定及部署凭据哈希，不读取研究日志。
TDR技术检验可以在隔离空间验证拟冻结发布包，检验通过不等于已冻结或已部署。
历史发布原件保留供人工查阅，平台不承诺机器复验或在当前运行时执行；升级须单独授权。
