# TDR研究工具使用说明

研究员统一调用Python API；用户CLI仅提供`backtest run`。阶段审批、选型与冻结权限见[RSCH契约](../../research/RSCH_AGENT.md)。公开API不代表获准写入、冻结或部署。

## 1. 公共契约与能力导航

先读公共导出，再沿导入阅读类型、实现和契约测试。第三方库的资源默认值见[研究库说明](../../docs/RESEARCH_LIBRARIES.md)。

| 任务 | 公共入口 | 说明 |
| --- | --- | --- |
| 完整业务操作 | [application](application/__init__.py) | 选择性导出现有应用服务，不重复包装实现 |
| 正式实验与账户评价 | [research_tools](research_tools/__init__.py) | REX受管上下文、预算及执行追踪 |
| 回测底层契约 | [backtesting](backtesting/__init__.py) | 请求、策略快照、执行数据及回放 |
| 研究身份 | `create_research_batch`、`update_research_intent` | 写入研究登记及交接资料，调用前取得授权 |
| 数据准备与校验 | `PrepareDataCommand`、`prepare_data`、`validate_data` | 准备行情可能联网并写入数据目录 |
| 目录与模板 | `validate_catalog/list_catalog/show_catalog`、`validate_templates/list_templates/show_template/instantiate_template` | 完整模板操作包含跨FSC绑定校验 |
| 档案校验 | `validate_archives` | 只读验证；不重签原件 |
| 版本查询与部署 | `list_installed_strategies`、`strategy_info`、`deploy_strategy` | 部署单独授权；不操作PTE账户 |

## 2. 公共输入与执行约定

- `RepositoryContext.discover`只定位仓库路径，不加载凭据；数据入口按其签名接收仓库环境文件。
- API输入遵循公开类型；现有文件化API仍接收JSON文件路径，不要求经由CLI。
- 应用服务返回`CommandResult`对象，调用者读取状态、结果、制品及警告；失败使用明确异常。
- 路径相对性按接口签名处理。临时工作空间放在`.tmp/`，不得覆盖封存实验。
- API返回成功不替代研究结论判断、用户批准或生产授权。

## 3. 实验预检与执行

实现REX的`ResearchExperiment`并冻结源码绑定。正式执行前完成合成预检；详见[REX](../../packages/research_experiment/README.md)。

```python
from pathlib import Path
from czsc_trader.application import RepositoryContext, preflight_experiment_archive

context = RepositoryContext.discover(Path.cwd())
report = preflight_experiment_archive(
    context, context.root / "experiments/SXXX/YYYYMMDD_SXXX_EXNN",
    max_workers=1, max_evaluations=100,
)
```

路径和预算是示例，须替换为已批准的实际值。前驱通过`PredecessorEvidence`绑定回执哈希。

实验使用`load_experiment`加载，按模式通过`create_formal_experiment_context`或`create_experiment_context`建立上下文，再调用`execute_experiment`。正式评价使用`context.evaluation.evaluate(request)`，保留身份、截止日、并发和次数预算校验。执行回执不允许由研究实现伪造。

## 4. 策略评价与回测

| 用途 | API | 输出 |
| --- | --- | --- |
| 实验内账户评价 | `context.evaluation.evaluate(EvaluationRequest)` | `EvaluationResult`，含各窗口／成本场景的账户、基准及身份 |
| 文件化评价及发布 | `evaluate_research_request(context, input_path)` | 实验`artifacts/evaluation/`及文件哈希 |
| 候选或版本完整回测 | `run_backtest(context, strategy, request)` | 账户、指标、审计、报告及图表，位于返回的`artifacts.output_dir` |

`run_backtest`接受SRT的`StrategyCandidate`或SM的`StrategyVersion`，请求统一使用`BacktestRequestV2`。候选图表描述通过`chart_descriptor`显式传入；版本使用认证后的原图表，不允许覆盖。两类对象共用底层回放流程，保留各自身份。

当前版本回测仍需要已有SRT部署凭据；缺少时明确失败，不自动部署。移除该依赖属于后续改造。候选持久化解析尚未实现，用户CLI暂仅支持已登记版本；候选通过API传对象，不自动登记。

```python
from czsc_trader.application import BacktestRequestV2, run_backtest
# context、strategy、start、end来自已核对的仓库、对象与获准窗口。
result = run_backtest(
    context, strategy,
    BacktestRequestV2("588080.SH", "etf", start, end, 1_000_000),
)
```

用户CLI从仓库根目录执行：

```powershell
.\.venv\Scripts\czsc-trader.exe backtest run `
  --strategy SXXX --strategy-version v1 `
  --symbol 588080.SH --asset etf `
  --start 2026-07-01 --end 2026-09-28 --init-cash 1000000
```

核对`audit_status`及审计文件，不能仅看命令PASS。评价／回测不替代正式REX实验回执，也不自动产生完整阶段报告。

## 5. 证据读取与失败语义

- 前驱通过REX `load_experiment_input`及可信的`expected_receipt_sha256`读取。
- 档案通过`validate_archives(context, archive)`或`all_archives=True`校验，二者只能选一。
- 文件化评价重复发布校验既有身份及文件哈希；不同结果不得覆盖旧证据。
- 重复调用可能重新准备数据和执行计算，不推定无副作用。
- 数据截止日缺口、输入身份不符、未完成审计均显式报告，不静默缩窗或降级。

## 6. 冻结与历史治理

旧候选包、CIO审查及冻结执行入口已移除；新闻抽取能力已移除。新候选检验、批准绑定及冻结入口仍待CAP-07实现，当前不可执行冻结。

历史版本、发布清单、批准记录和凭据原件保持不变。SM内部只读解码器用于历史治理验证，不提供送审、裁定或冻结写入。发布清单中的历史字段继续参与哈希验证，不恢复候选包对象模型。

## 7. 使用与维护边界

API收敛不改变模块职责；数据、统计及策略计算继续使用所属模块的公开能力。研究员不得使用私有函数、CLI子进程或手工治理写入绕过契约。安装依赖、部署及生产写入分别取得授权。
