# 策略运行时（Strategy Runtime，SRT）

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

## 美股区间决策补充

`ResearchExecutionSpec`、`EquityCandidate` 和 `EquityStrategyInstance` 提供显式市场与时间合同的研究规划。
原 A 股策略及冻结运行时不变。输入、支持范围及因果时序见[TDR美股研究接口](../../src/czsc_trader/README.md#us-equity-research)。

### 美股正式策略定义与加载

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

正式美股定义还固定 `parameter_schema_json`（类型、可选上下界或枚举）、`feedback_mode`
及 `analysis_price=RAW`。未显式提供参数 schema 时以初始参数的实际类型建立不可变类型声明；
后续参数变更仍须满足同一 schema。MARKET_INTENT 不向策略暴露账户快照。
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
