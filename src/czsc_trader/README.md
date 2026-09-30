# TDR研究工具使用说明

本文面向策略研究员Agent，按“公共契约 → 任务能力 → 结果处理”说明工具使用。研究目标、阶段审批与冻结权限见[RSCH Agent](../../research/RSCH_AGENT.md)；平台维护见[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。本文不授予数据、治理区或生产操作权限。

## 1. 能力导航与公共入口

先阅读[研究工具公共导出](research_tools/__init__.py)及[回测公共导出](backtesting/__init__.py)，沿导入核对契约和实现。CLI参数以[主解析器](cli/main.py)和[研究命令解析器](cli/research_commands.py)为准。

| 任务 | 现有入口 | 详见 |
| --- | --- | --- |
| 实验预检 | `experiment preflight` / `preflight_experiment` | 第3章 |
| 实验执行 | 上下文工厂 + `execute_experiment` | 第3章 |
| 策略评价与回测 | `context.evaluation.evaluate`、`research evaluate`、`backtest run`及回测API | 第4章 |
| 证据读取与档案校验 | `load_experiment_input`、`archive validate` | 第5章 |
| 新流程技术检验与冻结 | 待CAP-07增强，当前无新流程入口 | 第6章 |

TDR组织跨模块调用、评价和证据输出；SRT提供策略计算，TXE提供账户事实，SE提供数值评价。正式研究按RSCH要求经过REX预检与执行留证。单独调用`research evaluate`或`backtest run`不生成完整REX实验回执，也不替代正式实验流程。

统一阶段产物组装、候选身份治理及阶段四自检组合仍有待实现能力，状态见[平台能力占位清单](../../research/RSCH_AGENT.md)。

## 2. 公共输入与执行约定

| 项目 | 使用约定 | 契约或说明 |
| --- | --- | --- |
| 研究对象与身份 | 实验ID、候选身份和冻结版本各按对应契约传入，不相互替代 | [REX](../../packages/research_experiment/README.md)、[候选身份占位](../../docs/RESEARCH_DELIVERY_CONTRACT.md) |
| 源码与数据 | 使用已校验绑定及受管数据；调用者登记来源身份 | [SRT](../../packages/strategy_runtime/README.md)、[DFLS](../../packages/dataflows/README.md) |
| 工作目录 | 本文CLI示例从仓库根目录执行；Python路径按实际调用签名传入 | [CLI解析器](cli/main.py) |
| 写入范围 | 实验工作空间位于`.tmp/`；评价和回测发布位置见各能力章节 | [实验档案说明](../../experiments/README.md) |
| 资源配置 | 显式传入资源预算；搜索默认配置不由示例中的单进程设置替代 | [第三方研究库说明](../../docs/RESEARCH_LIBRARIES.md) |
| 交易与账户 | 明确窗口、初始资金、成本、基准及完整账户口径 | [TXE说明](../../packages/trading_execution_engine/README.md) |

`SXXX`、实验路径、版本、日期和资源预算均为示例输入，执行前替换为已批准且实际存在的值。所需数据访问与文件写入须在授权范围内；不得写入已封存档案。

`research create`、`research intent update`涉及注册及意图写入，使用前核对授权和[当前命令契约](cli/research_commands.py)。安装依赖、部署及生产操作分别取得授权，不随评价或回测授权自动开放。

## 3. 实验预检与执行

### 3.1 适用场景

为一个可证伪实验建立可追溯的执行记录。正式模式使用`create_formal_experiment_context`；探索模式使用`create_experiment_context`，两者不可互换。

### 3.2 契约与入口

| 能力 | 公共入口 | 输入 → 输出 |
| --- | --- | --- |
| 源码加载 | REX `load_experiment` | 实验目录及源码绑定 → `LoadedExperiment` |
| 预检 | `preflight_experiment` / `experiment preflight` | 已加载实验、资源及前驱 → 预检报告 |
| 上下文 | 两种上下文工厂 | 定义、资源、工作空间及前驱 → `ExperimentContext` |
| 执行 | `execute_experiment` | 已加载实验及上下文 → `ExperimentResult`及平台执行证据 |

代码入口：[REX公共导出](../../packages/research_experiment/src/research_experiment/__init__.py)、[TDR研究工具公共导出](research_tools/__init__.py)。

### 3.3 输入与前置条件

- 实现REX的`ResearchExperiment`，通过`load_experiment`加载源码绑定。
- 绑定版本、定义版本及合成预检要求见[REX说明](../../packages/research_experiment/README.md)。
- 资源预算和前驱身份必须与实验协议一致。
- `ExperimentResources`声明进程预算、种子及内部线程预算；参数搜索还须声明`max_evaluations`。
- 探索上下文按签名提供获准适配器；正式上下文使用平台受管适配器。

### 3.4 最小调用示例

预检命令中的单进程仅用于说明调用；搜索预算和前驱参数按REX说明填写。

```powershell
.\.venv\Scripts\czsc-trader.exe experiment preflight `
  --experiment experiments/SXXX/YYYYMMDD_SXXX_EXNN `
  --max-workers 1 --repo-root .
```

正式执行时传入已冻结实验目录、批准的资源及已校验前驱；未指定工作空间时由TDR在`.tmp/`创建。

```python
from pathlib import Path
from research_experiment import (
    ExperimentInput, ExperimentResources, ExperimentResult, load_experiment,
)
from czsc_trader.research_tools import (
    create_formal_experiment_context, execute_experiment,
)

def run_formal(
    repository_root: Path,
    experiment_root: Path,
    resources: ExperimentResources,
    predecessors: tuple[ExperimentInput, ...] = (),
) -> ExperimentResult:
    loaded = load_experiment(experiment_root)
    context = create_formal_experiment_context(
        loaded.definition,
        repository_root=repository_root,
        resources=resources,
        predecessors=predecessors,
    )
    return execute_experiment(loaded, context)
```

### 3.5 输出与写入范围

`execute_experiment`核对源码和定义身份，对新绑定执行预检，在工作空间生成`execution_receipt.json`及`execution_envelope.json`。研究实现不得自行构造平台回执。归档按[实验档案说明](../../experiments/README.md)执行；临时工作空间不等同于已封存档案。

### 3.6 失败与重试语义

加载、预检或模式检查失败时不进入正式执行。执行异常时保留失败输入及已有证据。同一工作空间已有执行回执或封套时，工具拒绝覆盖；此检查不保证实验计算尚未发生，不能把重复调用当成无副作用操作。复算使用新工作空间，研究修订由后继实验承接。

## 4. 策略评价与回测

### 4.1 适用场景

按对象和用途选择入口，再确定请求形式。

| 对象／用途 | 首选入口 | 限制 |
| --- | --- | --- |
| 正式实验内评价候选 | `context.evaluation.evaluate` | 保留实验能力检查、预算及追踪 |
| 文件化候选评价 | `research evaluate` | 使用指定位置的JSON请求，不替代REX实验回执 |
| 已登记冻结版本回测 | `backtest run` | 需要已登记版本及对应SRT部署凭据 |
| 自行编排候选回放 | 回测公共API | 校验候选身份；图表需要有效图表描述 |

### 4.2 契约与入口

| 能力 | 类型与入口 | 代码 |
| --- | --- | --- |
| 账户评价 | `EvaluationRequest`、`EvaluationResult`、`evaluate_strategy`；实验内通过上下文调用 | [研究工具公共导出](research_tools/__init__.py)、[评价实现](research_tools/evaluation.py) |
| 文件化评价 | `research evaluate --input` | [JSON适配器](application/research_evaluation_service.py) |
| 策略回放 | `BacktestRequestV2`、`resolve_candidate_snapshot`、`run_backtest_v2` | [回测公共导出](backtesting/__init__.py) |
| 登记版本回测 | `backtest run` | [CLI解析器](cli/main.py)、[应用服务](application/backtest_service.py) |

### 4.3 输入与前置条件

Python评价请求：

| 请求部分 | 必填内容与口径 |
| --- | --- |
| 身份 | 仓库、实验ID、`StrategyCandidate`、运行绑定 |
| 市场 | 标的、资产类型、开发截止日 |
| 窗口 | `EvaluationWindow`序列，独立窗口与账户切片不得混用 |
| 资金与成本 | 初始资金、`EvaluationCost`序列；`one_way_cost=0.001`表示每侧10bp |
| 执行数据 | `BacktestExecutionData`；受管准备入口见[回测公共导出](backtesting/__init__.py) |
| 基准与执行 | `EvaluationBenchmark`、进程数、频率统计窗口、执行模式 |

完整账户证据使用`FULL`模式。策略绑定、标的、窗口、成本及数据身份须通过当前实现校验；不从历史示例继承未经确认的默认口径。

文件化CLI的JSON结构与Python构造参数不同。请求路径须为`experiments/<策略>/<实验>/evaluation_request.json`，当前字段如下：

| 字段 | 内容 |
| --- | --- |
| `schema_version` / `experiment_id` | 当前版本1；实验ID与所在目录一致 |
| `strategy` | `strategy_id`、`candidate_id`、`strategy_payload`、`runtime_root`、`runtime_binding` |
| `market` | `symbol`、`asset_type`、`development_cutoff` |
| `windows` | 每项含`window_id`、`start`、`end` |
| `capital` | `initial_cash` |
| `costs` | 每项含`scenario_id`、`one_way_cost`、`measurement_tier`；当前CLI要求标准及压力场景 |
| `benchmark` | `benchmark_id`、`kind` |
| `execution` | `mode`、`workers`、`frequency_window_days` |

字段必须与适配器要求精确匹配。源码目录及绑定文件使用实验目录内的安全相对路径。CLI会准备受管执行数据，须具备相应数据与文件写入授权。

`backtest run`解析SM已登记版本，并读取对应SRT部署凭据及源码闭包；仅有未冻结候选ID不足以调用。缺少凭据时报告限制，不因此自行部署。该命令没有`--repo-root`参数，须在正确仓库工作目录执行。

### 4.4 最小调用示例

正式实验内评价候选：

```python
from research_experiment import ExperimentContext
from czsc_trader.research_tools import EvaluationRequest, EvaluationResult

def evaluate_candidate(
    context: ExperimentContext, request: EvaluationRequest,
) -> EvaluationResult:
    return context.evaluation.evaluate(request)
```

文件化候选评价：

```powershell
.\.venv\Scripts\czsc-trader.exe research evaluate `
  --input experiments/SXXX/YYYYMMDD_SXXX_EXNN/evaluation_request.json `
  --repo-root .
```

已登记版本回测：

```powershell
.\.venv\Scripts\czsc-trader.exe backtest run `
  --strategy SXXX --strategy-version v1 `
  --symbol 588080.SH --asset etf `
  --start 2026-07-01 --end 2026-09-28 `
  --init-cash 1000000
```

### 4.5 输出与写入范围

| 入口 | 结果与发布位置 |
| --- | --- |
| 评价API | 返回各窗口／成本场景的信号、账户事实、基准和评价，以及请求、策略、绑定、数据和结果哈希；返回值不自动等同于已发布文件或完整阶段报告 |
| `research evaluate` | 写入实验的`artifacts/evaluation/`；以返回的`artifacts.directory`定位 |
| `backtest run` | 写入`outputs/`下的运行目录；以返回的`artifacts.output_dir`定位 |

文件化评价输出`evaluation_result.json`，以及每个窗口／场景下的`signals.csv`、`decisions.csv`、`orders.csv`、`fills.csv`、`account_daily.csv`、`trades.csv`、`observation.json`和BuyHold证据。

回测输出账户账本、`metrics.json`、`audit.json`、`manifest.json`、`report.md`和`chart.html`等，见[回测实现](backtesting/service.py)。需同时核对返回的`audit_status`及审计文件，不能只看命令`PASS`。

### 4.6 失败与重试语义

- 评价重复执行会校验既有结果身份及文件哈希；结果不同或目录不完整时失败，不应删除旧证据绕过检查。
- 重复评价或回测可能重新准备数据、执行计算或发布运行结果，不能仅凭输入相同认定无写入。
- 数据未达到请求截止日时报告缺口，不静默缩窗。
- 修订窗口、参数或执行口径时保留原证据，按相应身份及后继实验契约处理。

## 5. 证据读取与档案校验

### 5.1 适用场景

为后继实验加载已保留身份的前驱证据，或检查已整理实验档案的结构与文件一致性。校验不证明研究结论正确。

### 5.2 契约与入口

前驱读取使用REX的`load_experiment_input`，见[REX公共导出](../../packages/research_experiment/src/research_experiment/__init__.py)；档案检查使用`archive validate`，见[档案应用服务](application/archive_service.py)。

### 5.3 输入与前置条件

前驱读取提供工作空间及`expected_receipt_sha256`；预期哈希来自此前保留的可信身份记录。前驱清单须与实验协议一致。档案路径和历史文档版本处理见[实验档案说明](../../experiments/README.md)。

### 5.4 最小调用示例

Python调用形式为`load_experiment_input(workspace_root, expected_receipt_sha256=receipt_hash)`；两个参数均须来自已核对的证据记录。

```powershell
.\.venv\Scripts\czsc-trader.exe archive validate `
  --archive experiments/SXXX/YYYYMMDD_SXXX_EXNN --repo-root .
```

### 5.5 输出与写入范围

前驱加载器核对执行封套、结果和文件哈希后返回`ExperimentInput`。档案CLI返回校验数量及实验身份。两种入口读取证据，不修复、重签或覆盖原档案。

### 5.6 失败与重试语义

身份或文件不符时保留原件，先核对路径、预期哈希和封存版本；不得修改哈希使其通过。只读检查可在输入来源核实后重复执行，结果仍取决于实际证据状态。

## 6. 候选技术检验与版本冻结

### 6.1 适用场景

对用户选定候选完成技术检验，并在用户明确批准后冻结。研究员负责执行，用户保留冻结决定权。

### 6.2 契约与入口

**CAP-07待增强：当前无新流程公共入口。**契约需求见[交付与候选契约占位](../../docs/RESEARCH_DELIVERY_CONTRACT.md)及[平台能力占位清单](../../research/RSCH_AGENT.md)。现有旧候选包／CIO治理命令不作为新流程入口。

### 6.3 输入与前置条件

拟议输入为已选定的候选身份、内容指纹、技术检验证据及用户批准记录；检验通过和明确冻结批准是执行冻结的前置条件。冻结不授权部署、PTE操作或生产写入。

### 6.4 最小调用示例

**待实现后补齐。**公共API、CLI名称及参数须经实现验证，不提供虚构命令。

### 6.5 输出与写入范围

拟议输出为检验记录、`StrategyVersion`、冻结回执及来源关联；治理记录和版本文件由获批公共接口写入。实际路径与查询接口待实现后填写。

### 6.6 失败与重试语义

能力缺失时报告受阻。新接口实现后，冻结结果未知须先查询实际状态，再决定后续动作；幂等和重试契约待实现验证，不假定重复调用安全。

## 7. 执行状态与问题处理

| 情形 | 读取位置与处理 |
| --- | --- |
| CLI正常返回 | 默认JSON含`status`、`command`、`result`、`artifacts`、`warnings`；按返回路径取证 |
| CLI失败 | 检查退出码及`error.code`、`error.message`、`error.context` |
| Python调用失败 | 保留异常及输入身份，不伪造回执或成功产物 |
| 数据尚未发布到所需日期 | `backtest_data_not_ready`报告请求截止、已发布截止及首个缺失交易日；不静默缩窗 |
| 评价输入或结果身份不符 | `research_evaluation_failed`；核对绑定、字段和既有证据，修订由后继实验承接 |
| 部分成功或结果未知 | 明确未完成范围，不将技术成功解释为研究通过或冻结批准 |
| 预检失败 | `experiment_preflight_invalid`表示输入或调用校验失败；`experiment_preflight_failed`表示预检报告未通过 |
| 档案不符 | `experiment_archive_invalid`；核对manifest及被引用文件，保留原件 |

先保留错误与身份，再核对输入、依赖和授权，最后按对应能力章节判断可否重试。CLI通用输出与退出语义见[输出实现](cli/output.py)和[错误类型](application/errors.py)。
