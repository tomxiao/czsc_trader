# 策略研究资料导航

`research/`用于研究治理：研究意图、目标约束、确认依据、登记索引和交接导航。阶段二至五的新交付
及候选实体跟随来源实验保存；历史原件保持原位，不因目录规则更新而搬移或重签。
本文只提供资料入口，不重复维护策略状态、研究规则或平台接口。开始工作时以当前用户指令和相应
角色契约确定授权；具体批次的目标、结论和下一步以其`HANDOFF.md`为准。

## 角色与交付

| 事项 | 权威入口 |
| --- | --- |
| 五阶段研究、自检、技术检验及获批冻结 | [RSCH Agent](RSCH_AGENT.md) |
| 不可变正式实验的目录和归档合同 | [实验档案说明](../experiments/README.md) |
| 当前公共契约、五阶段交付与冻结API | [TDR使用说明](../src/czsc_trader/README.md) |
| 平台工程决策、架构与开发环境 | [DEV Agent](../docs/DEV_AGENT.md) |

新流程由用户批准阶段推进、选择候选并决定是否冻结；研究员执行研究、自检、技术检验及获批冻结。
`StrategyCandidate`身份贯穿阶段三至五，通过TDR显式登记。当前已实现的接口以模块README和
公共导出为准；历史设计稿中的能力占位仅用于追溯需求。
部署和PTE账户操作须另行取得授权。

正式研究执行通过TDR/REX受管入口，研究员管理参数搜索与预算。阶段报告使用
`assemble_delivery/validate_delivery`发布和验证；用户选型后调用`inspect_candidate`，取得明确
冻结批准后调用`freeze_candidate`，仅`COMMITTED`表示成功。旧CIO及候选包执行入口已删除，
历史实验与冻结证据原件保留供人工查阅；公共入口只接受当前契约，平台不承诺历史机器复验。

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
| 候选身份与派生登记 | `research/registrations/<策略ID>/candidates/` |
| 新登记候选的源码、载荷与来源证据 | `experiments/<策略ID>/<来源实验ID>/objects/`，通过登记引用读取 |
| 阶段一目标、约束及确认依据 | `research/<策略ID>/mandates/<修订>/` |
| 阶段二至五交付和自检证据 | `experiments/<策略ID>/<归属实验ID>/deliveries/<阶段>/<修订>/` |
| 历史schema 1/2/3阶段交付 | 原`research/<策略ID>/deliveries/`，原件保留供人工查阅 |
| 用户决定及确认材料 | `research/<策略ID>/decisions/`及其`objects/`，使用带归属和哈希的研究证据引用 |
| 技术检验与冻结计划 | `experiments/<策略ID>/<检验实验ID>/objects/inspection/` |
| 冻结请求及结果查询 | `research/<策略ID>/freeze_requests/<请求ID>/`，通过TDR查询实际状态 |
| 历史候选提交内容 | `research/SXX/candidates/`及对应旧候选包 |
| 运行策略族、冻结版本、SRT部署及生命周期 | `strategies/`，只由平台工具写入；运行合同不依赖研究批准目录 |
| 数据与可再生输出 | `data/`、`outputs/`；使用前仍须按角色契约核对因果及身份 |

`HANDOFF.md`记录当前状态及精确交付引用，不另存一套正式阶段结论。实验原件与交付中的
证据副本各自保留；本地忽略制品的备份及跨机器恢复要求见[实验档案说明](../experiments/README.md)。

PTE生产状态属于独立运行环境；研究资料或Git状态不能替代生产核对。具体操作与安全边界见
[PTE运维手册](../docs/PTE_OPERATIONS.md)。
