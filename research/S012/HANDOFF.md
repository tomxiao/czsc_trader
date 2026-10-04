# S012｜518850.SH 阶段二交接

## 当前增量：全历史日内数据门

EX012_20261004的COMPONENTS修订1为BLOCKED，交付FULL核验与EX012档案核验PASS。
完整历史价格修复尚未达成：518850的7日5分钟成交量错误已用1分钟修复，仍有52日价格跨周期冲突；未开展任何日内收益检验。
518880参考ETF全历史73680根/1535日校验通过。原组件面板仍为EX010，不因本轮空增量面板失效。

- [本轮报告](../../experiments/S012/EX012_20261004/04_conclusion.md)
- [交付核验](materials/intraday_data_gate_v2_validation.json)、[档案核验](materials/intraday_archive_v2_validation.json)
- [独立来源探查](materials/independent_source_probe_20261004/summary.json)
- 当前精确交付哈希：68b039e183d50562596cd40ec256ef96c42b8e2fc6accdc86043d4538b88948f。

用户要求先解决全历史数据，再检验收益；已允许独立来源、付费另确认。
免费来源未取得三个代表日分钟数据，富途现有服务缺A股ETF行情权限。用户暂无其他来源，将自行联系Tushare申请修复。
下一步：取得可追溯修订数据或独立分钟证据后，创建后继实验复验完整历史。
EX011执行回执与交付有效，但档案因执行文档文件名不符合契约而失败，原件保留；由EX012补齐可复验归档，不宣称全库档案通过。
本轮DFLS新增未复权分钟和显式市场观察时间假设，30项聚焦测试通过。研究分支codex/s012-stage2；无推送、合并或生产变更。

## 前轮组件结论（EX010）


本轮机会优先迭代已完成。当前交付为EX010的COMPONENTS修订1，完整度COMPLETE、FULL技术核验PASS。
找到一个有条件的低频机会候选：人民币贬值较强时，ETF三日回调后的约3—5日修复。
保守时间口径下5日净事件均值0.779%、匹配毛增量0.722%；q=0.280。前收盘限价去重容量约1.10次/60日。
原波动、趋势后回撤、冲击集中度仍为风险/状态辅助。当前机会覆盖不足，不建议直接进入阶段三。
阶段一修订3继续有效，三个账户经济目标均未在完整策略中验证；无候选或冻结版本，阶段三尚未授权。

## 权威入口

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

研究分支codex/s012-stage2；本轮按既有DEV授权修改DFLS时间契约，22项聚焦测试通过。
全部历史为开发池。2020-2021用于年度阈值训练，具体有效日期与标签尾部损失见当前报告。
各实验artifacts及交付实验副本仅在本机，Git不包含完整数据制品；跨机器恢复需同步完整S012前驱链并核验哈希。
未推送、未合并、未部署。没有配置外部备份目的地。

## 下一步

优先补充可核验时点的黄金/ETF日内独立机会，先确认历史覆盖与可得时间，避免靠放宽弱条件凑交易频率。
若考虑进入阶段三，必须取得用户批准并绑定当前精确交付；须验证限价成交、费用、资金、交易单位及三个账户目标。
新增外部供应商或依赖仍须另获授权。
