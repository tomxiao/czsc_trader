# 研究事实、账户诊断与实验报告

本文说明DEV提供给RSCH的确定性工具。研究问题、标签、人群、报告原文、结果声明和下一步建议由RSCH负责；平台只关联、计算及核验显式事实，不解析报告文字推导研究结论或授权。

## 入口与存储边界

业务函数从`czsc_trader.application`导入，请求及结果从`czsc_trader.research_tools`导入。

| 入口 | 输入 | 输出 | 写入 |
| --- | --- | --- | --- |
| `get_research_overview(repository, batch)` | `RepositoryContext`、`ResearchBatchRef` | `ResearchOverview` | 无 |
| `diagnose_accounts(repository, request)` | `AccountDiagnosisRequest` | `AccountDiagnosisResult` | 无 |
| `validate_experiment(repository, request)` | `ExperimentValidationRequest` | `ExperimentValidation` | 无 |
| `create_experiment(context, request)` | `ResearchContext`、`ExperimentRequest` | `ExperimentRef` | 分配新实验 |
| `publish_evidence(context, request)` | 包括`ExperimentReportWrite`的强类型证据请求 | `EvidenceRef` | 证据快照；报告请求另提交当前引用 |
| `validate_delivery(repository, reference, scope=...)` | `DeliveryReference`及范围 | `DeliveryValidation` | 无 |

只读入口不创建数据准备环境，不访问供应商、PTE生产库或其他研究批次，不重新执行策略。正式账户和五张账本保存在`research/<批次>/assets/evidence/<实验>/<哈希>.json`；研究运行资料位于`assets/runs/`，不是默认诊断输入。

## 研究概览

```python
from czsc_trader.application import get_research_overview
from czsc_trader.research_tools import ResearchBatchRef

overview = get_research_overview(repository, ResearchBatchRef("S900"))
```

返回登记状态、各阶段最高已支持修订、实验报告状态、组件测试声明、候选、交接集合、搜索声明、计数、限制及来源快照。来源包含文件/目录位置、存在状态和哈希；调用结束前复核读取清单，检测并发变化即报错，不自动重试。

同一路径的重复哈希引用在单次调用内复用认证记录，期望哈希不同仍拒绝；结束前逐路径重新读取并核验。快照只保留哈希和大小，不缓存完整的大证据正文，也不跨调用缓存文件认证结果。

计数的`basis`为`VERIFIED`（已认证登记事实）、`DECLARED`（已保存的声明）或`UNKNOWN`（`value=None`及原因）。重复交付中的相同搜索声明只展示一次；多个可能重叠的搜索声明不相加。账户评价数只覆盖保留的评价身份声明，不等于账户账本已认证，也不是完整尝试次数。没有受管的经济路径分组声明时，该计数保持未知，不在概览中重算。

概览认证保留记录及关联文件哈希，不重算SE、验证运行资格或判断研究是否充分。最高交付修订不等于阶段获批；登记状态不代替当前用户指令。旧格式明确列为不支持，不按新格式解读。缺失或损坏的必要引用报错，不补零或静默改用旧版本。

报告状态为`MISSING`、`DRAFT`、`PUBLISHED`、`UNPUBLISHED_CHANGES`。历史实验缺少根报告如实显示，不自动搬迁或补写。

## 账户损益与路径诊断

```python
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import (
    AccountDiagnosisRequest, AccountRunRef, EvaluationWindow,
)
from datetime import date

result = diagnose_accounts(repository, AccountDiagnosisRequest(
    baseline=AccountRunRef(account_evidence, evaluation_identity),
    alternative=None,
    window=EvaluationWindow("review", date(2026, 6, 1), date(2026, 10, 15)),
))
```

`account_evidence`须是`account_evaluation` schema 7正式证据，`evaluation_identity`精确选中一个评价；平台核验原始哈希、账户及账本认证，不凭候选编号找最近一次结果。`alternative`可传同批次另一账户；标的、市场执行数据、费用、单位、初始资金及会话等上下文不同则不可比。候选实现可以不同。

窗口是原连续账户的切片，继承此前资金和持仓，不重置本金。首版支持单标的、只做多、全仓/现金、单周期一次买入和至多一次卖出的账本；加减仓、多次成交、日内往返等不支持，不降级为简化收益计算。

在原账户一致的价格及数量单位下，每日互斥分解为：

| 分项 | 金额 |
| --- | --- |
| 入场日 | 买入数量 ×（当日估值价 − 买价） |
| 其他持有日 | 持仓数量 ×（当日估值价 − 前一估值价） |
| 退出日 | 卖出数量 ×（卖价 − 前一估值价） |
| 费用 | 当日实际成交费用的负值 |

分项合计核对实际权益变化，费用不重复扣除。返回逐日、逐年明细及完整切片残差；年度贡献使用本账户该诊断年度期初权益，单位为比例。部分年度标识是诊断窗口边界说明，不改变原研究年度目标。跨年周期不把全部利润记入入场年。SE协议固定为`single-long-full-position-v1`，精度固定，调用方不能放宽容差。

返回状态为`COMPUTED`、`INCOMPARABLE`、`UNSUPPORTED`、`INVALID_EVIDENCE`，失败保留原因。结果包含原证据、评价身份、决策/订单/成交/周期标识。两账户返回共同或仅一方入场周期及逐日资金路径差异，不把差额解释为独立因果贡献，也不据此计算取消交易的反事实。

可选`DecisionPopulationRef(evidence, population_id)`引用研究员显式提供的人群。材料JSON必须是以下精确结构：

```json
{"schema_version":1,"population_id":"entry-population","evaluation_id":"<64位评价身份哈希>","memberships":[{"decision_id":"<原决策身份>","member":true}]}
```

`member`仅允许`true`、`false`、`null`；未列决策保持未知，未知/重复决策和跨账户身份拒绝。平台按真实订单、成交与持仓记录计算覆盖，不寻找分类条件，不认证研究员的金融解释或真实历史可得性。

`coverage_summary`按评价、人群及买入意图/成交/持有决策类别汇总总数、组内、组外及未知数。比例分母为该类别总数；分母为零或存在未知成员时`member_fraction=None`，不把未知改为组外。

结果的`to_dict()`可交给现有材料证据发布入口保存；诊断调用本身不写证据、不新增账户。

## 每实验根报告及独立发布

新实验创建根`report.md`，初始`IN_PROGRESS`内容只表示已建立入口。源码、方案及其他材料分别内聚于`src/`、`protocols/`、`others/`；根`notes.md`保留工作笔记。批次`materials/`只放批次级材料，共享材料指定归属并引用。

```python
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import ExperimentOutcome, ExperimentReportWrite

report_bytes = (experiment.resolve(repository.root) / "report.md").read_bytes()
report_ref = publish_evidence(research, ExperimentReportWrite(
    experiment=experiment,
    expected_report_sha256=sha256(report_bytes).hexdigest(),
    outcome=ExperimentOutcome.FAILED,
    evidence=(source_evidence,),
    previous=None,
))
```

`outcome`由RSCH声明：`COMPLETED/FAILED/CANCELLED/INCOMPLETE`。没有阶段交付也能发布，阶段报告与实验报告不要求相同。

报告快照为`experiment_report` schema 1，保存UTF-8原文、字节哈希、声明结果、来源及前版；使用原始字节，不转换换行。快照先按内容寻址保存，再在实验级锁下原子提交根`report_ref.json`。前版冲突或正文哈希变化拒绝，同一请求可幂等确认。发布不会改写根报告。

引用提交前失败可能留下不可变但未被当前引用指向的快照，不删除或冒称提交完成。`ReportPublicationError`及批量`PublicationError`提供`phase/reference/pointer_committed`；发生异常且指针已提交或提交结果不确定时批量状态为`UNKNOWN`，明确未提交为`FAILED`，取消按实际状态表达。正常提交仍返回`PUBLISHED`。不自动重试。`publish_evidence_many`逐项报告，参数预检失败仍在任何写入前拒绝整批。

根报告以后可继续编辑；已发布快照仍不变，正文不同于当前快照即为未发布修改，修订时传入准确的`previous`。原始阶段交付、候选及旧实验报告不迁移、不重签。

## 实验结构检查

```python
from czsc_trader.application import validate_experiment
from czsc_trader.research_tools import ExperimentValidationRequest, ExperimentValidationScope

check = validate_experiment(repository, ExperimentValidationRequest(
    experiment, ExperimentValidationScope.REPORT_PUBLICATION,
))
```

`STRUCTURE`检查身份、根报告及目录；`REPORT_PUBLICATION`还要求当前报告引用、快照、正文及关联证据一致。`ExperimentArtifactRef(owner, path, sha256)`中`path`相对其所属实验，禁止绝对路径、逃逸、符号链接或junction；共享材料可以属于同批次另一实验。只检查声明的必要材料，不要求完整过程封存，也不能发现未声明材料的语义归属。

返回`ExperimentValidation(status, scope, issues, report)`；`PASS`只表示结构或发布契约成立，不表示研究有效、实验成功、报告充分或阶段获批。

## 交付图校验与统计

`validate_delivery`仍区分`INTEGRITY/FULL`，前驱沿用既有范围，FULL仍按原协议复算当前交付。请求内复用以完整内容身份、实际路径、校验范围和公开副本状态为边界；活动递归路径与已完成节点分开，循环先于复用拒绝。每次引用重新认证文件，调用结束前再次认证所有已读取节点，不跨调用复用成功状态。

返回`stats`：`unique_deliveries/reference_visits/recursive_expansions/semantic_reuses/files_hashed/bytes_hashed/elapsed_seconds`。哈希计数统计交付服务显式执行的文件内容哈希，不含下游库内部操作系统读取量；最终复核包含在计数和耗时内。运行统计不参与交付身份或业务结果相等性。相同会话也用于发布前驱检查；不减少证据覆盖、不自动替换前驱关系。

正确性使用公开调用链和固定小数据验收。S014历史结果可另做只读对照，不重新计算或修改旧研究。全仓回归、合并、标签、远端同步及生产发布按各自授权执行。
