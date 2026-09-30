# 策略候选包

> 旧流程参考：新研究流程以`StrategyCandidate`贯穿阶段三至五，已取消独立候选包对象，见[RSCH Agent](RSCH_AGENT.md)。本文件仅用于阅读历史候选包及现有工具依赖，不作为新研究的交付要求。原流程正文保留如下。

[策略研究员Agent](RSCH_AGENT.md)负责实现并交付完整候选包；
[首席投资官Agent](CIO_AGENT.md)通过平台工具完成候选审查、体检，并在当前任务授权范围内
冻结和部署到SRT。

## 存放位置

候选包必须存放在：

```text
research/SXXX/candidates/SXXX-Cnnn/
```

平台受理后，将经过验证的原始内容封存到：

```text
strategies/SXXX/candidates/SXXX-Cnnn/package/
```

策略研究员不得直接修改治理区内容。

## 目录结构

```text
SXXX-Cnnn/
├─ candidate_submission.json
├─ candidate_snapshot.json
├─ runtime_binding.json
└─ runtime/
   └─ strategy_runtime/
      ├─ strategies/
      │  └─ sxxx_cnnn.py
      ├─ charts/
      │  ├─ __init__.py
      │  └─ sxxx_cnnn.py
      └─ resources/
         └─ ...
```

`runtime/strategy_runtime/`使用可独立加载的Python包形态保存源码闭包。冻结后，平台把它原样
复制到`strategies/SXXX/releases/vN/runtime/strategy_runtime/`；`strategy deploy`只在
`strategies/deployments/`创建经过校验的部署凭据。策略源码不会写入
`packages/strategy_runtime/`，SRT始终是策略无关的运行引擎，并从策略治理区加载已部署版本。

## candidate_submission.json

```json
{
  "schema_version": 1,
  "candidate_snapshot": "candidate_snapshot.json",
  "runtime_binding": "runtime_binding.json",
  "runtime_root": "runtime/strategy_runtime",
  "files": {
    "candidate_snapshot.json": "<sha256>",
    "runtime_binding.json": "<sha256>",
    "runtime/strategy_runtime/strategies/sxxx_cnnn.py": "<sha256>",
    "runtime/strategy_runtime/charts/__init__.py": "<sha256>",
    "runtime/strategy_runtime/charts/sxxx_cnnn.py": "<sha256>"
  },
  "package_hash": "<sha256>"
}
```

`files`必须覆盖候选包内除`candidate_submission.json`以外的全部文件。`package_hash`是去掉
`package_hash`字段后，对完整manifest对象计算的规范JSON SHA-256。

## candidate_snapshot.json

```json
{
  "schema_version": 1,
  "strategy_id": "SXXX",
  "candidate_id": "Cnnn",
  "source_experiment": "experiments/SXXX/<experiment-id>",
  "strategy_payload": {
    "runtime": {
      "module": "strategy_runtime.strategies.sxxx_cnnn",
      "qualname": "SXXXCandidate",
      "contract_version": 1,
      "source_files": ["strategies/sxxx_cnnn.py"],
      "source_sha256": "<sha256>"
    },
    "parameters": {}
  },
  "data_contract": {"requirements": []},
  "execution_policy": {"policy_type": "FROZEN_RULE"},
  "research_claims": {"summary": "候选策略主张"},
  "candidate_hash": "<sha256>"
}
```

`candidate_hash`是去掉`candidate_hash`字段后，对完整候选快照计算的规范JSON SHA-256。
`strategy_payload`中的实现和参数是体检、冻结及部署过程中保持不变的可执行身份。

## runtime_binding.json

```json
{
  "schema_version": 1,
  "candidate_id": "SXXX-Cnnn",
  "source_files": [
    "strategies/sxxx_cnnn.py"
  ],
  "implementation_sha256": "<sha256>",
  "install_files": [
    "strategies/sxxx_cnnn.py",
    "charts/__init__.py",
    "charts/sxxx_cnnn.py"
  ],
  "charts": {
    "module": "strategy_runtime.charts.sxxx_cnnn",
    "qualname": "SXXXCharts",
    "contract_version": 1,
    "source_files": [
      "charts/sxxx_cnnn.py"
    ],
    "source_sha256": "<sha256>"
  },
  "observation": {
    "contract_version": "strategy_observation.v1",
    "series": [
      {
        "key": "score",
        "label": "策略分数",
        "value_field": "score",
        "guides": [
          {"key": "entry_threshold", "label": "入场阈值", "value": 0.5}
        ]
      }
    ]
  }
}
```

策略实现必须继承`StrategyImplementation`，同时实现`from_candidate`和`from_release`。候选
`strategy_payload.runtime`声明的模块、类、源码闭包和源码哈希必须与binding一致。

图表类必须实现：

```python
class SXXXCharts:
    def render_backtest(self, context): ...
```

该方法生成TDR回测图。图表代码只能读取平台传入的context，不得直接读取TDR输出目录、PTE
数据库、券商接口或SRT私有准备目录。

该方法接收`strategy_chart.v1`上下文。平台负责提供策略身份、窗口、独立行情、策略输出、
执行账本和渲染选项；策略图表代码负责把这些事实解释为本策略的分面、阈值、信号和状态语义，
并返回完整HTML文档。候选审查会校验图表源码闭包和哈希；缺少契约、身份不一致或渲染失败
都会直接阻断审查或回测，不存在平台旧图回退路径。

`observation`只声明策略决策中可观察序列、字段和阈值的展示无关语义。SRT在生成冻结策略决策
时把它物化为`strategy_observation.v1`事实；PTE只消费已部署冻结版本的决策事实，独立调用DFLS
获取行情，并在PTE后台线程中生成`pte_forward_chart.v1`前瞻观察图。PTE不读取未冻结候选包，
候选包也不提供前瞻图HTML、JavaScript或Plotly实现。

## 首席投资官操作

最终EvaluationMandate由CIO维护在候选包目录之外，避免与RSCH提交的不可变候选包混合。受理、
体检、冻结和部署的授权边界见[CIO Agent描述](CIO_AGENT.md)。

```powershell
.\.venv\Scripts\czsc-trader.exe candidate review `
  --package research/SXXX/candidates/SXXX-Cnnn `
  --mandate research/SXXX/mandates/SXXX-Cnnn.json

.\.venv\Scripts\czsc-trader.exe candidate evaluate SXXX-Cnnn

.\.venv\Scripts\czsc-trader.exe candidate freeze SXXX-Cnnn `
  --change-summary "策略版本说明"

.\.venv\Scripts\czsc-trader.exe strategy deploy SXXX-vN
.\.venv\Scripts\czsc-trader.exe strategy list SXXX
.\.venv\Scripts\czsc-trader.exe strategy info SXXX-vN
```

`candidate freeze`只在策略治理区生成不可变策略版本包。`strategy deploy`完整校验版本包、
运行时、回测图和前瞻观察语义后写入SRT部署凭据；此后SRT才能从治理区加载该版本，且该版本
才能被`strategy list`和`strategy info`查询。以上`strategy`命令只覆盖SRT部署状态，不承担
候选包管理或PTE账户部署。
