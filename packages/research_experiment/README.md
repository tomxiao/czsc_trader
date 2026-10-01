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

## 正式实验预检

先阅读[公共导出](src/research_experiment/__init__.py)，沿导入核对绑定、定义和预检契约。

### 契约版本与实现

| 对象 | 当前要求 | 代码入口 |
| --- | --- | --- |
| `experiment_binding.json` / `ExperimentBinding` | 新正式实验使用`schema_version=3`；加载器仍支持历史版本2 | [loader.py](src/research_experiment/loader.py) |
| `ExperimentDefinition` | 当前`schema_version=1`；在`subjects`中声明唯一研究标的 | [contracts.py](src/research_experiment/contracts.py) |
| `ResearchExperiment.synthetic_precheck()` | 返回`ExperimentPrecheckResult`或`None`，不读取真实研究结果 | [contracts.py](src/research_experiment/contracts.py) |

两个对象的版本号独立，不得把绑定版本3填写到`ExperimentDefinition.schema_version`。

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

源码与定义冻结后、首次正式执行前调用TDR公共`preflight_experiment_archive(context, experiment, ...)`，见[公共导出](../../src/czsc_trader/application/__init__.py)。显式提供`max_workers`、搜索预算`max_evaluations`及`PredecessorEvidence`序列；前驱绑定工作空间与回执哈希。示例见[TDR说明](../../src/czsc_trader/README.md)。用户CLI仅保留回测，研究员不得通过CLI执行预检。

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

Optuna继续作为独立第三方库使用，由实验实现组织搜索，并遵守已声明的能力及评价次数预算。
TDR/REX不接管study、sampler或trial生命周期；当前未提供平台Optuna适配器。

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

研究员负责披露选择历史及污染影响；上述记录不构成独立性证明。现有协议字段不足时由实验结构化产物补齐，统一交付入口待CAP-01实现，见[交付契约占位](../../docs/RESEARCH_DELIVERY_CONTRACT.md)。
