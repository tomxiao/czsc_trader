# 策略管理器（SM）

SM管理策略族、候选登记、用户决定、不可变冻结版本、生命周期和绩效证据。
研究员从[公共导出](src/strategy_manager/__init__.py)导入契约，经[TDR业务API](../../src/czsc_trader/README.md)
执行登记、决定留痕和冻结；SM存储API供平台实现使用。

## 公共契约与API

| 工作 | 强类型契约 | 平台存储API |
| --- | --- | --- |
| 候选身份与来源 | `CandidateKey`、`CandidateRegistrationOrigin`、`CandidateRegistration`、`CandidateDerivation` | `StrategyRegistry.register_candidate/get_candidate` |
| 用户决定 | `ResearchDecision`、`DecisionReference`、`DecisionAction`及三类subject | `StrategyRegistry.record_research_decision` |
| 技术检验记录 | `InspectionProtocol`、`InspectionCheckResult`、`CandidateInspectionReport`、`FreezePlan` | TDR `inspect_candidate`执行计算，SM保存和验证引用 |
| 冻结提交 | `FreezeCandidateRequest`、`FreezeVersionRequest`、`FreezeGovernance`、`FreezeReceipt` | `StrategyRegistry.freeze_version/get_freeze_result` |
| 策略身份查询 | `StrategyFamily`、`StrategyVersion` | `StrategyRegistry.list_families/get_family/get_version/versions` |
| 治理与生命周期 | 版本、绩效证据及生命周期契约 | `validate_version_governance/validate_all`、`evidence/lifecycle_events/current_qualification` |

`CandidateEvidence(path, sha256)`中的路径相对相应API声明的证据根目录，拒绝绝对路径、越界和
内容哈希不符。候选登记存于`research/registrations/`；同键同记录幂等，不同内容拒绝覆盖。
派生类型明确区分`PARAMETERS`、`IMPLEMENTATION`和`EXECUTION`，绑定双方内容及变更证据。

`ResearchDecision`将`APPROVE/REJECT/DEFER`与以下对象之一绑定：

- `StageAdvanceSubject`：已有交付回执和拟推进阶段。
- `CandidateSelectionSubject`：阶段四交付、候选键及内容哈希。
- `FreezeSubject`：候选内容、检验报告、冻结计划哈希和明确版本。

决定必须留存`confirmation_source`和原因；同一决定ID内容冲突拒绝写入。宿主负责核验真实用户
授权，SM验证记录与引用的一致性。决定留痕不自动驱动研究阶段或参数搜索。

## 原子冻结与查询状态

TDR先检验候选、复算及发布文件，生成`FreezePlan`和检验报告；用户随后批准该确切计划。
`CandidateOrigin`保存登记记录的文件引用，连同预检、派生材料组成可读取的证据闭包。
`FreezeVersionRequest`携带业务请求、暂存发布包和候选登记根目录；SM在已有写锁内再次核验。

发布包和schema 4版本文件准备完成后，最后原子写入`committed.json`作为提交可见性标记。
`get_version`、`versions`、部署和治理读取共同核验提交身份，未提交版本不可作为可用版本读取。
新版本`release_hash`覆盖来源、检验和用户决定等完整版本内容；历史schema 1/2/3按原规则读取。

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
| `research/registrations/objects/` | 候选载荷、源码及来源材料 |
| `strategies/research_objects/` | 检验、计划引用的内容寻址证据 |
| `strategies/research_decisions/<策略ID>/` | 用户决定及确认材料引用 |
| `strategies/freeze_requests/<策略ID>/<请求ID>/` | 冻结请求及提交／失败事实 |
| `strategies/<策略ID>/versions/`、`releases/` | 不可变版本和发布文件闭包 |
| `strategies/deployments/` | 单独授权产生的SRT部署凭据 |

历史`credentials/`、`freeze_approvals.jsonl`、`lifecycle.jsonl`及`evidence.jsonl`保留原件和哈希。
旧候选包、CIO审查类型仅在内部历史解码中使用，当前写入使用上述强类型契约。
SM不计算绩效、不执行回测、不操作PTE账户；技术检验通过不代表平台认证研究结论。
操作遵守[RSCH契约](../../research/RSCH_AGENT.md)和[开发安全边界](../../docs/DEVELOPMENT_HANDOFF.md)。
