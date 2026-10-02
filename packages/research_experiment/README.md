# 研究实验（Research Experiment，REX）

本文面向策略研究员（RSCH）。REX给一个可证伪实验提供可执行锚点、
能力边界和结果身份；研究问题、金融机制与是否继续研究仍由研究员判断。安装、源码维护及
测试见[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

## RSCH：定义并执行实验

从`research_experiment`顶层导入`ResearchExperiment`，实现只读`definition`属性和
`execute(context)`。`ExperimentDefinition`在执行前写明问题、假设、证伪条件、数据范围、
开发截止、随机种子、阶段协议与允许的能力；`ExperimentResult`返回机器事实、诊断及声明的
产物。研究员只通过平台提供的`ExperimentContext`访问数据、SRT运行、评价、前驱证据和工作
空间，不自行构造平台回执。

实验源码以`experiment_binding.json`声明模块、类、源码闭包和依赖身份；
`load_experiment(...)`核对哈希并隔离加载。探索使用
`czsc_trader.research_tools.create_experiment_context(...)`，正式实验使用
`create_formal_experiment_context(...)`；两者不可互换。`execute_experiment(...)`核对定义、
能力、产物及资源使用，并生成平台回执。公共导出和类型签名以
[`research_experiment`顶层](src/research_experiment/__init__.py)及
[`czsc_trader.research_tools`顶层](../../src/czsc_trader/research_tools/__init__.py)为准。

正式实验在读取结果前预注册，既有档案保持不可变；技术失败、探索发现和完整账户证据应分开
归档。目录和manifest要求见[实验档案说明](../../experiments/README.md)，研究判断与污染边界见
[RSCH Agent](../../research/RSCH_AGENT.md)。

执行回执完成与整个实验封存分别发生：先完成受管执行，将回执及声明制品保存到实验
`artifacts/`中的实际归档位置，再完成候选实体保存和TDR阶段交付，最后生成
`experiment_manifest.json`。阶段二至五交付位于归属实验的`deliveries/<阶段>/<修订>/`；
回执完成后不能追加执行或技术检验，实验manifest生成后不能追加交付或候选对象。
后续研究或交付修订由后继实验承接；阶段一任务与确认材料保留在研究治理区。

## 正式实验预检

先阅读[公共导出](src/research_experiment/__init__.py)，沿导入核对绑定、定义和预检契约。

### 契约版本与实现

| 对象 | 当前要求 | 代码入口 |
| --- | --- | --- |
| `experiment_binding.json` / `ExperimentBinding` | 只接受`schema_version=3` | [loader.py](src/research_experiment/loader.py) |
| `ExperimentDefinition` | 只接受`schema_version=2`；`data_scope`必填且使用`ExperimentDataScope`；在`subjects`中声明唯一研究标的 | [contracts.py](src/research_experiment/contracts.py) |
| `ExperimentReceipt` | 读写只接受`schema_version=2`，绑定实际执行追踪和产物 | [contracts.py](src/research_experiment/contracts.py) |
| `ResearchExperiment.synthetic_precheck()` | 返回`ExperimentPrecheckResult`或`None`，不读取真实研究结果 | [contracts.py](src/research_experiment/contracts.py) |

绑定、定义与回执分别管理版本号，不得互相套用。执行追踪也必须显式包含强类型`data_scope`。
旧格式不自动解码、升级或补齐字段；原件供人工查阅，平台不承诺历史机器复验。

`ExperimentMode.FORMAL`声明受管执行方式；`ExperimentDataScope.DEVELOPMENT`声明开发数据范围，
`SEALED_VALIDATION`声明封存验证范围。正式开发实验可以搜索参数；封存验证必须使用正式模式、
显式验证截止日及读取能力，并禁止搜索和选择参数。数据门属于执行契约，不构成Python代码安全沙箱。

- 实验必须显式实现`synthetic_precheck`，缺失时预检失败。
- 合成预检必须覆盖输入结构、边界、时间对齐和实际计算路径。
- 合成预检不得使用真实收益筛选参数。
- 预检未通过时必须修正并重新执行。
- 预检通过前不得读取正式结果。
- DFLS的`READY`状态不得替代历史可得性或研究合同核验。

### 合成检查与结果样本

`ExperimentPrecheckResult(checks, result=None)`将合成检查的覆盖项显式交给平台。
`checks`包含非空、编码唯一的`ExperimentPreflightCheck`；`PRECHECK`和`COVERAGE`是保留编码。
每项检查使用`ExperimentPreflightStatus.PASS/WARNING/FAIL`，平台在报告中加`SYNTHETIC_`前缀。
检查必须执行实际合成路径，再按结果填写状态。

可选`result`是合成的`ExperimentResult`样本。平台调用其公共`to_dict()`做严格JSON往返校验，
拒绝非有限数值和序列化前后内容变化；不得用`dict(result.facts)`替代嵌套结构的正式序列化。
样本缺失报告`RESULT_SERIALIZATION`警告。已有仅靠断言的预检可返回`None`，
但会报告`SYNTHETIC_COVERAGE`警告；返回`False`等其他类型会失败。

任一命名检查失败或结果样本序列化失败，整体`SYNTHETIC_PRECHECK`失败。
前置合同失败时跳过合成执行；执行后再次核验源码及定义未变。

### API入口

源码与定义冻结后、首次正式执行前调用TDR公共`preflight_experiment_archive(context, experiment, ...)`，见[公共导出](../../src/czsc_trader/application/__init__.py)。按需提供`max_workers`、`native_threads_per_worker`及`PredecessorEvidence`序列；前驱绑定工作空间与回执哈希。示例见[TDR说明](../../src/czsc_trader/README.md)。用户CLI仅保留回测，研究员使用Python API执行预检。

- 技术失败档案必须按实际档案身份引用。
- 不得伪造成功receipt。

需要显式探测数据可用性时，使用底层公共
`czsc_trader.research_tools.preflight_experiment(loaded, resources=resources,
dataflows=flows, data_requests=requests)`。`requests`必须是`DataRequest`元组，
且必须提供已配置的`Dataflows`。探测只允许声明过的数据集、已声明的`reads_real_returns`能力
及开发截止日内的请求；仅`READY`通过。不传请求时报告`DATA_READINESS`警告，不隐式联网。
`preflight_experiment_archive`当前不接收这两个探测参数。
缓存命中不验证源凭据；需要验证源访问时，使用未启用缓存或`REFRESH`配置的DFLS。

预检还扫描绑定的Python源码，报告以下风险位置：

| 报告码 | 需要核验的风险 |
| --- | --- |
| `NUMPY_VIEW_MUTATION_RISK` | `to_numpy`未显式传`copy=True`，后续原地修改可能失败或污染共享数据 |
| `JOIN_COLUMN_COLLISION_RISK` | `join`缺少显式后缀策略，可能发生列名冲突 |
| `PROCESS_PAYLOAD_REVIEW` | 进程worker载荷序列化及子进程数据配置 |
| `SHALLOW_RESULT_SERIALIZATION_RISK` | 对`facts/diagnostics`浅层转换后仍残留不可序列化对象 |
| `LAST_TRIAL_IDENTITY_RISK` | 使用`trials[-1]`可能取到排队试验，应保留`ask()`返回的试验身份 |

源码扫描是启发式`WARNING`，不能证明已发生故障或风险已全部覆盖。
预检通过仍须阅读警告，不能推定数据探测、序列化和全部运行路径均已验证。

## 数据缓存与第三方搜索

探索上下文的必填`dataflows`参数同时用于默认SRT和默认评价器；显式提供自定义运行时或评价器时，
调用方负责它们的数据配置。正式上下文只接受`cache: LocalCacheConfig | None`，由平台创建DFLS
并共享给SRT和评价器，默认不启用缓存。配置见[DFLS说明](../dataflows/README.md#dev配置本地缓存)。

Optuna继续作为独立第三方库使用，研究员组织study、sampler、trial、预算、剪枝、重试和停止条件。
`ExperimentResources(max_workers, random_seed, native_threads_per_worker=1)`配置单次执行资源，
不包含评价次数预算。当前未提供平台Optuna适配器或跨进程搜索调度。

## 受管端口与执行证据

`ExperimentContext`通过强类型`ExperimentDataPort`、`ExperimentRuntimePort`和
`ExperimentEvaluationPort`提供数据、运行和评价能力。正式评价使用
`context.evaluation.evaluate(EvaluationRequest)`；批量使用
`context.evaluation.evaluate_many(tuple[EvaluationRequest, ...])`，返回按输入顺序排列的
`tuple[EvaluationOutcome[EvaluationResult], ...]`。`EvaluationOutcome.record`必须是终态，
仅`SUCCEEDED`携带非空`result`。全部请求预检后才开始计算；每项独立留证，失败不影响其他项。
进程异常退出使用`UNKNOWN`，证据写入失败抛出异常；平台不自动重试。研究员决定重试请求，
重试生成新`attempt_id`。评价本身不自动登记候选。

主进程持有唯一上下文与回执，子进程只计算；不得将上下文传入研究员自己的进程池。批量请求
各自`workers=1`，进程数由`ExperimentResources.max_workers`限定，本地数值库线程数由
`native_threads_per_worker`限定。每次评价的SRT临时数据目录隔离。正式入口在子进程重建
平台DFLS配置；探索入口的自定义evaluator及provider须可序列化（模块级函数或可序列化对象），
不支持的传输在执行前报错。Windows脚本入口使用`if __name__ == "__main__":`保护。
新实验目录为`EXxxx_YYYYMMDD`，完整定位需策略ID；已封存目录保持原位。
平台为真实调用保留开始及终态记录，成功、失败、取消分别表达；窗口／场景结果绑定候选内容、
输入、协议和环境身份，重复计算不增加独立研究证据数量。

`execute_experiment`将声明产物、受管评价产物以及`inspect_candidate`注册的检验证据共同纳入
执行回执。技术检验须在正式执行尚未封存时完成，已存在回执或失败终态的空间拒绝追加检验。
REX记录实际执行事实；阶段报告由TDR的`assemble_delivery`另行验证和发布。

新TDR评价结果产物使用schema 4，REX执行回执仍使用schema 2，两个版本号独立。
`EvaluationRecord.result_artifact`绑定评价产物路径与哈希；封存后可由TDR
`EvaluationEvidenceReference`绑定回执、尝试与完整评价ID，在后续正式执行中恢复检验基线。
原执行保留封存状态，新的复算和检验证据进入本次执行。构造与历史证据限制见
[TDR归档检验说明](../../src/czsc_trader/README.md#8-技术检验用户决定与冻结)。

## 阅读实验来源

研究员核对候选所指向的实验问题、数据门、源码绑定、执行回执和结果身份。
REX执行成功只证明实验按声明运行；其结果不自动成为可交易Alpha、候选资格或冻结授权。

## 实验协议与选择历史

| 记录对象 | 合同要求 |
| --- | --- |
| 执行前协议 | 正式执行前冻结问题、实现、输入、候选空间、预算及评价合同 |
| 探索结果 | 标记`DISCOVERY_ONLY` |
| 研究计数 | 分别记录机制数、字段数、检验路径数、评价数、唯一参数数和交易行为数 |
| 开发池 | 包含已查看、调参、比较或用于接受决定的数据 |
| 数据再使用 | 开发池的滚动、年度、留一及walk-forward切片仍为开发证据 |
| 窗口重叠 | 重叠窗口不计作独立样本 |
| 重复复算 | 不增加独立证据数量 |
| 前瞻数据 | 参与新版本选择后纳入该版本开发池范围 |

研究员负责披露选择历史及污染影响；上述记录不构成独立性证明。实验结构化产物可以补充研究记录，
阶段交付通过`ResearchDeliverable`、`assemble_delivery`和`validate_delivery`绑定完整证据，
调用契约见[TDR五阶段交付](../../src/czsc_trader/README.md#7-五阶段交付)。
