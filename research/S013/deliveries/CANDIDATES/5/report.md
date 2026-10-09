# S013：参考 S007-v1 的信息式买入确认分

本轮身份为RSCH，属于已授权的阶段三继续研究。用户否定固定冷却日，要求考虑确认分控制买入，并明确允许参考S007-v1的策略表达。所有旧证据、候选和阶段四反证保留；本轮不进入阶段四或冻结。

完成183个真实、去重参数配置的TDR FULL账户评价；42个开启确认分的技术身份通过原四门，另有10个关闭确认分的达标控制。关闭控制及相同经济路径的技术继任不计独立新发现。

新达标配置中盈利余量最大的是C2308，2022/2023两年最小净收益3.6891%；原十个中心中最厚的控制为C9029，对应0.5500%。新配置最高净年化为C2132的16.1572%。

相对自身母体提高最小盈利余量且同时保持原四门的身份：C2301、C2302、C2303、C2304、C2307、C2308、C2310、C2311、C2312、C2203、C2204、C2208、C2209、C2212、C2213、C2214、C2215、C2216、C2126、C2127、C2401、C2402。提高总年化与改善亏损年份盈利余量分别判断，不能相互代替。

## 借用表达和买入职责

S007-v1只提供表达结构：基础机会满足，同时确认分达到门槛，才允许买入；持仓退出由基础规则控制，确认分转弱不强制卖出。冻结版本源码与manifest哈希已核验，授权记录保存定义及源码快照。没有读取S007数据、实验结果、种子或研究绩效，也没有移植其权重和适用性结论。

本轮使用已有20收益的滞后一期自相关ACF（相邻涨跌是否延续）、成交额/过去20日成交额均值、过去20日log成交量变化均值。每项以当时完整的过去N个观察归一化：

`分数 = (小于当前值的个数 + 0.5 × 等于当前值的个数) / N - 0.5`

单项或声明的组合采用固定等权；反向分数作为反证。组合等块权重为0.5×ACF+0.25×成交额+0.25×成交量，避免两项高度相关的量能信息占2/3。S007实际使用252日/min20及其他因子，本轮120/60/40日完整窗口与新输入是S013自己的研究设计。分数范围[-0.5,0.5]，不表示盈利概率。

全部路线的固定冷却日为零。全买入门检查每次原机会；状态重入门仅在最终信号退出原因是`regime`时激活，持续到下一次信号买入，每个交易日重新评分，达门即可买入。并发退出按loss、trailing、range、time、regime优先顺序判定，不能把它泛化成所有发生状态变化的退出。退出上下文属于信号政策，未用实际成交日冒充信号日期。

## 评价约定和已见信息

510500.SH原开发池2020-01-02至2026-09-30，共1636交易日；初始现金100万元，HFQ研究单位100为一手，锚点2019-12-31=0.2803；逐日price_scale映射原始0.001价格跳动，T决策、T+1执行，限价买/市价卖，只做多、不加杠杆，每侧0.1%费用，同口径可执行NextOpenBuyHold(100)基准。以上研究单位不解释为PTE实盘份额或现金。

四门保持：净年化≥1.5×同基准；每个自然年的最大回撤严格小于基准；闭合交易数×60/1636≥4（至少110笔）；负基准年份2022及2023的实际净收益严格为正。年度权益连续、上年末权益作锚，2026截至9月底。盈利余量、20/30bp、条件标签和参数邻域是诊断，不新增门槛。

本轮重复使用已见的完整开发池；追加设计受已见结果影响，没有独立封存样本。Optuna用于前瞻固定队列和去重，不代表全局优化或统计验证。所有调用限制为S013现有离线资产，没有新外部获取。

## 达标配置

|身份|母体|净年化|闭合笔数|2022收益|2023收益|比母体最小余量变化（百分点）|
|---|---|---:|---:|---:|---:|---:|
|C2300|C9023|13.2786%|111|2.0524%|0.3041%|-0.0013|
|C2301|C9023|12.9908%|110|2.0524%|2.5630%|+1.7470|
|C2302|C9023|12.9908%|110|2.0524%|2.5630%|+1.7470|
|C2303|C9023|12.6696%|110|2.0488%|2.5626%|+1.7434|
|C2304|C9023|12.6696%|110|2.0488%|2.5626%|+1.7434|
|C2307|C9025|12.2172%|110|2.0519%|2.5618%|+1.7482|
|C2308|C9029|12.3144%|111|5.7848%|3.6891%|+3.1391|
|C2310|C9029|11.2737%|111|1.6223%|1.5149%|+0.9649|
|C2311|C9029|11.2737%|111|1.6223%|1.5149%|+0.9649|
|C2312|C9029|11.0534%|112|1.6223%|1.5149%|+0.9649|
|C2203|C9023|12.6405%|110|4.8851%|0.9247%|+0.6194|
|C2204|C9023|12.6405%|110|4.8851%|0.9247%|+0.6194|
|C2208|C9023|12.6405%|110|4.8851%|0.9247%|+0.6194|
|C2209|C9023|12.6405%|110|4.8851%|0.9247%|+0.6194|
|C2212|C9025|12.1879%|110|4.8847%|0.9271%|+0.6233|
|C2213|C9026|12.1879%|110|4.8847%|0.9271%|+0.6233|
|C2214|C9029|11.0534%|112|1.6223%|1.5149%|+0.9649|
|C2215|C9030|11.0534%|112|1.6223%|1.5149%|+0.9649|
|C2216|C9023|12.6696%|110|2.0488%|2.5626%|+1.7434|
|C2100|C9023|15.5635%|110|8.0953%|0.2839%|-0.0215|
|C2101|C9023|13.9855%|114|7.9628%|0.2846%|-0.0208|
|C2102|C9023|13.8983%|116|7.9593%|0.2854%|-0.0200|
|C2103|C9023|14.7493%|116|7.9593%|0.2854%|-0.0200|
|C2109|C9023|12.9721%|114|2.1053%|0.3040%|-0.0014|
|C2111|C9023|13.2786%|111|2.0524%|0.3041%|-0.0013|
|C2126|C9023|12.6405%|110|4.8851%|0.9247%|+0.6194|
|C2127|C9023|12.6405%|110|4.8851%|0.9247%|+0.6194|
|C2132|C9023|16.1572%|112|12.1687%|0.2841%|-0.0213|
|C2133|C9023|14.7493%|116|7.9593%|0.2854%|-0.0200|
|C2136|C9018|14.5396%|113|7.9607%|0.2843%|-0.0186|
|C2142|C9023|14.7493%|116|7.9593%|0.2854%|-0.0200|
|C2144|C9023|13.9456%|116|7.9588%|0.3054%|+0.0000|
|C2145|C9023|11.9335%|113|2.1044%|0.3034%|-0.0020|
|C2018|C9023|15.5635%|110|8.0953%|0.2839%|-0.0215|
|C2026|C9025|15.0007%|111|8.0958%|0.2844%|-0.0193|
|C2030|C9026|15.0007%|111|8.0958%|0.2844%|-0.0193|
|C2034|C9027|15.0007%|111|8.0958%|0.2844%|-0.0193|
|C2038|C9028|15.0007%|111|8.0958%|0.2844%|-0.0193|
|C2059|C9018|15.1306%|111|11.0780%|0.2849%|-0.0180|
|C2080|C9023|15.3425%|114|11.0837%|0.2840%|-0.0213|
|C2401|C9029|12.3144%|111|5.7848%|3.6891%|+3.1391|
|C2402|C9029|12.3144%|111|5.7848%|3.6891%|+3.1391|

最大余量配置C2308的精确确认参数：`{'enabled': True, 'profile': 'turnover', 'threshold': -0.175, 'orientation': 1, 'scope': 'both', 'lookback': 120}`；上下文：`{'entry_gate': 'regime_reentry', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_FEATURES'}`。基础规则沿用C9029、两路线冷却均为0。

最高净年化配置C2132的精确确认参数：`{'enabled': True, 'profile': 'all', 'threshold': -0.2, 'orientation': 1, 'scope': 'both', 'lookback': 120}`；上下文：`{'entry_gate': 'all', 'volume_basis': 'ADJUSTED', 'weighting': 'EQUAL_BLOCKS'}`。它与最大盈利余量配置分别列示，不能拼成一个策略的绩效。


C2100与C2018是同一经济政策的第二源码技术复现；全部共同信号、决策、订单、成交、日账户、交易和基准逐项精确一致。新增`confirmation_exit_context`诊断列单独排除，并保留原严格比较失败记录与明确比较模式，不排除任何共同经济字段。其他不同参数但同账户表现的身份仍保留，不能把身份数当独立证据次数。

## 逐年价格与费用归因

每个成功账户独立重建数量、现金及每日权益：持仓价格变化，加当日买卖相对收盘价的收益，再扣真实费用。全部账户年度收益与回撤复算一致，误差界限在诊断证据中。以下贡献均除以各自当年期初权益，不用全期手续费减少冒充预测力。

|配置|年份|价格收益贡献|费用贡献|净收益|原四门|
|---|---|---:|---:|---:|---|
|C2008|2022|6.6805%|5.0577%|1.6228%|通过|
|C2008|2023|4.6328%|4.0828%|0.5500%|通过|
|C2308|2022|10.5357%|4.7509%|5.7848%|通过|
|C2308|2023|7.4408%|3.7518%|3.6891%|通过|
|C2132|2022|17.9489%|5.7802%|12.1687%|通过|
|C2132|2023|4.5466%|4.2625%|0.2841%|通过|
|C2055|2022|9.4743%|3.4600%|6.0143%|未通过：frequency|
|C2055|2023|7.2098%|2.0655%|5.1443%|未通过：frequency|

## 信息标签、反证和量纲

原控制真实信号入场标签1164行，仅159个不同信号日期，十个中心和1/3/5日期限大量重叠。按年份和路线分层的固定期限T+1开盘后价格收益只是描述性信息，不扣费、不等于完整交易盈利；原政策被拒绝的交易盈利不能直接相加当成新政策贡献。实际新政策机会、拒绝、入场及退出上下文另行统计。

成交额与成交量在原机会中的相关约0.65—0.67，不能称三个独立信息源。旧bear ACF开/关、单项/组合、同日反向、路线门、等块权重均保留完整配置记录和必要完整账户。

原始成交量来自已有原价资产；每个日期校验HFQ Volume×HFQ Close/raw Close等于raw Volume，以及成交额保持不变。原价预热只有60日，因此RAW仅采用完整40日分位配对，不以RAW40与ADJUSTED120的差异归因于复权量纲。

|同40日配对：ADJUSTED/RAW|净年化（%）|闭合笔数|最小盈利余量（%）|
|---|---:|---:|---:|
|C2207/C2201|12.8054/12.8054|112/112|-2.5391/-2.5391|
|C2208/C2203|12.6405/12.6405|110/110|0.9247/0.9247|
|C2209/C2204|12.6405/12.6405|110/110|0.9247/0.9247|
|C2312/C2214|11.0534/11.0534|112/112|1.5149/1.5149|
|C2116/C2117|13.6663/13.6663|108/108|-0.9903/-0.9903|
|C2118/C2119|13.0603/13.0603|113/113|-0.9901/-0.9901|
|C2120/C2121|8.8008/8.8371|88/87|2.9855/2.9860|
|C2122/C2123|10.2159/10.2159|104/104|-2.8200/-2.8200|
|C2124/C2125|9.4126/9.6429|100/99|-2.8530/-2.8546|
|C2126/C2127|12.6405/12.6405|110/110|0.9247/0.9247|
|C2128/C2129|10.0458/9.7226|85/85|1.5962/1.2969|
|C2130/C2131|10.3547/10.0318|104/104|-2.8182/-4.6511|

## 费用压力（代表性覆盖）

按实验前发布的压力计划，选择开启评分达标的最大余量及最高年化、原控制最大余量、上下文代表及非达标余量/缺口对照。仅下列账户做每侧20/30bp压力，不宣称所有新候选已做压力检验；压力不得改变10bp的资格。每次压力请求中的10bp基准完整账本精确复现原结果。

|身份|每侧费用|净年化|闭合笔数|2022收益|2023收益|原四门|
|---|---:|---:|---:|---:|---:|---|
|C2308|10bp|12.3144%|111|5.7848%|3.6891%|通过|
|C2308|20bp|8.5773%|111|0.9767%|0.0619%|未通过|
|C2308|30bp|4.9643%|111|-3.6084%|-3.4379%|未通过|
|C2132|10bp|16.1572%|112|12.1687%|0.2841%|通过|
|C2132|20bp|12.2417%|112|6.2278%|-3.7959%|未通过|
|C2132|30bp|8.4568%|112|0.5987%|-7.7100%|未通过|
|C2008|10bp|10.9939%|117|1.6228%|0.5500%|通过|
|C2008|20bp|7.0887%|117|-3.3775%|-3.3508%|未通过|
|C2008|30bp|3.3201%|117|-8.1299%|-7.1033%|未通过|
|C2400|10bp|10.2442%|98|4.1716%|4.8115%|未通过|
|C2400|20bp|6.9964%|98|0.0278%|1.3477%|未通过|
|C2400|30bp|3.8462%|98|-3.9472%|-2.0055%|未通过|
|C2055|10bp|12.3511%|68|6.0143%|5.1443%|未通过|
|C2055|20bp|10.0430%|68|2.6049%|3.0822%|未通过|
|C2055|30bp|7.7835%|68|-0.6904%|1.0616%|未通过|
|C2305|10bp|11.8617%|109|2.0497%|2.5628%|未通过|
|C2305|20bp|8.2035%|109|-3.1628%|-1.4141%|未通过|
|C2305|30bp|4.6692%|109|-8.1051%|-5.2389%|未通过|

## 技术验证和保存范围

合成验证覆盖分位并列值、参数异常、因果前缀/未来修改不变、关闭确认和无约束门的原历史精确等价、当日门槛相等即通过、下一日立即重评、弱确认不退出；上下文与RAW配对再做对应检查。十个原中心真实账户精确复现并验证单进程/多进程一致。

新增原价预热引用只从已有S013资产截取到要求的截止日：首次准备因多出截止日之外一行被契约拒绝，修正为严格日期子集后准备PASS，并保留来源/目标引用及逐行等价证明。禁止外部获取的提前探针未命中已有准备键，没有发生外部取数。策略源码、计划、实际账户、归因、费用和数据引用正式发布，原31个资产及28个准备记录逐行不变。

已知2020-12-01分钟Low差异单独检查，所有成功账户的潜在受影响订单为零；四处分钟High偏差不参与可信日特征及当前限价买/市价卖成交。此结论不等于未知数据误差不存在。

本轮执行聚焦检查及正式交付FULL完整性验证，不做仓库全量回归。FULL PASS证明契约、身份及关联证据可核验，不证明未来收益或独立样本有效性。

## 研究判断和下一步

最佳配置2023年的价格收益贡献从4.6328%变为7.4408%，费用贡献从4.0828%变为3.7518%。改善包含真实账户价格路径收益增加和费用贡献下降，不仅是减少手续费；这项账本归因仍不是分数的独立预测效力证明。

该最佳配置在20bp下净年化8.5773%，最小负基准年净收益0.0619%，原四门未同时通过。费用压力仍限制收益，不能把10bp改善直接解释为足以冻结。

存在同时通过四门并超过原中心最佳盈利余量的配置。已有组件通过信息式重入控制能够改善本开发池的盈利余量，因此不能推断已有组件无法解决这一问题；结论限于已见开发池，不能直接作为冻结依据。

本轮停止依据是：已定位并复核信息门的适用上下文、改善来源、邻域及费用取舍，完成必要反证；不是固定试验次数或首个达标。仍未穷举所有组件和参数，尚未验证样本外效力与长期费用稳健性。建议维持阶段三，围绕确认信息的互补性和费用敏感性继续研究；不要引入固定等待日。阶段变更、候选选择及冻结分别取得用户明确批准。



## 正式证据索引

- [confirmation-account-references](../../../assets/deliveries/CANDIDATES/5/evidence/d6b8ab2acd932c8f8c22946847205a3d50e6478939786d7b48981e9edea6973f.json)
- [confirmation-authorization](../../../assets/deliveries/CANDIDATES/5/evidence/ea08f06d5fa6d97eb83f9626691c839e5ffa64eb68810634eec5dbb6c610e98b.json)
- [confirmation-best-margin](../../../assets/deliveries/CANDIDATES/5/evidence/73d61d5ab137e9ed6b019997089697cdb32c642df71cff2751502a491b6c1cff.json)
- [confirmation-best-margin-plan](../../../assets/deliveries/CANDIDATES/5/evidence/de32d86528bce02a21a07e06733e391940d1c6c10801d71eb33599eb10707b63.json)
- [confirmation-boundary](../../../assets/deliveries/CANDIDATES/5/evidence/ce47ad7fac57f908d04f9f2ee60d595f44a45efef34df51fef0cbb2841011424.json)
- [confirmation-boundary-plan](../../../assets/deliveries/CANDIDATES/5/evidence/56190e9eb2a3f6d9a71f0e0ce9539e3c3c270913690be9a41af72cdcb5e9ff48.json)
- [confirmation-context](../../../assets/deliveries/CANDIDATES/5/evidence/2242bc386e3e648449e0dd1fa4d0e4a668d050b2cb017ccb2f34463a40b4b0d1.json)
- [confirmation-context-plan](../../../assets/deliveries/CANDIDATES/5/evidence/6a5bc1f66c50567dd7ff8beb1b2bba94def87adf3778eb89f8ccf7fef2be5e56.json)
- [confirmation-context-precheck](../../../assets/deliveries/CANDIDATES/5/evidence/7d489d848167898093c1719a61637524a1e8e1afebe47a7dbd9e434ae5d31c33.json)
- [confirmation-context-precheck-failure](../../../assets/deliveries/CANDIDATES/5/evidence/b679d2839fe578100dba4615311f266ee4a43f3cc8cee843671277d2cfda1ce5.json)
- [confirmation-context-synthetic-check](../../../assets/deliveries/CANDIDATES/5/evidence/d38288de341314835802cfd73703e00a0745cf3cb495a2cd6528bc3860bfd9f6.json)
- [confirmation-cost-diagnostics](../../../assets/deliveries/CANDIDATES/5/evidence/6dc4b31e5996239adda5e8c0902c11bb8bea582a70f2a0da8344f01c5c783400.json)
- [confirmation-diagnostics](../../../assets/deliveries/CANDIDATES/5/evidence/daf5b7ad99c5011e30d2944af7b82e2e3c653adaa940617c1da5a2050840cea4.json)
- [confirmation-initial](../../../assets/deliveries/CANDIDATES/5/evidence/bbcfac82721dd8cad76374145f29dcea58fb79f62e4431ebc68e1f9b9fcdbe6e.json)
- [confirmation-initial-plan](../../../assets/deliveries/CANDIDATES/5/evidence/9bb3042c0d081aa537298d240ad828ee3284cfd8e504f6af8af7a880dd53781d.json)
- [confirmation-opportunity-labels](../../../assets/deliveries/CANDIDATES/5/evidence/833805105c803c2c1f69b618cd0e5e62b636d7245680b064c1ebe29b5609242d.csv)
- [confirmation-policy-control](../../../assets/deliveries/CANDIDATES/5/evidence/b1731a7bc47429ba23e187675dee25334a2b416e5e657615b6c861e120acd9bf.json)
- [confirmation-policy-control-plan](../../../assets/deliveries/CANDIDATES/5/evidence/26cc400d520127da1925306ee7b127d8fc0f33b39c7c16bdbb777d46877365f0.json)
- [confirmation-precheck](../../../assets/deliveries/CANDIDATES/5/evidence/f91afc80ca0bcf07fcc5c2066fd2f65b79d489e71c99edcba7e6e956853d13bd.json)
- [confirmation-preservation](../../../assets/deliveries/CANDIDATES/5/evidence/935e34a4232784aab52313925b4633a937b5f8f09afabf8054950a80288b74fd.json)
- [confirmation-raw-volume-scope-preparation](../../../assets/deliveries/CANDIDATES/5/evidence/15d884a8cc05431d7cfdb9b986b58a6f50dbc5db12cca145fe365ff3a6e859ea.json)
- [confirmation-reproduction](../../../assets/deliveries/CANDIDATES/5/evidence/6077754a42e03ae5c0bab58fbb13d0f9bfaf0e2d06f357ab8c7530fb7818d7ed.json)
- [confirmation-score-attribution](../../../assets/deliveries/CANDIDATES/5/evidence/ab5d7e86fbfe83788f2bac65c2eb9a1f46ed2746d1f6bbb8fffd74040e363b7a.json)
- [confirmation-selection](../../../assets/deliveries/CANDIDATES/5/evidence/0900768f53d35c618dc89121b5049141175ece1144ff57beec8017ed258234d6.json)
- [confirmation-stress-plan](../../../assets/deliveries/CANDIDATES/5/evidence/77ac128b0d8a46e51f0f15b8e05593e98d9cfdfbfaa9e7150ef44c2cbdd28122.json)
- [confirmation-synthetic-check](../../../assets/deliveries/CANDIDATES/5/evidence/5bc27f1b16d31ee4ec71b3ca1f715ebd167ddd4e320498ef2963f3481f142dc5.json)
- [cost-C2008](../../../assets/deliveries/CANDIDATES/5/evidence/8d3b3a9de01ae0ac4f42d41a9cfdc3e8d6960931ab11b8da7dcdaee7a69224c5.json)
- [cost-C2055](../../../assets/deliveries/CANDIDATES/5/evidence/96be138c2f6407586fdd09c8b149dab0e14e3ff0d9b2d230d66e08260cc6ab7f.json)
- [cost-C2132](../../../assets/deliveries/CANDIDATES/5/evidence/3a2fa6255e3ab4a4659d68559db79672cbb0704706a1ed7072f65c2d430d9fb1.json)
- [cost-C2305](../../../assets/deliveries/CANDIDATES/5/evidence/d647d906dcd853691041f08862069012b39c23d47e17faf5c5f13a7daa9956ba.json)
- [cost-C2308](../../../assets/deliveries/CANDIDATES/5/evidence/01d05251aa233b22004a0c74f29e9c6fd9ea7609d557e383fe6690f100c731c7.json)
- [cost-C2400](../../../assets/deliveries/CANDIDATES/5/evidence/bf8e9ef70261cb8193c49446abea245121c6cdbd5b5c95079f01e303fe246935.json)
- [C1000完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/3bdddb97c03cce6da5b963a353bde216c4c2c14aa243e725927a26be57cb6305.json)
- [C1013完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/61dd042547a4a59b85ff17ea2be1192e757028c223d862b70474d727c87e15c0.json)
- [C1124完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/0b40189dd4aade40918ea4119ecbe17aa81ffb8ef641fd32d30715cc929e5b17.json)
- [C2000完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/957b9394adff4e9058ed515b36dbe2f188519ebb31d67487da4ca5cddebd879c.json)
- [C2001完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/66f74b2f03e5e702bb254663acd97026a97ac3b63a3630995043817d5877ec3b.json)
- [C2002完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/979264848ee887c6ec7acda51237961665ea0bb68f0623fbd26ebb01b726fcc6.json)
- [C2003完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/4f50265e5c2294f89e6513f1158f813968f2a23f6c3aee75c5c126a4b58ee015.json)
- [C2004完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ae658cc6b53ae16eade0058021b3fc6fd871e7a4a90ad2ac519a1f2343b01753.json)
- [C2005完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/e9bc3e4efeeb52857cd6bbd91efc305d5d9313c30bb6ba03563edb04af1ab5ab.json)
- [C2006完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/46a05729a536095d1b28111dcbeac38619ae73a7d5590ed9c2367b8becb87056.json)
- [C2007完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/97b5f8b0f25ee450c785a660a7d34fce785b06f99df31245f7cd390aa627dbaf.json)
- [C2008完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/0bd586aec0342d91583fc14716cdb606d1d8ed0a7e6cc853dbf76d6b627a920b.json)
- [C2009完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/675dbf0764258f1b0cb535e4acd0fa01209708c12fad83f4c3ac36a7cef567ff.json)
- [C2010完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/120ab783207da5fb3bcb6118a76bb1645ca437f50dabb1950b1c361d2293c9e8.json)
- [C2018完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/4e3981c0877e868db62a45770905401e053eec20d93159b2d7d5920f6bbff6f2.json)
- [C2026完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/3a9c6f26671f58b506d6b2d9164d72538655864b299aa55e7c5bc0ab08c4555b.json)
- [C2030完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1de71dae12bd061bbcebac11ace314089e5a24c5a200a718f58d6aa41ea9b428.json)
- [C2034完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/13ba93c6b869a7eb6a2d07c406713ff098e5382b3b5e93a47765cf84dd1c9a9b.json)
- [C2038完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/fefcb5123336d308b19e4ae20e2357534d50fe9d0bff7c63be5a604b3efb853c.json)
- [C2041完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1ba7aee1375887e7ab4cd7f29f8acef602c78f884545957e1a93baba8ea1a198.json)
- [C2052完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/6dfa521b1deaf46a16ccb55b11b598784a2795952f3cafbb5a3cb5a3a111ff48.json)
- [C2055完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/055b089566c8f5bb8fa6f6656f85696a48bfc4d6969eaa457c7501be4273a84e.json)
- [C2059完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5fcb6667c41708cda2225196438a39bb5ee679948d89b557d802c03588ade9ef.json)
- [C2068完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/3d2f615c867fed239fb4ecb642ea7bb67848e0ae34de815b8b06577ee042bf57.json)
- [C2069完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/57c6e1c58288ac7a86e49ac0c666b5f3749a9385b61b38988ba061e9738e8448.json)
- [C2070完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/9030152b84c859a23f8884b24426f29c810a157e806fc6176bf23b4e3a57cdfb.json)
- [C2073完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/16af859e685dc4e416cb28d1590bfc3445a2785bbf2547ac321ce3657a20d17c.json)
- [C2076完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/28f04c9dde2f3babbf3b3e30abe512d2762fe9971c83e68e23717de0d3c7ebb6.json)
- [C2080完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/8769030e3f793f1ae4a733d37dbfb933d96cbfaae69205a8f8a7e577e266ff3f.json)
- [C2089完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/d58cbf38400a7efe144062a43d2ffd2ecdf2e1bb1e3c292eb368b2b9ff615346.json)
- [C2090完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ba045dae2001b446882a93996b73878dad44d32258476e4aa8e9f75a694273b3.json)
- [C2091完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/185e26e74ccf19986414f650336f86cc75d812f26ceb67cdd9cb29b27cdc750c.json)
- [C2092完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/09376aa341c4d0a705bd01d331ec2ade97dc8cbbe3bb6c8b75a51d7484c809c9.json)
- [C2093完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5eb337ec5e2b1c706664a6f6b97fbaefc3e9455ef7dcadc8a598f6c3e59ed521.json)
- [C2100完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/b513c6c31af7238526c2b6ff9c17b9d7b19c2b2ee38c7f00501578606df4edb3.json)
- [C2101完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/eee7b27978c03dc81fd79a11998d3dfca5eaf5f9cfc652dd18fb50952decdc57.json)
- [C2102完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5e377a303c7441d0ff20e294b701c451ac7153ad119a1b42196850a041fc00c5.json)
- [C2103完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/a77df7899f2ddee4e91ec3f3987046b21bee95ee0d1b3f5d94d2e9f35baecffd.json)
- [C2104完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/f9f839d1e9a2ec7632f39e6c341cc6f454e658b399d747ae0187b4156aacb14b.json)
- [C2105完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/cd3c5dde6f5faef62292bc2f9b0bd1de7f5bad79143c31eb6b86728d2ddf1063.json)
- [C2109完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ced36ec09ec83aa5d90b4f5d3b27c4ac71d1f26147b0bb6980efea93e5d61993.json)
- [C2110完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/a5e4eb3b911eaf62038342d1279bea91dc913d6dd61e0343898340f970dfe0b0.json)
- [C2111完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1cf6dce0cb4d0c65260c2a6a48db54293cdb2fb795ed0e2a840c696da3801f20.json)
- [C2112完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1e979cc9f36ad1566da5ae79b6abc7b4582613ed65530c8d7dcbb06483450c35.json)
- [C2113完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/4600aeb938d743c041138d894fdb237979ac237aee2f51317a9fb62e6e96cc6f.json)
- [C2114完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/01795d58f95f22bbe48c926a525df09275d1316b1aac88e4b54c5a91f97368b4.json)
- [C2116完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/2bed4c6a31fe6ef30e5716bd44b2bb4651d3738cd0d56c4010384a6714c294a7.json)
- [C2117完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1eefb2320a3e70feae9638c84372d3a30f14d4da7b64807303628d6d5270e4f9.json)
- [C2118完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/92ef10d5aeddaf52e88e1f44b9b1671dc030b4dbde5cf938d85af55a1f841d1a.json)
- [C2119完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/826b5c5f2de3652e7a5a44f56f92489bb42126acc1384306ecaeed4174870bb2.json)
- [C2120完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ae50b22c50c70dc5474573401ff9c6ad0eef86c5988fd55393e13677af828fb5.json)
- [C2121完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/145752cac06fb6fae21665c24d776b7cc3e389b5ba50b0617cdc59a564984907.json)
- [C2122完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/c3a0dadde00778c18c5aa47cbf373f7b889570d582b6292c6fe0659ec452f8ff.json)
- [C2123完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/91e0a34c1ed0b438dd9db4712c1bb66788d62fce860dfda50a48975bf3dbe7de.json)
- [C2124完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/9d39ef1292d7ec9d68558a5d6cc6783c1e51205004de6f97f802425d1d3962bf.json)
- [C2125完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5c177022db891d32845046721b6d5c89fcb2eeb4f5bd5077470f88d57cd9cb1c.json)
- [C2126完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1550c39485e6e62f461a6ed17027cd646b6f57b537492bbd5c9a1c6fc0683a4e.json)
- [C2127完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/413983cbc7ff93fb572a9c968c5bfb92acc0f2e8153ef549febfbcc873964d8c.json)
- [C2128完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/d35e741642c8a87f323ef1ced15590db74864681f6e2dc8bc8441dfa3a8513df.json)
- [C2129完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/0608fbc357e2b9f6bcb590bec07564530d5ae0f1ad09932f1fe7f6546d02e056.json)
- [C2130完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/a29f6c943329306c2823ebb6a088d07cd36b7c5dd4110f58683db74811cbd66d.json)
- [C2131完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1a5301a82b82bbbe0427d519e95c2ca107fee10d17ae14131743cee34df95bf1.json)
- [C2132完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/6f1e172710f3ad124b05b710b45f568145969f2e41da3ed57e4c3f2700423d3e.json)
- [C2133完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/6ba4195ab511127b3a2d1374cefc87c54ebfe863e03ffc7a40992eb4d444a570.json)
- [C2134完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/6bcaeacf7e69fb08748bad00a01a31ee881be0ffa8d030d9c073293d02b1e724.json)
- [C2135完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/d46d79a958d0d91c5a1e5a2becd22ab0c0caa831be590502dc21224737748a98.json)
- [C2136完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/d8253dbc6b7a3559f1754819e768341a28a75659c7dce42a3c464453907e8306.json)
- [C2140完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5f789c86ccca60a3c82ef374601b1e05d7e2c1821750aae3d85d1d419b105815.json)
- [C2142完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/fb0cf379c30775fb101a97c3e821ecda010d1d464f15bdbff61d638ea2ca807f.json)
- [C2144完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/94455deface2044ae25a011463411274c4fa489719432f51848561b685ff3c6c.json)
- [C2145完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/46fde9af811ac43bb0d09d0ad38551d0e89179f7ba83074ccd7f61d9bfc81b17.json)
- [C2201完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/bae00de86d4ef5250f7153fd845d5bd6ddfd99a00444244494ef99ef5ef28f68.json)
- [C2203完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ac99395a6514869b4afb9a404b5c55bab8fdfc48a1ddf3a3ed9e71ca5a4b1c6d.json)
- [C2204完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/7c1930c45bdba4a3c4d3465e3c2d19aa5e401c83bd84d28cecd716ecc14113b3.json)
- [C2207完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/a9819885d4b4180da261e33aa72acab2035bf076d4b6a938babfaac07c67c393.json)
- [C2208完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5a3019466071c5852bcd9a89dde111877409dc3c8e71673889431aff238e2e72.json)
- [C2209完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/4f441a83cf1774fb2cf209fd9f2ff39b70402ca55be412450af1423ac2d8b4cb.json)
- [C2212完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/18806c40f3927ffd57184f195789e4498bede1c06550090b4c9eb9261e350958.json)
- [C2213完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/e8f542d55b1cf9d032a7c6371e5d9b9f7ddde6035e0a76c19b13173256e9535f.json)
- [C2214完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/030e066473f9f1f001d3918656fb49c8358d25bcc77fbd4d143ef5988a8e7abb.json)
- [C2215完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/0d730fdf3f39411a8f0f866d58074494a2460d54f1947d68577f3479389ee02e.json)
- [C2216完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/41f63e0da2debe2fbc50397d5d0ab9d1f9e15c5a19c6e3f4c513608002f8a1b6.json)
- [C2220完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/5f355fa5ca85065b5d9703781d3916034fb13ebe50d4340996917c40ffe3ac21.json)
- [C2300完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/2848e95c0a5be18a6986509392d184f5c38c93ebf827244e4a790ed159200707.json)
- [C2301完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/41922578ae365d0d70820db53ef7aec0edfa0e7c6d6de2ff12aaeb2c80de873e.json)
- [C2302完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1a81aa32200310368dfb87c3ec5d73bb33596250b2e205bdc0cb0a11a6e665b3.json)
- [C2303完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/9a9d9941c7156147c092a02d3fa25bf6a28d7c09bfaea79db708564179f7148c.json)
- [C2304完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/d302c519ec65ec7119accee89b890ef3c29983688299c61141dbada6d2116de9.json)
- [C2307完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ea655d834a3ce3d8339647fc99dc98769449b269fec9ab2ff391a98ea873b387.json)
- [C2308完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/479891b2fdb62943b3d636396675274087edaf6f509e35960351f46e4d888e06.json)
- [C2310完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/57353a22e8a326565cb25bd15f60b35e094d436274afa56444cc7ce953688ff7.json)
- [C2311完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/eec8a62a466014830dedb8dd7da0620b96e674eafdd8314608e9370a7b4d0586.json)
- [C2312完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1ec67863051b0f32e18ed77e86b53a044b8424f55aa635fabc87b0631060101a.json)
- [C2400完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/084d52b9f5d715d15a00ec56ff8b69eb9aad5262059e839735cda8ba3eccbdf3.json)
- [C2401完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/82c62a56c6d73849594162c36d9813023e95ef542814ba984822e4d9efc2be0d.json)
- [C2402完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/ce3c70033c8c2d9e6e5eb2771d958597889d22cdc0d6d64cb32f65ac6f5919bc.json)
- [C9018完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/12b1103556638e4902d6ef9a3ba7b76fc0502cc3a68c3ee90c2bf0e2c5480f28.json)
- [C9020完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/8f570966ef68704c918e45d556e43649e0b9c0f0700186054e36ffc0b83784c3.json)
- [C9023完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/fcf6e9bef89a648056226e3b0a10b791e1a3636df8d18246dc649f3719bd785c.json)
- [C9024完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/1a5f42dd206eccc6049e3b5bf55afaadb3b2d60999b385f633452c557ab565e8.json)
- [C9025完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/049a622eb6d24a3105cbb37ef182539e9698d0794d6eb4c7ae07e7774583e005.json)
- [C9026完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/dd1808b47afe3ef0efd4dab3a5ce0d71a55b857e3b76cdc9e641050d3cddea27.json)
- [C9027完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/91685cd72cd716eeac212a1618aca2432fc70a53bac76a00217dce418ce8f1f9.json)
- [C9028完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/402aab2547a5476fc629adb32412080f8f921fa8f19bc39b84812cceba437ef4.json)
- [C9029完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/86a299e660ffe9f4489c426cb763aec340e0e34116fce08eb57b79fc7ecfb2dc.json)
- [C9030完整账户](../../../assets/deliveries/CANDIDATES/5/evidence/b2fd6abba44aa22148fef49e05aa21215aa1437598e4eeed393d0468872b55a8.json)
