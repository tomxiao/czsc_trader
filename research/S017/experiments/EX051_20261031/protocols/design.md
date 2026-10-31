# EX051：完整排除入场区间的结构观察边界

Status: PREDECLARED；阶段二4个有效经济配置边界修订+1旧C108技术复算。0新增入场机制、0搜索、无timecap。

## 这组尝试什么

原2x2的收益来自收复后延续，支撑或在严格三点更高Low被右柱确认便抬升，或等Close重新超过截至left的推进High才接受。独立审阅发现公开BAR_INTERVAL成交的cycle_entry是entry interval起点，并非精确成交时刻；原BarStart>=cycle_entry不能普遍保证entry整柱的High/Low均来自实际买入后。原源/账户/已发布报告与审计保留，不能覆盖为修正结果。

原factual路径的所有BAR_INTERVAL在候选/抬线影响计数为0，不能说已证实partial污染旧收益。统一strict>还排除合法OPEN entry完整柱，实际会改变OPEN相关候选/抬线，故本轮是明确的保守完整政策边界修订，不是纯技术等价修复，不预称经济不变。

## 精确规则与最小组

原[EX050精确金融规则](../../EX050_20261031/protocols/design.md)中M005/M006入口、冻结S0、strict三点、候选L/H冻结/更高小pivot忽略/Low<L先撤/同右Close>H可接受、单向支撑/strict失效/due锁存全部保持，唯一经济差异：

- pivot左柱资格改left.BarStart>portfolio.cycle_entry；
- 峰值当前柱资格改current.BarStart>portfolio.cycle_entry。

无论OPEN还是BAR_INTERVAL，都保守排除整个entry interval，不编造精确成交时点。这是可观察的结构样本边界，不是最短持仓：S0自真实cycle激活即有效，若持仓第一次完成决策Close<S0可立即退出，没有强制等三柱/计时cap。只有支撑抬升与推进峰的结构素材排除entry整段，首次可用三点均来自其后完整柱。

- C109：旧C108 M006+ACCEPTED exact技术控制，直接使用冻结EX050 strategy.py原字节/原参数/原入口，定义sourceSHA447ea66a6b0a9cc18d12c72fa328f05680fbd1d30b6246f9619c1e55227925da。
- C110：M005+IMMEDIATE、strict整entry排除。
- C111：M005+ACCEPTED、strict整entry排除。
- C112：M006+IMMEDIATE、strict整entry排除。
- C113：M006+ACCEPTED、strict整entry排除。

四臂同一观察边界才能保留2x2金融依据，不按赢家只修一臂。控制与旧C108候选/买持六表12经济投影必须全部相等。source-dir控制由公共candidate显式绑定旧冻结src，其他四定义绑定新src，均V4公共账户，无私有回放或自编账户。

## 竞争解释、勘误与会改变的决定

原050独立边界检查：M005即时/接受与M006即时/接受都存在OPEN入场柱资格/候选H的改变；旧BAR_INTERVAL峰理论纳入但在候选前已被后续完整柱覆盖，不等于收益被污染。边界复核只算旧factual路径，不是新完整账户反事实。

原多期限3/13/26/65/130、旧17表达与M006七年负证/长130去重增量负、训练先看再选历史全部保留，不据最高标签选时间。确认支撑政策差异还含候选管理，不归因纯Close>H；边界排除也会改资金/后续成员，不称同笔纯因果。

若完整边界下仍保留可兑现收益及2x2依据，可交付值得进一步完善但未达标的金融原型，再向用户建议下一阶段明确批准，不继续为收益/25%回撤堆门或扫参数。若优势不保留，如实否定/收敛。旧36+12已WITHDRAWN，不实现/恢复；2026封存。

## 验证与固定合同

前检必须强制真实public LIMIT BAR_INTERVAL：entry bar Open>limit、Low<limit，查fill.time_precision/interval_start/executed_at及trade.entry_at区间起点；旧控制会纳该entry峰，新四臂第一held峰为0且不能作pivot左。不得只mock假设entry_at=interval_end。仍覆盖strict等号、真实post-entry三点、冻结H/同right升级/候选破优先、既存due不反悔、OPEN整段也排除，价格/量未来suffix不变、解释体积。旧控制源码SHA也绑定precheck。

全新100000空仓/周期，2024-01-02—2025-12-31训练、2023-11指标预热261，旧EX042 prepared；502日6490点443全滚窗，RTH30分钟/跨夜/全资金0或1只多/每侧.1%费/固定1%限价/下一段执行保持。原年化>=247.633956%、DD<=42.810252%且<=25%、60日闭合中位>=6且90%窗>=3全部同时验，不添每年/显著性硬门，末仓保留训练末估值不读2026。

5prepare READY+源绑定public前检+独立终审无阻断后唯一evaluate_many；5candidate共享买持共6compute，准备不算正式运行。完整V4/SE、公共配对诊断、独立strict边界/候选/峰与全部账本/443窗、旧050控制12经济投影、报告公开校验。正文四问，数据/选择史/反证与勘误集中附录。
