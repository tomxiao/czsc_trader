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
| `ResearchExperiment.synthetic_precheck()` | 实现不读取真实研究结果的合成预检 | [contracts.py](src/research_experiment/contracts.py) |

两个对象的版本号独立，不得把绑定版本3填写到`ExperimentDefinition.schema_version`。

- 合成预检必须覆盖输入结构、边界、时间对齐和实际计算路径。
- 合成预检不得使用真实收益筛选参数。
- 预检未通过时必须修正并重新执行。
- 预检通过前不得读取正式结果。
- DFLS的`READY`状态不得替代历史可得性或研究合同核验。

### API入口

源码与定义冻结后、首次正式执行前调用TDR公共`preflight_experiment_archive(context, experiment, ...)`，见[公共导出](../../src/czsc_trader/application/__init__.py)。显式提供`max_workers`、搜索预算`max_evaluations`及`PredecessorEvidence`序列；前驱绑定工作空间与回执哈希。示例见[TDR说明](../../src/czsc_trader/README.md)。用户CLI仅保留回测，研究员不得通过CLI执行预检。

- 技术失败档案必须按实际档案身份引用。
- 不得伪造成功receipt。

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
