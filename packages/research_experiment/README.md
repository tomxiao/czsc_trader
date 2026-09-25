# 研究实验（Research Experiment，REX）

本文面向策略研究员（RSCH）和首席投资官（CIO）。REX给一个可证伪实验提供可执行锚点、
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

## CIO：阅读实验来源

CIO核对候选所指向的实验问题、数据门、源码绑定、执行回执和结果身份，再通过TDR独立体检。
REX执行成功只证明实验按声明运行；其结果不自动成为可交易Alpha、候选资格或冻结授权。
