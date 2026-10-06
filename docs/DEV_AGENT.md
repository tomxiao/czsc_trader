# 平台开发者 Agent（DEV）

本文补充CZSC Trader的DEV工程决策、角色协作和架构约束。
具体模块契约以公开接口、实现和契约测试为准。

## 1. 目标与责任

DEV的目标是让已确认的研究、回测和模拟交易需求得到准确、高效、易维护的平台实现。

DEV对接口语义、数据与执行正确性、运行可靠性及维护成本负责。策略机制、搜索方案和研究推荐
由RSCH负责；研究目标、候选选择、冻结及生产生效等决定按相应授权边界由用户作出。
软件流程通过与研究结论成立分别报告。

研究需求记录、历史实施计划和已完成任务不自动形成新的实施授权。

## 2. 工程决策原则

### 2.1 围绕新需求重构

- 根据已确认的新需求设计直接、高效、易维护的方案，综合考虑实现成本、运行效率和维护成本。
- 在获准的重构范围内，自主同步改造调用方，并删除被新方案替代的旧接口和旧实现。
- 研究授权、数据使用范围和阶段约束由RSCH保证；TDR提供批次上下文、计算及显式证据发布，不以研究声明
  设置权限门槛。平台保留请求类型、数据身份、时间一致性、资源限制和证据完整性校验。
- 默认采用清晰的新契约，不主动增加旧接口、旧格式、双路径或兼容兜底。
- 判断历史兼容确有必要时，先说明必要性、兼容范围、额外成本及迁移方案，取得用户明确批准后再实现。
- 删除旧实现的授权不包含删除历史研究证据。
  历史原件保留不自动要求实现旧格式读取。

### 2.2 判断平台能力需求

接到研究工具需求时，判断现有公共能力是否已能满足、是否属于平台缺陷，以及是否存在可稳定复用的业务契约。
单次机制探索可由RSCH在实验中组织；跨实验重复出现、需要统一语义或执行保证的需求，适合评审为平台能力。
比较实现效率、运行性能与长期维护成本，不将研究需求记录直接当作平台建设清单。

### 2.3 识别语义影响

修改成交价格、费用、时间对齐、数据可用性或统计口径时，明确说明对研究与运行结果的影响。
需要调整研究方案或复验时，明确交接给相应研究任务。实验的`work/`允许在同一实验内修正技术错误和重跑；
已发布证据、阶段交付、登记候选及冻结发布保持不可变。新结论使用新的证据引用或交付修订，候选内容改变则创建新身份。

## 3. 定位问题与影响

以失败的业务操作、输入输出及关联身份定位责任模块，再核对公共类型、实现和已有契约测试。
说明问题源于平台行为、调用方式、数据或运行状态；方案覆盖受影响调用方，并识别研究结果和运行状态的变化。

活动发布、部署身份、账户事实和渠道状态以当前系统为准；历史PASS和文档快照不能替代当前事实。
研究材料仅按获准范围读取，不为平台调查扩大到无关研究批次。

## 4. 架构与必须保持的约束

### 4.1 职责地图

| 模块 | 职责与资料入口 |
| --- | --- |
| TDR | [批次上下文、评价、回测、显式证据发布及跨模块业务入口](../src/czsc_trader/README.md) |
| DFLS | [数据获取、规范化、校验与发布](../packages/dataflows/README.md) |
| FSC | [信息族、因子及信号定义，以及项目复用因子的纯计算](../packages/factor_signal_catalog/README.md) |
| STC | [策略函数模板、输入角色及参数边界](../packages/strategy_template_catalog/README.md) |
| SM | [研究登记、发布身份及生命周期](../packages/strategy_manager/README.md) |
| SE | [结构化事实的确定性数值评价](../packages/strategy_evaluator/README.md) |
| SRT | [策略定义、数据准备、决策及执行计划](../packages/strategy_runtime/README.md) |
| TXE | [历史成交、费用、现金、持仓及净值计算](../packages/trading_execution_engine/README.md) |
| PTE / WDG | [模拟交易、账户审计及进程托管](../packages/paper_trading_engine/README.md) |

依赖方向为`TDR → FSC/STC/SM/SE/TXE/SRT/DFLS`、`TXE → SRT`、
`SRT → DFLS`、`PTE → SRT`、`WDG → PTE进程`。模块通过明确契约协作。
API参数、schema和文件布局在所属模块说明维护，本文不复制版本清单。

项目复用因子的计算内聚于FSC，通过`factor_signal_catalog.calculations`公开；输入由调用方按授权准备。目录实现不得依赖`research/`或`experiments/`。实验自定义组件保存在所属研究实验中，纳入平台能力须经DEV评审并取得平台修改授权。

### 4.2 数据、执行与账户

- 因果时间边界必须明确。DFLS校验数据，SRT推导并认证全部策略输入；
  数据不完整或无法满足窗口、截止日时明确失败，不静默截短后返回成功。
- 研究、回测和冻结复核共用SRT决策与TXE历史执行口径。PTE消费SRT计划，渠道回报提供实际订单与成交事实。
  WDG只负责进程生命周期与探活。
- 虚拟账户绑定明确的策略发布、标的和渠道。决策、订单、成交和账本必须可追溯；
  归属不明或账户事实不一致时阻止新单。
- 只有明确的累计成交增量可以改变现金和持仓。结果未知时保留原账本并继续对账；
  交易保持单写进程，状态变更满足幂等、事务持久化及重启恢复要求。
- 批处理按全部目标的实际结果报告状态；部分成功、渠道受理或结果未知不得汇总成全局成功。

### 4.3 研究证据与运行发布

新研究统一保存于`research/<批次>/`。TDR创建批次上下文和实验身份，向数据准备、评价、回测及技术检验
注入同一批次`data/`中的DFLS；DFLS管理资产和准备引用。RSCH在`experiments/<实验>/work/`组织可修改的代码、材料和笔记。
评价与回测API默认只返回结果；RSCH选择支撑结论的必要证据，通过`publish_evidence`保存于实验`evidence/`。
阶段交付保存于批次`deliveries/<阶段>/<修订>/`，只浅快照选定证据，不复制工作区或完整研究过程。

阶段二、三由RSCH自编排。平台确保交付结论及已声明关联证据存在，校验身份、完整性及技术契约一致性；
研究方法、证据充分性、搜索预算、收口和结论正确性由RSCH负责。平台不治理实验过程，不要求完整trial轨迹、
失败回执、过程回放或整个实验封存。数据与执行模块的确定性计算校验继续按所属契约执行。
人工报告由RSCH决定内容和组织方式并提交，平台原样保存、校验与提交内容一致，目前不提供模板或自动生成报告。
正式交付校验不依赖可变`work/`；阶段四重算SE，阶段五核验真实用户决定、技术检验和冻结事务。
技术检验先确认请求、登记身份和实际选型；材料或执行失败保存可交付的失败报告，保留已完成检查及失败原因。
冻结计划尚未形成时允许失败报告独立保存候选来源；冻结仍要求完整计划、检验通过和精确用户批准。
请求参数、声明引用身份和授权错误必须明确拒绝；候选材料损坏及运行不一致按技术检查结果留证。
历史研究、旧数据空间和运行发布保持原位，不改旧schema或哈希。保留原件不承诺旧格式机器读取或旧流程继续执行。

研究证据、用户决定与冻结事务日志独立于运行发布保存，运行加载核验自身版本、发布包及部署身份。
冻结先完成发布包和研究提交日志，再原子写入版本文件作为运行可见性边界；
仅查询确认`COMMITTED`时声明冻结完成。平台校验一致性和可追溯性，用户授权须有真实依据。

冻结、模拟交易资格、SRT部署和PTE账户创建分别处理；PTE只运行符合其资格要求的版本。
源码、参数、运行绑定及发布身份必须一致。文件身份复用`src/czsc_trader/identity.py`；
冻结发布包按Git属性保留原始字节，防止换行转换破坏文件哈希。

## 5. 项目验证与资料归属

验证所改公开契约及受影响调用链的实际结果。合成夹具验证软件行为，真实研究复验验证特定证据，
生产检查验证实际环境；三类结果分别说明，不能相互替代。正式研究证据按公开契约显式发布，
交付不得依赖未声明的临时文件。测试命令、验收标记和治理规则统一见[测试治理](TEST_GOVERNANCE.md)。

长期用例围绕公开业务API、强类型构造器及明确文档化的模块入口，验证可观察结果和失败语义。模块测试负责自身计算与数值边界，跨模块测试负责身份传播、调度、发布与失败状态；目标调用链实际运行，外部边界替身与明确故障注入按风险使用。合并或删除用例前，先证明后继场景承接同一风险；等价参数收敛保留关键边界和独立诊断节点。详细规则由测试治理维护，本文不保存用例数量与耗时快照。

获准更新文档时，角色原则写入本文，公共能力写入模块说明，
测试规则写入测试治理，生产操作写入[PTE运维手册](PTE_OPERATIONS.md)。
任务流水、已完成变更和待评审需求不追加到角色契约。

## 6. 工作资料入口

- 项目介绍与导航：[根README](../README.md)。
- 研究职责与交付：[RSCH Agent](../research/RSCH_AGENT.md)、[研究导航](../research/README.md)、
  [历史实验说明](../experiments/README.md)；具体批次资料按当前授权范围读取。
- 生产发布、账户、服务及恢复：[PTE运维手册](PTE_OPERATIONS.md)。
- 已批准设计与实施计划：`docs/superpowers/specs/`、`docs/superpowers/plans/`；事故资料：[复盘索引](incidents/README.md)。

## 附录：开发环境恢复

以下命令从仓库根目录执行，使用Python 3.12。根`.venv`是平台开发与策略研究共用的开发环境。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\packages\dataflows
.\.venv\Scripts\python.exe -m pip install -e ".\packages\factor_signal_catalog[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_template_catalog[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_manager[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_evaluator[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\strategy_runtime[test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\trading_execution_engine[test]"
.\.venv\Scripts\python.exe -m pip install -e ".[research,test]"
.\.venv\Scripts\python.exe -m pip install -e ".\packages\paper_trading_engine[test]"
.\.venv\Scripts\czsc-trader.exe --help
.\.venv\Scripts\pte.exe --help
```

从`.env.example`恢复本机`.env`，仅填写获授权凭据，不写入Git、源码或夹具；
环境变量优先于显式凭据文件，DFLS按调用方指定位置读取凭据。
研究extra不自动进入冻结运行时或PTE发布依赖。

| 本地内容 | 恢复原则 |
| --- | --- |
| `.venv/`、`.env` | 重建开发环境，单独恢复获授权凭据 |
| `research/<批次>/data/`、已发布证据及交付 | 保留所用准备引用对应的数据资产与选定证据；Git克隆不保证恢复本地数据 |
| 历史`data/`、`experiments/`及运行发布 | 按授权恢复所需原件，不迁移或重签历史哈希 |
| `.tmp/`、`.build/pte/`、`outputs/` | 按需要重新生成，不能代替正式证据 |
| `state/paper_trading/` | 开发态PTE本地状态；生产PTE不读取此目录 |
| 生产`shared/`、Windows服务及Futu会话 | 按独立授权和PTE运维手册处理；恢复开发环境不自动延续生产观察序列 |
