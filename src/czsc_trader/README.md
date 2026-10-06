# TDR 研究工具使用说明

TDR 为研究员提供批次上下文、账户评价、回测、结果留证、候选登记及五阶段交付。
阶段二、三的探索与搜索由 RSCH 自主组织，平台校验产物、输入身份及数值一致性。
研究目标、授权、候选选择和冻结批准见 [RSCH 契约](../../research/RSCH_AGENT.md)。
用户 CLI 提供 `backtest run`；Python API 与 CLI 的结果保存行为分别说明如下。

## 1. 公共契约与能力导航

| 任务 | 公共入口 | 输出与职责 |
| --- | --- | --- |
| 业务操作 | [application](application/__init__.py) | 批次、证据、候选、交付、决定、检验及冻结入口 |
| 研究类型 | [research_tools](research_tools/__init__.py) | 上下文、评价请求／结果和强类型交付内容 |
| 立项与意图 | `create_research_batch`、`update_research_intent` | 研究族、立项凭据及 `ResearchBatchRef` |
| 批次能力与实验分配 | `create_research_context`、`create_experiment` | `ResearchContext`、`ExperimentRef` |
| 账户评价 | `research.evaluation.prepare/evaluate/evaluate_many` | 绑定输入、计算各窗口／成本场景及逐项结果 |
| 完整回测 | `run_backtest` | `BacktestEvaluation`，包含账户、基准、指标和审计 |
| 结果留证 | `publish_evidence` | `EvidenceRef`，显式保存选定材料或完整评价事实 |
| 候选登记与读取 | `register_candidate`、`load_candidate` | 保存候选载荷、源码快照及支撑证据，读取已登记实体 |
| 五阶段交付 | `assemble_delivery`、`validate_delivery` | 结论、选定证据快照和不可变修订 |
| 自检与比较 | `build_assessment_evidence`；SE `assess_candidates/compare_candidates` | 数值事实适配、自检和比较 |
| 技术检验与冻结 | `inspect_candidate`、`record_research_decision`、`freeze_candidate`、`get_freeze_result` | 真实用户决定、技术检验、批准与事务状态 |
| 目录与模板 | `validate_catalog/list_catalog/show_catalog`、`validate_templates/list_templates/show_template/instantiate_template` | FSC/STC 公开内容与绑定校验 |
| 运行发布 | `list_installed_strategies`、`strategy_info`、`deploy_strategy`、`validate_release_package` | 发布查询和单独获准的部署操作 |

项目复用因子计算由 [FSC](../../packages/factor_signal_catalog/README.md) 提供，策略编写使用
[SRT](../../packages/strategy_runtime/README.md) 公共契约。第三方研究库由研究员组织，见
[RSCH 的使用原则](../../research/RSCH_AGENT.md#43-第三方研究库的用途与高效使用)。

| 对象 | 当前版本 |
| --- | --- |
| 已发布账户评价／回测 manifest | 5／5 |
| 阶段交付定义、文档和回执 | 5 |
| SM 候选登记／候选内容身份 | 3／2 |
| SM 冻结版本／SRT 发布记录 | 5／5 |
| SRT 运行定义／运行绑定 | 3／2 |
| SE 评价标准 | `opc-v3` |

版本按对象独立管理。当前入口只接受当前契约；历史研究原件供人工查阅，不自动解码或改签。

## 2. 输入、状态与生命周期

- `RepositoryContext.discover` 定位仓库路径；`create_research_context` 打开已登记批次并配置 DFLS。
- 研究批次、实验和交付采用强类型请求；其他服务是否接收文件路径以各自公开签名为准。
- 单次评价和回测返回计算结果，数据准备可能更新 DFLS 资产，计算缓存位于 `.tmp/`。它们不自动登记候选或保存阶段报告。
- 显式发布的证据、候选快照及阶段修订不可覆盖；同一内容可复用，冲突明确失败。
- 实验 `work/` 可修改，技术修正或重复计算可沿用同一实验。实验不需要整体封存，也无需保留全部运行过程。
- 正式结论的修正通过新交付修订表达。影响判断的有效负面结果、反证和修正说明仍须随结论保存。
- 数据身份、日期或数值不符时明确失败；研究成功、技术通过与用户批准分别判断。

## 3. 批次上下文、实验与数据

新立项使用 `create_research_batch(repository, ResearchBatchRequest, *, actor, reason)`，返回
`ResearchBatchRef`；调用前取得用户立项授权。更新意图使用
`update_research_intent(repository, batch, ResearchIntentUpdate, *, actor, reason)`。
重复启动同族的研究轮次需要显式且符合该策略ID的立项凭据，既有名称及范围须一致。

下面的连续示例在仓库根目录使用已获准并已登记的 `S900`。实际策略、日期、资源与费率按研究合同填写。

```python
from datetime import date
from pathlib import Path
from czsc_trader.application import (
    RepositoryContext, create_research_context, create_experiment, ExperimentRequest,
)
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources

repository = RepositoryContext.discover(Path.cwd())
research = create_research_context(
    repository, ResearchBatchRef("S900"),
    resources=EvaluationResources(max_workers=2, native_threads_per_worker=1, random_seed=42),
)
experiment = create_experiment(
    research, ExperimentRequest("收益机会检验", "该机制能否改善账户收益？", date(2026, 10, 7)),
)
work = experiment.resolve(repository.root) / "work"
```

`create_experiment` 在 `research/S900/experiments/EXxxx_YYYYMMDD/` 分配身份，创建 `experiment.json` 和初始笔记。
编号在批次内跨日期递增，分配时参考本批次旧目录的现有编号；三位编号耗尽时拒绝。具体代码及材料由 RSCH 写入 `work`。

上下文的 `data`、`runtime` 和 `evaluation` 共用 `research/<批次>/data/`。DFLS 的只读 `binding`
返回 `DataSpaceBinding(base_dir, space, space_id)`，可核对实际空间；批次上下文拒绝混用另一批次的数据能力。
默认供应商配置使用仓库 `.env`；需要明确的供应商绑定时向 `create_research_context` 提供 `ProviderConfig`。

```python
from dataflows import DataRequest, Dataset, PreparePolicy

requests = (
    DataRequest(dataset=Dataset.ETF_OHLCV, symbol="588080.SH", frequency="daily",
                start="2026-09-14", end="2026-09-15", required_cutoff="2026-09-15"),
)
prepared = research.data.prepare(requests, policy=PreparePolicy.REUSE)
if not prepared.ready:
    raise RuntimeError(tuple((item.status, item.error) for item in prepared.items))
market = research.data.fetch(requests[0], prepared=prepared.reference)
if not market.ready:
    raise RuntimeError(market.error)
```

一次 prepare 对完整请求集合完成校验、适用补丁及质量验收，再形成准备引用。fetch 读取已准备资产，
核对空间、准备身份与实现修订，不对子窗口重新执行质量验收。详情与门槛见 [DFLS 手册](../../packages/dataflows/README.md)。
独立取数与多个账户可复用相同批次空间；完整评价所需行情、分钟执行数据和策略预热由平台按实际依赖准备。

## 4. 策略评价与回测

### 账户评价

继续前例，先按 SRT 契约在 `work/strategy_runtime/` 编写策略并保存已核对的 `work/payload.json`。
下面的绑定来自该载荷，不能以任意参数替换真实源码身份。

```python
import json
from strategy_runtime import StrategyCandidate
from czsc_trader.research_tools import (
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, NextOpenBuyHold,
)

payload = json.loads((work / "payload.json").read_text(encoding="utf-8"))
candidate = StrategyCandidate("S900", "C0001", payload, work / "strategy_runtime")
request = EvaluationRequest(
    repository_root=repository.root, experiment_id=experiment.experiment_id,
    strategy=candidate,
    runtime_binding={
        "candidate_id": candidate.reference_id,
        "source_files": list(candidate.payload["runtime"]["source_files"]),
        "implementation_sha256": candidate.payload["runtime"]["source_sha256"],
    },
    symbol="588080.SH", asset_type="etf",
    windows=(EvaluationWindow("full", date(2026, 9, 14), date(2026, 9, 15)),),
    data_cutoff=date(2026, 9, 15), initial_cash=1_000_000,
    costs=(EvaluationCost("baseline", one_way_cost=0.001),),
    benchmark=EvaluationBenchmark(NextOpenBuyHold(lot_size=100)),
)
bound_request = research.evaluation.prepare(request)
result = research.evaluation.evaluate(bound_request)
```

保留 `bound_request`，用于结果留证、自检和技术检验的输入绑定。跨进程恢复时，保存请求参数、执行数据准备引用及策略输入绑定，按公开类型重建请求并保留对应数据资产。执行数据和策略输入引用必须来自同一批次空间，
无效引用或内容变化明确失败。重复评价可复用已准备输入，仍会执行账户计算。

`evaluate_many(tuple[EvaluationRequest, ...])` 按输入顺序返回 `EvaluationOutcome`：

| 状态 | 含义 |
| --- | --- |
| `SUCCEEDED` | 有经过身份核验的结果，无错误 |
| `FAILED` | 本项准备或计算失败，有错误，无结果 |
| `CANCELLED` | 本项被取消，有错误，无结果 |
| `UNKNOWN` | 工作进程等异常导致结果无法确认，有错误，无结果 |

批量请求为非空 tuple，各自 `workers=1`，批次并行数来自 `EvaluationResources.max_workers`。
主进程绑定输入，子进程以 `spawn` 计算；单项准备失败不妨碍其他项。非法类型或批量契约拒绝整次调用。
平台不自动重试、管理 Optuna study 或决定搜索预算；调用方根据逐项结果组织后续研究。

### 显式基准执行合同

`EvaluationRequest.benchmark` 必填。`NextOpenBuyHold(lot_size)` 使用下一交易日开盘价，
`LimitBuyHold(lot_size, premium, price_tick, price_limit_ratio, maximum_order_quantity)` 使用 SRT 限价规划。
两者要求显式整手单位，限价合同还约束溢价、价格档位、涨跌停比例和最大委托数量。
基准身份纳入评价及 SE 场景上下文；阶段一通过 `BenchmarkRequirement` 确认，阶段四核对实际基准。

成本场景名称、费率及计量层级由 RSCH 决定。`EvaluationCost` 要求非空且唯一的安全场景名、
有限 `0 <= one_way_cost < 1` 费率；计量层级为 `FORMAL/SCREENING/STRESS`，默认 `FORMAL`。
平台不从场景名推算费用。SE 的标准／压力配对诊断另外要求费用、层级和公共上下文可比，见 [SE 手册](../../packages/strategy_evaluator/README.md)。

### 完整回测

```python
from czsc_trader.application import BacktestRequest, run_backtest

backtest = run_backtest(
    research, candidate,
    BacktestRequest("588080.SH", "etf", date(2026, 9, 14), date(2026, 9, 15),
                    initial_cash=1_000_000, lot_size=100),
)
print(backtest.manifest["audit"]["status"], backtest.metrics)
```

`run_backtest(research, strategy, request) -> BacktestEvaluation` 接受本批次 `StrategyCandidate` 或已认证 `StrategyVersion`，
返回账户、基准、指标与审计，不自动保存 CSV、报告或图表。`lot_size` 必填正整数，并须与策略执行合同一致。
输入价格、时间、成交及费用通过 SRT/TXE 计算，SE 复算账户审计；完整回测包含 BuyHold、MA5/MA20 基准。
回测 manifest 为 schema 5，研究指标语义版本为 `candidate-srt-txe-v4-explicit-benchmark`。

执行行情按订单需要获取：限价成交通常使用30分钟，日内执行检查按需使用5分钟；仅市价执行与开盘持有基准可不需要分钟线。
分钟线直接消费 DFLS 不复权产品。SRT 独立规划策略预热，完整回测的 MA5/MA20 基准另需20个先前交易日。
缺少必需频率、日期或截止日时失败，不静默缩窗。

用户 CLI 从仓库根目录执行，仅接受已登记冻结版本；对应研究族须已登记。CLI 明确创建实验并保存报告证据，
JSON 输出的 `artifacts` 给出内容寻址文件路径，报告内图表链接保持可用。

```powershell
.\.venv\Scripts\czsc-trader.exe backtest run `
  --strategy S900 --strategy-version v1 `
  --symbol 588080.SH --asset etf `
  --start 2026-09-14 --end 2026-09-15 --init-cash 1000000 --lot-size 100
```

## 5. 显式发布和读取证据

计算完成后，按交付需要选择结果留证。完整账户证据保存请求身份、策略输入绑定、信号、账户账本、基准、指标和 SE 适配事实，
发布时核验请求与结果一致。它的格式是 `account_evaluation`／schema 5。

```python
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, EvaluationEvidenceRef

account_evidence = publish_evidence(
    research, EvaluationEvidenceWrite(experiment, "baseline-account", bound_request, result),
)
evaluation_reference = EvaluationEvidenceRef(account_evidence)
```

`EvaluationEvidenceRef.evaluation_ids` 为空表示引用该结果全部评价；可显式指定其中的评价ID。
协议、组件实现说明、反证或其他选定材料通过 `MaterialEvidenceWrite` 发布：

```python
from czsc_trader.research_tools import MaterialEvidenceWrite

note = publish_evidence(research, MaterialEvidenceWrite(
    experiment=experiment, name="mechanism-conclusion",
    content="机制结论与边界待按真实结果填写".encode("utf-8"),
    media_type="text/markdown", suffix="md",
))
verified_path = note.resolve(repository.root)
```

上例说明材料发布格式，实际结论须来自已完成研究。`EvidenceRef` 保存业务名、实验身份、内容哈希、媒体格式及可选 schema。
`path` 相对所属实验，`repository_path` 相对仓库；`resolve(repository.root)` 核验文件哈希。
TDR 根据内容生成 `evidence/<hash>.<suffix>`，同内容可复用，已有内容冲突拒绝覆盖。
证据引用可通过 `to_dict/from_dict` 保存和恢复。完整评价留证必须使用对应已绑定请求，材料发布不会自动变成账户评价证据。

## 6. 候选登记与自检

候选键为策略ID和 `C` 加四位数字。实现、有效参数或执行规则变化时使用新候选身份；评价不自动登记。
在阶段三授权范围内，继续前例登记交接候选：

```python
from czsc_trader.application import CandidateRegistrationRequest, register_candidate

registration = register_candidate(repository, CandidateRegistrationRequest(
    candidate=candidate, experiment=experiment, evidence=(account_evidence,),
    dependencies=bound_request.dependencies,
))
```

请求中的证据须为同批次、同候选内容的已发布完整评价，可来自该批次多个实验。
TDR 保存 `evidence/payload/` 和 `evidence/source/` 快照；SM 登记 schema 3，内容身份仍为 schema 2。
文件引用相对批次根 `research/<策略ID>/`，`source_root` 记录快照源码根。
同键同登记内容复用，冲突拒绝；`load_candidate(repository, CandidateKey(...))` 认证记录及源码后返回候选。
登记记录、源码快照和支撑证据须一起保留，修改原 work 不影响已登记候选。

未交接的搜索点无须逐个登记。`CandidateDerivation` 记录参数、实现或执行规则派生；
补充评价关系可使用 `EvaluationLineage`，不能据此覆盖已登记内容。

```python
from czsc_trader.research_tools import build_assessment_evidence

assessment_evidence = build_assessment_evidence(bound_request, result)
```

该适配器核验请求与结果，返回 `tuple[AssessmentEvidence, ...]`，供 SE `assess_candidates` 与 `compare_candidates` 使用。
实际费用、计量层级、基准、窗口及输入身份须可比，不能仅依赖相同场景名。
账户比较使用 SE `compare_ledgers`，按目的选用 `STRICT/ECONOMIC` 并读取实际状态；计算口径见 [SE 手册](../../packages/strategy_evaluator/README.md)。

## 7. 五阶段交付

`assemble_delivery(repository, DeliveryDefinition, DeliveryContent) -> DeliveryReceipt` 直接接受强类型数据。
研究员提供结论、必要事实、解释、人工报告和关联证据，自主组织实验过程。
平台核验结论与已声明证据的存在、身份、完整性及契约一致性，无法判断研究结论是否正确。
研究方法、证据是否充分及结论解释由 RSCH 负责。

`DeliveryContent` 必须以关键字参数提供非空字符串 `report`。RSCH 决定报告内容和组织方式，
平台将其 UTF-8 字节原样写入 `report.md`；目前不提供报告模板或自动生成报告。
报告使用的额外材料通过 `evidence: tuple[EvidenceRef, ...] = ()` 显式关联，
与内容契约中的证据一起核验和浅快照；平台不会从报告文字自动提取证据引用。

| 阶段 | 交付内容 | 主要校验 |
| --- | --- | --- |
| `MANDATE` | `ResearchMandate` | 目标、约束、基准及明确确认依据 |
| `COMPONENTS` | `ComponentPanel` | 组件定义、测试结论、边界及证据；引用 FSC 定义时核对所提交定义快照的身份 |
| `CANDIDATES` | `CandidateSet` | 候选内容及真实账户证据；handoff 对象须已登记且来源完整 |
| `ASSESSMENT` | `CandidateAssessmentDelivery` | 精确交接范围、已确认目标／窗口／基准、保存事实，以及 SE 自检和比较重算 |
| `INSPECTION` | `CandidateInspectionDelivery` | 实际选型、技术检验、决定及冻结事务证据 |

`FactValue` 的数值和不可用状态分别表达；`Explanation` 区分事实、假设、统计证据和研究判断。
`SearchSummary` 保存方法、范围、评价次数、独立配置数、选择依据、局限和必要证据，不要求完整 trial 历史。
组件测试仍需协议及结果证据，包含影响结论的负面结果；协议可共享，材料可来自同批次多个实验，
实验划分由 RSCH 决定。FSC 定义引用不依赖当前可变目录，提交的定义快照须与声明身份一致。
研究方法与用户要求由 RSCH 保证，平台校验产物契约。

继续前例，用该候选形成阶段三交付；实际修订号与前驱引用由 RSCH 按已发布记录指定。

```python
from czsc_trader.application import assemble_delivery, validate_delivery
from czsc_trader.research_tools import (
    CandidateEntry, CandidateIdentityRef, CandidateSet, DeliveryDefinition,
    DeliveryStage, DeliveryContent, DeliveryStatus, ValidationStatus,
)

candidate_set = CandidateSet(
    candidates=(CandidateEntry(CandidateIdentityRef(registration.key, registration.content_sha256),
                               "按实际机制填写收益假设", "提交自检", (evaluation_reference,)),),
    handoff=(registration.key,), searches=(), conclusion="交接该候选进行自检与比较",
)
receipt = assemble_delivery(
    repository, DeliveryDefinition(research.batch, DeliveryStage.CANDIDATES, revision=1),
    DeliveryContent(
        candidate_set, DeliveryStatus.COMPLETE, facts=(), explanations=(),
        report="交接该候选进行自检与比较。关联账户评价支持本次交付，后续结论待自检完成。",
        evidence=(),
    ),
)
checked = validate_delivery(repository, receipt.reference)
if checked.status is not ValidationStatus.PASS:
    raise RuntimeError(checked.issues)
```

交付位于 `research/<批次>/deliveries/<阶段>/<修订>/`，包含 `delivery.json`、`report.md`、`receipt.json`、
选定证据的 `evidence/` 浅快照及必要的决定／检验 `support/`。不复制整个 work 或历史执行目录。
`DeliveryDefinition`、`DeliveryReceipt` 和 `delivery.json` 使用 schema 6，读取时拒绝旧交付格式，
不自动迁移历史原件。账户评价证据与 `StrategyVersion` 继续使用各自的 schema 5。
修订号在“批次＋阶段”内唯一，同内容重复发布复用，冲突拒绝覆盖，失败不留下可见的半成品修订。
前驱为同批次的 `DeliveryReference`；同阶段前驱只能是更早修订。

`PARTIAL/BLOCKED` 须列明未完成项，完整交付不能同时声称有未完成项。
校验默认 `DeliveryValidationScope.FULL`，核对文件身份和关联事实，并重算阶段四 SE 结果；
`INTEGRITY` 仍核对文件、引用及保存事实，但不重新执行阶段四 SE 自检和排序计算。两者都不重跑整个研究过程。
两种范围均核验 `report.md` 与提交的 `report` 字节一致；该检查不判断文字解释或研究结论的正确性。
阶段五继续核验实际决定、检验及冻结状态；交付快照不取代运行发布和批准事实。

## 8. 技术检验、用户决定与冻结

1. 用户依据阶段四交付选择明确的候选。通过 `record_research_decision` 保存真实选择与确认来源。
2. `inspect_candidate(repository, CandidateInspectionRequest)` 使用批次上下文，对已登记候选及拟冻结版本进行技术检验。
3. 向用户交付检验报告、已形成的 `FreezePlan`、风险和待决定事项。检验通过后仍需用户对该计划的明确批准。
4. 保存批准决定，再调用 `freeze_candidate(repository, FreezeCandidateRequest)`；用 `get_freeze_result` 核对事务状态。
5. 冻结后的状态用阶段五新修订交付，已发布的待批准修订继续保留。

| 契约 | 核心字段与意义 |
| --- | --- |
| `ResearchDecision`（SM） | `decision_id/strategy_id/action/subject/confirmation_source/reason`；真实批准、拒绝或待定 |
| `CandidateSelectionSubject`（SM） | 阶段四回执、候选键及内容哈希 |
| `InspectionReplay`（TDR） | `reference: EvaluationEvidenceRef`、`reproduction_request: EvaluationRequest`；已发布账户证据与可重放的请求 |
| `CandidateInspectionRequest`（TDR） | 候选、选择、协议、`research: ResearchContext`、`experiment: ExperimentRef`、replays、版本及父版本、变更说明、选择截止日、前瞻起始日、附加发布文件和剩余风险 |
| `CandidateInspectionReport`（SM） | `origin` 独立绑定候选登记身份；`plan: FreezePlan \| None`、实际选型、协议、逐项检查、风险及所属实验 |
| `FreezeSubject`（SM） | 候选内容、检验报告、冻结计划哈希和准确版本 |
| `FreezeCandidateRequest`（SM） | `request_id/inspection/approval`；绑定准确检验和批准 |

请求与引用的构造见 [SM 手册](../../packages/strategy_manager/README.md) 及 [公开类型](application/inspection_service.py)。
技术检验保存于所属实验 `evidence/inspection/`，可以在同一实验追加独立检验；每次报告与计划以内容身份保存。
检验核对可交付文件、源代码闭包、依赖、数据截止日、实际信号和账户账本，以及冻结运行的技术等价性。
重放需要保留原绑定引用及对应批次数据资产，不能只保存一份账户 JSON。

检验先核验请求、登记身份及实际选型，再检查候选材料和运行依赖。源码、载荷、依赖、
计划构建或重放等技术失败会保存失败报告和原因；已完成项保留实际状态，后续未执行项标为 `INCOMPLETE`。
计划尚未形成时报告保留 `origin` 且 `plan=None`，可作为阶段五 `BLOCKED` 交付，
由 RSCH 编写报告并说明未完成项和待决定事项；无计划或检验未通过均不能冻结。
请求参数、声明引用身份和授权错误仍明确拒绝；候选材料损坏及运行不一致按技术检查结果留证。

SM 在独立事务日志中保存事实，发布包准备完成后以版本文件的原子写入作为运行可见性边界。
冻结返回 `NOT_FOUND/IN_PROGRESS/COMMITTED/FAILED/UNKNOWN`，仅 `COMMITTED` 携带确定的版本引用。
同请求同内容复用既有状态，同请求不同内容或版本冲突拒绝；不自动换号、重试或回滚。
冻结初始资格为 `RESEARCH`，模拟交易资格、SRT 部署、PTE 账户及生产变更另行授权。

## 9. 目录与保存责任

精确的路径指定及落盘模块见 [研究导航](../../research/README.md#批次空间与落盘职责)。
批次 DFLS 空间、候选快照和已发布证据属于正式引用的一部分；数据资产按实际 Git 规则单独保存。
`.tmp/`、准备引用或 Git clone 均不能替代缺失的数据资产。正式交接说明引用、资产位置及同步责任。

旧实验、旧交付和旧候选原件保持原位，继续研究时按授权生成当前契约证据，见 [历史实验说明](../../experiments/README.md)。
运行策略加载核验自己的版本、发布包与部署身份，运行合同独立于可修改实验材料。
