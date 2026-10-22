# S011-C9902 首次正式技术检验

Status: INCOMPLETE（行为等价通过；PTE场景预期错误导致总体FAIL）

用户批准C9902进入S011-v2技术检验，不含冻结或生产部署。目标版本v2、父版本v1。

首次运行因Windows沙箱multiprocessing权限被拒绝，在EQUIVALENCE阶段停止。原件保存在 `others/attempts/inspection-db211a4bcb0f442e883bcf591c90b588/`。
申请所需进程权限后，用相同协议、输入、候选重试，耗时41.09秒。

| 检查 | 结果 |
| --- | --- |
| 415日候选与最终格式v2发布包，零容差行为比较 | PASS |
| EX080同一C9902正式账户基线复现 | PASS |
| 入场、部分成交、重复回报、重启、持有、退出 | PASS |
| 零成交撤单 | FAIL：预期health=OK，实际BLOCKED |
| 包损坏、输入缺失、未来输入 | 各项PASS |

[正式检验报告](others/inspection_report.json) · [摘要](others/inspection_summary.json)

## 原因与后继处理

原因是检验场景对平台契约的理解错误，不是策略实现差异。
`packages/paper_trading_engine/src/paper_trading_engine/futu_execution.py:518-527` 明确将首次非完整成交终态标记BLOCKED，等待人工确认执行缺口。
既有 `test_channel_safety.py::test_ft_pte03_incomplete_and_unknown_orders_never_silently_recover` 验证此规则，不允许静默恢复。
零成交撤单应保持零持仓、现金100000、冻结现金0、订单数1，同时账户BLOCKED；重复回报和重启不应解除阻断。

本次协议及FAIL证据保持不变。后继实验只根据既有平台契约修正撤单后两个检查点的健康预期，保留其余数值、策略、数据与比较标准；不修改平台、不自动确认执行缺口。

本报告不能用于冻结批准。现有S011-v1及部署回执逐文件哈希未变，没有创建正式v2版本或操作生产。
