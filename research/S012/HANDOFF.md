# S012｜518850.SH 阶段一交接

## 当前状态

阶段一（MANDATE）合同已完成。当前交付完整度为`COMPLETE`，修订3的`FULL`技术核验为`PASS`，14项全部确认。
资金、基准交易单位、策略执行细节授权及研究资源范围均已有用户确认。尚无实验、候选或冻结版本；阶段二待单独批准。

## 权威入口

| 事项 | 入口 |
| --- | --- |
| 当前人工报告 | [阶段一修订3](mandates/3/report.md) |
| 当前机器合同与回执 | [delivery.json](mandates/3/delivery.json)、[receipt.json](mandates/3/receipt.json) |
| 当前注册意图 | [family.json](../registrations/S012/family.json) |
| 立项凭据 | [SGC-S012-001](../registrations/S012/credentials/SGC-S012-001.jsonl) |
| 原始注册材料 | [批次文档](batches/SGC-S012-001.md)、[注册请求](materials/registration_request.json) |
| 目标及交易口径确认 | [用户回复01](materials/user_confirmation_20261004_01.json) |
| 评价日期及预热原则确认 | [用户回复02](materials/user_confirmation_20261004_02.json) |
| 资金、执行研究权限及资源确认 | [用户回复03](materials/user_confirmation_20261004_03.json) |
| 数据覆盖与复算入口 | [覆盖证据](materials/data_coverage_v1.json)、[核验代码](deliverables/check_data_coverage.py) |
| 当前交付实现及验证 | [mandate_v3.py](deliverables/mandate_v3.py)、[验证结果](materials/mandate_v3_validation.json) |

精确交付引用：`owner=MandateOwner(S012)`，`stage=MANDATE`，`revision=3`，
`content_sha256=6e2f856f79f4211f0f6532b3349b33a2f35cd881fd8c4a687d020dff5bb46435`。
前驱修订1、2及其附件保留原样；后续变更通过新修订承接。

## 下一步

请用户审阅修订3报告，决定是否进入阶段二；获批后通过公共API记录绑定该精确交付的阶段推进决定。
重型研究开始前确认Git分支选择；本轮阶段一在`master`开展，起点提交为`91dc2b9`。
当前只核验日线可用性；后复权因子历史发布时点仍需在实际使用前核验。
本批次材料已记录其他研究摘要的背景暴露边界，具体见当前人工报告。
