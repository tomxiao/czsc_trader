# 研究目录说明

`research/`按研究批次保存研究材料、实验、数据资产、正式成果及交接信息。

```text
research/
  RSCH_AGENT.md                       # 研究员工作指南
  guides/                            # A股、美股等市场补充指南
  registrations/                     # 研究族、立项凭据及候选登记

  <批次>/
    batch.json                       # 批次身份
    HANDOFF.md                       # 当前状态、成果引用及接续入口
    batches/                         # 后续立项凭据对应的材料
    materials/                       # 批次级约定、授权及跨实验材料

    experiments/<实验>/
      experiment.json                # 实验身份
      report.md                      # 实验报告入口
      report_ref.json                # 已发布报告的引用
      src/                           # 实验程序、策略及自定义组件
      protocols/                     # 实验方案
      notes.md                       # 研究笔记
      others/                        # 其他实验资料

    deliveries/<阶段>/<修订>/         # 阶段报告及交付回执
    decisions/                       # 正式用户决定
    freeze_requests/<请求ID>/         # 冻结请求及事务记录

    assets/
      data/                          # 数据资产
      runs/<实验>/<运行>/             # 运行结果、搜索数据库及检查点
      evidence/<实验>/               # 显式发布的正式证据
      candidates/<候选>/             # 候选载荷、源码及依赖快照
      deliveries/<阶段>/<修订>/       # 完整机器交付包
```

各批次从对应的`HANDOFF.md`接续；历史批次的实际布局以其交接记录和引用为准。

研究方法与职责见[RSCH指南](RSCH_AGENT.md)，市场差异见[A股补充](guides/CN_RESEARCH.md)和
[美股补充](guides/US_RESEARCH.md)，平台接口及证据契约见[TDR说明](../src/czsc_trader/README.md)。
