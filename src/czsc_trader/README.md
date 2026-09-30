# TDR研究工具使用说明

本文面向策略研究员Agent，说明TDR现有公共能力的调用方式、输入输出及失败语义。研究目标、阶段审批与冻结权限见[RSCH Agent](../../research/RSCH_AGENT.md)；平台维护见[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。本文不授予数据、治理区或生产操作权限。

## 1. 代码入口与工具选择

先阅读[研究工具公共导出](research_tools/__init__.py)及[回测公共导出](backtesting/__init__.py)，沿导入核对契约和实现。CLI参数以[主解析器](cli/main.py)和[研究命令解析器](cli/research_commands.py)为准。

| 任务 | 首选入口 | 输入 → 输出 |
| --- | --- | --- |
| 实验预检 | `experiment preflight` / `preflight_experiment` | 源码绑定、定义、资源与前驱 → 预检报告 |
| 执行正式实验 | `create_formal_experiment_context` + `execute_experiment` | `LoadedExperiment`及上下文 → `ExperimentResult`、回执和产物 |
| 探索实验 | `create_experiment_context` + `execute_experiment` | 探索定义及获准适配器 → 探索结果和执行记录 |
| 实验内候选评价 | `context.evaluation.evaluate` | `EvaluationRequest` → `EvaluationResult` |
| 文件化候选评价 | `research evaluate` | `evaluation_request.json` → 评价账本及身份清单 |
| 已登记冻结版本回测 | `backtest run` | 版本、标的、窗口和资金 → 账本、指标、报告及图表 |
| 实验档案校验 | `archive validate` | 已整理档案 → 校验结果 |

正式研究按RSCH要求经过REX预检与执行留证。单独调用`research evaluate`或`backtest run`不生成完整REX实验回执，也不替代正式实验流程。调用方仍须登记结果来源及归档身份。

以下CLI示例均从仓库根目录执行。`SXXX`、实验路径、版本、日期和资源预算均为占位输入，执行前替换为已批准且实际存在的值。

## 2. 定义、预检并执行实验

### 输入与前置条件

- 实现REX的`ResearchExperiment`，通过`load_experiment`加载源码绑定。
- 按[REX说明](../../packages/research_experiment/README.md)核对绑定版本、定义版本和合成预检。
- 正式实验定义使用`FORMAL`模式；探索模式使用对应上下文。
- 资源预算和前驱身份必须与实验协议一致。
- 工作空间位于仓库`.tmp/`；已封存档案不得作为可写工作空间。

### 预检命令

```powershell
.\.venv\Scripts\czsc-trader.exe experiment preflight `
  --experiment experiments/SXXX/YYYYMMDD_SXXX_EXNN `
  --max-workers 1 --repo-root .
```

搜索预算、前驱证据及预检细节统一见[REX说明](../../packages/research_experiment/README.md)。示例中的单进程用于说明调用；搜索默认配置见[第三方研究库说明](../../docs/RESEARCH_LIBRARIES.md)。

### 正式执行API

下列函数展示调用顺序。调用者传入已冻结实验目录、批准的资源及已校验前驱；未指定工作空间时由TDR在`.tmp/`创建。

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

`ExperimentResources`显式声明进程预算、种子及内部线程预算；参数搜索还须声明`max_evaluations`。`execute_experiment`核对源码和定义身份，对新绑定执行预检，并生成`execution_receipt.json`及`execution_envelope.json`；研究实现不得自行构造平台回执。输出归档按[实验档案说明](../../experiments/README.md)执行，临时工作空间不等同于已封存档案。

## 3. 候选策略评价

### 请求与结果契约

代码见[评价契约及实现](research_tools/evaluation.py)。正式实验中通过上下文调用公共评价实现`evaluate_strategy`，保留能力检查、预算及追踪记录：

```python
from research_experiment import ExperimentContext
from czsc_trader.research_tools import EvaluationRequest, EvaluationResult

def evaluate_candidate(
    context: ExperimentContext, request: EvaluationRequest,
) -> EvaluationResult:
    return context.evaluation.evaluate(request)
```

| 请求部分 | 必填内容与口径 |
| --- | --- |
| 身份 | 仓库、实验ID、`StrategyCandidate`、运行绑定 |
| 市场 | 标的、资产类型、开发截止日 |
| 窗口 | `EvaluationWindow`序列，独立窗口与账户切片不得混用 |
| 资金与成本 | 初始资金、`EvaluationCost`序列；`one_way_cost=0.001`表示每侧10bp |
| 执行数据 | `BacktestExecutionData`；受管准备入口见[回测公共导出](backtesting/__init__.py) |
| 基准与执行 | `EvaluationBenchmark`、进程数、频率统计窗口、执行模式 |

完整账户证据使用`FULL`模式。策略绑定、标的、窗口、成本及数据身份须通过当前实现校验；不从历史示例继承未经确认的默认口径。结果包含各窗口／成本场景的信号、账户事实、基准和评价，以及请求、策略、绑定、数据和结果哈希。API返回值不自动等同于已发布文件或完整阶段报告。

### 文件化CLI

```powershell
.\.venv\Scripts\czsc-trader.exe research evaluate `
  --input experiments/SXXX/YYYYMMDD_SXXX_EXNN/evaluation_request.json `
  --repo-root .
```

该入口的JSON适配契约见[research_evaluation_service.py](application/research_evaluation_service.py)，与Python的`EvaluationRequest`构造参数不同。路径须为`experiments/<策略>/<实验>/evaluation_request.json`，当前顶层字段如下：

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

字段必须与适配器要求精确匹配。运行源码目录及绑定文件使用实验目录内的安全相对路径。CLI会准备受管执行数据，并写入该实验的`artifacts/evaluation/`，须具备对应数据与文件写入授权。

产物包括`evaluation_result.json`，以及每个窗口／场景下的`signals.csv`、`decisions.csv`、`orders.csv`、`fills.csv`、`account_daily.csv`、`trades.csv`、`observation.json`和BuyHold证据。重复执行会校验既有结果身份及文件哈希；结果不同或原目录不完整时失败，不应删除旧证据来绕过检查。

## 4. 已登记版本回测与图表

```powershell
.\.venv\Scripts\czsc-trader.exe backtest run `
  --strategy SXXX --strategy-version v1 `
  --symbol 588080.SH --asset etf `
  --start 2026-07-01 --end 2026-09-28 `
  --init-cash 1000000
```

此CLI解析SM已登记版本，并读取对应SRT部署凭据及源码闭包；仅有一个未冻结候选ID不足以调用。缺少部署凭据时报告限制，不因此自行部署。它没有`--repo-root`参数，须在正确仓库工作目录执行。

未冻结候选的回测API见[回测公共导出](backtesting/__init__.py)：`resolve_candidate_snapshot`校验候选内容身份，`run_backtest_v2`使用`BacktestRequestV2`执行；图表还需要有效的图表描述。正式实验内候选绩效评价优先按第3节执行。

回测产物写入`outputs/`下的运行目录，准确路径读取返回的`artifacts.output_dir`。包括账户账本、`metrics.json`、`audit.json`、`manifest.json`、`report.md`和`chart.html`等；实现见[backtesting/service.py](backtesting/service.py)。需同时核对返回的`audit_status`及审计文件，不能只看命令`PASS`。

## 5. 证据复用与档案校验

前驱读取使用REX的`load_experiment_input(workspace_root, expected_receipt_sha256=...)`，见[REX公共导出](../../packages/research_experiment/src/research_experiment/__init__.py)。预期哈希应来自此前保留的可信身份记录；加载器核对执行封套、结果和文件哈希。前驱清单须与实验协议一致。

```powershell
.\.venv\Scripts\czsc-trader.exe archive validate `
  --archive experiments/SXXX/YYYYMMDD_SXXX_EXNN --repo-root .
```

档案校验验证结构及证据一致性，不证明研究结论正确。旧文档哈希与历史档案的处理见[实验档案说明](../../experiments/README.md)。

## 6. 状态、失败与授权边界

| 情形 | 读取位置与处理 |
| --- | --- |
| CLI正常返回 | 默认JSON含`status`、`command`、`result`、`artifacts`、`warnings`；按返回路径取证 |
| CLI失败 | 检查退出码及`error.code`、`error.message`、`error.context` |
| Python调用失败 | 保留异常及输入身份，不伪造回执或成功产物 |
| 数据尚未发布到所需日期 | `backtest_data_not_ready`报告请求截止、已发布截止及首个缺失交易日；不静默缩窗 |
| 评价输入或结果身份不符 | `research_evaluation_failed`；核对绑定、字段和既有证据，修订由后继实验承接 |
| 部分成功或结果未知 | 明确未完成范围，不将技术成功解释为研究通过或冻结批准 |

`research create`、`research intent update`涉及注册及意图写入，不属于纯评价操作；使用前核对授权和[当前命令契约](cli/research_commands.py)。参数搜索、安装依赖和资源调整遵循[第三方研究库说明](../../docs/RESEARCH_LIBRARIES.md)。

## 7. 技术检验与冻结：待增强

新流程由研究员执行检验，并在用户明确批准后冻结。统一产物组装、候选身份治理、阶段四自检组合、新冻结和查询入口仍按[平台能力占位清单](../../research/RSCH_AGENT.md)及[交付契约占位](../../docs/RESEARCH_DELIVERY_CONTRACT.md)管理。

现有旧候选包／CIO治理命令不作为新流程入口。新公共API及CLI的名称、示例、失败语义须待CAP-07实现验证后补齐；能力缺失时报告受阻。冻结不授权部署、PTE操作或生产写入。
