# S013阶段三修订三：动量状态分工与亏损年份盈利

本次继续阶段三后，累计494个不同配置完成完整账户评价，其中本次新增116个。全部四项目标同时达标10个；全部保留并交接。

## 目标与评价口径

沿用MANDATE/4：开发池整体净年化≥10.8342%（1.5×同窗BuyHold的7.2228%）；逐自然年最大回撤幅度严格更小；平均每60交易日闭合交易数≥4（1636日至少110笔）；BuyHold年度实际净收益<0时，策略同年实际净收益严格>0。未新增经济否决项。

自然年收益从初始资金或上一年末权益计算，扣费后现金和持仓跨年连续，2026年只到9月30日；全年展示实际收益，整体年化仍用252/1636折算。基准亏损年份为2022、2023，判断使用未舍入数值。

510500.SH，2020-01-01至2026-09-30，首个交易日2020-01-02；100万元、100个研究单位整手、每侧10bp、只做多、不加杠杆。HFQ_RESEARCH在2019-12-31以0.2803因子固定归一化，策略和基准共用价格、资金、费用与日历。收益不直接代表真实ETF份额账户收益；PTE/SRT执行仍输出未复权价格。

## 机制与竞争解释

旧高收益C0385在2022年价格损失和费用均为负面贡献；2023年微弱价格收益被费用吞没。原相关性过滤路线C0315两年盈利，但只有56笔闭合交易。第一组34个单路线过滤/持有期对照未同时达标，说明单纯强化过滤付出了整体收益或频率代价。

新策略使用T日已知的过去20日动量选择入场路线：动量≥阈值走较宽松的180日区间路线，否则走120日区间且要求20日收益一阶相关性≥门槛的路线。入场时锁定路线；区间到达退出线、持有期限或启用的损失控制触发退出。可选在动量状态改变时退出。没有读取未来年度BuyHold盈利标签或按年份硬编码路由。

三组相同路线FULL控制通过：原非ID字段、逐日账户、订单、成交与交易精确一致，新增状态诊断单列；独立候选和结果哈希均保留。此项验证组合实现，不宣称两个不同特征集合在SE全证据中等价。

C0440与C0439只有“状态改变时退出”不同：2022收益从-13.8044%变为+7.9616%，2024从+42.6235%变为+58.7042%；2023却从+0.8199%降至+0.3029%，2021也下降。状态退出在观察到的账户中改变入场/退出和后续仓位路径，不能分离成一个独立市场因子的收益；改善并非逐年一致。详细每日价格与费用归因见关联材料。

两次准备的整体身份不同，剔除策略身份后的输入计划相同；已通过公共DFLS fetch验证calendar/daily/execution逐值相等，daily含180条2019年预热记录。执行输入的四项身份也一致。归因支持同一已见开发池内完整退出政策的影响，不推断未见环境中的因果效应。

C0440在2023年净利润仅4253.89元：1月盈利60542.65元，其余月份合计亏损56288.76元；算术剔除最大盈利周期后年度收益会变为-2.1874%。2024最大盈利周期占该年净利润62.8270%，前三周期占88.7875%。这些是收益依赖诊断，未重跑“跳过该交易”的反事实账户，也未新增经济淘汰门。

## 全部达标配置

| 候选 | 净年化 | 闭合交易 | 每60日 | 2022收益 | 2023收益 | 最小逐年回撤优势 | 完整账户 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| C0440 | 13.7375% | 113 | 4.1443 | 7.9616% | 0.3029% | 7.1687个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/86267ffbd3fc5c00a256cc8c688a7d41fca292a319aa61eaf022ae3b2ac2adee.json) |
| C0472 | 11.3437% | 114 | 4.1809 | 1.6192% | 0.5498% | 4.1209个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/5963b93901bce3aefe6c597f7036cf114dda4b81e43947ea96bd871be82f9415.json) |
| C0494 | 13.9456% | 116 | 4.2543 | 7.9588% | 0.3054% | 7.1690个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/126f5da0a8282cae70311f432f02c51f9e3e5054bf8a39c6f64a8437c32f008d.json) |
| C0496 | 13.3924% | 113 | 4.1443 | 7.4082% | 0.3036% | 7.1813个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/04310b8e7eef172a3a9bd72cfaa57551fbddcc1ce673e1e06d6e680374710762.json) |
| C0503 | 13.4887% | 116 | 4.2543 | 7.9596% | 0.3038% | 6.5762个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/15c1bdb11f4733d01dcd97199e0c24e14b00168d0e29d7bd7375854b8e09fdc0.json) |
| C0504 | 13.4887% | 116 | 4.2543 | 7.9596% | 0.3038% | 6.5762个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/96e54ee8c814242e0bff43c65557daea3ae1c6f52115761917d28a884c219dfc.json) |
| C0505 | 13.4887% | 116 | 4.2543 | 7.9596% | 0.3038% | 6.5762个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/7da65d9a8f7dc022a3329e5ec1eddc61f2afead2d78cc436d211e1edddb09378.json) |
| C0506 | 13.4887% | 116 | 4.2543 | 7.9596% | 0.3038% | 6.5762个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/10c5aee918bc117be42101ddb96dd0aa301b99ef7a7ba8cba5eccdea49093748.json) |
| C0507 | 10.9939% | 117 | 4.2910 | 1.6228% | 0.5500% | 4.1211个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/5e97627763d38a31807928a37ff061f1e1702b323826f104860c3dd6c7aefc00.json) |
| C0509 | 10.9939% | 117 | 4.2910 | 1.6228% | 0.5500% | 4.1211个百分点 | [账本](../../../assets/deliveries/CANDIDATES/3/evidence/1b926a7e7f8536a1fb88c2e62b1f75cacc022ab5cb15b6fecd4e43dd967bdc28.json) |

下面列出完整参数相对C0440的变化，所有正式身份包含源码和依赖；没有以相同表现合并不同配置。

C0440：bull窗口180、入场0.675、退出0.95、最长信号持有8日、无相关性/动量/止损过滤；bear窗口120、入场0.85、退出0.99、最长4日、ACF门槛0.1；动量窗口20、阈值0、状态改变退出；共同限价溢价1%、冷却0。

| 候选 | 相对C0440参数变化 |
| --- | --- |
| C0440 | 中心配置 |
| C0472 | regime_threshold=0.005 |
| C0494 | bear.entry=0.9 |
| C0496 | bull.limit_premium=0.015；bear.limit_premium=0.015 |
| C0503 | bear.entry=0.925 |
| C0504 | bear.entry=0.95 |
| C0505 | bear.entry=0.975 |
| C0506 | bear.entry=0.985 |
| C0507 | bear.entry=0.95；regime_threshold=0.005 |
| C0509 | bear.entry=0.985；regime_threshold=0.005 |

## 自然年策略与基准比较

C0440作为机制对照中心展示；这不是阶段四正式排序或选型。

| 年份 | BuyHold净收益 | C0440净收益 | BuyHold回撤 | C0440回撤 |
| --- | ---: | ---: | ---: | ---: |
| 2020 | 22.1821% | 15.4433% | 14.9790% | 7.0915% |
| 2021 | 17.2432% | 12.6789% | 9.7079% | 2.5392% |
| 2022 | -18.3277% | 7.9616% | 28.4220% | 10.1465% |
| 2023 | -6.2480% | 0.3029% | 17.2743% | 5.6548% |
| 2024 | 6.9596% | 58.7042% | 18.5832% | 10.0227% |
| 2025 | 32.7258% | 8.3172% | 13.8038% | 3.5331% |
| 2026（至9月30日） | 0.9951% | -4.7535% | 18.7703% | 9.8858% |

## 前沿与必要反证

先满足逐年回撤与负基准年份盈利，在收益/截断到4的平均频率上保留非支配点；并保留全部四项目标达标配置及必要反证。阶段三展示，不是阶段四排序。

| 配置 | 净年化 | 闭合交易 | 2022收益 | 2023收益 | 未通过要求 |
| --- | ---: | ---: | ---: | ---: | --- |
| C0058 | 7.3743% | 47 | 3.4953% | 4.0519% | 整体收益、逐年回撤、平均频率 |
| C0315 | 7.5450% | 56 | 0.6972% | 7.2238% | 整体收益、平均频率 |
| C0385 | 13.5570% | 111 | -18.4954% | -3.9663% | 负基准年份盈利 |
| C0439 | 5.9792% | 94 | -13.8044% | 0.8199% | 整体收益、平均频率、负基准年份盈利 |
| C0440 | 13.7375% | 113 | 7.9616% | 0.3029% | 无 |
| C0444 | 14.7630% | 95 | 6.1881% | 1.6646% | 平均频率 |
| C0472 | 11.3437% | 114 | 1.6192% | 0.5498% | 无 |
| C0474 | 14.3313% | 105 | 13.4870% | 1.7297% | 平均频率 |
| C0488 | 16.2900% | 108 | 5.6110% | -0.7708% | 平均频率、负基准年份盈利 |
| C0494 | 13.9456% | 116 | 7.9588% | 0.3054% | 无 |
| C0496 | 13.3924% | 113 | 7.4082% | 0.3036% | 无 |
| C0503 | 13.4887% | 116 | 7.9596% | 0.3038% | 无 |
| C0504 | 13.4887% | 116 | 7.9596% | 0.3038% | 无 |
| C0505 | 13.4887% | 116 | 7.9596% | 0.3038% | 无 |
| C0506 | 13.4887% | 116 | 7.9596% | 0.3038% | 无 |
| C0507 | 10.9939% | 117 | 1.6228% | 0.5500% | 无 |
| C0509 | 10.9939% | 117 | 1.6228% | 0.5500% | 无 |

## 搜索与选择历史

| 搜索组 | 实际评价尝试 | 成功不同配置 | 四门达标 |
| --- | ---: | ---: | ---: |
| four_gate_acf_1 | 34 | 34 | 0 |
| four_gate_adaptive_1 | 39 | 39 | 1 |
| four_gate_adaptive_entry_extension | 8 | 8 | 6 |
| four_gate_adaptive_followup_1 | 34 | 34 | 3 |
| four_gate_premium_controls | 1 | 1 | 0 |
| hfq_followup_1 | 60 | 60 | 0 |
| hfq_followup_2 | 11 | 11 | 0 |
| hfq_followup_3 | 22 | 22 | 0 |
| hfq_followup_4 | 15 | 15 | 0 |
| hfq_initial | 1 | 1 | 0 |
| hfq_replay_completion | 24 | 16 | 0 |
| hfq_replay_recovery4 | 22 | 22 | 0 |
| old_configuration_hfq_replay | 239 | 231 | 0 |

旧378个成功配置重新套用四项字面条件，16次UNKNOWN原状态保持。固定对照和扩边在执行前发布，以Optuna固定队列及参数哈希去重；种子13，最多4个spawn进程、每个原生线程1、单请求workers=1、每个父进程只评价一批。重复点复用同内容同口径结果。不同源码的相同路线账户仍独立评价。

本次根据已见亏损归因选择动量分工，根据初次达标点设计相邻对照、持有期扩边和交互。全部开发池持续用于方法和参数选择，没有独立封存验证样本。年度约束检查不等于样本外检验；达标数量不能解释为独立发现数量或未来成功概率。

## 数据、执行及未解决问题

沿用本批次数据与准备引用。已声明的五处残余偏差位于30分钟聚合相对可信独立日线的High/Low，日线组件来源为ETF_OHLCV daily；四处分钟High未进入日线区间特征或LIMIT买入/MARKET卖出撮合。对当前494个成功配置逐单复核2020-12-01分钟Low偏差，发现可能改变已发生订单成交金额的订单0项；仅覆盖已声明偏差及真实订单，没有重建未知分钟修复路径或供应商历史版本。

供应商复权因子历史发布时间、修订和真实馈送延迟未重建。最长持有期、止损及冷却仍按信号目标序列，不按限价实际成交日期重置。部分配置在基准上涨年份跑输；C0440在2026前九个月为-4.7535%，而基准为+0.9951%。这些观察保留在报告中，不擅自增加硬门。

本次未修改平台或新增数据/依赖。未执行仓库全量回归；阶段四五项标准自检、正式排序、技术冻结和真实ETF份额PTE评价尚未开展。

## 收口依据与下一步

# 四项约束下阶段三收口判断

建议结束本次机制构建与局部优化，向用户申请进入阶段四标准自检。此判断依据已验证的改善机制、竞争解释、扩边结果和剩余不确定性；10个达标点与116次新增完整账户评价本身不足以证明研究充分。

## 已验证方向

- 单路线相关性过滤和短持有期能取得负基准年份正收益，但34个新对照没有同时维持原收益、回撤和频率目标。必要反证说明过滤付出了机会与周转代价。
- 39个状态分工对照中，原高收益路线与相关性路线组合、允许状态变化退出时出现C0440。三组相同路线控制逐项复现原账本；C0439/C0440同源输入含2019预热精确相等，只有状态退出布尔参数改变。
- 退出政策在2022年提升价格贡献23.6619个百分点，同时增加费用1.8959个百分点，净改善21.7660个百分点。2023价格改善小于额外费用，因此该年反而退化；不是纯粹费用节省，也不是逐年一致的改进。
- 34个相邻与扩边对照检验了动量窗口5/10/15/25/30/40/60、阈值±0.5%/±1%/±4%、负动量持有期1/2/3/5/12、相关性门槛、上涨持有期与入场线、共同限价和六个持有期×阈值交互。新达标C0472、C0494、C0496与C0440一并保留；负向阈值、相邻窗口、较短持有期及低溢价的失败均保留在搜索材料。
- 对C0494的bear入场0.90上沿改善追加8个扩边/交互。0.925/0.95/0.975/0.985的收益13.4887%、116闭合和年度结果相同，较0.90的13.9456%下降，显示这条扩边的经济表现饱和；继续逼近退出0.99的逻辑边界没有当前改善依据。阈值+0.5%的交互两点也达标，3日持有交互两点未达收益要求。

全部四项目标同时达标10个不同参数配置，覆盖全部交接；七个前沿或必要反证一并保留。未以“只挑一个最好点”替代全部覆盖，未将达标后的更高频率增加为额外偏好。搜索未穷举所有可能组件与联合参数；没有宣称不存在更好的策略。

## 继续搜索的代价与当前缺口

当前已见开发池反复用于选择，直接围绕2023年小幅正收益继续细调，会加深对少量交易的依赖。C0440的2023净利润仅4253.89元，最大盈利周期的算术剔除会使该年转负；2024最大盈利周期占年度净利润62.8270%，前三周期占88.7875%。这些诊断解释脆弱性，不能替代真实扰动账户，也不新增经济硬门。

多个达标配置经济结果相同或接近，均属于共同机制研究族；10个配置不能理解为10次独立发现。动量期限与阈值相邻失败提示参数敏感性；2026部分年度仍亏损、2025明显跑输基准提示择时机会成本。供应商因子历史可得性、真实份额执行收益和限价成交与信号锚点差异仍未解决。

目前已有足够完整的可执行对象和反证，下一步更有价值的是按已规定的五项自检量化参数、时间、收益集中、执行和统计不确定性，而非继续用同池细调掩盖这些问题。阶段三局部对照未替代阶段四联合扰动、正式精度政策或排名。

## 下一步和重启条件

向用户申请进入阶段四，覆盖全部10个达标候选，按现有RSCH标准政策完成五项自检、七项排序证据、行为分组和敏感性说明。重点确认2023盈利余量与额外费用、2024收益集中及动量状态的稳定性，不自行增加淘汰硬门。

若阶段四揭示对精确阈值、个别交易或撮合边界的依赖，应明确呈现并建议回到阶段三或阶段二；有可解释的额外收益/风险机制、已获批准的新增数据或平台能力时，再提出相应重启设计。独立样本和真实ETF份额评价须另立授权及比较边界。当前尚未进入阶段四，不执行冻结、生产或Git发布。

## 关联证据

- [stage-two-data](../../../assets/deliveries/CANDIDATES/3/evidence/304cd281e0cde1850650b0dcc07aaad9f64c1621672d8b4606d84654f786c3ee.json)
- [four-gate-search-results](../../../assets/deliveries/CANDIDATES/3/evidence/949368ac6e7006cbee3e48c8d5272fc47eee60181f47236ef66e47146785f57f.json)
- [four-gate-search-analysis](../../../assets/deliveries/CANDIDATES/3/evidence/d91e72526977aceadab3a1f52217333825c6fd890f85fd8638c339a1cbda4ed2.json)
- [four-gate-quality-impact](../../../assets/deliveries/CANDIDATES/3/evidence/e44df456c81c4813c9d5bad256ec08ec70a0378a2c32fa72f684c855404ed17a.json)
- [four-gate-loss-diagnostics](../../../assets/deliveries/CANDIDATES/3/evidence/398dab96565f1fbad004ce1aebe07e1d33841b0d59bc0a953f0229ecd826938f.json)
- [four-gate-adaptive-controls](../../../assets/deliveries/CANDIDATES/3/evidence/39b35a1f02c7c0ffeb03e740c899778f56b7135ffbc61be6ae24b2142f948316.json)
- [four-gate-adaptive-attribution](../../../assets/deliveries/CANDIDATES/3/evidence/5e0c87ad94ae1cdd55a42ef2640322dc0ff108dabddbca425e609f77fea9d35c.json)
- [four-gate-adaptive-input-control](../../../assets/deliveries/CANDIDATES/3/evidence/d8ca5fefeabf7630a4038731ca31f8b465e130726c6de6a6e6bef0503b64f0be.json)
- [four-gate-acf-1-plan](../../../assets/deliveries/CANDIDATES/3/evidence/9b1b82bf693c76232877103a4daa347c9444ffcf2f8809ef6ab004e2c4dc8e0e.json)
- [four-gate-acf-1-coverage](../../../assets/deliveries/CANDIDATES/3/evidence/66f2bd4a63216218449545aa67eaa5388b32dc3745658089c5b9d30d2e9ca38d.json)
- [four-gate-adaptive-1-plan](../../../assets/deliveries/CANDIDATES/3/evidence/2fcc84e5f58c84264144c0773539170c391da917d2a666b44b1795ade54fd11b.json)
- [four-gate-adaptive-1-coverage](../../../assets/deliveries/CANDIDATES/3/evidence/9a8b08bd7f0fc066b9cea3ca0b07fe6e8382555fa935b133cc9c7e6cb8f18784.json)
- [four-gate-adaptive-entry-extension-plan](../../../assets/deliveries/CANDIDATES/3/evidence/18e2e01a64dd17d17050a028ba4831d28cfa2b7e8b8d99f40228ce373505c863.json)
- [four-gate-adaptive-entry-extension-coverage](../../../assets/deliveries/CANDIDATES/3/evidence/fe63948ff92d232777dafaeb147f2f4b3c2b008c49c2b8a5fa14807fa8246684.json)
- [four-gate-adaptive-followup-1-plan](../../../assets/deliveries/CANDIDATES/3/evidence/bd42539b0663f7cf4cc3db64a2753f6a7ad5727dde110149486d0c1511c32eca.json)
- [four-gate-adaptive-followup-1-coverage](../../../assets/deliveries/CANDIDATES/3/evidence/656e979bf843ea35d8c67b94023a6113d5c659b25f70db5e679ebf5dda3a15eb.json)
- [four-gate-premium-controls-plan](../../../assets/deliveries/CANDIDATES/3/evidence/2a01a8b73d324bf839f7c952536f289650155feaf70d4134a7addd7528981026.json)
- [four-gate-premium-controls-coverage](../../../assets/deliveries/CANDIDATES/3/evidence/b04484ed6b498649c4ad5eb68071fb12a7b57020d6a428d80c84f4c874fda5e3.json)
- [four-gate-stopping-review](../../../assets/deliveries/CANDIDATES/3/evidence/9a57ffd93b486e3bf16cf9c7dea99b015f71e7aa13c3cb0e24d9cf764626eaac.md)
- [four-gate-continuation-authorization](../../../assets/deliveries/CANDIDATES/3/evidence/49dec35af4f4b26781f76462be221979ac938c13a3a405251ce43d9c928572e9.json)
- [four-gate-reproduction-sources](../../../assets/deliveries/CANDIDATES/3/evidence/72376d002e46adc179ab35d149a38ab3f7fcf6d11d6b7c6dfee4142b25c7d5df.json)
- [control-account-c0385](../../../assets/deliveries/CANDIDATES/3/evidence/53a2a66fdbb9cd58925ac37c5f6acec84f59feb6b39bdd92a39ba5d26295f1bb.json)
- [control-account-c0430](../../../assets/deliveries/CANDIDATES/3/evidence/e1f9c05baec4433befb59f4f67938852b245e0921b5f9aa5d9a9aa863fa1d289.json)
- [control-account-c0426](../../../assets/deliveries/CANDIDATES/3/evidence/da42555e35650e969457687d26d9515de67cbe22ed665f733b86e039d19a2e3e.json)
- [control-account-c0431](../../../assets/deliveries/CANDIDATES/3/evidence/88f42e2c184828e61ffe68b967f6cec4c779911de6a998a5d98772c799d3008a.json)
- [control-account-c0429](../../../assets/deliveries/CANDIDATES/3/evidence/de5b15c11f60b865f860f99775377230a858cc570aee377b1f2b75e42c8778a7.json)
- [control-account-c0432](../../../assets/deliveries/CANDIDATES/3/evidence/169d3ccb27a29a57f5d349d9d0981d52fb1c720ab7d22d5534668d6c5acfcbd3.json)
- [four-gate-selected-account-references](../../../assets/deliveries/CANDIDATES/3/evidence/d170f94380efc4f015beb922fb41359057780f4e4c8c9075499f38846ce76bce.json)
