# S013：价格条件退出与参数交互对照

9个新配置全部完成，均未同时通过原四项经济目标。到期后等价格转弱退出的原背景配置年化更高、全窗回撤更低，但2023仍亏损；不能把单个漂亮指标视为稳健性改善。策略参数敏感性改善的总目标尚未得到证明。

身份RSCH、阶段三。用户明确授权“授权你可以自主完成目标，无需评审”，本轮自主执行；沿用S013已有资产、MANDATE/6及原四门，不推进PTE、冻结、生产或阶段五。

## 前瞻设计与执行

四背景B0=(过滤0.1、期限4日)，B1=(0.045、4日)，B2=(0.1、3日)，B3=(0.045、3日)。TIME为原到期退出，NONE为取消定时退出，DOWN为到期且收盘不高于前一实际交易日收盘才退出，UP为到期且收盘不低于前日才退出。相等时两者均退出。上涨路线、其他退出优先级、原水平买入确认保持；没有新增数值阈值或窗口。

16个展示格对应14个内容身份，5个历史账户精确核对后复用，9个新业务配置。新完整账户评价18次：2次串行/spawn预检、首次批量8次计算，以及结果保存脚本缺失key字段后对原8请求显式重跑。首次未保存的结果不作为证据；相同交易规则未调整，重复运行不算新发现。原前瞻预算10次及实际18次同时保留。

2020-01-02至2026-09-30、1636交易日、100万元、100个HFQ研究单位整手、每侧10bp、策略和LimitBuyHold统一1%限价溢价。T决策、T+1执行。只使用S013既有数据及预热，无外部提供者调用。研究账户不是真实份额PTE账户。

## 全矩阵

|背景|机制|身份|净年化|全窗回撤|闭合交易|2022收益|2023收益|四门|
|---|---|---|---:|---:|---:|---:|---:|---|
|B0|TIME|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|B0|NONE|C7201|16.5258%|22.9693%|84|10.3727%|-1.4742%|frequency、negative_buyhold_year_profit|
|B0|DOWN|C7300|17.7909%|13.1720%|110|12.0751%|-2.1142%|negative_buyhold_year_profit|
|B0|UP|C7301|11.7706%|17.2199%|106|4.4211%|-1.8063%|frequency、negative_buyhold_year_profit|
|B1|TIME|C7005|15.8174%|24.6200%|125|20.6159%|-1.9705%|annual_drawdown、negative_buyhold_year_profit|
|B1|NONE|C7203|17.6051%|21.7643%|89|10.2440%|1.5725%|frequency|
|B1|DOWN|C7302|11.8705%|23.1437%|120|10.3735%|-2.5938%|negative_buyhold_year_profit|
|B1|UP|C7303|12.5855%|19.3471%|117|12.3458%|-2.7358%|negative_buyhold_year_profit|
|B2|TIME|C7009|11.7652%|17.4850%|121|5.9394%|-1.9690%|negative_buyhold_year_profit|
|B2|NONE|C7201|16.5258%|22.9693%|84|10.3727%|-1.4742%|frequency、negative_buyhold_year_profit|
|B2|DOWN|C7304|12.0031%|23.8162%|115|12.5959%|-2.5302%|negative_buyhold_year_profit|
|B2|UP|C7305|13.9731%|20.2276%|114|12.1653%|-4.3163%|negative_buyhold_year_profit|
|B3|TIME|C7306|8.4482%|26.7916%|139|-1.7731%|-4.3671%|return、annual_drawdown、negative_buyhold_year_profit|
|B3|NONE|C7203|17.6051%|21.7643%|89|10.2440%|1.5725%|frequency|
|B3|DOWN|C7307|17.0372%|14.5168%|130|10.4075%|-1.9992%|negative_buyhold_year_profit|
|B3|UP|C7308|12.2913%|25.6452%|130|13.0902%|-5.7777%|annual_drawdown、negative_buyhold_year_profit|

四门仍是年化至少正收益基准1.5倍、各自然年回撤严格小于同期基准、每60交易日平均至少4笔闭合交易（本窗至少110笔）、基准亏损年2022/2023策略收益严格为正。全窗回撤只是诊断，不新增自动否决。

## 判断与最强反证

原背景DOWN年化17.7909%、回撤13.1720%，优于原中心16.1572%/14.1599%，闭合110笔刚好满足频率，但2023收益-2.1142%，经济目标未同时满足。B3-DOWN年化17.0372%、回撤14.5168%也未修复2023亏损。

全部新增方向配置2023亏损，不能仅因DOWN优于UP就把DOWN视为有效改进。B0-DOWN变为B1-DOWN的年化明显降低、回撤明显扩大；条件退出并未消除过滤门槛的交互敏感性。补齐的B3-TIME更差，证明两条敏感坐标不能仅按单独损失相加理解。

已有无定时退出周期中，到期日上涨组和下跌组延长持有后的平均周期收益都更好。这是有未来标签的描述，无法唯一支持“到期转弱卖出”的假说；本轮相反方向和完整账户是更强反证。旧周期利润不能直接相加作为新策略贡献。

删除过滤、删除定时退出、改变确认分方向、价格条件退出至此均未产生兼顾原四门的新机制。简单删参数或替换一个条件没有证明稳健改进；继续研究须解释如何同时保留过滤的风险控制、期限的周转价值，以及亏损年份的小盈利。

## 局部响应与持仓

- TIME，B0→B1：年化-0.3398个百分点；回撤+10.4601个百分点；交易+13笔。
- TIME，B0→B2：年化-4.3921个百分点；回撤+3.3252个百分点；交易+9笔。
- TIME，B0→B3：年化-7.7091个百分点；回撤+12.6318个百分点；交易+27笔。
- NONE，B0→B1：年化+1.0793个百分点；回撤-1.2051个百分点；交易+5笔。
- NONE，B0→B2：年化+0.0000个百分点；回撤+0.0000个百分点；交易+0笔。
- NONE，B0→B3：年化+1.0793个百分点；回撤-1.2051个百分点；交易+5笔。
- DOWN，B0→B1：年化-5.9204个百分点；回撤+9.9716个百分点；交易+10笔。
- DOWN，B0→B2：年化-5.7879个百分点；回撤+10.6442个百分点；交易+5笔。
- DOWN，B0→B3：年化-0.7538个百分点；回撤+1.3448个百分点；交易+20笔。
- UP，B0→B1：年化+0.8149个百分点；回撤+2.1272个百分点；交易+11笔。
- UP，B0→B2：年化+2.2026个百分点；回撤+3.0078个百分点；交易+8笔。
- UP，B0→B3：年化+0.5208个百分点；回撤+8.4253个百分点；交易+24笔。

|配置|平均完成持仓|最长完成持仓|下跌闭合|下跌时间退出|未闭合周期|
|---|---:|---:|---:|---:|---:|
|B0-TIME|4.3036|8|56|38|1|
|B1-TIME|4.2800|8|69|50|1|
|B2-TIME|3.8595|8|65|50|1|
|B0-NONE|7.1786|35|29|0|1|
|B1-NONE|7.5730|36|34|0|1|
|N0|4.4818|8|54|31|1|
|N1|4.6981|8|50|33|1|
|N2|4.5417|8|64|39|1|
|N3|4.7009|9|61|42|1|
|N4|4.1391|8|59|36|1|
|N5|4.1667|8|59|47|1|
|N6|3.7842|8|84|69|1|
|N7|4.2154|9|74|48|1|
|N8|4.0923|8|75|63|1|

取消期限导致失效坐标的相同账户，不能算参数稳定性提升。全部期末持仓按实际收盘计入净值，未计作闭合交易；年度价格/费用和全部变更周期保存在分析材料。局部有限差分不等于完整13坐标32点诊断。本轮没有把未达标机制追加为正式阶段四选型集合。

## 验证、保存与局限

五个复用控制与原不可变完整账户重新序列化精确相等，原哈希和身份吻合。14个账户的基准五类账本精确相等；全部账户的数量、现金、费用、逐日净值、自然年、周期、尾仓对账通过。已知分钟Low差异的潜在受影响订单为零；High不参与本买限价/卖市价撮合，不宣称重建未知轨迹。

九配置因果前缀及未来修改不变，合成检查覆盖3/4日期限、价格上涨/下跌/相等、原区间/状态退出、上涨原期限、非法方向、零冷却。代表配置串行/spawn信号、五类双方账本及结果哈希精确相等。研究源码Ruff通过，未做仓库全量回归。已发布的描述诊断脚本含一处必要路径初始化后的导入，未声明其通过通用lint。

完整账户、真实授权、前瞻方案、实际次数、完整分析、源码与依赖版本均通过公共API保存。交付CANDIDATES/10沿用MANDATE/6，FULL校验记录独立保存。历史交付及原C2132不投入PTE的决定保持。

全部设计使用已见开发池，没有独立样本外证据。未找到达标新机制不等于证明所有机制无效；继续方向应减少阈值引起的整笔交易突变或检验买入信息能否支持持仓，而不能只为好看分数降低仓位或放宽目标。

## 正式证据引用

- [N0完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/96217b5ff912fcc7ad011e646adcfe5fa8450cb2a7ac005a2b5634cd68ad1188.json)
- [N1完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/bd9e0d32754d744d1e5b814f4bfdaa40965452017fb0705869b74b756fba149b.json)
- [N2完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/597e6c4451062102c95273889a92c5a45ca737a87c7e0a4a7aa2718f7840428c.json)
- [N3完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/10470f58e589329e9011cc71c9cafbb5d7392a4755d1e3465e78fec8995d26cd.json)
- [N4完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/8bdff4965af7b13a237fd6b9e36947b6ba26f37da9b84059eadf3360dfdeb905.json)
- [N5完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/c1016398aea840c2ce0b8d21854a621afc9c111315450a9442769d3cc311b81a.json)
- [N6完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/1fecef52e37e7073dcf4208b5895c71146c5e775f3fc41fb88e60e59ed090361.json)
- [N7完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/14dac69f948dbb695472ae729294b6187b204d08c184d4bfeb60aa462d1037cc.json)
- [N8完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/25ecd6e2f0a5fc95db8cabbcfb487b6ee608352f04934620e6df5f47096c5cf0.json)
- [B0-TIME完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B1-TIME完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [B2-TIME完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [B0-NONE完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/7874e234a9141792742157e25da36132018572e4cf5155310dd59f6a0b1cab33.json)
- [B1-NONE完整账户](../../../assets/deliveries/CANDIDATES/10/evidence/cf5d108a336aa9874c2b144f825ecd70818f49dd7d0e662ee56f95678c38b95c.json)
- [price-exit-authorization](../../../assets/deliveries/CANDIDATES/10/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [price-exit-plan](../../../assets/deliveries/CANDIDATES/10/evidence/8c8878acf3e71ae8774a07bf69ccfa49b507a47dc9c868c15595098d8a5bfe98.json)
- [price-exit-plan-references](../../../assets/deliveries/CANDIDATES/10/evidence/9440d59756d6a5ea5812f4285a3ee6e5c4359fde35f40eede58d65f4f4e9ce17.json)
- [price-exit-mandate-validation](../../../assets/deliveries/CANDIDATES/10/evidence/f0682e41798c61bd113530c63b6b093454cde040b93768335ff11fab37012d40.json)
- [price-exit-synthetic-check](../../../assets/deliveries/CANDIDATES/10/evidence/b72a1ecf12bdb8a9af83b30e95ad082e31cffbbfbeb453acccc3edeca47086a6.json)
- [price-exit-precheck](../../../assets/deliveries/CANDIDATES/10/evidence/bb83f0fe65c7b804f7cbc1b296e5f9c95389d6cbb678b1d5439237c67249fadd.json)
- [price-exit-matrix](../../../assets/deliveries/CANDIDATES/10/evidence/8428f2b6b8e118e12d75689dfd65726af232828ad0744cbd917f7090c043e83d.json)
- [price-exit-analysis](../../../assets/deliveries/CANDIDATES/10/evidence/6b5bb24e8823bca675ce27f908d6f6e8869bc8ed1602114c7d218c97b052c026.json)
- [price-exit-helper-provenance](../../../assets/deliveries/CANDIDATES/10/evidence/f0316b881ccb9110e56479235ffaa91764b012eefd4f1db268abfd79eebd382b.json)
- [price-exit-account-references](../../../assets/deliveries/CANDIDATES/10/evidence/49a8f6414444f2ac6c10a75d009f89f46d8837da402888a4ef12dff31bcbb81d.json)
- [price-exit-reproduction](../../../assets/deliveries/CANDIDATES/10/evidence/9eb744013e9197e90c4a09f889d8c37c5c65fe6756bb4ae90f061a0932d60a95.json)
