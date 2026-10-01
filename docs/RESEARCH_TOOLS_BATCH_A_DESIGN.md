# 批次A：受管实验、候选身份和评价留证详细设计

状态：供用户评审，未实施。已确认研究员掌握研究控制流程，平台实现被调用的业务操作并保证技术契约；正式研究通过TDR／REX受管入口执行。
基线：`b9bc8442`；承接[总体技术方案](RESEARCH_TOOLS_DESIGN_REVIEW.md)。
本批不实施阶段报告、自检排序、批准冻结或Optuna适配器。

## 1. 变更清单与模块依赖

| 模块 | 新增契约／公共API | 修改及删除的行为 |
| --- | --- | --- |
| REX | `ExperimentDataScope`；`EvaluationAttemptStatus`与可序列化尝试摘要 | `ExperimentDefinition` schema 2；端口强类型；删除FORMAL自动绑定封存数据的规则；新资源契约删除`max_evaluations` |
| SRT | `ImplementationDependency`、`CandidateContentIdentity`；`StrategyRuntime.identify` | 身份认证复用现有加载和定义验证；不改变已有运行哈希算法 |
| SM | `CandidateKey/CandidateRegistrationOrigin/CandidateRegistration/CandidateDerivation`；登记和查询方法 | 候选ID唯一约束及不可变登记；现有冻结版本不变 |
| TDR application | `CandidateRegistrationRequest`；`register_candidate/load_candidate` | 新研究写操作统一从业务入口进入 |
| TDR research_tools | `EvaluationIdentity/EvaluationLineage`及尝试记录 | 认证实际候选内容；记录每次调用；删除`_EvaluationBudget`及预算扣减；支持独立进程评价 |
| DFLS／SE／TXE | 本批不增加API | 使用既有数据、账本及执行能力 |

SM只依赖自身值对象及标准库。SRT不导入SM或REX；候选内容认证返回SRT合同。
REX数据端口直接使用DFLS类型，评价端口使用泛型，由TDR绑定具体请求／结果类型。
TDR完成各模块之间的类型转换；禁止REX反向导入TDR的评价实现。

## 2. REX：定义及上下文

### 2.1 增删改字段

保留`mode: ExperimentMode`及现有`development_cutoff/validation_cutoff`。
新增必填`data_scope: ExperimentDataScope`，新定义固定`schema_version=2`；两者均拒绝裸字符串。
日期必须为`date`，拒绝`datetime`；种子及数量拒绝布尔值。

| mode／data_scope | 必须满足的条件 |
| --- | --- |
| DISCOVERY／DEVELOPMENT | `validation_cutoff=None`，不允许封存读取能力 |
| FORMAL／DEVELOPMENT | 同上；真实数据计算声明`reads_real_returns`；搜索／选参按声明能力校验，研究代码控制预算和停止 |
| FORMAL／SEALED_VALIDATION | validation截止晚于development截止；真实收益及封存读取能力齐备；禁止搜索和选参 |
| DISCOVERY／SEALED_VALIDATION | 构造失败 |

所有请求均由scope推导数据上界，禁止通过`FORMAL`布尔分支隐式扩展范围。
封存验证允许读取开发区数据作为预热，但评价窗口必须位于声明的验证区间；开发数据不得计入验证绩效。
阶段四使用开发池时明确采用`FORMAL + DEVELOPMENT`。

`ExperimentDefinition.sha256`按schema分支计算：schema 1保持原始算法，schema 2包含data_scope。
新正式执行只接受schema 2；历史定义及回执按原schema验真，不重写历史实验。
`ExperimentBinding.schema_version=3`保持独立，不随定义版本改号。

### 2.2 保留API，修改内部校验

保留`create_experiment_context/create_formal_experiment_context/preflight_experiment/execute_experiment`
的入口名称。上下文工厂验证模式及scope；正式工厂仍只使用平台拥有的适配器及显式缓存配置。

`context.data.fetch`核对数据集及请求截止；`context.runtime.create`核对声明输入和可交易窗口；
`context.evaluation.evaluate`核对评价窗口及scope，记录实际输入身份。预检只探测开发区。
TDR工厂及内部字段删除“formal即sealed”的绑定，实际scope必须进入执行追踪和回执。

评价请求中现有`development_cutoff`改名为`data_cutoff`：它表示本次执行数据的截止日。
实验定义继续分别保留开发、验证截止，受管端口检查`data_cutoff`等于该scope的合同上界。
内部评价仍需开发截止语义的旧计算结构由TDR显式适配；不能把验证日期重新写入实验开发截止字段。
新公共调用不同时支持两个同义参数；文件化请求引入新schema解码，旧证据按原schema只读验真。

## 3. SRT：内容指纹

### 3.1 公共API和返回契约

```python
def identify(
    self,
    candidate: StrategyCandidate,
    *,
    dependencies: tuple[ImplementationDependency, ...],
) -> CandidateContentIdentity: ...
```

`ImplementationDependency(name, version)`保存精确声明，名称规范化、去重、版本非空。
dependencies是必填参数；不从运行机器的全部已安装包隐式推断，明确无额外声明时传空元组。
平台及Python实际运行版本另由评价环境身份记录。评价时由已绑定实验的依赖声明提供该参数；
登记时由TDR登记请求提供并核对实验声明，SM登记后保持不可变。内容认证不依赖候选已经登记。

`CandidateContentIdentity`字段：`schema_version=1`、`content_sha256`、`source_sha256`、
`dependency_sha256`。所有SHA-256均校验64位小写十六进制。

### 3.2 规范化及计算

复用`StrategyRuntime.describe`的加载和源码验证路径，取得`RuntimeDefinition`后构造身份负载：

| 纳入内容指纹 | 排除 |
| --- | --- |
| implementation的module、qualname、contract_version、源码相对路径与文件哈希 | candidate_id、release_id、release_hash、登记时间 |
| 完整parameters、inputs、decision、execution、monitoring、capabilities、history、state_mode及tradable_symbol | source_root等机器绝对路径 |
| 规范化的声明依赖、内容身份算法版本 | 本次评价窗口、初始账户资金、临时成本压力、报告和结果 |

固定执行合同内的资金模式、分配比例或费用规则仍纳入指纹；排除的是评价请求的资金和压力覆盖。
默认参数由运行定义物化，未声明参数在契约验证时拒绝，防止payload中存在未计入指纹的执行参数。
JSON规范化使用固定键序、有限数值及明确类型；不将NaN、Infinity、bool当作数值接收。

验证失败抛`RuntimeContractError`，不返回部分身份。`runtime_identity_sha256/runtime_sha256`
沿原算法保留，新增内容指纹不替代已封存的运行身份。

## 4. SM／TDR：评价身份与持久登记分离

### 4.1 必填字段和来源时点

| 类型 | 字段及约束 |
| --- | --- |
| `CandidateKey` | strategy_id、candidate_id；族内唯一，不得回收 |
| `CandidateRegistrationOrigin` | 来源experiment_id、definition_sha256、binding_sha256及预检报告引用；全部在执行前可获得 |
| `CandidateRegistrationRequest`（TDR） | candidate、origin、dependencies、可选derivation；不要求当前实验的执行回执 |
| `CandidateRegistration`（SM） | key、content/source/dependency三个SHA-256字段及身份算法版本、原payload哈希、受管payload／源码清单引用、声明依赖、origin、可选derivation、record_sha256 |
| `CandidateDerivation` | parent及child各自的key与内容指纹、派生类型、参数变化、协议哈希和来源证据引用；parent不能等于child |

每个trial可直接以不可变`StrategyCandidate`进入受管评价。评价认证源码、声明依赖、运行合同
及内容指纹；SM登记用于持久查询、跨阶段交接和冻结，不作为每次评价的前置条件。
研究员决定何时登记。登记前认证已绑定实验定义、源码、声明依赖和预检结果；已有评价可被引用，
不要求尚未产生的执行回执。同一候选后续重用时沿用原登记，追加证据不修改origin或候选ID。
派生关系由研究员显式提交，平台核对父子内容及来源；parent和child均无须为此提前登记。

### 4.2 API及职责

```python
# TDR application：RSCH写入入口
def register_candidate(context: RepositoryContext,
                       request: CandidateRegistrationRequest) -> CandidateRegistration: ...
def load_candidate(context: RepositoryContext,
                   key: CandidateKey) -> StrategyCandidate: ...

# SM：TDR使用的模块API
def register_candidate(self, record: CandidateRegistration) -> CandidateRegistration: ...
def get_candidate(self, key: CandidateKey) -> CandidateRegistration: ...
```

TDR调用SRT identify、验证origin、固化文件，再交给SM登记；SM验证族、键、引用、哈希和冲突。
TDR将SRT认证结果转换为SM标量身份字段，SM不引用`CandidateContentIdentity`类型。
登记前后重算源文件哈希，源在复制／认证期间变化则失败。load读取受管副本，检查哈希、依赖及SRT
定义后返回现有`StrategyCandidate`；原研究目录移动不会改变已登记候选。

存储建议：`research/registrations/<family>/candidates/<candidate_id>.json`，
源码及payload位于同一受管根目录的按内容寻址文件区。先写文件，再原子发布登记记录；
登记文件是登记可见性边界，未被记录引用的暂存文件不算已登记。
写锁范围为研究族；同key且完整登记负载相同幂等返回，同key任一绑定内容不同则
`CandidateIdentityConflict`。内容相同的不同key允许共存。

SM内部路径对调用方不构成API；不提供覆盖、删除和自动换号接口。

研究代码为并发生成的候选分配唯一ID。单次实验汇总及交付校验拒绝同key异内容；SM在登记时
执行持久唯一约束。未登记且未汇总的独立进程之间不存在中心注册校验，不宣称全局实时拒绝冲突。
评价结果始终携带key与内容指纹，不能只按候选ID合并。

## 5. TDR：评价身份与尝试状态

### 5.1 请求与结果

正式评价仍使用`context.evaluation.evaluate(EvaluationRequest) -> EvaluationResult`。
请求中的`strategy`保持现有候选类型，增加可选lineage，截止字段按第2.2节改名。
受管端口通过SRT重新认证实际候选内容，不要求调用方重复传一份可信指纹或登记证明。
未登记候选可正式评价；如使用已登记候选，load及评价分别核对受管副本与实际输入。
评价调用不隐式写SM登记。

`EvaluationLineage`绑定研究员声明的中心候选与派生关系，包含双方key、内容指纹及来源证据引用；
实际执行候选由request.strategy决定。扰动评价核对实际候选等于child，中心等于parent；
普通评价传None。关系认证使用内容与证据，不要求父子均存在SM登记记录。

| 身份 | 生成规则 |
| --- | --- |
| request_hash | 请求的规范化输入意图；保留来源实验和窗口／场景列表，不把机器路径作为内容 |
| evaluation_id | 每个实际候选／窗口／场景单独计算，绑定内容指纹、实际输入身份、资金、实际成本及整手／执行规则、基准、执行／指标版本、运行环境 |
| attempt_id | 平台为每次接受执行的请求创建唯一ID；相同评价重跑也创建新attempt |
| result_hash | 绑定评价身份及实际信号、五类账本、指标、基准结果，结果改变必须改变哈希 |

在SRT完成输入准备、获得实际信号输入身份后最终确定evaluation_id；执行数据指纹不能代替
全部策略输入身份。准备失败的尝试可无evaluation_id，必须保留request_hash及明确错误。
一个请求的attempt关联多个评价坐标；`EvaluationRun`携带各自身份，`EvaluationResult`
携带attempt_id及完整runs。模块级非受管计算不签发受管attempt引用。

### 5.2 单次调用的执行和留证

```text
校验请求类型／scope／候选内容／派生关系／本次执行配置
  → 创建独立attempt_id并记录STARTED
  → 准备实际输入并确定各评价身份
  → 执行SRT／TXE
  → 核对结果身份、坐标覆盖和账本，写入结果文件
  → 原子发布包含结果引用的SUCCEEDED记录
```

输入校验拒绝时抛明确异常，不启动评价；搜索提议被拒绝由研究侧搜索轨迹记录。
记录开始／结束时间、耗时、请求坐标数、实际完成坐标数、错误和结果引用，供研究代码自行判断。
平台不按调用数或坐标数扣减研究预算，不因历史评价次数达到阈值停止后续调用。

状态描述本次调用的已观察事实：`STARTED/SUCCEEDED/FAILED/CANCELLED/UNKNOWN`；
它不提供排队、调度、重试或接续控制。终态不得被重跑覆盖。
只有捕获明确取消信号才记CANCELLED；异常为FAILED；中断后只留下STARTED且无法核实结果时，
读取或归档呈现UNKNOWN，不凭空认定执行失败或成功。
写成功记录失败时不得返回成功。后续按原attempt查询已提交事实，不能自动发起第二次评价。
首批通过既有`context.trace`暴露强类型尝试摘要，失败异常携带attempt_id和错误码；不新增一套任务查询服务。

### 5.3 删除预算控制，支持调用方编排并发

| 模块／契约或API | 拟修改 |
| --- | --- |
| REX `ExperimentResources` | 新契约删除`max_evaluations`；保留`max_workers/random_seed/native_threads_per_worker`，表达本次执行配置 |
| TDR `create_experiment_context/create_formal_experiment_context` | 删除搜索必须声明评价预算的检查及预算对象注入；每个进程独立创建绑定同一实验身份的上下文 |
| TDR `preflight_experiment` | 删除搜索预算必填校验；继续检查输入、依赖、数据范围与执行配置 |
| TDR application `preflight_experiment_archive` | 删除公共参数`max_evaluations`及向资源对象的转传 |
| TDR `_ExperimentEvaluationAccess.evaluate` | 删除`_EvaluationBudget.claim`调用及`_EvaluationBudget`类；增加单次调用的开始、结果及失败留证 |

历史资源字段仅由旧证据解码路径读取并按原算法验真；新公共调用不接受该字段，也不静默忽略。
搜索预算保留在研究员的协议／搜索记录中；实际次数和耗时是观测数据，是否停止由研究代码决定。
Optuna Study、sampler、进程池、任务分发、剪枝和重试均留在研究代码中。

本批要求受管评价可在调用方启动的独立进程中使用；单请求内部窗口／场景并行继续保留。
每个进程通过正式工厂绑定相同定义、源码绑定和数据范围，使用隔离的工作目录；不共享可变上下文。
`workers/native_threads_per_worker`等配置只约束本次调用，平台校验类型及支持范围，
不计算整个搜索的并发额度。研究代码负责避免进程池与请求内并行造成资源过量使用。

每个attempt在独立目录中写规范JSON及结果文件，以原子发布完成记录作为成功边界；
无需为搜索引入SQLite、共享预算或调度服务。可序列化摘要绑定实验定义／源码绑定哈希、
attempt及评价身份、状态、时间、错误和产物引用。研究代码提交各进程产物清单，REX归档校验
声明记录的来源、哈希、重复ID及结果完整性；不从Optuna内部反推任务集合。
跨进程摘要交回现有`ExperimentResult/context.trace`的具体强类型签名仍需评审后确定。

归档将已提交的尝试及结果引用纳入REX产物哈希／回执。只能验证声明的证据集合，不能据此证明
研究员已提交进程外的全部搜索行为。归档失败必须显式失败，不能留下成功回执指向未封存的临时文件。
`execute_experiment`的异常路径同样保存可取得的尝试和错误记录；没有完整结果时不补造成功回执。
失败记录的封存本身出错时保留明确的未完成状态和工作文件位置，不能声称已经完成正式交付。
REX新增独立尝试摘要合同，仅存标量身份、状态、错误及结果引用，避免依赖TDR运行结果类。

## 6. 错误分类与验收

| 错误类别 | 示例 | 行为 |
| --- | --- | --- |
| 输入合同错误 | scope冲突、父子错绑、非法日期 | 执行前抛错 |
| 身份冲突 | 同候选ID异payload／源码／依赖 | 拒绝登记；保留原记录 |
| 执行配置错误 | workers为布尔值、线程数非正整数、配置不受支持 | 执行前拒绝；不产生STARTED |
| 执行失败 | 数据未就绪、SRT／TXE异常、结果身份不符 | FAILED及attempt_id；保留错误与已完成部分的证据 |
| 结果未知 | 进程失联、结果持久化状态不明确 | UNKNOWN；先核对原尝试，不自动重试 |

最小聚焦验收覆盖：

1. FORMAL开发池可以搜索；封存验证禁止搜索，scope不能被cache或目录改变。
2. schema 1原定义哈希可验证；新定义的scope改变必然改变哈希；定义和源码绑定版本独立。
3. 相同有效定义换候选ID或移动目录，内容指纹不变；改源码、依赖、参数或固定规则则改变。
4. 登记不依赖未来回执；相同登记幂等、冲突失败；登记前后内容身份及同输入评价身份保持一致。
5. 未登记候选可正式评价且不写SM；扰动引用实际child；同key异内容在汇总或登记时拒绝。
6. 同评价重跑的evaluation_id稳定、attempt_id不同；实际输入变化使evaluation_id变化。
7. 异常、取消、崩溃和结果提交失败不造成假成功；完成数仅作观测，不影响后续调用；旧证据哈希仍可验真。
8. 两个独立进程的正式评价可并发完成，产物互不覆盖且可校验归档；正式上下文拒绝自定义评价器。

## 7. 本批待评审决定

- 是否采纳scope必填及新`EvaluationRequest.data_cutoff`字段，消除开发／验证截止同名异义。
- 是否采纳第4节候选持久登记字段、存储及冲突处理；每次评价无须登记的原则已确认。
- 是否采纳内容指纹显式依赖声明，同时保留既有运行身份哈希。
- 明确多进程评价摘要交回`ExperimentResult/context.trace`的最小强类型契约，复用现有产物归档入口。

研究控制流程、搜索预算、并发编排、剪枝和重试归研究员；平台保证单次执行合同及证据完整性。
以上边界已确认，不再作为待决定的取舍。多进程能力须通过本批验收，不以序列化候选替代执行验证。

本文件明确了可实施的接口及验收范围；用户确认后再修改源码。没有新增经济目标、研究阶段授权、
具体候选冻结批准或生产操作授权。
