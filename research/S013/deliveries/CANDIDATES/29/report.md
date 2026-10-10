# S013：原策略退出与重新入场的连锁诊断

RSCH阶段三。用户已授权自主完成参数敏感性研究，无需逐轮评审。本轮只复用33个既有完整账户，新增账户、候选、参数搜索和生产变更均为0。总目标尚未达成；COMPLETE仅表示这份诊断交付完成。

## 为什么调整研究方向

C2132原中心满足四项经济要求，但原完整13维域、5%联合扰动32点的收益Q10仅5.8974%、回撤Q90达30.5044%。EX031/032波动时钟及半单位计数修正都未保住经济要求，停止继续调整时钟偏移。本轮检查退出日期是否通过重新入场和持仓年龄清零，放大后续路径差异，并保留“主要是入场规则直接差异”的竞争解释。

原生信号状态定义为空仓，或持仓路线与信号持仓年龄；原stop/trailing为null、cooldown为0、确认适用于所有入场，所以锚价、峰值、上次退出原因在此固定合同不影响未来目标动作。不同参数和滚动特征仍然存在，状态重同步不意味着以后交易相同，更不意味着现金/持仓数量相同。

最大连续不同状态段从共同前状态开始，到双方状态再次相同结束。双方目标仓位同为1仍可能路线/年龄不同；双方同日入场但路线不同也算状态分歧。逐日原规则重算精确复现原生状态、原因、目标与确认门判定，真实确认score和range特征来自原生账户，未宣称全特征从OHLC独立重建。

## 全部路径的观察结果

32个点共1793段状态分歧，451段包含TIME起始原因（25.15%）。平均每点状态不同365.6875日，目标仓位不同190.6250日；最长状态分歧49个交易日。不同点共享数据与对照，这些不是独立统计样本，也不代表参数单独因果。

|分歧起点的原策略→扰动点动作|段数|
|---|---:|
|flat->entry|487|
|entry->flat|450|
|hold->time|239|
|time->hold|212|
|regime->hold|192|
|hold->regime|128|
|entry->entry|52|
|entry->confirmation_rejected|19|
|hold->range|11|
|confirmation_rejected->entry|2|
|range->hold|1|

|点序号|状态分歧段|最长段|段长中位数|TIME起点段|目标不同日|
|---|---:|---:|---:|---:|---:|
|0|65|41|5|18|243|
|1|71|37|4|21|250|
|2|59|35|4|5|212|
|3|53|38|5|6|216|
|4|62|37|4|26|174|
|5|55|38|4|0|191|
|6|58|30|3|30|183|
|7|52|38|5|6|207|
|8|45|30|4|14|167|
|9|58|30|3|35|171|
|10|26|34|4|0|104|
|11|51|49|5|30|206|
|12|65|27|4|31|232|
|13|57|45|6|11|248|
|14|35|34|3|0|122|
|15|61|29|4|6|188|
|16|75|35|4|20|250|
|17|57|42|5|10|200|
|18|47|45|4|7|190|
|19|60|29|4|19|177|
|20|58|35|4|7|185|
|21|64|31|3|10|186|
|22|46|42|4|0|150|
|23|55|44|5|12|191|
|24|60|27|5|12|208|
|25|50|31|3|27|145|
|26|56|47|3.5|10|199|
|27|54|40|4|20|179|
|28|61|27|4|21|189|
|29|53|27|4|0|174|
|30|58|30|2|11|163|
|31|66|26|4|26|200|

## 单步：当前规则与继承状态的区别

每个真实时点检查p规则/特征与q规则/特征各自应用于双方已有状态，共四组合。两原组合须精确复现原生记录，另两组合只计算当日一步，不传播新的状态或账户。双方实际目标不同而固定双方任一状态换规则都不改变目标，称继承状态差异；固定任一规则换状态都不改变目标，称当前规则/特征差异；其余称混合。原参数与其滚动特征一起变化，不能称单个H的因果分解。SAME_TARGET也不等于SAME_STATE。

|目标不同日的单步类别|全部32点日数|占目标不同日|
|---|---:|---:|
|INHERITED_STATE_ONLY|2778|45.54%|
|CURRENT_FEATURE_RULE_ONLY|2291|37.56%|
|MIXED|1031|16.90%|

## 持续入场机会与重新买回

原中心bear有38次TIME退出，其中27次在rawbear和原range入场机会都未刷新前再次入场，22次发生在下一信号日。扰动点平均此类再次入场28.5312次；平均9.4062次退出和再次入场同处至少8日的状态分歧段。8日仅是原bull H8的描述尺度，不作为额外经济门或剔除条件。原ACF或确认可能中间不通过，不能称完整买入机会持续通过。

原中心的退出—入场统计：

|路线|退出原因|退出次数|下一信号日同路线入场|
|---|---|---:|---:|
|bull|time|28|13|
|bull|range|1|0|
|bull|regime|27|7|
|bear|time|38|22|
|bear|range|1|0|
|bear|regime|17|3|

## 实际账户收益核对

实际每日净值的对数收益差，按当日收盘真实数量是否大于0分组，各组相加严格等于年度对数收益差。该标签包含当日卖出前的价格变动、成交和费用；双方收盘空仓也可能当日有盈亏。下表给出真实连续账户年度收益，不把分组描述或旧交易利润当作删项后收益。

|自然年|原中心收益|32点平均收益|
|---|---:|---:|
|2020|16.7355%|15.4160%|
|2021|9.9101%|6.9123%|
|2022|12.1687%|-8.3142%|
|2023|0.2841%|-4.0173%|
|2024|64.9989%|45.2930%|
|2025|11.0774%|8.5194%|
|2026|-0.0384%|-3.8627%|

## 判断、验证与下一步

此前18/32最早目标分歧涉及TIME，仅覆盖每点最早一次。全部事件显示，入场差异同样重要，不能把TIME解释为全局唯一根因。状态差异可能持续，也会在双方空仓时消失；单步分类和持续机会统计支持检验相互作用，尚未证明任何新机制能保住收益、回撤、频率及亏损年盈利。

下一步最小可证伪方向：仅bear因TIME退出且仍位于原rawbear与range入场机会内时，要求机会刷新后再买。原H、ACF、确认、bull规则及退出优先级保留，新增的是入场记忆，无新增天数或阈值。最强反证是重复买回可能本来有利，阻断会漏反弹并让交易数低于110；原中心仅112笔，频率余量很小。是否改善只能由后续完整账户及原域参数尾部对照证明，本轮未运行该机制。

33账户逐个验证正式证据hash/schema、整个原生请求/结果精确等于缓存、候选身份、参数点序号及源身份；现金、数量、逐日净损益、年末尾仓和年度回报核对。未新增数据、依赖、平台接口、阶段四排名/交接、冻结、PTE或生产操作。原四项经济目标与13维完整参数域保持，诊断不新增硬门。未做仓库全量回归，FULL仅核验已声明证据完整性。

补充方法v1因2019-12-31信号对应2020-01-02有效执行、年度索引未覆盖而停止；没有新账户运行或结果交付。原方法/源码/失败记录保留，v2按有效执行日归年。同时修正“退出在分歧段内”不能替代“退出和再次入场都在同一段内”的口径。

## 正式证据引用

- [center](../../../assets/deliveries/CANDIDATES/29/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-TIME-P00](../../../assets/deliveries/CANDIDATES/29/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01](../../../assets/deliveries/CANDIDATES/29/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02](../../../assets/deliveries/CANDIDATES/29/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03](../../../assets/deliveries/CANDIDATES/29/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04](../../../assets/deliveries/CANDIDATES/29/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05](../../../assets/deliveries/CANDIDATES/29/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06](../../../assets/deliveries/CANDIDATES/29/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07](../../../assets/deliveries/CANDIDATES/29/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08](../../../assets/deliveries/CANDIDATES/29/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09](../../../assets/deliveries/CANDIDATES/29/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10](../../../assets/deliveries/CANDIDATES/29/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11](../../../assets/deliveries/CANDIDATES/29/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12](../../../assets/deliveries/CANDIDATES/29/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13](../../../assets/deliveries/CANDIDATES/29/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14](../../../assets/deliveries/CANDIDATES/29/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15](../../../assets/deliveries/CANDIDATES/29/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16](../../../assets/deliveries/CANDIDATES/29/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17](../../../assets/deliveries/CANDIDATES/29/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18](../../../assets/deliveries/CANDIDATES/29/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19](../../../assets/deliveries/CANDIDATES/29/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20](../../../assets/deliveries/CANDIDATES/29/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21](../../../assets/deliveries/CANDIDATES/29/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22](../../../assets/deliveries/CANDIDATES/29/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23](../../../assets/deliveries/CANDIDATES/29/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24](../../../assets/deliveries/CANDIDATES/29/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25](../../../assets/deliveries/CANDIDATES/29/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26](../../../assets/deliveries/CANDIDATES/29/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27](../../../assets/deliveries/CANDIDATES/29/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28](../../../assets/deliveries/CANDIDATES/29/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29](../../../assets/deliveries/CANDIDATES/29/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30](../../../assets/deliveries/CANDIDATES/29/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31](../../../assets/deliveries/CANDIDATES/29/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [primary-method](../../../assets/deliveries/CANDIDATES/29/evidence/a92ab4016b72efbc977ec7e64a6131615127cf1e78fe6adcea632decd5cb7ff9.json)
- [primary-diagnosis](../../../assets/deliveries/CANDIDATES/29/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [failed-method-v1](../../../assets/deliveries/CANDIDATES/29/evidence/20b40ce2d5b352703675eba4850ea984ff3b8e7551e6baf87c5d616fdf56cc59.json)
- [corrected-method-v2](../../../assets/deliveries/CANDIDATES/29/evidence/025681b0cbec40b58c7eccdbbb6295b70ab787191ecfca7303d8ca51574eab4a.json)
- [corrected-refresh-diagnosis](../../../assets/deliveries/CANDIDATES/29/evidence/9f02897390a12003981b948a84fbf53b3bf2f84bbd3f8b78a5d4af582c1f6016.json)
- [technical-failure-v1](../../../assets/deliveries/CANDIDATES/29/evidence/ab4a939e850ecba83fa3a2b7a0aefb61db0058296fddecd5d6c3dd2371a914cb.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/29/evidence/8a46d62fb94faca899848204678ad2d478878646555709fdb8fffde79c83c3c0.json)
- [conclusion](../../../assets/deliveries/CANDIDATES/29/evidence/fc4fab90a2d25f8eeb0cd880fbfc4a8994de97d50225335bc11934502b47f03e.json)
