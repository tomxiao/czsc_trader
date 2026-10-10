# S013：按定时退出价格状态区分再次买入的最小机制对照

RSCH阶段三，用户授权自主完成研究，无需逐轮评审。S013既有510500.SH数据固定2020-01-02至2026-09-30共1636交易日、100万元、HFQ信号、整手100、T决策/T+1执行、单边0.1%费用、策略及可执行LimitBuyHold统一1%限买溢价。

原四项经济目标不变：年化至少正基准1.5倍；每自然年回撤严格低于基准；每60日不少于4笔闭合交易（本窗至少110笔）；基准亏损年2022/2023连续账户收益为正。全窗回撤用于诊断，不能替代年度门。

EX042以37个既有完整账户核对退出价格状态及真实资金。原中心2023低于入场价TIME退出后再次入场的持仓来源贡献+2.3049个百分点；MEAN/BODY2024同类贡献约+33.6747/+33.6749个百分点。亏着退出不意味着再次买入有害。EX041对所有下跌TIME再次入场加方向门的两个完整账户均使2023约-1.25%。这些是事前已见反证，不是本轮独立验证，旧组PnL不能相减预测新收益。

本轮MEAN背景四配置：N0/N1仅在上一次最终bear TIME退出Close严格低于自身信号入场Close锚点时，分别要求本T Close>前一日Close或Close>本日Open；N2/N3仅在严格高于锚点时加相同门。EQUAL/NONE/非选中类别沿原MEAN入场。只在原空仓资格合格rawbear机会门控，方向拒绝先于原score。每次bear TIME最终出口分类，其他出口记录None；任意路线成功信号entry消耗并清空reason/route/category，空仓失败/raw变化保留。分类描述信号价格，不能当作实际净盈亏。

原买入确认、全部持仓退出优先级与H8/H4信号日保持，13个原数值坐标及完整域仍有效。MEAN保持原严格过去L均值居中ACF及L+21预热。没有新幅度/容差/未来观察窗/年份例外。四个类别范围与方向选择是13数值域之外的新固定结构，本轮未证明类别选择本身稳定。

四新业务配置、五实际完整评价（N0串行/spawn严格一致），四旧完整账户精确复用。每个新配置全1636行由不导入SRT的独立公式/状态重建核对，日期沿原41v2绑定公共日历保持全部T至T+1及末端。八账户信号/原生身份/真实数量/现金/价格/费用独立核对，五基准账本严格一致，所有失败账户、自然年及尾仓保留。

|账户|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
|B0-TIME|C2132|16.1572%|14.1599%|112|+12.1687%|+0.2841%|通过|
|B0-MEAN|C8701|13.5405%|23.9087%|123|+11.4638%|+0.5481%|annual_drawdown|
|B0-TIME-CLOSE|C4800|12.1547%|16.5875%|116|+8.4479%|-1.2487%|negative_buyhold_year_profit|
|B0-TIME-BODY|C4801|13.0995%|22.8325%|116|+12.9032%|-1.2500%|annual_drawdown、negative_buyhold_year_profit|
|N0|C4900|10.8889%|21.2540%|119|+9.4200%|+0.5491%|通过|
|N1|C4901|13.8928%|22.6858%|119|+13.9067%|+0.5491%|annual_drawdown|
|N2|C4902|14.3524%|20.1952%|120|+9.0663%|-1.2506%|negative_buyhold_year_profit|
|N3|C4903|12.9424%|24.8786%|120|+9.0663%|-1.2506%|annual_drawdown、negative_buyhold_year_profit|

|账户|自然年|收益|回撤|基准回撤|年度回撤门|
|---|---:|---:|---:|---:|---|
|B0-TIME|2020|+16.7355%|6.1272%|14.9712%|通过|
|B0-TIME|2021|+9.9101%|2.7008%|9.7035%|通过|
|B0-TIME|2022|+12.1687%|9.7680%|28.4105%|通过|
|B0-TIME|2023|+0.2841%|5.6722%|17.2665%|通过|
|B0-TIME|2024|+64.9989%|10.0213%|18.5736%|通过|
|B0-TIME|2025|+11.0774%|3.5332%|13.7975%|通过|
|B0-TIME|2026|-0.0384%|4.5425%|18.7646%|通过|
|B0-MEAN|2020|+17.3786%|6.1272%|14.9712%|通过|
|B0-MEAN|2021|+12.0902%|2.2401%|9.7035%|通过|
|B0-MEAN|2022|+11.4638%|12.9741%|28.4105%|通过|
|B0-MEAN|2023|+0.5481%|6.7438%|17.2665%|通过|
|B0-MEAN|2024|+50.4429%|19.7899%|18.5736%|未通过|
|B0-MEAN|2025|+10.7206%|3.5336%|13.7975%|通过|
|B0-MEAN|2026|-7.1506%|10.1152%|18.7646%|通过|
|B0-TIME-CLOSE|2020|+18.2050%|6.1272%|14.9712%|通过|
|B0-TIME-CLOSE|2021|+10.6278%|2.6939%|9.7035%|通过|
|B0-TIME-CLOSE|2022|+8.4479%|12.3203%|28.4105%|通过|
|B0-TIME-CLOSE|2023|-1.2487%|6.7412%|17.2665%|通过|
|B0-TIME-CLOSE|2024|+44.0969%|11.8362%|18.5736%|通过|
|B0-TIME-CLOSE|2025|+10.6862%|2.2390%|13.7975%|通过|
|B0-TIME-CLOSE|2026|-5.7231%|8.3093%|18.7646%|通过|
|B0-TIME-BODY|2020|+18.2050%|6.1272%|14.9712%|通过|
|B0-TIME-BODY|2021|+10.6278%|2.6939%|9.7035%|通过|
|B0-TIME-BODY|2022|+12.9032%|11.2403%|28.4105%|通过|
|B0-TIME-BODY|2023|-1.2500%|6.7426%|17.2665%|通过|
|B0-TIME-BODY|2024|+53.2144%|19.8148%|18.5736%|未通过|
|B0-TIME-BODY|2025|+5.5924%|3.5334%|13.7975%|通过|
|B0-TIME-BODY|2026|-5.7252%|8.3108%|18.7646%|通过|
|N0|2020|+18.2050%|6.1272%|14.9712%|通过|
|N0|2021|+12.0899%|2.2407%|9.7035%|通过|
|N0|2022|+9.4200%|12.3185%|28.4105%|通过|
|N0|2023|+0.5491%|6.7421%|17.2665%|通过|
|N0|2024|+32.7842%|18.3070%|18.5736%|通过|
|N0|2025|+9.7887%|2.2391%|13.7975%|通过|
|N0|2026|-7.9477%|10.8864%|18.7646%|通过|
|N1|2020|+18.2050%|6.1272%|14.9712%|通过|
|N1|2021|+12.0899%|2.2407%|9.7035%|通过|
|N1|2022|+13.9067%|11.2419%|28.4105%|通过|
|N1|2023|+0.5491%|6.7424%|17.2665%|通过|
|N1|2024|+50.4473%|19.7928%|18.5736%|未通过|
|N1|2025|+10.7222%|3.5332%|13.7975%|通过|
|N1|2026|-7.9489%|10.8874%|18.7646%|通过|
|N2|2020|+20.2317%|6.1272%|14.9712%|通过|
|N2|2021|+10.6256%|2.6933%|9.7035%|通过|
|N2|2022|+9.0663%|12.9735%|28.4105%|通过|
|N2|2023|-1.2506%|6.7425%|17.2665%|通过|
|N2|2024|+60.6726%|14.8142%|18.5736%|通过|
|N2|2025|+9.1292%|3.5332%|13.7975%|通过|
|N2|2026|-4.9069%|7.5166%|18.7646%|通过|
|N3|2020|+20.2317%|6.1272%|14.9712%|通过|
|N3|2021|+10.6256%|2.6933%|9.7035%|通过|
|N3|2022|+9.0663%|12.9735%|28.4105%|通过|
|N3|2023|-1.2506%|6.7425%|17.2665%|通过|
|N3|2024|+53.2050%|19.8135%|18.5736%|未通过|
|N3|2025|+5.5920%|3.5332%|13.7975%|通过|
|N3|2026|-4.9073%|7.5172%|18.7646%|通过|

|中心|收益Q10|回撤Q90|收益退化|回撤退化|邻点四门通过数|
|---|---:|---:|---:|---:|---:|
|B0-TIME|5.8974%|30.5044%|10.2598%|16.3446%|0/32|
|N0|1.7843%|34.6163%|9.1046%|13.3624%|0/32|

参数保持原13完整域、域宽归一总L2=.05、32点、seed13/PCG64、整数HALF_EVEN、LINEAR分位。中心满足四门且绝对尾部与相对退化同时改善才说明开发池实质改善；较弱中心造成退化缩小不算。邻点资格是诊断。原EX01532完整原生身份/计划/绑定/账户精确复用。

静态审查与合成复现发现原冻结汇总器尚未识别43四个机制，会错误拒绝新方向拒绝样本。原源/几何保留，显式v2仅新增类别条件、对应入口导入和完整三字段机制描述；其他资金/年度/四门函数AST保持。合成非法类别与拒绝优先级验证通过，全部新账户以v2独立核对；交易源码及原32点完整域未改，零账户重跑。

参数首批发布后，旧队列因共享列表令试验编号重复登记而失败，原代码/checkpoint/study/计划保留。首8点缓存与已正式发布证据逐一严格核对；v3固定原复用数量32并从8个已有结果恢复，零账户重跑，剩余24点照原计划执行。总计32新参数业务账户、33实际评价（2预检+7首批+24后续），不因失败删点/改点/改规则。

四个新完整中心独立核对通过。仅N0（MEAN背景、上次bear TIME退出价严格低于自身信号入场锚点的再次买入要求Close>前收）通过原四门：年化10.8889%、全窗回撤21.2540%、119笔，2022+9.4200%、2023+0.5491%，2024年度回撤18.3070%低于基准18.5736%。N1仍2024回撤未达标；N2/N3均2023约-1.2506%，N3还年度回撤未达标。不是所有方向确认都保护恢复。

唯一达标N0完整13维/32点的收益Q10=1.7843%、回撤Q90=34.6163%，原策略对应5.8974%/30.5044%。绝对两项均恶化，所以参数敏感性改善目标没有达成。邻点四门0/32是诊断，未另设资格 veto；本轮失败依据为原先固定的绝对尾部要求。

N0相对中心收益退化9.1046、回撤退化13.3624个百分点，看似小于原10.2598/16.3446。但N0中心本身比原中心年化低5.2683、全窗回撤高7.0941个百分点，导致相对退化机械缩小。绝对与相对必须同时改善的事前规则阻止了假稳健结论。

所有四中心、32新参数点、原四旧中心与32旧参数点完整保留。新增36业务/38实际完整评价（中心4/5、参数32/33），复用36个不同旧完整账户；首批调度故障从8个已保存/已正式发布参数结果精确恢复，零重跑、不改点。技术PASS与FULL仅证据核对，不证明新策略经济稳健。

结合EX042的真实资金反证，旧路径低于价退出后的再次入场并非一致有害；EX043新路径分类后的门可让中心达标，却仍让参数尾部更差。停止继续细分bear TIME退出价格方向门，不把“更谨慎买入”或旧交易分组作为改善证据。

总目标继续，下一步零新增完整账户。复用原中心及32点、新N0中心及32点共66条已审计完整原生路径，对照各自中心和同坐标点的完整信号、持仓前状态及首次分歧，分开记录当期数值触发差异、已有持仓/退出上下文的后续传播和两者并存；重点检查H整数跨日、ACF均值基准借用confirmation.lookback的耦合。全日期/自然年/类别及末尾保留，联合扰动关联不是单参数因果，状态分类不是删除交易后的利润。先冻结描述方法并复用旧正式证据，不再盲加价格确认门；原四目标、13完整域、绝对和相对共同改善标准保持。

已见开发池反复选择存在偏差，不是独立验证或未来保证。全路径差异是完整账户对照，不能用删掉旧交易的盈亏相加替代新利润。FULL只核验证据完整性。未推进正式阶段四、冻结、PTE或生产。

合成验证保持完整13维32坐标、全部类别及16种中心资格组合。原41v2仅缺失分类metadata在独立期望None位置允许None/浮点NaN等价，真实非空类别和所有经济字段严格核对。新last_exit_category沿同一明确缺失契约；无 blanket NaN修复或金融值替换。

源码静态检查覆盖全src，仅已冻结v3调度源的未使用optuna导入F401明示豁免以保留冻结字节；其他规则通过。未将此豁免视为经济或账户验证。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/39/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-MEAN](../../../assets/deliveries/CANDIDATES/39/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [B0-TIME-CLOSE](../../../assets/deliveries/CANDIDATES/39/evidence/225c77a01b03d8e3858f790a935f971d3ccec5ec9c4d8a7fcd626aeda95217c6.json)
- [B0-TIME-BODY](../../../assets/deliveries/CANDIDATES/39/evidence/65a233dafec5ebb2ee2ffcfbf00fad9530245ab1b35d9efed6125eeb799edc4a.json)
- [N0](../../../assets/deliveries/CANDIDATES/39/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N1](../../../assets/deliveries/CANDIDATES/39/evidence/bf339e0c9c6563a77b0e19d72b6bfee9f8355707c10ac4512e41bf93f136c2fc.json)
- [N2](../../../assets/deliveries/CANDIDATES/39/evidence/6cb74e4cb32b959f885c5c19cc22502efee272adde4d23be0e83825b4509558c.json)
- [N3](../../../assets/deliveries/CANDIDATES/39/evidence/869bc53f75539235e239f991f5e76afae90b6623a6284473215fefc49c260317.json)
- [B0-TIME-P00](../../../assets/deliveries/CANDIDATES/39/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01](../../../assets/deliveries/CANDIDATES/39/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02](../../../assets/deliveries/CANDIDATES/39/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03](../../../assets/deliveries/CANDIDATES/39/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04](../../../assets/deliveries/CANDIDATES/39/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05](../../../assets/deliveries/CANDIDATES/39/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06](../../../assets/deliveries/CANDIDATES/39/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07](../../../assets/deliveries/CANDIDATES/39/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08](../../../assets/deliveries/CANDIDATES/39/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09](../../../assets/deliveries/CANDIDATES/39/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10](../../../assets/deliveries/CANDIDATES/39/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11](../../../assets/deliveries/CANDIDATES/39/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12](../../../assets/deliveries/CANDIDATES/39/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13](../../../assets/deliveries/CANDIDATES/39/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14](../../../assets/deliveries/CANDIDATES/39/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15](../../../assets/deliveries/CANDIDATES/39/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16](../../../assets/deliveries/CANDIDATES/39/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17](../../../assets/deliveries/CANDIDATES/39/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18](../../../assets/deliveries/CANDIDATES/39/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19](../../../assets/deliveries/CANDIDATES/39/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20](../../../assets/deliveries/CANDIDATES/39/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21](../../../assets/deliveries/CANDIDATES/39/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22](../../../assets/deliveries/CANDIDATES/39/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23](../../../assets/deliveries/CANDIDATES/39/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24](../../../assets/deliveries/CANDIDATES/39/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25](../../../assets/deliveries/CANDIDATES/39/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26](../../../assets/deliveries/CANDIDATES/39/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27](../../../assets/deliveries/CANDIDATES/39/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28](../../../assets/deliveries/CANDIDATES/39/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29](../../../assets/deliveries/CANDIDATES/39/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30](../../../assets/deliveries/CANDIDATES/39/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31](../../../assets/deliveries/CANDIDATES/39/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [N0-P00](../../../assets/deliveries/CANDIDATES/39/evidence/8b52feb7089cffe70d9021197a45f309b8906fe343fd85120036a82cbf9c004c.json)
- [N0-P01](../../../assets/deliveries/CANDIDATES/39/evidence/cdd7dccfa0da7ae03b743a21e48a8aba760b0341f00e73f4e825e4ceb4c77080.json)
- [N0-P02](../../../assets/deliveries/CANDIDATES/39/evidence/9fad10754f615e5c41fb1a718fbe9a6c045ebd8ac463c0f23a72e10666e1fed2.json)
- [N0-P03](../../../assets/deliveries/CANDIDATES/39/evidence/00d30ba9690c9b92d17a628a50de0da836a1d7d106cff956ad88e2141f80cb6e.json)
- [N0-P04](../../../assets/deliveries/CANDIDATES/39/evidence/aa2e4c590c9cd82dfeadb1063273d6b15b45eef2c93c7d9f90134c6e85985bec.json)
- [N0-P05](../../../assets/deliveries/CANDIDATES/39/evidence/0884ee746fd76a00b22b33967195a3a387b25da8922c8be6de894d62df687dfe.json)
- [N0-P06](../../../assets/deliveries/CANDIDATES/39/evidence/ee9def90c73145e9d990a235ba4f7e94fa580d624125fb9ab34818cbe5d107b9.json)
- [N0-P07](../../../assets/deliveries/CANDIDATES/39/evidence/5f3461d47fb7b4c9338b8a8b479a0a6f49412ed0f2c70226bbd204296478d83f.json)
- [N0-P08](../../../assets/deliveries/CANDIDATES/39/evidence/cb3769d22cbd8170797367c194b389f6e2dd708278d55ff3c26d6f9cb9d62cbc.json)
- [N0-P09](../../../assets/deliveries/CANDIDATES/39/evidence/c94030e112bdb6cab54d27dc15199db42e9d886db62dc9dcdf062647bab92f0c.json)
- [N0-P10](../../../assets/deliveries/CANDIDATES/39/evidence/b031978651fe123213477dae03ac9def22348a1116babd87fc02b5d1f629a7c9.json)
- [N0-P11](../../../assets/deliveries/CANDIDATES/39/evidence/5d7013e4c8d1903694786398e486a6ed9fd38b88151acb618259d9cd22927552.json)
- [N0-P12](../../../assets/deliveries/CANDIDATES/39/evidence/1ef7f4e1189b56d6d713e23f5b2fdfc78dc7794b8d793573a3fffb426acc0e6e.json)
- [N0-P13](../../../assets/deliveries/CANDIDATES/39/evidence/4208ec1da81fb5ad0325bbd20e69797d241c329fc4c2e8e5b54931329868a422.json)
- [N0-P14](../../../assets/deliveries/CANDIDATES/39/evidence/3ebf6975f4f6e6ccea30553b56a359a9e9c4e0f834e8e9c62e182a5d7e501326.json)
- [N0-P15](../../../assets/deliveries/CANDIDATES/39/evidence/0bfc404ce11e85f66410b0faf1d26874114010ba3b332145a8e74980aec06047.json)
- [N0-P16](../../../assets/deliveries/CANDIDATES/39/evidence/f31f4de50a96b5e9355fb6f0dd1fbbd78b5cf8e5849a70b2f30d4a6ec20cc42f.json)
- [N0-P17](../../../assets/deliveries/CANDIDATES/39/evidence/b376761b8720466b3664ab93e17dadf1d90e9db2ef9d3e1623706af9473c4683.json)
- [N0-P18](../../../assets/deliveries/CANDIDATES/39/evidence/75d3678c81ddb4aa77dba987df31d56dccb16e4670660e472ec51472cc5824c2.json)
- [N0-P19](../../../assets/deliveries/CANDIDATES/39/evidence/b9650c9f8689c9484347ad76f569eb8bb762e3371a503a8b2ef28816cb40e106.json)
- [N0-P20](../../../assets/deliveries/CANDIDATES/39/evidence/849028292cef252249bbcd8f6d23c3ed000ea86291126c5a37843058a5f83226.json)
- [N0-P21](../../../assets/deliveries/CANDIDATES/39/evidence/303a8a774752297d889d0d9a2a0939195c815ae56797360f9b6b0259e7d48b63.json)
- [N0-P22](../../../assets/deliveries/CANDIDATES/39/evidence/b3bec19f81c0612e3e95f947e57a5e56c30cefa30a2ff4cffd6d7e9e714ef5aa.json)
- [N0-P23](../../../assets/deliveries/CANDIDATES/39/evidence/6394a851b6663be50542325af7af773e11dab1adeeb5b997bd4b179e4b25cf4d.json)
- [N0-P24](../../../assets/deliveries/CANDIDATES/39/evidence/706bb3a28910bf56bfb44151f68c11c32c0d57bcdccc3c499b71ed47a59f1479.json)
- [N0-P25](../../../assets/deliveries/CANDIDATES/39/evidence/b857b34d928c03ba8c71d4dacebf9829193ff1f185c7092482eecb4d91b232d5.json)
- [N0-P26](../../../assets/deliveries/CANDIDATES/39/evidence/6db1a6097ab4bb15730ac10db206f27f6ece191326ef0686f6a7330ba187bab0.json)
- [N0-P27](../../../assets/deliveries/CANDIDATES/39/evidence/0587291034ca9c3a77730bc739f94856a9b948edef3eb9de52633a7841c1ee0c.json)
- [N0-P28](../../../assets/deliveries/CANDIDATES/39/evidence/dc7c9f99b5cf5bebe6aca5e86508fd1a07e867331f1ce74476cb21be5c29f3b0.json)
- [N0-P29](../../../assets/deliveries/CANDIDATES/39/evidence/6f47f434e289e61283f04846a71a00473ee57cbaff1098a0d01d788de304920d.json)
- [N0-P30](../../../assets/deliveries/CANDIDATES/39/evidence/bab9b8ec7926165a1072b529ca510d44fe69e262583d6d05a57df99ff588111d.json)
- [N0-P31](../../../assets/deliveries/CANDIDATES/39/evidence/7c4db143900693ed02b62741881f2859593aca138472a8367cda06019a212513.json)
- [plan](../../../assets/deliveries/CANDIDATES/39/evidence/7beed71f67b643eba397a87ff360e384f66abc2940c44e07e2423a8acc8a20ae.json)
- [authorization](../../../assets/deliveries/CANDIDATES/39/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [previous42-prior-account-descriptive-diagnosis](../../../assets/deliveries/CANDIDATES/39/evidence/26dad0baf35054808dca919a74d7537f2858de04f21b303c432c7b8c13a53135.json)
- [previous42-native-anchors](../../../assets/deliveries/CANDIDATES/39/evidence/8902444f3a11c4764fc1b379ba49d3110f843e00112c236719108697b69c27a3.json)
- [previous42-research-decision](../../../assets/deliveries/CANDIDATES/39/evidence/a081e8c9163c9041d3fb54e0cf98aa7cb55fe518c93227f650ba199b556e5838.json)
- [geometry](../../../assets/deliveries/CANDIDATES/39/evidence/d508642461d6d3ab99fed0429c7a29c596d11000bcc859be867b5724e011d0fb.json)
- [summary-technical-correction](../../../assets/deliveries/CANDIDATES/39/evidence/0ace5b3d5e5f4f2f69beb440d3b3c5a74acd5a189fb841b6e7149af390301966.json)
- [parameter-execution-failure](../../../assets/deliveries/CANDIDATES/39/evidence/ff17ffbc89a449a4331cff9ab74a25ad48c55b3e20d86d2ad548e033178ecf01.json)
- [explicit-parameter-execution-correction](../../../assets/deliveries/CANDIDATES/39/evidence/1adf1f73878426c6825b32f16ba3ed4b5e05d07edee98dd8b794a56c352cfdde.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/39/evidence/6c41243765cdb3b91b1a5ea3b7287d084400c860e0a2de46ebaae48c2712b107.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/39/evidence/40e4f19759035cfde27d2eb0a53c1f32da89a61e43c44f6cf5d07dd8769ee9db.json)
- [protocols-parameter-analysis-references](../../../assets/deliveries/CANDIDATES/39/evidence/213c790956d504d88a6362dd605edad2a01093dca51c7a22819181a894a17158.json)
- [protocols-parameter-execution-correction-reference](../../../assets/deliveries/CANDIDATES/39/evidence/0b59971391813c9fe0f54b892446e879f530ec4dc370c9228a6f9fe01f78d5a8.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/39/evidence/b65882c412f915de13ab38a5b96101c77e6faa1d9631ac70959322c383034619.json)
- [protocols-plan-references](../../../assets/deliveries/CANDIDATES/39/evidence/ebd543339aa9f611aa97b75d27c25a527953a2f4c351eb59bf621180d60f059c.json)
- [protocols-technical-correction-reference](../../../assets/deliveries/CANDIDATES/39/evidence/f25a520424aded39350d241a9c9a0ea86a0280884054cc84ec3fc7b9a3c3edef.json)
- [protocols-technical-proof-references](../../../assets/deliveries/CANDIDATES/39/evidence/9833f53e6bb69e59ffe5cc8865960f093b688a9819bd587f58797a0cef58e90e.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/39/evidence/de5a12ced288618b4326ba8b728fc3a858f8e1eb7ebbec7f5b1cb2a04bdf1431.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/39/evidence/f825f73bcf8514aab3f3d0a6205b70ad4730a7c28f87df489f43c0224648449b.json)
- [runs-conclusion](../../../assets/deliveries/CANDIDATES/39/evidence/269be9fa94081b694ed0adc0bfe0e7424153dedfca686f40dd599d84b306ea90.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/39/evidence/aad2587a349ca5d905bc468b6de5cd3a12399fd1722352bd8ebe5b1bc6b54e27.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/39/evidence/e11c0a57bf7624f459b05a81eff6b1383b0a261f6b719841323b9da21922f786.json)
- [runs-parameter-matrix](../../../assets/deliveries/CANDIDATES/39/evidence/b11d90a62e1718fe1c893ba8eecae78506920ad42f67fe40610a8e633202a782.json)
- [runs-parameter-matrix-v3](../../../assets/deliveries/CANDIDATES/39/evidence/b29cbb9d4cd592025f31af53465eecb7b32d5d6f1e162ec4e2a2731ad438e27e.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/39/evidence/69193ac615aa1b56bb65d9d900d0b31a52dddeef9c68b504e904d54c7eaa0090.json)
- [runs-parameter-precheck](../../../assets/deliveries/CANDIDATES/39/evidence/2ac761ccbe4de93329366b226d7f60e2102aa5d079ee42f9cafdfdf584cdd4ec.json)
- [runs-parameter-recovery](../../../assets/deliveries/CANDIDATES/39/evidence/ec943b646accc2826d35b2528f16483ed8a57f5716ed2f34dcfe7c40584df841.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/39/evidence/869b2835c9594fd8b1ab0bf80f2e7c5127d131689dd2e6a5f8d10015dc299746.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/39/evidence/16217eddadf27d2305b011d5ed830c0eeae76d7987631ac83643ab2cbb5283c6.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/39/evidence/70fd9fb5f2c2624ec152beebc64ee5d3fd0cb8b120944b01c8f801418de792a6.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/39/evidence/3a00ce2a40ae9ceff564c99edc2dc0dcc8d9d0fe29fe06d3de4fd628954040e4.json)
