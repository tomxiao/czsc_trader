# 研究平台接口收敛验收

日期：2026-10-01。身份：DEV。分支：`codex/research-platform-capabilities`。

## 1. 范围与结论

本轮实施已评审的接口收敛及旧流程删除。研究员统一使用公开Python API，TDR用户CLI仅保留`backtest run`；PTE独立运维CLI不在删除范围。

| 改造项 | 交付与验证 |
| --- | --- |
| API导航 | [application公共导出](../src/czsc_trader/application/__init__.py)选择性暴露现有业务服务；模块原生能力沿原公共入口使用 |
| 统一回测 | `run_backtest(context, StrategyCandidate或StrategyVersion, BacktestRequestV2)`共用回放、审计和报告路径；候选端到端账本与直接回放一致 |
| CLI收敛 | 仅`backtest run`；删除的命令组明确返回参数错误，不设置别名或回退 |
| 新闻能力删除 | 删除新闻抽取模块、应用服务、CLI入口及专属测试 |
| 旧治理删除 | 删除候选包、CIO审查、裁定和冻结写入；移除相应公共对象及旧策略判定器 |
| 共用证据保留 | 账户评价、统计审计、工程审计及证据组装保留；证据组装迁至`research_tools/audit_evidence.py` |
| 历史冻结治理 | 原件保持不变；保留完整性校验及内部历史格式解码，不提供历史流程的写入入口 |

已同步[TDR使用说明](../src/czsc_trader/README.md)、相关包说明及RSCH当前能力边界。删除内容可从`v0.5.22`恢复；冻结记录和实验原件没有删除或重签。

## 2. 验收证据

### 2.1 离线回归

执行入口：`scripts/test-all.ps1`。最终完整离线回归及规定范围Ruff均通过，耗时153.29秒。最终日志位于`.tmp/test-regression/run-ddb21b24aeea4b529632298ecfc747ea/`；该目录不进入Git。

| 分组 | 通过数量 |
| --- | ---: |
| TDR | 75 |
| PTE Python | 99 |
| DFLS | 141 |
| FSC / STC | 2 / 3 |
| SM / REX / SE | 13 / 7 / 4 |
| SRT / TXE | 69 / 2 |
| Python合计 | 415 |
| PTE前端 | 3 |

统一API专项覆盖候选与版本派发、候选完整回放和图表、版本身份篡改、版本图表覆盖、错误输入类型及未知CLI版本。SM测试覆盖五个既有版本、治理接纳记录缺失／重复／错绑、凭据篡改及生命周期证据约束。已废弃流程的专属测试随实现删除，其余有效的账本和完整性测试继续执行。

### 2.2 冻结原件对照

- 实施前后对`strategies/`全部76个非缓存文件计算SHA-256，路径集合与逐文件哈希完全一致。
- 排序后的相对路径／哈希映射规范JSON汇总哈希：`45ec4110b785cc978e428548193f219306bc1d9ae6d91878bc35ccb50d1ccf58`。
- `StrategyRegistry.validate_all()`：4个策略族、5个版本、17条事件、5条绩效证据、1条凭据。
- S001-v1、S001-v2、S002-v1、S003-v1、S007-v1分别验证为`LEGACY_GOVERNANCE_ACCEPTED`，与实施前一致。
- 上述5个版本分别通过`validate_release_package`，文件闭包、绑定与运行时描述校验通过。
- 未修改S011研究档案，未变更生产状态，未合并master、打tag或推送远端。

### 2.3 历史实验档案限制

额外执行只读档案普查：500个档案中379个通过，121个因缺少声明的文件未通过。分布为METHODS 2个、S008 88个、S009 10个、S010 21个；失败类别均为`missing declared experiment file`。

例如`experiments/METHODS/20260926_PYSR_EX01/artifacts/s003_forecast.csv`本机缺失且属于Git忽略范围。档案校验器与实验原件未改动；本轮不补造产物、不重签、不宣称历史档案全量验收通过。此项与冻结版本治理校验分开报告。

另一次扩大到整个工作目录的Ruff扫描包含封存研究脚本，存在1786条告警；这些文件未调整。正式Ruff验收范围沿用`test-all.ps1`，不以重写研究证据消除告警。

## 3. 已知边界及后续

1. 新阶段产物契约、自检排序编排、批准绑定及冻结能力仍按RSCH占位清单单独建设；当前没有可用的新冻结入口。
2. CLI目前只解析已登记版本；候选由Python API直接接收，不新增候选持久化或CLI身份解析。
3. 版本回测仍依赖已有SRT部署凭据；缺少时明确失败，不自动部署。
4. 离线验收不包含在线数据供应商、实盘收益或生产发布验证。
5. 建议下一轮先评审阶段产物及StrategyCandidate持久化契约，再增补能力。历史缺失产物恢复应另行确认来源与范围。
