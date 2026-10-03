# S012｜518850.SH 阶段二交接

## 当前状态

阶段二（COMPONENTS）已完成，当前交付为EX005修订1，完整度`COMPLETE`、`FULL`技术核验`PASS`。
交付三个核心风险/状态组件和两项弱入场候选，完整保留无效、冗余、互补性反证及技术失败。
阶段一修订3继续约束全部研究。已有5个实验档案，无策略候选或冻结版本；阶段三待用户批准。

## 权威入口

| 事项 | 入口 |
| --- | --- |
| 当前人工研究报告 | [阶段二结论](../../experiments/S012/EX005_20261004/04_conclusion.md) |
| 当前正式组件报告 | [COMPONENTS修订1](../../experiments/S012/EX005_20261004/deliveries/COMPONENTS/1/report.md) |
| 当前机器合同与回执 | [delivery.json](../../experiments/S012/EX005_20261004/deliveries/COMPONENTS/1/delivery.json)、[receipt.json](../../experiments/S012/EX005_20261004/deliveries/COMPONENTS/1/receipt.json) |
| 已批准阶段一合同 | [修订3](mandates/3/report.md) |
| 当前注册意图 | [family.json](../registrations/S012/family.json) |
| 立项凭据 | [SGC-S012-001](../registrations/S012/credentials/SGC-S012-001.jsonl) |
| 原始注册材料 | [批次文档](batches/SGC-S012-001.md)、[注册请求](materials/registration_request.json) |
| 目标及交易口径确认 | [用户回复01](materials/user_confirmation_20261004_01.json) |
| 评价日期及预热原则确认 | [用户回复02](materials/user_confirmation_20261004_02.json) |
| 资金、执行研究权限及资源确认 | [用户回复03](materials/user_confirmation_20261004_03.json) |
| 阶段二授权及推进决定 | [用户指令](materials/stage2_authorization_20261004.json)、[已登记决定](decisions/S012-STAGE2-20261004.json) |
| 数据覆盖与复算入口 | [覆盖证据](materials/data_coverage_v1.json)、[核验代码](deliverables/check_data_coverage.py) |
| 当前交付实现及验证 | [delivery.py](../../experiments/S012/EX005_20261004/delivery.py)、[验证结果](materials/components_v1_validation.json) |
| 完整组件普查台账 | [504条检验](../../experiments/S012/EX004_20261004/artifacts/rex/component_metrics.json)、[年度分组](../../experiments/S012/EX004_20261004/artifacts/rex/fold_metrics.json) |
| 后继复核及互补性 | [96条复核](../../experiments/S012/EX005_20261004/artifacts/rex/robustness.json)、[条件分组](../../experiments/S012/EX005_20261004/artifacts/rex/interactions.json) |

精确交付引用：`owner=ExperimentOwner(S012, EX005_20261004)`，`stage=COMPONENTS`，`revision=1`，
`content_sha256=e23f28dde9be22f04bc3331c0cc47a99c136084ba0de0ffc0d71762a39a6b258`。
前驱合同及全部已封存实验保持原样；EX002为权限技术失败，EX003为零有效检验技术失败，均不作为研究有效性证据。

研究分支为`codex/s012-stage2`，起点`2bdd46a2`。本轮现有DFLS足够，未修改平台模块。
各实验`artifacts/`及交付中的实验副本按规则仅保存在本机；Git不包含完整数据制品。
跨机器恢复需同步完整S012实验制品和前驱链，并核验manifest及交付。尚未配置外部备份目的地。

## 下一步

请用户审阅阶段二报告，决定是否进入阶段三；获批后通过公共API记录绑定该精确交付的推进决定。
建议检验短期反转入场与各风险/状态组件的完整策略假设，逐一比较移除组件后的账户变化。
必须实际核验限价可成交性、成本和交易频率，当前组件证据尚未证明三项用户经济目标能同时实现。
全部结果来自开发池，后继选择与技术失败记录已披露；阶段三不得将年度切片包装为封存验证。
