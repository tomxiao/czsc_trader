# S011 · INSPECTION · 1

研究员声明状态：COMPLETE
归属：EX078_20261003

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：EX078_20261003；用途：CURRENT_EVALUATION；回执：`480a8473eb228e9cb40bfc220407ff80459783e9e4f0785f2ad472ff4fdfb7e1`

候选：S011-C0618

内容指纹：`ef4ba51984b8766bb02b4ac212fb8eee24b902eadb0e89f04f2130486eb92cfe`

拟冻结版本：v1；计划摘要：`267c76ae30e813ca43ad4f52bc1017b81feb32d5c6ab520a95698f4f6f343fad`

技术检验：PASS；方法：candidate-inspection-v1

| 检验项 | 状态 | 说明 |
| --- | --- | --- |
| CONTENT | PASS | registered candidate source, payload and installed dependencies verified |
| PACKAGE | PASS | source, observation and install closure verified |
| RUNTIME | PASS | candidate and prospective release runtime contracts match |
| COVERAGE | PASS | actual reproduction coverage compared with explicit protocol |
| REPRODUCTION | PASS | fresh managed evaluations persisted |
| LEDGER_AUDIT | PASS | 4/4 reproduction coordinates passed |
| LEDGER_EQUIVALENCE | PASS | 4/4 reproduction coordinates passed |
| SIGNAL_EQUIVALENCE | PASS | 4/4 reproduction coordinates passed |

剩余风险：
- 本次核验使用已见开发池；历史选择偏差及重叠样本限制仍存在，技术检验不构成独立收益验证。
- 原始复权数据历史发布时间尚未逐日核实，不能据此证明全部历史信息当时可得。
- C0618阶段四联合邻域5/16满足原目标，参数稳健性仍有限；此次沿用原选择，不重复优化。
- 基线账户截至2026-09-28；选型已见数据包含截至2026-09-30的补充回测，前瞻起点拟为DFLS日历所示下一交易日2026-10-08。
- 冻结初始资格为RESEARCH；资格晋级、SRT部署及PTE账户操作需独立证据和授权。

冻结状态：尚未请求

待用户决定：是否批准按计划267c76ae30e813ca43ad4f52bc1017b81feb32d5c6ab520a95698f4f6f343fad将当前C0618冻结为S011-v1？

### 用户决定与确认来源

- S011-C0618-selection-20261003：APPROVE；理由：用户明确选择C0618并授权继续阶段五技术检验；精确冻结计划尚待批准。；[确认来源](<attachments/fdde5421f7315e1c0514731808b150c8c13dc5e815daa89ac8b1d09e7c559024>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |

## 解释

**RESEARCH_JUDGMENT**：本交付完成冻结前技术检验并呈现精确计划；用户已选择C0618，尚未批准该计划冻结。选择数据截止日2026-09-30，拟前瞻起点2026-10-08。前瞻起点仅为计划边界，不代表部署、实盘启用或资格晋级。


## 未完成事项


## 复算

依据本实验inputs.json的原评价引用及experiment.py通过公开inspect_candidate执行技术一致性检验。报告与计划、来源及复算证据均附于交付。

数据访问：既有DFLS授权数据及缓存；原账户窗口2025-02-06至2026-09-28，共403交易日。

确定性及容差：标准及20bp成本压力两场景；候选内容/数据/协议身份一致；信号与完整经济账本绝对容差1e-7、相对容差0。

