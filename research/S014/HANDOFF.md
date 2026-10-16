# S014 研究交接

## 当前身份

- 策略族：`S014 / 金牛化工A股个股技术可行性试点`；
- 初始范围：`["600722.SH"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "stage": "阶段一：数据与成交规则可行性准备",
  "objective": "核实单标的数据完整性及执行偏差，形成是否具备策略研发条件的判断；本轮不评价收益能力",
  "authorization": [
    "用户指定金牛化工为个股试点",
    "用户同意在codex/a-share-600722-pilot分支开展试点"
  ],
  "technical_window": {
    "start": "2020-01-01",
    "end": "2026-09-30",
    "basis": "研究员选取已结束完整季度作为准备期；不是独立封存样本"
  },
  "scope": {
    "symbols": [
      "600722.SH"
    ],
    "vendor": "项目既有Tushare权限",
    "new_data_sources": false
  },
  "budget": {
    "source_probes": 8,
    "dfls_upstream_call_cap": 50,
    "workers": 2,
    "models": 0,
    "account_evaluations": 0
  },
  "constraints": [
    "S013保持PAUSED",
    "不搜索策略及参数",
    "不修改平台",
    "不操作PTE或生产",
    "不读取其他研究批次数据"
  ],
  "pending": [
    "有真实成交约束的账户合同",
    "策略研究的经济目标、开发及封存范围",
    "跨角色DEV平台修改授权"
  ]
}
```

研究意图是可演化的人类语义。阶段目标和推进由用户确认；完成技术检验并取得用户对冻结计划的明确批准后，通过TDR公共冻结接口发布策略版本。
