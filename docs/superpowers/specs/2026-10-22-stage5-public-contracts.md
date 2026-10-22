# 阶段五公共契约、API与存储设计

状态：已获用户批准，已在`codex/stage5-technical-validation`实现并通过[聚焦验证](../plans/2026-10-22-stage5-technical-validation.md)。设计基线：`ad468f4a`。依据：[RSCH新版需求](../../../research/S015/DEV_STAGE5_REQUIREMENTS.md)。本次实施只使用隔离合成测试，不冻结S015研究候选或操作生产。

本文定义已获批准的公共契约。当前调用方式和状态处理见[TDR手册](../../../src/czsc_trader/README.md#8-技术检验用户决定与冻结)；公共类型、序列化及调用方随实施同步。

## 1. 范围与设计决定

阶段五只有两个检验结果：行为等价、PTE可部署且可运行。直接使用指定候选及其技术输入，不读取阶段一至四报告、不检查排名成员关系、不递归认证研究来源。选型和冻结批准仍须绑定精确对象。

本版采取以下确定方案：

- RSCH继续使用`inspect_candidate`一个主入口；原回测为可选输入。
- 新检验使用`candidate-inspection-v2`协议；旧8项报告不转译为新PASS。
- 提前构造最终格式的待冻结包，正式冻结核对并提交同一内容。
- 技术输入复用SRT/DFLS/TXE类型，不复用带必需基准、绩效和谱系字段的`EvaluationRequest`。
- PTE提供一个供TDR调用的隔离检验入口；许可、目录、账户和渠道组件由平台构造。
- 正式证据继续使用既有内容寻址目录；不增加持久PASS缓存、检验调度服务或通用测试脚本语言。

## 2. 类型归属与基本约定

| 所属模块 | 公共类型或职责 |
| --- | --- |
| SM `freeze_contracts` | 用户选择、冻结计划、报告中的持久化记录、冻结请求及回执 |
| TDR `application` | 主请求、技术回放输入及业务编排；向RSCH重导出入口类型 |
| PTE `inspection`（新增） | 有限场景协议、隔离运行请求与原始运行结果 |
| SRT | 输入绑定、发布包认证、策略运行；共用包认证逻辑及无宿主依赖的检验控制类型 |
| DFLS / TXE | 准备数据引用、行情输入及历史执行规则，沿用原有语义 |

所有记录使用不可变强类型；拒绝未知字段、非法枚举、NaN/Inf、不安全路径及重复业务ID。SHA256为64位小写十六进制。日期为`date`，事件时间为带时区`datetime`，持久化时间统一带偏移的ISO格式。价格/现金精确预期使用`Decimal`并以十进制字符串存储，既有TXE的浮点字段按明确比较规则处理。

现有`ResearchEvidenceRef(owner, path, sha256)`用于检验对象；`path`相对于owner。现有`EvidenceRef.repository_path`指源证据位置，而其`path`是交付包内部路径，两者不能互换。不新增万能路径字符串作为证据接口。

## 3. 用户选择与候选加载

### 3.1 新版选择对象

```python
@dataclass(frozen=True)
class CandidateSelectionSubject:
    candidate: CandidateKey
    content_sha256: str
    registration_sha256: str
    schema_version: Literal[2] = 2

def record_research_decision(
    repository: RepositoryContext,
    decision: ResearchDecision,
) -> DecisionReference: ...

def load_candidate(
    repository: RepositoryContext,
    key: CandidateKey,
) -> StrategyCandidate: ...
```

选择对象移除`delivery`。`ResearchDecision`保留现有决定ID、策略族、动作、确认原文引用和理由；批准对象的记录不能替代真实用户确认。

`record_research_decision`对选择只核对登记元数据、两个哈希及确认来源，不调用`validate_delivery`。同决定ID同字节可确认已保存；不同内容拒绝覆盖。

`load_candidate`的语义明确为加载已登记的可执行内容：核验登记记录、payload、源码闭包、依赖及SRT实际内容身份。它不解析`origin.evidence`或`derivation.evidence`指向的研究文件。SM现有完整登记文件核验可保留原语义，但阶段五运行路径不得调用它；不增加`skip_validation`开关。

候选登记原件不重写，登记快照仍可包含历史来源引用，阶段五将其视为元数据。新增候选登记仍沿用现有登记规则；“允许从未评价的候选登记”不包含在本次变更中。

## 4. 主检验输入

```python
@dataclass(frozen=True)
class FreezeTarget:
    version: str
    parent_version: str | None
    change_summary: str
    selection_data_cutoff: date
    forward_start: date

@dataclass(frozen=True)
class InspectionReplay:
    coordinate: InspectionCoordinate       # 既有window_id、scenario_id
    input_binding: StrategyInputBinding    # 已准备的候选输入
    execution_data: BacktestExecutionData  # 必须完整绑定DFLS准备资产
    initial_cash: float
    one_way_cost: float
    baseline: EvaluationEvidenceRef | None = None

@dataclass(frozen=True)
class InspectionProtocol:
    method_version: Literal["candidate-inspection-v2"]
    comparison: Literal["ECONOMIC_V1"]
    float_tolerance: float
    pte: PteInspectionProtocol

@dataclass(frozen=True)
class CandidateInspectionRequest:
    candidate: CandidateKey
    selection: DecisionReference
    research: ResearchContext
    experiment: ExperimentRef
    target: FreezeTarget
    protocol: InspectionProtocol
    replays: tuple[InspectionReplay, ...]
    data_kind: InspectionDataKind          # HISTORICAL或SYNTHETIC，显式来源声明
    additional_files: tuple[FreezeFile, ...] = ()
    remaining_risks: tuple[str, ...] = ()

def inspect_candidate(
    repository: RepositoryContext,
    request: CandidateInspectionRequest,
    *,
    control: InspectionControl | None = None,
) -> CandidateInspectionReport: ...
```

### 4.1 输入约束

- `replays`非空、坐标唯一；`input_binding.plan.tradable_window`确定评价窗口，预热和交易日历来自该计划。初始现金有限且大于0，单边费用在`[0,1)`。
- 首版直接回放从现金空仓开始；需要持仓恢复时通过正常前置交易建立，不接受任意数据库行或内部状态播种。若后续需要非空初始持仓，必须定义独立强类型合同，不能静默忽略。
- `execution_data`的prepared引用、角色请求、内容身份、市场规则、pricing及实际数据必须齐全、一致；缺少绑定时拒绝，不在线补取或自动截短。其输入范围与策略绑定及截止日一致。
- 主请求不需要buyhold、收益门槛、排名、绩效指标或研究谱系。标的与执行策略从候选合同推导并与执行数据核对，调用方不能覆盖策略合同；费用是该场景显式条件。
- 两个实现的绑定含各自策略身份，完整绑定哈希可以不同；必须比较请求、日历、覆盖和底层数据内容，并分别保存双方绑定。
- 数据只使用获准的准备资产；合成场景亦先经明确标记的离线DFLS提供器准备和留证，不直接塞入预计算信号。

### 4.2 可选原结果

没有`baseline`时，执行当前候选与待冻结实现的直接比较，附加复现状态为`NOT_REQUESTED`。

提供`baseline`时，引用必须唯一选中本坐标的结果；核对候选内容、输入、窗口、初始资金、费用和执行规则，再比较原结果与当前候选。引用不匹配或复现失败属于本次声明检查失败，A为FAIL；不新增第三个顶层目的。只加载这份指定结果，不追溯其研究报告。

### 4.3 比较语义

`ECONOMIC_V1`固定比较信号、决策、目标、订单、成交、费用和账户结果，以及策略公开的影响行为状态。方向、数量、状态、日期和计数精确比较；浮点容差仅用于白名单数值字段，默认0，不能用于内容哈希、数量或时间。

排除项固定为纯运行标识及候选/发布身份表示，不允许RSCH传任意忽略字段列表。每次结果记录具体比较器版本和排除列表。差异包含坐标、时点、对象序号、字段、双方值与容差，完整差异作为证据保存。

## 5. PTE场景公共契约

以下类型由`paper_trading_engine.inspection`提供，TDR重导出RSCH所需输入类型。它们表示固定业务事实，不支持任意Python、SQL、shell命令或字符串断言。

```python
@dataclass(frozen=True)
class PteEnvironmentRequirement:
    platform_build_sha256: str
    pte_contract_version: str
    srt_contract_version: str

@dataclass(frozen=True)
class PteDecisionInput:
    step_id: str
    binding: StrategyInputBinding
    decision_at: datetime
    trading_date: date
    submit_at: datetime
    repeat_decision: bool = False

@dataclass(frozen=True)
class PteOrderKey:
    decision_step_id: str
    order_ordinal: int                  # 从0开始，真实计划中的顺序

@dataclass(frozen=True)
class PteSubmissionResult:
    event_id: str
    observed_at: datetime
    order: PteOrderKey
    outcome: SubmissionOutcome        # ACCEPTED / REJECTED / UNKNOWN

@dataclass(frozen=True)
class PteOrderUpdate:
    event_id: str
    observed_at: datetime
    order: PteOrderKey
    status: InspectionOrderStatus     # OPEN / PARTIAL / FILLED / CANCELLED
    cumulative_filled_quantity: int
    average_fill_price: Decimal
    cumulative_fee: Decimal            # 渠道独立事实，不从PTE账本反推

@dataclass(frozen=True)
class PteRepeatedOrderReport:
    event_id: str
    observed_at: datetime
    source_event_id: str               # 前一个PteOrderUpdate

PteChannelEvent = PteSubmissionResult | PteOrderUpdate | PteRepeatedOrderReport

@dataclass(frozen=True)
class PteCheckpointExpectation:
    checkpoint_id: str
    after_event_id: str
    expected_orders: tuple[PlannedOrder, ...]
    position_quantity: int
    available_cash: Decimal
    frozen_cash: Decimal
    cycle_target_quantity: int | None
    health: AccountHealth
    cumulative_order_count: int

@dataclass(frozen=True)
class PteInspectionScenario:
    scenario_id: str
    initial_cash: Decimal
    decisions: tuple[PteDecisionInput, ...]
    channel_events: tuple[PteChannelEvent, ...]
    checkpoints: tuple[PteCheckpointExpectation, ...]
    restart_after: tuple[str, ...] = () # event_id；不是任意操作列表

@dataclass(frozen=True)
class PteCoverageRequirement:
    capability: PteInspectionCapability
    requirement: CoverageRequirement  # REQUIRED / NOT_APPLICABLE
    scenario_ids: tuple[str, ...]
    reason: str

@dataclass(frozen=True)
class PteInspectionProtocol:
    environment: PteEnvironmentRequirement
    scenarios: tuple[PteInspectionScenario, ...]
    coverage: tuple[PteCoverageRequirement, ...]
    failures: tuple[PteFailureCase, ...]
```

### 5.1 事件与预期的固定语义

- 场景初始化产生保留事件`LOAD`，时钟为首个decision_at，先于所有业务事件。每个决策产生`<step_id>:decision`和`<step_id>:submit`；重复决策的`<step_id>:repeat`紧接原决策、使用相同时钟。渠道事件ID与这些ID共同唯一。检查点和restart只引用完整结束的事件，不能落在同步调用中间。
- 每次实际渠道提交恰有一个`PteSubmissionResult`，其observed_at必须等于所属submit_at，在真实提交调用内返回或抛出对应结果；`<step_id>:submit`在本次所有同步结果返回后结束。之后的订单更新按独立时刻推进。相同时间的其他事件若无法由依赖确定顺序则拒绝，核验T日决策、T+1执行及数据可得时间。
- `expected_orders`只表示最近决策的完整计划；重复请求可复用同一非空计划且没有新委托。只有计划本身为空才使用空元组。`cumulative_order_count`统计该场景实际发起的渠道提交调用次数，包含REJECTED和UNKNOWN；幂等要求重复决策/回报不增加此计数，不能只统计受理订单以掩盖重复调用。方向/价格/份额通过SRT现有`PlannedOrder`强类型比较，不比较运行UUID。
- 渠道事件通过业务位置匹配实际订单；引用不存在订单、额外订单、累计成交倒退/超量或不合法状态迁移明确失败。零成交均价必须为0，正成交均价必须为正。累计费用非负且单调，以四位小数ROUND_HALF_EVEN规范化；重复回报不重复收费。
- 首版渠道替身规则固定为`RECORDED_FILLS_V1`：按初始资金、订单累计成交金额增量和累计费用增量，独立推导渠道总现金及持仓，不读取PTE实际账本作为渠道事实。BUY扣成交额与费用，SELL加成交额再扣费用；累计金额为累计数量乘累计均价，先按累计金额规范化再求增量。PTE自身费率模型及渠道费用对账照常运行，分别留证。
- 渠道快照的cash为总现金，frozen_cash是其中未成交限价买单的剩余数量乘限价，拒单/撤单释放；可用现金为两者之差。市价单须在同次提交时刻给出成交或拒绝结果，不支持跨事件悬挂市价单；不支持的场景明确拒绝。行情估值取已绑定数据在当前时刻可得的价格。替身模型版本、累计费和推导快照进入证据，不声称这是实际券商资金规则。
- 所有给定预期独立于被测结果提交，不从实际运行结果自动生成“期望值”。期望字段的`None`只表示该策略没有周期目标，不表示跳过比较。
- `restart_after`处关闭并重建数据库连接、策略适配器、账户引擎及执行组件，从持久化事实恢复；平台运行不中断对照并比较后续行为，不把清空缓存称为重启。

能力枚举固定为`LOAD_PREPARE / ENTER_HOLD_EXIT / NO_OR_PARTIAL_FILL / IDEMPOTENCE / RECOVERY / RELEVANT_FAILURE / POSITION_CHANGE`。覆盖由实际轨迹与断言结果计算，不能只看场景名称。前五项必需；相关失败路径必需；`POSITION_CHANGE`按策略合同适用，标注不适用必须提供原因且与合同一致。

`PteFailureCase`字段为`case_id: str, scenario_id: str, fault: PteFault, at_event_id: str`。`PteFault`首版仅包含`PACKAGE_CONTENT_CHANGED / INPUT_UNAVAILABLE / INPUT_AFTER_DECISION`；包故障固定在初始化前的`LOAD`事件，输入故障固定在所选决策事件前。期望固定为对应错误码且无新增订单，不开放文件路径或任意修改内容。未知提交结果由`SubmissionOutcome.UNKNOWN`覆盖。故障仅作用于独立副本，不污染主场景或受检包。

### 5.2 环境身份

`platform_build_sha256`是实际受检平台执行文件清单的内容摘要，不能只填Git HEAD或任意自报文字。入口复用现有构建清单；本地开发环境没有清单时，按同一规范采集并显示供调用方固定。实现时提供纯读函数`describe_inspection_environment(repository) -> InspectionEnvironment`，同时用于协议准备和运行前后核验。

`InspectionEnvironment`字段为`platform_build_sha256, platform_files: tuple[ImplementationFileIdentity,...], git_revision: str | None, python_version: str, dependencies: tuple[ImplementationDependency,...], pte_contract_version: str, srt_contract_version: str, effective_config_sha256: str`。`ImplementationFileIdentity(path: str, sha256: str)`使用包相对路径。运行环境与声明不匹配时B不得执行；运行期间执行文件/依赖改变则不能出具有效PASS。

### 5.3 跨模块API与内部边界

```python
# SRT：新增，供正式部署与隔离检验共用，不包含资格批准
def validate_release_package(
    strategy_root: Path,
    release_id: str,
) -> VerifiedReleasePackage: ...

# PTE：新增，供TDR调用，不是RSCH直接入口
def inspect_release(
    request: PteReleaseInspectionRequest,
    *, control: InspectionControl | None = None,
) -> PteInspectionOutcome: ...
```

`VerifiedReleasePackage`由认证函数构造，包含`release: StrategyRelease, package_sha256: str, runtime_binding: RuntimeBinding, source_root: Path`；核验实际版本记录、manifest、全部包文件和绑定，不依赖正式部署回执。现有应用层同名函数迁移为薄适配，正式部署仍核验资格/回执各自合同。

`PteReleaseInspectionRequest`字段为`run_id: str, isolated_repository: Path, workspace: Path, expected_release_id: str, expected_release_sha256: str, expected_package_sha256: str, data_spaces: tuple[DataSpaceBinding,...], input_copies: tuple[InspectionInputCopy,...], protocol: PteInspectionProtocol`。复用DFLS的`DataSpaceBinding(base_dir, space, space_id)`；`InspectionInputCopy(source: PreparedDataRef, isolated: PreparedDataRef, content_mapping: tuple[InputContentIdentity,...])`说明原准备资产到隔离准备资产的映射，`InputContentIdentity(role: str, source_sha256: str, isolated_sha256: str)`要求同角色内容完全相同。

TDR负责通过DFLS支持的读写/准备能力物化本次所需资产到私有数据空间，并提供空间绑定；不要求DFLS允许复制内部UUID目录。SRT在隔离空间重建发布绑定，核验具名请求、日历、时间覆盖及逐角色内容。PTE由显式space_id绑定定位输入，禁止按UUID猜磁盘路径。无法取得等价隔离准备资产时明确失败，不能联网补取或更换数据。

这些路径只能由TDR在受管临时根创建，PTE入口再次核对根、链接和身份。RSCH主请求不提供任意数据库路径、生产根、provider或broker回调。

`PteInspectionOutcome`字段为`run_id: str, status: PteInspectionStatus, environment: InspectionEnvironment, scenarios: tuple[PteScenarioResult,...], coverage: tuple[PteCoverageResult,...], artifacts: tuple[PteArtifact,...]`。`PteInspectionStatus`限定PASS/FAIL/NOT_RUN/INCOMPLETE，由TDR显式映射到报告状态。

`PteScenarioResult(case_id, status, code, summary, artifact_ids)`记录场景或故障用例；`PteCoverageResult(capability, requirement, covered: bool, scenario_ids, reason)`记录实际覆盖。`PteArtifact(artifact_id: str, path: str, sha256: str, schema: str, schema_version: int)`的path仅相对workspace、不可越界。缺文件或哈希不符即发布失败。这些是受管临时结果，TDR认证并转为正式`ResearchEvidenceRef`后才作为最终报告证据。PTE不依赖TDR研究目录或导入`tests`。

负向用例准确产生预期拒绝且没有违规新单时，该用例PASS；必须同时留存实际拒绝码和订单计数。真实缺陷造成的失败不能伪装成“预期错误”。

内部`InspectionRuntimePermit`绑定run ID、最终发布/包身份、场景协议摘要和隔离根。只在隔离上下文使用，普通入口拒绝原样测试许可及测试部署封套。SRT再次加载部署时必须使用同一经认证上下文，不能仅替换PTE最外层入口。

PTE当前账户绑定和建账也硬性要求正式资格，实施须同步改为显式的正式准入/技术检验准入分支。隔离数据库记录技术许可，不能填假`PAPER_READY`。建议在隔离库增加`inspection_context`及`inspection_admissions`表，正式启动入口发现该标记即拒绝；正式账户路径和资格集合保持原规则。测试账户`qualification_snapshot`不写正式资格，技术账户准入仅凭受管许可验证。核心订单、成交及账本逻辑共用。具体SQL属于PTE内部实现，不作为RSCH公共契约。

该隔离保证防止普通入口误用或原样复制测试凭据；不宣称抵御具有文件写权限者主动伪造记录，也不构建任意Python的操作系统级沙箱。

## 6. 冻结计划、受检包与结果

### 6.1 持久化计划和发布内容

新版`FreezePlan`沿用`origin, version, parent_version, change_summary, source_experiment, selection_data_cutoff, forward_start, payload, source_files, runtime_binding`，增加`schema_version=2`，删除`registration_evidence`。

`origin.registration`保存登记记录快照，但其中研究来源引用不进入递归校验。`source_files`覆盖源码及安装文件，`runtime_binding`是尚未绑定release ID/hash的规格；所有文件均与指定候选和显式additional_files核对。

```python
@dataclass(frozen=True)
class InspectedRelease:
    version_record: ResearchEvidenceRef
    manifest: ResearchEvidenceRef
    files: tuple[FreezeFile, ...]      # 相对发布包的路径→内容引用，排除manifest
    release_sha256: str
    package_sha256: str
```

`InspectedRelease`由报告引用。它保存足以重建正式包的字节；删除`.tmp/`后仍能冻结，不依赖临时目录。实际冻结包的`src/strategy_runtime/`路径布局沿用现状。

哈希顺序固定为：

```text
候选/登记身份 → FreezePlan → StrategyVersion → RuntimeBinding
             → 文件manifest → package_hash → 检验报告 → 冻结批准/事务
```

计划不包含最终manifest、package hash或报告。报告/批准/事务不放入发布包。manifest文件清单不包含manifest本身，`package_hash`是移除该字段后的规范化manifest摘要。

现有manifest的`candidate_package_hash`字段实际保存plan hash，本版维持其格式并明确这一含义；不将其冒充真正`package_hash`。当前正式StrategyVersion schema5、发布manifest schema1不因报告升级而改变。检验使用真正release hash，禁止再以plan hash代替。

### 6.2 报告

```python
class InspectionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"

@dataclass(frozen=True)
class InspectionGoalResult:
    status: InspectionStatus
    cases: tuple[InspectionCaseResult, ...]
    evidence: tuple[ResearchEvidenceRef, ...]

@dataclass(frozen=True)
class CandidateInspectionReport:
    schema_version: Literal[2]
    run_id: str
    owner: ResearchEvidenceOwner
    origin: CandidateOrigin
    selection: DecisionReference
    request: ResearchEvidenceRef
    protocol: ResearchEvidenceRef
    environment: ResearchEvidenceRef | None
    plan: FreezePlan | None
    release: InspectedRelease | None
    behavior_equivalence: InspectionGoalResult
    pte_runtime: InspectionGoalResult
    measurements: ResearchEvidenceRef
    remaining_risks: tuple[str, ...]
```

`InspectionCaseResult`字段为`case_id: str, status: InspectionStatus, reason_code: InspectionReason, summary: str, evidence: tuple[ResearchEvidenceRef,...]`。`InspectionReason`包含`OK / CONTENT_MISMATCH / INPUT_MISMATCH / UNSUPPORTED_CONTRACT / BEHAVIOR_DIFFERENCE / BASELINE_DIFFERENCE / PTE_FAILURE / COVERAGE_MISSING / ENVIRONMENT_MISMATCH / CANCELLED / RESOURCE_LIMIT / EXECUTION_ERROR`。完整差异在证据中，不把全部账本塞入API返回。

报告保留既有派生属性`sha256`、`reference`和`status`：`reference`为当前owner下的`inspection/<报告sha256>`。整体状态为派生属性：任一目标FAIL则FAIL；两项均PASS且计划、受检包、环境及必需覆盖齐全才PASS；其他情况INCOMPLETE。环境采集未完成时引用为None，并说明原因，不能声明PASS。可选基准未提供在其证据中记`NOT_REQUESTED`，不伪造PASS、不增加第三个目标。不适用覆盖项与检查状态分开，不可令必需场景消失。

### 6.3 错误及控制

`InspectionControl`与`InspectionProgress`定义在SRT的独立控制模块，由TDR和PTE复用，不依赖SM或TDR。`InspectionControl`是运行控制对象，含`timeout_seconds: float | None, max_workers: int=1, cancelled: Callable[[], bool] | None, on_progress: Callable[[InspectionProgress], None] | None`；只允许取消/接收进度，不可改写策略、输入或结果。控制对象本身不序列化，有效预算写入运行记录。回调异常明确终止为EXECUTION_ERROR，不静默忽略；超时是主请求总预算，进入PTE时传剩余预算。

`InspectionProgress`字段为`run_id: str, stage: InspectionStage, completed: int, total: int | None, elapsed_seconds: float, message: str`。阶段枚举为PREPARE/EQUIVALENCE/PTE/PERSIST/FINALIZE，未知总量使用None。长步骤至少每30秒报告，不伪造进度。取消和预算耗尽停止受管子进程、保留诊断，不自动重试或续跑。

错误分为三类：

1. 非法类型、重复坐标、无效选择、路径越界等请求错误：执行前抛明确`InspectionInputError(code, field, message)`，无策略运行；已认证的技术材料损坏按检查失败处理。
2. 内容损坏、差异、运行异常、取消、预算耗尽：保留已完成结果，返回持久化的FAIL/INCOMPLETE报告。尚未准备成功的计划/包为None，后续目标NOT_RUN。
3. 证据存储失败：抛`InspectionPublicationError(phase, partial_evidence, report_reference, message)`；引用只在确实落盘并认证后返回，不声称正式报告已发布。进程被强制杀死时可能只有临时日志，不能保证最终报告存在。

入口同步执行，每次调用生成独立run ID；不新增后台作业、查询/恢复API或跨调用自动复用。再次调用是新检验，正式结果不可覆盖。冻结仍沿用其独立幂等请求ID。

## 7. 阶段交付与正式冻结API

```python
@dataclass(frozen=True)
class CandidateInspectionDelivery:
    inspection: ResearchEvidenceRef
    decisions: tuple[DecisionReference, ...]
    freeze: FreezeReceipt | None
    pending_decisions: tuple[str, ...]

def assemble_delivery(
    repository: RepositoryContext,
    definition: DeliveryDefinition,
    content: DeliveryContent,
) -> DeliveryReceipt: ...

def validate_delivery(
    repository: RepositoryContext,
    reference: DeliveryReference,
    *, scope: DeliveryValidationScope = DeliveryValidationScope.FULL,
) -> DeliveryValidation: ...

def freeze_candidate(
    repository: RepositoryContext,
    request: FreezeCandidateRequest,
) -> FreezeReceipt: ...

def get_freeze_result(
    repository: RepositoryContext,
    request_id: FreezeRequestId,
) -> FreezeReceipt: ...
```

新版交付移除`source_assessment`，且只存正式报告引用，不同时嵌入另一份可分歧的报告对象。INSPECTION的`predecessors=()`；修订历史可以在报告中列出定位链接，不能成为递归技术依赖。

**格式决定：**新版INSPECTION交付使用schema9；阶段一至四继续使用现有schema8。`delivery.json.schema_version`、`definition.schema_version`及`receipt.schema_version`三处必须按stage一致，交叉组合拒绝；`DeliveryReference`保持现有结构。INSPECTION新写入口不接受schema8。既有schema8 INSPECTION原件保留，不自动升级或作为新检验资格；显式完整校验旧检验协议返回`UNSUPPORTED_LEGACY_INSPECTION`，不增加旧执行分支。

概览遇到已识别的旧INSPECTION/schema8时，仅展示可定位的历史元数据并记录同名limitation，不解码旧payload为新版结果，继续处理schema9。依赖旧内容的汇总项报告unknown及范围，不能填0或新版PASS；不得因保留INSPECTION/1而使整个概览再次失败。未知格式或文件损坏仍明确报告。这是受限的历史元数据识别，不是旧格式完整机器复验。

`assemble_delivery`与INSPECTION的`validate_delivery`只校验新报告、用户决定及显式技术支持对象。FULL可复核本次已保存的比较/覆盖事实，不能触发前序研究评价或自动运行PTE。校验器按对象角色枚举实际依赖，禁止泛化遍历登记记录中的所有来源引用。不要用“全部历史完整”描述该结果。

`FreezeSubject`和`FreezeCandidateRequest`保留现有精确报告、plan hash、版本和批准引用字段；报告已绑定最终包身份，无需再添加一套相互重复的批准哈希。冻结核验两个目标PASS、真实批准、登记内容及完整受检字节，再提交现有事务，不读取研究前序。

同冻结请求ID同内容返回实际已有状态；同ID不同内容拒绝。只有`FreezeStatus.COMMITTED`带正式版本引用；其余状态按既有`get_freeze_result`查询，不用重跑检验来猜测冻结结果。

## 8. 存储布局、所有权和发布边界

全部路径相对仓库根。`<S>`如S015，`<C>`如C0031，`<EX>`为正式实验ID。哈希文件名和受管临时目录均由平台分配，不由调用方指定。

| 内容 | 路径 | 写入方/性质 |
| --- | --- | --- |
| 候选登记 | `research/registrations/<S>/candidates/<C>.json` | 既有SM登记；阶段五只读 |
| 候选payload | `research/<S>/assets/candidates/<C>/payload/<sha>.json` | 既有候选快照，只读 |
| 候选源码 | `research/<S>/assets/candidates/<C>/source/<source_sha>/strategy_runtime/<file>` | 既有候选快照，只读 |
| 输入数据 | `research/<S>/assets/data/` | 既有DFLS准备资产；阶段五按准备引用读，不猜内部路径 |
| 原回测（可选） | `research/<S>/assets/evidence/<source_EX>/<sha>.json` | 既有EvidenceRef，只读指定对象 |
| 用户决定 | `research/<S>/decisions/<decision_id>.json` | `record_research_decision`，不可变 |
| 确认原文等决定对象 | `research/<S>/decisions/objects/<sha>` | 内容寻址，不可变 |
| 检验全部正式对象 | `research/<S>/assets/evidence/<EX>/inspection/<sha>` | 检验API及现有发布存储，内容寻址、不可变 |
| 完整检验交付 | `research/<S>/assets/deliveries/INSPECTION/<revision>/` | `assemble_delivery`原子发布，不可变 |
| 可读交付入口 | `research/<S>/deliveries/INSPECTION/<revision>/{report.md,receipt.json}` | 现有公共副本，不可变 |
| RSCH实验材料 | `research/<S>/experiments/<EX>/{src,protocols,others}/`及根`report.md` | 调用脚本、协议草稿及说明；不替代正式证据 |
| 冻结请求/事务 | `research/<S>/freeze_requests/<request_id>/` | TDR/SM；沿用`research_request.json,request.json,committed.json,failed.json` |
| 正式版本 | `strategies/<S>/versions/<version>.json` | 仅获批冻结提交；原子可见边界 |
| 正式发布包 | `strategies/<S>/releases/<version>/` | 仅获批冻结提交 |
| 正式SRT部署回执 | `strategies/deployments/<S>-<version>.json` | 后续独立部署操作，本次检验不写 |

检验证据目录中的对象包括：规范化请求、协议、环境清单、输入描述、登记快照、payload、源码/安装字节、版本记录、绑定、manifest、比较与PTE轨迹、覆盖、计时和最终报告。计划以内嵌强类型对象保存在最终报告中，其安装字节使用显式引用。独立对象均为单个`<sha>`文件，名称语义由引用和schema说明，不另造可变“最终结果目录”。

规范化请求不含ResearchContext/Python实例、绝对路径、DataFrame或pickle。`BacktestExecutionData`被转换为DFLS准备引用、具名请求/角色、内容身份、日历、pricing及市场规则；受检帧必须重读认证资产或与其逐项一致。报告引用的技术材料完整保留；DFLS资产依照引用保留，不强行复制整批数据进入交付包。

每次输入快照记录`data_kind=HISTORICAL | SYNTHETIC`和精确资产身份。实施明确由`CandidateInspectionRequest.data_kind: InspectionDataKind`提供强类型声明（同一请求输入须使用同一数据类别），保存`CALLER_DECLARATION`来源标记及DFLS实际供应商元数据，不由平台猜测来源；PTE离线渠道始终标为SYNTHETIC。禁止把合成轨迹混入真实收益证据。请求hash覆盖规范化内容及协议/目标，排除临时路径、run ID、进度、耗时及输出报告；环境实际身份单独绑定在报告内。

临时布局如下，不使用系统临时目录：

```text
.tmp/strategy-inspection/<run_id>/
  candidate/<index>/                      # 候选与冻结版本的等价回放工作区
  repository/
    strategies/<S>/family.json            # 所需元数据；无正式批准事件
    strategies/<S>/versions/<version>.json
    strategies/<S>/releases/<version>/
      src/strategy_runtime/<file>
      runtime_binding.json
      release_manifest.json
  inputs/<index>/data/                    # 按公开DFLS API生成的私有准备空间
  scenarios/<case_id>/<restart|continuous>/
    runtime.db                            # 隔离PTE账户事实及技术准入标记
    trace.jsonl                           # 实际事件与检查点
    result.json                           # 场景结果
  scenarios/<case_id>/<restart|continuous>-worker.log # 子进程诊断
  scenarios/<fault_case_id>/restart-repository/ # 包损坏场景的私有发布副本
  pte-request.json                         # 显式输入及协议
  pte-summary.json                         # 结果与覆盖清单
  progress.jsonl
```

技术许可通过强类型`InspectionRuntimePermit`显式传递，技术部署封套由共享包认证结果生成；隔离数据库保存`INSPECTION`身份与准入记录。普通部署和账户入口不接受该技术资格。所有故障写入作用于私有副本，禁止通过硬链接修改正式输入。恢复从隔离数据库重新读取，不能从上次内存对象复原。测试运行根与账户ID不进入最终发布包hash。

成功、失败和取消均按“停止工作组件并确认静止 → 收集/认证已有结果 → 发布可获得证据 → 清理临时目录”的顺序收尾。必要时终止受管子进程；不能对仍在变化的数据库或轨迹形成成功快照。无法确认静止则INCOMPLETE并保留诊断。发布失败可保留临时诊断并返回路径。清理只作用于本次已确认的受管根，删除临时根不影响已正式发布的报告或之后的冻结。

交付包仍包含`delivery.json,receipt.json,report.md`和本次选定证据快照。两种引用使用既有`evidence/`与`support/<sha>`布局；不复制整个实验目录，不沿背景引用复制历史档案。概览显式识别`inspection/`，不将其对象计为研究绩效账户，不静默吞掉未知或损坏布局。

## 9. 最短调用顺序

1. RSCH创建实验，准备候选及DFLS输入；真实用户选型写成新版`ResearchDecision`。读取旧选型原文可用于新的准确记录，不制造新的批准，不要求用户重复选择同一内容。
2. `describe_inspection_environment(repository)`取得实际环境身份，固定场景及预期；`inspect_candidate(repository, request)`执行两项目标并返回正式报告引用。
3. `assemble_delivery(..., stage=INSPECTION, schema_version=9, predecessors=())`发布待批准报告；检验失败也可发布明确失败/受阻交付。
4. 用户批准精确对象后，`record_research_decision`保存`FreezeSubject`；`freeze_candidate`提交同一受检包，必要时`get_freeze_result`确认实际结果。
5. 冻结结果通过新的INSPECTION修订发布。正式资格、部署、PTE账户和启用仍是独立操作。

上述步骤只要求当前候选登记元数据、可执行材料、选择原文、本次输入和输出存在。实现验收必须把阶段一至四档案从可读环境中移除，再完成检验、发布和测试冻结事务；任何隐藏读取均算不满足需求。

## 10. 实施影响与评审结论

改动集中于TDR候选加载、选择/检验/冻结编排、交付格式与证据枚举，SM的阶段五记录类型，SRT共享包认证，以及PTE隔离场景运行和准入边界。TDR新增调用PTE检验模块，PTE不反向依赖TDR；不扩展策略计算或成交语义。

既有S015的选择、INSPECTION/1和所有证据原件保留；新检验使用新实验、新协议和新交付修订。对旧格式需要的迁移或完整读取兼容不默认加入本次范围。正式StrategyVersion、发布包及历史账户不因为检验协议升级而重写。

实施验收覆盖契约非法输入、哈希和身份不一致、可选基准有/无、两目标状态组合、无历史档案运行、报告发布、冻结幂等、PTE隔离及恢复；性能测量覆盖输入校验到交付发布的完整链路。仓库级全量回归仍按用户安排。

本版已完成实现与聚焦验证，开发分支为`codex/stage5-technical-validation`。下一步由RSCH按本契约开展新检验；S015新检验、精确冻结批准和正式PTE部署沿各自授权边界执行。
