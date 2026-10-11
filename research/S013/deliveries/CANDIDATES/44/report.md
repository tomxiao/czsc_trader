# EX048 仅确认下跌持仓转上涨的状态退出

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

只对下跌路线的已有持仓，要求当前及前一完整交易日原市场状态都是上涨才按状态退出；上涨持仓遇下跌仍立即退出。区间、持仓天数、止损与追踪退出优先，入场当天不强退。空仓路线、区间、rawACF20过滤与原买入确认分完全保持。

原13数值中心、完整原域及同32共同坐标保持，原H仍以实际信号交易日计数。两日是事前固定结构，没有搜索确认天数、增加数值门槛或年份例外。原C2132隔离退出改变；旧C4900只作多结构历史反证，不冒称单机制对照。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原C2132 | 16.1572% | 14.1599% | 112 | 通过 |
| 既有多结构对照C4900 | 10.8889% | 21.2540% | 119 | 通过 |
| 下跌持仓转上涨两日确认C5980 | 13.9039% | 14.1270% | 107 | 未通过 |

新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。

新中心逐项判断：年化收益通过；各自然年回撤通过；闭合交易频率未通过；基准亏损年份仍盈利通过。

与原中心的1636个信号日相比，目标仓位不同33天，最终信号原因不同57天；首次仓位分歧为2020-02-06 00:00:00。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。

新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。

## 最强反证与证据边界

事前完整33原生路径、全部13坐标的正反单步诊断显示市场窗口/阈值与持仓期限直接触发较多，确认窗口不是独立主要触发。计数不可相加为利润损失，历史持仓也是内生路径。旧三日动量中位数与EX024多数票数学等价，未重复运行。

原路径作用点核对：中心17次最终下跌状态退出均会被两日条件推迟；32点共570个观察作用点。原规则本来不允许下跌持仓经历一天上涨后继续存活，因此这个计数首先反映原政策自身，而不是盈利优势、修订后的交易数量或独立样本。所有日期和年度分组正式留存。

最强反证：原中心仅112笔、门槛至少110笔，延迟可能使频率不达标；可能延长亏损，也没有直接消除H或ACF门槛敏感。EX017/30旧上涨延迟和整体多数票未保住经济要求。新中心和原32点须由完整账户判断，不能从触发次数或删除旧交易预测收益。80项独立策略纯检查、54条合成oracle路径、16拒绝和52条oracle检查通过，仅证明计算机制与因果可得，不替代经济门。

完成判断：{'center_four_gates': False}

本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、确认天数网格或缩窄参数域。

新增机制业务账户1、实际评价2；新增参数业务账户0、实际评价0；精确复用机制对照2、参数对照0。重复评价仅核对串行/spawn一致性。

反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/44/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/44/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/44/evidence/33ab2a6738c90f3502e57b44e99251348869577210f6accc4138adf4dcbb381c.json)
- [plan](../../../assets/deliveries/CANDIDATES/44/evidence/4229165ebe9264603d2d0484dd1ac9b93cf221e48e019c189997bb9543f31c4a.json)
- [observed-bear-exit-effect](../../../assets/deliveries/CANDIDATES/44/evidence/9c268395eca233a25cf31b5c35798a61e7f9a3ccda14db3cfde2338e34943e9b.json)
- [effect-method](../../../assets/deliveries/CANDIDATES/44/evidence/d198fc23dbcb9a8a39b59db96e0daa3146f9502a302daebb76c6b939d218be7a.json)
- [geometry](../../../assets/deliveries/CANDIDATES/44/evidence/b37ae46ecc0bc6a792a460424e4ab58b910cc47629b2ab84f7293ed70692fa37.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/44/evidence/b465449e6b6528a76239434f652060a7c293183ed8aa28e36a791bd009ad602f.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/44/evidence/77e7ce7be9aeb9a2db94ed402d9437716d8685a32eaa6694ea04ba7bcac36b9b.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/44/evidence/a479a326439afa03557dad95f4e96b4b4f196ccee52095536204169f5bdd140f.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/44/evidence/644234e3e746963234f79d88ce6a1f904b6e196544a296762b8e4c1b1570e2c8.json)
- [protocols-effect-method-reference](../../../assets/deliveries/CANDIDATES/44/evidence/e87eb3b2008eb349c1a4739b1ca5282bdaa568eb9cc4f82cad9f5918265ca6ca.json)
- [protocols-effect-reference](../../../assets/deliveries/CANDIDATES/44/evidence/b1a90962695021482a2b5eab39699f4014d216e1d0e5e69dc8490aec9a0627d9.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/44/evidence/7210fcbc1e62098be5d7ad6fb2915154c42f5f065d2f52c957793e048f5c5f83.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/44/evidence/99af29efc76092c23649ef0252b01f09b1d958f1dc57753a3dfc36b13c5f7316.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/44/evidence/d58ef2829d619dd2fbda7799cf7670ae3db8eefb1ec3581bd2bfd384ddcdebef.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/44/evidence/2c0994e94aa79e0b7a1d9cbd0f9da2303f7ceb81106d779aab1bee28bff465a4.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/44/evidence/e64dd2a39889c579d91073e7de7e9b12d99cd9a1a3ce287983868a9d430d805c.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/44/evidence/862c408e804c00de44abf0faac4a543edf9bf2b8c20a7e98965ba66f069a6374.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/44/evidence/b1a060f744482bef3fcfdf3e61671fe63c37ad9d3dbeaddc8ef43b3c329c03de.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/44/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/44/evidence/ccab22fc3fe0bc4315b9aad4d25f7a73a8c5feb479e136ace8025bad2b556bab.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/44/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/44/evidence/065c962771db332b31d7e68773726215a9b8dd5b10e584d767848da58d517f08.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/44/evidence/8b7e34f6a5d7dc60e6bc91980d4c91c4c249040fc0baf81e62e0dfbd7440abf3.json)
