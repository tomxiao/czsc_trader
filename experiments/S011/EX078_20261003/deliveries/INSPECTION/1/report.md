# S011 · INSPECTION · 1

研究员声明状态：BLOCKED
归属：EX078_20261003

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：EX078_20261003；用途：CURRENT_EVALUATION；回执：`646e99df255e76b81f2be08a02d2326a236a3ebf5b30528b30ebb8aa6489aa66`

候选：S011-C0618

内容指纹：`a3cffbaa193522db6f81e8da2cdff4ca5116d85d1d49cf6796580130d3bf7a29`

拟冻结版本：v1；计划摘要：`d43538cbfc5f4d144481dd2abddcf1bb19ceb641c92171f084d24826804f4d09`

技术检验：FAIL；方法：candidate-inspection-v1

| 检验项 | 状态 | 说明 |
| --- | --- | --- |
| CONTENT | PASS | registered candidate source, payload and installed dependencies verified |
| PACKAGE | PASS | source, observation and install closure verified |
| RUNTIME | FAIL | strategy implementation has no from_release factory: S011Reversal |
| COVERAGE | INCOMPLETE | actual reproduction coverage compared with explicit protocol |
| REPRODUCTION | FAIL | ValueError: evaluation request data cutoff differs |
| LEDGER_AUDIT | INCOMPLETE | 0/0 reproduction coordinates passed |
| LEDGER_EQUIVALENCE | INCOMPLETE | 0/0 reproduction coordinates passed |
| SIGNAL_EQUIVALENCE | INCOMPLETE | 0/0 reproduction coordinates passed |

剩余风险：
- 本次核验使用已见开发池；历史选择偏差及重叠样本限制仍存在，技术检验不构成独立收益验证。
- 原始复权数据历史发布时间尚未逐日核实，不能据此证明全部历史信息当时可得。
- C0618阶段四联合邻域仅5/16满足原目标，参数稳健性仍有限；此次沿用原选择，不重复优化。
- 基线账户截至2026-09-28；选型已见数据包含截至2026-09-30的补充回测，前瞻起点拟为DFLS日历所示下一交易日2026-10-08。
- 冻结初始资格为RESEARCH；资格晋级、SRT部署及PTE账户操作需独立证据和授权。

冻结状态：尚未请求

待用户决定：技术检验存在失败或未完成项，须处理后重新检验。

### 用户决定与确认来源

- S011-C0618-selection-20261003：APPROVE；理由：用户明确选择C0618并授权继续阶段五技术检验；精确冻结计划尚待批准。；[确认来源](<attachments/fdde5421f7315e1c0514731808b150c8c13dc5e815daa89ac8b1d09e7c559024>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |

## 解释

**RESEARCH_JUDGMENT**：本交付完成冻结前技术检验并呈现精确计划；用户已选择C0618，尚未批准该计划冻结。选择数据截止日2026-09-30，拟前瞻起点2026-10-08。前瞻起点仅为计划边界，不代表部署、实盘启用或资格晋级。


## 未完成事项

- 技术检验未通过，不能申请冻结。

## 复算

依据本实验inputs.json的原评价引用及experiment.py通过公开inspect_candidate重建后继实验；禁止覆盖已执行工作空间。报告与计划、来源及复算证据均附于交付。

数据访问：既有DFLS授权数据及缓存；原账户窗口2025-02-06至2026-09-28，共403交易日。

确定性及容差：标准及20bp成本压力两场景；候选内容/数据/协议身份一致；信号与完整经济账本绝对容差1e-7、相对容差0。

