# S013：持仓相对入场价格与参数敏感性

RSCH、阶段三；直接用户自主研究授权，保持原S013数据、MANDATE/6四项目标、执行规则与成本。已有C2132参数扰动的主要失败是净年化和基准亏损年仍盈利要求，年度回撤门不是主要失败项。此前单日价格方向、原确认分方向与平滑过滤均不足；本轮检验不同的信息：持仓价格是否仍高于入场信号日价格。

## 事前机制与完整对照

EXIT_NONPOSITIVE：下跌路线年龄达到原期限后，当前Close不高于入场信号日Close才定时退出；仍高于该价时继续持有。EXIT_NONNEGATIVE为相反方向。等号满足两边。anchor来自入场信号日、因果可得，不是成交价格或账户净盈利。费用、实际买价和订单未成交仍按完整账户计算；不把这种相对价格叫作实际盈亏。上涨期限、区间/状态退出及优先级、原买入确认全部保持。

两机制×四背景：B0=(ACF0.1,H4)、B1=(0.045,H4)、B2=(0.1,H3)、B3=(0.045,H3)。8配置在评价前完整发布；4个原TIME控制核对原生序列化后复用。没有新增可调数值坐标；零相对变化是业务比较本身。全部结果保留。Optuna固定队列、8进程、每进程原生线程1、请求workers1、seed13。

仍使用510500.SH、2020-01-02至2026-09-30、1636交易日、初始100万元、HFQ研究单位/整手100、每侧10bp、策略与LimitBuyHold统一1%买入溢价、T决策T+1执行。数据均来自S013已有授权资产及预热，没有其他批次或新数据。历史开发池已反复查看，非独立验证。

原四门：年化≥正收益基准1.5倍；各自然年回撤严格小于基准；每60交易日平均≥4笔闭合交易；基准亏损年2022/2023策略年度收益严格为正。全窗回撤与扰动指标均为诊断，不新增经济门。

|背景|机制|候选|净年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---|---:|---:|---:|---:|---:|---|
|B0|TIME|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|B1|TIME|C7005|15.8174%|24.6200%|125|20.6159%|-1.9705%|annual_drawdown、negative_buyhold_year_profit|
|B2|TIME|C7009|11.7652%|17.4850%|121|5.9394%|-1.9690%|negative_buyhold_year_profit|
|B3|TIME|C7306|8.4482%|26.7916%|139|-1.7731%|-4.3671%|return、annual_drawdown、negative_buyhold_year_profit|
|B0|EXIT_NONPOSITIVE|C7800|16.8103%|17.7050%|100|9.7420%|-1.3315%|frequency、negative_buyhold_year_profit|
|B1|EXIT_NONPOSITIVE|C7801|15.0450%|24.8350%|106|16.9094%|-1.8168%|annual_drawdown、frequency、negative_buyhold_year_profit|
|B2|EXIT_NONPOSITIVE|C7802|12.3483%|22.8303%|105|9.2935%|-1.5658%|frequency、negative_buyhold_year_profit|
|B3|EXIT_NONPOSITIVE|C7803|11.8903%|27.8512%|113|15.0251%|-4.3407%|annual_drawdown、negative_buyhold_year_profit|
|B0|EXIT_NONNEGATIVE|C7804|14.2228%|23.6517%|98|7.4470%|-2.5257%|frequency、negative_buyhold_year_profit|
|B1|EXIT_NONNEGATIVE|C7805|16.5567%|22.6486%|108|12.8832%|-1.1872%|frequency、negative_buyhold_year_profit|
|B2|EXIT_NONNEGATIVE|C7806|15.2075%|23.0392%|103|13.1429%|-4.2059%|frequency、negative_buyhold_year_profit|
|B3|EXIT_NONNEGATIVE|C7807|15.6109%|22.1344%|113|1.2773%|-2.8903%|negative_buyhold_year_profit|

## 参数诊断与结论

8个新机制没有原四门达标配置，未追加扰动账户。事前参数域仍保留，未为了宣布稳健性而放宽经济目标。

本轮机制对照完成，但未证明保留原目标的参数敏感性改善；总目标尚未达成。延长持仓可能降低频率并积累亏损，相反方向完整报告，不能只挑收益最高账户。

## 技术验证与留存

8新机制配置、9次实际完整评价（1次串行/spawn技术重复），4原控制复用；参数配置0个、实际参数评价0次。实际总评价9，不同新业务配置8。技术重复不计新策略发现。

全部8配置前缀及未来修改因果检查通过；合成检查包括两方向、年龄条件、等号双边、上涨原期限和非法机制；代表串行/spawn信号及策略/基准双方5账本精确相同。12中心账户的基准5账本精确相同，完整现金/数量/价格/费用/年度/周期/尾仓核验通过。研究源码Ruff检查通过；未做仓库全量回归。

全部评价、原生账户、源码、完整数据和参数绑定通过公开研究API留存；旧证据不可变。本交付COMPLETE只表示本轮证据完整，不表示稳健目标自动达成、正式阶段四排名/交接、冻结或PTE授权。Git不是数据资产备份。


## 已有账户的最强反证与下一步

已有EX015两套各32点账户的事后描述独立留存。原32点2023实际日历年收益平均−4.0173%；下跌路线定时退出组平均贡献+2.8702个百分点、下跌状态退出+1.6173，上涨状态退出−7.6401、上涨定时退出−0.8647。这按当年每日持仓价格损益和实际费用归因，并对到账户年度净值；退出原因只是原政策的事后分组，不能解释成改变该退出即消除该损失。原32点每点均未通过基准亏损年盈利门，30点未过总收益、9点未过频率，年度回撤门均通过。

对2023下跌定时退出按入场/退出信号日期去重，排除当日状态已切换的事件：相对入场价负组30事件，随后3日均+0.3690%；正组36事件，随后3日均−0.1261%。到10日则约−0.0308%与+0.7948%，方向改变；不能据此挑观察窗或机制。未来窗口统一使用信号价格单位；未发布初稿混用单位已在留存说明中揭示，实际年度现金/费用归因不受影响。事件重叠且非独立，不是完整新政策账户效果。

这条反证改变下一步优先级：不能把2023损失主要归因于下跌定时退出，应先研究上涨路线入场和状态切换带来的路径损失，考虑有明确反证的状态确认或参数决策组合。仍保持原四门，不依赖反复微调旧门槛宣布成功。

## 正式证据引用

- [N0完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/f4002f9175794a6a55f113f7d19fdd5091e4c95c3b891d17403cd94208c47ee9.json)
- [N1完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/662e3117819f6da8d4e05d2cb31ec425ae0b4d971352027654046df23b598858.json)
- [N2完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/a4832fc9993cb0f9cad4cb0ee5e99de2ff16bac60da3b9e2ad875112a1f82800.json)
- [N3完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/5897f55ca8d285e85afdf651e61a95a39c531e2abc792f31cb7eb89ed31f6ad8.json)
- [N4完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/7d1146c3e67717f86c82b3d66eb20904c45a9a08c391c59bcf67afe5f6982dc9.json)
- [N5完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/c45d3e303e3193e9a98d7afef58d8410f51463b564603320f2e6fc6a8cdc5087.json)
- [N6完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/5a214356dff49f354b20f08dd563d69cec641e7fedf20c9cbfdb7462f93f2e99.json)
- [N7完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/3ea029622e073d6980bafc30990687334d6d4b0568efc4c7174b3cc849b83d46.json)
- [B0-TIME完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B1-TIME完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [B2-TIME完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [B3-TIME完整账户](../../../assets/deliveries/CANDIDATES/12/evidence/1fecef52e37e7073dcf4208b5895c71146c5e775f3fc41fb88e60e59ed090361.json)
- [既有诊断输入B0-TIME-P00](../../../assets/deliveries/CANDIDATES/12/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [既有诊断输入B0-TIME-P01](../../../assets/deliveries/CANDIDATES/12/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [既有诊断输入B0-TIME-P02](../../../assets/deliveries/CANDIDATES/12/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [既有诊断输入B0-TIME-P03](../../../assets/deliveries/CANDIDATES/12/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [既有诊断输入B0-TIME-P04](../../../assets/deliveries/CANDIDATES/12/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [既有诊断输入B0-TIME-P05](../../../assets/deliveries/CANDIDATES/12/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [既有诊断输入B0-TIME-P06](../../../assets/deliveries/CANDIDATES/12/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [既有诊断输入B0-TIME-P07](../../../assets/deliveries/CANDIDATES/12/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [既有诊断输入B0-TIME-P08](../../../assets/deliveries/CANDIDATES/12/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [既有诊断输入B0-TIME-P09](../../../assets/deliveries/CANDIDATES/12/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [既有诊断输入B0-TIME-P10](../../../assets/deliveries/CANDIDATES/12/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [既有诊断输入B0-TIME-P11](../../../assets/deliveries/CANDIDATES/12/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [既有诊断输入B0-TIME-P12](../../../assets/deliveries/CANDIDATES/12/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [既有诊断输入B0-TIME-P13](../../../assets/deliveries/CANDIDATES/12/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [既有诊断输入B0-TIME-P14](../../../assets/deliveries/CANDIDATES/12/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [既有诊断输入B0-TIME-P15](../../../assets/deliveries/CANDIDATES/12/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [既有诊断输入B0-TIME-P16](../../../assets/deliveries/CANDIDATES/12/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [既有诊断输入B0-TIME-P17](../../../assets/deliveries/CANDIDATES/12/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [既有诊断输入B0-TIME-P18](../../../assets/deliveries/CANDIDATES/12/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [既有诊断输入B0-TIME-P19](../../../assets/deliveries/CANDIDATES/12/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [既有诊断输入B0-TIME-P20](../../../assets/deliveries/CANDIDATES/12/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [既有诊断输入B0-TIME-P21](../../../assets/deliveries/CANDIDATES/12/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [既有诊断输入B0-TIME-P22](../../../assets/deliveries/CANDIDATES/12/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [既有诊断输入B0-TIME-P23](../../../assets/deliveries/CANDIDATES/12/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [既有诊断输入B0-TIME-P24](../../../assets/deliveries/CANDIDATES/12/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [既有诊断输入B0-TIME-P25](../../../assets/deliveries/CANDIDATES/12/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [既有诊断输入B0-TIME-P26](../../../assets/deliveries/CANDIDATES/12/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [既有诊断输入B0-TIME-P27](../../../assets/deliveries/CANDIDATES/12/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [既有诊断输入B0-TIME-P28](../../../assets/deliveries/CANDIDATES/12/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [既有诊断输入B0-TIME-P29](../../../assets/deliveries/CANDIDATES/12/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [既有诊断输入B0-TIME-P30](../../../assets/deliveries/CANDIDATES/12/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [既有诊断输入B0-TIME-P31](../../../assets/deliveries/CANDIDATES/12/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [既有诊断输入N8-P00](../../../assets/deliveries/CANDIDATES/12/evidence/03571480a68a616cd5396fc6d401220757ccdbd044a9b584ff33faa7e43256b1.json)
- [既有诊断输入N8-P01](../../../assets/deliveries/CANDIDATES/12/evidence/ce784b17a9f8205d11cf9b042ff16cc14d6064826be756254d0ca7495e0c73e9.json)
- [既有诊断输入N8-P02](../../../assets/deliveries/CANDIDATES/12/evidence/c0a455bfd71dca6f65a01d9c4a1f30c463100a05c5e296558d6a205be7b9bb3c.json)
- [既有诊断输入N8-P03](../../../assets/deliveries/CANDIDATES/12/evidence/8447ad9bd4b2d3fb04c77e8a6169396b33abd2c4927e98f6a24b6a73cb1f2572.json)
- [既有诊断输入N8-P04](../../../assets/deliveries/CANDIDATES/12/evidence/1d56fce2b90db2af34cbb9f0094e25d740c55304cdc5d8e40a6eee71fa8384a7.json)
- [既有诊断输入N8-P05](../../../assets/deliveries/CANDIDATES/12/evidence/569b4d33bdd0313ef804dc6f05b76183d1eb612f44744124c6c1ff8276b09468.json)
- [既有诊断输入N8-P06](../../../assets/deliveries/CANDIDATES/12/evidence/92177316c263c1a6a81a5163808bc8975adbb797bd1da9d7d24b92b4e8b731a7.json)
- [既有诊断输入N8-P07](../../../assets/deliveries/CANDIDATES/12/evidence/90716ae57f452dd5baecac2b50bc5f7e70c64051c62697d9c5c8532c01ae8f46.json)
- [既有诊断输入N8-P08](../../../assets/deliveries/CANDIDATES/12/evidence/7686bdf5076b990237126d2a35e74491ac405cc0ae9e6da8e058b2ab763ab8a8.json)
- [既有诊断输入N8-P09](../../../assets/deliveries/CANDIDATES/12/evidence/777eaf9b4927ec1a390e51f5650b7cdb351333b641472748b1334d7dc47dc0dd.json)
- [既有诊断输入N8-P10](../../../assets/deliveries/CANDIDATES/12/evidence/7b34575a5af3d0d8776582ecc05f97acd2e44377eebc3e1f6b375bc164d44381.json)
- [既有诊断输入N8-P11](../../../assets/deliveries/CANDIDATES/12/evidence/6d7d4de195479df634c726acfc725cc2ebe4bce42895dd1c2100ead0cad1d1ea.json)
- [既有诊断输入N8-P12](../../../assets/deliveries/CANDIDATES/12/evidence/a995cc27b08ccf340f08998e0f28083d02ca2153503328893938c241f1897474.json)
- [既有诊断输入N8-P13](../../../assets/deliveries/CANDIDATES/12/evidence/7d19b6b9c5f80b34be89b405b04d41416bd349bfe4440c997da812f2faaf135c.json)
- [既有诊断输入N8-P14](../../../assets/deliveries/CANDIDATES/12/evidence/d138d5fa48707489bd6c8b3f6191caedd26e3484b51a02af44eaaac7599e50b8.json)
- [既有诊断输入N8-P15](../../../assets/deliveries/CANDIDATES/12/evidence/a561deaa3a129501dee0351ff46e535ade90f84f9da3bc6d699dc37c0b266588.json)
- [既有诊断输入N8-P16](../../../assets/deliveries/CANDIDATES/12/evidence/9367c023616684b385526dc2890608b96199d764fd7528fc4f78aa902de3a7ca.json)
- [既有诊断输入N8-P17](../../../assets/deliveries/CANDIDATES/12/evidence/a529ed3172b110215c6840045cd5ae49a26c5d20212e80d27a5f7cd7ea691adf.json)
- [既有诊断输入N8-P18](../../../assets/deliveries/CANDIDATES/12/evidence/d24abab7755f6f6dc3e83789f430fab4095c3aecd86c711d8a6a15b5f578f2ff.json)
- [既有诊断输入N8-P19](../../../assets/deliveries/CANDIDATES/12/evidence/fb7ab4f5c42cc22a02badf706b792ccb6c7948c1e563a9a6f14d2437609a4963.json)
- [既有诊断输入N8-P20](../../../assets/deliveries/CANDIDATES/12/evidence/72f63bffe90852ae501573e69f0e17d436eadbce8be313fc8b77573ef00fe31e.json)
- [既有诊断输入N8-P21](../../../assets/deliveries/CANDIDATES/12/evidence/5e5b27cb5f85a5e14e526ffd6ac1d35c7de3a042c3443362fbd367d682822d32.json)
- [既有诊断输入N8-P22](../../../assets/deliveries/CANDIDATES/12/evidence/fc7ea90b4925fcbe1efd2c632c6a1603d49b48df0feca845c1a5eebab7be1787.json)
- [既有诊断输入N8-P23](../../../assets/deliveries/CANDIDATES/12/evidence/787ae51ef463005ca033db01a769059c5313c23bf6bf8c28e4e7a578fe015ed5.json)
- [既有诊断输入N8-P24](../../../assets/deliveries/CANDIDATES/12/evidence/299ec56048bf1d7e989eb9f62560fe499e8f1e0e78e7d2072331caf203e112a8.json)
- [既有诊断输入N8-P25](../../../assets/deliveries/CANDIDATES/12/evidence/e016caafd734d51c9d64df2180f8caeb4e587361a31154cf4c08bfe92536cb86.json)
- [既有诊断输入N8-P26](../../../assets/deliveries/CANDIDATES/12/evidence/daaba1bd5291638645630889e2a290e32287f6f26e25f66aec32fd38d42eea15.json)
- [既有诊断输入N8-P27](../../../assets/deliveries/CANDIDATES/12/evidence/f44fe2ea4c5eedfde3e6b7e64200535ba4597cc4e50bf1231527377d2e50651a.json)
- [既有诊断输入N8-P28](../../../assets/deliveries/CANDIDATES/12/evidence/40310c35b259719891e96831c9432c4fc0be7c5b41a678fecb49fa1baeb6ddf4.json)
- [既有诊断输入N8-P29](../../../assets/deliveries/CANDIDATES/12/evidence/8c69faa83e1dbc492fb542084f544ae087e8543c1895a0b3544b593f61e112a8.json)
- [既有诊断输入N8-P30](../../../assets/deliveries/CANDIDATES/12/evidence/c22427d5db1e373153c45b8cc2afc7e46a79cb314848d04357142efd0c7d450d.json)
- [既有诊断输入N8-P31](../../../assets/deliveries/CANDIDATES/12/evidence/5087b30f7abfba3714c1d8735a5707ff8bcd9e6163e608d2889d990466d256d8.json)
- [既有诊断输入C2132-center](../../../assets/deliveries/CANDIDATES/12/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [final-authorization](../../../assets/deliveries/CANDIDATES/12/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [final-geometry](../../../assets/deliveries/CANDIDATES/12/evidence/1b59fcb6b6ecabe2e5c787523f39f0eb26354bb3367427a4c3032ae8598b9b1d.json)
- [final-geometry-reference](../../../assets/deliveries/CANDIDATES/12/evidence/f1d146d31b0138cfc6afe65fc7e39647f16b06dcbdcc334556b736dd0019bd75.json)
- [final-parameter-plans](../../../assets/deliveries/CANDIDATES/12/evidence/462709356485c188f7655792368c6065b9314f60c874701b34f18210f6cd03fc.json)
- [final-plan](../../../assets/deliveries/CANDIDATES/12/evidence/c34a3c0c07181937612ce4bf26006d527a70bb8dcb357de03db9d973b972ad71.json)
- [final-plan-references](../../../assets/deliveries/CANDIDATES/12/evidence/57e5df72976658b10defcf29b57e7a2ed675f4c06a5e15e0aae24b73aa3be9e9.json)
- [final-previous-account-diagnosis-reference](../../../assets/deliveries/CANDIDATES/12/evidence/92111745af7695439e0396f1789c9eb0ebf123674fcb4fefd6a95e0bb1fdb16f.json)
- [final-account-references](../../../assets/deliveries/CANDIDATES/12/evidence/f6868849a69c9ae7ce92d66f7fea0fbb15119ac305e23a9d918480dd2a7ed116.json)
- [final-analysis](../../../assets/deliveries/CANDIDATES/12/evidence/e34fe34d02823eaea53903204681794b52798489a79cb39172fd0625da318e89.json)
- [final-conclusion](../../../assets/deliveries/CANDIDATES/12/evidence/6b289d15a648287567f27ea18efb740cf864a754269e0bf9e1c1542ddcd3093e.json)
- [final-mandate-validation](../../../assets/deliveries/CANDIDATES/12/evidence/f0682e41798c61bd113530c63b6b093454cde040b93768335ff11fab37012d40.json)
- [final-matrix](../../../assets/deliveries/CANDIDATES/12/evidence/0bf5e7ca22e0f85c93a51168b01d07f7e560acbeb38a6fe186428bb54e554b15.json)
- [final-parameter-analysis](../../../assets/deliveries/CANDIDATES/12/evidence/7c93de697c6772cc1b0f44c4bc90ac71189d655aa5078449ac7bc0d935fded55.json)
- [final-precheck](../../../assets/deliveries/CANDIDATES/12/evidence/0f9861822221918e2ad0aed80d4d9b7f8559fa6904dd961a8488282145bced00.json)
- [final-previous-account-diagnosis](../../../assets/deliveries/CANDIDATES/12/evidence/26dad0baf35054808dca919a74d7537f2858de04f21b303c432c7b8c13a53135.json)
- [final-registration](../../../assets/deliveries/CANDIDATES/12/evidence/60d02b34818897fbd7e434ed45732da7f9af70df30a69763c18539f4c344da62.json)
- [final-reproduction](../../../assets/deliveries/CANDIDATES/12/evidence/f249e05d97402cf1dcda27c975c2eea7a6d630e1d56f8643d6003fa4854e9eea.json)
- [final-synthetic-check](../../../assets/deliveries/CANDIDATES/12/evidence/41f66a4f91cf8cd6195eb98afd646c1ef8d482d47071b1d89b5990ab2fa28329.json)
