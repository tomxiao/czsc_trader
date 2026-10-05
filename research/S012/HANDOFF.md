# S012｜518850.SH 阶段二交接

## 当前状态：阶段二研究进行中（2026-10-05）

用户明确要求“提交研究员Agent文档。新开分支继续S012的研究工作”。研究员Agent文档已提交为`41c7f25b`，当前分支`codex/s012-research-resume`，登记恢复为`RESEARCHING`。标的518850.SH、阶段一修订3的三个经济目标及全部上市历史开发池保持；采用T日收盘后决策、T+1执行的日频研究口径，未进入阶段三。

- [恢复授权](materials/resume_authorization_20261005.json)、[最小DEV性能修复授权](materials/dev_performance_authorization_20261005.json)。
- EX013全历史正式数据门通过：1535日日线完整率/准确率100%；5分钟完整率100%、准确率1483/1535=96.6124%；30分钟完整率100%、准确率1509/1535=98.3062%。保持DFLS现有容差，52日及26日异常明细保留，不能解释为独立真值修复。
- [数据门报告](../../experiments/S012/EX013_20261005/04_conclusion.md)、[独立重算](materials/resume_data_independent_verification_20261005.json)、[档案核验](materials/resume_data_archive_validation_20261005.json)。
- EX014固定“收盘前相对落后”机制主检验FAIL：8个事件，3日平均净收益0.0355%、年度匹配费用后增量-0.1189%；异常排除后7个事件增量转正，结果敏感。限价触价容量0.1173次/60日；与O01事件不重叠，但3日并集容量仅1.0945次/60日。
- [机制报告](../../experiments/S012/EX014_20261005/04_conclusion.md)、[增量COMPONENTS](../../experiments/S012/EX014_20261005/deliveries/COMPONENTS/1/report.md)、[交付核验](materials/relative_lag_delivery_validation_20261005.json)、[档案核验](materials/relative_lag_archive_validation_20261005.json)。EX010原面板保留，本轮负结果完整留证，未完成账户三个经济目标验证。
- 用户另授权暂切DEV，两处校验局部副本清空attrs以避免pandas逐行/分组重复复制整窗元数据。提交`7a053451`，63项聚焦测试、Ruff及真实日线元数据保持验证通过；未变更价格、容差或质量判据。原未完成执行空间保留，独立新空间重试EX013约101秒完成三请求执行。

当前人工结论和正式增量以EX014为准，既有有效O01组件仍以EX010为准；暂停时EX012的历史阻断结论保持。新分支及本轮提交均在本地，正式数据制品及交付实验副本由Git忽略，跨机器复验需要同步S012真实制品和前驱链。

## 历史暂停记录（2026-10-04）

用户于2026-10-04明确要求“暂停S012，合并到master”。登记状态为`PAUSED`，停止研究和数据排查，等待用户明确恢复。
标的仍为518850.SH，518880.SH仅完成替代可行性的数据诊断，未切换标的、未进入阶段三。
暂停时收口分支为master；既有实验、交付和阶段一合同保持原样。该暂停已由上述2026-10-05恢复授权撤销。

- [暂停授权](materials/pause_authorization_20261004.json)
- [暂停时的数据诊断摘要](materials/pause_data_diagnostics_20261004.json)

EX012之后的DEV补充核验发现：518880在2020-01-02至2026-09-30的1636日数据完整，已有修复后的1/5/30分钟通过现有校验；
进一步检查仍有91日高低价差异、56根1分钟及3根5分钟量价不一致。TDX日线与Tushare原始日线价格一致，未支持本地三个日线修复值；
五个目标日期的TDX分钟导出均为空。通过现有容差校验不代表这些问题已经解决。
补充核验仅为DEV诊断，原始大数据制品留在本机临时目录，不能替代正式研究证据。

## 历史封存增量：全历史日内数据门（EX012）

EX012_20261004的COMPONENTS修订1为BLOCKED，交付FULL核验与EX012档案核验PASS。
完整历史价格修复尚未达成：518850的7日5分钟成交量错误已用1分钟修复，仍有52日价格跨周期冲突；未开展任何日内收益检验。
518880参考ETF全历史73680根/1535日校验通过。原组件面板仍为EX010，不因本轮空增量面板失效。

- [本轮报告](../../experiments/S012/EX012_20261004/04_conclusion.md)
- [交付核验](materials/intraday_data_gate_v2_validation.json)、[档案核验](materials/intraday_archive_v2_validation.json)
- [独立来源探查](materials/independent_source_probe_20261004/summary.json)
- 当前精确交付哈希：68b039e183d50562596cd40ec256ef96c42b8e2fc6accdc86043d4538b88948f。

用户要求先解决全历史数据，再检验收益；已允许独立来源、付费另确认。
免费来源未取得三个代表日分钟数据，富途现有服务缺A股ETF行情权限。用户暂无其他来源，将自行联系Tushare申请修复。
暂停时建议：取得可追溯修订数据或独立分钟证据，再创建后继实验复验完整历史；数据到达不自动恢复研究。2026-10-05用户明确恢复后，按新确认的统计验收口径完成EX013，结果见本文件首节。
EX011执行回执与交付有效，但档案因执行文档文件名不符合契约而失败，原件保留；由EX012补齐可复验归档，不宣称全库档案通过。
该轮DFLS新增未复权分钟和显式市场观察时间假设，30项聚焦测试通过。

## 前轮组件结论（EX010）


本轮机会优先迭代已完成。当前交付为EX010的COMPONENTS修订1，完整度COMPLETE、FULL技术核验PASS。
找到一个有条件的低频机会候选：人民币贬值较强时，ETF三日回调后的约3—5日修复。
保守时间口径下5日净事件均值0.779%、匹配毛增量0.722%；q=0.280。前收盘限价去重容量约1.10次/60日。
原波动、趋势后回撤、冲击集中度仍为风险/状态辅助。当前机会覆盖不足，不建议直接进入阶段三。
阶段一修订3继续有效，三个账户经济目标均未在完整策略中验证；无候选或冻结版本，阶段三尚未授权。

## EX010历史组件面板入口

| 事项 | 入口 |
| --- | --- |
| 当前人工研究报告 | [机会研究结论](../../experiments/S012/EX010_20261004/04_conclusion.md) |
| 当前正式组件报告 | [COMPONENTS修订1](../../experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/report.md) |
| 当前合同与回执 | [delivery.json](../../experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/delivery.json)、[receipt.json](../../experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/receipt.json) |
| 已批准阶段一合同 | [修订3](mandates/3/report.md) |
| 当前注册意图 | [family.json](../registrations/S012/family.json) |
| 阶段二初始授权 | [用户指令](materials/stage2_authorization_20261004.json)、[阶段推进决定](decisions/S012-STAGE2-20261004.json) |
| 本轮继续授权 | [机会优先用户指令](materials/opportunity_authorization_20261004.json) |
| 当前交付验证 | [FULL验证](materials/components_opportunities_v2_validation.json)、[10档案验证](materials/opportunity_archives_validation.json) |
| 当前实现与协议 | [delivery.py](../../experiments/S012/EX010_20261004/delivery.py)、[固定协议](../../experiments/S012/EX010_20261004/02_design.md) |
| 当前机会台账 | [汇率168路径](../../experiments/S012/EX010_20261004/artifacts/rex/fx/opportunities.json)、[境外黄金96路径](../../experiments/S012/EX010_20261004/artifacts/rex/gold/opportunities.json) |
| 反证与容量 | [年度](../../experiments/S012/EX010_20261004/artifacts/rex/fx/annual.json)、[252项敏感性](../../experiments/S012/EX010_20261004/artifacts/rex/fx/sensitivity.json)、[36项限价诊断](../../experiments/S012/EX010_20261004/artifacts/rex/fx/limit_events.json) |
| 旧风险/状态面板 | [EX005结论](../../experiments/S012/EX005_20261004/04_conclusion.md) |

精确引用：owner=ExperimentOwner(S012, EX010_20261004)，stage=COMPONENTS，revision=1，
content_sha256=fdf27e7c93e9f73b0ed6ae9b3b6d77f6e42451b1d0d0bdc18b6140c6bcdff532。

## 时间与证据边界

FXCM源日期可能标记跨日K线起点。EX008的境外黄金强信号被隔离；EX006/007涉汇率结论须以EX010重算为准。
DFLS已增加AvailableDate=源日后2自然日08:00中国时间，明确为保守研究政策，历史逐日发布时间未核实。
旧缓存和旧发布不自动兼容新时间契约；本轮用s012-fx-availability-v2缓存命名空间。
EX009因报价计数快照修订停止，无收益结果；EX010证实全部OHLC与日期不变，计数修订单独保存。
所有已封存实验保持原样；平台PASS不代表时间语义、机会充分性或账户目标达成。

机会研究轮按既有DEV授权修改DFLS时间契约，22项聚焦测试通过。
全部历史为开发池。2020-2021用于年度阈值训练，具体有效日期与标签尾部损失见当前报告。
各实验artifacts及交付实验副本仅在本机，Git不包含完整数据制品；跨机器恢复需同步完整S012前驱链并核验哈希。
2026-10-04暂停收口时仅合并至本地master，当时未推送、未部署。没有配置外部备份目的地。

## 下一步

继续阶段二独立机会来源研究，优先解释能提高限价实际成交密度的经济机制，再预注册可证伪实验；保留EX010的O01及本轮EX014负面证据，停止沿本轮固定机制继续放宽条件。全历史数据已按用户确认的现行DFLS规则通过，异常与实时可得性限制继续披露。
更换研究标的、修改既定目标或进入阶段三仍须取得用户批准。
