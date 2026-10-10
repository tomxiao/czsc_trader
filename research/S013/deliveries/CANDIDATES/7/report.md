# S013：确认分变化与下跌路径脆弱性机制对照

本轮目标已完成。原确认门具有收益作用，但没有缓解已知下跌过滤和退出脆弱性。“确认分正在改善才买”的新表达没有形成满足原四项经济目标的新策略。建议收口本轮固定机制对照，下一步优先评审下跌路径过滤与退出的改进方案。这个判断限于本次机制、两个定向背景和已见开发池，不否定S013研究族或所有变化类信息。

身份RSCH；继续阶段三。用户批准3×4固定矩阵并要求自主完成；本轮没有追加参数搜索，没有进入阶段四、阶段五、冻结或PTE。当前C2132不投入PTE的决定保持。

## 已批准的比较与实际执行

三个背景为B0原C2132、B1仅将下跌状态自相关门槛从0.1改为0.045、B2仅将下跌状态最长持仓从4日改为3日。四种买入门为M0关闭、M1原分数S≥−0.2、M2当日分数减上一交易日分数≥0、M3同差值≤0。M2/M3替换原绝对水平门，不叠加；数学持平同时通过两门。原入场机会、退出优先级、活动路线锁定及零冷却日保持。

分数保持0.5×涨跌自相关分＋0.25×成交额分＋0.25×成交量分，使用完整120日当前分位。分数和分数变化都不是盈利概率。变化门只决定是否买入，转弱不强迫卖出。

仅使用S013原510500.SH资产与既有预热；2020-01-02至2026-09-30、1636交易日、100万元、100个HFQ研究单位整手、每侧10bp、T已知参考价限价T+1执行。策略与LimitBuyHold基准统一1%买入溢价；原价格网格、复权锚点、市场约束及四门沿用。账户跨年连续；基准实际亏损年份重新计算为2022/2023。研究单位账户不是PTE真实份额账户。

完整账户经TDR公共批次API；Optuna管理事前固定队列、种子13、8进程、每进程1原生线程、单请求workers=1。12个业务配置全部完成，两个源码实现版本共18个技术内容身份；实际账户评价21次，包含4次同配置技术控制、11次矩阵新评价和6次等值修正复算。次数不是独立发现数。

## 完整矩阵

最大回撤为全窗净值从高点的最大跌幅，仅用于诊断；四门中的回撤要求仍逐自然年核验。

|背景|买入门|身份|净年化|全窗最大回撤|闭合交易|2022净收益|2023净收益|原四门|
|---|---|---|---:|---:|---:|---:|---:|---|
|B0|关闭确认|C7000|13.9456%|14.1416%|116|7.9588%|0.3054%|通过|
|B0|原水平门|C2132|16.1572%|14.1599%|112|12.1687%|0.2841%|通过|
|B0|分数改善门|C7022|7.5951%|20.4889%|94|9.9156%|-2.0937%|未通过：return,frequency,negative_buyhold_year_profit|
|B0|分数下降门|C7023|3.0005%|16.9855%|87|-7.0598%|3.4486%|未通过：return,frequency,negative_buyhold_year_profit|
|B1|关闭确认|C7004|13.5252%|24.6207%|129|16.0887%|-1.9713%|未通过：annual_drawdown,negative_buyhold_year_profit|
|B1|原水平门|C7005|15.8174%|24.6200%|125|20.6159%|-1.9705%|未通过：annual_drawdown,negative_buyhold_year_profit|
|B1|分数改善门|C7026|6.4513%|27.2242%|110|5.1490%|-5.7048%|未通过：return,negative_buyhold_year_profit|
|B1|分数下降门|C7027|5.0639%|16.6010%|100|-5.8865%|3.4298%|未通过：return,frequency,negative_buyhold_year_profit|
|B2|关闭确认|C7008|9.5571%|17.8183%|125|1.9616%|-1.9513%|未通过：return,negative_buyhold_year_profit|
|B2|原水平门|C7009|11.7652%|17.4850%|121|5.9394%|-1.9690%|未通过：negative_buyhold_year_profit|
|B2|分数改善门|C7030|9.2289%|18.2580%|102|11.2865%|-2.1773%|未通过：return,frequency,negative_buyhold_year_profit|
|B2|分数下降门|C7031|1.7651%|21.6684%|93|-8.5384%|0.4127%|未通过：return,frequency,negative_buyhold_year_profit|

原四门为整体净年化至少基准1.5倍、每自然年回撤严格更小、每60交易日平均至少4笔闭合交易、基准亏损年份策略实际净收益严格为正。1636日至少110笔闭合交易。费用、余量、集中度、路径变化及分数变化诊断不新增资格门。

只有B0的关闭与原水平确认控制通过。它们是既有机制对照，不是新增机制发现；六个变化门均未同时满足四门，本轮无新增达标变化门、无新候选登记、无新增阶段四交接。原CANDIDATES/6、ASSESSMENT/2及历史账户原件保持。

## 为什么原确认门有用，却没有修好脆弱性

在中心，开启原门将年化从13.9456%提高至16.1572%，增加2.2116个百分点，交易数从116降至112。收益作用保留。

但三个背景的原水平门，在实际下跌状态基础机会中均没有直接拒绝过一次买入；全部直接拒绝发生在上涨状态。不能把这一门描述为已给下跌状态加上保护。跨路线交易会改变空仓时间和继承资金，因此“不直接拒绝”不等于整个账户完全没有间接影响。

放松下跌过滤后，原水平门回撤从14.1599%升至24.6200%，2023年由盈利0.2841%变为亏损1.9705%；年化仍有15.8174%，单看年化会掩盖风险。关闭确认时该方向的回撤也从14.1416%升至24.6207%，增幅几乎相同。这是原确认门未修复该定向弱点的直接对照。

缩短下跌持有期后，原水平门年化降至11.7652%，回撤升至17.4850%，2023年亏损1.9690%。关闭确认的年化损失同样约4.3885个百分点；原确认门也没有消除对该退出时点的依赖。

以上是完整账户路径对照，说明两个弱点在开启和关闭确认时均存在，不能相加推算13维联合扰动损失。更值得优先研究的是下跌过滤与退出造成的入退场路径变化。

## 为什么“分数改善才买”没有达到目标

中心的改善门只有7.5951%年化、20.4889%回撤、94笔闭合交易，2023年亏损2.0937%；低于收益要求和110笔频率下限。反向门年化更低，只有3.0005%，2022年亏损7.0598%。

改善方向在三个背景均比下降方向获得更高年化，留下了有限的方向性线索；但两者都没有满足完整经济目标，不能把相对较好解释为策略有效或值得投入PTE。

改善门中心拒绝81个当时机会，原水平门拒绝23个。机会集合会随各自持仓状态改变，不能把拒绝数差或被拒绝旧交易收益直接相加当成策略贡献。实际账户的价格与费用分解更清楚：2024年改善门相对原水平门的价格贡献减少26.3031个百分点，费用贡献减少1.1052个百分点，净收益仍减少25.1979个百分点；2023年价格贡献减少3.0101个百分点，费用贡献减少0.6323个百分点，净收益减少2.3778个百分点。少花的手续费未能补回价格收益损失。

改善门在B1的回撤仍为27.2242%，在B2也没有同时满足收益、交易频率和负基准年盈利。B2改善门比自身中心年化更高，说明某一局部反应可以改善；它仍低于同背景原水平门，不能据此宣布修复整体脆弱性。

完整交易周期、退场原因、成交量、资金继承和配对路径保存在关联分析材料中。原水平门中心与改善门仅49个周期具有相同入场/退出时点及路线，体现了实际路径重排，不能只解释成减少四五笔交易。

## 数值等值修正与验证范围

原分位评分在固定120日及0.5/0.25/0.25权重下，可精确表示为1/960的整数刻度。初始浮点实现出现4个理论持平日的机器尾差；其中B1反向门有2个当时机会受影响。原六份变化门账户和源码保持，并在实际复算前发布技术修订协议；新版使用整数刻度计算相邻差，数学持平同时放行，没有改变业务阈值、参数域或搜索范围。六个变化门均重新评价。

修正仅改变B1反向门少量经济结果，其年化从5.0771%改为5.0639%；中心主要结论保持。报告与资格全部采用修正后的实际账户。旧尝试不冒充新版验证。滚动参考窗口效应另行分解、原始组件变化核对，但不能作为独立样本验证。

合成及真实前缀因果性、未来修改不变、正反向/等值分支、非法参数、原退出AST一致、单/多进程信号及五类账本精确等价通过。12个最终账户及基准均按成交重建现金/数量、逐日价格和费用、年度净收益和回撤；交易周期与尾仓收益对账通过。已知2020-12-01分钟Low差异的潜在受影响订单为零；四处已知分钟High偏差不参与当前买入限价/市价卖出撮合。本次没有重建未知分钟轨迹或供应商历史修订。

研究约定采用当前schema 7的MANDATE/6，旧schema 6约定精确字节另作材料关联，不补签、不修改旧原件。最终12账户及6份数值修正前账户均经公开证据API保存，源码、实际请求、数据准备绑定和重现说明显式关联。

## 局限、停止依据与下一步

完整开发池此前已用于选择；本轮设计来自已见C2132扰动和确认机制结果，没有独立样本外证据。两处单参数背景是问题定位，不能替代正式5%总距离、32个联合点的阶段四稳健性自检。这个实验也没有覆盖其他变化期限、原始分量变化、权重或退出表达。

本轮收口依据是四种门的作用、方向反证、两处已知弱点及价格/费用取舍已有完整对照，变化门未形成新达标机制；不是因固定预算结束就宣称研究充分。建议保留原确认门的收益作用证据，把下一轮问题集中到下跌路径的基础过滤与退出硬切换，先提出可证伪的机制改进方案供用户评审。阶段四、选型、冻结和PTE分别等待明确授权。

## 正式证据

- [B0-M0完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/4f031683bdf865941d142b1135cfe2cfcb7cd20656f7db38dfdd4aca9e0d6ee2.json)
- [B0-M1完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-M2完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/295383493bc635f9f05f97f31ee9eed7654dd1c6910de99d0dcd6c687afecac6.json)
- [B0-M3完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/bf95305fffc19e64c49c7fb3c80d23903d90e2b053e4f9ea576046b7e048f0cf.json)
- [B1-M0完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/11f0edf305a628ab40374d8fc8bd47fb4e88b64ec06f352ed89783f8a5ee44ff.json)
- [B1-M1完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/4adf5f1214a44c76cff3241792a3a6a8fb8cee1f8547f05fd4fe8de1e846432a.json)
- [B1-M2完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/a3a6559ec2d65558c16970006c2bf75f657ba67964a15de20047c38afeac8cf1.json)
- [B1-M3完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/730e3f10de374400cc5c19e7668bb87ffe3dd38c023ab061986dddaca7eefd33.json)
- [B2-M0完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/34e5cb691990991aa5faf4029fd8c942458f85bd2df0b1915ba8ce75437a65d4.json)
- [B2-M1完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/02a5a9627e09db1b37d3c6580ec494035778be6a1db9f10b9be50658c101c11d.json)
- [B2-M2完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/de92216a4cb6df07084868bb564f2724121e3e08744057bc4a2c3664a0e13da6.json)
- [B2-M3完整账户](../../../assets/deliveries/CANDIDATES/7/evidence/5e67439df37e481c97e84c8ad4a550709d8d6192041e23cda07777b3e99c00ff.json)
- [mechanism-account-references](../../../assets/deliveries/CANDIDATES/7/evidence/23e74e28c23b8499523083332a1c269db046b4440b3f3a5c1d9300097888b5bd.json)
- [mechanism-analysis](../../../assets/deliveries/CANDIDATES/7/evidence/74f1b82f4fef95c21db949ce3a5970410616004eca8f16e21a0ac45287c6a2b0.json)
- [mechanism-analysis-r1](../../../assets/deliveries/CANDIDATES/7/evidence/9d3bfbc7413ff26e1ddc5a369cb99af670d158b50438ea33e9af1bc2cf8b53f3.json)
- [mechanism-authorization](../../../assets/deliveries/CANDIDATES/7/evidence/5bd1e92fa7d467df5019524edc0687030943fb2133364a6a6df420ff6da324d2.json)
- [mechanism-exact-tie-precheck](../../../assets/deliveries/CANDIDATES/7/evidence/5ef5dca59f54e7f0a9453cf1282c013ad59ec4701787b5589577b122eae0ce44.json)
- [mechanism-exact-tie-precheck-reference](../../../assets/deliveries/CANDIDATES/7/evidence/29d738063398a4dd652b3b21c1a074ffdfd5fb3165713f38c7ce8497c590a008.json)
- [mechanism-mandate-reference](../../../assets/deliveries/CANDIDATES/7/evidence/723dcccd82ba6c8e0cf3967c559db6dc5e4ff28f7061b18c09c767c4e88b862c.json)
- [mechanism-matrix](../../../assets/deliveries/CANDIDATES/7/evidence/575a269d46baf75ffbcd78c91f9467a88ecba02650aa51b3cf9bdc5f3d85f4a3.json)
- [mechanism-numeric-correction](../../../assets/deliveries/CANDIDATES/7/evidence/65ef08c078f0453f23021d246e335db382bdf965faa644ab51bbf65fd3829b4b.json)
- [mechanism-plan](../../../assets/deliveries/CANDIDATES/7/evidence/87683951db135f3d9d941ec672630dd5eb1de97dd8c212b05b56162b2bcccd29.json)
- [mechanism-plan-r2](../../../assets/deliveries/CANDIDATES/7/evidence/ad165c06f1c5e9f4c8f440d0ea1bb4960965190a9daff58e714c833c84194536.json)
- [mechanism-plan-r2-reference](../../../assets/deliveries/CANDIDATES/7/evidence/d9fa49dad0772e3f74bb0734a4544c1e757ffdceb00b038af42db80d1916b1f5.json)
- [mechanism-plan-references](../../../assets/deliveries/CANDIDATES/7/evidence/0b719cb23506fce7a15c9e35de116ce88b8592439087d29d53f4db11b43e1a97.json)
- [mechanism-precheck](../../../assets/deliveries/CANDIDATES/7/evidence/1f860e79d0c12cac0bd2a3beb406f5351cfa208995e61e6d76dd79fd314cb2db.json)
- [mechanism-preflight-reference](../../../assets/deliveries/CANDIDATES/7/evidence/b19c26c83565c74ff041e54dfe14a091bcfb9e36f5c2f0a46a3f8e0f67a10c00.json)
- [mechanism-preflight-supplement](../../../assets/deliveries/CANDIDATES/7/evidence/c920750056f850c59cf1d0a193a13e570ef99b9a857f0111d1cd10ecd0281894.json)
- [mechanism-synthetic-check](../../../assets/deliveries/CANDIDATES/7/evidence/8122258fcc5edf7f2d41b9186e6d620f2f1607fb2efc6264535e8fa2e528e832.json)
- [prior-candidates-receipt](../../../assets/deliveries/CANDIDATES/7/evidence/cac5d5ff67f2c1bb1ecbb64d320d54194d0845b72f3184c0e128a25fa0a5a1da.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/7/evidence/b0ef3c588aa05ca4919f08ca5aafc03a93f8cb50bb230001c4e5218f08075238.json)
- [数值等值修正前账户：mechanism-r1-numeric-attempt-b0-m2](../../../assets/deliveries/CANDIDATES/7/evidence/3a28ba131e6d8583a1dfdc934972313768c4926dc3e717005ab375502bf4395e.json)
- [数值等值修正前账户：mechanism-r1-numeric-attempt-b0-m3](../../../assets/deliveries/CANDIDATES/7/evidence/262ba0b92d8d2f675fae8442416913c7c2b0b9c31919f447cbd4f50aca4a689d.json)
- [数值等值修正前账户：mechanism-r1-numeric-attempt-b1-m2](../../../assets/deliveries/CANDIDATES/7/evidence/57916c1f26ed111c5a34c8c713ea2045a3c0f452a5d1eba83c4bce9d5d5718bb.json)
- [数值等值修正前账户：mechanism-r1-numeric-attempt-b1-m3](../../../assets/deliveries/CANDIDATES/7/evidence/b84859e443aee58aa59a323b4120035de29ebd61f8954bc9de1f7164265148d3.json)
- [数值等值修正前账户：mechanism-r1-numeric-attempt-b2-m2](../../../assets/deliveries/CANDIDATES/7/evidence/ed68efd41cb6f0a55aa061bc5ed48e5c63f94b2622ec434f196f7977222e0f0b.json)
- [数值等值修正前账户：mechanism-r1-numeric-attempt-b2-m3](../../../assets/deliveries/CANDIDATES/7/evidence/f2ece2478cd6eb7682c1061ade796df3aa49c499dae7e105bd4d9663941b1fc0.json)
