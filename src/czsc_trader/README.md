# TDR 研究工具使用说明

TDR 为研究员提供批次上下文、研究概览、账户评价与诊断、回测、实验报告、结果留证、候选登记及五阶段交付。
本文是这些公共工具的统一使用入口，说明调用契约、支持范围、示例及结果处理；研究方法与判断责任由RSCH指南规定。
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
| 结果留证 | `publish_evidence`、`publish_evidence_many` | 单项 `EvidenceRef`；批量逐项 `PublicationOutcome` |
| 候选登记与读取 | `register_candidate`、`load_candidate` | 保存候选载荷、源码快照及支撑证据，读取已登记实体 |
| 五阶段交付 | `assemble_delivery`、`validate_delivery` | 结论、选定证据快照和不可变修订 |
| 研究概览 | `get_research_overview(repository, batch)` | `ResearchOverview`，读取保留事实、来源及限制 |
| 账户诊断 | `diagnose_accounts(repository, AccountDiagnosisRequest)` | `AccountDiagnosisResult`，正式账户损益、路径差异及覆盖 |
| 实验检查 | `validate_experiment(repository, ExperimentValidationRequest)` | `ExperimentValidation`，实验结构或报告发布一致性 |
| 自检与比较 | `build_assessment_evidence`；SE `assess_candidates/compare_candidates` | 数值事实适配、自检和比较 |
| 技术检验与冻结 | `inspect_candidate`、`record_research_decision`、`freeze_candidate`、`get_freeze_result` | 真实用户决定、技术检验、批准与事务状态 |
| 目录与模板 | `validate_catalog/list_catalog/show_catalog`、`validate_templates/list_templates/show_template/instantiate_template` | FSC/STC 公开内容与绑定校验 |
| 运行发布 | `list_installed_strategies`、`strategy_info`、`deploy_strategy`、`validate_release_package` | 发布查询和单独获准的部署操作 |

项目复用因子计算由 [FSC](../../packages/factor_signal_catalog/README.md) 提供，策略编写使用
[SRT](../../packages/strategy_runtime/README.md) 公共契约。第三方研究库由研究员组织，见
[RSCH 的使用原则](../../research/RSCH_AGENT.md#62-研究工具使用原则)。

| 对象 | 当前版本 |
| --- | --- |
| 账户评价证据／请求身份 | 7／6 |
| 已发布账户评价／回测 manifest | 5／5 |
| 实验报告快照 | 1 |
| 阶段一至四交付定义、文档和回执 | 8 |
| INSPECTION交付定义、文档和回执 | 9 |
| 选型对象／冻结计划／技术检验报告 | 2／2／2 |
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
- 实验 `src/`、`protocols/`、`others/` 和根目录 `notes.md` 可修改，技术修正或重复计算可沿用同一实验。运行结果、搜索数据库及检查点按需要保存于批次 `assets/runs/<实验>/<运行>/`。
- 正式结论的修正通过新交付修订表达。影响判断的有效负面结果、反证和修正说明仍须随结论保存。
- 数据身份、日期或数值不符时明确失败；研究成功、技术通过与用户批准分别判断。

## 3. 批次上下文、实验与数据

### 批次与实验分配

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
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources

repository = RepositoryContext.discover(Path.cwd())
research = create_research_context(
    repository, ResearchBatchRef("S900"),
    resources=ExecutionResources(max_workers=2, native_threads_per_worker=1, random_seed=42),
)
experiment = create_experiment(
    research, ExperimentRequest("收益机会检验", "该机制能否改善账户收益？", date(2026, 10, 7)),
)
experiment_root = experiment.resolve(repository.root)
source = experiment_root / "src"
```

`create_experiment` 在 `research/S900/experiments/EXxxx_YYYYMMDD/` 分配身份，创建 `experiment.json`、根目录初始 `notes.md`、进行中的`report.md`及`src/`、`protocols/`、`others/`。单个实验材料内聚于该目录，正式资产仍由批次`assets/`管理。实验报告独立发布，不要求阶段交付；操作见[实验报告发布](#实验报告独立发布与修订)。
编号在批次内跨日期递增，分配时参考本批次旧目录的现有编号；三位编号耗尽时拒绝。源码、实验方案和其他材料分别保存于对应目录，运行资料由研究程序按需要组织。

上下文的 `data`、`runtime` 和 `evaluation` 共用 `research/<批次>/assets/data/`。DFLS 的只读 `binding`
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

### 研究概览

`get_research_overview(repository, batch) -> ResearchOverview`接受已发现的仓库上下文和批次引用。
研究概览、账户诊断及实验检查均为只读入口，不创建数据准备环境，不访问供应商、PTE生产库或其他研究批次，不重新执行策略。

```python
from czsc_trader.application import get_research_overview
from czsc_trader.research_tools import ResearchBatchRef

overview = get_research_overview(repository, ResearchBatchRef("S900"))
```

返回登记状态、各阶段最高已支持修订、实验报告状态、组件测试声明、候选、交接集合、搜索声明、计数、限制及来源快照。来源包含文件/目录位置、存在状态和哈希；调用结束前复核读取清单，检测并发变化即报错，不自动重试。

计数的`basis`为`VERIFIED`（已认证登记事实）、`DECLARED`（已保存的声明）或`UNKNOWN`（`value=None`及原因）。重复交付中的相同搜索声明只展示一次；多个可能重叠的搜索声明不相加。账户评价数只覆盖保留的评价身份声明，不等于账户账本已认证，也不是完整尝试次数。没有受管的经济路径分组声明时，该计数保持未知，不在概览中重算。

概览认证保留记录及关联文件哈希，不重算SE、验证运行资格或判断研究是否充分。最高交付修订不等于阶段获批；登记状态不代替当前用户指令。旧格式明确列为不支持，不按新格式解读。缺失或损坏的必要引用报错，不补零或静默改用旧版本。

报告状态为`MISSING`、`DRAFT`、`PUBLISHED`、`UNPUBLISHED_CHANGES`。历史实验缺少根报告如实显示，不自动搬迁或补写。

### 实验结构与报告检查

创建实验后可用`STRUCTURE`检查结构；以下示例用于完成第5节的独立报告发布后，检查当前报告与正式引用的一致性。

```python
from czsc_trader.application import validate_experiment
from czsc_trader.research_tools import ExperimentValidationRequest, ExperimentValidationScope

check = validate_experiment(repository, ExperimentValidationRequest(
    experiment, ExperimentValidationScope.REPORT_PUBLICATION,
))
```

`STRUCTURE`检查身份、根报告及目录；`REPORT_PUBLICATION`还要求当前报告引用、快照、正文及关联证据一致。`ExperimentArtifactRef(owner, path, sha256)`中`path`相对其所属实验，禁止绝对路径、逃逸、符号链接或junction；共享材料可以属于同批次另一实验。只检查声明的必要材料，不要求完整过程封存，也不能发现未声明材料的语义归属。

返回`ExperimentValidation(status, scope, issues, report)`；`PASS`只表示结构或发布契约成立，不表示研究有效、实验成功、报告充分或阶段获批。

## 4. 策略评价与回测

### 账户评价

继续前例，先按 SRT 契约在 `src/strategy_runtime/` 编写策略并保存已核对的 `src/payload.json`。
下面的绑定来自该载荷，不能以任意参数替换真实源码身份。

```python
import json
from strategy_runtime import StrategyCandidate
from czsc_trader.research_tools import (
    EvaluationRequest, EvaluationWindow, EvaluationCost, EvaluationBenchmark, NextOpenBuyHold,
)

payload = json.loads((source / "payload.json").read_text(encoding="utf-8"))
candidate = StrategyCandidate("S900", "C0001", payload, source / "strategy_runtime")
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
无效引用或内容变化明确失败。普通重复评价会重新计算；显式执行会话的检查点可恢复已完整落盘且通过身份核验的结果。

`signal_cash_fraction / entry_cycle`沿用相同评价、批量和留证入口。策略的`CYCLE_TARGET`信号决定本次资金比例；
SRT生成预算与目标份额，TXE采纳计划并按实际成交更新周期。决策账本保存当前信号、计划采纳前后周期、
周期状态与身份；每日账本保存成交后的周期预算和含费累计买入金额。这些字段完整进入结果身份、跨进程传输和正式账户证据。
SE除普通账户核对外，独立检查开仓预算、数量目标、补买上限、持有锁定、退出释放及成交累计；字段缺失或不一致明确失败。
评价环境身份包含`entry_cycle.py`，技术检验的实际平台源码清单也覆盖该模块。预算锁定策略与每日权益目标策略不能据相同比例认定执行等价。
技术检验的经济比较按引用关系重命名信号、计划和周期身份（含周期JSON内的开仓信号与周期引用）；比例、预算、锁定份额、累计买入金额及阶段状态继续精确比较。
当前账户损益诊断只支持全仓/现金单次买卖，动态周期分配明确返回`UNSUPPORTED`；这不影响账户评价和数值审计。

`evaluate_many(tuple[EvaluationRequest, ...])` 按输入顺序返回 `EvaluationOutcome`：

| 状态 | 含义 |
| --- | --- |
| `SUCCEEDED` | 有经过身份核验的结果，无错误 |
| `FAILED` | 本项准备或计算失败，有错误，无结果 |
| `CANCELLED` | 本项被取消，有错误，无结果 |
| `UNKNOWN` | 工作进程等异常导致结果无法确认，有错误，无结果 |

批量请求为非空 tuple，资源配置统一来自 `ExecutionResources`，`EvaluationRequest` 不再含 `workers`。
先预检全部请求契约；主进程逐项绑定输入，准备完成即提交给 `spawn` 子进程，
使后续准备与已经提交的账户计算重叠。单项准备或传输失败不妨碍其他项；非法类型或批量契约在计算前拒绝整次调用。
平台不自动重试、管理 Optuna study 或决定搜索预算；调用方根据逐项结果组织后续研究。

### 研究库与并行执行

以下配置承接[RSCH研究工具使用原则](../../research/RSCH_AGENT.md#62-研究工具使用原则)，由研究员组织，平台按显式资源请求执行。

| 库 | 解决的问题 | 高效使用方式 |
| --- | --- | --- |
| Optuna | 管理参数提议、搜索轨迹与trial状态，包括联合搜索、固定网格和参数扰动 | 独立使用`InMemoryStorage`，由主进程持有唯一Study并组织提议、调度和结果回填；独立CPU密集评价默认使用多进程，Windows采用`spawn`。采样器与并发方式分别选择，按实际版本验证重复提议和耗尽行为；完整账户评价仍经TDR批次上下文执行 |
| tsfresh | 从时序中批量提取和筛选候选特征 | 适用的特征普查应实际使用该库；按研究问题限定特征集合和窗口，批量提取并使用授权预算内的多核能力，复用相同输入与配置的计算结果；筛选结果仍须接受因果核验和组件职责评审 |
| expr_codegen | 将因子表达式转换为可执行计算代码 | 对同批表达式统一生成代码，复用生成结果，减少逐条解释和重复生成；使用前核对当前版本支持的计算后端，并与参考计算逐值核验 |
| pandas、NumPy及统计库 | 数据对齐、批量数值计算与统计检验 | 优先使用向量化、批量运算和公共中间结果，减少逐行Python循环与重复转换；按内存容量分批，核验缺失值、索引和数值类型对结果的影响 |
| 其他加速评价库 | 降低特定计算环节或策略评价的耗时 | 先用代表性样例确认加速收益与适用交易语义；用于正式比较前，必须完成与SRT/TXE的信号及完整经济账本等价性核验 |

可并行接口内部默认采用`max(1, os.cpu_count() * 70 // 100)`个工作进程／线程，向下取整；
例如16个逻辑核默认11个，实际同时执行数还受独立任务数限制。`ExecutionResources(max_workers=...)`
显式覆盖，默认`native_threads_per_worker=1`。无法识别逻辑核数时明确报错，调用方可显式指定。
预算控制工作进程／线程数量，不承诺CPU利用率；同一会话共享总预算，不同顶层会话不受整机调度器协调。
`evaluate_many`在请求间并行，子请求内部执行使用一个工作线程；`evaluate`可在独立窗口／费用场景间使用上下文预算。
资源类型不负责Optuna调度；研究员仍须统筹平台以外的trial及第三方库并发。

正式批量评价调用`context.evaluation.evaluate_many(tuple_of_requests)`，由TDR使用Windows `spawn`
进程池执行研究员已确定的请求。主进程持有Study和批次上下文，核对逐项结果并选择必要证据；子进程只计算，
不得按worker或计算分片创建实验。进程数取`ExecutionResources.max_workers`。
单次`evaluate`返回`EvaluationResult`，失败抛出异常；批量`evaluate_many`逐项返回`EvaluationOutcome`，
区分`SUCCEEDED/FAILED/CANCELLED/UNKNOWN`。研究员据此决定Optuna回填及显式重试，
平台不管理研究预算或自动重试；正式发布使用`evaluation.prepare`绑定后的请求和对应结果。
正式批量运行前，用最小样例验证公共API、传输、目录隔离和结果一致性。默认配置不适用时，报告阻断证据和调整方案，不得静默串行或增加兜底。
披露实际配置、种子、搜索范围、评价及独立配置数量、选择依据和方法局限；保存正式结论所需结果与反证。
内存Study不替代必要的持久证据，无须保留全部trial和技术失败日志；并行采样的复现范围须如实说明。
安装、升级及跨角色修改仍需另行授权；研究依赖不得自动进入冻结运行时依赖。

### 执行会话与显式恢复

`open_research_execution(research, experiment=..., checkpoint=None, on_progress=None)`返回
`ResearchExecutionSession`上下文管理器。连续批次通过`execution=session`共享同一个有界`spawn`池，
评价和证据序列化按完成顺序收取结果，返回tuple仍保持输入顺序。正式证据仅由主进程提交。
不传会话时，批量API内部创建并关闭一次相同执行器。一个研究上下文同时只允许一个显式会话；
会话活动期间必须明确传入它，避免隐式创建第二个资源预算。

```python
from czsc_trader.application import open_research_execution, publish_evidence_many
from czsc_trader.research_tools import (
    CheckpointMode, ExecutionCheckpointRequest, EvaluationEvidenceWrite,
)

with open_research_execution(
    research, experiment=experiment,
    checkpoint=ExecutionCheckpointRequest("stage4-round1", CheckpointMode.CREATE),
) as session:
    outcomes = research.evaluation.evaluate_many(bound_requests, execution=session)
    selected = tuple(
        EvaluationEvidenceWrite(experiment, f"account-{i}", request, outcome.result)
        for i, (request, outcome) in enumerate(zip(bound_requests, outcomes, strict=True))
        if outcome.status.value == "SUCCEEDED"
    )
    if selected:
        publications = publish_evidence_many(research, selected, execution=session)
stats = session.stats
```

重启后用相同运行标识和`CheckpointMode.RESUME`打开会话，重新提供准备后的请求。
检查点位于`.tmp/research-execution/<批次>/<运行标识>/`，包括绑定实验与实现身份的`manifest.json`、
`results/<请求哈希>.json`和`publications/<发布身份哈希>.json`。使用结构化JSON、校验和、原子写入及单写锁，
恢复时重新核对请求、源码／实现、数据、参数、数值结果及当前证据字节；不读取磁盘pickle。
同一请求可恢复已完整保存的计算结果，继续显式发布；不同名称的发布不会错误复用旧名称引用。
缓存损坏或身份不符明确失败，不自动重新计算掩盖问题。未保存的结果需要调用方明确决定重试。
缓存可清理，正式交付不依赖检查点；`CREATE`不覆盖已有运行，`RESUME`不创建缺失运行。

工作进程丢失时，计算结果按`UNKNOWN`表达；仅在序列化阶段丢失工作进程且主进程未提交文件，
发布状态为`FAILED`。文件提交无法确认时仍为`UNKNOWN`。进程池损坏或收取结果中断后禁止继续使用该会话，
调用方需关闭它并显式开启新的会话。平台不自动重试、不重建损坏池、不静默改为串行。

`ExecutionProgress`报告阶段、完成数、失败／未知数和耗时，回调在主进程执行；回调异常使调用失败。
`session.stats`区分会话墙钟时间、分阶段墙钟区间、累计工作进程时间、进程池创建次数及恢复命中数。
准备与计算、发布与序列化可能重叠，分段区间不能直接相加；累计工作进程时间也不等于端到端耗时。
资源变化不改变策略参数，平台源码变化可能改变评价环境／结果身份，应比较经济账本与数值并核验新身份。

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

基准估值与图表投影使用独立的数值容器，避免在 pandas 派生操作中反复深复制行情的质量元数据。
原始输入及其元数据保留用于认证；同次基准计算的 BuyHold 和 MA 共用已构造的估值表，
数值结果保持隔离，不修改调用方行情。复用仅发生在本次内存调用中，不新增磁盘缓存或跨调用认证缓存，
输入身份、当前字节及数值校验继续执行。端到端性能验证需同时计入报告生成和实际写盘，
不得将纯计算时间直接当成完整交付耗时。

普通`FROZEN_RULE`目标仓位策略采用`DAILY_RANGE_V3`日范围成交模型，含普通限价单；该路径不请求分钟成交数据，
也不按成交量约束成交数量。当前声明`11:30_CLOSE`检查点的日内执行策略请求5分钟DFLS不复权产品；
仅声明`OPEN`检查点不增加分钟需求。
数据已准备不表示某个账户执行路径实际消费了该频率。具体成交与时点精度见[TXE](../../packages/trading_execution_engine/README.md)。
SRT独立规划策略预热，完整回测的MA5/MA20基准另需20个先前交易日。
缺少必需频率、日期或截止日时失败，不静默缩窗。

多档位策略须显式声明`FROZEN_RULE`资金模式`target_equity_fraction`、作用范围`decision`及
`allocation_fraction=1`。TDR评价保留小数目标，由SRT按实际账户权益计算份额、TXE执行及记账；
原`entry_cycle`资金模式仍仅接受0/1目标。计算规则见[SRT执行计划](../../packages/strategy_runtime/README.md#执行计划)。
公开账户归因诊断的全仓/现金、单周期单次买入等限制不因新增仓位能力而扩大。

用户 CLI 从仓库根目录执行，仅接受已登记冻结版本；对应研究族须已登记。CLI 明确创建实验并保存报告证据，
JSON 输出的 `artifacts` 给出内容寻址文件路径，报告内图表链接保持可用。

```powershell
.\.venv\Scripts\czsc-trader.exe backtest run `
  --strategy S900 --strategy-version v1 `
  --symbol 588080.SH --asset etf `
  --start 2026-09-14 --end 2026-09-15 --init-cash 1000000 --lot-size 100
```

### 账户损益与路径诊断

`diagnose_accounts(repository, request) -> AccountDiagnosisResult`要求强类型`AccountDiagnosisRequest`，引用正式证据及精确评价身份。
以下示例在完成第5节的账户证据发布后执行，沿用前例单窗口、单成本场景的`result`及`bound_request`；多个场景须显式选择对应评价和窗口。

```python
from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import (
    AccountDiagnosisRequest, AccountRunRef, AccountDiagnosisStatus,
)

selected_run = result.runs[0]
if selected_run.identity is None:
    raise ValueError("账户评价缺少完整身份")
diagnosis = diagnose_accounts(repository, AccountDiagnosisRequest(
    baseline=AccountRunRef(account_evidence, selected_run.identity),
    alternative=None,
    window=bound_request.windows[0],
))
if diagnosis.status is AccountDiagnosisStatus.COMPUTED:
    print(diagnosis.reconciliation)
else:
    print(diagnosis.status.value, diagnosis.issues)
```

`account_evidence`须是`account_evaluation` schema 7正式证据，`AccountRunRef.identity`精确选中一个评价；平台核验原始哈希、账户及账本认证，不凭候选编号找最近一次结果。`alternative`可传同批次另一账户；标的、市场执行数据、费用、单位、初始资金及会话等上下文不同则不可比。候选实现可以不同。

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

## 5. 显式发布和读取证据

### 账户与材料证据

计算完成后，按交付需要选择结果留证。完整账户证据保存请求身份、策略输入绑定、信号、账户账本、基准、指标和 SE 适配事实，
发布时核验请求与结果一致。它的格式是 `account_evaluation`／schema 7，请求身份使用 schema 6，
包含实际策略输入绑定及可选的参数扰动点绑定。

```python
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import EvaluationEvidenceWrite, EvaluationEvidenceRef

account_evidence = publish_evidence(
    research, EvaluationEvidenceWrite(experiment, "baseline-account", bound_request, result),
)
evaluation_reference = EvaluationEvidenceRef(account_evidence)
```

多项留证使用 `publish_evidence_many(research, requests)`，`requests` 必须是非空
`tuple[EvidenceWriteRequest, ...]`，返回与输入顺序一致的 `tuple[PublicationOutcome, ...]`。
账户认证及 JSON 序列化按 `research.evaluation.resources` 的进程数和原生线程预算计算；
子进程只返回证据字节，主进程逐项原子发布，已完成项无需等待前面的慢项。材料字节由主进程直接发布。
`max_workers=1` 明确采用串行计算；多进程失败不重试或切换串行计算。

批量调用先检查全部请求类型、批次、已分配实验和数据空间归属；非法调用整体抛出异常，且不发布任何项。
账户结果认证、序列化和实际写入失败按项返回，不撤销其他已发布项。
`PublicationOutcome.index` 是输入的零起始位置，`status` 使用 `PublicationStatus`：
`PUBLISHED` 只携带 `reference`，`FAILED`、`CANCELLED`、`UNKNOWN` 携带 `PublicationError`；
除基本错误外，报告发布错误还可保留阶段、快照引用及当前引用的提交状态，见[实验报告发布](#实验报告独立发布与修订)。
计算进程失败时正式证据尚未写入，返回 `FAILED`；计算取消返回 `CANCELLED`。
若原子写入之后发生异常，或无法确认写入状态，返回 `UNKNOWN`，不会自动重试。

```python
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import PublicationStatus

publications = publish_evidence_many(research, (
    EvaluationEvidenceWrite(experiment, "baseline-account", bound_request, result),
))
for item in publications:
    if item.status is PublicationStatus.PUBLISHED:
        retained = item.reference
    else:
        print(item.index, item.status.value, item.error.code, item.error.message)
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
`path` 为交付包内的 `evidence/<hash>.<suffix>`，`repository_path` 为仓库内的
`research/<批次>/assets/evidence/<实验>/<hash>.<suffix>`；`resolve(repository.root)` 核验文件哈希。
TDR 按内容哈希保存证据，同内容可复用，已有内容冲突拒绝覆盖。
证据引用可通过 `to_dict/from_dict` 保存和恢复。完整评价留证必须使用对应已绑定请求，材料发布不会自动变成账户评价证据。

正式账户及五张账本保存在`research/<批次>/assets/evidence/<实验>/<哈希>.json`；`assets/runs/`中的运行资料不作为账户诊断的默认输入。

### 实验报告独立发布与修订

先将实际结论写入实验根`report.md`并选择结果声明。下例假定报告已完成，使用前例正式账户证据作为来源；发布接口不判断研究结论或报告内容是否充分。

```python
from hashlib import sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import ExperimentOutcome, ExperimentReportWrite

report_bytes = (experiment.resolve(repository.root) / "report.md").read_bytes()
report_ref = publish_evidence(research, ExperimentReportWrite(
    experiment=experiment,
    expected_report_sha256=sha256(report_bytes).hexdigest(),
    outcome=ExperimentOutcome.COMPLETED,
    evidence=(account_evidence,),
    previous=None,
))
```

`outcome`由RSCH声明：`COMPLETED/FAILED/CANCELLED/INCOMPLETE`。没有阶段交付也能发布，阶段报告与实验报告不要求相同。

通过`publish_evidence`提交`ExperimentReportWrite`，返回报告快照的`EvidenceRef`。快照为`experiment_report` schema 1，保存UTF-8原文、字节哈希、声明结果、来源及前版，不转换换行；根`report_ref.json`指向当前正式快照。前版冲突或正文哈希变化拒绝，同一请求可幂等确认。发布不会改写根报告。

引用提交前失败可能留下不可变但未被当前引用指向的快照，不删除或冒称提交完成。`ReportPublicationError`及批量`PublicationError`提供`phase/reference/pointer_committed`；发生异常且指针已提交或提交结果不确定时批量状态为`UNKNOWN`，明确未提交为`FAILED`，取消按实际状态表达。正常提交仍返回`PUBLISHED`。不自动重试。`publish_evidence_many`逐项报告，参数预检失败仍在任何写入前拒绝整批。

根报告以后可继续编辑；已发布快照仍不变，正文不同于当前快照即为未发布修改，修订时传入准确的`previous`。原始阶段交付、候选及旧实验报告不迁移、不重签。

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
TDR 保存 `assets/candidates/<候选>/payload/<hash>.json` 和 `assets/candidates/<候选>/source/<hash>/strategy_runtime/` 快照；SM 登记 schema 3，内容身份仍为 schema 2。
文件引用相对批次根 `research/<策略ID>/`，`source_root` 记录快照源码根。
同键同登记内容复用，冲突拒绝；`load_candidate(repository, CandidateKey(...))` 认证记录及源码后返回候选。
登记记录、源码快照和支撑证据须一起保留，修改原实验源码不影响已登记候选。

未交接的搜索点无须逐个登记。`CandidateDerivation` 记录参数、实现或执行规则派生；
补充评价关系可使用 `EvaluationLineage`，不能据此覆盖已登记内容。

```python
from czsc_trader.research_tools import build_assessment_evidence

assessment_evidence = build_assessment_evidence(bound_request, result)
```

该适配器核验请求与结果，返回 `tuple[AssessmentEvidence, ...]`，供 SE `assess_candidates` 与 `compare_candidates` 使用。
实际费用、计量层级、基准、窗口及输入身份须可比，不能仅依赖相同场景名。
账户比较使用 SE `compare_ledgers`，按目的选用 `STRICT/ECONOMIC` 并读取实际状态；计算口径见 [SE 手册](../../packages/strategy_evaluator/README.md)。

### 参数扰动评价

SE 生成 `ParameterPerturbationDesign`，RSCH 将规定坐标转换为实际策略载荷；TDR 认证载荷、
同源执行条件和真实账户。默认研究流程采用 5% 总距离、32 个联合点、种子 13；平台接受显式协议，
不根据研究结果自动增加距离或替换规定点。具体几何与分位数口径见 [SE 参数扰动](../../packages/strategy_evaluator/README.md)。

默认五项独立检验时，参数计划中的中心和全部子候选只声明同一基准窗口、标准费用；
中心费用压力另建独立请求，不与子点交叉。完整非参数契约包含整个窗口及费用列表，
不得用双费用中心请求搭配单费用子请求，也不得改写已有证据的请求身份来复用。
中心标准账本同时支撑时间稳定性、收益集中性及收益区间；完整身份核对通过的既有结果可复用。
没有可复用证据时，每中心默认34个策略账户场景，研究族收益补证另计。

先用 `MaterialEvidenceWrite` 发布坐标映射及可行性约束材料；其原始字节哈希应分别等于
`ParameterSpace.mapping_sha256`、`feasibility_sha256`。中心和全部子候选通过
`research.evaluation.prepare` 准备后，构造完整计划：

```python
from czsc_trader.research_tools import ParameterEvaluationPlan, EvaluationLineage

plan = ParameterEvaluationPlan.create(
    design, prepared_center, prepared_children,
    mapping_evidence=mapping_reference, feasibility_evidence=constraint_reference,
    dataflows=research.data,
)
plan_reference = publish_evidence(research, MaterialEvidenceWrite(
    experiment, "parameter-evaluation-plan",
    json.dumps(plan.to_dict(), ensure_ascii=False).encode("utf-8"), "application/json", "json",
))
point_binding = plan.bind_point(plan_reference, 0, repository_root=repository.root)
child_request = replace(prepared_children[0], lineage=EvaluationLineage(derivation, point_binding))
child_result = research.evaluation.evaluate(child_request)
```

上例需导入 `json` 及 `dataclasses.replace`；`derivation` 为实际中心与该子候选的 `PARAMETERS` 派生关系。
`ParameterEvaluationPlan` 使用 schema 1，保存中心和各子候选的完整规范 JSON 载荷、内容身份、
规定点集、中心请求身份、中心输入准备身份、固定执行契约和映射／约束材料引用。
各子载荷及有效内容必须互不相同，也必须不同于中心；相同行为不构成拒绝理由。
`ParameterEvaluationBinding` 保存已发布计划引用及 SE `ParameterPointBinding`，进入请求哈希和账户证据。
普通评价可以不提供该绑定；带绑定的评价必须核验计划已经发布、文件字节一致、点序号及实际载荷匹配。

参数计划读取每次核验计划及两份材料的实际字节。内部只复用最近一份已验证内容的不可变解析结果，
不缓存文件核验成功状态。一次交付发布或校验内，相同实际账户字节可复用已通过的解析、账本认证及结构化事实，
仍在每次引用时重新读取文件、核验哈希和证据归属。不同公开调用各自认证，FULL交付仍独立复算SE面板与比较结果。

计划和实际评价固定源码、依赖、非参数结构、标的、窗口、截止日、资金、费用场景、价格单位、基准和频率口径。
同时核验 SRT 实际执行政策、订单能力及决策时间规则，不能通过参数切换执行契约。
参数导致的预热起点变化允许存在；策略原始输入用已固定的 DFLS 准备引用，在中心与子候选共同日期范围内
通过公开 `Dataflows.fetch` 核对来源、原始值及时间契约。除起点与预热所需最小观测／交易日数量外，
输入源请求须相同；共同范围使用两者中较小的历史覆盖要求，范围不足或数据失败明确拒绝。
中心范围以外新增的预热内容保留其准备身份，不能据共同范围校验声称已与不存在的中心区间逐值复验。
这些校验不调用实时供应商重新获取数据，也不比较整个可能随参数变化的派生输入哈希。

`build_assessment_evidence` 把已认证点绑定传给 SE；缺失或失败账户仍按实际状态处理，不能填零。
阶段四 `CandidateAssessmentDelivery.parameter_plans` 显式引用计划。交付浅快照计划及其映射／约束材料，
核对实际中心请求、全部规定父子关系和保存账户的点身份，并在 `FULL` 范围重算 SE。
发布后的校验读取交付快照，不依赖实验工作目录、原计划材料文件或可变源码。一次调用内按完整身份、位置及校验范围复用已完成节点的递归展开和语义计算；循环检测独立维护，每次引用仍认证当前文件，结束前再次核对输入。不同调用不复用成功状态。`validate_delivery`返回`stats`记录不同交付数、引用访问、展开、语义复用、文件哈希次数/字节量及耗时；统计不进入交付身份。
平台只认证声明、身份及确定性计算；坐标业务含义、映射合理性及研究授权由 RSCH 负责。

## 7. 五阶段交付

`assemble_delivery(repository, DeliveryDefinition, DeliveryContent, *, resources=None, on_progress=None) -> DeliveryAssemblyResult` 直接接受强类型数据。
返回值包含 `receipt: DeliveryReceipt` 和 `validation: DeliveryValidation`；后者是包含安装后完整性复核的本次 `FULL PASS`，无需紧接着再调用一次完整校验。
同内容修订的重复组装也重新执行 FULL。后续独立调用 `validate_delivery(..., resources=None, on_progress=None)` 时重新读取当前文件，绝不以历史 PASS 代替认证。
两个入口的独立账户认证默认采用 `ExecutionResources` 的本机 70% 逻辑核预算，显式资源可覆盖；单项认证直接执行。
认证缓存只在本次调用内保存按 SHA-256 标识的必要事实，每次消费仍核验文件当前字节和账户引用所属实验；最终复核覆盖前驱及公开副本。
`DeliveryValidationProgress` 回调报告 `PACKAGE_LOAD`、`AUTHENTICATION`、`RECOMPUTATION`、`FINAL_RECHECK` 阶段、完成数量及累计墙钟耗时。
`PACKAGE_LOAD` 在读取每个交付包之前立即发出；`package_load_seconds` 累计包封装读取、清单哈希与强类型解析的墙钟时间，包含失败读取，排除递归前驱、账户认证和 SE 复算。
`DeliveryValidationStats` 记录认证墙钟时间（含并行进程启动及结果传输）、SE 复算时间、最终复核时间、认证账户数和缓存复用数；阶段数值不包含其他序列化及 I/O，不将这些局部计时之和称为端到端时间。
`file_read_task_seconds` 和 `file_hash_task_seconds` 是校验路径的主进程及工作进程逐项文件读取／哈希累计耗时，含在认证与最终复核阶段内；并行任务累计时间不可相加或当作墙钟耗时。
这些执行统计和组装返回包装不写入交付文件，不改变交付 schema 或内容身份。
研究员提供结论、必要事实、解释、人工报告和关联证据，自主组织实验过程。
平台核验结论与已声明证据的存在、身份、完整性及契约一致性，无法判断研究结论是否正确。
研究方法、证据是否充分及结论解释由 RSCH 负责。

`DeliveryContent` 必须以关键字参数提供非空字符串 `report`。RSCH 决定报告内容和组织方式，
平台将其 UTF-8 字节原样写入 `report.md`；目前不提供报告模板或自动生成报告。
报告使用的额外材料通过 `evidence: tuple[EvidenceRef, ...] = ()` 显式关联，
与内容契约中的证据一起核验和浅快照；平台不会从报告文字自动提取证据引用。

所有位置上显式声明 `schema="account_evaluation"` 的 `EvidenceRef` 都须通过账户认证，
包括组件测试、顶层 `DeliveryContent.evidence`、`SearchSummary.evidence` 和候选评价引用。
账户仅接受 schema 7，认证请求与结果身份、保存账本及数值一致性；不支持的版本明确拒绝。
`INTEGRITY` 和 `FULL` 均执行此认证，不重跑策略。普通材料仍检查归属、路径及文件哈希，
平台不会扫描材料 JSON 或 Markdown 中嵌套的账户声明；支撑正式账户结论的引用必须直接纳入强类型交付。
同批次可以复用其他实验账户，但账户内来源必须与该引用自身的实验身份一致；
`CandidateEntry.evaluations` 还须匹配声明候选的身份及 `evaluation_ids`。

未登记原型可通过现有评价与发布 API 形成正式账户，不要求先登记候选。
RSCH 应用普通材料显式保存完整参数、源码文件及依赖，并直接关联所需材料引用；账户身份哈希本身不构成原型恢复包。
组件信息诊断和否定结论仍可使用普通材料，不要求每项测试都产生账户。
账户认证不判断组件有效性、基线与变体是否只改变一个因素，或研究目标是否达成。

证据不合法时，`assemble_delivery` 抛出 `DeliveryValidationError`，不留下本次未完成的正式修订；
`validate_delivery` 返回 `FAIL` 及 `DeliveryIssue`。错误参数类型仍抛出 `TypeError`，
同修订不同内容仍抛出 `DeliveryConflictError`。进入引用与账户认证后的错误分类如下；
初始证据复制、交付包清单等前置检查失败时，仍报告各自阶段的错误，例如 `ASSEMBLY_FAILED` 或 `DELIVERY_FILES`：

| 错误码 | 含义 |
| --- | --- |
| `EVIDENCE_OWNER` | 引用属于其他批次 |
| `EVIDENCE_HASH` | 当前证据字节与引用哈希不符 |
| `EVALUATION_REFERENCE` | 不支持的账户版本、账户来源不符，或声明的运行编号不存在 |
| `ACCOUNT_AUTHENTICATION` | 账户 JSON、请求、账本或结果认证失败 |
| `CANDIDATE_CONFLICT` | 账户候选身份与交付声明不一致 |

单个故障的分类不因串行或并行认证改变；多个故障并存时不保证首先返回哪一个。
工作进程失败明确失败，不自动回退到串行或普通材料校验。历史交付原件保持不变；
此前仅通过文件哈希检查的非法账户附件会在新的校验中被拒绝，不自动改写历史回执或研究资格。

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
from czsc_trader.application import assemble_delivery
from czsc_trader.research_tools import (
    CandidateEntry, CandidateIdentityRef, CandidateSet, DeliveryDefinition,
    DeliveryStage, DeliveryContent, DeliveryStatus, ValidationStatus,
)

candidate_set = CandidateSet(
    candidates=(CandidateEntry(CandidateIdentityRef(registration.key, registration.content_sha256),
                               "按实际机制填写收益假设", "提交自检", (evaluation_reference,)),),
    handoff=(registration.key,), searches=(), conclusion="交接该候选进行自检与比较",
)
assembled = assemble_delivery(
    repository, DeliveryDefinition(research.batch, DeliveryStage.CANDIDATES, revision=1),
    DeliveryContent(
        candidate_set, DeliveryStatus.COMPLETE, facts=(), explanations=(),
        report="交接该候选进行自检与比较。关联账户评价支持本次交付，后续结论待自检完成。",
        evidence=(),
    ),
)
receipt, checked = assembled.receipt, assembled.validation
if checked.status is not ValidationStatus.PASS:
    raise RuntimeError(checked.issues)
```

完整交付位于 `research/<批次>/assets/deliveries/<阶段>/<修订>/`，包含 `delivery.json`、`report.md`、`receipt.json`、
选定证据的 `evidence/` 浅快照及必要的决定／检验 `support/`。
公开目录 `research/<批次>/deliveries/<阶段>/<修订>/` 保存对应的 `report.md` 和 `receipt.json`。
发布与校验核对两处报告及回执的字节一致性；完整包只包含已选定材料。
阶段一至四的`DeliveryDefinition`、`DeliveryReceipt`和`delivery.json`使用schema 8；新`INSPECTION`三处均使用schema 9且`predecessors=()`。
旧阶段五schema 8仅在概览展示有限元数据并列出限制，显式交付校验拒绝，不解释为新版通过，不自动迁移历史原件。账户评价证据使用 schema 7，请求身份使用 schema 6，`StrategyVersion` 继续使用 schema 5。
修订号在“批次＋阶段”内唯一，同内容重复发布复用，冲突拒绝覆盖，失败不留下可见的半成品修订。
前驱为同批次的 `DeliveryReference`；同阶段前驱只能是更早修订。

`PARTIAL/BLOCKED` 须列明未完成项，完整交付不能同时声称有未完成项。
校验默认 `DeliveryValidationScope.FULL`，核对文件身份和关联事实，并重算阶段四 SE 结果；
`INTEGRITY` 仍核对文件、引用及保存事实，但不重新执行阶段四 SE 自检和排序计算。两者都不重跑整个研究过程。
两种范围均核验 `report.md` 与提交的 `report` 字节一致；该检查不判断文字解释或研究结论的正确性。
阶段四使用 SE 自检公式 `research-assessment-v5` 与排序公式 `research-ranking-v3`，
按中心收益和回撤分层、同层稳健性优先及交易频率最后比较；指标、分箱与频率口径见
[SE 比较政策](../../packages/strategy_evaluator/README.md#比较请求与政策)。
盈利年份合并频率由已保存基准净值与实际退出日计算，频率硬门仍须绑定已确认的目标及精确窗口。
旧自检或排序字段集合明确拒绝，历史原件保留，不自动改写或重算历史排名。
阶段五继续核验实际决定、检验及冻结状态；交付快照不取代运行发布和批准事实。

### 完整目标集合的交付绑定

阶段一`PerformanceRequirement.targets`接受SE的`ResearchTarget`、`FrequencyCoverageTarget`和
`ParameterGroupTarget`。标准成本、压力成本、条件分支、联合点数及内层全部点条件都属于获批目标内容。
具体字段、完整标准构造示例、逐项输出及精确计算口径见[SE验收契约](../../packages/strategy_evaluator/README.md#经济频率及稳健性验收)。

| 入口 | 输入要求 | 输出及检查 |
| --- | --- | --- |
| `assemble_delivery`阶段一 | 在`ResearchMandate.items`的`PerformanceRequirement.targets`保存完整目标；每项有真实`ConfirmationRecord`；基准使用`BenchmarkRequirement` | 保存目标及确认引用，供后继交付精确绑定；不推断确认文本语义 |
| `assemble_delivery`阶段四 | `CandidateAssessmentDelivery`携带自检请求/面板、比较请求/结果、账户正式证据，以及每个外层目标的`TargetMandateBinding(target_id, mandate_item_id)` | 所有已确认绩效目标必须完整保留且值一致，包括参数组内层；漏项或改阈值拒绝 |
| `validate_delivery(..., scope=FULL)` | 当前schema交付引用及其前驱 | 认证账户、参数设计和阶段一绑定，再用`assess_candidates/compare_candidates`复算覆盖事实、逐点和压力验收及排序；不一致拒绝 |

两项频率验收共用`ResearchTargets.frequency_window_days`，在已确认的执行条目中保存
`NumericRequirement("frequency_window_days", "sessions", lower=60.0, upper=60.0)`，
由`frequency_window_item_id`引用；`benchmark_item_id`绑定已确认基准。
自检协议显式设置`frequency_min_closed_cycles=3`，参数协议规定32点；不要用排序频率替代双频率目标。
`target_bindings`只绑定参数组外层ID，内层条件随整个组的强类型值精确核对。

技术校验`PASS`表示交付真实、可复算；研究验收读取`comparison.rows[*].acceptance_status`及
`target_checks`，推荐排序还须满足可比性和完整证据政策。研究未达标或证据不足的真实报告可正常留存，
不能将保存成功当作研究通过。`INTEGRITY`不重算数值，不得替代FULL声称复算成功。

本次版本升级拒绝schema 7交付及旧自检/排序字段，不实现双版本读取或自动迁移；旧原件保持原位。
已有schema 7账户证据可在新合同下显式引用；继续旧研究须获准生成新交付，不能直接接续旧交付链。
StrategyVersion和运行发布合同不变，不更改已冻结策略、SM状态或PTE运行行为。

### 交付校验与运行统计

`validate_delivery`返回`DeliveryValidation`，范围与技术成功状态按上文处理。共享前驱在单次调用内避免重复展开，文件完整性及结束前的一致性复核保持；不同调用不复用文件校验结果。

返回`stats`：`unique_deliveries/reference_visits/recursive_expansions/semantic_reuses/files_hashed/bytes_hashed/elapsed_seconds`。哈希计数统计交付服务显式执行的文件内容哈希，不含下游库内部操作系统读取量；最终复核包含在计数和耗时内。运行统计不参与交付身份或业务结果相等性。发布前驱检查沿用相同校验保证；运行统计不代表研究充分性或阶段批准。

## 8. 技术检验、用户决定与冻结

阶段五只回答两个问题：同一技术输入下，Candidate和最终格式StrategyVersion是否行为等价；该发布包能否在隔离环境通过真实PTE部署加载、决策、订单、账户与恢复链路。研究判断及阶段推进由RSCH负责。

1. `record_research_decision`保存真实选型：`CandidateSelectionSubject(candidate, content_sha256, registration_sha256)`，schema 2，不绑定阶段四回执。
2. `describe_inspection_environment(repository)`读取实际执行的平台源码清单、构建哈希、依赖版本及SRT/PTE契约，用于构造PTE环境要求。
3. 构造`CandidateInspectionRequest(candidate, selection, research, experiment, target, protocol, replays, data_kind, additional_files=(), remaining_risks=())`，调用`inspect_candidate(repository, request, control=InspectionControl(...))`。
4. 交付两目标结果、精确`FreezePlan`及`InspectedRelease`、风险和待决定事项；取得用户对该报告、计划和版本的冻结批准。
5. 调用`freeze_candidate`，以`get_freeze_result`核实事务；只有`COMMITTED`表示已冻结。部署、账户和生产生效分别授权。

公共输入从`czsc_trader.application`导入；控制及环境从`strategy_runtime.inspection`导入；PTE场景从`paper_trading_engine.inspection`导入。

| 类型 | 核心字段 |
| --- | --- |
| `FreezeTarget` | version、parent_version、change_summary、date类型selection_data_cutoff和forward_start |
| `InspectionReplay` | coordinate、候选StrategyInputBinding、完整BacktestExecutionData、initial_cash、one_way_cost、可选baseline |
| `InspectionProtocol` | `candidate-inspection-v2`、`ECONOMIC_V1`、float_tolerance、PteInspectionProtocol |
| `InspectionControl` | 总timeout_seconds、max_workers、cancelled、on_progress；默认预算为本机70%逻辑核，实际并发受独立任务数限制 |
| `CandidateInspectionReport` | schema 2；run_id、owner、origin、selection、request/protocol/environment引用、plan/release、behavior_equivalence、pte_runtime、measurements、remaining_risks |
| `InspectedRelease` | 最终version_record、manifest、文件闭包，以及release_sha256和package_sha256 |
| `CandidateInspectionDelivery` | inspection报告引用、decisions、freeze、pending_decisions；无source_assessment |

回放输入必须为显式准备的DFLS资产，包含日历、行情、价格单位及市场规则；不需要基准收益、SE排序或研究历史档案。候选加载核验登记元数据、payload、源码及依赖，不解引用登记中的研究来源和派生证据。原回测baseline缺省时保存`NOT_REQUESTED`辅助事实；提供时精确核对身份、窗口、输入和执行条件并比较账本，差异使目标A失败。

先构造最终schema 5版本及manifest 1发布包，再用同一包做两目标检验。`FreezePlan` schema 2不含研究历史闭包；manifest的既有`candidate_package_hash`字段绑定plan哈希。冻结直接提交报告保存的同一版本与发布字节，既有冻结事务请求ID、幂等性和状态保持。

目标A通过正常SRT/TXE路径运行候选及发布实现，比较信号、决策、订单、成交、账户、交易与观察事实。只归一化纯运行身份；离散数量、状态、时点严格一致，明确金融浮点字段才适用容差。目标B使用正常PTE业务组件和独立的离线成交渠道；检查进入／持有／退出、无成交或部分成交、重复决定／回报、重启后与连续运行一致，以及适用故障。多档持仓调整按能力声明验证。测试许可、数据库及部署回执受隔离路径和包身份约束，普通PTE入口拒绝技术检验数据库。

检验提供PREPARE、EQUIVALENCE、PTE、PERSIST、FINALIZE进度；长回放和PTE场景使用可终止子进程。取消或总超时先停止并等待worker退出，再保存已完成事实和未完成原因。回调错误明确失败。发布失败抛`InspectionPublicationError(phase, partial_evidence, report_reference, message)`，不得把未发布结果当作已交付。

技术报告独立保存于`research/<策略>/assets/evidence/<实验>/inspection/<sha256>`。临时运行位于`.tmp/strategy-inspection/<run_id>/`，包含候选工作区、隔离repository、私有DFLS输入、场景状态和进度；成功后清理，失败可保留诊断。输入复制通过DFLS公开fetch/prepare完成；`content_mapping.role`是规范DataRequest的SHA256键，用来区分同名角色的不同窗口，源与隔离内容哈希须一致。实际数据来源与元数据随技术证据保存。请求必须显式提供`InspectionDataKind.HISTORICAL/SYNTHETIC`，标记为调用方声明；PTE离线成交渠道始终标为SYNTHETIC，不能作为真实账户收益。

报告只有两目标均PASS且plan/release/environment完整才PASS。技术故障保存FAIL，未启动目标为NOT_RUN，取消／超时或覆盖不足为INCOMPLETE；无计划、缺证或未通过均不能冻结。`INSPECTION`交付不递归研究前驱；概览识别合法`inspection/<hash>`证据但不把它计入账户数量。旧八项检验报告、旧选型与旧InspectionReplay执行接口已经移除，历史原件保持不变。

冻结返回`NOT_FOUND/IN_PROGRESS/COMMITTED/FAILED/UNKNOWN`。同请求同内容复用既有状态，同请求不同内容或版本冲突拒绝；不自动换号或重试。冻结初始资格仍是`RESEARCH`。

更完整字段、API和目录表见[阶段五公共契约](../../docs/superpowers/specs/2026-10-22-stage5-public-contracts.md)。

## 9. 目录与保存责任

精确的路径指定及落盘模块见 [研究导航](../../research/README.md#批次空间与落盘职责)。
批次 DFLS 空间、候选快照和已发布证据属于正式引用的一部分；数据资产按实际 Git 规则单独保存。
`.tmp/`、准备引用或 Git clone 均不能替代缺失的数据资产。正式交接说明引用、资产位置及同步责任。

旧实验、旧交付和旧候选原件保持原位，继续研究时按授权生成当前契约证据，见 [历史实验说明](../../experiments/README.md)。
运行策略加载核验自己的版本、发布包与部署身份，运行合同独立于可修改实验材料。
