# 策略研究资料导航

本文只提供资料入口，不重复维护策略状态、研究规则或平台接口。开始工作时以当前用户指令和相应
角色契约确定授权；具体批次的目标、结论和下一步以其`HANDOFF.md`为准。

## 角色与交付

| 事项 | 权威入口 |
| --- | --- |
| 五阶段研究、自检、技术检验及获批冻结 | [RSCH Agent](RSCH_AGENT.md) |
| 不可变正式实验的目录和归档合同 | [实验档案说明](../experiments/README.md) |
| 当前公共契约、五阶段交付与冻结API | [TDR使用说明](../src/czsc_trader/README.md) |
| 平台架构与开发运维 | [开发运维交接](../docs/DEVELOPMENT_HANDOFF.md) |

新流程由用户批准阶段推进、选择候选并决定是否冻结；研究员执行研究、自检、技术检验及获批冻结。
`StrategyCandidate`身份贯穿阶段三至五，通过TDR显式登记。当前已实现的接口以模块README和
公共导出为准；RSCH附录及历史设计稿中的能力占位用于追溯需求。
部署和PTE账户操作须另行取得授权。

正式研究执行通过TDR/REX受管入口，研究员管理参数搜索与预算。阶段报告使用
`assemble_delivery/validate_delivery`发布和验证；用户选型后调用`inspect_candidate`，取得明确
冻结批准后调用`freeze_candidate`，仅`COMMITTED`表示成功。旧CIO及候选包执行入口已删除，
历史实验与冻结证据原件保留。

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
| 候选身份、源码与派生关系 | `research/registrations/<策略ID>/candidates/`及登记对象 |
| 五阶段交付和自检证据 | `research/<策略ID>/deliveries/<阶段>/<修订>/`中的内容、报告、回执及附件 |
| 用户决定、技术检验与冻结结果 | `strategies/research_decisions/`、`research_objects/`、`freeze_requests/`中的不可变引用及状态 |
| 历史候选提交内容 | `research/SXX/candidates/`及对应旧候选包 |
| 正式身份、冻结版本、SRT部署和治理证据 | `strategies/`，只由平台工具写入 |
| 数据与可再生输出 | `data/`、`outputs/`；使用前仍须按角色契约核对因果及身份 |

PTE生产状态属于独立运行环境；研究资料或Git状态不能替代生产核对。具体操作与安全边界见
[开发运维交接](../docs/DEVELOPMENT_HANDOFF.md)。
