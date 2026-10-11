# 原C2132参数的当天触发与历史持仓诊断

RSCH，S013阶段三；本轮诊断完成，改善参数敏感性的总目标尚未达成。原中心与32个完整账户精确复用，另保存2个既有中心的增量反证；零新账户、零资金重放。

## 先看经济结果

原中心净年化16.1572%、全窗回撤14.1599%、112笔闭合交易，四项经济目标通过；完整13维的32个共同扰动点，较差一端年化Q10仅5.8974%、回撤Q90为30.5044%。中心达标不能说明参数邻域稳定。EX043与EX045两次改法的绝对尾部更差，未实现改善。

EX046清除跨rawbull状态的旧类别记忆，年化从10.8889%降为10.6245%，低于本次原生买入持有基准对应门槛10.8290%。因此没有展开新32点，不能声称参数敏感性改善。

三次旧门拒绝在新真实路径上均变为入场，三个新增实际闭合周期均净亏。费用减少5081.77元，最终权益仍减少30085.55元。这是完整账户事实，不是把旧交易删掉再加减收益。2023/2024全部目标、信号原因和实际成交时点/价格相同，微小年度收益差来自继承现金与整手预算。完整两次诊断假设/日账联接失败和修正源码保留，正式账户未改。

## 方法：分别只换一个参数，观察当天决定

对每个点、每一天，在原中心的既有持仓状态和扰动点的既有持仓状态上分别计算。正向只把一个中心参数换为该点值；反向只把一个点参数恢复中心值。价格、rawACF20、原退出优先级等保持，改变窗口则重算其完整依赖：区间窗口影响对应高低价位置，确认窗口影响原完整分数，市场窗口与门槛分别用原收益率单位重算。边界等号属于上涨状态。

全部13项、32点、1636信号日期、信号年2019—2026/执行年2020—2026、无执行日期均保留；每个新决定的下一信号状态只记录一次，不传到后一天。故这不是13套新账户，不能从次数推断收益贡献。观察到的历史持仓本身由之前联合13项参数变化形成。

原32点与中心实际目标仓位不同共6100点天。固定中心既有状态时，联合改变13项当天条件产生3379点天目标差异；固定各扰动既有状态时为3279点天。前后持仓状态不同仍会改变结果，两组计数不是可相加的损失来源。

|只换一个参数|中心既有状态：当天目标改变|扰动既有状态：当天目标改变|反向恢复：扰动状态目标改变|
|---|---:|---:|---:|
|bull.range_window|62|106|106|
|bull.entry|210|218|189|
|bull.exit|9|9|9|
|bull.max_hold|494|438|438|
|bear.range_window|0|0|0|
|bear.entry|24|18|25|
|bear.exit|0|0|0|
|bear.max_hold|707|689|710|
|bear.acf_min|242|221|219|
|regime_window|997|981|968|
|regime_threshold|1048|1013|957|
|confirmation.lookback|0|0|6|
|confirmation.threshold|31|31|41|

联合条件改变目标、但没有任何单项替换能独自复现该目标的点天：中心状态200，扰动状态200。各参数可能重叠、相互掩盖或抵消；不把表中数字相加，不把触发较多解释为更大收益因果。完整目标/最终原因/下一状态及所有年分组、首次分歧分别留存。

## 否决重复机制，下一步收敛对照

三个有限原动量的中位数达到门槛，等价于三个原状态至少两次为上涨；这与EX024已失败的三日多数票完全相同，故没有为改名再运行账户。EX017/30延迟上涨退出降低交易频率并出现亏损年份，不能笼统把更多等待当作改进。

下一项仅作为待检验机制：只让下跌路线持仓在连续两日原市场状态为上涨后按状态退出，上涨路线转下跌仍立即退出；原区间和持仓天数退出优先级保持。它与旧上涨退出延迟/整体多数票不同，但可能延迟亏损退出、减少交易，且可能不解决期限和过滤脆弱性。须先事前留证、完整新中心四门，再决定是否运行全部原32点；不从本轮诊断预测收益。

## 验证与边界

33个账户完整公共身份、序列化证据、参数计划/派生/点坐标、原特征和全信号状态、执行日历、现金/数量/费用/交易周期/尾仓及共同基准五类账本逐项核对。纯映射89项检查、52正反映射/恒等与104次固定状态调用通过；Ruff通过。未做仓库全量回归。

只用反复研究的S013已有开发池与预热，无新增行情、独立样本或跨批次材料。完整13个原域、同32共同坐标及四项经济目标保持；不额外要求全部32点达标，也不以诊断次数新增否决条件。技术PASS仅确认声明材料完整与计算一致，不代表经济目标达成。未推进正式阶段四、冻结、PTE、生产、合并、tag或推送。

正式数据资产与绑定仍须保留；Git源码与交付包装不是数据资产备份。

## 正式证据引用

- [center](../../../assets/deliveries/CANDIDATES/43/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [P00](../../../assets/deliveries/CANDIDATES/43/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [P01](../../../assets/deliveries/CANDIDATES/43/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [P02](../../../assets/deliveries/CANDIDATES/43/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [P03](../../../assets/deliveries/CANDIDATES/43/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [P04](../../../assets/deliveries/CANDIDATES/43/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [P05](../../../assets/deliveries/CANDIDATES/43/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [P06](../../../assets/deliveries/CANDIDATES/43/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [P07](../../../assets/deliveries/CANDIDATES/43/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [P08](../../../assets/deliveries/CANDIDATES/43/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [P09](../../../assets/deliveries/CANDIDATES/43/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [P10](../../../assets/deliveries/CANDIDATES/43/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [P11](../../../assets/deliveries/CANDIDATES/43/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [P12](../../../assets/deliveries/CANDIDATES/43/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [P13](../../../assets/deliveries/CANDIDATES/43/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [P14](../../../assets/deliveries/CANDIDATES/43/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [P15](../../../assets/deliveries/CANDIDATES/43/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [P16](../../../assets/deliveries/CANDIDATES/43/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [P17](../../../assets/deliveries/CANDIDATES/43/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [P18](../../../assets/deliveries/CANDIDATES/43/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [P19](../../../assets/deliveries/CANDIDATES/43/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [P20](../../../assets/deliveries/CANDIDATES/43/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [P21](../../../assets/deliveries/CANDIDATES/43/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [P22](../../../assets/deliveries/CANDIDATES/43/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [P23](../../../assets/deliveries/CANDIDATES/43/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [P24](../../../assets/deliveries/CANDIDATES/43/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [P25](../../../assets/deliveries/CANDIDATES/43/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [P26](../../../assets/deliveries/CANDIDATES/43/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [P27](../../../assets/deliveries/CANDIDATES/43/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [P28](../../../assets/deliveries/CANDIDATES/43/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [P29](../../../assets/deliveries/CANDIDATES/43/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [P30](../../../assets/deliveries/CANDIDATES/43/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [P31](../../../assets/deliveries/CANDIDATES/43/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [EX046-old](../../../assets/deliveries/CANDIDATES/43/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [EX046-new](../../../assets/deliveries/CANDIDATES/43/evidence/5e4c852f5dfc2246e3bc6e89d4ae3440680d4e69163f2fd0b6f2ea71d8d9e7ff.json)
- [plan](../../../assets/deliveries/CANDIDATES/43/evidence/b59cf3e26fbb0c46f632eb11a1538b30c69fc6cae084f1fec5e7ab2eb598e40e.json)
- [native-contrast](../../../assets/deliveries/CANDIDATES/43/evidence/98929006cde8d198611e05dccc04796d59b55fe71c39dd4540db4cb285d33353.json)
- [contrast-source-history](../../../assets/deliveries/CANDIDATES/43/evidence/49480f05690694bdabd8140f85a53bba77fe939be932f7feecd5a8fd4579e1c4.json)
- [complete-single-coordinate-observed-state](../../../assets/deliveries/CANDIDATES/43/evidence/9f02253e2e2183981e84dd0f33f3294c20f026b8573bca1c7a74fa1a8b6483a4.json)
- [pure-coordinate-checks](../../../assets/deliveries/CANDIDATES/43/evidence/54ef447e09d31e40fca0e44aac7a13dff2d156e531dcafd06b2844630ae9682a.json)
- [research-conclusion](../../../assets/deliveries/CANDIDATES/43/evidence/56f8dd0e56f6205d1fb692bb936e4ce945a99df9c2a9bf909e1a8e9b7b3105f4.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/43/evidence/0f4a7ff1b8bcea72148c85d2e0c71f1a77caa415bf19a86550f7825ed60792b0.json)
