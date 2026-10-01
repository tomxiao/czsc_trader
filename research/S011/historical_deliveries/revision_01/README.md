# S011 阶段二至四历史交付补全

本修订依据用户2026-10-01批准的顺序，先整理历史交付及迁移清单。标的为159326.SZ，开发截止日为2026-09-28。阶段二、三、四的原结论、失败档案、目标、排序和621选型决定保持原样。

## 交付入口

| 阶段 | 人工报告 | 机器产物 | 本次补齐的内容 |
| --- | --- | --- | --- |
| 二 | [组件报告](stage2/report.md) | [组件与实验索引](stage2/delivery.json) | 4个组件的定义、职责、期限、可得性、支持与反面证据，EX01—EX12研究路径 |
| 三 | [策略与优化报告](stage3/report.md) | [策略及搜索索引](stage3/delivery.json)、[达标配置映射](stage3/qualified_configurations.json) | 完整假设、573条评价的来源、26个达标参数、优化归因、停止依据及后续36配置范围 |
| 四 | [自检与决定报告](stage4/report.md) | [自检及决定索引](stage4/delivery.json)、[完整36配置面板](stage4/rankings.json) | 五项自检、全部排序、缺口、敏感性、用户选择及代价 |

机器产物的`record_kind=S011_HISTORICAL_STAGE_SUPPLEMENT`明确表示历史补充索引。`formal_delivery_status=NOT_PUBLISHED`：本目录未生成TDR `DeliveryReceipt`，未登记新版候选，也未取得新的阶段推进或冻结批准。后续正式交付通过TDR公共API发布到独立修订。

## 证据与验证

- [源文件索引](sources.json)按仓库相对路径和原始字节SHA-256锁定本次读取的材料；大体量账户及实验数据继续存于原档案，需要与本仓库和本地原始产物一起使用。
- [实验核验](verification.json)通过公共`validate_archives`核验全部28个S011档案，通过`load_experiment_input`核验21份已有执行回执。7个技术失败档案保留无成功回执状态。
- [专项核验](focused_validation.json)记录原阶段二、阶段四及收尾验证器的当前执行结果。归档完整性、研究数值复核与新契约可发布性分别表达。
- [迁移清单](MIGRATION.md)及[机器清单](migration.json)记录新契约需要的证据、平台差异、验收条件和权限边界。
- [本包清单](manifest.json)锁定报告、机器索引和构建代码。证据目录清理或内容变化会使后续核验失败；本次没有复制全部大体量档案。

本次只整理与核验已存在的开发池事实，没有新行情读取、参数提议、账户回测或统计覆盖扩张。已有覆盖缺口仍属于研究事实；交付整理完成不表示缺口已补测。

## 复核与复建

在仓库根目录、项目`.venv`环境执行：

```powershell
.\.venv\Scripts\python.exe -B research/S011/historical_deliveries/revision_01/src/build.py validate --package research/S011/historical_deliveries/revision_01
.\.venv\Scripts\python.exe -B research/S011/historical_deliveries/revision_01/src/build.py build --output .tmp/s011-history-rebuild
```

复建目标必须是尚不存在的`.tmp/`子目录。构建器按原源数据生成报告、机器索引并运行公共档案校验；专项核验记录以本包所保存的结果为证据，复建不会自动重新执行其历史脚本。专项命令见`focused_validation.json`，均为只读核验。已有修订禁止覆盖，材料发生变化应建立后继修订。

## 研究结论与下一步

阶段二支持4项限定职责的开发组件。阶段三证据支持同一完整策略表达的两类收益／回撤取舍。阶段四保留36配置的比较及覆盖限制，用户选定`S011-CFG-000621`，原第一层收益优先顺序仍为618、624、621、628。全部证据属于已见开发池。

下一步先评审迁移清单中的目标与排序契约差异，再建立新受管评价和正式阶段交付。既有选择的历史记录可继续引用，绑定新交付与新内容身份的用户决定须明确核对确认范围。
