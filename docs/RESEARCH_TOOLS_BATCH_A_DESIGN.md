# 批次A：受管实验、候选身份和评价留证详细设计

状态：供用户评审，未实施。正式研究通过TDR／REX受管执行的原则已确认。
基线：`b9bc8442`；承接[总体技术方案](RESEARCH_TOOLS_DESIGN_REVIEW.md)。
本批不实施阶段报告、自检排序、批准冻结或Optuna适配器。

## 1. 变更清单与模块依赖

| 模块 | 新增契约／公共API | 修改及删除的行为 |
| --- | --- | --- |
| REX | `ExperimentDataScope`；`EvaluationAttemptStatus`与可序列化尝试摘要 | `ExperimentDefinition` schema 2；端口强类型；删除FORMAL自动绑定封存数据的规则 |
| SRT | `ImplementationDependency`、`CandidateContentIdentity`；`StrategyRuntime.identify` | 身份认证复用现有加载和定义验证；不改变已有运行哈希算法 |
| SM | `CandidateKey/CandidateRegistrationOrigin/CandidateRegistration/CandidateDerivation`；登记和查询方法 | 候选ID唯一约束及不可变登记；现有冻结版本不变 |
| TDR application | `CandidateRegistrationRequest`；`register_candidate/load_candidate` | 新研究写操作统一从业务入口进入 |
| TDR research_tools | `EvaluationIdentity/EvaluationLineage`及尝试记录 | 评价请求／结果、上下文和追踪；正式评价验证登记身份；预算与尝试原子留证 |
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
| FORMAL／DEVELOPMENT | 同上；真实数据计算声明`reads_real_returns`；搜索／选参按能力及预算允许 |
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
平台及Python实际运行版本另由评价环境身份记录。该参数由TDR登记请求提供，SM登记后保持不可变。

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

## 4. SM／TDR：先登记，再评价

### 4.1 必填字段和来源时点

| 类型 | 字段及约束 |
| --- | --- |
| `CandidateKey` | strategy_id、candidate_id；族内唯一，不得回收 |
| `CandidateRegistrationOrigin` | 来源experiment_id、definition_sha256、binding_sha256及预检报告引用；全部在执行前可获得 |
| `CandidateRegistrationRequest`（TDR） | candidate、origin、dependencies、可选derivation；不要求当前实验的执行回执 |
| `CandidateRegistration`（SM） | key、content/source/dependency三个SHA-256字段及身份算法版本、原payload哈希、受管payload／源码清单引用、声明依赖、origin、可选derivation、record_sha256 |
| `CandidateDerivation` | 已登记parent key及内容指纹、child key、派生类型、参数变化和协议哈希；parent不能等于child |

登记前认证已绑定实验定义、源码、声明依赖和预检结果；登记后进行评价，执行结束后回执引用
登记及评价结果。候选登记不需要自己的未来回执，消除“有评价才能登记、有登记才能评价”的循环。
同一候选在后继实验重用时，沿用原登记；新实验的评价与回执追加引用，不改候选origin。

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
登记文件是候选可见性边界，未被记录引用的暂存文件不算已登记。
写锁范围为研究族；同key且完整登记负载相同幂等返回，同key任一绑定内容不同则
`CandidateIdentityConflict`。内容相同的不同key允许共存。

SM内部路径对调用方不构成API；不提供覆盖、删除和自动换号接口。

## 5. TDR：评价身份与尝试状态

### 5.1 请求与结果

正式评价仍使用`context.evaluation.evaluate(EvaluationRequest) -> EvaluationResult`。
请求中的`strategy`保持现有候选类型，增加可选lineage，截止字段按第2.2节改名。
受管端口按候选key加载登记并重新核对内容，不要求调用方重复传一份可信指纹。
正式评价遇到未登记候选直接失败，不隐式登记；探索及合成诊断不自动写候选登记。

`EvaluationLineage`绑定中心候选与派生登记引用，实际执行候选由request.strategy决定。
扰动评价要求实际候选等于登记child，中心等于parent；普通评价传None。

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

### 5.2 接受、计费、完成的顺序

```text
校验请求类型／scope／候选登记／派生关系／资源上限
  → 同一事务内预占预算，创建STARTED尝试
  → 准备实际输入并确定各评价身份
  → 执行SRT／TXE
  → 核对结果身份、坐标覆盖和账本，写入结果文件
  → 同一事务内记录结果引用并转为SUCCEEDED
```

输入校验拒绝时抛明确异常，不启动评价、不扣预算；搜索提议被拒绝由研究侧搜索轨迹记录。
接受执行后按`len(windows) * len(costs)`预占，并计入已消耗的执行预算；失败或取消不返还，
避免重试绕过预算。另行统计实际完成坐标数，不将预占量表述为已完成评价量。

状态转移为`STARTED → SUCCEEDED/FAILED/CANCELLED/UNKNOWN`；终态不得被重跑覆盖。
只有捕获明确取消信号才记CANCELLED；异常为FAILED；崩溃或提交结果未知为UNKNOWN。
写成功记录失败时不得返回成功。后续按原attempt查询已提交事实，不能自动发起第二次评价。
首批通过既有`context.trace`暴露强类型尝试摘要，失败异常携带attempt_id和错误码；不新增一套任务查询服务。

### 5.3 留证实现及本批并发范围

使用标准库SQLite在受管工作空间保存预算及尝试，单次事务同时更新预算与STARTED记录。
同一工作空间再次打开必须核对定义、资源和已有计数；不允许重建上下文清零。
已知成功／失败记录保留；失联尝试显式标识，不自动恢复执行。

本批只有一个上下文所有者负责接收评价和写入尝试账本。现有单请求内部窗口／场景并行可保留，
worker返回结果由所有者提交；不支持把正式上下文直接pickle给多个搜索进程。
跨进程搜索的共享预算、worker身份和接续属于后续批次，未验收前不宣称支持。

归档时把预算、全部尝试及结果引用导出为规范JSON并纳入REX产物哈希／回执；
工作用SQLite不是唯一交付证据。归档失败必须显式失败，不能留下成功回执指向未封存的临时文件。
`execute_experiment`的异常路径同样保存可取得的尝试和错误记录；没有完整结果时不补造成功回执。
失败记录的封存本身出错时保留明确的未完成状态和工作文件位置，不能声称已经完成正式交付。
REX新增独立尝试摘要合同，仅存标量身份、状态、错误及结果引用，避免依赖TDR运行结果类。

## 6. 错误分类与验收

| 错误类别 | 示例 | 行为 |
| --- | --- | --- |
| 输入合同错误 | scope冲突、未登记候选、父子错绑、非法日期 | 执行前抛错；预算不消耗 |
| 身份冲突 | 同候选ID异payload／源码／依赖 | 拒绝登记；保留原记录 |
| 资源拒绝 | 预占后将超过预算 | 原子拒绝；不产生STARTED |
| 执行失败 | 数据未就绪、SRT／TXE异常、结果身份不符 | FAILED及attempt_id；保留已消耗预算 |
| 结果未知 | 进程失联、结果持久化状态不明确 | UNKNOWN；先核对原尝试，不自动重试 |

最小聚焦验收覆盖：

1. FORMAL开发池可以搜索；封存验证禁止搜索，scope不能被cache或目录改变。
2. schema 1原定义哈希可验证；新定义的scope改变必然改变哈希；定义和源码绑定版本独立。
3. 相同有效定义换候选ID或移动目录，内容指纹不变；改源码、依赖、参数或固定规则则改变。
4. 候选先登记后评价不依赖未来回执；相同登记幂等、冲突失败、来源变化须显式处理。
5. 未登记正式评价失败；扰动引用实际child；失败结果不能成为有效评价引用。
6. 同评价重跑的evaluation_id稳定、attempt_id不同；实际输入变化使evaluation_id变化。
7. 预算扣减与STARTED原子一致；异常、取消、崩溃和结果提交失败不造成假成功或预算重置。
8. 归档包含全部尝试且不依赖工作SQLite；正式上下文拒绝自定义评价器及未支持的进程传输。

## 7. 本批待评审决定

- 是否采纳scope必填及新`EvaluationRequest.data_cutoff`字段，消除开发／验证截止同名异义。
- 是否采纳“执行前实验身份登记候选、执行后回执引用候选”的顺序。
- 是否采纳内容指纹显式依赖声明，同时保留既有运行身份哈希。
- 是否采纳接受执行后预占预算不返还，并将实际完成次数单列。
- 是否接受首批只支持单一正式上下文所有者，跨进程搜索受管接续后续实现。

本文件明确了可实施的接口及验收范围；用户确认后再修改源码。没有新增经济目标、研究阶段授权、
具体候选冻结批准或生产操作授权。
