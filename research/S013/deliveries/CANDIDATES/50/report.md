# EX054 原相关背景低价到期退出后日内回升再入场对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

保留C2132原相关性过滤和原买入确认，只增加固定的再次入场条件：上次持仓是下跌路线、最终因到期退出、退出信号收盘价低于该次入场信号收盘价时，后续原本满足条件的下跌买入还需今天收盘价高于今天开盘价。这里的低于是信号价格比较，不代表实际交易亏损。

记忆跨空仓、资格不满足及市场状态变化保留，任意路线成功发出入场信号后清空。持仓期限、全部退出优先级、费用及执行保持；不按日期或未来收益分类。原13数值中心、全域、同32坐标和父暖启动均保持；固定方向与类别选择仍有结构风险。

## 完整账户背景对照

| 背景与门控 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 四项目标 |
|---|---|---:|---:|---:|---:|---:|---|
| 原相关、无门 | C2132 | 16.1572% | 14.1599% | 112 | +12.1687% | +0.2841% | 通过 |
| 原相关、BODY重入门 | C7880 | 13.0062% | 14.6157% | 108 | +3.2530% | +0.2856% | 未通过 |
| 均值调整相关、无门 | C8701 | 13.5405% | 23.9087% | 123 | +11.4638% | +0.5481% | 未通过 |
| 均值调整相关、CLOSE重入门 | C4900 | 10.8889% | 21.2540% | 119 | +9.4200% | +0.5491% | 通过 |
| 原相关、CLOSE重入门 | C7580 | 12.8588% | 14.6157% | 108 | +3.2530% | +0.2856% | 未通过 |
| 均值调整相关、BODY重入门 | C4901 | 13.8928% | 22.6858% | 119 | +13.9067% | +0.5491% | 未通过 |

新中心逐项判断：年化收益通过；各自然年回撤通过；闭合交易频率未通过；基准亏损年份仍盈利通过。

六行是按精确身份与完整原生账本认证的独立完整策略，五个旧账户不新增评价；原相关新门是本轮唯一新增业务账户。均值背景无门对照即使未达标也完整呈现，仅作机制诊断，不成为参数面板或新增资格条件。全期回撤与逐自然年回撤口径不同，资格使用原逐年门。

新中心串行与spawn信号及双方五账本精确一致，独立公式与全部状态/入场锚点/分类审计通过，所有成交、现金、费用与年度权益分别核对。不同完整策略间差异不等于删除旧交易利润；信号入场与实际首次成交可不同，实际多次成交按全量账本核验。

相对原中心，目标仓位不同22天，原因不同32天；首个仓位分歧2020-09-10 00:00:00。

新中心未达原四门，不运行32点；新增和复用参数账户均为零。

## 最强反证与解释边界

原中心2023年低价到期后重入来源实际贡献+2.3049个百分点，而全年只有+0.2841%；该来源含有维持年度盈利的机会。全下跌价格方向门先前只剩96笔且2023亏损。均值背景CLOSE门中心达标，但参数较差一端收益和回撤均劣于原C2132；它同时改变相关算法及方向，不能当作本轮BODY的单项证据。局部门也可能伤害恢复机会，不能把低价退出自动当作坏交易。

原相关CLOSE局部门只有108笔而未达频率门；均值背景BODY局部门2024回撤19.7928%高于基准18.5736%。BODY与CLOSE机会不嵌套，不能从旧机会计数预言增加交易数。更早双相关共同确认年化12.5897%、107笔且2022亏损3.4613%，费用下降未抵消实际价格路径收益损失；据此保留原相关算法，本轮只改变局部再次入场条件。原112笔仅比最低110笔多2，2023盈利余量很小，频率与年度盈利的失败都会按原门完整呈现。

纯runtime、独立oracle、原13域参数辅助及33条合成完整路径互证通过，失败和修正证据保留。合成检查确认实现语义，不代替经济目标。反复使用已见S013开发池，未获独立市场验证；FULL只检验证据完整性。RSCH阶段三。

完成判断：{'center_four_gates': False}

本机制未满足原联合目标；保留负面结果，按实际原生路径继续机制反证，不追加年份例外或缩窄参数域。

新增机制业务账户1、实际评价2；旧中心精确复用5；新增参数业务账户0、实际评价0、复用参数账户0。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/50/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/50/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [B0-MEAN](../../../assets/deliveries/CANDIDATES/50/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [B0-RAW-CLOSE](../../../assets/deliveries/CANDIDATES/50/evidence/5f96a39ece6ff78ac7c22324e3bee87e8bbe0a7314622800c5621f75d410152d.json)
- [B0-MEAN-BODY](../../../assets/deliveries/CANDIDATES/50/evidence/bf339e0c9c6563a77b0e19d72b6bfee9f8355707c10ac4512e41bf93f136c2fc.json)
- [N0](../../../assets/deliveries/CANDIDATES/50/evidence/c5da2788202b76d909adf5bba14fc5da3716be98bf4fb88bbc85b7252b7905a6.json)
- [plan](../../../assets/deliveries/CANDIDATES/50/evidence/7068eb60b910537f2cf9b9cb0e13333944d49870d7ac3868e1cbe27b4238cf26.json)
- [raw-below-reentry-method](../../../assets/deliveries/CANDIDATES/50/evidence/7a86b8111f0f478087635d877dda9d427ce754d6fa17f3aaadf265e5134d015f.json)
- [geometry](../../../assets/deliveries/CANDIDATES/50/evidence/5615cf54e9e2c3f9765a04a6d169fac8668c5a5cfc2e6b52f2bd785870c36158.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/50/evidence/644545830d531fa44a6bcc7959070994179ace417aa098412ce79c83fd612fd8.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/50/evidence/0b87ffb5ea1b8738d9e6e0f4fe8c42c976160ae8cf3a35d28bb51505b7b8c4f2.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/50/evidence/3b737bc0747032df1b5a5e86780ff766f3dadec1fa7fb30829f090691ad281a9.json)
- [crosscheck-pure-prototype](../../../assets/deliveries/CANDIDATES/50/evidence/93e0b2700118ab9b81b5989d7b4bd9a932e01bc52388f347ce5b6ed20adabe3b.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/50/evidence/903b85c96c6499eb912401b79543525d6849c4d232c66dd7632f38120fc33cc2.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/50/evidence/994a2ce9350a5f24db92c409f2fc76329e6b264e285071071bc2b4e24c40ca8d.json)
- [protocols-method-reference](../../../assets/deliveries/CANDIDATES/50/evidence/e2da483f677c22e86ab5a1097ad2755150d7f2600eb6876ba4447dfc1df033eb.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/50/evidence/1542229c0b97f515f392fe231880394cf70de357dce2f43c0d2fa6bcfebd9226.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/50/evidence/4530e2074d512fb35d65c0d79e929f27caa2466ef936ac96be2cb01ce5e97ec9.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/50/evidence/a5d710ab21e645214db38f30a38d5291b7c68581e2eb723b5022b855996f97f1.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/50/evidence/f8bd0c5f58fa4e9963e16b6a26e8a8bc954ffcd357d9d65bd77c66eeaf42bb5a.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/50/evidence/0695079c9eb96fa4a8e80198005e9019e5d2a8596acc612407f5136803c18a83.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/50/evidence/6d4187d9ac16cf6df6262d59d6ae95fe1c45f68ba4e67208a96415fd67e84f2a.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/50/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/50/evidence/a3aabe0f4fa7d6f84b11077a3b7d455e1f5295fd6a4648cbe78b6fb44a8f172b.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/50/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/50/evidence/6ed5ea26d72d1cc0ce7f68a4febb680d48113e4c22ec6af8d96eabc607b8fd10.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/50/evidence/956fa3c409c5c130b9ee87f967325d6c824fc929387cfb72db0206f575c91336.json)
