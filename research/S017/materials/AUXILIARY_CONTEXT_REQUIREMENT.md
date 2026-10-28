# S017：辅助价格与当日会话上下文需求

2026-10-29。RSCH需求核验，DEV实施交接。

用户已明确授权暂停研究，先补齐平台基建，在当前分支实施。本文件固定业务边界与验收范围；
平台按下述契约实施，并使用合成夹具聚焦验证；未取得辅助标的真实行情或启动新研究账户。
工程开发及聚焦验证不消耗新增最多20轮研究额度，目前该额度未消耗，也未创建新研究实验。

## 1. 需要支持的研究操作

1. 正式评价仍只交易LITE。策略可声明SPY、QQQ或明确行业ETF的辅助价格，读取截至决策时实际可用的历史，
   研究相对强弱或市场背景。辅助标的不下单、不占资金、不形成组合。
2. 策略可读取当日已知交易会话结束时间，区分正常交易日与半日市，选择最后可执行30分钟区间前退出。
3. 主账户、同条件买入持有、费用、限价规则、公司行动及正式证据链继续使用公共SRT/TXE/TDR链路。

此处只确认平台能力，不选择行业代理、不认定辅助条件有收益、不把基本面事件纳入交易规则。
真实供应商权限、具体ETF可用日期、价格调整方式及行业代表性，仍需后续获准的数据准备和研究核验。

## 2. 实施前缺口与职责边界

|层|原有能力|实施前阻断/保留边界|
|---|---|---|
|DFLS|`InstrumentId`支持US股票及ETF；`EquityDataRequest`独立声明标的、来源修订、产品、日期、30分钟或日频；`prepare/fetch`绑定精确准备引用|尚未核验拟选辅助标的真实供应商覆盖，不能把适配器存在当成数据已就绪|
|TDR|正式请求对交易标的准备行情、会话、行动、约束；固定输入与审计身份|`EquityEvaluationRequest.requests()`只使用`candidate.instrument`，无辅助输入声明、分标的绑定或传递|
|SRT|`EquityDecisionContext(history, portfolio, point, parameters)`；主行情按完成及可用时点截断|无辅助行情集合及当前会话字段；`EquityInputBinding`严格只含四类主产品身份|
|日历|DFLS识别正常日09:30—16:00、半日09:30—13:00；时区与夏令时正确进入执行网格|TDR只核对各产品日历一致性，没有把会话事实传给决策函数|
|TXE|市价卖出按下一执行区间模型开盘价成交，受可交易性/量/缺口限制|没有收盘竞价/MOC订单，也不保证任何退出意图一定成交|

源码依据：

- [DFLS权益类型](../../../packages/dataflows/src/dataflows/equity_contracts.py)：`AssetClass`、`TradingSession`、`EquityQuery`。
- [Futu权益适配器](../../../packages/dataflows/src/dataflows/futu_equity.py)：`futu_equity_bindings`及`trade_date_type`处理。
- [DFLS发布校验](../../../packages/dataflows/src/dataflows/equity_data.py)：标的身份、独立日历网格与可用时间校验。
- [正式评价入口](../../../src/czsc_trader/research_tools/equity_evaluation.py)：`EquitySources`、`EquityEvaluationRequest.requests`、`prepare_equity`、`evaluate_equity`。
- [SRT正式定义](../../../packages/strategy_runtime/src/strategy_runtime/equity_definition.py)：`EquityDecisionContext`、`EquityInputBinding`、`EquityStrategyDefinition`。
- [SRT时序](../../../packages/strategy_runtime/src/strategy_runtime/equity.py)：`run_window`和`plan`。
- [TXE执行](../../../packages/trading_execution_engine/src/trading_execution_engine/equity.py)：实际成交及缺口处理。
- [TDR接口说明](../../../src/czsc_trader/README.md#us-equity-research)、[SRT说明](../../../packages/strategy_runtime/README.md#美股正式策略定义与加载)、[DFLS说明](../../../packages/dataflows/README.md#市场限定的权益数据产品)。

原先可以独立准备/读取辅助价格做研究描述，但不能通过正式API把它们变成LITE决策输入。
本次补齐声明、绑定、决策及认证链路。独立数据读取不等于正式策略可使用，不能将辅助历史数组塞入源码、参数或私有文件，不能在决策函数中连接供应商，
也不能利用行情允许额外列的实现细节绕过辅助产品身份及时间校验。

## 3. 实施契约

以下为本轮实现的API契约，复用既有产品、准备空间和时间类型。

### 3.1 策略声明

新增不可变强类型`EquityAuxiliaryInput`，每个声明代表一个必需的辅助价格输入：

```python
@dataclass(frozen=True)
class EquityAuxiliaryInput:
    name: str
    instrument: InstrumentId
    source: SourceRef
    frequency: BarFrequency
    warmup_bars: int
    max_age_seconds: float
    analysis_price: str = 'RAW'
```

- `name`为稳定、唯一的非空名称，例如`market`；名称不能覆盖主行情或账户字段。
- 本轮仅允许US股票/ETF及`M30/DAILY`；交易标的仍只允许原LITE，辅助声明不得改变执行标的。
- 来源修订必须显式固定；`warmup_bars`为正整数，`max_age_seconds`为有限非负数。
  行情和会话共用该来源；可用时间额外延迟复用执行契约的`data_latency_seconds`。
- `max_age_seconds`按决策时间减最新可用辅助柱结束时间计算，是显式研究容忍度，周末/假日也计入。
  调用方须按所选频率设置，不默设延用前值。该容忍度不允许忽略已应出现却缺失的辅助柱。
- `analysis_price='RAW'`固定生成`PriceAdjustment.NONE`请求。ETF分红导致的原始价格跳变不等于总回报，研究需说明价格收益口径；
  本轮不顺带扩展可回溯复权或总回报指数合同。
- 辅助准备沿用请求`history_start`与评价结束日；不足时明确失败，不自动向前扩展或缩短评价窗口。

在`EquityStrategyDefinition`增加显式会话开关及声明：

```python
auxiliary_inputs: tuple[EquityAuxiliaryInput, ...] = ()
session_context: bool = False
```

辅助输入和会话可以独立启用；空辅助声明及`False`会话开关在序列化中省略，以保持旧定义身份。
开关、声明及来源修订进入候选内容身份。既有参数schema、账户feedback_mode及解释契约保持各自职责，
不把行情输入伪装成策略参数或执行反馈。

### 3.2 准备与精确绑定

正式`EquityEvaluationRequest`继续从候选定义推导请求；原四类产品仅属于交易标的。
每项辅助声明增加`BARS`和`SESSIONS`两个独立`EquityDataRequest`，使用自己的标的、来源、频率。
辅助行情只用于观察，因此不强制要求其交易约束或支付型公司行动产品，不创建辅助账户。

同一个正式准备引用必须包含全部声明产品，worker只读准备资产。已经固定的旧LITE准备引用不被改写：
新增辅助数据应形成新的准备引用，可以复用原LITE资产，但必须重新绑定全部声明。
不得因为旧引用缺少辅助数据而静默忽略声明、网络补取或退回纯LITE策略。

扩展`EquityInputBinding`，保留主`content_identities`四项原语义，增加辅助绑定元组：

```python
@dataclass(frozen=True)
class EquityAuxiliaryBinding:
    input: EquityAuxiliaryInput
    bars_sha256: str
    sessions_sha256: str

# EquityInputBinding新增；prepared仍为整体精确准备引用
auxiliary_inputs: tuple[EquityAuxiliaryBinding, ...] = ()
```

每个名称必须恰好绑定一次，来源/标的/频率/范围与声明一致。不能把多个辅助内容哈希混成一个未声明列集。
声明的`data_key(product)`提供稳定产品键，`requests(start, end)`生成两项公开DFLS请求；
TDR的`request_items(specification)`返回有序`(key, request)`，主四产品键不变。
绑定的`request_key(request)`认证请求，`expected_identities`暴露主辅产品精确哈希映射。
正式请求身份、结果证据、输入认证及checkpoint合同必须包含新声明和绑定；辅助证据应能追溯来源、
独立会话、缺口和可用时间假设。SE账户经济审计仍围绕LITE，但正式证据认证需覆盖新增决策输入。

### 3.3 决策上下文与时点截断

复用不可变`TradingSession`，仅传当前会话及其可用时点：

```python
# EquityDecisionContext新增；只提供显式声明的输入
auxiliary_histories: Mapping[str, DataFrame]
session: TradingSession | None = None
session_available_at: datetime | None = None
```

- `auxiliary_histories`只包含已声明名称，每项为独立深拷贝的有量有效历史；映射不可改写。
  只暴露`Date/AvailableDate/BarStart/Open/High/Low/Close/Volume/Amount`中的标准字段，供应商附加列不传入。
  策略可以计算指标，但不能改变后续决策、另一配置或worker的准备资产。
- 在每次主标的决策时间`t`，各辅助序列先检查其独立日历及最新应有观察，再只暴露
  `Date <= t`且`AvailableDate + data_latency_seconds <= t`的已完成柱。
  不按行号与LITE配对，不把当天未完成日线用于当天日内信号，不读取当前执行区间OHLCV。
- 需要明确主`point.observed_through`只描述主行情，辅助列保留各自`Date/AvailableDate`；
  公共检查对所有序列以`decision_at`为因果上界。数据延迟不得提前暴露后来信息。
- 每个辅助输入都是必需输入。历史不足、已应可用的缺失/零量柱、超出声明陈旧容忍、
  未绑定身份或非法时点均明确失败，错误指出名称、时点及原因。不能自动跳过该条件、前填、补零或使用将来柱。
- 非同步频率允许读取仍在声明有效期内的最近已完成观察；这不合成新的时间戳或伪造当前价格。
- 原LITE缺口的`SUPPRESSED_UNOBSERVED_BAR`规则不变；原来不调用策略的时点仍不调用。
  新辅助失败策略不扩展为改变原主行情缺口语义。
- 仅提供当次执行区间所属主会话，校验区间属于该会话且`available_at <= decision_at`。
  半日闭市时间属于此前已知的日历事实，不能从当天后续实际行情的最后一根反推。
  复用DFLS会话元数据及会话产品`AvailableDate`，保留来源的日历可用时间假设。
  Futu当前日历的历史公告时间未独立实测，不升级宣称为完整历史公告证据。

调用方式示意：

```python
market = ctx.auxiliary_histories['market']
market_close = market.Close.iloc[-1]
session_end = ctx.session.segments[-1].end
last_execution_interval = ctx.point.execution_interval.end == session_end
```

正式`run_window`和直接`plan`使用一致的`auxiliary_histories`、`sessions`、`trading_sessions`关键字参数。
公开`build_equity_decision_context(definition, history, portfolio, point, *, auxiliary_histories=None, sessions=None, trading_sessions=())`
统一切片；候选直接调用另行认证已传上下文，拒绝未来行。直接调用不能绕过辅助覆盖及会话可用时点。
新能力启用时，辅助上下文实现源码进入正式`engine_sources`。
TDR的`audit_inputs.decision_inputs`保留声明辅助的行情/会话记录与主会话记录；归档认证核对声明、绑定、来源元数据、
独立网格及每次实际决策的可用性，经济账本仍只交给原账户审计。
TXE无需新增订单类型或辅助账户，只消费SRT生成的原`EquityPlan`。

## 4. 半日市退出的可执行含义

按现行30分钟模型，在不增加MOC订单的前提下：

|会话|最后执行区间（美东）|可用最近主柱|市价卖出模型价格|
|---|---|---|---|
|正常日|15:30—16:00|截至15:30已完成且可得的柱|15:30区间开盘价，含既有费用/滑点规则|
|半日市|12:30—13:00|截至12:30已完成且可得的柱|12:30区间开盘价，含既有费用/滑点规则|

策略在最后区间开始时返回0，并禁止最后区间新买入，可以表达“收盘前尝试清仓”。
这是提前一个30分钟区间开盘退出，不是按16:00/13:00收盘价成交。
若等到最后柱收盘才产生信号，当天已经没有下一RTH执行区间；不能虚构当日收盘成交，
后续可执行区间通常是下一交易日。

缺失/零量/已知不可交易/成交量不足仍可能使退出失败；上一可用主柱缺失也可能抑制信号。
因此该能力不承诺严格日终零持仓。需要在证据中披露隔夜残留及未成交原因；不得为了日内策略标签强制平账。
如研究要求每个交易日必定清仓，就应先承认当前成交模型无法保证，再决定是否另行扩展订单和数据能力。

不能把整段历史半日日期表塞进源码或参数代替正式日历上下文。

## 5. 不变边界与交付范围

- 旧无辅助模式维持原输入、下单、费用、现金、持仓、交易周期及缺口处理；新字段不隐式改变旧策略输入。
  旧定义默认值在序列化时不增加影响历史内容身份的字段；旧证据原样读取，不改签哈希或迁移历史原件。
- 新模式单独绑定版本和全部输入；新运行引擎源码身份据实记录，不声称新旧环境哈希相同。
- 同条件买入持有继续只交易LITE，沿用相同主数据、窗口、资金、费用、买入合同及行动；不应用策略辅助过滤或日终清仓。
  不为日内原型另换较弱基准。候选及基准的数据声明差异明确呈现。
- 原A股链路不增加辅助上下文要求，原有A股接口和账本保持不变。
- 同步登记、冻结复核和离线PTE输入准备的声明及身份校验；不做真实冻结发布、生产变更、交易连接、订单提交或全市场组合。
- 本轮维护本文需求与实施交接，不修改模块README。

## 6. 聚焦验收

1. **声明与绑定**：重复名称、非法市场/频率/年龄、缺来源、错标的、错修订、错内容哈希明确失败；
   定义、绑定及候选通过序列化和Windows进程传输。
2. **因果边界**：30分钟和日线辅助各一组；同一时点延迟到达、当前未完成柱、未来价格扰动均不改变此前决策；
   主辅助不同观察时间可以正确表达，无位置拼接。
3. **缺失与陈旧**：缺一个必需来源、最新应有柱缺失/零量、最少历史不足、周末/假日跨越陈旧限额，
   返回明确失败及输入名称；不自动退回纯价格模式。
4. **会话与成交**：正常日、半日市及夏令时各有确定性样例；最后区间分别于15:30/12:30请求卖出，
   无最后柱Close泄漏，无收盘价虚构成交；阻断退出仍保留真实持仓及失败原因。
5. **账户与基准**：相同LITE数据下，辅助声明只影响候选决策；买入持有经济账本与原同条件基准精确一致；
   无辅助旧模式及既有A股聚焦账本结果等价。
6. **身份与运行**：辅助输入修订、日历结束时间或上下文模式变化形成不同身份；checkpoint不复用旧输入结果；
   单进程与至少两worker结果等价，worker无供应商访问，结果证据能认证新增输入。
7. **范围纪律**：先用合成夹具完成上述软件验收；本项不读取2026行情、不创建研究实验，不将软件PASS当作收益假设成立。

建议聚焦测试入口：

- [DFLS权益产品测试](../../../packages/dataflows/tests/functional/test_equity_products.py)及[Futu适配器测试](../../../packages/dataflows/tests/functional/test_futu_equity.py)。
- [SRT正式定义测试](../../../packages/strategy_runtime/tests/functional/test_equity_definition.py)。
- [TDR正式权益链路](../../../tests/functional/test_equity_research.py)、[源码闭包](../../../tests/functional/test_equity_closure.py)、
  [候选身份](../../../tests/functional/test_equity_candidate_registration.py)及[参数评价](../../../tests/functional/test_equity_parameter_evaluation.py)。
- [TXE闭合周期](../../../packages/trading_execution_engine/tests/functional/test_equity_closed_cycle.py)和原A股执行聚焦用例。

实际测试结果随本轮DEV交付报告汇总；无需消耗研究实验额度。研究恢复时再按真实可用能力固定研究方案。

## 7. 本轮聚焦验证记录

- [辅助上下文集成测试](../../../tests/functional/test_equity_auxiliary_context.py)：最终源码稳定后 **15 PASS**。
  覆盖精确准备与发布、来源/标的/日历认证、独立日历、同条件买入持有等价、陈旧输入失败、
  重算外层身份后的未来/陈旧/缺失/会话可用时点拒绝、双worker与checkpoint精确复用、
  主历史数据延迟的归档一致性，以及正常/半日市最后区间按Open成交的实际卖出。
- 原[权益研究入口](../../../tests/functional/test_equity_research.py)与[正式源码闭包链路](../../../tests/functional/test_equity_closure.py)
  共 **23项通过**；其中原串并行checkpoint项在实现稳定后单独复跑通过。
- [SRT上下文](../../../packages/strategy_runtime/tests/functional/test_equity_context.py)与
  [正式定义](../../../packages/strategy_runtime/tests/functional/test_equity_definition.py)：**36项通过**。
  覆盖混频因果边界、半日与夏令时、数据有效期、字段白名单及副本隔离。
- [PTE输入与账户](../../../tests/functional/test_equity_pte.py)及
  [技术复核与冻结回放](../../../tests/functional/test_equity_inspection_roundtrip.py)：**12项通过**。
  同一来源的LITE/SPY变体在源码稳定后单独复验通过，含隔离PTE、冻结后回测及交付认证。
- [参数计划](../../../tests/functional/test_equity_parameter_evaluation.py)与
  [辅助输入账户对照](../../../tests/functional/test_equity_auxiliary_diagnosis.py)：**16项通过**。
  带辅助输入和无辅助输入的策略允许比较，但主交易数据、费用与执行条件必须一致，各自输入完整认证。
- 原A股[候选运行](../../../tests/functional/test_candidate_runtime_execution.py)、
  [公共评价](../../../tests/functional/test_evaluation.py)与
  [公共运行接口](../../../packages/strategy_runtime/tests/functional/test_public_runtime.py)：**14项通过**。
- 以上去重合计**116项通过**；全部改动Python文件Ruff、公共导入及`git diff --check`通过。
  本记录不是全仓回归，也不是原A股能力的全量验收，不构成研究收益结论。
  没有读取真实2026行情，没有新建研究实验或消耗新增研究额度。

本轮开发目标已完成，S017继续暂停，新增20轮额度仍为0/20。后续先核验真实辅助数据来源、覆盖和行业代表性，
取得恢复指示后再进入研究；本次不合并master、不打tag、不推送、不做生产变更。
