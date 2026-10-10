# S013：下跌定时退出后再次入场的价格方向最小对照

RSCH阶段三，用户授权自主研究，无需逐轮评审。原S013数据、四项经济门和13维完整域保持。

EX033原33完整账户诊断显示下跌TIME退出后常在原范围/路由条件刷新前重新入场。EX034/35刷新等待已损害交易次数和基准亏损年盈利。EX040四个所有下跌买入方向门也失败：闭合交易95–106笔不足110，2023收益全部为负。此次只把价格门放在原定时退出后的再次入场上下文，检验减少不当重复买回是否有净改善；这些已见信息和失败结果在选择前已披露。

两新配置均保留EX028均值居中自相关背景：当前ACF20减严格过去L估计均值，L为原confirmation.lookback；其原C8701背景123笔，仅2024年度回撤不满足原门。只在T空仓、原资格合格、rawregime=bear，并且上次信号退出路线bear/原因time、其后没有任何新信号入场时，分别加严格Close>前一实际日Close或Close>当日Open。等号拒绝，方向拒绝优先原确认拒绝。每次持仓信号退出保存退出前路线与原因，每次任意路线成功信号入场清除二者；方向拒绝、资格失败、空仓时路由变化不清除。这是策略信号状态，与实际成交/闭合交易不同。

首次/非TIME/上次bull-TIME下跌机会及全部bull机会保留原入场；所有持仓loss/trailing/range/time/regime退出、原H8/H4信号持仓日、原确认分与阈值不变。没有新增等待刷新条件、止损、风险宽度、幅度阈值或年份例外。新增两类别与上下文范围不在原13数值坐标中，未证明类别或范围选择稳定。全部13数值仍有效，MEAN既有L+21预热和W+2纯前路由诊断依赖披露。

510500.SH、2020-01-02至2026-09-30共1636交易日、100万元、HFQ信号、统一可执行价口径、整手100、T决策/T+1执行、单边0.1%费用、策略与LimitBuyHold统一1%限买溢价。原四门：年化≥正基准1.5倍；每自然年回撤严格低于基准；每60日≥4闭合交易（至少110笔）；基准亏损年2022/2023实际连续账户收益为正。全窗回撤是诊断，不替代年度门。

两新业务配置、三实际完整评价（N0串行/spawn完全一致重复），两旧完整原生背景精确复用。原生全部信号与现金/数量/费用账本独立核对，四账户五基准账本一致。日期按已绑定公共交易日历、完整signal_dates和执行日期验证全部1636对T→下一会话；信号行情截至末T，无未来价格或删除末端信号。所有失败账户和年份保留。

|账户|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
|B0-TIME|C2132|16.1572%|14.1599%|112|+12.1687%|+0.2841%|通过|
|B0-MEAN|C8701|13.5405%|23.9087%|123|+11.4638%|+0.5481%|annual_drawdown|
|N0|C4800|12.1547%|16.5875%|116|+8.4479%|-1.2487%|negative_buyhold_year_profit|
|N1|C4801|13.0995%|22.8325%|116|+12.9032%|-1.2500%|annual_drawdown、negative_buyhold_year_profit|

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
|N0|2020|+18.2050%|6.1272%|14.9712%|通过|
|N0|2021|+10.6278%|2.6939%|9.7035%|通过|
|N0|2022|+8.4479%|12.3203%|28.4105%|通过|
|N0|2023|-1.2487%|6.7412%|17.2665%|通过|
|N0|2024|+44.0969%|11.8362%|18.5736%|通过|
|N0|2025|+10.6862%|2.2390%|13.7975%|通过|
|N0|2026|-5.7231%|8.3093%|18.7646%|通过|
|N1|2020|+18.2050%|6.1272%|14.9712%|通过|
|N1|2021|+10.6278%|2.6939%|9.7035%|通过|
|N1|2022|+12.9032%|11.2403%|28.4105%|通过|
|N1|2023|-1.2500%|6.7426%|17.2665%|通过|
|N1|2024|+53.2144%|19.8148%|18.5736%|未通过|
|N1|2025|+5.5924%|3.5334%|13.7975%|通过|
|N1|2026|-5.7252%|8.3108%|18.7646%|通过|

两新中心均未通过原四门，按事前方案零新增参数账户。本轮无参数敏感性改善证据。

两个新完整账户均未通过原四门。TIME再入场-CLOSE年化12.1547%、全窗回撤16.5875%、116笔、2022+8.4479%/2023-1.2487%；TIME再入场-BODY年化13.0995%、全窗回撤22.8325%、116笔、2022+12.9032%/2023-1.2500%。两者交易次数保住原门，但2023均亏损。

CLOSE所有自然年回撤门通过，2024年度回撤11.8362%低于基准18.5736%；BODY2024仍为19.8148%，高于基准。相对旧MEAN背景123笔和2023+0.5481%，新条件仅作用于下跌TIME再入场仍削弱薄弱年份盈利。不能以原账户删掉交易后的收益推算新利润。

缩小价格门作用范围解决了EX040全下跌机会门的交易次数不足，但没有解决薄弱年份盈利。结合先前刷新等待与全下跌门失败，证据反对把严格上涨方向视作一般可靠的再入场确认。诊断是完整账户对照，不能声称所有价格信息都无效。

两个原生失败账户、全部年份、原失败审计和继任方法已留证；零新候选登记、按事前方案零新增参数账户。原四经济要求与13完整数值域保持，改善参数敏感性目标尚未达成。

原审计拒绝原生类别列NaN与重建None的表示差异，原冻结源码与失败保留。显式v2只接纳两个退出状态字段在相同独立缺失位置的表示，所有非空类别、信号、日历与经济账本严格核对。全重建与日历函数AST相同，17项非法状态/表示篡改被拒绝，零重跑完整账户。

停止不区分退出价格状态的严格TIME再入场方向门扩展。下一步先做零新增账户诊断：精确复用原33参数/中心账户、MEAN与MEAN-BODY旧背景以及本轮两账户共37个不同原生账户，独立重建每次下跌TIME信号退出当时的Close与该信号持仓entry-anchor，并完整列出后续空仓机会、重新入场、方向拒绝、实际资金贡献与全部自然年。价格低于/等于/高于原信号入场锚点为事前类别，全部组保留；这是当时可得信号价格状态，不是实际闭合交易P&L，也不按年份或事后盈利删选。核验这种状态是否区分风险重复买回与正常恢复，检查此前相同入口机制是否已测；证据支持才声明最小新完整对照。原13域/四门/完整账户及只达标中心展开32点保持，不继续校准已有风险宽度或门阈值。

已见开发池反复选择存在偏差，不是独立验证或未来保证。全路径差异是完整账户对照，不能用删掉旧交易的盈亏相加替代新利润。FULL只核验证据完整性。未推进正式阶段四、冻结、PTE或生产。

原独立审计在last_exit_reason初始无退出记录的493行发现原生NaN与重建None表示差异。冻结原源码与失败完整保留；显式v2仅核对last_exit_reason/last_exit_route两类别字段的相同缺失位置，所有非空类别和经济字段仍严格相等，拒绝17项非法状态/表示篡改。特征、全状态重建及日历函数AST完全相同，原生账户未重跑，参数、规则和四门未变。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/37/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-MEAN](../../../assets/deliveries/CANDIDATES/37/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [N0](../../../assets/deliveries/CANDIDATES/37/evidence/225c77a01b03d8e3858f790a935f971d3ccec5ec9c4d8a7fcd626aeda95217c6.json)
- [N1](../../../assets/deliveries/CANDIDATES/37/evidence/65a233dafec5ebb2ee2ffcfbf00fad9530245ab1b35d9efed6125eeb799edc4a.json)
- [plan](../../../assets/deliveries/CANDIDATES/37/evidence/e78034572361a74db71946119087d360aede6486161eaed6386d66daff5d8ad8.json)
- [authorization](../../../assets/deliveries/CANDIDATES/37/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [previous40-runs-analysis](../../../assets/deliveries/CANDIDATES/37/evidence/439c0d02fd4631f1024f7ec71bc369ef1c2ad4862a2596b5d4de9016c092b7e5.json)
- [previous40-runs-conclusion](../../../assets/deliveries/CANDIDATES/37/evidence/e42dabb57ad7f9f8e7197793dd7cf1f6088f96f706436e831c6ddf392375aeae.json)
- [previous40-original-reentry-diagnosis](../../../assets/deliveries/CANDIDATES/37/evidence/aef297c6fb506885121aa9bc4e6fc4f6975127c852af1647bd62984ff127279b.json)
- [geometry](../../../assets/deliveries/CANDIDATES/37/evidence/74f334b300d253616d13e0e1986a5f741a936710f0975006e3301d6d512e27fb.json)
- [original-analysis-failure](../../../assets/deliveries/CANDIDATES/37/evidence/1d15c362f05df0d520df81ca357c7129590e7a48de6b95fc98ea45881d4240de.json)
- [focused-nullable-correction](../../../assets/deliveries/CANDIDATES/37/evidence/81e5decb5c74d9e2238d9cd5c06d13c1e3e7e6dd6f8224f16ddaf98585d3f7ba.json)
- [explicit-technical-correction](../../../assets/deliveries/CANDIDATES/37/evidence/96ecfa0aad88a80eb110038499cd600814217268cfb524c812ad6e0cbf16ebd7.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/37/evidence/717c7dfc9e7c726ef614b801588d17cef233da01f8b2a44820580efa026accf3.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/37/evidence/8853011f3be5c7185c892e7bb304d3802f7053854ab3bdb2f7f741387a612101.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/37/evidence/a1a7e04df4df15ca3cdc4c2e85ae6f51056d66e956febab29f7b72d8e51daa59.json)
- [protocols-plan-references](../../../assets/deliveries/CANDIDATES/37/evidence/30876295f08997d251ed087b1a62facf1abbc7ada109e6f79decb9dbe19f747d.json)
- [protocols-technical-correction-reference](../../../assets/deliveries/CANDIDATES/37/evidence/e445dbfa4f73bfefdce96f1c4c685c0a5dbff665bcbdc330e0462a1752983d8b.json)
- [protocols-technical-proof-references](../../../assets/deliveries/CANDIDATES/37/evidence/35398fb151ba46e9740aafc4054b4fd54d29a6ea56dfdec07a4392e6a3404f65.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/37/evidence/e504317d51023a056a31f264e14c43c5543953a71442a5fb00ce2bc9129906d2.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/37/evidence/023285389e4d3ba00801047f830e03898a4987409ec946c9246e370d38bee4f5.json)
- [runs-conclusion](../../../assets/deliveries/CANDIDATES/37/evidence/e47a76c2517ae82a59901e0c1439acb6c2197b9c43f3e084ed20b1050061a663.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/37/evidence/9d4fe74b03564a4259b44482a8a5e9d15b4032f4366c5789020f5e77e2a01748.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/37/evidence/f4b0faf20d8a8af1b55dabddb567bdb7b72f9c54e986b466793557f1de19ac1b.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/37/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/37/evidence/3584c8b90b3108e0f64d4d523f993c70919c83aeffb092030a594df2032c896f.json)
- [runs-prospective-pure-verification](../../../assets/deliveries/CANDIDATES/37/evidence/5ba816cf7a572dbb169afb6a7f90dc4ca1346e041dc49a73c5b398f3c546e5fe.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/37/evidence/d4ccfa778e01fc4bec5483b3ebb573d53a374103667c38590b37b14e65ad9ef9.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/37/evidence/264b2092961bc8d5c821c798288c2f9282ea47509cbd2758ba27aad527a13206.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/37/evidence/cd1b2aae215bd8a64467000baabc4be2699deb74b40fd219b35d7ec4a90a2ca8.json)
