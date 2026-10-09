# 策略研究资料导航

`research/` 保存研究任务、实验定义、程序、资料、数据资产、研究结果和阶段交付。
各批次的 `HANDOFF.md` 记录当前状态、成果引用和下一步。

## 目录布局

以下为研究目录的目标布局。

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
    others/                          # 定义以外的资料

  deliveries/<阶段>/<修订>/
    report.md                        # 阶段报告
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
```

## 批次入口

| 策略 | 交接入口 | 策略 | 交接入口 |
| --- | --- | --- | --- |
| S001 | [HANDOFF](S001/HANDOFF.md) | S007 | [HANDOFF](S007/HANDOFF.md) |
| S002 | [HANDOFF](S002/HANDOFF.md) | S011 | [HANDOFF](S011/HANDOFF.md) |
| S003 | [HANDOFF](S003/HANDOFF.md) | S012 | [HANDOFF](S012/HANDOFF.md) |
| S013 | [HANDOFF](S013/HANDOFF.md) | | |
