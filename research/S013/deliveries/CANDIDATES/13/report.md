# S013：上涨状态两日确认与参数敏感性

RSCH、阶段三；用户授权自主研究无需逐轮评审，保持S013已有数据、MANDATE/6、原四经济目标、执行合同、资源和依赖。目标是验证机制能否在保留经济目标的同时减轻参数退化，本交付COMPLETE只指本轮证据留存完整。

## 事前问题、竞争解释与设计

EX016中已有32个原策略扰动账户2023平均年度收益−4.0173%。上涨路线入场且原状态退出的交易平均实际年度贡献−7.6401个百分点，下跌定时退出组+2.8702；这是按实际当年持仓价格损益和费用核对净值的事后分组，不证明更改状态退出即可消除亏损。本轮因此直接区分上涨入场误判与状态过快切换两种竞争机制。

ENTRY_CONFIRM：仅对上涨路线入场，当前和前一实际交易日的原raw状态均为bull才允许买入。EXIT_CONFIRM：原上涨持仓仅在当前和前一实际交易日raw状态均为bear时按状态退出。BOTH_CONFIRM结合两者。前一交易状态由完整已绑定预热日线先算动量、再shift(1)、最后重索引实际评价sessions；首日使用真实预热上一状态，无日历天替代或缺失填充。原状态动量等于门槛仍属于bull。

这是固定两日确认结构，增加决策等待，不搜索确认长度；不是连续平滑。下跌入场和下跌状态退出保持即时原规则；上涨/下跌时间、区间、止损、追踪退出及优先级和原买入确认分保持。即使状态尚未确认，时间或区间条件仍可先触发卖出。bull持仓改变可能间接影响后续bear机会与资金，不能把bull-only说成bear账户结果不变。

三机制×四背景：B0=(ACF0.1,H4)、B1=(0.045,H4)、B2=(0.1,H3)、B3=(0.045,H3)。12个配置在评价前完整发布，4原TIME账户序列化精确核对后复用；Optuna固定队列、8进程、每进程原生线程1、请求workers1、seed13。新增状态拒绝与原分数拒绝分别核验，不改变原score含义。

最强反证：效果可能只来自少做交易、少付费用或避开已见亏损；延迟上涨状态退出也可能失去2022的保护，错过行情或降低频率。全部四背景及2022/2023、净年化、频率一并披露，不能只挑2023或最好配置。

510500.SH、2020-01-02至2026-09-30、1636交易日、初始100万元、HFQ研究单位/整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策T+1执行。仅S013已有授权资产及预热，无新数据、其他批次或独立封存验证。

原四门：净年化≥正收益基准1.5倍；每自然年回撤严格小于基准；每60交易日平均≥4闭合交易；基准亏损年2022/2023策略年度收益严格为正。全窗回撤及参数退化为诊断，无新增经济门。

## 全部完整账户

|背景|机制|候选|净年化|全窗回撤|闭合交易|2022收益|2023收益|状态拒绝|原四门|
|---|---|---|---:|---:|---:|---:|---:|---:|---|
|B0|TIME|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|0|通过|
|B1|TIME|C7005|15.8174%|24.6200%|125|20.6159%|-1.9705%|0|annual_drawdown、negative_buyhold_year_profit|
|B2|TIME|C7009|11.7652%|17.4850%|121|5.9394%|-1.9690%|0|negative_buyhold_year_profit|
|B3|TIME|C7306|8.4482%|26.7916%|139|-1.7731%|-4.3671%|0|return、annual_drawdown、negative_buyhold_year_profit|
|B0|ENTRY_CONFIRM|C8000|15.4726%|14.5595%|105|7.4353%|1.2716%|28|frequency|
|B1|ENTRY_CONFIRM|C8001|15.3740%|22.7561%|119|15.5236%|0.4578%|25|annual_drawdown|
|B2|ENTRY_CONFIRM|C8002|11.4738%|17.7302%|114|1.4677%|1.2504%|26|通过|
|B3|ENTRY_CONFIRM|C8003|9.7997%|26.1315%|134|2.1876%|0.2345%|25|return、annual_drawdown|
|B0|EXIT_CONFIRM|C8004|12.5037%|15.5679%|104|-2.1553%|-0.0180%|0|frequency、negative_buyhold_year_profit|
|B1|EXIT_CONFIRM|C8005|12.5692%|24.9819%|118|6.4150%|-2.4418%|0|annual_drawdown、negative_buyhold_year_profit|
|B2|EXIT_CONFIRM|C8006|10.3524%|20.2930%|114|4.7064%|-2.2665%|0|return、negative_buyhold_year_profit|
|B3|EXIT_CONFIRM|C8007|7.4781%|27.3685%|132|1.4301%|-3.7326%|0|return、annual_drawdown、negative_buyhold_year_profit|
|B0|BOTH_CONFIRM|C8008|11.9998%|16.9044%|100|-2.6662%|-1.7305%|26|frequency、negative_buyhold_year_profit|
|B1|BOTH_CONFIRM|C8009|12.2976%|25.1783%|115|5.8523%|-2.6960%|23|annual_drawdown、negative_buyhold_year_profit|
|B2|BOTH_CONFIRM|C8010|10.2193%|19.6461%|110|4.1578%|-1.7513%|24|return、negative_buyhold_year_profit|
|B3|BOTH_CONFIRM|C8011|8.6837%|27.1527%|130|7.7354%|-1.7926%|22|return、annual_drawdown、negative_buyhold_year_profit|

入场确认四个背景均通过基准亏损年盈利门，而退出确认与两者结合的全部背景均未通过该门。这支持优先检验入场方向，反对直接把上涨状态退出延迟解释成修复。四个背景共享行情，不能当独立统计样本。

同一H3/ACF0.1背景下，入场确认使年化从11.7652%变为11.4738%，2022从5.9394%变为1.4677%，2023从-1.9690%变为1.2504%，交易121→114。2023修复伴随收益和交易代价，仍按原四门验收，不把旧交易损益相加当新政策贡献。

## 同域完整参数诊断

看到本轮账户结果前固定与EX015相同全部13个数值坐标和域：两路线窗口/入场/退出/期限、下跌ACF、状态窗口/门槛、确认窗口/门槛。原源合法域及S013原ACF搜索域[-0.60,0.50]保持；类别、固定两日确认、null、零冷却和固定执行条件单列。域宽标准化5%总L2、32点/中心、seed13、PCG64、INTEGER HALF_EVEN、LINEAR分位数；原中心及全部新四门达标机制均检验，规定点不按收益替换。不能将历史S007-native未保存域字节的扰动作相同量尺基线。

|中心|年化Q10|回撤Q90|年化退化pp|回撤恶化pp|邻点原四门通过|
|---|---:|---:|---:|---:|---:|
|C2132|5.8974%|30.5044%|10.2598|16.3446|0/32|
|C8002|4.6836%|30.6991%|6.7902|12.9689|0/32|
|C7009（H3未达标控制）|5.2424%|28.0251%|6.5228|10.5401|0/32|

N2相对原中心：年化退化差-3.469609、回撤恶化差-3.375714个百分点。

B2-TIME相对原中心：年化退化差-3.737017、回撤恶化差-5.804524个百分点。

其中原C2132的32点按EX015原身份、强类型计划/绑定、协议、相同坐标/域和账户证据完整核对复用，无新身份或重放；本轮新评价64点（C8002的32点与原H3未达标控制32点）。全部96点纳入诊断。H3控制在C8002代表点技术预检之后、任何批量扰动评价和参数指标查看之前补充声明；初始计划和补充计划分别不可变留存。控制不作为达标候选。

SE公共参数比较可比，分位数独立NumPy复算一致。有限32点不是未来成功概率、置信区间或独立验证；邻点原四门通过数仅作诊断，不改变中心资格或加入硬门。

执行说明：初始几何材料沿用“重跑原C2132”的意图文字；核验已有EX015的完整同域身份、计划和账户后，实际执行改为完整复用32点。初始材料保持不可变，以执行矩阵与本说明区分计划文字和实际次数，不把复用计作新评价。

在完全相同H3数值坐标的32对账户中，入场确认年化更好16点、更差16点；回撤更小20点、更大12点。平均年化差+0.141654、平均回撤差-1.639332个百分点。原H3控制四门通过0/32、新机制0/32。这是完整政策配对描述，非独立统计检验。

只改变入场确认相对原H3控制：年化Q10差-0.558792、回撤Q90差+2.674026、年化退化差+0.267408、回撤恶化差+2.428811个百分点。这一对照用来判断主要改善是否来自期限改变；不得仅凭相对原H4的结果把全部改善归于入场确认。

本轮实际反证：C8002的两项相对退化均比原H4小，但中心年化也由16.1572%降为11.4738%、中心全期回撤由14.1599%升为17.7302%。参数收益Q10由5.8974%降为4.6836%、回撤Q90由30.5044%升为30.6991%。因此相对退化数字的改善未转化为更好的较差参数账户表现。同H3控制收益Q10为5.2424%、回撤Q90为28.0251%；新增入场确认的尾部收益更低、尾部回撤更高，独立机制对照削弱改善主张。32对平均年化略高0.1417个百分点、平均回撤低1.6393个百分点仍是有价值的局部线索，不能代替较差一批账户反证。三个中心扰动均0/32通过原四门，此数仍仅为诊断。

研究判断：相对中心的两项退化指标下降属实，但本轮未提供实质降低参数敏感性的充分证据。中心四门资格保持，诊断不新增候选否决条件；本轮目标不因该数字变化自动完成。

## 验证、结论与下一步

12新机制业务配置，13次实际评价（1次串行/spawn技术重复），4控制复用；参数新业务配置64、既有参数账户复用32、实际评价66。合计不同新业务配置76、实际评价79；重复预检不计新策略发现。

12配置因果前缀/未来修改不变；合成检查确认首日真实预热状态、等号bull、入场与退出方向、下跌即时原规则、非法机制。代表机制及各中心代表参数点（若适用）的串行/spawn信号及双方5类账本精确相同。16中心账户基准账本精确相同，现金/数量/费用/年度/周期/尾仓完整核验通过。研究源码Ruff通过；未做仓库全量回归。分析辅助程序新增状态拒绝单列，仅影响留存分析，不改已发布策略源码或重放账户。

本轮完整对照完成，尚未证明保留原四门的参数敏感性改善，总目标尚未达成。事后上涨/状态损失归因未自动转化为有效交易改进。

全部原生账户、实现、数据与准备绑定、参数强类型父子关系及SE证据通过公开API留存；历史材料保持不可变。未进行正式阶段四五项自检/族排名/交接、冻结、PTE或生产操作。Git不是数据资产备份。

下一步依完整配对路径检验状态等待的收益与频率代价；若简单状态确认不成立，则检验参数决策组合能否减少单一门槛和期限依赖，保留原四门与明确反证。

## 正式证据引用

- [N0完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/b4294f15cd04b72e08a0267e9ea782d79b4e25020490849384e6a6d41e839ae6.json)
- [N1完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/d3fc8001128683a4ac797aaa72cadc9b42e9f124175fd4e731863bd3a0c3faad.json)
- [N2完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/8a0e75060ac94eebdb39d7b87ea2cfcde99b12a25ccced257ec0a883f804b20d.json)
- [N3完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/42e49d3f58beb8cdc01e5dff0356ef1f723b4a08737e1eafade3f22998488869.json)
- [N4完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9de2d557dbf8e423efbdd333729bfbf1f591a5e82225c326404e4e3916525c29.json)
- [N5完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/47b080a1388d5ee3367d4f46320be7e07aa849130cfe84b30d58299cf361b467.json)
- [N6完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/523f37567ed83d1a81490cbefaf4a916be8740032e3e4f172d02b2ed5125738b.json)
- [N7完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/ed37b1fdee99d627fd61268c7501c13bcb2d1dceb78dcd46dd49e5a6495387c2.json)
- [N8完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/0f56d802bcbd14ec473c38bf0bfb22846c714ceefd00ffb518d02e798571db0a.json)
- [N9完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/b8653ee79c6c54069d53d265e28b577df4beebe57562344de432ad7e95d8b8af.json)
- [N10完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/30116230629efc326ca88d5b4b5feb38feb199531d9ba48c16888529c76b7521.json)
- [N11完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/1ff477be6f155f0663b7f2b6aa92ac7460b0cb95b69f3842d70f616659f0b3e9.json)
- [B0-TIME完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B1-TIME完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [B2-TIME完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [B3-TIME完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/1fecef52e37e7073dcf4208b5895c71146c5e775f3fc41fb88e60e59ed090361.json)
- [B0-TIME-P00完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [N2-P00完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e24ca6e324762a6364da0449ac289ebfe7252c00729de48bfdd861dc18182e62.json)
- [N2-P01完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/cb4fbbbb29028ddff41836d640b6788847ab7a30a562b603e7dd538492f7a767.json)
- [N2-P02完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/3e77466fd8c00fe21395aa6723bd27b7734dcb309685bafeeb14e3f217100944.json)
- [N2-P03完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/c670fa67d35e4b1d869be5fabc068b7f91c3806f2bd0cd962bfb673d010149bf.json)
- [N2-P04完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/95c1d89b955962308b968c6150d96fcadae459e4a5b4db7a8a5844db80647a9c.json)
- [N2-P05完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/c0d59644bf67879259740abdae57b082ff4b8b7a5dbdd0327a46e44bce4eec2a.json)
- [N2-P06完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/3a504db0898e5d212ee8d1dd5929a3b677f73752026b35b82c2edbd0ff230713.json)
- [N2-P07完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/edd0bebac0ffd9ec241f4e2669b85fccd693c08c380ded9abed7d220ceba647f.json)
- [N2-P08完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/5104986dc438227e52fd43f845e1902c43401560900ee9a8f5c95ca22b9e0150.json)
- [N2-P09完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a2edcc96f044fbc6b6397d5dd9ef4aedd8f4d6b97b769d0ed4bf5877db383d89.json)
- [N2-P10完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9c08c3a5bd447658d02c407c1cc8f37129ddf5e0b85cafed78a3ffbf9c287f7f.json)
- [N2-P11完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/34b73e883177d8eba4409b335873b4b974d28e67600da784c151a98a758e80ce.json)
- [N2-P12完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/35113acf5d6c7bc53f2eccf436b75f85aee93453cdd6656335fe9f0756e773f4.json)
- [N2-P13完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a06bb890d62856838fe8caf5cd1beafb4b3810ab4666b56d3506e930ceeefba8.json)
- [N2-P14完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/bf9d163cd4843faaacc04837f985e0e37b16cd7369741cc651b78f4b8c2e025c.json)
- [N2-P15完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/05eae7360e2be9e3bbf81ffd536fc68be52cdb55e9b6d52019ffde7e60e6e82a.json)
- [N2-P16完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/7c13fc4f141e6c47f25d1c028f4c5c7cb651eaa43528371316f116c4560a2dd0.json)
- [N2-P17完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a7a2a20ada9d7d32e705aa00c693f6bdc480dbf6d2a1d9b969046c1a6e8e69cf.json)
- [N2-P18完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/6c59bee6d5e90364e2755f681caa8cd44098fd270886185346a2d72f6a9311a6.json)
- [N2-P19完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/6708efe87217df7e86a458ad24970b35a8b1e1e7f1214926e5ed49354398b564.json)
- [N2-P20完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/02df86cd1c17d4649f8b57fbe3a8b5999ae9fbe34fb72e943b293a7e58f57ac4.json)
- [N2-P21完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a2bbda5a7823baf4feb4b86fcbb0ccb45475f9eb014530f44885265de30a21d9.json)
- [N2-P22完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/220e6386729f91ba585356269227619b2a67b51effc814e7821d0c127b8cc004.json)
- [N2-P23完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/790b4f4ee6b566ad018e00d9434d226e76b7e29fd948907260bab0a20acf9e87.json)
- [N2-P24完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/0e450b22f717d7fa0454d43c88801b8f159d33dcc1ee008b043ef0f4808fabdc.json)
- [N2-P25完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/7ce07666916bbf36a59d7d39349cec9eefc5d647d8c215b2d7166513ea783f34.json)
- [N2-P26完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/7664e0b2beedc6281c8ad6727832c7fe27efd866dcb3f413e4404bbca182d4b9.json)
- [N2-P27完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/5a58342bf7c3fa2a9712abc146abb7d0e001e9c958475abdd3963d36ad7f9cf3.json)
- [N2-P28完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/84f5bd2644618d0fe29d27d2921b2ae7ec4e59f960063b1b5e382fc01a7f4fd2.json)
- [N2-P29完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/14558ba1e463f25415c8eee907b6ae443f9b31d4e67da325a99f55ce8f9556bc.json)
- [N2-P30完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/64a52e7e28c0ce7a5f322385d41d63b9d1276460241746dad1cce97a674965f7.json)
- [N2-P31完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/31979ad31132558f9cd2334766317f8a360e4381279fa395dcc880173c7bdd3d.json)
- [B2-TIME-P00完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/c083c2c91c2d68b92e9faede727cd618d500aa4fd4c9caff0760c1ef11711d2c.json)
- [B2-TIME-P01完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/bd482c1f18a70767ef7953b62d411139e26529522f7a2d0a0eac325970f75688.json)
- [B2-TIME-P02完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/39587eb6db203968f686902c29aafd113a37a003a2fc772197e312a422cf9392.json)
- [B2-TIME-P03完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/d08dea900a888fb9d9a90b60f0d12c8150fcca92724fc434749b5af3f7e22b12.json)
- [B2-TIME-P04完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/f0ac470fb46a6105dd822858bf612f6dd95cc76c9a0ec6e569154ee45097add2.json)
- [B2-TIME-P05完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/1750d794a79225ad36f3e030c15b001ecf8557258b0f568e790a20233c5e2a15.json)
- [B2-TIME-P06完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9533a70b1d855f6075069e3bd9d999992d4179ed03fdb7925c12d1d0a72258a1.json)
- [B2-TIME-P07完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/2b97d265c2beeb3e2f95dd3664bbbd531e5312946b646f79fce4403b502b5d5e.json)
- [B2-TIME-P08完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/8ca0507e2d62bad528122042c79ea07283920e11fc96605d12e3a0a143c18472.json)
- [B2-TIME-P09完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/14f5f1f42b42fed8ba819f04621b96c78c3196c6697c28abd774a4a767cf7ae2.json)
- [B2-TIME-P10完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e75dd3ce0d9cabfdc4558a047352f11af5da3c9652ecbf03013e1dfa545bd061.json)
- [B2-TIME-P11完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/5ef58a11808c4753ce31e0aad6ffb1093942e419c6b2c40142b7fa4ff908fe6e.json)
- [B2-TIME-P12完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9ccec27dfacbb8ab5217f9a111a0d4c2ba8e9ca3841541f7dc2e94b77b6ae5ea.json)
- [B2-TIME-P13完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/270f1fc0b3d23b72e49f3ed6113df774c6c6a00aa0684ef67fb7d770e81c9c9e.json)
- [B2-TIME-P14完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/fc0efbd98359d36e9e2faee6d6402b30a4ec56fa263b604032236419c57d8dd0.json)
- [B2-TIME-P15完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/1e9cf3ba95502175d78cb8ce49bca4653c7ff2615c5c7689ba3f03408e2ee9f4.json)
- [B2-TIME-P16完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e6bb70dfb44374693fc6956ae6e25e3a7c44160938f630b232360d5791c434de.json)
- [B2-TIME-P17完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/255e8cbdec6d457bebf4ce9b8727c9501aa07e04f4edc8d37ff1f931da8b373a.json)
- [B2-TIME-P18完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e7f60ac95e11b72ba93c7f73c54c1e561354a5e96599754a7259430f9aee7cfd.json)
- [B2-TIME-P19完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/cbc796225e5277f0e52af6240f21c0b22f9ea31cdb7e7383ad9ec1fbb964aa93.json)
- [B2-TIME-P20完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/77766dc37424606e78b92eabd2d6192d3784706d7ec63a4619b5854b30b4308c.json)
- [B2-TIME-P21完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/14e14c8f275e65613de6fa7c8ebef58925c16d1c9d1baca59582a72151e1cdf7.json)
- [B2-TIME-P22完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e3862d18742dfc79feb53a43e78d98bac7865c13851e4060ab6496f3cdf532bf.json)
- [B2-TIME-P23完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a2962bda7a7afd0c911e8a2b0215603e1724898662bd8fb536f04100efb0785c.json)
- [B2-TIME-P24完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/fe892a0d8302f63773b6a3fdb074e5623c548c2d1820901a1478df7144e424a2.json)
- [B2-TIME-P25完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/885a7d3fbbed6a17b79b24c22878525e6e572d251aeb445f71ed352d570c347f.json)
- [B2-TIME-P26完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/303e5eedf823c2056a4fa3c74686412cb3a213efb38b974652d7c131aaec060f.json)
- [B2-TIME-P27完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/941281e6a94eb6a9ca04efd11274739a3a1cbf6d6777de55fd0ceba0aca19b65.json)
- [B2-TIME-P28完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/e96c1a9b402375baea7dd9d3aefcec6121cbb4249a130dca548cf9e79dfbaac8.json)
- [B2-TIME-P29完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/c745ef1fdb86dfd5cbdf209245914a7135d439e1f1342a88c3c499ac45d599e3.json)
- [B2-TIME-P30完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/a1e2e65bcc723335d54de764ca784f0509fb1f559bb29a251c9a28b165560989.json)
- [B2-TIME-P31完整账户](../../../assets/deliveries/CANDIDATES/13/evidence/9ff70003b0047eae92e941e466181d57e6cfb61003240ad342330c9871e73751.json)
- [既有诊断输入B0-TIME-P00](../../../assets/deliveries/CANDIDATES/13/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [既有诊断输入B0-TIME-P01](../../../assets/deliveries/CANDIDATES/13/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [既有诊断输入B0-TIME-P02](../../../assets/deliveries/CANDIDATES/13/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [既有诊断输入B0-TIME-P03](../../../assets/deliveries/CANDIDATES/13/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [既有诊断输入B0-TIME-P04](../../../assets/deliveries/CANDIDATES/13/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [既有诊断输入B0-TIME-P05](../../../assets/deliveries/CANDIDATES/13/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [既有诊断输入B0-TIME-P06](../../../assets/deliveries/CANDIDATES/13/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [既有诊断输入B0-TIME-P07](../../../assets/deliveries/CANDIDATES/13/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [既有诊断输入B0-TIME-P08](../../../assets/deliveries/CANDIDATES/13/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [既有诊断输入B0-TIME-P09](../../../assets/deliveries/CANDIDATES/13/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [既有诊断输入B0-TIME-P10](../../../assets/deliveries/CANDIDATES/13/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [既有诊断输入B0-TIME-P11](../../../assets/deliveries/CANDIDATES/13/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [既有诊断输入B0-TIME-P12](../../../assets/deliveries/CANDIDATES/13/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [既有诊断输入B0-TIME-P13](../../../assets/deliveries/CANDIDATES/13/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [既有诊断输入B0-TIME-P14](../../../assets/deliveries/CANDIDATES/13/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [既有诊断输入B0-TIME-P15](../../../assets/deliveries/CANDIDATES/13/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [既有诊断输入B0-TIME-P16](../../../assets/deliveries/CANDIDATES/13/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [既有诊断输入B0-TIME-P17](../../../assets/deliveries/CANDIDATES/13/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [既有诊断输入B0-TIME-P18](../../../assets/deliveries/CANDIDATES/13/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [既有诊断输入B0-TIME-P19](../../../assets/deliveries/CANDIDATES/13/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [既有诊断输入B0-TIME-P20](../../../assets/deliveries/CANDIDATES/13/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [既有诊断输入B0-TIME-P21](../../../assets/deliveries/CANDIDATES/13/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [既有诊断输入B0-TIME-P22](../../../assets/deliveries/CANDIDATES/13/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [既有诊断输入B0-TIME-P23](../../../assets/deliveries/CANDIDATES/13/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [既有诊断输入B0-TIME-P24](../../../assets/deliveries/CANDIDATES/13/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [既有诊断输入B0-TIME-P25](../../../assets/deliveries/CANDIDATES/13/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [既有诊断输入B0-TIME-P26](../../../assets/deliveries/CANDIDATES/13/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [既有诊断输入B0-TIME-P27](../../../assets/deliveries/CANDIDATES/13/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [既有诊断输入B0-TIME-P28](../../../assets/deliveries/CANDIDATES/13/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [既有诊断输入B0-TIME-P29](../../../assets/deliveries/CANDIDATES/13/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [既有诊断输入B0-TIME-P30](../../../assets/deliveries/CANDIDATES/13/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [既有诊断输入B0-TIME-P31](../../../assets/deliveries/CANDIDATES/13/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [既有诊断输入N8-P00](../../../assets/deliveries/CANDIDATES/13/evidence/03571480a68a616cd5396fc6d401220757ccdbd044a9b584ff33faa7e43256b1.json)
- [既有诊断输入N8-P01](../../../assets/deliveries/CANDIDATES/13/evidence/ce784b17a9f8205d11cf9b042ff16cc14d6064826be756254d0ca7495e0c73e9.json)
- [既有诊断输入N8-P02](../../../assets/deliveries/CANDIDATES/13/evidence/c0a455bfd71dca6f65a01d9c4a1f30c463100a05c5e296558d6a205be7b9bb3c.json)
- [既有诊断输入N8-P03](../../../assets/deliveries/CANDIDATES/13/evidence/8447ad9bd4b2d3fb04c77e8a6169396b33abd2c4927e98f6a24b6a73cb1f2572.json)
- [既有诊断输入N8-P04](../../../assets/deliveries/CANDIDATES/13/evidence/1d56fce2b90db2af34cbb9f0094e25d740c55304cdc5d8e40a6eee71fa8384a7.json)
- [既有诊断输入N8-P05](../../../assets/deliveries/CANDIDATES/13/evidence/569b4d33bdd0313ef804dc6f05b76183d1eb612f44744124c6c1ff8276b09468.json)
- [既有诊断输入N8-P06](../../../assets/deliveries/CANDIDATES/13/evidence/92177316c263c1a6a81a5163808bc8975adbb797bd1da9d7d24b92b4e8b731a7.json)
- [既有诊断输入N8-P07](../../../assets/deliveries/CANDIDATES/13/evidence/90716ae57f452dd5baecac2b50bc5f7e70c64051c62697d9c5c8532c01ae8f46.json)
- [既有诊断输入N8-P08](../../../assets/deliveries/CANDIDATES/13/evidence/7686bdf5076b990237126d2a35e74491ac405cc0ae9e6da8e058b2ab763ab8a8.json)
- [既有诊断输入N8-P09](../../../assets/deliveries/CANDIDATES/13/evidence/777eaf9b4927ec1a390e51f5650b7cdb351333b641472748b1334d7dc47dc0dd.json)
- [既有诊断输入N8-P10](../../../assets/deliveries/CANDIDATES/13/evidence/7b34575a5af3d0d8776582ecc05f97acd2e44377eebc3e1f6b375bc164d44381.json)
- [既有诊断输入N8-P11](../../../assets/deliveries/CANDIDATES/13/evidence/6d7d4de195479df634c726acfc725cc2ebe4bce42895dd1c2100ead0cad1d1ea.json)
- [既有诊断输入N8-P12](../../../assets/deliveries/CANDIDATES/13/evidence/a995cc27b08ccf340f08998e0f28083d02ca2153503328893938c241f1897474.json)
- [既有诊断输入N8-P13](../../../assets/deliveries/CANDIDATES/13/evidence/7d19b6b9c5f80b34be89b405b04d41416bd349bfe4440c997da812f2faaf135c.json)
- [既有诊断输入N8-P14](../../../assets/deliveries/CANDIDATES/13/evidence/d138d5fa48707489bd6c8b3f6191caedd26e3484b51a02af44eaaac7599e50b8.json)
- [既有诊断输入N8-P15](../../../assets/deliveries/CANDIDATES/13/evidence/a561deaa3a129501dee0351ff46e535ade90f84f9da3bc6d699dc37c0b266588.json)
- [既有诊断输入N8-P16](../../../assets/deliveries/CANDIDATES/13/evidence/9367c023616684b385526dc2890608b96199d764fd7528fc4f78aa902de3a7ca.json)
- [既有诊断输入N8-P17](../../../assets/deliveries/CANDIDATES/13/evidence/a529ed3172b110215c6840045cd5ae49a26c5d20212e80d27a5f7cd7ea691adf.json)
- [既有诊断输入N8-P18](../../../assets/deliveries/CANDIDATES/13/evidence/d24abab7755f6f6dc3e83789f430fab4095c3aecd86c711d8a6a15b5f578f2ff.json)
- [既有诊断输入N8-P19](../../../assets/deliveries/CANDIDATES/13/evidence/fb7ab4f5c42cc22a02badf706b792ccb6c7948c1e563a9a6f14d2437609a4963.json)
- [既有诊断输入N8-P20](../../../assets/deliveries/CANDIDATES/13/evidence/72f63bffe90852ae501573e69f0e17d436eadbce8be313fc8b77573ef00fe31e.json)
- [既有诊断输入N8-P21](../../../assets/deliveries/CANDIDATES/13/evidence/5e5b27cb5f85a5e14e526ffd6ac1d35c7de3a042c3443362fbd367d682822d32.json)
- [既有诊断输入N8-P22](../../../assets/deliveries/CANDIDATES/13/evidence/fc7ea90b4925fcbe1efd2c632c6a1603d49b48df0feca845c1a5eebab7be1787.json)
- [既有诊断输入N8-P23](../../../assets/deliveries/CANDIDATES/13/evidence/787ae51ef463005ca033db01a769059c5313c23bf6bf8c28e4e7a578fe015ed5.json)
- [既有诊断输入N8-P24](../../../assets/deliveries/CANDIDATES/13/evidence/299ec56048bf1d7e989eb9f62560fe499e8f1e0e78e7d2072331caf203e112a8.json)
- [既有诊断输入N8-P25](../../../assets/deliveries/CANDIDATES/13/evidence/e016caafd734d51c9d64df2180f8caeb4e587361a31154cf4c08bfe92536cb86.json)
- [既有诊断输入N8-P26](../../../assets/deliveries/CANDIDATES/13/evidence/daaba1bd5291638645630889e2a290e32287f6f26e25f66aec32fd38d42eea15.json)
- [既有诊断输入N8-P27](../../../assets/deliveries/CANDIDATES/13/evidence/f44fe2ea4c5eedfde3e6b7e64200535ba4597cc4e50bf1231527377d2e50651a.json)
- [既有诊断输入N8-P28](../../../assets/deliveries/CANDIDATES/13/evidence/40310c35b259719891e96831c9432c4fc0be7c5b41a678fecb49fa1baeb6ddf4.json)
- [既有诊断输入N8-P29](../../../assets/deliveries/CANDIDATES/13/evidence/8c69faa83e1dbc492fb542084f544ae087e8543c1895a0b3544b593f61e112a8.json)
- [既有诊断输入N8-P30](../../../assets/deliveries/CANDIDATES/13/evidence/c22427d5db1e373153c45b8cc2afc7e46a79cb314848d04357142efd0c7d450d.json)
- [既有诊断输入N8-P31](../../../assets/deliveries/CANDIDATES/13/evidence/5087b30f7abfba3714c1d8735a5707ff8bcd9e6163e608d2889d990466d256d8.json)
- [既有诊断输入C2132-center](../../../assets/deliveries/CANDIDATES/13/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [final-authorization](../../../assets/deliveries/CANDIDATES/13/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [final-geometry](../../../assets/deliveries/CANDIDATES/13/evidence/cf64f2732db99e3df55306a13c19cc4834f3fd973eababeebbfe25e893d16e8f.json)
- [final-geometry-reference](../../../assets/deliveries/CANDIDATES/13/evidence/cad1af4876019586c4d746dec79cc42596a25e32b10c0459d0fa7f7589c2d2ef.json)
- [final-parameter-analysis-references](../../../assets/deliveries/CANDIDATES/13/evidence/1081bc6f28e4b7bbab75368d5367b8c316792b2b27649b084d582357661aac14.json)
- [final-parameter-plans](../../../assets/deliveries/CANDIDATES/13/evidence/915d2ceaf62056df4afa1d936d4840308a404ba2dfc72aa41b6ce6e3e7ad1fcb.json)
- [final-parameter-plans-with-control](../../../assets/deliveries/CANDIDATES/13/evidence/cbb77c68d90dc87c2f5849959f0ffccb647a0521c188dd650b1c1f2c28da0973.json)
- [final-plan](../../../assets/deliveries/CANDIDATES/13/evidence/273402a69b02a089ac3698acbce1ab16078c5863c7ab6c83f538b499d1a22783.json)
- [final-plan-references](../../../assets/deliveries/CANDIDATES/13/evidence/bdbcc4e57952e242375878f16afdbf76b698c3c358ff5004f1e48d5e5682b67b.json)
- [final-account-references](../../../assets/deliveries/CANDIDATES/13/evidence/b9730875813c3e569ddaf96da75eea456539f40a5e28c62c3ac11b1b377fb4b2.json)
- [final-analysis](../../../assets/deliveries/CANDIDATES/13/evidence/f36a6307d1dbeb2cfb1bf766fc83072629be62b77a161d0cc51ef362cd80464f.json)
- [final-conclusion](../../../assets/deliveries/CANDIDATES/13/evidence/05a495e21af917c115d00e428381fe8f6004420e3263096ebc8fe19548d0634a.json)
- [final-mandate-validation](../../../assets/deliveries/CANDIDATES/13/evidence/f0682e41798c61bd113530c63b6b093454cde040b93768335ff11fab37012d40.json)
- [final-matrix](../../../assets/deliveries/CANDIDATES/13/evidence/24793472819fc2748b1f6cc96439564cf5777839af6a5663b64f8b037abcc533.json)
- [final-parameter-analysis](../../../assets/deliveries/CANDIDATES/13/evidence/b85e3eaaf2f5835b3ce82143f80c07a3d3f1452bc05f477de96ec69592e3801c.json)
- [final-parameter-matrix](../../../assets/deliveries/CANDIDATES/13/evidence/9470c888e2147ba4fe85584b78d004da6e5adbc672d342571ecb37fc994a123b.json)
- [final-parameter-pairs](../../../assets/deliveries/CANDIDATES/13/evidence/19f869b6897bbf6eb7e3f7714c27380477b723a6da036f0ecf6af0c0c7b16299.json)
- [final-parameter-precheck](../../../assets/deliveries/CANDIDATES/13/evidence/d59f8cf38da9c1f63efa2a44e439c950a4525ea12b140b830750df90940c1cae.json)
- [final-parameter-precheck-initial](../../../assets/deliveries/CANDIDATES/13/evidence/8374ce017a88640c51841973744f1986e787a7ad617d3247a124d7ed6fd9d0b0.json)
- [final-precheck](../../../assets/deliveries/CANDIDATES/13/evidence/c0b916b8b3812233319f166e99777f74715cc58821f775c39d01c6cd4bf0d587.json)
- [final-previous-diagnosis-binding](../../../assets/deliveries/CANDIDATES/13/evidence/30db20533fc7f2293eed35a382f8f32d4967bb9440e1a18466492df880e3f807.json)
- [final-registration](../../../assets/deliveries/CANDIDATES/13/evidence/4281dcf443d6512611012df8cda36d5bd339c145e530c7d7d5f3588f2017ad8a.json)
- [final-reproduction](../../../assets/deliveries/CANDIDATES/13/evidence/f0753501301ad1ebd41faa4bc318d2c0fb0dec014e19be220723307d32a8b1ae.json)
- [final-synthetic-check](../../../assets/deliveries/CANDIDATES/13/evidence/3bf9bb77d9a3366a1959404ab064955718331af719eb7cdb28a55969a7cd878b.json)
- [既有年度描述归因](../../../assets/deliveries/CANDIDATES/13/evidence/26dad0baf35054808dca919a74d7537f2858de04f21b303c432c7b8c13a53135.json)
