# S013：确认边界与年度回撤完整路径诊断

身份RSCH，S013阶段三。用户授权自主推进目标，无需逐轮评审。本轮只精确复用34个独立已有原生账户，零新增策略评价、零新增业务配置、零候选登记；原33账户与均值居中C8701均属反复使用的开发池。本轮完成不等于改善目标达成。

## 方法与技术修订

执行前正式声明两项方法及源码哈希，保留原C2132和32个原完整13维联合扰动点、全部自然年与原生机会。逐账户完整正式序列化、候选内容/源码/依赖/参数、运行绑定、评价身份、参数派生关系及现金/数量/费用账本核对。确认分由原绑定HFQ数据独立重算自相关、量额、因果归一秩和原权重，并核对原入场/退出全状态。

初次确认检查将EvaluationIdentity与CandidateContentIdentity整对象比较而失败；共同content哈希一致。独立v2方法按各自公共字段语义核验，保留原评价的输入/协议/环境哈希，另核对内容/源码/依赖及绑定/派生。初次回撤输出在严格JSON序列化失败：2388个非有限输出位置全部为没有实际交易周期的actual_cycle_id，经济数值没有非有限值。独立v2仅将原记录中缺失周期编号以object dtype保留为null；所有其他非有限值继续拒绝。原源码、方法、失败、精确空值路径和修订方法均保留；不改变账户、年份、点集、权重、计算或经济要求。

## 原生确认机会与固定权重替代

以下是原生信号机会和当日判断，不是实际完成交易数或新策略收益。机会集合依各自既有持仓路径变化。统计按信号日期分年，首个2020执行可能对应2019信号；实际经济年仍按连续账户执行日期。三个预先固定权重：原权重(自相关0.5、成交额0.25、成交量0.25)，三个分量等权，剔除自相关后量额各0.5。替代判断保持各自原阈值，不传播持仓、订单、资金或收益。

|账户组|路线|原机会|原通过|原拒绝|等权通过|量额通过|
|---|---|---:|---:|---:|---:|---:|
|原中心|bull|79|56|23|58|54|
|原中心|bear|57|57|0|55|45|
|33账户合并描述|bull|2596|1783|813|1800|1706|
|33账户合并描述|bear|2021|2014|7|1942|1567|

32对已有路径的相同空仓策略状态中，共33900个配对日；原基础资格不同1128日，确认通过不同486日，实际当日入场目标不同958日。双方都符合基础资格时，确认通过不同21日。重复配对日并非独立样本；共同空仓状态不等于共同继承现金。四种跨特征/阈值判断及所有分量距离分布保存在正式数据中，不解释为单个参数因果作用。

## 全年度回撤与实际路线

年度开头继承连续账户权益，峰谷按实际净值确定。路线分组的每日对数收益相加严格等于该峰谷净值比的对数，误差低于1e-12。下表分组值是已发生路径的描述，不能解释为删除该路线后可获得的利润，也不是各路线独立最大回撤。信号模型的活动路线和实际成交库存分别保留。

|中心|年|年度回撤|基准回撤|年度回撤门|峰谷区间bull对数收益|bear对数收益|flat对数收益|
|---|---:|---:|---:|---|---:|---:|---:|
|C2132|2020|6.1272%|14.9712%|通过|-6.3229%|+0.0000%|+0.0000%|
|C2132|2021|2.7008%|9.7035%|通过|-2.1408%|-0.5972%|+0.0000%|
|C2132|2022|9.7680%|28.4105%|通过|-8.8181%|-1.4605%|+0.0000%|
|C2132|2023|5.6722%|17.2665%|通过|-4.3122%|-1.5273%|+0.0000%|
|C2132|2024|10.0213%|18.5736%|通过|+0.0000%|-10.5598%|+0.0000%|
|C2132|2025|3.5332%|13.7975%|通过|+0.0000%|-3.5972%|+0.0000%|
|C2132|2026|4.5425%|18.7646%|通过|-4.6490%|+0.0000%|+0.0000%|
|C8701|2020|6.1272%|14.9712%|通过|-6.3229%|+0.0000%|+0.0000%|
|C8701|2021|2.2401%|9.7035%|通过|+0.0000%|-2.2656%|+0.0000%|
|C8701|2022|12.9741%|28.4105%|通过|-6.1215%|-7.7749%|+0.0000%|
|C8701|2023|6.7438%|17.2665%|通过|-4.3134%|-2.6686%|+0.0000%|
|C8701|2024|19.7899%|18.5736%|未通过|+0.0000%|-22.0520%|+0.0000%|
|C8701|2025|3.5336%|13.7975%|通过|+0.0000%|-3.5975%|+0.0000%|
|C8701|2026|10.1152%|18.7646%|通过|-0.4717%|-10.1924%|+0.0000%|

全窗每个模型持仓信号日的入场锚点逆向价格位移、严格过去20日平均真实波幅单位及两次连续不高于锚点的标记全部保留。锚点是HFQ信号入场Close，实际成交价及费用独立；此处没有新增止损规则，也没有回放替代账户。

## 研究判断与下一步

事实：原中心的下跌路线57次基础买入机会全部通过确认；在33个已见账户中，下跌路线2021次机会只有7次被原确认拒绝。共同满足基础资格的配对日，确认判断不同仅21次。研究判断：现有确认分数对下跌路线的筛选很弱，继续单独调确认阈值缺少有力依据。该统计依赖已有持仓路径，不是取消确认后的收益。

事实：均值居中自相关方案C8701只差2024年度回撤这一项经济要求；该年峰谷25日中有24个实际下跌路线持仓日，其净值损失全部来自该路线。研究判断：优先验证下跌持仓风险控制，停止追加牛市入场过滤和反复入场等待机制。全年、全部年份和完整账户仍是评价对象。

固定等权和剔除自相关的当日判断改变了部分原生机会，但尚未传播订单、持仓和现金，不能据此声称改善收益或参数稳定性。等权须先核对已有同内容账户，避免重复评价。

本轮只是34个既有账户的完整路径诊断，新增评价为零。原四项经济要求、完整13维参数域及原32扰动点保持不变；总目标尚未达成。

下一轮事前声明最小下跌持仓风险退出对照：用信号入场价作为锚点，损失达到严格过去20日平均真实波幅的一个单位时退出；分别在原均值居中自相关方案和其已有BODY边界方案上运行完整账户。该固定单位是新机制选择，须披露；不按年份触发、不缩短原参数域、不改变原定时单位。仅在中心通过原四项经济要求后，才按同一完整13维、原32点方法评价绝对尾部与相对退化。所有失败账户保留，若风险退出破坏收益或负基准年份盈利，则否定此方案。

原四项经济要求和全部13数值域保持；描述统计、替代判断及路线分解均不新增经济否决门。所有已见年份和原32点保留。技术FULL仅核验声明证据完整性；没有独立样本、未来收益保证或实质参数改善证明。总目标仍未达成。未推进正式阶段四交接、冻结、PTE或生产。

## 正式证据引用

- [confirmation-center](../../../assets/deliveries/CANDIDATES/32/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [confirmation-B0-TIME-P00](../../../assets/deliveries/CANDIDATES/32/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [confirmation-B0-TIME-P01](../../../assets/deliveries/CANDIDATES/32/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [confirmation-B0-TIME-P02](../../../assets/deliveries/CANDIDATES/32/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [confirmation-B0-TIME-P03](../../../assets/deliveries/CANDIDATES/32/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [confirmation-B0-TIME-P04](../../../assets/deliveries/CANDIDATES/32/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [confirmation-B0-TIME-P05](../../../assets/deliveries/CANDIDATES/32/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [confirmation-B0-TIME-P06](../../../assets/deliveries/CANDIDATES/32/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [confirmation-B0-TIME-P07](../../../assets/deliveries/CANDIDATES/32/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [confirmation-B0-TIME-P08](../../../assets/deliveries/CANDIDATES/32/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [confirmation-B0-TIME-P09](../../../assets/deliveries/CANDIDATES/32/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [confirmation-B0-TIME-P10](../../../assets/deliveries/CANDIDATES/32/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [confirmation-B0-TIME-P11](../../../assets/deliveries/CANDIDATES/32/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [confirmation-B0-TIME-P12](../../../assets/deliveries/CANDIDATES/32/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [confirmation-B0-TIME-P13](../../../assets/deliveries/CANDIDATES/32/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [confirmation-B0-TIME-P14](../../../assets/deliveries/CANDIDATES/32/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [confirmation-B0-TIME-P15](../../../assets/deliveries/CANDIDATES/32/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [confirmation-B0-TIME-P16](../../../assets/deliveries/CANDIDATES/32/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [confirmation-B0-TIME-P17](../../../assets/deliveries/CANDIDATES/32/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [confirmation-B0-TIME-P18](../../../assets/deliveries/CANDIDATES/32/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [confirmation-B0-TIME-P19](../../../assets/deliveries/CANDIDATES/32/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [confirmation-B0-TIME-P20](../../../assets/deliveries/CANDIDATES/32/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [confirmation-B0-TIME-P21](../../../assets/deliveries/CANDIDATES/32/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [confirmation-B0-TIME-P22](../../../assets/deliveries/CANDIDATES/32/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [confirmation-B0-TIME-P23](../../../assets/deliveries/CANDIDATES/32/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [confirmation-B0-TIME-P24](../../../assets/deliveries/CANDIDATES/32/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [confirmation-B0-TIME-P25](../../../assets/deliveries/CANDIDATES/32/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [confirmation-B0-TIME-P26](../../../assets/deliveries/CANDIDATES/32/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [confirmation-B0-TIME-P27](../../../assets/deliveries/CANDIDATES/32/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [confirmation-B0-TIME-P28](../../../assets/deliveries/CANDIDATES/32/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [confirmation-B0-TIME-P29](../../../assets/deliveries/CANDIDATES/32/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [confirmation-B0-TIME-P30](../../../assets/deliveries/CANDIDATES/32/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [confirmation-B0-TIME-P31](../../../assets/deliveries/CANDIDATES/32/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [drawdown-B0-TIME](../../../assets/deliveries/CANDIDATES/32/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [drawdown-MEAN_LAGGED_ACF](../../../assets/deliveries/CANDIDATES/32/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [plan](../../../assets/deliveries/CANDIDATES/32/evidence/7dab8db4509d75de288162eccad4282781b98625298dcb35c56899322e0f7815.json)
- [confirmation-method](../../../assets/deliveries/CANDIDATES/32/evidence/74a4813161d7206b2e42412b26a3b12a89b160fdb004133e31460d049ae612dd.json)
- [drawdown-method](../../../assets/deliveries/CANDIDATES/32/evidence/966d43859b0f2aaade5e82a5733b1f4b8fa7f96cab62b60bbff32983f1a08397.json)
- [input-original33](../../../assets/deliveries/CANDIDATES/32/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [input-mean_center](../../../assets/deliveries/CANDIDATES/32/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [confirmation-method-v2](../../../assets/deliveries/CANDIDATES/32/evidence/7c3b9912e9493a784d47d48615d57e4da6e3fd17070b3a111811c8fbd26359f2.json)
- [drawdown-method-v2](../../../assets/deliveries/CANDIDATES/32/evidence/44dc297b6ab2a2a50b32fa9ed69b9dd4403c597bfa192e207c2cb4da52100a1f.json)
- [execution-failures](../../../assets/deliveries/CANDIDATES/32/evidence/2b81be5adfcf6dc3fd3536909229cfd0bb01aa980a4e4e8139af3cb0d0ba3f2e.json)
- [confirmation-failure](../../../assets/deliveries/CANDIDATES/32/evidence/9a5d6182b92948f847cb98fcc752e89d29f303f48b93462f79e8bac3c2867c29.json)
- [identity-type-difference](../../../assets/deliveries/CANDIDATES/32/evidence/ed88bead1251573cfd52b6647a96593c5a4197fcd21635f169d685c777f92187.json)
- [absent-cycle-nonfinite-paths](../../../assets/deliveries/CANDIDATES/32/evidence/504044116f12243290b27207117318c72c6886799ad439996b4e3de3be3a0cb6.json)
- [technical-correction](../../../assets/deliveries/CANDIDATES/32/evidence/d0cccf122728d240f688c94d647508b51d810715507e07b59a82c4e358c687fe.json)
- [research-decision](../../../assets/deliveries/CANDIDATES/32/evidence/0ec60e01d7137bfb86e3e33b3e54bda540cbc258575b43b8be807842447b24e3.json)
- [focused-original-math](../../../assets/deliveries/CANDIDATES/32/evidence/ee67b4ea1b78f566e822f40c28678f8d706a883fe93a44950a495c89a3f70d30.json)
- [confirmation](../../../assets/deliveries/CANDIDATES/32/evidence/0b916fde7b2c5d24b337b0e59a5952f33020d6e8a54fdfe97ddb2e0ca24c23e9.json)
- [drawdown](../../../assets/deliveries/CANDIDATES/32/evidence/9c18d0e3415b9b6c97561f372e8ff4e109c5023fe19f89cd64c4c703dc461ed1.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/32/evidence/107f603f41d219753f2016ea342795b0076567632f9cf8a8196be197b26cf732.json)
