# 策略研究资料导航

`research/` 是新研究的统一空间，保存批次意图、数据、实验材料、正式结果、阶段交付、用户决定和交接信息。
研究目标、当前结论和下一步以获准批次的 `HANDOFF.md` 及其精确交付引用为准。
本文维护目录职责与导航，研究方法见角色契约，接口使用见模块手册。

## 角色与交付

| 事项 | 权威入口 |
| --- | --- |
| 五阶段目标、研究方法、用户授权和交付责任 | [RSCH Agent](RSCH_AGENT.md) |
| 上下文、评价、证据、交付与冻结 API | [TDR 使用说明](../src/czsc_trader/README.md) |
| 平台架构、工程决策和开发环境 | [DEV Agent](../docs/DEV_AGENT.md) |
| 旧实验原件的保存边界 | [历史实验说明](../experiments/README.md) |

阶段二、三由 RSCH 自主组织，平台核对交付产物；阶段推进、候选选择和冻结由用户决定。
评价不自动登记候选，留证与正式交付均通过显式 API。选型后进行技术检验，获得对精确冻结计划的批准后执行冻结；
仅 `COMMITTED` 表示冻结完成。部署与 PTE 账户操作另行授权。

## 批次空间与落盘职责

```text
research/<批次>/
  batch.json
  HANDOFF.md
  batches/                         # 后续立项凭据对应的材料（如有）
  data/
  decisions/
  experiments/<实验>/
    experiment.json
    work/
    evidence/
  deliveries/<阶段>/<修订>/
  freeze_requests/<请求ID>/
research/registrations/
```

| 路径 | 路径确定及写入责任 | 内容与生命周期 |
| --- | --- | --- |
| 批次目录、`batch.json`、初始 `HANDOFF.md`、`batches/` | TDR `research_governance_service` 根据强类型批次请求确定并写入 | 研究身份与立项材料；后续交接由 RSCH 更新 |
| `data/` | TDR `research_governance_service.create_research_context` 指定空间；DFLS 写入 | 数据资产、质量证据和完整 prepare 引用 |
| 实验目录、`experiment.json`、初始 `work/notes.md` | TDR `research_governance_service.create_experiment` 分配编号并创建 | 实验身份；同批次编号跨日期递增 |
| `work/` | RSCH 组织并写入 | 源码、笔记与材料可修改；技术修正和重复计算可沿用实验 |
| `evidence/<hash>.<suffix>` | TDR `evidence_service.publish_evidence` 确定路径并写入 | 明确保留的结果或材料；内容不可覆盖 |
| `evidence/payload/`、`evidence/source/` | TDR `candidate_service` 保存；SM 登记引用 | 候选载荷和源码快照，不依赖可变 work |
| `evidence/inspection/` | TDR `inspection_service` 确定并写入 | 技术检验、冻结计划及必要证据 |
| `deliveries/<阶段>/<修订>/` | TDR `delivery_service` 根据批次、阶段、修订确定并写入 | 机器结论、人工报告、回执和选定证据浅快照；修正另发修订 |
| `decisions/` 及其 `objects/` | TDR `inspection_service`、`research_evidence` 写入 | 用户批准、拒绝或待定及真实确认依据 |
| `freeze_requests/<请求ID>/` | TDR 保存研究请求；SM 按显式日志根保存事务事实 | 请求、提交或失败及查询依据 |
| `research/registrations/` | SM `StrategyRegistry` 写入，TDR 组织业务调用 | 研究族、立项凭据和候选登记 |
| `strategies/` | SM 写入运行版本及发布包，SRT 管理部署身份 | 运行发布，独立于研究工作区 |
| `.tmp/` | 工具和平台计算按宿主确定并写入 | 临时缓存、排错和未选定输出 |

实验无需整体封存。影响正式结论的有效负面结果、反证和修正解释随交付保存；技术错误的过程记录按需要留存。
`HANDOFF.md` 记录当前状态和精确引用，正式结论以对应修订的交付为准。

## 策略批次

以下仅为交接入口，不复制阶段或版本状态。读取具体批次前核对研究授权。

| 策略 | 交接入口 | 策略 | 交接入口 |
| --- | --- | --- | --- |
| S001 | [HANDOFF](S001/HANDOFF.md) | S007 | [HANDOFF](S007/HANDOFF.md) |
| S002 | [HANDOFF](S002/HANDOFF.md) | S011 | [HANDOFF](S011/HANDOFF.md) |
| S003 | [HANDOFF](S003/HANDOFF.md) | S012 | [HANDOFF](S012/HANDOFF.md) |

## 保存与跨机器交接

当前 Git 规则忽略 `research/<批次>/data/`、根 `data/`、`.tmp/` 及旧实验机器制品中的指定路径。
新的已发布证据与交付按实际 Git 跟踪规则保存，受哈希约束的文件保留原始字节。
交接时明确正式交付引用、候选源码与支撑证据，以及复算所需的完整 DFLS 空间位置和同步责任。
单独保存准备引用或 Git clone 无法恢复缺失的数据资产；`.tmp/` 不能作为正式证据的唯一位置。

旧 `experiments/`、旧候选和交付保留原件及哈希供人工查阅。当前入口不自动解析旧格式；继续研究时在授权范围内
生成新契约证据，历史引用与新结果分别说明。目录更新不授予清理历史数据的权限。
PTE 生产状态以实际运行环境为准，操作边界见[PTE 运维手册](../docs/PTE_OPERATIONS.md)。
