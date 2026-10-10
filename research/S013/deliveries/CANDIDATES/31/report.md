# S013：下跌路线定时退出后的完整入场资格刷新

RSCH阶段三，用户授权自主完成目标无需逐轮评审。本轮COMPLETE只表示证据交付完成，保持原经济要求、S013既有数据及执行合同。

## 证据与最小对照

原C2132中心四门通过，但原完整13维32联合扰动收益Q10仅5.8974%、回撤Q90达30.5044%。删项、平滑、条件退出、状态确认及波动时钟等已有对照未证明保住原经济目标的实质参数改善。EX033状态分歧与重新入场诊断给出退出后状态连锁的线索，属于联合参数及既有完整路径的描述，不能解释成某个H的独立因果作用。

EX034仅等待rawbear/range机会刷新，旧C6100未通过原四门。本轮先精确核验原C2132和旧C6100原生账户，再对固定旧C6100路径做事前声明的pending诊断：18个pending段中10段存在原ACF/动量资格已失效而原range条件仍成立的更早解除机会。相对旧解除日或观察窗末的间隔中位15个信号日，该时点后合计25个旧blocked机会。这些数值不传播新的持仓状态，不预测新交易数、利润或回撤，也不能把旧交易收益加总为机制增益。完整方法和原生账户证据保留。

本轮只有1个新结构BEAR_TIME_ELIGIBILITY_REFRESH。设置pending精确保持EX034：原持仓路线bear、最终原reason=time、当日rawregime=bear且bear range_position<=原bear.entry；设置时不追加ACF、动量或买入确认score条件。空仓每个T先检查解除：沿用rawregime!=bear或bear range_position>entry；仅新增非null原bear.acf_min下acf1<acf_min，或非null原bear.momentum_min下momentum20<momentum_min。ACF/动量等于阈值不解除，score不参与解除；本轮原momentum_min保持null。解除当日按原规则判断入场，bear资格刚失效时不会买入，资格重新满足后无需另等一天。pending拒绝原eligible bear机会，并优先命名entry_refresh_rejected；原confirmation_opportunity与confirmation_pass完整保留。

原H8/H4信号持仓年龄、原ACF20、raw路由/range/确认、loss>trailing>range>time>regime优先级和bull全部保持，无新增阈值、等待天数、保护或时钟。原13数值中心与完整域不变，暖机沿父实现；不足明确失败，不下载、缩短或替换。

最强反证是较及时解除可能只恢复交易次数，同时损害回撤或亏损年收益。更早解除不保证下一次买入有利；所有实际收益必须由新完整现金/持仓路径计算。结构受EX034失败及上述旧路径诊断启发，反复使用已见S013开发池，存在搜索偏差，无独立验证或未来稳定保证。

本轮3个完整中心：B0-TIME原C2132、C0-RANGE_REFRESH旧C6100、N0新C6000。只有1新业务配置、2实际评价（串行/spawn技术重复），2旧中心完整账户精确复用。旧C6100只作失败控制证据，不登记或推广为新达标候选。N0原四门通过才运行32新完整参数账户，并精确复用32原EX015 TIME账户；否则零新参数。旧C6100不追加参数账户。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp，策略与LimitBuyHold统一1%买入溢价。原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤、邻点资格与其他诊断不新增经济门。

## 三个完整中心结果

|角色|机制|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---|---:|---:|---:|---:|---:|---:|---|
|B0-TIME|TIME|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|C0-RANGE_REFRESH|BEAR_TIME_ENTRY_REFRESH|C6100|10.8392%|10.6140%|86|-2.4305%|-5.1258%|frequency、negative_buyhold_year_profit|
|N0|BEAR_TIME_ELIGIBILITY_REFRESH|C6000|11.7522%|12.8506%|92|-3.8576%|-2.1436%|frequency、negative_buyhold_year_profit|

新完整路径设置pending 21次、解除21次，拒绝原eligible bear机会71日。机会数不等于损失或恢复的实际交易数；新路径改变后续现金、持仓和机会。

|自然年|原TIME收益|旧range刷新收益|新资格刷新收益|原TIME回撤|旧range刷新回撤|新资格刷新回撤|基准回撤|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|2020|16.7355%|11.1183%|11.0672%|6.1272%|6.4550%|6.4979%|14.9712%|
|2021|9.9101%|9.7084%|9.9080%|2.7008%|2.8794%|2.7009%|9.7035%|
|2022|12.1687%|-2.4305%|-3.8576%|9.7680%|10.6140%|11.9204%|28.4105%|
|2023|0.2841%|-5.1258%|-2.1436%|5.6722%|7.4010%|5.1897%|17.2665%|
|2024|64.9989%|64.1845%|70.1513%|10.0213%|4.3370%|6.1471%|18.5736%|
|2025|11.0774%|5.3170%|5.3164%|3.5332%|3.0137%|3.0141%|13.7975%|
|2026|-0.0384%|-0.0384%|-0.0392%|4.5425%|4.5420%|4.5429%|18.7646%|

## 参数结果、验证与目标判断

N0未通过原四门，未运行新参数账户；事前原域几何保留。不能以交易次数恢复、全窗回撤或局部路径改善替代原经济目标。

完整账户给出的实际结论：扩大解除后闭合交易从旧range刷新方案的86次变为92次，仍低于原策略的112次。年化从原策略16.1572%降至11.7522%；新2022收益-3.8576%、2023收益-2.1436%。回撤降低没有补回交易频率与亏损年盈利的要求。range刷新与完整资格刷新两个重复入场等待方案均未保留原四门，停止沿这一结构继续微调。

本轮1新业务中心、2实际评价、2旧中心复用；参数新业务配置0、实际评价0、原TIME参数复用0。新业务总数1、实际评价总数2；旧完整账户复用不计新评价。纯合成因果前缀/未来修改、未触发新增解除时与EX034全部原列及pending诊断精确等价、原退出优先级、设置/解除/ACF及动量严格等号、score不参与解除、原13域边界及暖机/非法拒绝检查。代表串行/spawn信号和策略/基准各5账本精确一致；真实绑定完整HFQ OHLC独立重算ACF20、range、rawregime、量额归一秩/原确认score及完整pending/age/entry/exit状态。现金、数量、费用、周期、尾仓、年度回报和共同基准核对。未做仓库全量回归；正式FULL只核验声明证据完整性，不证明收益或稳健性。

本轮最小完整账户对照交付与总研究目标分别判断；尚未证明保留原四门的实质参数敏感性改善，总目标仍未达成。

下一步转向原买入确认score阈值边界、量额分量与bull路线敏感性的共同变化，先做完整路径统计，不按已见年份、日期、少一笔交易或单笔利润挑选例外；该诊断方向不等于已声明或启动下一新机制。保留原目标及负面结果，未推进正式阶段四排名/交接、冻结、PTE或生产。

## 正式证据引用

- [N0](../../../assets/deliveries/CANDIDATES/31/evidence/e0c5037346248af68bdb045daf9e6ab09d2cf23d05e26c797e9240992683bb21.json)
- [B0-TIME](../../../assets/deliveries/CANDIDATES/31/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [C0-RANGE_REFRESH](../../../assets/deliveries/CANDIDATES/31/evidence/0121b92afd5b090bcd63a0ac3ff27329dffa2af6951659ddad2913e516551ec3.json)
- [EX033-native-center](../../../assets/deliveries/CANDIDATES/31/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [EX033-native-B0-TIME-P00](../../../assets/deliveries/CANDIDATES/31/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [EX033-native-B0-TIME-P01](../../../assets/deliveries/CANDIDATES/31/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [EX033-native-B0-TIME-P02](../../../assets/deliveries/CANDIDATES/31/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [EX033-native-B0-TIME-P03](../../../assets/deliveries/CANDIDATES/31/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [EX033-native-B0-TIME-P04](../../../assets/deliveries/CANDIDATES/31/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [EX033-native-B0-TIME-P05](../../../assets/deliveries/CANDIDATES/31/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [EX033-native-B0-TIME-P06](../../../assets/deliveries/CANDIDATES/31/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [EX033-native-B0-TIME-P07](../../../assets/deliveries/CANDIDATES/31/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [EX033-native-B0-TIME-P08](../../../assets/deliveries/CANDIDATES/31/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [EX033-native-B0-TIME-P09](../../../assets/deliveries/CANDIDATES/31/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [EX033-native-B0-TIME-P10](../../../assets/deliveries/CANDIDATES/31/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [EX033-native-B0-TIME-P11](../../../assets/deliveries/CANDIDATES/31/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [EX033-native-B0-TIME-P12](../../../assets/deliveries/CANDIDATES/31/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [EX033-native-B0-TIME-P13](../../../assets/deliveries/CANDIDATES/31/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [EX033-native-B0-TIME-P14](../../../assets/deliveries/CANDIDATES/31/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [EX033-native-B0-TIME-P15](../../../assets/deliveries/CANDIDATES/31/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [EX033-native-B0-TIME-P16](../../../assets/deliveries/CANDIDATES/31/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [EX033-native-B0-TIME-P17](../../../assets/deliveries/CANDIDATES/31/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [EX033-native-B0-TIME-P18](../../../assets/deliveries/CANDIDATES/31/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [EX033-native-B0-TIME-P19](../../../assets/deliveries/CANDIDATES/31/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [EX033-native-B0-TIME-P20](../../../assets/deliveries/CANDIDATES/31/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [EX033-native-B0-TIME-P21](../../../assets/deliveries/CANDIDATES/31/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [EX033-native-B0-TIME-P22](../../../assets/deliveries/CANDIDATES/31/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [EX033-native-B0-TIME-P23](../../../assets/deliveries/CANDIDATES/31/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [EX033-native-B0-TIME-P24](../../../assets/deliveries/CANDIDATES/31/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [EX033-native-B0-TIME-P25](../../../assets/deliveries/CANDIDATES/31/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [EX033-native-B0-TIME-P26](../../../assets/deliveries/CANDIDATES/31/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [EX033-native-B0-TIME-P27](../../../assets/deliveries/CANDIDATES/31/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [EX033-native-B0-TIME-P28](../../../assets/deliveries/CANDIDATES/31/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [EX033-native-B0-TIME-P29](../../../assets/deliveries/CANDIDATES/31/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [EX033-native-B0-TIME-P30](../../../assets/deliveries/CANDIDATES/31/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [EX033-native-B0-TIME-P31](../../../assets/deliveries/CANDIDATES/31/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [plan](../../../assets/deliveries/CANDIDATES/31/evidence/e5d58060cd8f0c4fac785217652f38e53e4be89a0d2d8349555adc756ac1489c.json)
- [authorization](../../../assets/deliveries/CANDIDATES/31/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [geometry](../../../assets/deliveries/CANDIDATES/31/evidence/daf7380f2ecb6316690c433351c44d897362258bedcf3b1b2b2ee94a8cf8bc54.json)
- [EX033-paths](../../../assets/deliveries/CANDIDATES/31/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [EX033-refresh](../../../assets/deliveries/CANDIDATES/31/evidence/9f02897390a12003981b948a84fbf53b3bf2f84bbd3f8b78a5d4af582c1f6016.json)
- [EX035-pending](../../../assets/deliveries/CANDIDATES/31/evidence/efd47747c2229a0143f36184f9dd156506999243ddb3934155ff5e43ebd44fe0.json)
- [EX035-pending_method](../../../assets/deliveries/CANDIDATES/31/evidence/36419666782cdd3f8d883e3d0ed61418e7ca14d5df3465c484ce3224224ef2b2.json)
- [final-geometry-reference](../../../assets/deliveries/CANDIDATES/31/evidence/22f71cfaea797f536624eb238c85143de1d52f12289b5b3161d99c4b7c7a4052.json)
- [final-parameter-plans](../../../assets/deliveries/CANDIDATES/31/evidence/b67a9f0194f479649dad3d4fd386dbfa79542a1c12d70529cee28551eb3d0fb0.json)
- [final-plan-references](../../../assets/deliveries/CANDIDATES/31/evidence/741bf8372f603988ad68986215ec5df07145e660ec1aa1ac48d108248a78cb7c.json)
- [final-account-references](../../../assets/deliveries/CANDIDATES/31/evidence/9f929f54f81ae68676df80e11c4d2024e9f15b7b40ddce23cbe713eaddd71cff.json)
- [final-analysis](../../../assets/deliveries/CANDIDATES/31/evidence/eaa8847752b983205fded288983381d55a1351e1e96693c2b29318de3b007146.json)
- [final-conclusion](../../../assets/deliveries/CANDIDATES/31/evidence/c409de01be414a4a9f93fc92c5214ba2c74a2f3e654b8c2da2bf01c010322bfc.json)
- [final-implementation-parent](../../../assets/deliveries/CANDIDATES/31/evidence/5eb62fb7e4edd3b5b1b84f7e911aae6666544a4c2dd5c83c54e25a21cf45eb29.json)
- [final-matrix](../../../assets/deliveries/CANDIDATES/31/evidence/f4cc207cce9b16f77e1cd1df12cfa28b7a5780944255cd9235aeeb7f96a3bc22.json)
- [final-parameter-analysis](../../../assets/deliveries/CANDIDATES/31/evidence/291b3c00e5dd2a96a2856913d343dd48c9f418ff2d236f5dc38763a80c6ca8c4.json)
- [final-parameter-pairs](../../../assets/deliveries/CANDIDATES/31/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [final-precheck](../../../assets/deliveries/CANDIDATES/31/evidence/50743b17cf8bab9550d02bfd46a20a3b4fed91abc07f2a1e2a5cdfb3ea79d507.json)
- [final-registration](../../../assets/deliveries/CANDIDATES/31/evidence/d8da31e27db9dccc96aff8aa5e2a4faab5c755d67e260f323213895f1129d0a7.json)
- [final-reproduction](../../../assets/deliveries/CANDIDATES/31/evidence/1452a7e44c465069ae51a4708a7d53f98f5da8293251d9bf1b605451c8fafc81.json)
- [final-synthetic-check](../../../assets/deliveries/CANDIDATES/31/evidence/8a10a1033dfec80ebf0b71623323cb0a4d0adfee671200ddca03a9b538387ef2.json)
