# S013：下跌路线定时退出后的入场机会刷新

RSCH阶段三，用户授权自主完成目标无需逐轮评审。本轮COMPLETE仅指证据交付完成；保持原经济要求、S013既有数据及执行合同。

## 已有证据与最小对照

原C2132中心年化16.1572%、全窗回撤14.1599%、112闭合交易，四门通过；原完整13维32联合扰动收益Q10仅5.8974%、回撤Q90达30.5044%。买入确认未直接拒绝导致bear敏感性的机会；删项、平滑、条件期限/退出及波动时钟等EX012..32未证明保住经济要求的实质参数改进。

EX033精确复用33原生账户，1793状态分歧段中451段起于TIME；全部目标不同日6100，其中2778日只在单步固定规则/特征下呈现继承状态差异，2291日只呈现当日规则/特征差异，1031日混合。原中心38次bear TIME退出有27次在rawbear与原range入场机会未刷新前再次入场，22次在下一信号日。此为联合参数和既有路径描述，不是单个H的因果贡献，也不能把旧交易收益相加当作阻断后的策略收益。

本轮仅新增入场记忆：最终原reason=time、原持仓路线bear、当日rawregime=bear且bear range_position<=原entry时设置pending。空仓每个T先检查；rawregime!=bear或bear range_position>entry即解除，解除当日可按原规则买入。否则pending拒绝bear原eligible机会；等于entry仍不解除。原confirmation机会/scorepass诊断保留，pending拒绝在score拒绝之前命名。原H8/H4的信号持仓年龄、原ACF20、rawroute/range/确认、loss>trailing>range>time>regime优先级和bull全部保持。无固定等待天数、新阈值、波动时钟、日期或单笔修补；这是新增入场记忆，不宣称只改退出。

最强反证是被阻断的再次买入本来可能有利，等待会漏反弹并损害频率。原112闭合交易距110门只有两笔余量。反复使用已见S013开发池，结构选择来自EX033，存在搜索偏差；无独立验证或未来稳定保证。

一新业务中心、两次实际评价（代表串行/spawn技术重复）、一旧原中心完整账户精确复用。新中心四门通过才做32新完整参数账户，32原EX015账户精确复用；否则零新参数。全部原13数值域与原数值中心保持，5%域宽标准化总L2、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位数。原H仍为真实信号持仓交易日，未变物理单位。暖机沿父实现；不足明确失败，不下载/缩短/替换。

510500.SH、2020-01-02至2026-09-30、1636交易日、100万元、HFQ信号、100整手、T决策/T+1执行、每侧10bp，策略与LimitBuyHold统一1%买入溢价。原四门：年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60日平均≥4闭合交易（至少110）；基准亏损年2022/2023实际连续账户年度收益严格为正。全窗回撤与诊断不追加经济门。

## 两个完整账户

|机制|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
|TIME|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|BEAR_TIME_ENTRY_REFRESH|C6100|10.8392%|10.6140%|86|-2.4305%|-5.1258%|frequency、negative_buyhold_year_profit|

真实新路径设置pending 18次、解除18次，拒绝原eligible bear机会88日。机会数量不等于损失的实际交易数，完整现金/持仓路径可能改变后续机会。

|自然年|原策略收益|新策略收益|原策略回撤|新策略回撤|基准回撤|
|---|---:|---:|---:|---:|---:|
|2020|16.7355%|11.1183%|6.1272%|6.4550%|14.9712%|
|2021|9.9101%|9.7084%|2.7008%|2.8794%|9.7035%|
|2022|12.1687%|-2.4305%|9.7680%|10.6140%|28.4105%|
|2023|0.2841%|-5.1258%|5.6722%|7.4010%|17.2665%|
|2024|64.9989%|64.1845%|10.0213%|4.3370%|18.5736%|
|2025|11.0774%|5.3170%|3.5332%|3.0137%|13.7975%|
|2026|-0.0384%|-0.0384%|4.5425%|4.5420%|18.7646%|

## 参数结果、验证与结论

新中心未通过原四门，未运行新参数账户；事前原域几何保留。不能以较少交易或局部路径改善代替原经济目标。

本轮1新业务中心、2实际评价、1旧中心复用；参数新业务配置0、实际评价0、原参数复用0。纯合成因果前缀/未来修改、无触发原信号等价、原退出优先级、设置/解除/严格等号、确认/ACF门及暖机/非法/原13域边界检查。代表串行/spawn信号和策略/基准各5账本精确一致；真实绑定完整HFQ OHLC独立重算ACF20、range、rawregime、量额归一秩/原确认score及完整pending/age/entry/exit状态。现金、数量、费用、周期、尾仓、年度回报和共同基准核对。未做仓库全量回归；正式FULL仅核验声明证据完整性。

本轮最小完整账户对照完成，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。

本轮完整账户显示，强制等待原range机会刷新会过度阻断：闭合交易112降至86，2022由+12.1687%变为-2.4305%、2023由+0.2841%变为-5.1258%。全窗回撤下降不能替代频率和亏损年盈利，不能认定原重复买回应整体取消。

下一步保留重复入场作为必要对照，检查完整原入场资格（包含ACF）重新激活是否能减少等待，先核对其与本轮范围刷新条件的差异，再选择最小完整账户对照。不按已见单笔利润挑选例外，保留负面结果及原目标。未推进正式阶段四排名/交接、冻结、PTE或生产。

## 正式证据引用

- [N0](../../../assets/deliveries/CANDIDATES/30/evidence/0121b92afd5b090bcd63a0ac3ff27329dffa2af6951659ddad2913e516551ec3.json)
- [B0-TIME](../../../assets/deliveries/CANDIDATES/30/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [EX033-native-center](../../../assets/deliveries/CANDIDATES/30/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [EX033-native-B0-TIME-P00](../../../assets/deliveries/CANDIDATES/30/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [EX033-native-B0-TIME-P01](../../../assets/deliveries/CANDIDATES/30/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [EX033-native-B0-TIME-P02](../../../assets/deliveries/CANDIDATES/30/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [EX033-native-B0-TIME-P03](../../../assets/deliveries/CANDIDATES/30/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [EX033-native-B0-TIME-P04](../../../assets/deliveries/CANDIDATES/30/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [EX033-native-B0-TIME-P05](../../../assets/deliveries/CANDIDATES/30/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [EX033-native-B0-TIME-P06](../../../assets/deliveries/CANDIDATES/30/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [EX033-native-B0-TIME-P07](../../../assets/deliveries/CANDIDATES/30/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [EX033-native-B0-TIME-P08](../../../assets/deliveries/CANDIDATES/30/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [EX033-native-B0-TIME-P09](../../../assets/deliveries/CANDIDATES/30/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [EX033-native-B0-TIME-P10](../../../assets/deliveries/CANDIDATES/30/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [EX033-native-B0-TIME-P11](../../../assets/deliveries/CANDIDATES/30/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [EX033-native-B0-TIME-P12](../../../assets/deliveries/CANDIDATES/30/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [EX033-native-B0-TIME-P13](../../../assets/deliveries/CANDIDATES/30/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [EX033-native-B0-TIME-P14](../../../assets/deliveries/CANDIDATES/30/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [EX033-native-B0-TIME-P15](../../../assets/deliveries/CANDIDATES/30/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [EX033-native-B0-TIME-P16](../../../assets/deliveries/CANDIDATES/30/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [EX033-native-B0-TIME-P17](../../../assets/deliveries/CANDIDATES/30/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [EX033-native-B0-TIME-P18](../../../assets/deliveries/CANDIDATES/30/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [EX033-native-B0-TIME-P19](../../../assets/deliveries/CANDIDATES/30/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [EX033-native-B0-TIME-P20](../../../assets/deliveries/CANDIDATES/30/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [EX033-native-B0-TIME-P21](../../../assets/deliveries/CANDIDATES/30/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [EX033-native-B0-TIME-P22](../../../assets/deliveries/CANDIDATES/30/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [EX033-native-B0-TIME-P23](../../../assets/deliveries/CANDIDATES/30/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [EX033-native-B0-TIME-P24](../../../assets/deliveries/CANDIDATES/30/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [EX033-native-B0-TIME-P25](../../../assets/deliveries/CANDIDATES/30/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [EX033-native-B0-TIME-P26](../../../assets/deliveries/CANDIDATES/30/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [EX033-native-B0-TIME-P27](../../../assets/deliveries/CANDIDATES/30/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [EX033-native-B0-TIME-P28](../../../assets/deliveries/CANDIDATES/30/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [EX033-native-B0-TIME-P29](../../../assets/deliveries/CANDIDATES/30/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [EX033-native-B0-TIME-P30](../../../assets/deliveries/CANDIDATES/30/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [EX033-native-B0-TIME-P31](../../../assets/deliveries/CANDIDATES/30/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [plan](../../../assets/deliveries/CANDIDATES/30/evidence/d3a64708ad639285ce0948a4e7fff278b3b1265b7927d77a118c818259435d4c.json)
- [authorization](../../../assets/deliveries/CANDIDATES/30/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [geometry](../../../assets/deliveries/CANDIDATES/30/evidence/0b40cad9d05883c7f793b1f63c8f935922d1f806f30e7901497890726907c92c.json)
- [EX033-paths](../../../assets/deliveries/CANDIDATES/30/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [EX033-refresh](../../../assets/deliveries/CANDIDATES/30/evidence/9f02897390a12003981b948a84fbf53b3bf2f84bbd3f8b78a5d4af582c1f6016.json)
- [final-declaration-failure](../../../assets/deliveries/CANDIDATES/30/evidence/b9dd155cb729cd9f910437a310318654058b2557bc6c4dba372e5d7ceda42536.json)
- [final-geometry-reference](../../../assets/deliveries/CANDIDATES/30/evidence/b458cbb84f54c21b3159211eb3a07f56fa8841a4c312c88d64742edd01165a64.json)
- [final-parameter-plans](../../../assets/deliveries/CANDIDATES/30/evidence/aeb7ceb930168fc99c576ac324decee09ef6df2b2622cc651dc1b41aef9e08cc.json)
- [final-plan-references](../../../assets/deliveries/CANDIDATES/30/evidence/48309414eb5264efeeffb805da64b931d7ec22a202cd153d6da3bdd017d81480.json)
- [final-account-references](../../../assets/deliveries/CANDIDATES/30/evidence/25f92607a8c927588d2231b31d1def6921405b0a7e4bfe5931c698f539ede00c.json)
- [final-analysis](../../../assets/deliveries/CANDIDATES/30/evidence/5341ec985d2314a9fcea3e58d8c09020cbf2de5309deb15cc08069028fa203b9.json)
- [final-conclusion](../../../assets/deliveries/CANDIDATES/30/evidence/d42f0b4e8b4c283bd725db30cb5007193b5dc3dcc3e7e37ef7293eb6b5ce31e3.json)
- [final-matrix](../../../assets/deliveries/CANDIDATES/30/evidence/e3464f9b0edce0fd2fa336af0c00055e26fe7cc0092adf604c81782ac0d81309.json)
- [final-parameter-analysis](../../../assets/deliveries/CANDIDATES/30/evidence/454aafdfe6aadc07f5c88994f5760d2cfc285f95b713adb588c69f7f6c5daa7a.json)
- [final-parameter-pairs](../../../assets/deliveries/CANDIDATES/30/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [final-precheck](../../../assets/deliveries/CANDIDATES/30/evidence/5151b763c610e10f45065c7974876b9a6e7d347de6732acf0a2d40b08539555c.json)
- [final-registration](../../../assets/deliveries/CANDIDATES/30/evidence/d8da31e27db9dccc96aff8aa5e2a4faab5c755d67e260f323213895f1129d0a7.json)
- [final-reproduction](../../../assets/deliveries/CANDIDATES/30/evidence/c027d2e997aa510236222fbdf27b764bc31b94a31a7ac12f916cea6b1d2a8d4e.json)
- [final-synthetic-check](../../../assets/deliveries/CANDIDATES/30/evidence/6f2856797b0e3ae9cad81ec1df4e7f03e0d3e9d478c10ce4d923ab3f61161567.json)
