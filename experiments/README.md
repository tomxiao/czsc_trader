# 实验档案

本目录保存可审计的正式研究实验及其阶段交付。实验按SM策略ID分区；Git跟踪范围与本地制品
的持久保存要求见下文，完整档案不能仅依赖Git恢复。

```text
experiments/
├── S001/
├── S002/
├── S003/
└── S004/
```

新实验路径统一为`experiments/<策略ID>/YYYYMMDD_<策略ID>_EXnn/`。实验ID在整个仓库内
保持唯一；同一策略、同一天从`EX01`开始递增。跨标的验证仍归属于被验证的策略，不按标的
另建目录。

不绑定具体策略、只验证项目级研究方法或工具的实验放在
`experiments/METHODS/YYYYMMDD_<方法>_EXnn/`。这类实验必须声明`DEVELOPMENT_ONLY`，只能
裁决工具适用性和目录定义提案资格，不能生成策略候选、冻结版本或前瞻结论。

每个实验包含四份研究文档、实验专属编排、`artifacts/`机器证据和
`experiment_manifest.json`。清单完成后，实验档案保持不可变；发现错误时创建新实验并声明
继承关系。可重建中间文件和运行缓存统一写入`.tmp/`，不得进入实验档案。

## 阶段交付与候选实体

```text
experiments/<策略ID>/<实验ID>/
├── experiment_binding.json
├── 01_goal.md ... 04_conclusion.md
├── artifacts/                       # 执行回执及声明的机器制品
├── objects/                         # 候选载荷、源码及来源证据
├── deliveries/<阶段>/<修订>/
│   ├── delivery.json
│   ├── report.md
│   ├── receipt.json
│   ├── attachments/
│   └── experiments/                 # 被引用实验的回执与制品副本
└── experiment_manifest.json
```

阶段二至五分别使用`COMPONENTS/CANDIDATES/ASSESSMENT/INSPECTION`，由TDR
`assemble_delivery`写入形成该交付的实验。跨实验汇总仍归属于一个明确实验，使用带哈希的
前驱交付及实验证据引用。修订号在“归属实验＋阶段”内计数，不同实验可以各自从1开始。
阶段一任务书与确认依据位于`research/<策略ID>/mandates/<修订>/`；候选治理登记位于
`research/registrations/`，登记中的来源身份指向本目录的候选实体。

保存顺序为：冻结定义和源码绑定、完成受管执行并保存执行回执及制品、保存交接候选实体并登记、
发布阶段交付、最后生成整个实验的manifest。执行回执完成后不能追加执行；整个实验封存后
不能追加交付或候选对象。`build_experiment_manifest`仅允许核验返回相同内容的已有清单，
内容变化或原件校验失败时拒绝覆盖。后续交付修订由新实验承接，旧档案保持原位。

## Git与制品保存

Git保存研究定义、程序、结论、合同、交付报告／回执及候选对象；`artifacts/`和
`deliveries/*/*/experiments/`中的机器制品副本按当前忽略规则保留在本地。
交付与候选对象的受哈希约束文件通过Git属性保留原始字节。
跨机器恢复须同时同步被忽略的制品和所引用的前驱档案。符合当前契约的档案可调用
`validate_archives`与`validate_delivery`核验；单独提交或推送Git不能证明完整档案已持久归档。
历史格式原件保留供人工查阅，平台不承诺机器复验。
当前平台未配置统一外部制品归档目的地，具体备份位置和同步责任须在任务交接中明确。
`.tmp/`及`outputs/`不能作为正式交付的唯一保存位置。

## 封存与验证

| 归档对象 | 治理要求 |
| --- | --- |
| 封存原件 | 有效manifest生成后保持只读 |
| 失败与未完成路径 | 连同未达标结果保留，不只归档成功路径 |
| 研究修订 | 方法、参数域、合同或判断变化由后继版本承接 |
| 实验执行 | 按[REX说明](../packages/research_experiment/README.md)冻结定义并通过正式执行前预检 |

核验指定的当前契约实验（路径替换为实际档案）：

```python
from pathlib import Path
from czsc_trader.application import RepositoryContext, validate_archives
context = RepositoryContext.discover(Path.cwd())
validate_archives(context, archive=context.experiments_root / "SXXX/YYYYMMDD_SXXX_EXNN")
```

`all_archives=True`仍可扫描全库；包含不支持的旧格式时明确失败，不视为历史复验保证。
实验manifest只支持schema 1；不接受schema 2重封存格式或`integrity_repair`，不通过更新哈希修复旧档案。
旧路径和旧来源字符串随原件保留，当前API不承担旧SM来源的兼容解析。

历史`run_experiment.py`保留为当时执行代码，不保证在迁移后的目录中直接运行。需要继续同一
问题时创建新实验，显式声明来源实验及其哈希，并通过TDR的当前公共能力重建证据。

## 历史文档与证据版本

文档修订只作用于后续工作，不改变已封存合同。旧manifest绑定的文档路径可能已更新，原manifest仍须保留；历史备份可用于人工查阅。平台不承诺旧格式解码、旧公式复算或历史档案机器校验。继续研究时，在授权范围内建立后继实验并生成当前契约证据，不修改旧哈希或替换现行文档来伪造通过。

[RSCH的0930备份](../research/RSCH_AGENT.md.0930)仅作为历史参考；使用前核对其哈希与目标实验绑定，不能假定它适配全部历史实验。
