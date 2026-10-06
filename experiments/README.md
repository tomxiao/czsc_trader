# 历史实验原件

本目录保留旧研究流程产生的实验源码、材料、机器制品和阶段交付，供人工查阅。
新实验通过 TDR `create_experiment` 创建于 `research/<批次>/experiments/<实验>/`，
当前目录职责见[研究导航](../research/README.md)，使用方法见[TDR 手册](../src/czsc_trader/README.md)。

## 原件与历史布局

旧档案可能包含 `experiment_binding.json`、四份研究文档、`artifacts/`、`objects/`、
实验内 `deliveries/` 和 `experiment_manifest.json`，路径及 schema 以原件为准。
这些内容维持原位、原始字节和哈希，目录规则更新不搬移、补写、重封存或修改其历史结论。

当前平台已移除旧预检、执行回执和实验整体封存入口，不承诺旧格式机器校验或旧程序可直接运行。
需要延续历史问题时，先核对研究授权，在新的批次上下文中生成当前契约的证据，并说明历史依据与新结果的关系。

## 保存与恢复边界

旧 `artifacts/` 及交付中的指定机器制品副本按现有 Git 规则忽略，完整原件不能仅靠 Git clone 恢复。
已有原件的保管位置和同步责任以具体交接为准；本文不授权清理或重签历史文件。
新的保存规则见[研究导航](../research/README.md)，研究权限及保留验证样本要求见[RSCH Agent](../research/RSCH_AGENT.md)。
