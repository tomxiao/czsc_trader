# S013：过滤平滑、确认分退出与参数敏感性结论

本轮自主机制研究及完整参数诊断已完成。原买入确认提高中心收益，但没有保护下跌路线的参数变化；删规则、价格条件退出、平滑过滤输入或等待确认分转弱退出均未形成满足原四门的改善。唯一新达标配置为C7408，到期且确认分仍达标才卖；其中心收益和回撤与C2132相同，必须依靠完整扰动结果判断是否有改进。

身份RSCH、阶段三。直接用户授权“授权你可以自主完成目标，无需评审”。沿用S013已有510500.SH资产及预热、MANDATE/6、2020-01-02至2026-09-30、1636交易日、100万元、HFQ研究单位整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策T+1执行。原四门保持，无新的经济否决或PTE资源选择。

## 已有证据与最强反证

C2132历史统一5%总距离32点显示年化退化9.5670、回撤恶化11.3476个百分点；这两个分位数可能来自不同配置，不能相加作为同一账户的损失。该证据支持参数脆弱性，不能证明整个参数平面的尖峰形状。

EX012完整账户对照中，原确认将中心年化从13.9456%提升到16.1572%，但三个背景中的下跌买入机会都没有被原确认直接拒绝，直接拒绝全部发生在上涨路线。门槛0.1→0.045时，开关确认两侧的回撤恶化都约10.5个百分点；期限4→3日时，两侧年化损失都约4.39个百分点。这是“买入确认已修复下跌参数脆弱性”的最强反证。不同资金继承可带来间接作用，不能把零直接拒绝说成零账户影响。

EX013五个删项新配置均失败。去掉过滤使回撤约翻倍；去掉期限减少闭合交易。放松门槛且不定时退出的年化17.6051%、2023盈利1.5725%，但只有89笔交易，不能放宽至少110笔的频率要求。两条规则有路径交互，简单删掉不足以改善。

EX014九个新价格条件及联合背景配置均失败。最好的原背景转弱条件退出年化17.7909%、回撤13.1720%，但2023收益-2.1142%；较好的两个总指标没有满足原全部目标。相反价格方向和完整2x2背景一起保留，没有只报告最好配置。

## 本轮最小机制与全部账户

四背景B0=(自相关门槛0.1、期限4日)，B1=(0.045、4日)，B2=(0.1、3日)，B3=(0.045、3日)。TIME为原规则；SMOOTH把原20日涨跌自相关估计再用同长度20日均值平滑，下跌门槛保持，未新增可调长度；LOW_SCORE到期且原确认分低于原门槛才卖，HIGH_SCORE采用相反条件。相等只属于HIGH_SCORE。上涨原规则、区间/状态退出及优先级保持。

现有FROZEN_RULE执行接口只允许空仓/整笔持仓，未实现连续仓位或改执行合同。平滑输入仍有硬门槛，不能声称消除了所有突变。三个机制×四背景事前固定，Optuna队列管理、8进程、每进程1原生线程、请求workers=1、seed13。

|背景|机制|身份|净年化|全窗回撤|闭合交易|2022收益|2023收益|四门|
|---|---|---|---:|---:|---:|---:|---:|---|
|B0|TIME|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|B1|TIME|C7005|15.8174%|24.6200%|125|20.6159%|-1.9705%|annual_drawdown、negative_buyhold_year_profit|
|B2|TIME|C7009|11.7652%|17.4850%|121|5.9394%|-1.9690%|negative_buyhold_year_profit|
|B3|TIME|C7306|8.4482%|26.7916%|139|-1.7731%|-4.3671%|return、annual_drawdown、negative_buyhold_year_profit|
|B0|SMOOTH|C7400|9.3504%|25.2791%|90|4.8148%|-7.6589%|return、frequency、negative_buyhold_year_profit|
|B1|SMOOTH|C7401|9.1982%|21.2384%|104|-7.3976%|-9.3739%|return、frequency、negative_buyhold_year_profit|
|B2|SMOOTH|C7402|8.9540%|19.2572%|95|2.9491%|-7.2416%|return、frequency、negative_buyhold_year_profit|
|B3|SMOOTH|C7403|7.2213%|24.7800%|111|-5.9686%|-9.1653%|return、negative_buyhold_year_profit|
|B0|LOW_SCORE|C7404|14.5846%|22.6326%|87|10.0167%|-1.0467%|frequency、negative_buyhold_year_profit|
|B1|LOW_SCORE|C7405|15.1559%|22.2138%|92|9.8890%|-1.2827%|frequency、negative_buyhold_year_profit|
|B2|LOW_SCORE|C7406|14.5846%|22.6326%|87|10.0167%|-1.0467%|frequency、negative_buyhold_year_profit|
|B3|LOW_SCORE|C7407|15.2156%|21.9539%|92|9.8890%|-0.9557%|frequency、negative_buyhold_year_profit|
|B0|HIGH_SCORE|C7408|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|B1|HIGH_SCORE|C7409|15.6488%|24.3758%|125|20.6166%|-1.6528%|annual_drawdown、negative_buyhold_year_profit|
|B2|HIGH_SCORE|C7410|11.7652%|17.4850%|121|5.9394%|-1.9690%|negative_buyhold_year_profit|
|B3|HIGH_SCORE|C7411|8.3709%|27.1260%|139|-1.7731%|-4.8061%|return、annual_drawdown、negative_buyhold_year_profit|

12新业务配置、13次新完整评价（含1次串行/spawn重复）；4历史控制完整序列化精确核对后复用，16个不同内容身份。只有N8通过原四门并登记为C7408，登记不等于推荐、阶段五选择或PTE批准。N8与C2132仅排除随身份生成的decision/order/fill/cycle IDs后，双方五类账本的全部其余信号与经济字段精确相同；原生身份及账本不改写。

原四门为年化至少正收益基准1.5倍、各自然年回撤严格小于基准、每60交易日平均至少4笔闭合交易、基准亏损年2022/2023策略收益严格为正。全窗回撤只作诊断。平滑配置都达不到收益门，等待确认分弱化的配置都低于交易频率要求。相反方向仍复制原背景脆弱性。

## 完整参数诊断

查看EX015结果前已发布共同域：13个活跃数值坐标，包括两路线的窗口/入场/退出/期限、下跌自相关门槛、状态窗口/门槛、确认窗口/门槛。路线源合法域、状态/确认源合法域，以及S013既有ACF搜索域[-0.60,0.50]逐项引用；结构、类别、null参数、冷却0和固定执行合同单列。

两中心各32点，域宽标准化后总欧氏距离5%，seed13、PCG64、整数HALF_EVEN、LINEAR Q10收益及Q90回撤；原中心与全部新四门达标机制完整检验。所有规定点保留，不按结果换点、不只保留达标点、不改变费用或时期、不增加10%/20%档。

原历史统一扰动计划的域字节由S007拥有，S013快照仅保存引用/哈希。本轮没有读取邻批次；前瞻声明新共同域，并同时重做原C2132，不能用历史9.5670/11.3476直接当作本轮相同量尺的基线。两套数值不同不代表历史结果被纠正或策略自动改进。

|中心|中心年化|中心回撤|32点年化Q10|32点回撤Q90|年化退化pp|回撤恶化pp|邻点四门通过|
|---|---:|---:|---:|---:|---:|---:|---:|
|C2132|16.1572%|14.1599%|5.8974%|30.5044%|10.2598|16.3446|0/32|
|C7408|16.1572%|14.1599%|6.0199%|30.5095%|10.1373|16.3496|0/32|

C7408相对原中心：年化退化差-0.122533个百分点，回撤恶化差+0.005004个百分点。年化退化略有减轻，较差回撤略有增加，不能把局部变化解释成稳健性目标已经达成。两项退化用于诊断，不作为新增资格否决。

32个点的数值坐标逐点精确相同，其中17个点的收益/回撤/交易数/各年结果/四门摘要完全相同；新机制年化更好12点、更差3点。平均年化差+0.025483、平均回撤差-0.084539个百分点。此为政策配对描述，不是独立统计检验。

SE公共比较明确可比，逐点分位数独立用NumPy复算一致。邻点的四门通过数是诊断，未追加经济硬门；有限32点不是置信区间或未来成功概率。没有进行全部阶段四五项自检、族排名、阶段五选择、冻结或PTE。

## 验证与留存

全部新机制12配置因果前缀/未来修改不变；合成分支检查平滑均值、到期后高低分、非法机制。源码保留上涨和区间/状态退出。代表机制及每个中心代表扰动点的串行/spawn信号、双方五类账本及结果哈希精确相同。机制16账户基准账本相同，完整数量/现金/价格/费用/年度/周期/尾仓对账通过；32点逐点账户核验保留，不掩盖已知数据问题。

参数业务账户64个，实际参数评价66次（含每中心1次技术重复）；不重放两个中心。本轮合计76个新业务配置、79次实际评价，另复用4个已有控制。所有原生账户、参数计划/映射/可行性、强类型父子绑定、SE事实及结果、完整源码、输入绑定和依赖均通过公共API保存。

研究源码静态检查采用明确per-file忽略：不可变mechanism_range.py保留原复制源码中的未使用Mapping导入，仅忽略该F401样式项，其余检查通过；没有修改已发布策略身份来消除样式警告。分析脚本缓存追溯及登记类型导入的调用修正仅影响留存程序，不重放机制账户、不改变指标。未做仓库全量回归。

正式交付CANDIDATES/11与FULL校验回执独立留存；旧交付和全部负面结果不改写。数据资产、候选快照和原生账户须一起保留，Git摘要不能恢复缺失数据资产。

## 结论与下一步

本轮没有发现保留原四门且明显减轻完整参数退化的方案。继续在同一开发池微调门槛或期限，越来越容易把偶然路径当作发现；当前证据支持结束这组简单规则改写路线，保留原候选不投入PTE的判断。

下一步建议回到下跌路线的信息机制：需要能区分反弹仍有支持与反弹已经失败的信息，并在设计中同时约束持仓延长的频率代价；原确认分和单日价格方向已提供明确反证，不能未经新证据继续赋予它们保护作用。该建议是研究方向，不是已获验证的新策略；需新的可证伪信息假说及独立证据，不能放宽原目标宣布成功。

## 正式证据引用

- [N0完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/e50df0a4f5132d4a76df148575e18c8d226a293c573318fc8c1cfef381f341a5.json)
- [N1完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/81cc393d99a6af3cc9413ca32f2ef374d9da6c3cdf5dc56f847f3c664212aa3f.json)
- [N2完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/4f2ebe8dd6f1a114429c774bd4040f24fe7a76351b7b67bc5bd04438cdb24863.json)
- [N3完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/a375f5c1c44d80f87d87da8e3859fc3d23319536a3355e640820ec93c7d565c2.json)
- [N4完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/6f00f4d0a7cf23cb889a2be22e3d63b9a1dd226491221716645ee051282a847e.json)
- [N5完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/6937273b4ed0396ae4c7834472dd23831be6a40f87754d63563dec5fc913b92b.json)
- [N6完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/5b7bb8e9e5a66724da0dcacf4c5012987977a60084bcba43c2c90cdd87ddada1.json)
- [N7完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/fb1765a32219e33bfb628958fd3cdc2f838872422d8909fb5c7210c628300d3e.json)
- [N8完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/6810460b64b9ee5a30aed48f969000335a1627e3874b7f8e4c5d91bc48a6b591.json)
- [N9完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/507006ef505e0c3057c44ba0a557372413d2eac7c11cdfafc7469daf572a2686.json)
- [N10完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/6e967cff7223fbac33fc60598e53af8fbd84763bd06a26e4b477c2fd173fd102.json)
- [N11完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/b374c8c5b0e7f87508cf137f3c03ff9be088af34c854a65b2e83347f9cf9857e.json)
- [B0-TIME完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B1-TIME完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [B2-TIME完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [B3-TIME完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/1fecef52e37e7073dcf4208b5895c71146c5e775f3fc41fb88e60e59ed090361.json)
- [B0-TIME-P00完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [N8-P00完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/03571480a68a616cd5396fc6d401220757ccdbd044a9b584ff33faa7e43256b1.json)
- [N8-P01完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/ce784b17a9f8205d11cf9b042ff16cc14d6064826be756254d0ca7495e0c73e9.json)
- [N8-P02完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/c0a455bfd71dca6f65a01d9c4a1f30c463100a05c5e296558d6a205be7b9bb3c.json)
- [N8-P03完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/8447ad9bd4b2d3fb04c77e8a6169396b33abd2c4927e98f6a24b6a73cb1f2572.json)
- [N8-P04完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/1d56fce2b90db2af34cbb9f0094e25d740c55304cdc5d8e40a6eee71fa8384a7.json)
- [N8-P05完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/569b4d33bdd0313ef804dc6f05b76183d1eb612f44744124c6c1ff8276b09468.json)
- [N8-P06完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/92177316c263c1a6a81a5163808bc8975adbb797bd1da9d7d24b92b4e8b731a7.json)
- [N8-P07完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/90716ae57f452dd5baecac2b50bc5f7e70c64051c62697d9c5c8532c01ae8f46.json)
- [N8-P08完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/7686bdf5076b990237126d2a35e74491ac405cc0ae9e6da8e058b2ab763ab8a8.json)
- [N8-P09完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/777eaf9b4927ec1a390e51f5650b7cdb351333b641472748b1334d7dc47dc0dd.json)
- [N8-P10完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/7b34575a5af3d0d8776582ecc05f97acd2e44377eebc3e1f6b375bc164d44381.json)
- [N8-P11完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/6d7d4de195479df634c726acfc725cc2ebe4bce42895dd1c2100ead0cad1d1ea.json)
- [N8-P12完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/a995cc27b08ccf340f08998e0f28083d02ca2153503328893938c241f1897474.json)
- [N8-P13完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/7d19b6b9c5f80b34be89b405b04d41416bd349bfe4440c997da812f2faaf135c.json)
- [N8-P14完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/d138d5fa48707489bd6c8b3f6191caedd26e3484b51a02af44eaaac7599e50b8.json)
- [N8-P15完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/a561deaa3a129501dee0351ff46e535ade90f84f9da3bc6d699dc37c0b266588.json)
- [N8-P16完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/9367c023616684b385526dc2890608b96199d764fd7528fc4f78aa902de3a7ca.json)
- [N8-P17完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/a529ed3172b110215c6840045cd5ae49a26c5d20212e80d27a5f7cd7ea691adf.json)
- [N8-P18完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/d24abab7755f6f6dc3e83789f430fab4095c3aecd86c711d8a6a15b5f578f2ff.json)
- [N8-P19完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/fb7ab4f5c42cc22a02badf706b792ccb6c7948c1e563a9a6f14d2437609a4963.json)
- [N8-P20完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/72f63bffe90852ae501573e69f0e17d436eadbce8be313fc8b77573ef00fe31e.json)
- [N8-P21完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/5e5b27cb5f85a5e14e526ffd6ac1d35c7de3a042c3443362fbd367d682822d32.json)
- [N8-P22完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/fc7ea90b4925fcbe1efd2c632c6a1603d49b48df0feca845c1a5eebab7be1787.json)
- [N8-P23完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/787ae51ef463005ca033db01a769059c5313c23bf6bf8c28e4e7a578fe015ed5.json)
- [N8-P24完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/299ec56048bf1d7e989eb9f62560fe499e8f1e0e78e7d2072331caf203e112a8.json)
- [N8-P25完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/e016caafd734d51c9d64df2180f8caeb4e587361a31154cf4c08bfe92536cb86.json)
- [N8-P26完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/daaba1bd5291638645630889e2a290e32287f6f26e25f66aec32fd38d42eea15.json)
- [N8-P27完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/f44fe2ea4c5eedfde3e6b7e64200535ba4597cc4e50bf1231527377d2e50651a.json)
- [N8-P28完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/40310c35b259719891e96831c9432c4fc0be7c5b41a678fecb49fa1baeb6ddf4.json)
- [N8-P29完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/8c69faa83e1dbc492fb542084f544ae087e8543c1895a0b3544b593f61e112a8.json)
- [N8-P30完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/c22427d5db1e373153c45b8cc2afc7e46a79cb314848d04357142efd0c7d450d.json)
- [N8-P31完整账户](../../../assets/deliveries/CANDIDATES/11/evidence/5087b30f7abfba3714c1d8735a5707ff8bcd9e6163e608d2889d990466d256d8.json)
- [final-information-authorization](../../../assets/deliveries/CANDIDATES/11/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [final-information-geometry](../../../assets/deliveries/CANDIDATES/11/evidence/251d21f02017fd245bc4325f9ab64d50a110ef58c63a826e86bb857253eec9ae.json)
- [final-information-geometry-reference](../../../assets/deliveries/CANDIDATES/11/evidence/50a44b3877b34a90ad1e193e183f2c25423da6f2f992b88e5419334f7180779f.json)
- [final-information-parameter-analysis-references](../../../assets/deliveries/CANDIDATES/11/evidence/64a973ea0694e9ec831af2af3d7d3dfa907553801f28f9576a4fea345909fc60.json)
- [final-information-parameter-plans](../../../assets/deliveries/CANDIDATES/11/evidence/38dcb384bd1757184b0ab958f9a37c07214021198ea219bc0f38319b786ea315.json)
- [final-information-plan](../../../assets/deliveries/CANDIDATES/11/evidence/ea5fa48493fdfd119f14ea84d6fb92dcc6e0b96a34df2074ef721ff4fb5f2753.json)
- [final-information-plan-references](../../../assets/deliveries/CANDIDATES/11/evidence/885ba4d09bf25931847da020c89cafd5c6913ebfcdabd78aeb9612afe4b5d1df.json)
- [final-information-mandate-validation](../../../assets/deliveries/CANDIDATES/11/evidence/f0682e41798c61bd113530c63b6b093454cde040b93768335ff11fab37012d40.json)
- [final-information-synthetic-check](../../../assets/deliveries/CANDIDATES/11/evidence/c9ddefd5e2a5d1d84775043783b4ebfc2ef88b3fd99bd125804c2559337282ae.json)
- [final-information-precheck](../../../assets/deliveries/CANDIDATES/11/evidence/6c7f7f75b7356c82c12ed70eeb410e3419361b16aac4d38c1d95119e25c19000.json)
- [final-information-matrix](../../../assets/deliveries/CANDIDATES/11/evidence/3c7f4db39f177041fd3f55fa86705c42d2a37242a23fb88e733b90d6edb7f87b.json)
- [final-information-analysis](../../../assets/deliveries/CANDIDATES/11/evidence/b395d61c5d4b003301fe026a63564e69cebcb0b846c1e6b827f5bae99cbe2a90.json)
- [final-information-account-references](../../../assets/deliveries/CANDIDATES/11/evidence/768ede2b64932a0ff1ba7b43714174448f53106fbe3aec8def8eb158728fb94f.json)
- [final-information-registration](../../../assets/deliveries/CANDIDATES/11/evidence/a36c9217377207f0ea7f401bfd51cd7da7448f3c959d79fa0dd50832d4570456.json)
- [final-information-center-equivalence](../../../assets/deliveries/CANDIDATES/11/evidence/67515d068fca1d48d8521bc1e76d8a865d2f7352c84cefe285d6809448a4987e.json)
- [final-information-parameter-precheck](../../../assets/deliveries/CANDIDATES/11/evidence/d46b8bccef06b33b3fe5c0a1b7b440bb188f3bdb6c487b5451f69ab842e9f922.json)
- [final-information-parameter-matrix](../../../assets/deliveries/CANDIDATES/11/evidence/2acd380ffd948ff990fffe54ca9f72d47476157849c3ead76f54e283c1d47e78.json)
- [final-information-parameter-analysis](../../../assets/deliveries/CANDIDATES/11/evidence/ad07b35eb3df6065900055feb6cdf3c7a56f72e336e586464cab819fda1f3ad6.json)
- [final-information-parameter-pairs](../../../assets/deliveries/CANDIDATES/11/evidence/ae895373db6a593fc8f3335f1e21b290660815c6370b5852baa87d7245a65663.json)
- [final-information-conclusion](../../../assets/deliveries/CANDIDATES/11/evidence/4e8883d22d3a67e879d09f3b21976eb41f8fa946441a090446637a2e3eddf2fc.json)
- [final-information-reproduction](../../../assets/deliveries/CANDIDATES/11/evidence/1ebf3efc6099127c0da2b8096681f85d8ac410e44384225e41a0d669edf19760.json)
