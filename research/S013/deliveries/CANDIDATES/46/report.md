# EX050 下跌入场相邻收益秩相关对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

只将下跌入场过滤换为秩相关：分别将最近20个日收益的前19个与后19个排序，比较相邻收益的顺序是否一起变化。相同值取平均名次。原买入确认仍用原rawACF，市场状态、持仓期限、退出与全部原列保持。

保留原13数值中心、完整原域及同32坐标，但秩相关与原ACF统计含义不同：同一个0.1阈值不代表相同过滤力度。没有单位映射、缩域、abs、截断或降级；任一19样本秩方差为零明确拒绝。固定20为事前结构，非优化窗口。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原C2132 | 16.1572% | 14.1599% | 112 | 通过 |
| 既有多结构对照C4900 | 10.8889% | 21.2540% | 119 | 通过 |
| 下跌秩相关C6680 | 10.6801% | 13.9135% | 110 | 未通过 |

新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。

新中心逐项判断：年化收益未通过；各自然年回撤通过；闭合交易频率通过；基准亏损年份仍盈利未通过。

与原中心的1636个信号日相比，目标仓位不同158天，最终信号原因不同221天；首次仓位分歧为2020-02-03 00:00:00。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。

新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。

## 最强反证与证据边界

原33完整观察路径核对：中心过滤判断不同199天，固定原既有状态的目标变化52天；32点共1614个目标作用点。次数不等于利润，只有新完整账户能判断经济效果。

最强反证：去掉原下跌ACF削弱负年份保护；原ACF时间均值/中位数、过去窗口去均值未保住全部经济目标。秩相关舍弃幅度，排序也可能跳变；原市场状态与H敏感性仍在。只在S013既有源码和元数据核对精确重复，没有用EX002未来收益标签进入运行。

策略、独立pairwise秩公式/原路径审计与原13域参数展开的聚焦合成检查通过；纯夹具失败及修正保存。父warmup不变，完整历史先计算后取信号日；无缺失填补。纯计算验证不代替经济目标。

完成判断：{'center_four_gates': False}

本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、确认天数网格或缩窄参数域。

新增机制业务账户1、实际评价2；新增参数业务账户0、实际评价0；精确复用机制对照2、参数对照0。重复评价仅核对串行/spawn一致性。

反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/46/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/46/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/46/evidence/b5311431f26b5294431aa378238e82e436614653c4ae9c91c5d95533e7af25f8.json)
- [plan](../../../assets/deliveries/CANDIDATES/46/evidence/d3c3833b36b59f6a66c9fd1a9eceed632c876e50c9fb90209c3b709133c867a9.json)
- [observed-rank-acf-effect](../../../assets/deliveries/CANDIDATES/46/evidence/f1fe4bbeec3e9eadd6f4348833dcc1d49c528ba618a42c1d95eb748cb26d9630.json)
- [effect-method](../../../assets/deliveries/CANDIDATES/46/evidence/2504b6af4a09714f3966aeebb2ffe5a08a6c5fa9c675ce03b24c363a04dedabc.json)
- [geometry](../../../assets/deliveries/CANDIDATES/46/evidence/e605b0d3db4c235197b44acdffe001d4418bc293a967a1c9abfec26e0e9383b0.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/46/evidence/5bd740749c5818dfa0883d40f70a03359bdaaf2eca33fd44650fda27af6d8edc.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/46/evidence/b2d38a2523031b5a1a89797486b5a234b449d6def77998235c1b679e4ada06d9.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/46/evidence/f0ed4076ace42c567053c15005f534726345eda85242c704b29d0572cc366273.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/46/evidence/644234e3e746963234f79d88ce6a1f904b6e196544a296762b8e4c1b1570e2c8.json)
- [protocols-effect-method-reference](../../../assets/deliveries/CANDIDATES/46/evidence/15dc9a8870006a0cda62f0e0c78036c0ec359753b204777948ac45ce5741843c.json)
- [protocols-effect-reference](../../../assets/deliveries/CANDIDATES/46/evidence/d293df7b7a1a3d2bbd131eb295c12327de5ced7d18ba6aa8a2733317f7f2ea72.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/46/evidence/d14e9113b2241abae5eb6e821b9ba5af361406411a68da6e175ebbe26c8b7d2f.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/46/evidence/377f59f24fc2014939e2c755ea208510ee68333d79d2502dd556a0ad2e6934f8.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/46/evidence/b46ebfee15bbdf5d1b45f4a5744924fcbccdf7cffd134096bd8be82caeb708b2.json)
- [protocols-setup-technical-failure](../../../assets/deliveries/CANDIDATES/46/evidence/1e5e3debdbfe8aae63a9d08f85426256129ad87538c03a6c5dcb61d48d9f33d1.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/46/evidence/926ae486e0aaf207207187f17d037bbed41d79d38eccfa5d0bd35aeb4e2c9961.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/46/evidence/686cd2a6772698796fc677cab275e1c96cb52c2f253b14048f615a7d558ded88.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/46/evidence/9ae0da8c3bf0b14b08b7031bdd919f2aa377fdd5ed60745bcd483c90b89ea379.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/46/evidence/b1a060f744482bef3fcfdf3e61671fe63c37ad9d3dbeaddc8ef43b3c329c03de.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/46/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/46/evidence/55fef56e8192398aac921bd1142df66e84d31c5720079b8df9ba7b39212ed9ec.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/46/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/46/evidence/d68f367b51a2d5ceab982099c57715a2a44d70b7488e65bf27e1587535eb3a80.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/46/evidence/2516a3d2e6dfcd8fcca31fe4352e9b36da4c9bd676820d3453c8c956c0d94d9f.json)
