# EX049 三完整原动量均值的市场状态对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

把当前与前两完整交易日的原W日动量求数值均值，以原阈值判断市场上涨或下跌。空仓路线和立即状态退出均使用新分类，持仓路线仍锁定；原区间、持仓天数、rawACF20与买入确认保持。没有先平滑价格，也没有增加退出等待天数。

原13数值中心、完整原域及同32共同坐标保持；W仍是原动量的实际窗口，阈值仍是原收益率单位，H仍是实际持有交易日。固定三日均值是事前结构选择，没有搜索均值天数、改变单位、缩域或年份例外。原C2132隔离状态分类改变；旧C4900只作多结构历史反证。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原C2132 | 16.1572% | 14.1599% | 112 | 通过 |
| 既有多结构对照C4900 | 10.8889% | 21.2540% | 119 | 通过 |
| 三原动量均值C6480 | 9.8046% | 21.8880% | 100 | 未通过 |

新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。

新中心逐项判断：年化收益未通过；各自然年回撤通过；闭合交易频率未通过；基准亏损年份仍盈利未通过。

与原中心的1636个信号日相比，目标仓位不同128天，最终信号原因不同218天；首次仓位分歧为2020-02-04 00:00:00。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。

新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。

## 最强反证与证据边界

事前完整33原生路径、全部13坐标的正反单步诊断显示市场窗口/阈值与持仓期限直接触发较多，确认窗口不是独立主要触发。计数不可相加为利润损失，历史持仓也是内生路径。旧三日动量中位数与EX024多数票数学等价，未重复运行。

原33完整观察路径核对：中心分类变化111天，与三票不同40天，固定原既有持仓状态的目标变化61天；32点共1898个目标作用点。新分类的后续持仓另行传播，只能由实际完整账户判断收益与交易频率，不能把作用点次数当利润。

最强反证：EX021平滑参考价格、EX024状态多数票、EX005阈值缓冲/确认和EX048下跌退出延迟，都提示减少状态抖动可能损失价格收益、下降控制或交易频率。EX048的112→107差额为持仓合并/重排少3和两个后续机会错过少2，尾仓相同；并非可删除旧交易估算新收益。新数值均值不解决全部H/ACF敏感，还可能被大幅异常动量主导。

限定S013既有实验源码和元数据的重复核对未发现三原动量数值均值的精确旧实现。多数票看三次正负，数值均值保留涨跌幅度；均值可能与多数方向相反。完整当前和两前日动量来自预热历史，warmup=max(parent,W+3)，未填补缺失。66策略纯检查、33独立合成公式路径、88检查、17拒绝及38参数/无金融展开检查通过；两次纯oracle测试夹具失败和修正记录完整保留。这些只证明计算与因果可得，不替代经济门。

完成判断：{'center_four_gates': False}

本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、确认天数网格或缩窄参数域。

新增机制业务账户1、实际评价2；新增参数业务账户0、实际评价0；精确复用机制对照2、参数对照0。重复评价仅核对串行/spawn一致性。

反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/45/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/45/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/45/evidence/fef551882720d747994dc3d852138d81104a4dfc55415ad9aa8c176d21d2ba83.json)
- [plan](../../../assets/deliveries/CANDIDATES/45/evidence/4d12c9b834e99415b490e44456b7aae4dfef213ce082f4833660f62243d28198.json)
- [observed-mean-momentum-effect](../../../assets/deliveries/CANDIDATES/45/evidence/9953398b315504ca75cce0016d07cc35cbc2956ec3e72ab377e0700acd824d10.json)
- [effect-method](../../../assets/deliveries/CANDIDATES/45/evidence/6d881a131fd88d9d71fd95372ccf525699d5c76d79a1aa31cbe8dca479ee0567.json)
- [geometry](../../../assets/deliveries/CANDIDATES/45/evidence/2945b22ec1bcc3120d31dc082d3a1e39dc4c9d9597384132d768d7824ec81589.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/45/evidence/3ebc169a4a2f54997ef6db21716dde06d2e1394e95de53ef7eed9a5788426aa0.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/45/evidence/fea98e49db2634d273197c1f62320104e13e1461e42fff18c50e2f38bccdae86.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/45/evidence/de452d936d8d6719ff90a1974af956fd6e6ebaffecca266b7116f6094529798e.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/45/evidence/644234e3e746963234f79d88ce6a1f904b6e196544a296762b8e4c1b1570e2c8.json)
- [protocols-declaration-technical-failure](../../../assets/deliveries/CANDIDATES/45/evidence/6acdffab1e97fe3f414c74480b504418c4325a2d539dffe19511be4fd5fdf1b8.json)
- [protocols-effect-method-reference](../../../assets/deliveries/CANDIDATES/45/evidence/5063fd1ffbfdf7352b0f22aa7d486895d8b219bb8b7a5e47969ff396f479cfe6.json)
- [protocols-effect-reference](../../../assets/deliveries/CANDIDATES/45/evidence/01e01f07592813518ea58cbc7c396b92a680635cb5220a2995492aacd6f02ec4.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/45/evidence/cb6746ca4fbc641729970dcb28c8f5492f2b3b968f2d2076e4a7ef5e919d043b.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/45/evidence/7620b697d64032f0ce4fc40fb87efa7662145ac73079ee9b85a7227332eb0b78.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/45/evidence/2bca772b50528d73afda63db250791e80cb9a90260d509dcba4ed2ec19c46877.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/45/evidence/bbe446cc38f10723e8458be15bcd6ecc358a6782d5a2a3a82d7c03f116664b5c.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/45/evidence/e63e95b607bb2a62260616cc28b7eaa8d5a6e972090db21b406d1491e0b4e9f4.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/45/evidence/f9d01028c74710863e1f32c72c510611e9d5a5318694b84bdd1ed19cd16e3883.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/45/evidence/b1a060f744482bef3fcfdf3e61671fe63c37ad9d3dbeaddc8ef43b3c329c03de.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/45/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/45/evidence/fb92fae4a88d6a52e77e5a4a3c0c14fc515ffa4a4c545cf70810ad437eda9292.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/45/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/45/evidence/03189cbd814cb627e885d089d3354b8b20b655dd02c07adaf5d5ad073ef462b0.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/45/evidence/8b35306c6c81f2c4bbb73265c048abd41116757ddbbc15acae454a40df75f31e.json)
