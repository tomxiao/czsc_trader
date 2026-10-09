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

以下为已确认的目标布局；平台适配及 S013 存量迁移按后续评审方案实施。

```text
research/<批次>/
  batch.json                         # 批次身份
  HANDOFF.md                         # 当前状态、成果引用及下一步
  batches/                           # 后续立项凭据对应的材料
  materials/                         # 研究任务、授权依据、评价约定

  experiments/<实验>/
    experiment.json                  # 实验身份
    src/                             # 验证程序、策略实现、自定义组件
    protocols/                       # 假设、方法、参数域、搜索及自检方案
    notes.md                         # 观察、判断变化、修正及停止依据
    others/                          # 定义以外的资料，供 RSCH 灵活组织

  deliveries/<阶段>/<修订>/
    report.md                        # 研究员编写的阶段报告
    receipt.json                     # 交付身份及关联文件引用

  decisions/                         # 正式用户决定
  freeze_requests/<请求ID>/           # 冻结请求及事务记录

  assets/
    data/                            # 实际使用的数据资产
    runs/<实验>/<运行>/               # 请求、结果、搜索数据库、检查点
    evidence/<实验>/                 # 显式发布的正式证据
    candidates/<候选>/               # 候选载荷、源码及依赖快照
    deliveries/<阶段>/<修订>/         # 完整机器交付包

research/registrations/               # 研究族、立项凭据和候选登记
.tmp/research/<批次>/<实验>/           # 临时缓存、排错及可丢弃输出
outputs/                             # 用户发起的独立回测产物
strategies/                          # 冻结运行版本及发布包
```

下表批次内路径相对 `research/<批次>/`；`research/registrations/`、`.tmp/` 和 `strategies/` 相对仓库根。

| 路径 | 写入责任 | 保存与修改规则 |
| --- | --- | --- |
| `batch.json`、`batches/`、`experiment.json` | 平台创建 | 身份记录通过公共 API 维护 |
| `materials/`、实验内 `src/`、`protocols/`、`notes.md`、`others/`、`HANDOFF.md` | RSCH | 按研究需要编辑、补充和更新 |
| `assets/data/` | 经平台入口，由 DFLS 写入 | 保存实际使用的数据版本，更新时保留已有研究引用 |
| `assets/runs/` | RSCH 组织写入 | 按接续需要保存和更新，选定材料发布为正式证据 |
| `assets/evidence/`、`assets/candidates/` | 平台通过公共 API 发布 | 按发布身份保存原始内容，变更形成新证据或新候选 |
| `assets/deliveries/` | 平台通过公共 API 发布 | 按修订保存，修正形成新修订 |
| `deliveries/` | RSCH 编写报告，平台原样发布报告及回执 | 与完整交付包对应，按修订保存，修正形成新修订 |
| `decisions/`、`freeze_requests/`、`research/registrations/` | 平台按实际授权写入 | 通过公共 API 维护，保留授权与状态变化历史 |
| `strategies/` | SM 写入运行版本及发布包，SRT 管理部署身份 | 按授权保存发布版本和部署记录 |
| `.tmp/` | RSCH、工具及平台 | 保存临时缓存及排错材料，可随任务更新、替换 |

## 策略批次

以下仅为交接入口，不复制阶段或版本状态。读取具体批次前核对研究授权。

| 策略 | 交接入口 | 策略 | 交接入口 |
| --- | --- | --- | --- |
| S001 | [HANDOFF](S001/HANDOFF.md) | S007 | [HANDOFF](S007/HANDOFF.md) |
| S002 | [HANDOFF](S002/HANDOFF.md) | S011 | [HANDOFF](S011/HANDOFF.md) |
| S003 | [HANDOFF](S003/HANDOFF.md) | S012 | [HANDOFF](S012/HANDOFF.md) |
| S013 | [HANDOFF](S013/HANDOFF.md) | | |

## 保存与跨机器交接

`HANDOFF.md` 记录当前研究所需的精确成果引用、资产位置及下一步任务。

资产交接包含任务所需的数据空间、候选快照、正式证据和完整交付包。未完成研究的交接同时包含必要运行状态。
交接说明列明资产保管位置、同步范围、责任人、恢复方式和实际就绪状态。

恢复后核对数据空间及准备引用、候选身份、证据哈希，以及报告、回执与完整交付包的一致性。
接续研究按实际需要恢复搜索数据库和检查点，核验结果记入交接说明。

历史研究原件按原目录、原始字节和哈希保存。延续研究时按当前契约形成新成果，并关联所采用的历史依据。
PTE 生产状态以实际运行环境为准，操作边界见[PTE 运维手册](../docs/PTE_OPERATIONS.md)。
