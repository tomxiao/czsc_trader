# S013：有上限的价格条件提前退出与参数敏感性

RSCH阶段三；用户授权自主完成目标，无需逐轮评审。S013既有数据、MANDATE/6、原四项经济目标及执行合同保持。COMPLETE仅指本轮正式证据完整交付，目标判断另列。

## 假说、完整对照与最强反证

原H4改H3显著改变收益及2023盈亏。EX016在H期限后按价格条件才卖出的机制会无限延长信号持仓，全部未达标。已留存的2023事件描述中，正相对入场价bear定时退出的随后3日均值弱于非正组，但10日方向反转，事件重叠非独立，不能据此挑持有窗或直接推算新政策收益。

本轮将退出选择限制在原期限的前一天，并保留原最迟期限：EARLY_POSITIVE在bear age>=max(1,H-1)且age<H、当前HFQ信号Close严格高于入场信号Close时提前退出；EARLY_NONPOSITIVE测试相反条件Close<=anchor。等号只归非正组，H=1不提前，H仍完整1..60活跃参数。原H最迟信号年龄无条件保留，两个方向不会无限延长。上涨时间限制及两路其他退出优先级保持loss>trailing>range>time(提前或默认)>regime。

两个对应组合另叠加EX020 NEW_BULL_BODY_UP：仅raw bear转bull当日、空仓原入场机会成立时，当前Close>Open AND原确认分；stablebull与bear不加门。四个中心均为原ACF0.1/H4，事前固定，原C2132 H4、原H3未达标诊断控制、EX020 BODY H4完整账户核对后复用，共3控制。单独提前退出、相反条件、组合与既有BODY逐对比较，不能把单组件收益相加当作组合效果。

选择历史完整披露：BODY H4既有年化16.6697%、回撤13.3493%、2023盈利，但仅109笔而未满足110笔要求；本轮组合由已见开发证据启发。提前退出是否增加完成交易、改善收益，必须重新运行整套账户，不能从旧交易补一笔或推断独立贡献。EX021参考均值平滑4中心全失败，证明数值平滑不是经济稳定性的证据。

最强反证：相对信号价上涨并不等于实际净盈利（1%买入溢价、实际成交与费用仍计算）；提前卖出可能截断后续反弹、改变空仓机会和资金、增加成本，组合可能放大H/ACF及边界切换脆弱性。单日提前缓冲是新固定结构，不搜索新期限；已有H4/H3跳变并未凭结构名自动解决。只在反复研究的S013开发池测试，无独立验证。中心漂亮、更多交易或相对退化小，均不能单独宣布目标完成。

参考锚为原信号入场Close，非实际买价；信号年龄不因实际未成交或买卖回执重置，沿用原策略语义。最迟H约束是信号状态约束，实际账户持仓与执行延迟仍完整对账。所有价格和前raw状态在T时点已知，T+1执行；body条件缺失不填充。

510500.SH、2020-01-02至2026-09-30、1636实际交易日、100万元、HFQ研究单位、整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价。仅S013已有数据，无新增依赖、外部数据或独立验证。

原四门：净年化≥正收益基准1.5倍、每自然年回撤严格小于基准、每60交易日平均≥4闭合交易、基准亏损年2022/2023实际年度收益严格为正。参数诊断与全窗回撤不新增经济硬门。

## 全部中心完整账户

|机制/背景|候选|年化|全期回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
|TIME/B0|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|TIME/B2|C7009|11.7652%|17.4850%|121|5.9394%|-1.9690%|negative_buyhold_year_profit|
|NEW_BULL_BODY_UP/B0|C9102|16.6697%|13.3493%|109|14.3291%|1.2316%|frequency|
|EARLY_POSITIVE/B0|C9500|14.9677%|18.6120%|114|13.6418%|-1.4429%|negative_buyhold_year_profit|
|EARLY_NONPOSITIVE/B0|C9501|11.0563%|23.7749%|117|10.3054%|-4.1218%|negative_buyhold_year_profit|
|NEW_BULL_BODY_EARLY_POSITIVE/B0|C9502|15.4729%|16.7911%|111|15.8339%|-0.5145%|negative_buyhold_year_profit|
|NEW_BULL_BODY_EARLY_NONPOSITIVE/B0|C9503|11.5434%|21.9925%|114|12.4302%|-3.2171%|negative_buyhold_year_profit|

提前与默认退出信号独立核对：

N0：真正提前退出信号26、默认bear期限退出信号21、最大bear信号年龄4。逐日独立重建route/age/anchor/peak，提前条件与优先级精确一致；信号计数不是实际交易盈亏贡献。

N1：真正提前退出信号19、默认bear期限退出信号20、最大bear信号年龄4。逐日独立重建route/age/anchor/peak，提前条件与优先级精确一致；信号计数不是实际交易盈亏贡献。

N2：真正提前退出信号26、默认bear期限退出信号21、最大bear信号年龄4。逐日独立重建route/age/anchor/peak，提前条件与优先级精确一致；信号计数不是实际交易盈亏贡献。

N3：真正提前退出信号19、默认bear期限退出信号20、最大bear信号年龄4。逐日独立重建route/age/anchor/peak，提前条件与优先级精确一致；信号计数不是实际交易盈亏贡献。

## 完整参数诊断

四个中心均未通过原四门，未追加参数账户；事前完整13维几何与不适用原因留存。不能用稳定但不达标的账户宣布目标达成。

## 验证、结论与下一步

4个新业务中心、5次实际评价（含一次串行/spawn技术重复）、3个原控制复用；参数新业务配置0、实际评价0、既有参数复用0。合计新业务配置4、实际评价5。各原生完整账户、现金/数量/费用/周期/尾仓/年度回报对账、共同基准与原买入确认逐日独立核对，技术与身份验证完整留存。

合成前缀/未来修改因果性、H1/2/4/60期限边界/正零负锚/最迟H/原score和退出优先级/body切换与稳定状态/非法价格输入及代表串行/spawn双方5账本精确一致；研究源码Ruff通过，未做仓库全量回归。全部历史证据保持不可变，Git不是数据资产备份。FULL公共交付验证只确认关联证据完整性，不保证交易效果。

本轮完整对照结束，未证明保留原四门的实质参数敏感性改善；总目标仍未达成。

未推进正式阶段四五项自检/族排名/交接、冻结、PTE或生产。下一步依据全账户与同坐标反证判断有界提前退出是否提供可用信息；不按已见亏损重选条件或缓冲日数、放宽原目标或擅自新增数据。

## 正式证据引用

- [N0完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/d3213f52c3aa941acdb3723cf490a6539858d861d200d0b297ca0ebc98d01306.json)
- [N1完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/3345964158b71e5c810aec978727531621f717350fd87ace1d02dbbbb5671f41.json)
- [N2完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/e4c784bcba3367e9fe981b95448f49a6f8fc372aae95e0d6de65309b264563b9.json)
- [N3完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/c1e741a53635384cf88a5f93ca50de090f52a0ddaa7464e1c9c2b753d7237435.json)
- [B0-TIME完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B2-TIME完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [B0-BODY完整账户](../../../assets/deliveries/CANDIDATES/18/evidence/7be615850fb5672f0d9920e1033e425a0d99affc0d3e3d03c206b93885d3cda7.json)
- [既有诊断输入B0-TIME-P00](../../../assets/deliveries/CANDIDATES/18/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [既有诊断输入B0-TIME-P01](../../../assets/deliveries/CANDIDATES/18/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [既有诊断输入B0-TIME-P02](../../../assets/deliveries/CANDIDATES/18/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [既有诊断输入B0-TIME-P03](../../../assets/deliveries/CANDIDATES/18/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [既有诊断输入B0-TIME-P04](../../../assets/deliveries/CANDIDATES/18/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [既有诊断输入B0-TIME-P05](../../../assets/deliveries/CANDIDATES/18/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [既有诊断输入B0-TIME-P06](../../../assets/deliveries/CANDIDATES/18/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [既有诊断输入B0-TIME-P07](../../../assets/deliveries/CANDIDATES/18/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [既有诊断输入B0-TIME-P08](../../../assets/deliveries/CANDIDATES/18/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [既有诊断输入B0-TIME-P09](../../../assets/deliveries/CANDIDATES/18/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [既有诊断输入B0-TIME-P10](../../../assets/deliveries/CANDIDATES/18/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [既有诊断输入B0-TIME-P11](../../../assets/deliveries/CANDIDATES/18/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [既有诊断输入B0-TIME-P12](../../../assets/deliveries/CANDIDATES/18/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [既有诊断输入B0-TIME-P13](../../../assets/deliveries/CANDIDATES/18/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [既有诊断输入B0-TIME-P14](../../../assets/deliveries/CANDIDATES/18/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [既有诊断输入B0-TIME-P15](../../../assets/deliveries/CANDIDATES/18/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [既有诊断输入B0-TIME-P16](../../../assets/deliveries/CANDIDATES/18/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [既有诊断输入B0-TIME-P17](../../../assets/deliveries/CANDIDATES/18/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [既有诊断输入B0-TIME-P18](../../../assets/deliveries/CANDIDATES/18/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [既有诊断输入B0-TIME-P19](../../../assets/deliveries/CANDIDATES/18/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [既有诊断输入B0-TIME-P20](../../../assets/deliveries/CANDIDATES/18/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [既有诊断输入B0-TIME-P21](../../../assets/deliveries/CANDIDATES/18/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [既有诊断输入B0-TIME-P22](../../../assets/deliveries/CANDIDATES/18/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [既有诊断输入B0-TIME-P23](../../../assets/deliveries/CANDIDATES/18/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [既有诊断输入B0-TIME-P24](../../../assets/deliveries/CANDIDATES/18/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [既有诊断输入B0-TIME-P25](../../../assets/deliveries/CANDIDATES/18/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [既有诊断输入B0-TIME-P26](../../../assets/deliveries/CANDIDATES/18/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [既有诊断输入B0-TIME-P27](../../../assets/deliveries/CANDIDATES/18/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [既有诊断输入B0-TIME-P28](../../../assets/deliveries/CANDIDATES/18/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [既有诊断输入B0-TIME-P29](../../../assets/deliveries/CANDIDATES/18/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [既有诊断输入B0-TIME-P30](../../../assets/deliveries/CANDIDATES/18/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [既有诊断输入B0-TIME-P31](../../../assets/deliveries/CANDIDATES/18/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [既有诊断输入N8-P00](../../../assets/deliveries/CANDIDATES/18/evidence/03571480a68a616cd5396fc6d401220757ccdbd044a9b584ff33faa7e43256b1.json)
- [既有诊断输入N8-P01](../../../assets/deliveries/CANDIDATES/18/evidence/ce784b17a9f8205d11cf9b042ff16cc14d6064826be756254d0ca7495e0c73e9.json)
- [既有诊断输入N8-P02](../../../assets/deliveries/CANDIDATES/18/evidence/c0a455bfd71dca6f65a01d9c4a1f30c463100a05c5e296558d6a205be7b9bb3c.json)
- [既有诊断输入N8-P03](../../../assets/deliveries/CANDIDATES/18/evidence/8447ad9bd4b2d3fb04c77e8a6169396b33abd2c4927e98f6a24b6a73cb1f2572.json)
- [既有诊断输入N8-P04](../../../assets/deliveries/CANDIDATES/18/evidence/1d56fce2b90db2af34cbb9f0094e25d740c55304cdc5d8e40a6eee71fa8384a7.json)
- [既有诊断输入N8-P05](../../../assets/deliveries/CANDIDATES/18/evidence/569b4d33bdd0313ef804dc6f05b76183d1eb612f44744124c6c1ff8276b09468.json)
- [既有诊断输入N8-P06](../../../assets/deliveries/CANDIDATES/18/evidence/92177316c263c1a6a81a5163808bc8975adbb797bd1da9d7d24b92b4e8b731a7.json)
- [既有诊断输入N8-P07](../../../assets/deliveries/CANDIDATES/18/evidence/90716ae57f452dd5baecac2b50bc5f7e70c64051c62697d9c5c8532c01ae8f46.json)
- [既有诊断输入N8-P08](../../../assets/deliveries/CANDIDATES/18/evidence/7686bdf5076b990237126d2a35e74491ac405cc0ae9e6da8e058b2ab763ab8a8.json)
- [既有诊断输入N8-P09](../../../assets/deliveries/CANDIDATES/18/evidence/777eaf9b4927ec1a390e51f5650b7cdb351333b641472748b1334d7dc47dc0dd.json)
- [既有诊断输入N8-P10](../../../assets/deliveries/CANDIDATES/18/evidence/7b34575a5af3d0d8776582ecc05f97acd2e44377eebc3e1f6b375bc164d44381.json)
- [既有诊断输入N8-P11](../../../assets/deliveries/CANDIDATES/18/evidence/6d7d4de195479df634c726acfc725cc2ebe4bce42895dd1c2100ead0cad1d1ea.json)
- [既有诊断输入N8-P12](../../../assets/deliveries/CANDIDATES/18/evidence/a995cc27b08ccf340f08998e0f28083d02ca2153503328893938c241f1897474.json)
- [既有诊断输入N8-P13](../../../assets/deliveries/CANDIDATES/18/evidence/7d19b6b9c5f80b34be89b405b04d41416bd349bfe4440c997da812f2faaf135c.json)
- [既有诊断输入N8-P14](../../../assets/deliveries/CANDIDATES/18/evidence/d138d5fa48707489bd6c8b3f6191caedd26e3484b51a02af44eaaac7599e50b8.json)
- [既有诊断输入N8-P15](../../../assets/deliveries/CANDIDATES/18/evidence/a561deaa3a129501dee0351ff46e535ade90f84f9da3bc6d699dc37c0b266588.json)
- [既有诊断输入N8-P16](../../../assets/deliveries/CANDIDATES/18/evidence/9367c023616684b385526dc2890608b96199d764fd7528fc4f78aa902de3a7ca.json)
- [既有诊断输入N8-P17](../../../assets/deliveries/CANDIDATES/18/evidence/a529ed3172b110215c6840045cd5ae49a26c5d20212e80d27a5f7cd7ea691adf.json)
- [既有诊断输入N8-P18](../../../assets/deliveries/CANDIDATES/18/evidence/d24abab7755f6f6dc3e83789f430fab4095c3aecd86c711d8a6a15b5f578f2ff.json)
- [既有诊断输入N8-P19](../../../assets/deliveries/CANDIDATES/18/evidence/fb7ab4f5c42cc22a02badf706b792ccb6c7948c1e563a9a6f14d2437609a4963.json)
- [既有诊断输入N8-P20](../../../assets/deliveries/CANDIDATES/18/evidence/72f63bffe90852ae501573e69f0e17d436eadbce8be313fc8b77573ef00fe31e.json)
- [既有诊断输入N8-P21](../../../assets/deliveries/CANDIDATES/18/evidence/5e5b27cb5f85a5e14e526ffd6ac1d35c7de3a042c3443362fbd367d682822d32.json)
- [既有诊断输入N8-P22](../../../assets/deliveries/CANDIDATES/18/evidence/fc7ea90b4925fcbe1efd2c632c6a1603d49b48df0feca845c1a5eebab7be1787.json)
- [既有诊断输入N8-P23](../../../assets/deliveries/CANDIDATES/18/evidence/787ae51ef463005ca033db01a769059c5313c23bf6bf8c28e4e7a578fe015ed5.json)
- [既有诊断输入N8-P24](../../../assets/deliveries/CANDIDATES/18/evidence/299ec56048bf1d7e989eb9f62560fe499e8f1e0e78e7d2072331caf203e112a8.json)
- [既有诊断输入N8-P25](../../../assets/deliveries/CANDIDATES/18/evidence/e016caafd734d51c9d64df2180f8caeb4e587361a31154cf4c08bfe92536cb86.json)
- [既有诊断输入N8-P26](../../../assets/deliveries/CANDIDATES/18/evidence/daaba1bd5291638645630889e2a290e32287f6f26e25f66aec32fd38d42eea15.json)
- [既有诊断输入N8-P27](../../../assets/deliveries/CANDIDATES/18/evidence/f44fe2ea4c5eedfde3e6b7e64200535ba4597cc4e50bf1231527377d2e50651a.json)
- [既有诊断输入N8-P28](../../../assets/deliveries/CANDIDATES/18/evidence/40310c35b259719891e96831c9432c4fc0be7c5b41a678fecb49fa1baeb6ddf4.json)
- [既有诊断输入N8-P29](../../../assets/deliveries/CANDIDATES/18/evidence/8c69faa83e1dbc492fb542084f544ae087e8543c1895a0b3544b593f61e112a8.json)
- [既有诊断输入N8-P30](../../../assets/deliveries/CANDIDATES/18/evidence/c22427d5db1e373153c45b8cc2afc7e46a79cb314848d04357142efd0c7d450d.json)
- [既有诊断输入N8-P31](../../../assets/deliveries/CANDIDATES/18/evidence/5087b30f7abfba3714c1d8735a5707ff8bcd9e6163e608d2889d990466d256d8.json)
- [既有诊断输入C2132-center](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX017-N0](../../../assets/deliveries/CANDIDATES/18/evidence/b4294f15cd04b72e08a0267e9ea782d79b4e25020490849384e6a6d41e839ae6.json)
- [既有诊断输入EX017-N1](../../../assets/deliveries/CANDIDATES/18/evidence/d3fc8001128683a4ac797aaa72cadc9b42e9f124175fd4e731863bd3a0c3faad.json)
- [既有诊断输入EX017-N2](../../../assets/deliveries/CANDIDATES/18/evidence/8a0e75060ac94eebdb39d7b87ea2cfcde99b12a25ccced257ec0a883f804b20d.json)
- [既有诊断输入EX017-N3](../../../assets/deliveries/CANDIDATES/18/evidence/42e49d3f58beb8cdc01e5dff0356ef1f723b4a08737e1eafade3f22998488869.json)
- [既有诊断输入EX017-N4](../../../assets/deliveries/CANDIDATES/18/evidence/9de2d557dbf8e423efbdd333729bfbf1f591a5e82225c326404e4e3916525c29.json)
- [既有诊断输入EX017-N5](../../../assets/deliveries/CANDIDATES/18/evidence/47b080a1388d5ee3367d4f46320be7e07aa849130cfe84b30d58299cf361b467.json)
- [既有诊断输入EX017-N6](../../../assets/deliveries/CANDIDATES/18/evidence/523f37567ed83d1a81490cbefaf4a916be8740032e3e4f172d02b2ed5125738b.json)
- [既有诊断输入EX017-N7](../../../assets/deliveries/CANDIDATES/18/evidence/ed37b1fdee99d627fd61268c7501c13bcb2d1dceb78dcd46dd49e5a6495387c2.json)
- [既有诊断输入EX017-N8](../../../assets/deliveries/CANDIDATES/18/evidence/0f56d802bcbd14ec473c38bf0bfb22846c714ceefd00ffb518d02e798571db0a.json)
- [既有诊断输入EX017-N9](../../../assets/deliveries/CANDIDATES/18/evidence/b8653ee79c6c54069d53d265e28b577df4beebe57562344de432ad7e95d8b8af.json)
- [既有诊断输入EX017-N10](../../../assets/deliveries/CANDIDATES/18/evidence/30116230629efc326ca88d5b4b5feb38feb199531d9ba48c16888529c76b7521.json)
- [既有诊断输入EX017-N11](../../../assets/deliveries/CANDIDATES/18/evidence/1ff477be6f155f0663b7f2b6aa92ac7460b0cb95b69f3842d70f616659f0b3e9.json)
- [既有诊断输入EX017-B0-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX017-B1-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [既有诊断输入EX017-B2-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [既有诊断输入EX017-B3-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/1fecef52e37e7073dcf4208b5895c71146c5e775f3fc41fb88e60e59ed090361.json)
- [既有诊断输入EX017-B0-TIME-P00](../../../assets/deliveries/CANDIDATES/18/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [既有诊断输入EX017-B0-TIME-P01](../../../assets/deliveries/CANDIDATES/18/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [既有诊断输入EX017-B0-TIME-P02](../../../assets/deliveries/CANDIDATES/18/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [既有诊断输入EX017-B0-TIME-P03](../../../assets/deliveries/CANDIDATES/18/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [既有诊断输入EX017-B0-TIME-P04](../../../assets/deliveries/CANDIDATES/18/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [既有诊断输入EX017-B0-TIME-P05](../../../assets/deliveries/CANDIDATES/18/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [既有诊断输入EX017-B0-TIME-P06](../../../assets/deliveries/CANDIDATES/18/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [既有诊断输入EX017-B0-TIME-P07](../../../assets/deliveries/CANDIDATES/18/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [既有诊断输入EX017-B0-TIME-P08](../../../assets/deliveries/CANDIDATES/18/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [既有诊断输入EX017-B0-TIME-P09](../../../assets/deliveries/CANDIDATES/18/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [既有诊断输入EX017-B0-TIME-P10](../../../assets/deliveries/CANDIDATES/18/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [既有诊断输入EX017-B0-TIME-P11](../../../assets/deliveries/CANDIDATES/18/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [既有诊断输入EX017-B0-TIME-P12](../../../assets/deliveries/CANDIDATES/18/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [既有诊断输入EX017-B0-TIME-P13](../../../assets/deliveries/CANDIDATES/18/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [既有诊断输入EX017-B0-TIME-P14](../../../assets/deliveries/CANDIDATES/18/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [既有诊断输入EX017-B0-TIME-P15](../../../assets/deliveries/CANDIDATES/18/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [既有诊断输入EX017-B0-TIME-P16](../../../assets/deliveries/CANDIDATES/18/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [既有诊断输入EX017-B0-TIME-P17](../../../assets/deliveries/CANDIDATES/18/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [既有诊断输入EX017-B0-TIME-P18](../../../assets/deliveries/CANDIDATES/18/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [既有诊断输入EX017-B0-TIME-P19](../../../assets/deliveries/CANDIDATES/18/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [既有诊断输入EX017-B0-TIME-P20](../../../assets/deliveries/CANDIDATES/18/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [既有诊断输入EX017-B0-TIME-P21](../../../assets/deliveries/CANDIDATES/18/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [既有诊断输入EX017-B0-TIME-P22](../../../assets/deliveries/CANDIDATES/18/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [既有诊断输入EX017-B0-TIME-P23](../../../assets/deliveries/CANDIDATES/18/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [既有诊断输入EX017-B0-TIME-P24](../../../assets/deliveries/CANDIDATES/18/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [既有诊断输入EX017-B0-TIME-P25](../../../assets/deliveries/CANDIDATES/18/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [既有诊断输入EX017-B0-TIME-P26](../../../assets/deliveries/CANDIDATES/18/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [既有诊断输入EX017-B0-TIME-P27](../../../assets/deliveries/CANDIDATES/18/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [既有诊断输入EX017-B0-TIME-P28](../../../assets/deliveries/CANDIDATES/18/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [既有诊断输入EX017-B0-TIME-P29](../../../assets/deliveries/CANDIDATES/18/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [既有诊断输入EX017-B0-TIME-P30](../../../assets/deliveries/CANDIDATES/18/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [既有诊断输入EX017-B0-TIME-P31](../../../assets/deliveries/CANDIDATES/18/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [既有诊断输入EX017-N2-P00](../../../assets/deliveries/CANDIDATES/18/evidence/e24ca6e324762a6364da0449ac289ebfe7252c00729de48bfdd861dc18182e62.json)
- [既有诊断输入EX017-N2-P01](../../../assets/deliveries/CANDIDATES/18/evidence/cb4fbbbb29028ddff41836d640b6788847ab7a30a562b603e7dd538492f7a767.json)
- [既有诊断输入EX017-N2-P02](../../../assets/deliveries/CANDIDATES/18/evidence/3e77466fd8c00fe21395aa6723bd27b7734dcb309685bafeeb14e3f217100944.json)
- [既有诊断输入EX017-N2-P03](../../../assets/deliveries/CANDIDATES/18/evidence/c670fa67d35e4b1d869be5fabc068b7f91c3806f2bd0cd962bfb673d010149bf.json)
- [既有诊断输入EX017-N2-P04](../../../assets/deliveries/CANDIDATES/18/evidence/95c1d89b955962308b968c6150d96fcadae459e4a5b4db7a8a5844db80647a9c.json)
- [既有诊断输入EX017-N2-P05](../../../assets/deliveries/CANDIDATES/18/evidence/c0d59644bf67879259740abdae57b082ff4b8b7a5dbdd0327a46e44bce4eec2a.json)
- [既有诊断输入EX017-N2-P06](../../../assets/deliveries/CANDIDATES/18/evidence/3a504db0898e5d212ee8d1dd5929a3b677f73752026b35b82c2edbd0ff230713.json)
- [既有诊断输入EX017-N2-P07](../../../assets/deliveries/CANDIDATES/18/evidence/edd0bebac0ffd9ec241f4e2669b85fccd693c08c380ded9abed7d220ceba647f.json)
- [既有诊断输入EX017-N2-P08](../../../assets/deliveries/CANDIDATES/18/evidence/5104986dc438227e52fd43f845e1902c43401560900ee9a8f5c95ca22b9e0150.json)
- [既有诊断输入EX017-N2-P09](../../../assets/deliveries/CANDIDATES/18/evidence/a2edcc96f044fbc6b6397d5dd9ef4aedd8f4d6b97b769d0ed4bf5877db383d89.json)
- [既有诊断输入EX017-N2-P10](../../../assets/deliveries/CANDIDATES/18/evidence/9c08c3a5bd447658d02c407c1cc8f37129ddf5e0b85cafed78a3ffbf9c287f7f.json)
- [既有诊断输入EX017-N2-P11](../../../assets/deliveries/CANDIDATES/18/evidence/34b73e883177d8eba4409b335873b4b974d28e67600da784c151a98a758e80ce.json)
- [既有诊断输入EX017-N2-P12](../../../assets/deliveries/CANDIDATES/18/evidence/35113acf5d6c7bc53f2eccf436b75f85aee93453cdd6656335fe9f0756e773f4.json)
- [既有诊断输入EX017-N2-P13](../../../assets/deliveries/CANDIDATES/18/evidence/a06bb890d62856838fe8caf5cd1beafb4b3810ab4666b56d3506e930ceeefba8.json)
- [既有诊断输入EX017-N2-P14](../../../assets/deliveries/CANDIDATES/18/evidence/bf9d163cd4843faaacc04837f985e0e37b16cd7369741cc651b78f4b8c2e025c.json)
- [既有诊断输入EX017-N2-P15](../../../assets/deliveries/CANDIDATES/18/evidence/05eae7360e2be9e3bbf81ffd536fc68be52cdb55e9b6d52019ffde7e60e6e82a.json)
- [既有诊断输入EX017-N2-P16](../../../assets/deliveries/CANDIDATES/18/evidence/7c13fc4f141e6c47f25d1c028f4c5c7cb651eaa43528371316f116c4560a2dd0.json)
- [既有诊断输入EX017-N2-P17](../../../assets/deliveries/CANDIDATES/18/evidence/a7a2a20ada9d7d32e705aa00c693f6bdc480dbf6d2a1d9b969046c1a6e8e69cf.json)
- [既有诊断输入EX017-N2-P18](../../../assets/deliveries/CANDIDATES/18/evidence/6c59bee6d5e90364e2755f681caa8cd44098fd270886185346a2d72f6a9311a6.json)
- [既有诊断输入EX017-N2-P19](../../../assets/deliveries/CANDIDATES/18/evidence/6708efe87217df7e86a458ad24970b35a8b1e1e7f1214926e5ed49354398b564.json)
- [既有诊断输入EX017-N2-P20](../../../assets/deliveries/CANDIDATES/18/evidence/02df86cd1c17d4649f8b57fbe3a8b5999ae9fbe34fb72e943b293a7e58f57ac4.json)
- [既有诊断输入EX017-N2-P21](../../../assets/deliveries/CANDIDATES/18/evidence/a2bbda5a7823baf4feb4b86fcbb0ccb45475f9eb014530f44885265de30a21d9.json)
- [既有诊断输入EX017-N2-P22](../../../assets/deliveries/CANDIDATES/18/evidence/220e6386729f91ba585356269227619b2a67b51effc814e7821d0c127b8cc004.json)
- [既有诊断输入EX017-N2-P23](../../../assets/deliveries/CANDIDATES/18/evidence/790b4f4ee6b566ad018e00d9434d226e76b7e29fd948907260bab0a20acf9e87.json)
- [既有诊断输入EX017-N2-P24](../../../assets/deliveries/CANDIDATES/18/evidence/0e450b22f717d7fa0454d43c88801b8f159d33dcc1ee008b043ef0f4808fabdc.json)
- [既有诊断输入EX017-N2-P25](../../../assets/deliveries/CANDIDATES/18/evidence/7ce07666916bbf36a59d7d39349cec9eefc5d647d8c215b2d7166513ea783f34.json)
- [既有诊断输入EX017-N2-P26](../../../assets/deliveries/CANDIDATES/18/evidence/7664e0b2beedc6281c8ad6727832c7fe27efd866dcb3f413e4404bbca182d4b9.json)
- [既有诊断输入EX017-N2-P27](../../../assets/deliveries/CANDIDATES/18/evidence/5a58342bf7c3fa2a9712abc146abb7d0e001e9c958475abdd3963d36ad7f9cf3.json)
- [既有诊断输入EX017-N2-P28](../../../assets/deliveries/CANDIDATES/18/evidence/84f5bd2644618d0fe29d27d2921b2ae7ec4e59f960063b1b5e382fc01a7f4fd2.json)
- [既有诊断输入EX017-N2-P29](../../../assets/deliveries/CANDIDATES/18/evidence/14558ba1e463f25415c8eee907b6ae443f9b31d4e67da325a99f55ce8f9556bc.json)
- [既有诊断输入EX017-N2-P30](../../../assets/deliveries/CANDIDATES/18/evidence/64a52e7e28c0ce7a5f322385d41d63b9d1276460241746dad1cce97a674965f7.json)
- [既有诊断输入EX017-N2-P31](../../../assets/deliveries/CANDIDATES/18/evidence/31979ad31132558f9cd2334766317f8a360e4381279fa395dcc880173c7bdd3d.json)
- [既有诊断输入EX017-B2-TIME-P00](../../../assets/deliveries/CANDIDATES/18/evidence/c083c2c91c2d68b92e9faede727cd618d500aa4fd4c9caff0760c1ef11711d2c.json)
- [既有诊断输入EX017-B2-TIME-P01](../../../assets/deliveries/CANDIDATES/18/evidence/bd482c1f18a70767ef7953b62d411139e26529522f7a2d0a0eac325970f75688.json)
- [既有诊断输入EX017-B2-TIME-P02](../../../assets/deliveries/CANDIDATES/18/evidence/39587eb6db203968f686902c29aafd113a37a003a2fc772197e312a422cf9392.json)
- [既有诊断输入EX017-B2-TIME-P03](../../../assets/deliveries/CANDIDATES/18/evidence/d08dea900a888fb9d9a90b60f0d12c8150fcca92724fc434749b5af3f7e22b12.json)
- [既有诊断输入EX017-B2-TIME-P04](../../../assets/deliveries/CANDIDATES/18/evidence/f0ac470fb46a6105dd822858bf612f6dd95cc76c9a0ec6e569154ee45097add2.json)
- [既有诊断输入EX017-B2-TIME-P05](../../../assets/deliveries/CANDIDATES/18/evidence/1750d794a79225ad36f3e030c15b001ecf8557258b0f568e790a20233c5e2a15.json)
- [既有诊断输入EX017-B2-TIME-P06](../../../assets/deliveries/CANDIDATES/18/evidence/9533a70b1d855f6075069e3bd9d999992d4179ed03fdb7925c12d1d0a72258a1.json)
- [既有诊断输入EX017-B2-TIME-P07](../../../assets/deliveries/CANDIDATES/18/evidence/2b97d265c2beeb3e2f95dd3664bbbd531e5312946b646f79fce4403b502b5d5e.json)
- [既有诊断输入EX017-B2-TIME-P08](../../../assets/deliveries/CANDIDATES/18/evidence/8ca0507e2d62bad528122042c79ea07283920e11fc96605d12e3a0a143c18472.json)
- [既有诊断输入EX017-B2-TIME-P09](../../../assets/deliveries/CANDIDATES/18/evidence/14f5f1f42b42fed8ba819f04621b96c78c3196c6697c28abd774a4a767cf7ae2.json)
- [既有诊断输入EX017-B2-TIME-P10](../../../assets/deliveries/CANDIDATES/18/evidence/e75dd3ce0d9cabfdc4558a047352f11af5da3c9652ecbf03013e1dfa545bd061.json)
- [既有诊断输入EX017-B2-TIME-P11](../../../assets/deliveries/CANDIDATES/18/evidence/5ef58a11808c4753ce31e0aad6ffb1093942e419c6b2c40142b7fa4ff908fe6e.json)
- [既有诊断输入EX017-B2-TIME-P12](../../../assets/deliveries/CANDIDATES/18/evidence/9ccec27dfacbb8ab5217f9a111a0d4c2ba8e9ca3841541f7dc2e94b77b6ae5ea.json)
- [既有诊断输入EX017-B2-TIME-P13](../../../assets/deliveries/CANDIDATES/18/evidence/270f1fc0b3d23b72e49f3ed6113df774c6c6a00aa0684ef67fb7d770e81c9c9e.json)
- [既有诊断输入EX017-B2-TIME-P14](../../../assets/deliveries/CANDIDATES/18/evidence/fc0efbd98359d36e9e2faee6d6402b30a4ec56fa263b604032236419c57d8dd0.json)
- [既有诊断输入EX017-B2-TIME-P15](../../../assets/deliveries/CANDIDATES/18/evidence/1e9cf3ba95502175d78cb8ce49bca4653c7ff2615c5c7689ba3f03408e2ee9f4.json)
- [既有诊断输入EX017-B2-TIME-P16](../../../assets/deliveries/CANDIDATES/18/evidence/e6bb70dfb44374693fc6956ae6e25e3a7c44160938f630b232360d5791c434de.json)
- [既有诊断输入EX017-B2-TIME-P17](../../../assets/deliveries/CANDIDATES/18/evidence/255e8cbdec6d457bebf4ce9b8727c9501aa07e04f4edc8d37ff1f931da8b373a.json)
- [既有诊断输入EX017-B2-TIME-P18](../../../assets/deliveries/CANDIDATES/18/evidence/e7f60ac95e11b72ba93c7f73c54c1e561354a5e96599754a7259430f9aee7cfd.json)
- [既有诊断输入EX017-B2-TIME-P19](../../../assets/deliveries/CANDIDATES/18/evidence/cbc796225e5277f0e52af6240f21c0b22f9ea31cdb7e7383ad9ec1fbb964aa93.json)
- [既有诊断输入EX017-B2-TIME-P20](../../../assets/deliveries/CANDIDATES/18/evidence/77766dc37424606e78b92eabd2d6192d3784706d7ec63a4619b5854b30b4308c.json)
- [既有诊断输入EX017-B2-TIME-P21](../../../assets/deliveries/CANDIDATES/18/evidence/14e14c8f275e65613de6fa7c8ebef58925c16d1c9d1baca59582a72151e1cdf7.json)
- [既有诊断输入EX017-B2-TIME-P22](../../../assets/deliveries/CANDIDATES/18/evidence/e3862d18742dfc79feb53a43e78d98bac7865c13851e4060ab6496f3cdf532bf.json)
- [既有诊断输入EX017-B2-TIME-P23](../../../assets/deliveries/CANDIDATES/18/evidence/a2962bda7a7afd0c911e8a2b0215603e1724898662bd8fb536f04100efb0785c.json)
- [既有诊断输入EX017-B2-TIME-P24](../../../assets/deliveries/CANDIDATES/18/evidence/fe892a0d8302f63773b6a3fdb074e5623c548c2d1820901a1478df7144e424a2.json)
- [既有诊断输入EX017-B2-TIME-P25](../../../assets/deliveries/CANDIDATES/18/evidence/885a7d3fbbed6a17b79b24c22878525e6e572d251aeb445f71ed352d570c347f.json)
- [既有诊断输入EX017-B2-TIME-P26](../../../assets/deliveries/CANDIDATES/18/evidence/303e5eedf823c2056a4fa3c74686412cb3a213efb38b974652d7c131aaec060f.json)
- [既有诊断输入EX017-B2-TIME-P27](../../../assets/deliveries/CANDIDATES/18/evidence/941281e6a94eb6a9ca04efd11274739a3a1cbf6d6777de55fd0ceba0aca19b65.json)
- [既有诊断输入EX017-B2-TIME-P28](../../../assets/deliveries/CANDIDATES/18/evidence/e96c1a9b402375baea7dd9d3aefcec6121cbb4249a130dca548cf9e79dfbaac8.json)
- [既有诊断输入EX017-B2-TIME-P29](../../../assets/deliveries/CANDIDATES/18/evidence/c745ef1fdb86dfd5cbdf209245914a7135d439e1f1342a88c3c499ac45d599e3.json)
- [既有诊断输入EX017-B2-TIME-P30](../../../assets/deliveries/CANDIDATES/18/evidence/a1e2e65bcc723335d54de764ca784f0509fb1f559bb29a251c9a28b165560989.json)
- [既有诊断输入EX017-B2-TIME-P31](../../../assets/deliveries/CANDIDATES/18/evidence/9ff70003b0047eae92e941e466181d57e6cfb61003240ad342330c9871e73751.json)
- [既有诊断输入EX018-N0](../../../assets/deliveries/CANDIDATES/18/evidence/e8a20a199cc89c4e8b1ba744c41a997e3c35e4bc73e7ea2cc2974b6758f0dbd3.json)
- [既有诊断输入EX018-N1](../../../assets/deliveries/CANDIDATES/18/evidence/f3fce816682ad0bd98f5d8bf041963fa0aa0b896bb476af77e73a8588faa3b27.json)
- [既有诊断输入EX018-B0-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX019-N0](../../../assets/deliveries/CANDIDATES/18/evidence/6cfbd034e871a0cc781cd7743420b75e77b77346442aa36c4e4f4d7f3f24b64e.json)
- [既有诊断输入EX019-N1](../../../assets/deliveries/CANDIDATES/18/evidence/f7ec0acd5a704707e74b6390e79d0a4db4b04eb21c77a996f4ec688ac62141ac.json)
- [既有诊断输入EX019-N2](../../../assets/deliveries/CANDIDATES/18/evidence/d1a7b5caf36341bd756300e3fbc1aac768d400ca915e6adee1706f0a6327f9bd.json)
- [既有诊断输入EX019-N3](../../../assets/deliveries/CANDIDATES/18/evidence/1f90baef579444baa80d93f7a13a8f1439a34eede9589c617ef5291201b9c438.json)
- [既有诊断输入EX019-B0-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX019-B2-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [既有诊断输入EX020-N0](../../../assets/deliveries/CANDIDATES/18/evidence/3452c973d4663a0291fe089fc1abda7665aac55eea1675be95c80c0e7c2b5415.json)
- [既有诊断输入EX020-N1](../../../assets/deliveries/CANDIDATES/18/evidence/90a2b7c56f9926282e14996cbdbeaf33dcf505bc82a8201c9e5b58d6357d79f2.json)
- [既有诊断输入EX020-N2](../../../assets/deliveries/CANDIDATES/18/evidence/7be615850fb5672f0d9920e1033e425a0d99affc0d3e3d03c206b93885d3cda7.json)
- [既有诊断输入EX020-N3](../../../assets/deliveries/CANDIDATES/18/evidence/d0673ee41a4920acb7a0e3fda9e527fbed88e081c80f3c8ac4db2b7359005552.json)
- [既有诊断输入EX020-B0-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX020-B2-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [既有诊断输入EX021-N0](../../../assets/deliveries/CANDIDATES/18/evidence/70dad506ecfaa19933bf1f144fe63111a7d306c02ba4b778eec6db75150f1ead.json)
- [既有诊断输入EX021-N1](../../../assets/deliveries/CANDIDATES/18/evidence/f0b4b0ced379e7e3d94ce8dc9cce7b225f169caf0ec6394b15f808cbfcdeba76.json)
- [既有诊断输入EX021-N2](../../../assets/deliveries/CANDIDATES/18/evidence/8a9c345f180eb07d7942337c4545d28e4bc35a27b32839a0300a562bd7ddf2f6.json)
- [既有诊断输入EX021-N3](../../../assets/deliveries/CANDIDATES/18/evidence/1890743bb34f46d910e1a28044729ed4a0a747ee0e87a93cbc339f469e0b8397.json)
- [既有诊断输入EX021-B0-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX021-B2-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [既有诊断输入EX016-N0](../../../assets/deliveries/CANDIDATES/18/evidence/f4002f9175794a6a55f113f7d19fdd5091e4c95c3b891d17403cd94208c47ee9.json)
- [既有诊断输入EX016-N1](../../../assets/deliveries/CANDIDATES/18/evidence/662e3117819f6da8d4e05d2cb31ec425ae0b4d971352027654046df23b598858.json)
- [既有诊断输入EX016-N2](../../../assets/deliveries/CANDIDATES/18/evidence/a4832fc9993cb0f9cad4cb0ee5e99de2ff16bac60da3b9e2ad875112a1f82800.json)
- [既有诊断输入EX016-N3](../../../assets/deliveries/CANDIDATES/18/evidence/5897f55ca8d285e85afdf651e61a95a39c531e2abc792f31cb7eb89ed31f6ad8.json)
- [既有诊断输入EX016-N4](../../../assets/deliveries/CANDIDATES/18/evidence/7d1146c3e67717f86c82b3d66eb20904c45a9a08c391c59bcf67afe5f6982dc9.json)
- [既有诊断输入EX016-N5](../../../assets/deliveries/CANDIDATES/18/evidence/c45d3e303e3193e9a98d7afef58d8410f51463b564603320f2e6fc6a8cdc5087.json)
- [既有诊断输入EX016-N6](../../../assets/deliveries/CANDIDATES/18/evidence/5a214356dff49f354b20f08dd563d69cec641e7fedf20c9cbfdb7462f93f2e99.json)
- [既有诊断输入EX016-N7](../../../assets/deliveries/CANDIDATES/18/evidence/3ea029622e073d6980bafc30990687334d6d4b0568efc4c7174b3cc849b83d46.json)
- [既有诊断输入EX016-B0-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [既有诊断输入EX016-B1-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [既有诊断输入EX016-B2-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [既有诊断输入EX016-B3-TIME](../../../assets/deliveries/CANDIDATES/18/evidence/1fecef52e37e7073dcf4208b5895c71146c5e775f3fc41fb88e60e59ed090361.json)
- [final-authorization](../../../assets/deliveries/CANDIDATES/18/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [final-geometry](../../../assets/deliveries/CANDIDATES/18/evidence/b3597098f9c2a18bcb66c29597698a429f99bfe599ffe36d734d8a798b954b9f.json)
- [final-geometry-reference](../../../assets/deliveries/CANDIDATES/18/evidence/e29df1fb2e66c3c3130cecc146f0c6de751316f685aeb16e31811c03bc311a04.json)
- [final-parameter-plans](../../../assets/deliveries/CANDIDATES/18/evidence/c0b628f109388599f613a2c2557594ee093e692d638c7aadad4b0b2feb118c53.json)
- [final-plan](../../../assets/deliveries/CANDIDATES/18/evidence/fe88bcc48a2df4741f3b7d021b9a2f4c68828178c70e3ebe0ebe89dd9a5afc9f.json)
- [final-plan-references](../../../assets/deliveries/CANDIDATES/18/evidence/a2f9f13a3f340ed4a740503677f5ac60bd5cf8c7d1cc37e6b131072940bb5a0c.json)
- [final-account-references](../../../assets/deliveries/CANDIDATES/18/evidence/31dcb8ce3b274ea24e22ffa5fa983b2f850688f6e90ecc22cafd272d72fbb82b.json)
- [final-analysis](../../../assets/deliveries/CANDIDATES/18/evidence/c27e40f36664a4f693e18f7cfe92d46172b314313bc47be1c59b5b70f8624288.json)
- [final-conclusion](../../../assets/deliveries/CANDIDATES/18/evidence/e516799885b5c0abc6fa787cd4ab05379f1b76fc394e1485b77f877a68445fb1.json)
- [final-mandate-validation](../../../assets/deliveries/CANDIDATES/18/evidence/f0682e41798c61bd113530c63b6b093454cde040b93768335ff11fab37012d40.json)
- [final-matrix](../../../assets/deliveries/CANDIDATES/18/evidence/89c6c88b359dd6de9ba7faf1d9633124eb26a7024f9af8f007ba8540b187743c.json)
- [final-parameter-analysis](../../../assets/deliveries/CANDIDATES/18/evidence/7c93de697c6772cc1b0f44c4bc90ac71189d655aa5078449ac7bc0d935fded55.json)
- [final-precheck](../../../assets/deliveries/CANDIDATES/18/evidence/e2b1e7a6ad88dd4394e8f2de5e96e11b93385fe144f302335d83704cb2c3b502.json)
- [final-previous-diagnosis-binding](../../../assets/deliveries/CANDIDATES/18/evidence/30db20533fc7f2293eed35a382f8f32d4967bb9440e1a18466492df880e3f807.json)
- [final-previous-parameter-counterevidence](../../../assets/deliveries/CANDIDATES/18/evidence/3b58117751126b9899ba753c3d7a3b72796b9bcb66df06b4cb06aec6f49f3066.json)
- [final-registration](../../../assets/deliveries/CANDIDATES/18/evidence/60d02b34818897fbd7e434ed45732da7f9af70df30a69763c18539f4c344da62.json)
- [final-reproduction](../../../assets/deliveries/CANDIDATES/18/evidence/48fb0d4cb27ece317c6c57f52bc5a85f5f99ccde4e30defc9cb45c508a84a04b.json)
- [final-synthetic-check](../../../assets/deliveries/CANDIDATES/18/evidence/17952402cc97a85206c7f2487541540bd4be834a41b5d31bf2efa5ddc309a6ab.json)
- [既有年度描述归因](../../../assets/deliveries/CANDIDATES/18/evidence/26dad0baf35054808dca919a74d7537f2858de04f21b303c432c7b8c13a53135.json)
- [EX017完整参数反证](../../../assets/deliveries/CANDIDATES/18/evidence/b85e3eaaf2f5835b3ce82143f80c07a3d3f1452bc05f477de96ec69592e3801c.json)
