# 策略研究资料导航

本文只提供资料入口，不重复维护策略状态、研究规则或平台接口。开始工作时以当前用户指令和相应
角色契约确定授权；具体批次的目标、结论和下一步以其`HANDOFF.md`为准。

## 角色与交付

| 事项 | 权威入口 |
| --- | --- |
| 五阶段研究、自检、技术检验及获批冻结 | [RSCH Agent](RSCH_AGENT.md) |
| 不可变正式实验的目录和归档合同 | [实验档案说明](../experiments/README.md) |
| 平台架构、研究工具待评审事项与开发运维 | [开发运维交接](../docs/DEVELOPMENT_HANDOFF.md) |

新流程由用户批准阶段推进、选择候选并决定是否冻结；研究员执行研究、自检、技术检验及获批冻结。
`StrategyCandidate`身份贯穿阶段三至五，不另建候选包对象。新平台能力的实现状态见RSCH附录“平台能力占位清单”。
部署和PTE账户操作须另行取得授权。

### 旧流程参考

| 资料 | 适用范围 |
| --- | --- |
| [旧CIO契约](CIO_AGENT.md) | 理解旧角色流程及历史记录，不用于启动新的CIO任务 |
| [旧候选包契约](CANDIDATE_PACKAGE.md) | 阅读历史候选包及现有工具依赖，不作为新研究交付模型 |

旧平台依赖尚未全部移除；保留资料不表示新冻结流程已经可执行，也不授权改写历史证据。

## 策略批次

以下仅是交接入口，不在此复制阶段或版本状态。

| 策略 | 交接入口 | 策略 | 交接入口 |
| --- | --- | --- | --- |
| S001 | [HANDOFF](S001/HANDOFF.md) | S005 | [HANDOFF](S005/HANDOFF.md) |
| S002 | [HANDOFF](S002/HANDOFF.md) | S006 | [HANDOFF](S006/HANDOFF.md) |
| S003 | [HANDOFF](S003/HANDOFF.md) | S007 | [HANDOFF](S007/HANDOFF.md) |
| S004 | [HANDOFF](S004/HANDOFF.md) | S008 | [HANDOFF](S008/HANDOFF.md) |
| S009 | [HANDOFF](S009/HANDOFF.md) | S010 | [HANDOFF](S010/HANDOFF.md) |
| S011 | [HANDOFF](S011/HANDOFF.md) | | |

## 事实来源

| 要核对的事实 | 来源 |
| --- | --- |
| 批次意图、材料和研究凭据 | `research/registrations/SXX/`、`research/SXX/materials.json` |
| 实验问题、失败记录和机器证据 | `experiments/SXX/`中的不可变档案 |
| 新流程候选内容与自检证据 | 阶段三、四机器产物及证据索引；统一登记入口待CAP-01、CAP-07补齐 |
| 历史候选提交内容 | `research/SXX/candidates/`及对应旧候选包 |
| 正式身份、冻结版本、SRT部署和治理证据 | `strategies/`，只由平台工具写入 |
| 数据与可再生输出 | `data/`、`outputs/`；使用前仍须按角色契约核对因果及身份 |

PTE生产状态属于独立运行环境；研究资料或Git状态不能替代生产核对。具体操作与安全边界见
[开发运维交接](../docs/DEVELOPMENT_HANDOFF.md)。
