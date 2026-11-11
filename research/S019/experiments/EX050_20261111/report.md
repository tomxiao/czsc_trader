# S019 三候选阶段四自检收尾

Status: COMPLETED

用户批准的 C0966、C1010、C0909 全部完成非参数检查与 1,698 个邻点计算。此前暂停点已由新版 V4 回放续完。[迁移校验](others/v4_migration/budget_validation.json)复现了标准与压力中心及抽样邻点的账户结果。

| 候选 | 邻点联合通过 | 通过率 | 80% 门槛 |
| --- | ---: | ---: | --- |
| C0966 | 161 / 242 | 66.53% | 未通过 |
| C1010 | 728 / 728 | 100.00% | 通过 |
| C0909 | 552 / 728 | 75.82% | 未通过 |

C1010 是本批唯一通过全部适用数值目标的候选。标准费率下 NAR 66.9452%、MDD 13.3508%、Calmar 5.014322，双倍费用下 Calmar 4.588179。C0966 和 C0909 的中心及费用检查完成，均在邻点联合通过率一项未达标。结果来自批次已见历史。本批新 `ASSESSMENT` 面板及阶段五待后续决定。

[非参数检查](others/nonparameter_selfcheck.json)、[完整邻域结果](others/v4_parameter_selfcheck/result.json)、[统计及时间诊断](others/statistics_report.md)与[S018-v1 同窗参考](others/temporal_s018_reference.json)保留各自的计算口径。研究绩效对标为 S018-v1，同条件 MU 买持用于原相对回撤约束。

后续的[持仓再平衡对照](../EX051_20261112/report.md)独立记录。此前[暂停检查点](others/pause_checkpoint.json)和[停止记录](others/process_pause.json)保留当时的执行状态。
