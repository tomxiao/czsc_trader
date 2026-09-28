# 策略研究资料导航

本文只提供资料入口，不重复维护策略状态、研究规则或平台接口。开始工作时以当前用户指令和相应
角色契约确定授权；具体批次的目标、结论和下一步以其`HANDOFF.md`为准。

## 角色与交付

| 事项 | 权威入口 |
| --- | --- |
| 策略研究员的假设、实验、实现与候选交付 | [RSCH Agent](RSCH_AGENT.md) |
| 首席投资官的独立体检、裁决、冻结与SRT部署 | [CIO Agent](CIO_AGENT.md) |
| 研究员手工提交候选包的目录、binding与文件身份 | [候选包契约](CANDIDATE_PACKAGE.md) |
| 不可变正式实验的目录和归档合同 | [实验档案说明](../experiments/README.md) |
| 平台架构、研究工具待评审事项与开发运维 | [开发运维交接](../docs/DEVELOPMENT_HANDOFF.md) |

研究员与首席投资官由用户分别授权；候选交付、体检、冻结、SRT部署和PTE账户操作各有独立
边界。操作步骤及权限以相应角色契约为准。

## 策略批次

以下仅是交接入口，不在此复制阶段或版本状态。

| 策略 | 交接入口 | 策略 | 交接入口 |
| --- | --- | --- | --- |
| S001 | [HANDOFF](S001/HANDOFF.md) | S005 | [HANDOFF](S005/HANDOFF.md) |
| S002 | [HANDOFF](S002/HANDOFF.md) | S006 | [HANDOFF](S006/HANDOFF.md) |
| S003 | [HANDOFF](S003/HANDOFF.md) | S007 | [HANDOFF](S007/HANDOFF.md) |
| S004 | [HANDOFF](S004/HANDOFF.md) | S008 | [HANDOFF](S008/HANDOFF.md) |

## 事实来源

| 要核对的事实 | 来源 |
| --- | --- |
| 批次意图、材料和研究凭据 | `research/registrations/SXX/`、`research/SXX/materials.json` |
| 实验问题、失败记录和机器证据 | `experiments/SXX/`中的不可变档案 |
| 候选提交内容 | `research/SXX/candidates/`及对应候选包 |
| 正式身份、冻结版本、SRT部署和治理证据 | `strategies/`，只由平台工具写入 |
| 数据与可再生输出 | `data/`、`outputs/`；使用前仍须按角色契约核对因果及身份 |

PTE生产状态属于独立运行环境；研究资料或Git状态不能替代生产核对。具体操作与安全边界见
[开发运维交接](../docs/DEVELOPMENT_HANDOFF.md)。
