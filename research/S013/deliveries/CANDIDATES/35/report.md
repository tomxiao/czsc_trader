# S013：完整既有账户下跌入场价格方向诊断

RSCH阶段三，用户授权自主推进，无需逐轮评审。原S013数据、四项经济门和13维完整参数域保持。本轮零新增账户，精确复用原C2132及32个原域联合扰动账户、均值居中自相关C8701和附加上涨转换BODY门C8481，共35个原生账户。原33账户使用同一市场路径，不能当作33个独立样本；另两中心单列。

每个账户原有1636个信号日保留，包含用于2020执行的2019信号。原生正式身份、参数来源、绑定、基准和完整现金/数量账本核对；独立重算自相关、量额秩、确认分、范围位置、路由和全持仓状态。只在原生空仓资格机会与原生买入上，统计两个严格不等式：Close>前一实际信号日Close，表示较前收上涨；Close>当日Open，表示当日收盘高于开盘。等于和下跌单列，不增加数值阈值。

|账户组|信号年|路线|原生集合|数量|原确认通过|较前收上涨|等于前收|较前收下跌|收高于开|等于开盘|收低于开|
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|原中心|ALL|bull|opportunity|79|56|37|1|41|38|0|41|
|原中心|ALL|bull|entry|56|56|26|1|29|28|0|28|
|原中心|ALL|bear|opportunity|57|57|23|0|34|22|0|35|
|原中心|ALL|bear|entry|57|57|23|0|34|22|0|35|
|原中心|2019|bull|opportunity|1|1|1|0|0|1|0|0|
|原中心|2019|bull|entry|1|1|1|0|0|1|0|0|
|原中心|2019|bear|opportunity|0|0|0|0|0|0|0|0|
|原中心|2019|bear|entry|0|0|0|0|0|0|0|0|
|原中心|2020|bull|opportunity|10|5|5|0|5|4|0|6|
|原中心|2020|bull|entry|5|5|1|0|4|1|0|4|
|原中心|2020|bear|opportunity|11|11|4|0|7|4|0|7|
|原中心|2020|bear|entry|11|11|4|0|7|4|0|7|
|原中心|2021|bull|opportunity|7|5|3|0|4|5|0|2|
|原中心|2021|bull|entry|5|5|2|0|3|4|0|1|
|原中心|2021|bear|opportunity|7|7|3|0|4|4|0|3|
|原中心|2021|bear|entry|7|7|3|0|4|4|0|3|
|原中心|2022|bull|opportunity|19|16|10|1|8|8|0|11|
|原中心|2022|bull|entry|16|16|9|1|6|7|0|9|
|原中心|2022|bear|opportunity|12|12|6|0|6|5|0|7|
|原中心|2022|bear|entry|12|12|6|0|6|5|0|7|
|原中心|2023|bull|opportunity|12|11|6|0|6|7|0|5|
|原中心|2023|bull|entry|11|11|6|0|5|6|0|5|
|原中心|2023|bear|opportunity|10|10|6|0|4|6|0|4|
|原中心|2023|bear|entry|10|10|6|0|4|6|0|4|
|原中心|2024|bull|opportunity|14|9|5|0|9|6|0|8|
|原中心|2024|bull|entry|9|9|4|0|5|5|0|4|
|原中心|2024|bear|opportunity|10|10|3|0|7|2|0|8|
|原中心|2024|bear|entry|10|10|3|0|7|2|0|8|
|原中心|2025|bull|opportunity|8|5|4|0|4|5|0|3|
|原中心|2025|bull|entry|5|5|2|0|3|3|0|2|
|原中心|2025|bear|opportunity|5|5|1|0|4|1|0|4|
|原中心|2025|bear|entry|5|5|1|0|4|1|0|4|
|原中心|2026|bull|opportunity|8|4|3|0|5|2|0|6|
|原中心|2026|bull|entry|4|4|1|0|3|1|0|3|
|原中心|2026|bear|opportunity|2|2|0|0|2|0|0|2|
|原中心|2026|bear|entry|2|2|0|0|2|0|0|2|
|原33账户合计（非独立样本）|ALL|bull|opportunity|2596|1783|1411|29|1156|1440|13|1143|
|原33账户合计（非独立样本）|ALL|bull|entry|1783|1783|983|12|788|1049|8|726|
|原33账户合计（非独立样本）|ALL|bear|opportunity|2021|2014|766|2|1253|770|2|1249|
|原33账户合计（非独立样本）|ALL|bear|entry|2014|2014|765|2|1247|769|2|1243|
|原33账户合计（非独立样本）|2019|bull|opportunity|32|32|32|0|0|32|0|0|
|原33账户合计（非独立样本）|2019|bull|entry|32|32|32|0|0|32|0|0|
|原33账户合计（非独立样本）|2019|bear|opportunity|0|0|0|0|0|0|0|0|
|原33账户合计（非独立样本）|2019|bear|entry|0|0|0|0|0|0|0|0|
|原33账户合计（非独立样本）|2020|bull|opportunity|307|154|138|0|169|114|0|193|
|原33账户合计（非独立样本）|2020|bull|entry|154|154|17|0|137|26|0|128|
|原33账户合计（非独立样本）|2020|bear|opportunity|376|376|92|0|284|104|0|272|
|原33账户合计（非独立样本）|2020|bear|entry|376|376|92|0|284|104|0|272|
|原33账户合计（非独立样本）|2021|bull|opportunity|249|166|162|0|87|181|11|57|
|原33账户合计（非独立样本）|2021|bull|entry|166|166|98|0|68|120|8|38|
|原33账户合计（非独立样本）|2021|bear|opportunity|291|291|77|0|214|93|0|198|
|原33账户合计（非独立样本）|2021|bear|entry|291|291|77|0|214|93|0|198|
|原33账户合计（非独立样本）|2022|bull|opportunity|620|466|378|28|214|382|2|236|
|原33账户合计（非独立样本）|2022|bull|entry|466|466|313|11|142|319|0|147|
|原33账户合计（非独立样本）|2022|bear|opportunity|402|402|208|0|194|192|0|210|
|原33账户合计（非独立样本）|2022|bear|entry|402|402|208|0|194|192|0|210|
|原33账户合计（非独立样本）|2023|bull|opportunity|384|323|245|0|139|232|0|152|
|原33账户合计（非独立样本）|2023|bull|entry|323|323|227|0|96|202|0|121|
|原33账户合计（非独立样本）|2023|bear|opportunity|357|357|210|0|147|213|0|144|
|原33账户合计（非独立样本）|2023|bear|entry|357|357|210|0|147|213|0|144|
|原33账户合计（非独立样本）|2024|bull|opportunity|522|339|193|1|328|242|0|280|
|原33账户合计（非独立样本）|2024|bull|entry|339|339|153|1|185|190|0|149|
|原33账户合计（非独立样本）|2024|bear|opportunity|342|335|98|2|242|113|2|227|
|原33账户合计（非独立样本）|2024|bear|entry|335|335|97|2|236|112|2|221|
|原33账户合计（非独立样本）|2025|bull|opportunity|256|180|151|0|105|157|0|99|
|原33账户合计（非独立样本）|2025|bull|entry|180|180|98|0|82|104|0|76|
|原33账户合计（非独立样本）|2025|bear|opportunity|185|185|80|0|105|54|0|131|
|原33账户合计（非独立样本）|2025|bear|entry|185|185|80|0|105|54|0|131|
|原33账户合计（非独立样本）|2026|bull|opportunity|226|123|112|0|114|100|0|126|
|原33账户合计（非独立样本）|2026|bull|entry|123|123|45|0|78|56|0|67|
|原33账户合计（非独立样本）|2026|bear|opportunity|68|68|1|0|67|1|0|67|
|原33账户合计（非独立样本）|2026|bear|entry|68|68|1|0|67|1|0|67|
|MEAN|ALL|bull|opportunity|78|56|36|1|41|36|0|42|
|MEAN|ALL|bull|entry|56|56|25|1|30|26|0|30|
|MEAN|ALL|bear|opportunity|68|68|29|0|39|28|2|38|
|MEAN|ALL|bear|entry|68|68|29|0|39|28|2|38|
|MEAN|2019|bull|opportunity|1|1|1|0|0|1|0|0|
|MEAN|2019|bull|entry|1|1|1|0|0|1|0|0|
|MEAN|2019|bear|opportunity|0|0|0|0|0|0|0|0|
|MEAN|2019|bear|entry|0|0|0|0|0|0|0|0|
|MEAN|2020|bull|opportunity|10|5|5|0|5|4|0|6|
|MEAN|2020|bull|entry|5|5|1|0|4|1|0|4|
|MEAN|2020|bear|opportunity|9|9|2|0|7|2|1|6|
|MEAN|2020|bear|entry|9|9|2|0|7|2|1|6|
|MEAN|2021|bull|opportunity|7|5|3|0|4|5|0|2|
|MEAN|2021|bull|entry|5|5|2|0|3|4|0|1|
|MEAN|2021|bear|opportunity|6|6|2|0|4|2|0|4|
|MEAN|2021|bear|entry|6|6|2|0|4|2|0|4|
|MEAN|2022|bull|opportunity|19|16|10|1|8|8|0|11|
|MEAN|2022|bull|entry|16|16|9|1|6|7|0|9|
|MEAN|2022|bear|opportunity|15|15|8|0|7|7|0|8|
|MEAN|2022|bear|entry|15|15|8|0|7|7|0|8|
|MEAN|2023|bull|opportunity|12|11|6|0|6|7|0|5|
|MEAN|2023|bull|entry|11|11|6|0|5|6|0|5|
|MEAN|2023|bear|opportunity|10|10|5|0|5|5|0|5|
|MEAN|2023|bear|entry|10|10|5|0|5|5|0|5|
|MEAN|2024|bull|opportunity|13|9|5|0|8|5|0|8|
|MEAN|2024|bull|entry|9|9|4|0|5|4|0|5|
|MEAN|2024|bear|opportunity|15|15|6|0|9|6|1|8|
|MEAN|2024|bear|entry|15|15|6|0|9|6|1|8|
|MEAN|2025|bull|opportunity|8|5|4|0|4|5|0|3|
|MEAN|2025|bull|entry|5|5|2|0|3|3|0|2|
|MEAN|2025|bear|opportunity|6|6|2|0|4|2|0|4|
|MEAN|2025|bear|entry|6|6|2|0|4|2|0|4|
|MEAN|2026|bull|opportunity|8|4|2|0|6|1|0|7|
|MEAN|2026|bull|entry|4|4|0|0|4|0|0|4|
|MEAN|2026|bear|opportunity|7|7|4|0|3|4|0|3|
|MEAN|2026|bear|entry|7|7|4|0|3|4|0|3|
|BODY|ALL|bull|opportunity|78|56|36|1|41|36|0|42|
|BODY|ALL|bull|entry|53|53|25|0|28|26|0|27|
|BODY|ALL|bear|opportunity|69|69|29|0|40|29|2|38|
|BODY|ALL|bear|entry|69|69|29|0|40|29|2|38|
|BODY|2019|bull|opportunity|1|1|1|0|0|1|0|0|
|BODY|2019|bull|entry|1|1|1|0|0|1|0|0|
|BODY|2019|bear|opportunity|0|0|0|0|0|0|0|0|
|BODY|2019|bear|entry|0|0|0|0|0|0|0|0|
|BODY|2020|bull|opportunity|10|5|5|0|5|4|0|6|
|BODY|2020|bull|entry|5|5|1|0|4|1|0|4|
|BODY|2020|bear|opportunity|9|9|2|0|7|2|1|6|
|BODY|2020|bear|entry|9|9|2|0|7|2|1|6|
|BODY|2021|bull|opportunity|7|5|3|0|4|5|0|2|
|BODY|2021|bull|entry|5|5|2|0|3|4|0|1|
|BODY|2021|bear|opportunity|6|6|2|0|4|2|0|4|
|BODY|2021|bear|entry|6|6|2|0|4|2|0|4|
|BODY|2022|bull|opportunity|19|16|10|1|8|8|0|11|
|BODY|2022|bull|entry|14|14|9|0|5|7|0|7|
|BODY|2022|bear|opportunity|16|16|8|0|8|8|0|8|
|BODY|2022|bear|entry|16|16|8|0|8|8|0|8|
|BODY|2023|bull|opportunity|12|11|6|0|6|7|0|5|
|BODY|2023|bull|entry|10|10|6|0|4|6|0|4|
|BODY|2023|bear|opportunity|10|10|5|0|5|5|0|5|
|BODY|2023|bear|entry|10|10|5|0|5|5|0|5|
|BODY|2024|bull|opportunity|13|9|5|0|8|5|0|8|
|BODY|2024|bull|entry|9|9|4|0|5|4|0|5|
|BODY|2024|bear|opportunity|15|15|6|0|9|6|1|8|
|BODY|2024|bear|entry|15|15|6|0|9|6|1|8|
|BODY|2025|bull|opportunity|8|5|4|0|4|5|0|3|
|BODY|2025|bull|entry|5|5|2|0|3|3|0|2|
|BODY|2025|bear|opportunity|6|6|2|0|4|2|0|4|
|BODY|2025|bear|entry|6|6|2|0|4|2|0|4|
|BODY|2026|bull|opportunity|8|4|2|0|6|1|0|7|
|BODY|2026|bull|entry|4|4|0|0|4|0|0|4|
|BODY|2026|bear|opportunity|7|7|4|0|3|4|0|3|
|BODY|2026|bear|entry|7|7|4|0|3|4|0|3|

原中心下跌路线57次原生买入全部通过原确认，但较前收上涨仅23次、收高于开盘仅22次。原确认通过不等于价格反弹已经开始。

原33账户合计2014次下跌买入中，较前收上涨765次、收高于开盘769次；这些账户共享一条市场路径，不能当作独立样本。均值居中与BODY背景独立单列，全部年份和等号保留。

原中心2023下跌买入10次，两个方向门各只保留原路径6次；2024为10次中的3次或2次。方向门覆盖面大，可能显著改变交易次数和恢复反弹机会，不能按被删旧交易盈亏预测新收益。

EX037/38六个风险退出中心均不满足原四项要求，停止继续调退出宽度。既有方向实验主要限制上涨路线；此次拟议所有下跌空仓资格机会上的门不存在精确重复账户。诊断只形成机制线索，没有证明收益或参数敏感性改善。

EX040采用四个最小完整账户对照：原始或均值居中下跌自相关背景，各加Close>前收或Close>Open入场门。保留原确认、全部持仓退出、13维完整数值中心与域和四经济门，精确复用两旧背景；不添加BODY上涨门、风险退出或日期例外。四新业务配置五实际评价；仅原四门达标新中心进入同原32点完整域扰动比较，原EX01532精确复用。全部失败完整账户保留；无逐轮审批或正式阶段推进。

这些是原路径的谓词计数，不是删除交易后的盈利预测。拒绝一次买入会改变以后持仓、退出、机会和成交，不能把被拒绝交易的盈亏相加当作新账户结果。机会年按信号日期分组，经济年度仍按实际执行日期。原始全部35账户每日信息、方向交叉计数和身份/账本审计保留在正式诊断中。

最强已有反证：原策略112笔闭合交易，仅比最低110笔多两笔；2023收益仅+0.2841%。此前所有上涨路线价格门降至97/99笔，转换日价格门也曾降至108/109笔。限制买入可能损害交易次数或删掉后续恢复机会。均值居中背景虽123笔，仍不满足2024年度回撤。本轮计数不能推断下跌门会解决这些问题。

反复使用同一已见开发池具有选择偏差，不是独立验证或未来保证。FULL只核验声明证据完整性，不证明经济达标或参数改善。本轮诊断已完成，总体参数敏感性改善目标仍未达成。未推进正式阶段四、冻结、PTE或生产。

## 正式证据引用

- [center](../../../assets/deliveries/CANDIDATES/35/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-TIME-P00](../../../assets/deliveries/CANDIDATES/35/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01](../../../assets/deliveries/CANDIDATES/35/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02](../../../assets/deliveries/CANDIDATES/35/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03](../../../assets/deliveries/CANDIDATES/35/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04](../../../assets/deliveries/CANDIDATES/35/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05](../../../assets/deliveries/CANDIDATES/35/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06](../../../assets/deliveries/CANDIDATES/35/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07](../../../assets/deliveries/CANDIDATES/35/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08](../../../assets/deliveries/CANDIDATES/35/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09](../../../assets/deliveries/CANDIDATES/35/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10](../../../assets/deliveries/CANDIDATES/35/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11](../../../assets/deliveries/CANDIDATES/35/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12](../../../assets/deliveries/CANDIDATES/35/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13](../../../assets/deliveries/CANDIDATES/35/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14](../../../assets/deliveries/CANDIDATES/35/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15](../../../assets/deliveries/CANDIDATES/35/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16](../../../assets/deliveries/CANDIDATES/35/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17](../../../assets/deliveries/CANDIDATES/35/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18](../../../assets/deliveries/CANDIDATES/35/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19](../../../assets/deliveries/CANDIDATES/35/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20](../../../assets/deliveries/CANDIDATES/35/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21](../../../assets/deliveries/CANDIDATES/35/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22](../../../assets/deliveries/CANDIDATES/35/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23](../../../assets/deliveries/CANDIDATES/35/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24](../../../assets/deliveries/CANDIDATES/35/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25](../../../assets/deliveries/CANDIDATES/35/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26](../../../assets/deliveries/CANDIDATES/35/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27](../../../assets/deliveries/CANDIDATES/35/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28](../../../assets/deliveries/CANDIDATES/35/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29](../../../assets/deliveries/CANDIDATES/35/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30](../../../assets/deliveries/CANDIDATES/35/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31](../../../assets/deliveries/CANDIDATES/35/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [MEAN](../../../assets/deliveries/CANDIDATES/35/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [BODY](../../../assets/deliveries/CANDIDATES/35/evidence/976de84cea65318f55203724ee8a7b2c5b4fa0805be1bfb9587b85927773db30.json)
- [plan](../../../assets/deliveries/CANDIDATES/35/evidence/fad98eb5aba8f0e76cb001904f96333c5a87c52ce7c4879987918f40f58d6b45.json)
- [method](../../../assets/deliveries/CANDIDATES/35/evidence/db16af593518be750aa4eb6b2fee1407d73b180ee882739ba9a1e4d0b5524a5b.json)
- [input-original33](../../../assets/deliveries/CANDIDATES/35/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [input-mean_center](../../../assets/deliveries/CANDIDATES/35/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [input-body_center](../../../assets/deliveries/CANDIDATES/35/evidence/976de84cea65318f55203724ee8a7b2c5b4fa0805be1bfb9587b85927773db30.json)
- [native-direction](../../../assets/deliveries/CANDIDATES/35/evidence/4c34f10a3e0ce2880b9e4189399e94f49f3601a97580ef42aff168b9c19a1a1a.json)
- [focused-checks](../../../assets/deliveries/CANDIDATES/35/evidence/fa5c05df5a6fef429f4eb8d96376774e1679a74351c49cdef258fae10dc752f0.json)
- [research-decision](../../../assets/deliveries/CANDIDATES/35/evidence/d10fd808bf19dea63aa30dcc05aa26e3ec1ad29ccfbdeb2b24fe6e2bcc92d821.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/35/evidence/7c326df880953bd4251cac56d2d62e1fdcdcc25088be67caa639af209ddf8210.json)
