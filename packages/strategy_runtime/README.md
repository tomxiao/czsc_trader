# 策略运行时（Strategy Runtime，SRT）

## 共用账户回放内核

`replay_kernel.run_account_replay(points, driver)` 是批量历史策略和显式状态策略共用的逐步运行器。
每步依次执行事务边界、账户快照、决策、执行和状态提交；只有全部步骤成功才调用账户收尾。
驱动器表达计算及成交模型差异，不拥有另一套完整账户循环。日期模型通过
`AccountPlanExecutor.execute_plan(neutral, model_plan)`接收计划及模型事实，V4权益账户直接消费
`AccountExecutionPlan`；SRT不导入TXE。

`replay_contracts` 的 `ReplayPoint`、`AccountSnapshot`、`ReplayOrder`、`ReplayLeg`、
`CycleBudget` 和 `AccountExecutionPlan` 使用有时区的因果时间、整数数量、显式可用资金和执行腿依赖。
这些类型不固定市场、100股单位或跨交易日执行；具体合法数量、价格和交易时点仍由执行规则认证。
`ExecutionPrecision` 区分交易日范围、K线区间和检查点，不能把范围成交解释成精确时刻。
旧冻结计划通过 `replay_adapters` 投影原有事实，不重新计算仓位、价格或Decimal周期预算。
交易日模型的零点到次日零点区间是日期级容器，不是声明盘中实际成交时刻。

`StrategyInstance.prepare_data(..., persist=False)` 明确选择内存研究准备，完成相同输入认证，
但不保存input-binding文件。`binding`与`policy`仍必须且只能指定一个；既有持久化准备默认行为不变。
批量历史先在准备实例上计算 `WINDOW` 信号，再用
`fork_for_replay(execution_policy=...)` 创建独立账户视图。账户复用已认证输入与批量计算结果，
不重新获取数据、保存绑定、计算全历史或读取源码。公共历史检查仍返回防御性副本。
账户视图只持有不可变策略定义和计算事实，不持有可执行的批量实现及模块全局状态；
未预先计算的历史模式明确拒绝。费用覆盖只改变账户的 `execution_policy`，不改写原策略定义和身份。
依赖真实成交反馈的 `StatefulStep` 则保持每账户独立装载一次、逐步提交状态。

事务边界由明确执行模型声明：单个模拟区间执行及策略状态原子提交；已确认的依赖腿成交
不会因为后腿失败而撤回。共同内核不改变这两类失败语义。循环内不进行数据获取、文件发布或源码装载。


## 跨市场账户研究 V4

新账户定义使用 `EquityStrategyDefinition(contract_version=4)`，运行身份为 `ACCOUNT_REPLAY`。
CN/US共用策略计算、回放内核与计划契约；市场差异由 `ResearchExecutionSpec`、独立交易日历和
逐执行区间约束表达。既有A股 `StrategyCandidate` 与已有美股V2冻结包不自动转换，原有价格单位和身份保持原契约。V1回调与V3研究定义不再接纳。

| 声明 | V4契约 |
| --- | --- |
| `computation` | 必须显式选择 `StrategyComputation.BATCH_HISTORY` 或 `STATEFUL_STEP` |
| 决策时钟 | `BarFrequency.DAILY` 或 `M30`；两者都要求真实交易段、可用时间及完整网格 |
| 输入 | RAW行情、公司行动、日历、逐区间交易规则；辅助行情可声明CN/US来源 |
| 决策 | `AccountDecision`，目标比例为有限的0至1；支持显式订单、依赖腿和周期预算 |
| 状态 | `StrategyStateSchema`及匹配的 `initial_account: StateRecord`；字段非空时必须声明初值 |
| 成交反馈 | `AccountSnapshot`、`PositionFeedback`和已确认的 `RecognizedAccountEvent` |

状态策略入口为 `step(ctx: AccountStepContext, state: AccountStrategyState) -> AccountStepResult`。
V4的 `feedback_mode`固定为 `CONFIRMED_EXECUTION`；旧V2闭合周期模式仅供原冻结合同使用。
`AccountStepResult`返回决策、账户记录及周期记录；仅真实成交改变持仓，全部卖出才关闭周期。
`ctx.position`保留多次加减仓的数量、累计买入成本、卖出收入、费用和成交次数。
框架通过 `ctx.events`提供截至决策时点已确认的拆股、分红应收、支付和交收事实；`event_cursor`
在状态提交时推进，缺失行情导致的抑制不会吞掉事件。策略据此显式调整止损价等自己的字段，
框架不会猜测任意状态字段的价格单位或自动缩放。未来事件和执行区间结束时才到账的资金不会提前进入决策上下文。

批量入口为 `calculate(ctx: BatchAccountContext) -> tuple[AccountDecision, ...]`，按
`ctx.observations`逐项返回决策。每项行情、特征、辅助历史均按该观察时点截断，不提供未来账户和执行报价。
批量计算只适用于不依赖实际成交反馈的信号，不能声明账户或周期状态字段。任意Python实现仍须通过
研究侧前缀／未来扰动检验；拿到全部观察项不等于平台已证明策略不存在跨项前视。

`capital_mode`支持 `target_equity_fraction`、`full_available_cash`及 `signal_cash_fraction`。
比例模式允许加减仓；全现金模式持仓后目标1表示继续持有，不因股息或剩余现金自动追加投资。
显式 `ReplayOrder`数量与目标比例分别留证；`ReplayLeg`声明真实检查点、提交区间及前腿所需结果。
周期预算以Decimal保留，不能中途重写已锁定预算；可卖数量、整手、余股清仓及价格限制由TXE逐步执行。

日线策略若需开盘、11:30等盘中检查点，声明
`execution_input=ExecutionInput(instrument, source, BarFrequency.M30)`。
该产品只供执行器读取，独立绑定行情和会话哈希，不进入特征或辅助历史；不从日线OHLC推测盘中成交。
同一精确产品不能同时声明为执行与辅助角色。普通订单仍按主决策柱的价格区间执行。
V4研究回放沿用一次装载、不可变可见历史、内存复用和完整证据闭包；生产加载与PTE准入仍需另行支持。

## 可见特征与显式状态

V4通过完整研究回放事务执行；生产加载和独立 `plan(...)`不接纳研究定义。
特征类型位于 `equity_features`，准备及可见性基础位于 `equity_replay`，
决策／状态上下文位于 `account_strategy`，共用生命周期驱动位于 `account_replay`。
旧V1回调与V3回放循环、类型及计划投影已删除；已有V2冻结运行独立按其合同加载。

```python
graph = FeatureGraph(
    nodes=(
        RawField("close", BarField.CLOSE),
        RawField("high", BarField.HIGH),
        RawField("low", BarField.LOW),
        TrueRange("tr", "high", "low", "close"),
        Mean("atr13", "tr", 13),
        Lag("atr_before_prior", "atr13", 2),
    ),
    outputs=("close", "atr13", "atr_before_prior"),
)
```

支持的有限窗口节点为 `RawField(key, field)`、`Lag(key, source, bars)`、
`TrueRange(key, high, low, close)`、`Mean(key, source, window)`、
`SameLocalSlotMedian(key, source, sessions=20, anchor_lag=1, timezone="America/New_York")`。
同槽中位数的 source 必须为原始 Volume 节点；取锚点当天之前、相同美东 RTH 起始时刻的不同实际交易日，
缺槽不补零，DST 通过当地时区处理。图拒绝未知节点、缺失依赖、循环和非法窗口，不接受任意 Python 算子。

数值版本 `FLOAT64_CHRONOLOGICAL_V1` 固定均值为在绑定的 Python 运行环境中，
将窗口转换成按时间顺序的 Python float 后执行 `sum(values) / window`；
保留 Python 3.12 的补偿求和行为，不用 NumPy 归约、前缀和或增减滚动和替代。
首根 TR 缺少前收盘时为未就绪。
`ctx.features.get(key)` 返回 `ReadyValue(value)` 或 `NotReady`，未就绪不是信号为假。

可见时间取 `max(Date, AvailableDate + latency)`。运行器按可见事件推进有序索引，所有 Lag 和窗口
均针对当前决策可见、按 Date 排序的 OBSERVED 序列。较早柱晚到时，只影响此后决策的当前特征；
已经返回的 FeatureView 不被改写。不能把按全历史预计算的特征列遮住不可见行来替代这个语义。
当准备数据的有效可见时间经认证为非递减时，每次可见历史都必然是观察序列的一个前缀，
相同特征图可在回放初始化时生成因果特征列。Raw/Lag/TR 和同槽中位数按列计算，Mean 仍对每个固定窗口
使用上述 Python float 规则。非单调到达保持逐时点求值；这是同一算子的内部计算选择，不提供用户切换模式。

`ctx.history` 保留完整可见历史。`last(0)`、`last(1)` 返回最近两根观察柱的只读 Mapping；
`to_frame(tail=None)` 显式生成独立 DataFrame 副本，`tail=N` 仅返回末尾 N 根。
DataFrame 物化本身包含遍历和复制成本，频繁导出完整历史仍可能产生二次增长，不能承诺任意策略秒级。
持有旧视图不会看到后续到达数据，也不能通过改动导出副本污染准备数据。
内部根据已认证的到达顺序选择不可变追加链或持久化有序树，不提供用户切换模式。
有效可见时间非递减时，N 行历史的可见性推进总计 O(N)，观察序列的 Lag 索引为 O(1)；
存在晚到插入时保留有序树及秩索引，单次插入 O(log N)，晚到数据的可见语义不变。
顺序历史导出最近 k 行的遍历为 O(k)，完整导出为 O(N)；旧视图、复制及序列化仍保留各自时点的历史。
两种结构都只包含当时已可见行；策略视图不持有完整未来数组的引用，
也不提供 BarStatus、ExecutionBlocked 等执行专用注释。行视图直接委托底层只读 Mapping，保持不可变性。

### 状态与成交事务

`StateField(key, StateValueType, nullable=False)` 声明严格字段类型；BOOL、INT、FLOAT、STR、DATETIME
不相互隐式转换，浮点必须有限、时间必须带时区。`StrategyStateSchema(account_fields=(), cycle_fields=())`
覆盖全部字段；`StateRecord(values=((key, value), ...))` 是不可变标量记录，不接受任意对象或隐式附加字段。
账户字段非空时，调用方必须明确提供符合 schema 的初始账户记录。

```python
def step(ctx: AccountStepContext, state: AccountStrategyState) -> AccountStepResult:
    # decision 必须是带结构化事实的 AccountDecision。
    # cycle_values 是本次观察后的提议，不代表买单已成交。
    return AccountStepResult(decision, account=StateRecord(), cycle_values=proposed_cycle_values)
```

`AccountStrategyState`包含revision、account、cycle、binding和event_cursor。`CycleState` 包含平台真实 cycle_id、
entry_at 与策略 values。首次真实买入后才激活 cycle；买单未成交不会启动周期。
已有持仓的卖单未成交时，仍保留提议中的止损锁存等观察状态；实际全部卖出后才清除 cycle。
空仓准备买入和已有持仓均要求显式 `cycle_values`，即使 schema 为空也传入 `StateRecord()`。

每个执行区间以 TXE `transaction()` 包含决策前事件应用、step、执行、实际成交归并及状态提交。
失败时撤回本区间账户、账本、幂等键与状态；成功的前序区间保持已提交。
`ReplayFailure` 通过 `committed_state`、`next_execution_start` 和 `cause` 显式交接失败位置，
不自动重试、不返回伪成功；KeyboardInterrupt/SystemExit 保持取消语义。
同一 executor 的显式重试必须使用同一候选、账户 owner、交易合同、费用和准备数据身份。
binding 覆盖上述身份，替换输入后不能承接旧状态。
受管检查点当前按完成账户恢复；需要中途交接时，调用方保存异常给出的状态及匹配执行事实。

### 准备、辅助上下文与执行

```python
prepared = PreparedReplay.from_frames(
    bars, constraints, graph, latency_seconds=0,
    frequency=definition.execution_spec.decision_clock, timezone=definition.instrument.timezone,
    auxiliary_histories=auxiliary_frames, sessions=session_frame,
    trading_sessions=certified_calendar,
)
outcome = run_replay(
    prepared, candidate, executor, start=start, end=end, fee_rate=0.001,
    initial_state=None, owner=None,
)
```

准备阶段认证时间和 OHLCV、构建可见性及本地槽位索引，并固定原始数据、交易约束和延迟的摘要。
已确认为带时区 datetime 类型的列批量转为 Python datetime；字符串及其他时间输入保留原解析路径，
时间精度处理、无效时间拒绝和准备数据身份不变。这些是内部计算优化，不改变数据合同或晚到语义。
身份 JSON 对原生 `datetime` 且 `tzinfo is UTC` 的值直接使用 `isoformat()`；其余类型沿用原转换，规范字节、非有限值拒绝及 Timestamp 亚微秒处理不变。
`prepared.with_graph(graph)` 共享这些不可变输入，不能改变候选声明的特征图。
辅助行情仍需显式声明；`ctx.auxiliary_histories[name]` 提供完整可见 HistoryView，保留最新柱状态、
warmup 和 max_age 检查。首版主特征图不隐式读取辅助别名，辅助指标由策略显式访问视图计算并承担相应成本。
session 上下文通过认证日历的精确执行区间索引选择，并核验日历可见时间。

`ReplayOutcome` 返回原 TXE `execution_result`、最终 `state` 和 `statistics`。
统计包含 `feature_seconds`（特征图初始化/因果列生成、主特征及辅助/session上下文）、`replay_seconds`（含启动源码装载、策略、TXE及结果表构造）、
执行区间 `rows` 和实际调用 step 的 `decisions`；准备耗时应由调用方另行计时。
`source_checks` 为 0，回放不逐步重读或检查源码；`source_bytes_read` 记录本账户作用域启动时
实际读取的声明源码字节数，不表示物理磁盘 I/O 次数或磁盘吞吐。
`module_loads` 记录账户作用域的入口模块装载次数，默认且正常完整回放为 1；相对导入的辅助模块不另计次数。
缺失/零量完成柱引起的抑制区间不调用 step，仍由公共 TXE 执行 WAIT 并记录账户状态。

owner 默认候选编号；共享基准必须传独立基准身份，不能把研究候选编号加入其计划与账本身份。
每个账户启动时读取全部声明源码，固定内存快照，只装载一次入口模块并在整个账户回放中复用。
回放运行器不重复调用候选 verify，也不进行源码身份或元数据检查；身份认证保留在 TDR 准备、候选构造和登记等原有边界。
后续相对导入同样从启动快照装载；启动后修改或删除磁盘源码不改变本次回放，下一账户启动时读取当时的声明文件。
同一账户的模块全局变量跨 step 保留，不同账户使用独立命名空间；成功、装载失败或 step 异常退出均清理命名空间及导入器。
模块全局变量不属于 TXE 事务或 `StrategyState` 检查点。需要成交归并、失败回滚或中途恢复的策略状态仍必须通过显式状态字段表达。
`EquityDecision.from_facts` 对完全相同的普通字符串键与文本复用不可变依据对象，缓存最多 4096 项；
事实仍逐次转为原始字符串，保持输入顺序、完整强类型解释及原有校验。字符串子类沿用直接构造，不引入额外哈希或相等比较。
复杂度由可见事件索引、声明窗口、显式历史导出和状态大小共同决定；有限窗口不会自动使任意 Python 策略达到固定耗时。

本文面向策略研究员（RSCH）。安装、源码维护及包级验证见
[DEV Agent](../../docs/DEV_AGENT.md)。

SRT 是研究、回测、模拟交易及未来实盘共用的策略计算锚点。它把一个候选或冻结策略转换为
`StrategyInstance`。实例推导数据需求、认证主调方绑定的数据并执行策略计算，输出与渠道无关的执行计划。

SRT 不管理策略生命周期，不评价策略优劣，也不记录成交和账户账本。SM 管理策略身份与治理，
SE 负责数值评估，TXE 和 PTE 分别负责历史执行与模拟交易执行。

RSCH通过显式源码绑定构造`StrategyCandidate`并复用同一实现进行研究评价。正式研究运行通过
TDR/REX受管入口；候选登记、首次检验冻结及同版本发布包升级见[TDR说明](../../src/czsc_trader/README.md)。
升级生成新的内容身份并归档原包，部署和生产账户切换分别授权；版本号相同不代表运行内容相同。

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

## 平台技术检验边界

`validate_release_package(strategy_root, release_id) -> VerifiedReleasePackage`供正式部署与隔离检验
共用。它认证实际schema 5版本、manifest、完整文件清单、运行绑定和源码闭包，返回
`release/package_sha256/runtime_binding/source_root`。该认证不授予模拟交易资格，也不生成部署回执。
`load_strategy_deployment`继续要求正式回执；共享认证按manifest声明的安全相对路径读取，
既有冻结发布文件与内容身份无需改写。

平台构造`InspectionRuntimePermit`，将run、发布、包、协议和受管临时根绑定。PTE以
`StrategyRuntime(strategy_root, inspection_permit=permit)`进入检验路径；每次描述或实例化发布
都会通过`load_inspection_deployment`重验实际包和隔离根。显式源码覆盖也必须与认证包一致。
技术许可不写成正式部署回执，普通入口不接受技术许可封套。许可不替代PTE自身的隔离账户准入。

`InspectionControl/InspectionProgress/InspectionStage`提供无宿主依赖的预算、取消和进度类型。
`ExecutionResources`是研究执行的共享资源契约，包含`max_workers`、
`native_threads_per_worker=1`和`random_seed=0`。它与`InspectionControl.max_workers`
均默认使用`max(1, os.cpu_count() * 75 // 100)`；16个逻辑核默认12个工作进程。
默认值在构造时读取本机，显式指定`max_workers`可覆盖；无法识别逻辑核数时拒绝默认构造，
要求显式提供预算。该预算表示并发上限，不是CPU使用率保证，实际并发还受独立任务数量限制。
同一执行会话及其子任务共享预算，不在嵌套阶段再次申请75%；不同顶层会话各自管理预算。
`InspectionEnvironment/ImplementationFileIdentity`记录实际执行环境；
`collect_inspection_environment(repository_root)`从当前解释器解析到的平台包源码位置采集清单和
精确依赖版本，数据仓库或隔离仓库路径不能替代执行文件身份，Git提交仅作辅助信息。
环境配置摘要覆盖固定的检验协议、渠道模型和准入模型；请求预算和场景配置在各自运行记录留证。

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

## 策略信号解释

`SignalPanelDefinition.explanation`声明三栏解释，使用`SignalExplanationDefinition(state_key, cases)`。
`state_key`引用已有`SignalStateDefinition`；`SignalExplanationCase.key`必须完整且唯一覆盖该状态的选项。
每个分支声明`judgment`、非空`basis`、`next_watch`及`explanation`，分别表示当前判断、依据、接下来关注
和详细说明。平台不按策略名称或数值重新推断交易原因。

正文使用`SignalText(parts)`，`parts`为纯文字和以下强类型引用的元组：

| 引用 | 来源 |
| --- | --- |
| `SeriesValueRef(series_key)` | 本次已声明数值，继承序列分组的单位与精度 |
| `GuideValueRef(series_key, guide_key)` | 本次参考线数值，继承相同单位与精度 |
| `StateValueRef(state_key)` | 本次状态选项的标签，可用于明确说明条件是否达标 |

不存在表达式求值、HTML、Markdown或脚本执行接口。文字按纯文本显示；参数阈值应通过引用填充，
不能在多份模板中手写。数值参考线应由策略当前参数或实际交易计算证据生成。示例：

```python
from strategy_runtime import (
    SignalText, SignalBasisDefinition, SignalExplanationCase,
    SignalExplanationDefinition, SeriesValueRef, GuideValueRef,
)

# 绑定到声明中的 decision 状态；该示例状态仅有 wait 一个选项。
explanation = SignalExplanationDefinition("decision", (
    SignalExplanationCase(
        "wait",
        SignalText(("暂不满足入场条件",)),
        (SignalBasisDefinition("entry", SignalText((
            "当前得分 ", SeriesValueRef("score"),
            "；入场门槛 ", GuideValueRef("score", "entry"),
        ))),),
        SignalText(("关注得分是否达到 ", GuideValueRef("score", "entry"))),
        SignalText(("得分描述模型定义的条件，不是上涨概率。",)),
    ),
))
```

`StrategyImplementationV2.observation_history(inputs, context, history)`接口不变。RSCH读取交易计算
已产生的原因码、条件结果和参数事实，返回声明所需的`obs_`字段，不能复制一套决策规则或修改交易历史。
解释采用实际命中的分支；模型入场、退出与账户成交分别表达。平台提供字段、引用和状态一致性校验；
RSCH负责金融含义、阈值边界、规则优先级及完整状态覆盖的审查。

观察声明和实现由RSCH随策略代码维护，可以沿正常继承链组织。交付时应使用实际交易分支产生的
事实验证入场、持有、各类退出、阈值边界及不可用状态；策略修改后的等价性结论也由RSCH负责。
SRT只认证新实现自身的类型、引用、源码和运行身份，不判断它是否与原实现具有相同金融逻辑。

`observe_execution_plan(definition, plan)`是运行消费者的统一入口，返回`StrategyObservation`或
`ObservationUnavailable`。它在异常隔离区外严格校验运行定义与执行计划身份；身份错误仍抛出异常。
只有之后的观察计算、解释解析和显示字段校验错误转为明确不可用，不影响已成功计算的交易计划。
`materialize_observation`保留严格抛错语义，适用于契约校验。所选解释引用`UNAVAILABLE`事实时整项观察
不可用；`INACTIVE`引用明确显示“不适用”，不替换为零。选择状态不可用、未知或缺失时不能生成解释。

解释快照`SignalExplanationSnapshot`保存`state_key`、`case_key`、已解析的三栏正文及详细说明，
`basis`为`SignalBasisSnapshot(key, text)`元组。回放消费当时快照，不用当前参数或代码重算历史文案。
带解释的声明和观察使用`strategy_observation.v4`；v2旧观察、v3旧面板仍按各自明确契约只读，
不得把新增解释塞入v3或将缺少解释的v3改标为v4。旧记录不自动补造解释，旧声明和哈希保持不变。

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
逐日计划按有序历史的位置读取当前及前一期目标，避免每天移动完整目标序列；第一期仍以前值0处理，
策略显式提供的动作保持优先。历史计算入口和诊断输出的必要隔离保留，避免策略修改输入污染其他模式或实例。
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

`FROZEN_RULE`的目标仓位与资金模式须配套声明：

| `capital.mode` | `target_scope` | 仓位语义 |
| --- | --- | --- |
| `full_available_cash` / `available_cash_fraction` | `entry_cycle` | 仅接受0/1目标；按既有开仓周期目标份额买入或补买，0表示清仓 |
| `target_equity_fraction` | `decision` | 接受有限的0至1目标比例；每次决策按当前实际现金与持仓重新计算目标份额，支持加仓、部分减仓与清仓 |
| `signal_cash_fraction` | `entry_cycle` | 策略每次开仓指定可用现金比例；采纳计划时锁定预算和目标份额，后续仅按剩余预算补买，退出结清后释放 |

多档位模式须显式设置`allocation_fraction=1`，例如：

```python
capital = {
    "mode": "target_equity_fraction",
    "target_scope": "decision",
    "allocation_fraction": 1.0,
    "fee_rate": 0.001,
}
```

设可用现金为C、实际份额为Q、同账户价格口径的信号日执行参考价为P、目标比例为w、整手单位为L，
目标份额为`floor((C + Q * P) * w / (P * L)) * L`。买入数量另受委托价含费现金上限限制；
减仓只卖出实际份额与目标份额的差额。比例不变时，价格变化也可能触发再平衡。
费用、整手取整、未成交及次日成交价格变化均可能使实际仓位比例偏离信号目标；目标比例不保证精确成交比例。
该模式不沿用上次开仓周期目标来限制新目标。非法比例或资金模式组合明确失败。

### 信号指定周期投入比例

使用`DecisionContract("CYCLE_TARGET", 0., 1., "NEXT_SESSION")`，资金声明为：

```python
capital = {
    "mode": "signal_cash_fraction",
    "target_scope": "entry_cycle",
    "fee_rate": 0.001,
}
```

该声明禁止静态`allocation_fraction`。策略历史须同时输出二元`target_position`与
`entry_allocation_fraction`：正目标必须给出有限的`(0, 1]`比例；零目标的比例为空值。
SRT将其校验为公开强类型`CycleTarget(active, entry_fraction)`。比例不能从观察/诊断字段推断。
固定比例对照也通过该列明确输出常数，从而在同一资金契约下比较。

`plan_at(point, portfolio, state)`仍为纯计算。首份开仓计划被执行宿主采纳后，
`ExecutionState.entry_cycle`保存`EntryCycleState`：周期及开仓信号身份、分配比例、
含买入费用的现金预算、目标份额、实际累计买入成本及`ACTIVE/EXITING`阶段。
其数量与`cycle_target_quantity`一致；新模式不能从旧目标数量或已有持仓猜测预算。
`EntryCycleState.to_dict()/from_dict()`使用显式字段及十进制字符串。

首次预算为可用现金乘信号比例，目标份额按限价、费用和整手规则向下取整。
后续补买同时受剩余目标份额、剩余预算及实际可用现金限制，不再次乘开仓比例。
日内价格变化、持有期间的新比例都不重设该周期的预算或目标，也不触发每日再平衡。
实际买入成本按确认成交和费用累计；异常实际费用导致超预算时保留事实，剩余可买预算为零。

`ExecutionPlan`明确携带`cycle_target`、`entry_cycle_before`、`entry_cycle_after`和
`cycle_status`。后者为`OPEN/HOLD/EXIT/IDLE/INSUFFICIENT_LOT/BUDGET_LIMIT`，
表达周期计划结果，不表示订单已成交。预算不足一手时不建立周期；需要退出时进入
`EXITING`，即使随后收到正目标也继续退出。持仓归零且相关委托终结后由宿主释放周期。
未知委托/成交状态不允许推断为已结清。计划采纳验证旧状态，成交增量更新新状态，二者均须幂等。

信号身份包含当日`CycleTarget`，计划身份包含前后周期事实、状态、实际可用现金和费用率。相同比例的不同周期、
相同目标但不同预算的计划不可混用。新模式字段缺失、旧状态混入或预算/份额越界明确失败。
`validate_entry_cycle_plan_facts(...)`是SRT计划与PTE接收/采纳共用的纯校验入口，
显式接收类型化目标、前后周期、状态、仓位/目标数量、比例/现金/费用、信号身份及订单。
它验证唯一合法阶段转移、开仓/补买数量、预算及订单方向，不修改账户，也不代替宿主核验
账户归属、状态版本和未终结委托。`CYCLE_TARGET`与`signal_cash_fraction`必须双向配套声明。
现有固定比例周期与权益再平衡模式维持各自业务语义；新模式的预算上限使其补买路径可能与
旧固定比例模式不同，研究对照须统一资金契约，不能假定逐笔等价。

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
源码、资源文件或绑定发生变化时，须通过获准的首次冻结或同版本升级入口形成新发布，不能直接修改
当前包后继续使用旧身份。原包及历史证据保持不可变；加载时任何哈希不一致都会失败。

新增多档位资金模式不会自动改变既有冻结策略的执行定义。启用该模式须由新实现显式声明，
由责任方完成适用验证并按授权形成新发布身份。PTE消费该模式前也须升级到支持该资金契约的版本，
旧PTE会拒绝未知资金模式。现有发布是否可用仍以其身份、加载及相应执行验证为准。

`RuntimeBindingSpec`使用schema 2，绑定`source_files/implementation_sha256/install_files/observation_sha256`；
`RuntimeBinding`再绑定发布ID和哈希。平台从候选定义生成绑定，加载时核对观察定义哈希。
SRT物化版本化观察事实；新解释使用`strategy_observation.v4`，旧v2/v3记录按其原合同读取。
TDR和PTE通过共享图表组件渲染回测及前瞻图，冻结包不绑定策略绘图代码。

同版本升级由TDR的`prepare_frozen_runtime_upgrade`和`apply_frozen_runtime_upgrade`组织。
输入为强类型`StrategyCandidate`，不强制先登记候选或取得技术检验PASS；SRT负责生成及校验新包的
源码闭包、运行绑定和观察身份。TDR归档旧包、授权与验证材料并记录提交事实，不裁决研究结论。
升级回执`COMMITTED`不授予PTE资格；新发布哈希的准入、部署及账户改绑另行处理。

冻结版本的可用性以当前治理事实和TDR `strategy_info` API查询为准，不以本说明中的历史版本清单判断。

`StrategyRelease.from_mapping`只接受显式整数`schema_version=5`；旧版本、缺失、
布尔值、字符串或未知版本立即失败。发布记录保存来源实验、候选编号和固定策略载荷；研究检验、
批准与冻结日志独立保存。部署加载核对版本、发布包、运行绑定及部署凭据哈希，不读取研究日志。
TDR技术检验可以在隔离空间验证拟冻结发布包，检验通过不等于已冻结或已部署。
历史发布原件保留供人工查阅，平台不承诺机器复验或在当前运行时执行；升级须单独授权。

## 既有V2冻结／PTE区间决策

`ResearchExecutionSpec`、`EquityCandidate` 和 `EquityStrategyInstance` 提供显式市场与时间合同的研究规划。
原 A 股策略及冻结运行时不变。输入、支持范围及因果时序见[TDR美股研究接口](../../src/czsc_trader/README.md#us-equity-research)。

以下仅说明既有V2冻结／PTE的运行合同；新研究统一使用上文V4，不能据此重建旧研究入口。

### 冻结V2定义与加载

`EquityStrategyCandidate` 与研究专用函数式 `EquityCandidate` 明确区分。正式定义使用
`EquityStrategyDefinition`：标的、执行合同、预热、`module:function` 入口、相对源码清单、
`equity_source_hash` 源码闭包哈希、有限 JSON 参数及精确 `ImplementationDependency`。
`definition.to_dict()/from_dict()` 可序列化；`definition.content_identity` 不依赖机器路径和候选名称。
本地源码采用相对导入并纳入清单，外部导入须有已安装且版本一致的声明依赖。

函数 `decide(context: EquityDecisionContext) -> EquityDecision` 接收因果历史、不可变参数、
交易点和权威账户快照，返回整数 0/1 目标及非空 `reason`。每次决策使用独立模块命名空间，
不以模块全局变量保存跨决策状态。账户提供周期进入时间、成本和反馈来源；区间成交时点不解释为逐笔时点。
`StrategyRuntime.identify/create/describe` 支持正式候选；加载、登记和运行前认证源码与依赖。
`EquityInputBinding` 绑定四类准备产品的内容身份、执行合同和预热，可序列化供回放复用。

声明 `auxiliary_inputs` 或 `session_context` 时，`build_equity_decision_context` 按决策时点
构造辅助行情与当前交易会话；直接调用候选 `decide` 也重新检查这些输入。辅助行情按完成时间和
可得时间共同截取，检查预热、最大年龄、OHLCV、金额和最新观察状态；传入策略的是独立副本。
日历仍须整体满足类型、顺序、唯一性及表与会话一致性，30分钟日历还要求所有时段完整整除。
当前执行区间必须精确属于唯一会话；半日市、时区变化及分段休市不能通过推测补齐。
上下文计算的性能优化不改变上述拒绝条件，不缓存调用方的可变行情，也不改变历史证据身份。

正式美股定义还固定 `parameter_schema_json`（类型、可选上下界或枚举）、`feedback_mode`
及 `analysis_price=RAW`。未显式提供参数 schema 时以初始参数的实际类型建立不可变类型声明；
后续参数变更仍须满足同一 schema。MARKET_INTENT 不向策略暴露账户快照。
`CONFIRMED_EXECUTION` 仅提供原有持仓反馈；需要最近一次真实完成周期的定义须显式声明
`CONFIRMED_CLOSED_CYCLE_V1`，该声明进入内容身份。新模式要求
`EquityPortfolio.closed_cycle_feedback: EquityClosedCycleFeedback`：外层 `None` 表示执行器没有该能力，
运行时明确拒绝；`latest=None` 表示能力可用但尚无完成周期。`latest` 为不可变 `EquityClosedCycle`，
记录周期标识、真实买入和清仓的成交区间、原始买入数量、含买入费的总成本及退出决策观察截止时间。
区间统一为 UTC，满足 `entry_interval.end <= exit_observed_through <= exit_interval.start`；
退出区间完成且退出观察范围不超过当次决策观察范围后，策略才可消费该事实。直接调用 `decide` 同样校验。
该事实不包含止损原因或止损线；策略用当时可见行情和参数自行重建条件。旧模式不向策略暴露新增周期事实。
正式 `EquityDecision` 必须包含共享 `SignalExplanationSnapshot`，其 target 状态与 flat/long 分支
必须匹配；可用 `EquityDecision.from_facts(..., facts={...}, next_watch=...)` 从当次条件／参数
建立结构化依据。解释进入计划及账户证据；平台核验结构和状态，金融解释由 RSCH 负责。

### 显式行情缺口研究口径

DFLS 的 `UsEquityBarPolicy` 在美股行情上标记 `BarStatus`。运行窗口只向策略传递已完成、已可得的
`OBSERVED` 行，不传入缺失、零量行或执行阻断标记。预热按有效观察数计算；不足时明确失败。
如果最新已可得行情为 `MISSING` 或 `ZERO_VOLUME`，平台不调用策略，记录
`signal_status=SUPPRESSED_UNOBSERVED_BAR`、`side=WAIT` 的零数量计划；该计划没有策略解释，
不代表策略改变目标，原持仓保持。新的有效行情完成后恢复调用。正常调用标记为 `EVALUATED`。

当前执行区间的行情缺口或已知中断只交给执行器判断成交，不能据此提前撤销区间开始时的决策。
因此缺口首段可能存在有效下单尝试，但最终未成交；平台保留该尝试及失败原因。
未显式启用政策的严格数据路径及原 A 股运行路径不变。
直接调用 `plan` 时也过滤历史缺失、零量行；最新观察无效则明确拒绝生成信号。
窗口中的自动等待由 `run_window` 负责，调用方不能把缺失行情直接交给策略。
