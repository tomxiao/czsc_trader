# 策略管理器（SM）

SM提供研究登记、冻结发布及生命周期所需的强类型契约和存储能力；研究证据与运行发布分别保存。
研究员从[公共导出](src/strategy_manager/__init__.py)导入契约，经[TDR业务API](../../src/czsc_trader/README.md)
执行登记、决定留痕和冻结；SM存储API供平台实现使用。

## 公共契约与API

| 工作 | 强类型契约 | 平台存储API |
| --- | --- | --- |
| 候选身份与来源 | `CandidateKey`、`CandidateRegistrationOrigin`、`CandidateRegistration`、`CandidateDerivation` | `StrategyRegistry.register_candidate/get_candidate` |
| 用户决定 | `ResearchDecision`、`DecisionReference`、`DecisionAction`及三类subject | TDR `record_research_decision`核验并写入声明的证据空间 |
| 技术检验记录 | `InspectionProtocol`、`InspectionCheckResult`、`CandidateInspectionReport`、`FreezePlan` | TDR `inspect_candidate`执行计算并保存到声明的归属空间 |
| 冻结提交 | `FreezeCandidateRequest`、`FreezeVersionRequest`、`FreezeReceipt` | `StrategyRegistry.freeze_version/get_freeze_result` |
| 策略身份查询 | `StrategyFamily`、`StrategyVersion` | `StrategyRegistry.list_families/get_family/get_version/versions` |
| 生命周期与运行资格 | `PaperTradingApproval`、版本及绩效证据 | `validate_all/evidence/lifecycle_events/current_qualification/approve_paper_trading` |

`CandidateEvidence(path, sha256)`中的路径相对相应API声明的证据根目录，拒绝绝对路径、越界和
内容哈希不符。调用方选择登记根目录；同键同记录幂等，不同内容拒绝覆盖。
`CandidateKey`由策略ID和`C`加四位数字的候选编号组成，例如`S900`与`C0001`。
派生类型明确区分`PARAMETERS`、`IMPLEMENTATION`和`EXECUTION`，绑定双方内容及变更证据。
仅登记需要正式交接、技术检验或冻结的候选。搜索trial和邻域对象可直接通过TDR受管评价，
其`EvaluationLineage`归入实验评价证据；不因补充派生关系重复登记同内容候选。
来源实验ID接受`EXxxx_YYYYMMDD`及保留原位的已封存目录名，逻辑身份与实际目录分别声明。

`CandidateRegistration`读写只接受schema 2，内容身份使用`identity_schema_version=2`，其载荷、源码、预检及派生证据路径相对来源实验根目录
由调用方指定。候选内容身份不因保存位置改变。
平台存储调用必须显式提供实际证据根目录：

```python
registry.register_candidate(record, evidence_root=source_experiment_root)
record = registry.get_candidate(key, evidence_root=source_experiment_root)
```

SM只从显式证据根目录读取实体并校验哈希；序列化记录须显式提供两个版本字段，
旧schema 1登记明确拒绝。研究员通过TDR
`register_candidate/load_candidate`使用上述能力；TDR负责将实体保存到来源实验的`objects/`，
拒绝在已封存实验中补写对象。登记记录和来源实验实体须一起保留，才能继续加载、检验及冻结。

`ResearchDecision`将`APPROVE/REJECT/DEFER`与以下对象之一绑定：

- `StageAdvanceSubject`：已有交付回执和拟推进阶段。
- `CandidateSelectionSubject`：阶段四交付、候选键及内容哈希。
- `FreezeSubject`：候选内容、检验报告、冻结计划哈希和明确版本。

决定必须留存`confirmation_source`和原因；同一决定ID内容冲突拒绝写入。宿主负责核验真实用户
授权，TDR验证决定及引用并保存到声明的归属证据根目录内的`decisions/`。
确认材料、阶段推进及选型交付引用、检验证据使用`ResearchEvidenceRef(owner, path, sha256)`；
逻辑归属通过`ResearchEvidenceLocation(owner, path)`绑定到实际证据根目录，解析须显式提供该绑定：
`ref.resolve(repository_root, location=declared_location)`。SM不按归属拼装研究目录。
决定留痕不自动驱动研究阶段或参数搜索。

## 原子冻结与查询状态

TDR先检验候选、复算及发布文件，生成`FreezePlan`和检验报告；用户随后批准该确切计划。
`FreezePlan.origin`使用`CandidateOrigin`绑定登记键、内容指纹、登记记录及其哈希；TDR验证
检验闭包、实际选型和精确冻结批准，并在发布前再次核验候选及依赖。
平台存储请求`FreezeVersionRequest(request_id, request_sha256, version, family, staged_package,
package_sha256, journal_root)`携带已准备的schema 5版本、族、发布包和独立事务日志目录。
SM在写锁内核验发布身份及文件闭包；研究批准的认证由TDR业务入口负责。

事务日志位于调用方指定的日志根目录内的`<请求ID>/`，与运行注册表分离。平台先完成发布包，
写入日志中的`committed.json`，再原子写入版本文件。版本文件是运行侧可见性边界；
冻结查询继续核验日志、版本及发布包，只有一致时返回`COMMITTED`。
`get_version/versions`读取版本及其内容哈希，运行加载和部署另核验发布包及部署身份，均不读取研究日志。

`StrategyVersion`只接受schema 5，保存来源实验、来源候选编号、选择截止日、前瞻起始日、固定
策略载荷和发布元数据。研究决定及技术检验证据独立保存。`release_hash`覆盖完整版本
内容并排除哈希自身，追加研究决定不改变发布身份。旧schema 1/2/3/4在读取边界拒绝。
SM底层`get_freeze_result(request_id, *, journal_root)`必须显式提供日志根目录；研究员使用TDR查询入口。

| `FreezeStatus` | 含义及调用方处理 |
| --- | --- |
| `NOT_FOUND` | 指定`FreezeRequestId`尚无持久请求 |
| `IN_PROGRESS` | 当前进程中该请求正在执行；继续查询同一ID |
| `COMMITTED` | 提交证据完整，返回`FrozenVersionReference`中的版本、release及package哈希 |
| `FAILED` | 已留存明确失败原因，未完成冻结 |
| `UNKNOWN` | 中断或持久证据损坏，无法确认结果；保留现场并核查 |

同请求同内容返回既有状态；同请求不同内容、已占用版本或未决请求占用的版本明确拒绝。
版本号和父版本由调用方显式指定；不自动改号、重试、恢复或回滚。仅`COMMITTED`回执可携带
版本引用。冻结初始资格为`RESEARCH`；晋级、部署、PTE账户操作需要各自的证据及授权。

## 不可变存储与权限

| 路径（相对仓库） | 内容 |
| --- | --- |
| `research/registrations/<策略ID>/candidates/` | 候选登记记录 |
| `experiments/<策略ID>/<来源实验ID>/objects/` | 新候选载荷、源码及来源材料；schema 2登记引用这些实体 |
| `experiments/<策略ID>/<检验实验ID>/objects/inspection/` | 检验、计划引用的内容寻址证据 |
| `research/<策略ID>/decisions/`及其`objects/` | 用户决定及确认材料 |
| `research/<策略ID>/freeze_requests/<请求ID>/` | 冻结请求及提交／失败事实 |
| `strategies/<策略ID>/versions/`、`releases/` | 不可变版本和发布文件闭包 |
| `strategies/deployments/` | 单独授权产生的SRT部署凭据 |

历史`credentials/`、`freeze_approvals.jsonl`、`lifecycle.jsonl`及`evidence.jsonl`保留原件和哈希。
旧候选包、CIO类型及历史解码分支已删除。原件供人工查阅，平台不承诺历史机器复验。
当前研究立项仍使用`StrategyGovernanceSeal/StrategyGovernanceCredential`，登记位于
`research/registrations/`；运行注册表在首次冻结发布时登记策略族。研究认证不进入运行发布合同。
新冻结版本初始为`RESEARCH`；获准后平台可用`approve_paper_trading(PaperTradingApproval)`
绑定准确发布哈希授予`PAPER_READY`，部署和PTE账户创建仍需各自授权。
`StrategyRegistry.record_evidence`校验`PerformanceEvidence`及其绑定的发布身份。首次登记PTE
导出证据时，显式提供`source_file`才能校验并保存来源文件；校验对象是文件中`source`的规范
内容哈希，传入参数省略时不核验来源文件。
`calmar_ratio`和`sharpe_ratio`允许`None`，表示指标未定义；数值、空值均按原事实保存。
PTE导出的观察数和年化状态位于`source.statistics`，随整个`source`参与哈希。
SM不计算绩效、不执行回测、不操作PTE账户；技术检验通过不代表平台认证研究结论。
角色分工与工程决策见[RSCH契约](../../research/RSCH_AGENT.md)和[DEV Agent](../../docs/DEV_AGENT.md)。
