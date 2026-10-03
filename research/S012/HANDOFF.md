# S012｜518850.SH 阶段一交接

## 当前状态

已注册S012并启动阶段一（MANDATE）。当前交付完整度为`PARTIAL`，修订2的`FULL`技术核验为`PASS`。
资金、基准交易单位、策略执行细节授权及研究资源范围待用户确认。尚无实验、候选或冻结版本；阶段二待单独批准。

## 权威入口

| 事项 | 入口 |
| --- | --- |
| 当前人工报告 | [阶段一修订2](mandates/2/report.md) |
| 当前机器合同与回执 | [delivery.json](mandates/2/delivery.json)、[receipt.json](mandates/2/receipt.json) |
| 当前注册意图 | [family.json](../registrations/S012/family.json) |
| 立项凭据 | [SGC-S012-001](../registrations/S012/credentials/SGC-S012-001.jsonl) |
| 原始注册材料 | [批次文档](batches/SGC-S012-001.md)、[注册请求](materials/registration_request.json) |
| 目标及交易口径确认 | [用户回复01](materials/user_confirmation_20261004_01.json) |
| 评价日期及预热原则确认 | [用户回复02](materials/user_confirmation_20261004_02.json) |
| 数据覆盖与复算入口 | [覆盖证据](materials/data_coverage_v1.json)、[核验代码](deliverables/check_data_coverage.py) |
| 当前交付实现及验证 | [mandate_v2.py](deliverables/mandate_v2.py)、[验证结果](materials/mandate_v2_validation.json) |

精确交付引用：`owner=MandateOwner(S012)`，`stage=MANDATE`，`revision=2`，
`content_sha256=55e51380d10e8c1b7a04327083feb251fd4eca370198317dfb6ef9d7bd83c679`。
前驱修订1及其附件保留原样；后续确认通过新修订承接。

## 下一步

收齐剩余三组用户确认，发布后继完整合同并呈现人工报告，再请用户决定是否进入阶段二。
重型研究开始前确认Git分支选择；本轮阶段一在`master`开展，起点提交为`91dc2b9`。
当前只核验日线可用性；后复权因子历史发布时点仍需在实际使用前核验。
本批次材料已记录其他研究摘要的背景暴露边界，具体见当前人工报告。
