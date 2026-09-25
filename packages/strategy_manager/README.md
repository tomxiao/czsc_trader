# 策略管理器（Strategy Manager，SM）

本文面向策略研究员（RSCH）和首席投资官（CIO）；平台实现与验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

SM 是策略身份、生命周期和治理证据的领域包。它把策略族、研究候选、评审结论、冻结版本和
运行证据保存为可审计的不可变事实，并校验状态转换是否合法。

## 职责与边界

SM 负责：

- 管理长期稳定的 `StrategyFamily` 身份；
- 追加保存 `StrategyGovernanceCredential`（SGC）及其治理封印；
- 保存 `CandidateSnapshot`、`EvaluationMandate`、`AdjudicationReport` 和
  `FreezeApproval`，形成候选冻结的完整证据链；
- 发布不可变的 `StrategyVersion`，记录生命周期事件和阶段性绩效证据；
- 通过原子写入、仓库写锁和并发变更检测保护治理状态。

SM 不获取行情、不运行或评价策略、不计算绩效，也不部署 PTE。TDR 负责组织研究与冻结评审，
SE 负责确定性数值评估，SRT 负责执行候选或冻结策略；SM 只接收这些模块已经形成的结构化事实。

## 治理链路

冻结版本必须依次具备以下事实：

1. 研究批次形成候选快照；
2. 评审锁定评价任务并形成裁决报告；
3. 人工批准后发布冻结版本。

`release_hash` 标识可执行发布内容，`governance_hash` 标识完整治理证据。二者用途不同，均需保持
不可变。后续模拟盘或实盘证据以 `PerformanceEvidence` 追加，不能覆盖既有版本和历史裁决。

RSCH可只读核对既有策略身份和冻结版本，候选仍提交到`research/`；CIO使用TDR的
`candidate review/evaluate/freeze`及`strategy deploy/list/info`完成治理动作。两种角色都
不直接调用`StrategyRegistry`修改`strategies/`。`PAPER_READY`只代表模拟盘资格，创建或操作
PTE账户另需授权。

## 存储

`StrategyRegistry` 默认把事实写入仓库根目录的 `strategies/`。每个策略族使用独立的
`strategies/SXX/`目录：

- `family.json`：策略族定义；
- `credentials/<credential_id>.jsonl`：追加式 SGC 记录；
- `candidates/<candidate_id>/package/`：`candidate review`受理后封存的原始候选提交包；
- `versions/vN.json`：冻结版本；
- `releases/vN/`：冻结版本对应的不可变策略运行时、binding和发布清单；
- `freeze_approvals.jsonl`：冻结批准记录；
- `lifecycle.jsonl`：生命周期事件；
- `evidence.jsonl`及`evidence/`：阶段性绩效记录和自包含证据制品。

根目录`strategies/deployments/`保存`strategy deploy`生成的SRT部署凭据。以上内容共同组成独立
策略治理区；人工编辑会破坏哈希或状态链，只能由候选治理和SRT部署平台入口修改。SRT通过部署
凭据从治理区加载冻结发布包，策略源码不会安装到`packages/strategy_runtime/`。

## 查询与核对

```powershell
.\.venv\Scripts\czsc-trader.exe strategy list
.\.venv\Scripts\czsc-trader.exe strategy info S007-v1
```

`strategy`命令仅查询或操作已部署到SRT的冻结版本；研究候选和未部署冻结版本应通过对应
研究交接、候选证据和CIO治理记录核对。上述查询不能推断PTE账户或生产运行状态。
