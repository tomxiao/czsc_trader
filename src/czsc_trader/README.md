# TDR研究工具使用说明

研究员统一调用Python API；用户CLI仅提供`backtest run`。阶段审批、选型与冻结权限见[RSCH契约](../../research/RSCH_AGENT.md)。公开API不代表获准写入、冻结或部署。

## 1. 公共契约与能力导航

先读公共导出，再沿导入阅读类型、实现和契约测试。第三方库的用途与高效使用方式见[RSCH Agent第4.3节](../../research/RSCH_AGENT.md#43-第三方研究库的用途与高效使用)。

| 任务 | 公共入口 | 说明 |
| --- | --- | --- |
| 完整业务操作 | [application](application/__init__.py) | 选择性导出现有应用服务，不重复包装实现 |
| 正式实验与账户评价 | [research_tools](research_tools/__init__.py) | REX受管上下文、执行契约及实际调用追踪 |
| 候选登记与读取 | `register_candidate`、`load_candidate` | 显式保存候选身份、来源和源码；评价不自动登记 |
| 五阶段交付 | `assemble_delivery`、`validate_delivery` | 强类型内容、证据闭包和不可变修订 |
| 自检证据适配 | `research_tools.build_assessment_evidence` | 将受管评价事实转换为SE的`AssessmentEvidence` |
| 技术检验与获批冻结 | `inspect_candidate`、`record_research_decision`、`freeze_candidate`、`get_freeze_result` | 用户选型、检验、冻结批准分别绑定证据 |
| 回测底层契约 | [backtesting](backtesting/__init__.py) | 请求、策略快照、执行数据及回放类型；业务执行使用`application.run_backtest` |
| 研究身份 | `create_research_batch`、`update_research_intent` | 写入研究登记及交接资料，调用前取得授权 |
| 目录与模板 | `validate_catalog/list_catalog/show_catalog`、`validate_templates/list_templates/show_template/instantiate_template` | 完整模板操作包含跨FSC绑定校验 |
| 项目因子计算 | [FSC计算模块](../../packages/factor_signal_catalog/src/factor_signal_catalog/calculations.py) | 由FSC提供纯计算函数；研究员提供输入数据并核对因果时点 |
| 档案校验 | `validate_archives` | 只读验证；不重签原件 |
| 版本查询与部署 | `list_installed_strategies`、`strategy_info`、`deploy_strategy` | 部署单独授权；不操作PTE账户 |

研究与策略发布公共入口只接受当前契约；旧格式在边界明确失败，不做隐式升级或历史解码。
历史数据和证据原件保留供人工查阅，平台不承诺机器复验。当前有效的schema 1对象仍可使用，
版本号按对象独立管理：

| 对象 | 唯一支持版本 |
| --- | --- |
| REX绑定／定义／执行回执 | 3／2／2 |
| TDR评价产物／阶段交付定义与回执 | 4／4 |
| SM候选登记／候选内容身份 | 2／2 |
| SM冻结版本／SRT发布记录 | 5／5 |
| SRT运行定义 | 3 |
| 实验manifest／运行绑定 | 1／2 |
| SE评价标准 | `opc-v3` |

## 2. 公共输入与执行约定

- `RepositoryContext.discover`只定位仓库路径，不加载凭据；回测宿主在执行时配置DFLS，并使用仓库`.env`作为凭据文件。
- API输入遵循公开类型；现有文件化API仍接收JSON文件路径，不要求经由CLI。
- 目录、回测等既有服务返回`CommandResult`；候选、交付、检验与冻结服务返回各自强类型结果，具体见下文。调用方须核对状态及异常。
- 路径相对性按接口签名处理。临时工作空间放在`.tmp/`，不得覆盖封存实验。
- API返回成功不替代研究结论判断、用户批准或生产授权。

TDR提供研究执行、评价、回测及证据业务接口。独立取数使用DFLS的`prepare/fetch`，
实验内通过`context.data`调用并记录请求、结果和准备引用。TDR不提供独立行情准备、CSV加载
或数据校验API。研究员负责取得研究授权、选择可用数据范围并遵守阶段约束；TDR校验请求
自身的数据身份、日期范围、资源配置和执行证据，不将研究声明作为权限门槛。

## 3. 实验预检与执行

实现REX的`ResearchExperiment`并冻结源码绑定。正式执行前完成合成预检；详见[REX](../../packages/research_experiment/README.md)。

```python
from pathlib import Path
from czsc_trader.application import RepositoryContext, preflight_experiment_archive

context = RepositoryContext.discover(Path.cwd())
report = preflight_experiment_archive(
    context, context.root / "experiments/SXXX/EX001_YYYYMMDD",
    max_workers=1, native_threads_per_worker=1,
)
```

路径和单次执行资源配置是示例，须替换为实际值。前驱通过`PredecessorEvidence`绑定回执哈希。
新执行上下文要求`ExperimentDefinition.schema_version=2`，显式区分`DEVELOPMENT`开发数据与
`SEALED_VALIDATION`封存验证数据。`FORMAL`表示受管执行方式，开发数据也可以正式执行；
封存验证要求正式模式及合法的验证截止日。封存数据的使用权限、搜索和选型限制由研究员按
研究合同保证；`allowed_datasets`和`capabilities`记录研究声明，平台不据此批准或拒绝执行。

合成预检可返回`ExperimentPrecheckResult`，列出检查项并提供合成`ExperimentResult`样本做严格
JSON往返校验。预检还报告共享数组修改、列名冲突、进程载荷、浅层序列化及trial身份风险。
这些源码扫描结果为启发式警告，调用方须阅读报告中的`checks`和`warnings`。

如需验证凭据、数据可用性和覆盖，显式调用
`research_tools.preflight_experiment(loaded, resources=resources, dataflows=flows,
data_requests=(request,))`。研究员确认探测范围；平台校验显式请求及DFLS就绪结果。
未传探测请求时保留`DATA_READINESS`警告；上面的档案应用API当前不接收探测参数。
复用资产只证明该请求的数据可用；验证源访问时，显式调用DFLS
`prepare(requests, policy=PreparePolicy.REFRESH)`并检查返回状态。

实验使用`load_experiment`加载，按模式通过`create_formal_experiment_context`或`create_experiment_context`建立上下文，再调用`execute_experiment`。正式评价使用`context.evaluation.evaluate(request)`，校验身份、请求窗口与数据截止日的一致性及单次执行资源。平台记录实际成功、失败和取消尝试，生成schema 2回执；执行回执不允许由研究实现伪造。

第三方研究操作可通过`context.record_capability(ExperimentCapability.SEARCH_PARAMETERS)`记录。
该方法仅记录操作类型，不检查授权；实际数据和评价调用由端口自动追踪。

Optuna维持独立第三方库使用方式。研究员负责study、trial、搜索预算、剪枝、重试和停止条件。
`ExperimentResources`只声明`max_workers`、`random_seed`和`native_threads_per_worker`；
平台不管理搜索预算或跨进程搜索调度，TDR未集成Optuna适配器。

## 4. 策略评价与回测

| 用途 | API | 输出 |
| --- | --- | --- |
| 实验内账户评价 | `context.evaluation.evaluate(EvaluationRequest)` | `EvaluationResult`，含各窗口／成本场景的账户、基准及身份 |
| 实验内批量评价 | `context.evaluation.evaluate_many(tuple[EvaluationRequest, ...])` | 按输入顺序返回`EvaluationOutcome`，分别携带终态记录和可选成功结果 |
| 文件化评价及发布 | `evaluate_research_request(context, input_path)` | 实验`artifacts/evaluation/`及文件哈希 |
| 候选或版本完整回测 | `run_backtest(context, strategy, request)` | 账户、指标、审计、报告及图表，位于返回的`artifacts.output_dir` |

`run_backtest`接受SRT的`StrategyCandidate`或SM的`StrategyVersion`，请求统一使用`BacktestRequest`。
两类对象共用底层回放流程，保留各自身份；TDR根据SRT观察事实、行情和账户账本统一绘图，
输出`tdr_backtest_chart.v1`。调用方不传入图表描述或策略专属绘图代码。

业务执行只使用`application.run_backtest`；底层回放函数不再公开，请求类型不保留带版本后缀的别名。
研究评价使用`EvaluationRequest`和`research_tools.evaluate_strategy`，正式实验通过上表的受管评价端口调用。
评价工作区、候选批量载荷回放及冠军审计构建属于内部实现；`candidate_evaluation`兼容门面已删除。

`BacktestRequest.lot_size`是必填正整数，拒绝布尔值、浮点数及隐式默认值。平台在请求行情前
核对它与策略执行合同的一致性：`FROZEN_RULE`读取`settings.instrument.lot_size`，
`INTRADAY_OVERLAY`读取`settings.lot_size`；不一致时`run_backtest`抛出错误码为`backtest_failed`的`ExecutionError`。
调用方应按已绑定的交易单位填写，不能用请求字段覆盖冻结规则。

回测按候选源码绑定或冻结发布身份加载SRT，缺失或身份不一致时明确失败。用户CLI仅支持已登记版本；
候选通过`load_candidate(context, key)`读取后传入API，回测和评价均不自动登记候选。

```python
from czsc_trader.application import BacktestRequest, run_backtest
# context、strategy、start、end来自已核对的仓库、对象与获准窗口。
result = run_backtest(
    context, strategy,
    BacktestRequest(
        symbol="588080.SH", asset_type="etf", start=start, end=end,
        initial_cash=1_000_000, lot_size=100,
    ),
)
```

用户CLI从仓库根目录执行：

```powershell
.\.venv\Scripts\czsc-trader.exe backtest run `
  --strategy SXXX --strategy-version v1 `
  --symbol 588080.SH --asset etf `
  --start 2026-07-01 --end 2026-09-28 --init-cash 1000000 --lot-size 100
```

核对`audit_status`及审计文件，不能仅看命令PASS。评价／回测不替代正式REX实验回执，也不自动产生完整阶段报告。

CLI的`--lot-size`必填且必须大于零。BuyHold、MA5/MA20与策略使用相同整手单位，基准通过TXE
记录实际现金、持仓、费用及净值，SE独立复算审计。研究评价的BuyHold交易单位由
显式`EvaluationBenchmark`中的执行合同给出。回测manifest使用`schema_version=4`并记录`request.lot_size`；
研究指标语义版本为`candidate-srt-txe-v4-explicit-benchmark`；结果比较要求双方均符合当前证据合同及计算口径。

### 回测数据空间

```python
# context、strategy、request按上面的回测契约构造。
result = run_backtest(context, strategy, request)
```

候选、冻结版本、研究内评价及文件化评价统一使用仓库根目录下的`data/backtest/`。
TDR内部创建DFLS，调用方无需指定空间；`run_backtest`和`evaluate_strategy(request)`
均不接收`dataflows`参数。

`EvaluationRequest.execution_data`可省略，平台根据策略和评价窗口准备执行行情及策略输入，
再以固定引用计算。已有执行数据和输入绑定须来自同一回测空间，引用无效、跨空间或内容变化
时明确失败。研究评价返回的结果可直接与原请求一起传给`build_assessment_evidence`。

执行数据准备遵循实际依赖：

- 策略计算输入及其预热由SRT按输入契约规划。
- TDR根据实际订单类型请求30分钟限价成交数据，日内执行检查时点需要时请求5分钟数据；
  显式`LimitBuyHold`基准也要求30分钟数据。仅市价策略配合开盘买入持有基准无需分钟行情。
- 分钟执行行情只覆盖评价区间，直接消费DFLS的不复权数据产品。TDR不通过日线比值逆算分钟价格。
- 原始日线包含前一信号交易日；完整回测的MA5/MA20基准需要20个先前交易日的后复权日线。
  账户评价通常只需一个先前交易日，策略自身预热仍由SRT独立准备；不再固定前取400个自然日行情。
- 已准备数据必须覆盖请求和实际执行所需的日期、频率。日线预热长度可不同，但重叠交易日须一致；
  缺少必需分钟数据时明确失败。内容与准备引用仍须一致。

研究过程的独立取数仍使用任务指定的空间，例如`data/research/<策略ID>/`；
上下文的数据端口与账户评价使用不同空间。配置和两阶段示例见[REX说明](../../packages/research_experiment/README.md#数据空间两阶段访问与第三方搜索)。
DFLS统一管理数据资产及复用，TDR不再生成供独立取数使用的CSV副本。
回测复算和review证据重放依赖`data/backtest/`中的原资产，须保留完整空间。

## 5. 证据读取与失败语义

- 前驱通过REX `load_experiment_input`及可信的`expected_receipt_sha256`读取。
- 当前契约档案通过`validate_archives(context, archive)`或`all_archives=True`校验，二者只能选一。全库调用遇到不支持的历史格式会明确失败，不等于平台承诺全部历史档案可复验。
- 文件化评价重复发布校验既有身份及文件哈希；不同结果不得覆盖旧证据。
- 重复调用可能重新准备数据和执行计算，不推定无副作用。
- 数据截止日缺口、输入身份不符、未完成审计均显式报告，不静默缩窗或降级。

比较两次账户回放时使用SE的`compare_ledgers(LedgerComparisonRequest(...))`，按目的选择
`STRICT`或`ECONOMIC`模式，并读取`EQUIVALENT/DIFFERENT/INCOMPARABLE/INVALID`状态。
保持两侧原始证据不变，差异定位和可比性条件见[SE说明](../../packages/strategy_evaluator/README.md)。
自定义执行器须遵守SRT的`SignalHistoryMode`及`ExecutionOutcomeStatus`契约，见
[SRT说明](../../packages/strategy_runtime/README.md)。

## 6. 候选登记与自检

以下业务函数从`czsc_trader.application`导入；`CandidateKey`、`CandidateRegistrationOrigin`、
`CandidateDerivation`从`strategy_manager`导入，候选与依赖类型从`strategy_runtime`导入。

候选编号固定为`C`加四位数字，例如`C0001`；`CandidateKey`同时包含策略ID，不能用自由命名
的候选编号替代。实现、有效参数或固定交易规则变化时创建新候选身份。

| API | 请求与返回 |
| --- | --- |
| `register_candidate(context, request)` | `CandidateRegistrationRequest(candidate, origin, dependencies, derivation=None)` → `CandidateRegistration` |
| `load_candidate(context, key)` | `CandidateKey(strategy_id, candidate_id)` → `StrategyCandidate` |

来源绑定实验定义、源码绑定和预检证据。调用方通过`ResearchWorkspace.registry_path`选择登记根目录，
通过`CandidateLocation(key, experiment_id)`声明候选来源，再由`DeliveryWorkspace.experiments`
提供该实验的实际目录。登记根目录内的`<策略ID>/candidates/`是SM机器记录布局。
新登记使用`CandidateRegistration.schema_version=2`；源码、载荷和来源证据保存在来源实验的
调用方声明的实验根目录内的`objects/`。登记内的文件引用相对该实验根目录，
`CandidateRegistrationRequest`中的输入证据路径仍相对仓库。同一键和登记内容重复调用返回原记录；
不同内容拒绝覆盖。实验封存后不得补写候选对象；已存在且一致的对象可只读复用。
读取与写入只接受schema 2登记；序列化记录须显式提供`schema_version=2`与`identity_schema_version=2`。
旧登记原件保留；继续研究须在获准的后继实验中通过当前API生成来源证据和登记。
参数、实现或执行规则派生使用`CandidateDerivation`分别记录`PARAMETERS/IMPLEMENTATION/EXECUTION`。
搜索trial和邻域点保存在实验及评价证据中，无须登记；只有正式交接对象须登记。已有同内容候选
的补充派生关系通过`EvaluationLineage`进入本次评价，不为补充评价关系重复登记。
未登记对象的完整载荷、源码及依赖身份由研究编排保存为实验产物并纳入执行回执，内容哈希不能
替代重建输入；评价接口不自动将临时对象写入注册表。

批量评价由主进程统一预检、校验结果和写回执，子进程通过`spawn`执行计算，使用隔离的SRT
临时目录。请求必须组成非空tuple，各自`workers=1`；进程数取`ExperimentResources.max_workers`。
单项计算失败返回失败记录，进程失联返回`UNKNOWN`，证据写入失败抛出异常。研究员根据结果
显式重试，平台生成新的`attempt_id`，不管理Optuna预算、剪枝或停止条件。
上下文完成执行回执后拒绝追加评价，不能跨进程共享或同时提交多个调用。
新目录通过`czsc_trader.experiment_archive.create_experiment_dir(root, run_date, strategy_id)`
分配`EXxxx_YYYYMMDD`，编号按策略跨日期递增；同名查找显式提供`strategy_id`。

`EvaluationRequest`显式携带`data_cutoff`、依赖及可选`EvaluationLineage`。每次受管评价保留
尝试身份；每个窗口／场景的`EvaluationIdentity`绑定候选键、内容、输入、协议与环境哈希。
`research_tools.build_assessment_evidence(request, result)`核验请求与结果后返回
`tuple[AssessmentEvidence, ...]`，供SE `assess_candidates`与`compare_candidates`使用。
每条证据的`scenario_context: EvaluationScenarioContext`绑定实际单边费用、计量层级及基准定义；
比较须同时核对公共上下文与场景口径，不能仅凭相同`scenario_id`或`context_sha256`认定可比。
自检、排序和不确定性结果的口径见[SE说明](../../packages/strategy_evaluator/README.md)。

### 显式基准执行合同

`EvaluationRequest.benchmark`必填，使用`EvaluationBenchmark(execution=...)`，执行策略为
`NextOpenBuyHold(lot_size)`或`LimitBuyHold(lot_size, premium, price_tick, price_limit_ratio,
maximum_order_quantity)`。两者均要求显式整手单位；开盘价模型接受正整数（包括1），
限价模型使用SRT执行规划，要求100股的正整数倍。
限价合同还校验溢价、价格档位、涨跌停比例和最大委托数量；研究员按已确认的执行口径选用。

```python
from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold

benchmark = EvaluationBenchmark(execution=NextOpenBuyHold(lot_size=100))
# 显式传给 EvaluationRequest(..., benchmark=benchmark)。
```

基准内容身份覆盖执行策略、参数及执行语义版本，纳入评价身份和
`EvaluationScenarioContext.benchmark_contract_sha256`。阶段一用`BenchmarkRequirement`
记录已确认合同；阶段四通过`benchmark_mandate_item_id`绑定并校验实际基准。
仅有相同的`BuyHold`名称不足以证明执行口径相同。

### 成本场景与自检协议

`EvaluationRequest.costs`为非空`tuple[EvaluationCost, ...]`。研究员决定场景名称、费用和计量层级，
可提交单个自定义场景、零成本归因、低成本对照或高成本压力实验。TDR逐场景准确执行，
不从`fee_x2`等名称推算费用，也不要求名为`standard`的场景。

场景ID须唯一且可安全用作路径组件；单边费率为有限数值并满足`0 <= one_way_cost < 1`。
计量层级允许`FORMAL`、`SCREENING`、`STRESS`，默认`FORMAL`；TDR不限制这些层级与费率高低的组合。

```python
from czsc_trader.research_tools import EvaluationCost

# 传给 EvaluationRequest(costs=costs, ...)；费率仅为示例，按已确认协议填写。
costs = (
    EvaluationCost("zero_cost", one_way_cost=0.0),
    EvaluationCost("baseline", one_way_cost=0.001),
    EvaluationCost("higher_cost", one_way_cost=0.002, measurement_tier="STRESS"),
)
```

需要计算SE标准／压力配对诊断时，研究员在`SelfCheckProtocol`中指定对应场景ID。
该项诊断要求标准层级为`FORMAL/SCREENING`，压力层级为`STRESS`且实际费用更高，
基准定义、指标版本和公共上下文一致；这是诊断可比性要求，不是TDR运行其他成本实验的前提。
跨候选比较及参数邻域须保持对应场景口径一致。完整口径见[SE说明](../../packages/strategy_evaluator/README.md)。
计量层级与REX实验执行模式分别声明；`SCREENING`场景也须遵守正式研究的受管执行要求。

## 7. 五阶段交付

从`czsc_trader.research_tools`导入交付契约，实现`ResearchDeliverable.definition`和
`build() -> DeliveryContent`，再调用以下业务API：

| API | 返回与语义 |
| --- | --- |
| `assemble_delivery(context, deliverable)` | `DeliveryReceipt`；验证内容和证据后发布不可变修订，校验失败或修订冲突抛出明确异常 |
| `validate_delivery(context, reference, *, scope=DeliveryValidationScope.FULL)` | `DeliveryValidation`；只读核验当前`DeliveryReference`，返回`PASS/FAIL`、实际范围及问题定位 |

`DeliveryValidationScope`从`czsc_trader.research_tools`导入。`INTEGRITY`验证文件哈希、身份、
引用及结构；默认`FULL`还复算本次`ASSESSMENT`的SE自检与比较结果。前驱交付按`INTEGRITY`
验证，两种范围均不重新运行账户回测；必要时加载实验定义核验源码和归属。

`ASSESSMENT`发布与`FULL`复验会重新计算自检面板。仅家族诊断`DSR_EFFECTIVE`的数值比较采用
`rel_tol=1e-12`、`abs_tol=0.0`，用于容纳原生线程数变化引起的浮点尾差；有差异时，两侧值
须在`[0,1]`内，诊断名称、状态、原因及顺序仍须一致。调用方无需为此强制单线程复验。
文件原始字节及哈希、请求与协议身份、账户指标、其他诊断和候选比较结果仍精确核验。
此规则不改变公共签名或schema，不改写已发布交付及其内容身份。

| `DeliveryStage` | 对应的强类型内容 |
| --- | --- |
| `MANDATE` | `ResearchMandate`：研究目标、约束及逐项确认记录 |
| `COMPONENTS` | `ComponentPanel`：组件角色、定义哈希、实验与事实引用 |
| `CANDIDATES` | `CandidateSet`：候选、评价证据、描述性的`SearchRecord`及必须已登记的`handoff`集合 |
| `ASSESSMENT` | `CandidateAssessmentDelivery`：自检／比较请求与结果、目标绑定、反面证据及待决事项 |
| `INSPECTION` | `CandidateInspectionDelivery`：技术检验、用户决定、可选冻结回执及待决事项 |

新`DeliveryDefinition`和`DeliveryReceipt`使用schema 4；`DeliveryDefinition`及`DeliveryReference`
以`owner`明确逻辑归属。调用方通过`RepositoryContext.discover(..., delivery_workspace=...)`
明确提供交付目录、前驱交付目录及绑定实验源码目录；TDR按声明位置读写，不从研究ID、
实验ID、阶段或修订号推导目录。遗漏位置时明确失败，即使原约定目录下存在文件也不会自动读取。

| 归属类型 | 允许阶段 | 位置契约 |
| --- | --- | --- |
| `MandateOwner(strategy_id)` | `MANDATE` | `DeliveryLocation(owner, stage, revision, path)` |
| `ExperimentOwner(strategy_id, experiment_id)` | 阶段二至五 | `DeliveryLocation`及`ExperimentLocation(owner, path)` |

```python
from pathlib import Path
from czsc_trader.application import RepositoryContext
from czsc_trader.research_tools import (
    DeliveryDefinition, DeliveryStage, ExperimentOwner,
    DeliveryLocation, ExperimentLocation, DeliveryWorkspace,
)

definition = DeliveryDefinition(
    owner=ExperimentOwner("S900", "EX001_20261004"),
    stage=DeliveryStage.COMPONENTS,
    revision=1,
)
workspace = DeliveryWorkspace(
    deliveries=(DeliveryLocation(definition.owner, definition.stage, 1,
                                 "experiments/S900/EX001_20261004/results/components-1"),),
    experiments=(ExperimentLocation(definition.owner,
                                    "experiments/S900/EX001_20261004"),),
)
context = RepositoryContext.discover(Path.cwd(), delivery_workspace=workspace)
# 发布前，该归属实验须已存在有效定义和源码绑定，且尚未生成实验manifest。
```

`DeliveryWorkspace`覆盖本次交付及其前驱链条所需的位置；所有路径相对仓库，拒绝越界路径、
链接、重复身份及相互重叠的交付目录。迁移目录后重新提供位置即可复验原`DeliveryReference`，
物理路径不改变内容身份。实验源码目录名称仍遵守REX加载契约。
候选、决定、检验和冻结空间另由下述`ResearchWorkspace`显式声明。

每份交付包含`delivery.json`、`report.md`、`receipt.json`及声明证据；`attachments/`保存附件，
`experiments/`保存声明实验的回执与制品副本。`EvidenceFile.source_path`相对仓库，
`EvidenceRef.path`相对交付目录。副本用于核验交付，来源实验保留原始档案。
先在`.tmp/delivery/`组装，再原子发布；同归属、同阶段、同修订的不同内容拒绝覆盖。
修订号在归属与阶段内计数，不同实验可以各自从1开始；跨实验汇总交付归入形成该交付的实验，
通过带内容哈希的`DeliveryReference`引用前驱，通过`ExperimentEvidenceRef`声明证据来源。

先完成受管执行并保存回执及制品，再保存需要交接的候选实体、发布阶段交付，最后生成
`experiment_manifest.json`封存整个实验。封存后拒绝追加交付，后续修订由新实验承接；
已有同内容交付可只读核验后返回。`build_experiment_manifest`也拒绝覆盖不同内容的已有清单。
`COMPLETE/PARTIAL/BLOCKED`表达交付完整度，与验证`PASS/FAIL`分别判定。

交付读写只支持schema 4及带`owner`的`DeliveryReference`，旧回执不能由当前API恢复或复验。
历史交付原件保持原位，供人工查阅；新的受管证据和交付由获准的后继实验生成。

发布`CandidateSet`时，`assemble_delivery`逐项检查`handoff`候选已登记、内容哈希一致、
登记源码及依赖证据完整且可由`load_candidate`加载。缺失或冲突返回`DeliveryValidationError`，
问题码为`HANDOFF_REGISTRATION`；平台不自动登记搜索trial。已发布的候选交付校验依赖其自身
证据，不依赖临时组装源文件或候选登记区；归属实验的有效绑定、已封存清单及前驱交付仍须保留。

阶段四发布和`FULL`验证按记录的请求复算SE结果，并绑定阶段一已确认的数值目标。阶段五复制
检验、登记、源码、决定和确认材料闭包；可先交付待批准报告，冻结后用新修订记录实际冻结结果。
若原归属实验已封存，冻结结果交付必须归入后继实验，不能向旧实验追加。
阶段四报告展开逐项目标检查、排序敏感性和行为分组；阶段五报告展示用户决定、确认材料链接
及冻结失败／结果不确定的具体原因。研究员继续补充选择代价、研究解释及待决定事项。
技术验证不自动推进研究阶段，也不替用户选型。

## 8. 技术检验、用户决定与冻结

业务函数、`CandidateInspectionRequest`、`InspectionReplay`和`EvaluationEvidenceReference`
从`czsc_trader.application`导入；
决定、检验协议、冻结请求及回执等强类型契约从`strategy_manager`导入。

| API | 请求与返回 |
| --- | --- |
| `record_research_decision(context, decision)` | `ResearchDecision` → `DecisionReference` |
| `inspect_candidate(context, request)` | `CandidateInspectionRequest` → `CandidateInspectionReport` |
| `freeze_candidate(context, request)` | `FreezeCandidateRequest(request_id, inspection, approval)` → `FreezeReceipt` |
| `get_freeze_result(context, request_id)` | `FreezeRequestId(strategy_id, value)` → `FreezeReceipt` |

上述入口要求`context.research_workspace`。从`czsc_trader.research_tools`导入
`ResearchWorkspace/CandidateLocation/FreezeJournalLocation`，从`strategy_manager`导入
`ResearchEvidenceLocation/ResearchEvidenceOwner`；调用方声明登记、候选来源、逻辑归属的证据根目录
和冻结事务根目录。目录位置由研究员选择，未声明时明确失败，不查找既有研究目录。
`RepositoryContext.discover(..., delivery_workspace=..., research_workspace=...)`分别接收两组绑定。

| `ResearchWorkspace`字段 | 声明内容 |
| --- | --- |
| `registry_path` | SM登记根目录，相对仓库 |
| `candidates` | `CandidateLocation`元组；候选键与来源实验ID的绑定，实际目录在`DeliveryWorkspace.experiments`声明 |
| `evidence` | `ResearchEvidenceLocation`元组；每个逻辑归属的实际证据根目录 |
| `freeze_journals` | `FreezeJournalLocation`元组；每个策略的实际事务日志根目录 |

调用顺序与必要输入：

1. 留存用户对阶段四交付中候选的选择，以`CandidateSelectionSubject`绑定交付、候选键和内容哈希。
2. `CandidateInspectionRequest`传入选择记录、`InspectionProtocol`、正在执行的正式REX上下文、
   `InspectionReplay`元组、明确的版本／父版本、版本说明、选择截止日和前瞻起始日；
   可选附加文件与剩余风险通过`additional_files/remaining_risks`声明。运行绑定由平台生成。
   每个回放项为`InspectionReplay(reference, reproduction_request)`：原评价使用已封存归档引用，
   本次复算使用新的`EvaluationRequest`，无需保留原Python请求或结果对象。
3. `inspect_candidate`核验候选及依赖、覆盖、运行定义、复算、独立账本审计、候选与拟冻结版本的
   信号／账本等价性和发布文件闭包，生成`FreezePlan`及`PASS/FAIL/INCOMPLETE`报告。
   检验证据同时归入本次REX执行回执；已封存执行空间拒绝追加。
4. 用户明确批准冻结后，以`FreezeSubject`绑定候选内容、检验报告、计划哈希和版本，留存
   `DecisionAction.APPROVE`决定，再传入`freeze_candidate`。
5. 读取回执状态；不确定时用同一`FreezeRequestId`查询，完整状态定义见[SM说明](../../packages/strategy_manager/README.md)。

归档引用使用以下强类型字段：

| `EvaluationEvidenceReference`字段 | 类型及含义 |
| --- | --- |
| `experiment` | `ExperimentEvidenceRef(experiment_id, workspace_path, receipt_sha256, use)`；路径相对仓库，指向持久归档或已发布交付中的实验副本，当前评价使用`CURRENT_EVALUATION` |
| `attempt_id` | 原成功评价的尝试ID |
| `evaluation_ids` | 该次评价的完整、有序窗口／场景ID元组 |
| `result` | `CandidateEvidence(path, sha256)`；对应`EvaluationRecord.result_artifact`，路径相对上述实验工作空间 |

执行回执完成后，将回执及其声明的全部制品按原相对布局保存到实验的实际归档位置，并通过
`load_experiment_input`核验，再保存引用的`to_dict()`结果。以下`record`是原成功评价记录，
`source_receipt`属于同一次执行；示例归档位置为`artifacts/rex/`，须替换为实际位置，
不能把可清理的`.tmp/`路径作为唯一持久引用。`reproduction_request`为本次复算请求：

```python
from czsc_trader.application import EvaluationEvidenceReference, InspectionReplay
from czsc_trader.research_tools import ExperimentEvidenceRef, ExperimentEvidenceUse
from research_experiment import load_experiment_input
from strategy_manager import CandidateEvidence

archived_workspace = context.experiments_root / strategy_id / record.experiment_id / "artifacts/rex"
load_experiment_input(archived_workspace, expected_receipt_sha256=source_receipt.sha256)
reference = EvaluationEvidenceReference(
    experiment=ExperimentEvidenceRef(
        record.experiment_id,
        archived_workspace.relative_to(context.root).as_posix(),
        source_receipt.sha256,
        use=ExperimentEvidenceUse.CURRENT_EVALUATION,
    ),
    attempt_id=record.attempt_id,
    evaluation_ids=record.evaluation_ids,
    result=CandidateEvidence(record.result_artifact.path, record.result_artifact.sha256),
)
saved_reference = reference.to_dict()  # 作为研究交接资料持久保存。
restored = EvaluationEvidenceReference.from_dict(saved_reference)
replay = InspectionReplay(reference=restored, reproduction_request=reproduction_request)
```

`result`引用评价结果产物；`EvaluationResult.record`引用尝试记录，二者不能混用。
`inspect_candidate`核验执行回执、尝试、完整评价ID、产物哈希和阶段四选型证据，从归档读取
复算基线，再通过当前正式上下文执行新评价。引用不符或原件被改动时拒绝检验。

新TDR评价产物采用schema 4，保存显式基准合同、请求身份、SE场景证据、复算账本输入及信号列类型；
REX执行回执仍为schema 2。新归档检验要求评价产物schema 4，旧产物缺少字段时须新建正式
实验及交付修订重新生成证据，保留旧原件。新契约不自动迁移或补写历史结果。

`ResearchDecision.subject`还支持阶段推进的`StageAdvanceSubject`；`action`使用
`APPROVE/REJECT/DEFER`。宿主负责取得和核验真实用户授权，平台校验确认材料及其引用，
调用者填写的批准字段本身不构成人员身份认证。

平台从已登记候选及附加文件构造`RuntimeBindingSpec`，schema 2包含
`source_files/implementation_sha256/install_files/observation_sha256`；冻结时添加
`release_id/release_hash`形成`RuntimeBinding`。观察定义绑定到候选内容，不保存策略绘图代码。

检验、计划和确认材料使用`ResearchEvidenceRef(owner, path, sha256)`，`path`相对其强类型归属。
`ResearchEvidenceLocation(owner, path)`将归属绑定到调用方选择的仓库相对目录。
用户决定及确认材料使用该证据根目录内的`decisions/`机器记录；检验证据使用其归属证据根目录内的
`objects/inspection/`；冻结请求及查询事实使用`FreezeJournalLocation`指定根目录内的`<请求ID>/`。
调用方复用API返回的引用，通过`ref.resolve(context.root, location=declared_location)`核验。
`StageAdvanceSubject.delivery`和`CandidateSelectionSubject.delivery`要求`ResearchEvidenceRef`，
使决定随归属空间迁移后仍能定位原交付。原仓库路径形式的决定不自动转换或改写。
`CandidateEvidence`仍用于原评价产物及登记输入，路径按对应接口声明的根目录解析。

仅`COMMITTED`表示版本完成冻结；新版本使用schema 5，保留来源实验、候选编号及固定运行内容。
检验、用户批准及请求身份由研究证据和冻结日志分别绑定；`StrategyVersion`不嵌入
`CandidateOrigin/FreezeGovernance`，发布哈希不随追加研究决定改变。
同一请求同内容返回既有状态，内容冲突或版本冲突明确失败。中断、证据损坏或未完成提交返回
`UNKNOWN`时保留现场，不自动重试、回滚或换版本。冻结不会自动获得`PAPER_READY`资格或执行部署。
平台先完成发布包和研究日志中的提交标记，再原子写入版本文件；版本文件是运行侧可见性边界。
版本读取、回测和部署只接受schema 5，并按各自入口核验版本、发布包及部署身份；运行侧不读取
研究批准或冻结日志。旧格式证据不自动升级；
若需在当前平台执行，须另行授权重新检验及生成当前发布，不能通过改字段或重签原件绕过合同。

## 9. 使用与维护边界

API收敛不改变模块职责；数据、统计及策略计算继续使用所属模块的公开能力。研究员不得使用私有函数、CLI子进程或手工治理写入绕过契约。安装依赖、部署及生产写入分别取得授权。
