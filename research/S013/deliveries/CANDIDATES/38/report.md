# S013：下跌定时退出的信号价格状态与真实资金路径

RSCH阶段三。用户已授权自主完成研究，无需逐轮评审。原S013数据固定2020-01-02至2026-09-30，四项经济目标与13维完整数值域保持。本轮零新增完整账户，精确复用原C2132中心及32个参数邻点、MEAN/BODY旧背景和EX041两个新方向门的既有账户，共37个不同原生账户、60,532行信号及实际执行日。原33账户共享同一市场路径，不能视为33个独立样本；四个额外中心分别报告。

## 为什么先诊断

EX041把严格价格确认缩小到下跌TIME退出后的再次买入，两配置116笔足够，却均使2023亏损约1.25%。不能把信号入场价以下的退出直接视为应阻止再次买回的理由。EX016已经研究过信号相对入场价：排除退出当日raw路由变化并去重的2023负组30事件随后3日均上涨0.3690%，正组36事件下跌0.1261%，10日方向又改变。这些重叠事件的未来窗口统计是反证，不能挑窗或替代新策略现金路径。本轮不计算新的未来观察窗。

S013源码/协议重复核查没有发现完全相同的“仅低于锚点的bear TIME退出后对再次买入加方向门”结构；EX041未分退出价类别，EX016按价格状态改变是否TIME退出。结构不同并不证明有效，完整新账户仍是必要证据。

## 事前固定的描述方法

入场锚点是该账户本次信号入场T的HFQ Close。每次持仓信号退出记录退出前active_route与最终原因；仅bear TIME退出按当时Close严格低于/等于/高于锚点分为BELOW/EQUAL/ABOVE。其他退出和初始状态为NONE。没有新增幅度、容差、年份例外或数值门槛。空仓拒绝、资格失败、raw路由变化保留退出上下文；任意路线成功信号入场清除当前上下文，并为持仓保存其入场来源上下文。

全部退出、后续bear资格机会、任意路线再次入场、方向拒绝、未再次入场和末尾持仓保留。机会年份按信号T，实际资金年份按T+1执行日期，2019末信号与2020首执行分别保留。退出当日raw路由已变的bear TIME也保留。全部日期、类别、自然年和空组完整展示。

37账户的原生序列化证据、候选/实现/依赖/绑定/参数/lineage身份、全部信号特征与状态、公共日历1636对T→T+1、实际现金/数量/价格/费用及五基准账本核对。资金有两套完整分组：按当日信号前退出上下文；按实际cycle首次BUY的decision_id对应的信号持仓来源。每笔fill保存自身来源及不一致计数，逐日按真实库存、成交价格、费用重建净权益变化，两套分组均对回全年和全窗原账户。OPEN尾仓和跨年cycle完整保留，跨年整笔PnL不是年度收益。

## 中心账户的全部类别

BELOW/ABOVE简称信号价格低于/高于入场锚点，与实际净亏损/净盈利不同。以下为既有路径计数，不能当作新增门的收益。

|账户|类别|bear TIME退出|随后bear资格机会|该类别bear信号入场|机会Close>前收|机会Close>Open|方向拒绝|
|---|---|---:|---:|---:|---:|---:|---:|
|center|BELOW|17|13|13|6|7|0|
|center|EQUAL|0|0|0|0|0|0|
|center|ABOVE|21|18|18|11|9|0|
|center|NONE|0|26|26|6|6|0|
|MEAN|BELOW|23|19|19|11|13|0|
|MEAN|EQUAL|0|0|0|0|0|0|
|MEAN|ABOVE|23|20|20|10|7|0|
|MEAN|NONE|0|29|29|8|8|0|
|BODY|BELOW|23|19|19|11|13|1|
|BODY|EQUAL|0|0|0|0|0|0|
|BODY|ABOVE|23|20|20|10|7|1|
|BODY|NONE|0|30|30|8|9|2|
|TIME_CLOSE|BELOW|22|29|17|17|19|12|
|TIME_CLOSE|EQUAL|0|0|0|0|0|0|
|TIME_CLOSE|ABOVE|18|36|17|17|15|19|
|TIME_CLOSE|NONE|0|27|27|8|8|0|
|TIME_BODY|BELOW|20|26|17|16|17|9|
|TIME_BODY|EQUAL|0|0|0|0|0|0|
|TIME_BODY|ABOVE|19|37|17|18|17|20|
|TIME_BODY|NONE|0|27|27|8|8|0|

## 全部自然年的真实资金分解

以下按实际持仓入场来源分组，各类别净权益变化除以该年真实期初权益；四组贡献之和严格等于当年账户收益。这是已有政策的会计分解，删除某组交易不会得到表中其他组组成的新收益。NONE包含其他信号来源。

|账户|执行年|实际年度收益|BELOW贡献|EQUAL贡献|ABOVE贡献|NONE贡献|
|---|---:|---:|---:|---:|---:|---:|
|center|2020|+16.7355%|+2.6542%|+0.0000%|+3.0710%|+11.0102%|
|center|2021|+9.9101%|+2.2925%|+0.0000%|+0.3619%|+7.2557%|
|center|2022|+12.1687%|+4.2826%|+0.0000%|-5.2244%|+13.1105%|
|center|2023|+0.2841%|+2.3049%|+0.0000%|+1.3924%|-3.4132%|
|center|2024|+64.9989%|-0.6316%|+0.0000%|+5.2936%|+60.3369%|
|center|2025|+11.0774%|+1.4959%|+0.0000%|+4.6542%|+4.9273%|
|center|2026|-0.0384%|+0.0000%|+0.0000%|+2.6687%|-2.7071%|
|MEAN|2020|+17.3786%|+2.0156%|+0.0000%|+2.3471%|+13.0159%|
|MEAN|2021|+12.0902%|+2.7064%|+0.0000%|+1.2816%|+8.1021%|
|MEAN|2022|+11.4638%|-0.9734%|+0.0000%|+2.9452%|+9.4920%|
|MEAN|2023|+0.5481%|+0.7018%|+0.0000%|+2.9025%|-3.0562%|
|MEAN|2024|+50.4429%|+33.6747%|+0.0000%|-4.7993%|+21.5675%|
|MEAN|2025|+10.7206%|+1.4958%|+0.0000%|+4.5102%|+4.7146%|
|MEAN|2026|-7.1506%|-0.1614%|+0.0000%|+0.0000%|-6.9892%|
|BODY|2020|+17.3786%|+2.0156%|+0.0000%|+2.3471%|+13.0159%|
|BODY|2021|+12.0902%|+2.7064%|+0.0000%|+1.2816%|+8.1021%|
|BODY|2022|+12.8492%|-0.9717%|+0.0000%|+2.9840%|+10.8369%|
|BODY|2023|+1.4978%|+0.7002%|+0.0000%|+2.9020%|-2.1044%|
|BODY|2024|+50.4465%|+33.6749%|+0.0000%|-4.7986%|+21.5702%|
|BODY|2025|+10.7211%|+1.4956%|+0.0000%|+4.5105%|+4.7149%|
|BODY|2026|-7.1525%|-0.1614%|+0.0000%|+0.0000%|-6.9911%|
|TIME_CLOSE|2020|+18.2050%|+0.6467%|+0.0000%|+3.1265%|+14.4318%|
|TIME_CLOSE|2021|+10.6278%|+2.7073%|+0.0000%|-0.0898%|+8.0103%|
|TIME_CLOSE|2022|+8.4479%|-2.7854%|+0.0000%|+2.1500%|+9.0833%|
|TIME_CLOSE|2023|-1.2487%|+0.7154%|+0.0000%|+1.0352%|-2.9993%|
|TIME_CLOSE|2024|+44.0969%|+24.0542%|+0.0000%|-0.3229%|+20.3656%|
|TIME_CLOSE|2025|+10.6862%|+3.8224%|+0.0000%|+2.7413%|+4.1224%|
|TIME_CLOSE|2026|-5.7231%|-0.9841%|+0.0000%|-4.3130%|-0.4259%|
|TIME_BODY|2020|+18.2050%|+0.6467%|+0.0000%|+3.1265%|+14.4318%|
|TIME_BODY|2021|+10.6278%|+2.7073%|+0.0000%|-0.0898%|+8.0103%|
|TIME_BODY|2022|+12.9032%|+4.0053%|+0.0000%|-0.5370%|+9.4349%|
|TIME_BODY|2023|-1.2500%|+0.7151%|+0.0000%|+1.0352%|-3.0004%|
|TIME_BODY|2024|+53.2144%|+34.5169%|+0.0000%|-6.1799%|+24.8773%|
|TIME_BODY|2025|+5.5924%|+1.4957%|+0.0000%|+0.2600%|+3.8367%|
|TIME_BODY|2026|-5.7252%|-0.9853%|+0.0000%|-4.3144%|-0.4255%|

## 原33账户的覆盖与局限

原33路径的bear TIME类别合计为{'BELOW': 659, 'EQUAL': 0, 'ABOVE': 721, 'NONE': 0}；这是同市场参数扰动路径的计数，不是独立事件样本或统计显著性。全部37账户的60,532行、每账户全年度两套资金分解及全部实际周期均在native-anchors正式证据中保留。

实际BUY fill来源与cycle首次来源不一致合计0，逐账户与逐fill明示，没有静默重写来源。

## 研究判断与下一步

37个不同既有完整账户及60532行信号/执行日核对通过；所有类别、自然年、尾仓和日期保留。原33条路径共享市场，不是33个独立样本。两套资金分组均精确回到真实账户，逐fill来源不一致为0。

“低于入场价定时退出后再次买入就是坏交易”受到实际资金反证：原中心2023该来源贡献+2.3049个百分点，高于价退出来源+1.3924个百分点，其他来源-3.4132个百分点，全年仅+0.2841%。MEAN与BODY背景2023的低于价来源仍贡献约+0.7018/+0.7002个百分点。直接按亏损退出禁买可能删除恢复收益。

分类效果不能跨年份或背景概括：2024原中心低于价来源-0.6316个百分点，而MEAN/BODY同类分别+33.6747/+33.6749个百分点；高于价来源则在MEAN/BODY为负。这些是既有账户的真实年度会计分解，不是删掉该组后的新策略收益。

EX041两个针对所有bear TIME再次入场的方向门使2023分别-1.2487%/-1.2500%，虽然各116闭合交易，仍未达到原四项经济目标。方向门后的类别路径本身变化，因此不能用旧组收益相减预测新规则，也不能把较小回撤当作达标。

原C2132参数敏感性证据与13维32点比较标准保持。零新账户诊断未验证任何改进策略，技术PASS/FULL只证明证据完整。总目标尚未达成。

下一轮最小机制对照采用MEAN背景，保留原买入score与所有持仓退出/H，运行4个新中心：方向门分别仅用于上一次最终bear TIME退出价格严格BELOW或严格ABOVE自身信号入场锚点，CLOSE/BODY各2。EQUAL/NONE沿原规则，任意路线成功入场消耗上下文；空仓拒绝/资格失败/raw变化保留。同时保留MEAN及EX041两方向门完整旧对照。两种价格状态都测试，不预设亏损组有害，无新幅度/容差/年份例外。冻结规则/纯检查/绑定/preflight后才执行；中心满足原4经济目标才运行原13维完整域32点，绝对尾部与中心相对退化均改善才可宣称目标达成。

## 技术修正与验证边界

原诊断在account.date的微秒与valid_session集合的秒精度比较失败，原冻结源码和失败完整保留。显式v2仅一行比较将两侧时间单位转为ns后仍严格比较全部日期值、顺序和数量；其余状态/锚点/类别/统计函数AST完全相同。9种秒/微秒/纳秒组合通过，改日与缺日拒绝，原10项非法状态/价格/资金检查保留。完整37既有账户核对使用v2，零新增或重跑完整账户。

诊断不新增经济硬门，不证明新规则收益或独立验证。FULL仅证据完整性。总参数敏感性改善目标仍未达成；未推进正式阶段四、冻结、PTE或生产。

## 正式证据引用

- [center](../../../assets/deliveries/CANDIDATES/38/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-TIME-P00](../../../assets/deliveries/CANDIDATES/38/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01](../../../assets/deliveries/CANDIDATES/38/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02](../../../assets/deliveries/CANDIDATES/38/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03](../../../assets/deliveries/CANDIDATES/38/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04](../../../assets/deliveries/CANDIDATES/38/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05](../../../assets/deliveries/CANDIDATES/38/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06](../../../assets/deliveries/CANDIDATES/38/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07](../../../assets/deliveries/CANDIDATES/38/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08](../../../assets/deliveries/CANDIDATES/38/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09](../../../assets/deliveries/CANDIDATES/38/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10](../../../assets/deliveries/CANDIDATES/38/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11](../../../assets/deliveries/CANDIDATES/38/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12](../../../assets/deliveries/CANDIDATES/38/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13](../../../assets/deliveries/CANDIDATES/38/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14](../../../assets/deliveries/CANDIDATES/38/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15](../../../assets/deliveries/CANDIDATES/38/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16](../../../assets/deliveries/CANDIDATES/38/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17](../../../assets/deliveries/CANDIDATES/38/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18](../../../assets/deliveries/CANDIDATES/38/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19](../../../assets/deliveries/CANDIDATES/38/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20](../../../assets/deliveries/CANDIDATES/38/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21](../../../assets/deliveries/CANDIDATES/38/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22](../../../assets/deliveries/CANDIDATES/38/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23](../../../assets/deliveries/CANDIDATES/38/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24](../../../assets/deliveries/CANDIDATES/38/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25](../../../assets/deliveries/CANDIDATES/38/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26](../../../assets/deliveries/CANDIDATES/38/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27](../../../assets/deliveries/CANDIDATES/38/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28](../../../assets/deliveries/CANDIDATES/38/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29](../../../assets/deliveries/CANDIDATES/38/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30](../../../assets/deliveries/CANDIDATES/38/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31](../../../assets/deliveries/CANDIDATES/38/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [MEAN](../../../assets/deliveries/CANDIDATES/38/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [BODY](../../../assets/deliveries/CANDIDATES/38/evidence/976de84cea65318f55203724ee8a7b2c5b4fa0805be1bfb9587b85927773db30.json)
- [TIME_CLOSE](../../../assets/deliveries/CANDIDATES/38/evidence/225c77a01b03d8e3858f790a935f971d3ccec5ec9c4d8a7fcd626aeda95217c6.json)
- [TIME_BODY](../../../assets/deliveries/CANDIDATES/38/evidence/65a233dafec5ebb2ee2ffcfbf00fad9530245ab1b35d9efed6125eeb799edc4a.json)
- [plan](../../../assets/deliveries/CANDIDATES/38/evidence/a87651231d88073928ffa03c8e136cbccd04ce421dd83eb906c845bd9645b2ee.json)
- [method](../../../assets/deliveries/CANDIDATES/38/evidence/b34e58be12cfc603bc8c52be0cfc2b9388c7d204fdd3e6ba4916d6ccd77ea9c3.json)
- [input-original33](../../../assets/deliveries/CANDIDATES/38/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [input-mean_center](../../../assets/deliveries/CANDIDATES/38/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [input-body_center](../../../assets/deliveries/CANDIDATES/38/evidence/976de84cea65318f55203724ee8a7b2c5b4fa0805be1bfb9587b85927773db30.json)
- [input-time_close](../../../assets/deliveries/CANDIDATES/38/evidence/225c77a01b03d8e3858f790a935f971d3ccec5ec9c4d8a7fcd626aeda95217c6.json)
- [input-time_body](../../../assets/deliveries/CANDIDATES/38/evidence/65a233dafec5ebb2ee2ffcfbf00fad9530245ab1b35d9efed6125eeb799edc4a.json)
- [prior-anchor-counterevidence](../../../assets/deliveries/CANDIDATES/38/evidence/26dad0baf35054808dca919a74d7537f2858de04f21b303c432c7b8c13a53135.json)
- [original-diagnostic-failure](../../../assets/deliveries/CANDIDATES/38/evidence/8830d65c270d9c95b189b7991a488a2054a1734f7a3c21fbc6b3af4fcc9a901a.json)
- [focused-date-correction](../../../assets/deliveries/CANDIDATES/38/evidence/9be6a7d525ae493f04e718d7555f609bf316b95026b4f60a8c54b999b51b937b.json)
- [explicit-technical-correction](../../../assets/deliveries/CANDIDATES/38/evidence/ccb5a2ee33a6471e043f1af036aa1e16effe91d47c3a2bd01fbff0ddb76fc701.json)
- [native-anchors](../../../assets/deliveries/CANDIDATES/38/evidence/8902444f3a11c4764fc1b379ba49d3110f843e00112c236719108697b69c27a3.json)
- [focused-checks](../../../assets/deliveries/CANDIDATES/38/evidence/941e5a67b7c890a2fbe5fb7f0d162bf7a98981dbd949a558284e3db918d40e16.json)
- [focused-checks-v2](../../../assets/deliveries/CANDIDATES/38/evidence/488b17de067a096a6044a66ed53e661105f20f3dc44d29a8eb67e4468b603eed.json)
- [source-checks](../../../assets/deliveries/CANDIDATES/38/evidence/2faf4813e6e6128f97dffd1026fe693cb18573fb17dbf32165d3e4935cf7bdf3.json)
- [research-decision](../../../assets/deliveries/CANDIDATES/38/evidence/a081e8c9163c9041d3fb54e0cf98aa7cb55fe518c93227f650ba199b556e5838.json)
- [research-conclusion](../../../assets/deliveries/CANDIDATES/38/evidence/0f7200fcda5042934f9dbd37166823e959fb9a0dcf60e0466bfa0fc5e13f6f3f.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/38/evidence/23d8508ed5205b62684687e4e118062f5157e911804d126f8609f492654c4259.json)
