# EX051 下跌入场两端缩尾收益相关对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

只将下跌入场过滤换为缩尾后的原相关：最近20个原日收益取第二小/第二大值作边界，将唯一外端限制到该边界，保留全部20样本及原时间顺序，再用原mean20/cov19/var20公式。中间收益幅度保留；原买入确认仍用原rawACF，市场状态、持仓期限、退出与全部原列保持。

原13数值中心、完整原域及同32坐标保持，但缩尾后的相关与原ACF统计含义不同，同0.1不代表同过滤强度。固定每端1为事前结构；没有删成18、插值分位数、改时间顺序、abs、截断相关输出、单位映射、缩域或降级。原isclose判定下requiredT零方差明确拒绝；父warmup不变。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原C2132 | 16.1572% | 14.1599% | 112 | 通过 |
| 既有多结构对照C4900 | 10.8889% | 21.2540% | 119 | 通过 |
| 下跌缩尾相关C6980 | 12.4007% | 19.7953% | 118 | 未通过 |

新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。

新中心逐项判断：年化收益通过；各自然年回撤通过；闭合交易频率通过；基准亏损年份仍盈利未通过。

与原中心的1636个信号日相比，目标仓位不同80天，最终信号原因不同117天；首次仓位分歧为2020-02-03 00:00:00。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。

新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。

## 最强反证与证据边界

原33完整观察路径核对：中心过滤判断不同86天，固定原既有状态的目标变化33天；32点共1167个目标作用点。次数不等于利润，只有新完整账户能判断经济效果。

最强反证：EX050只看排序，年化10.6801%、2022亏损3.3704%，未过收益和基准亏损年份盈利门；EX027原ACF均值/中位数也损害频率与2023。缩尾保留中间幅度，但仍可能删除有用的孤立跳涨跌，不能先认定是降噪。19相同加1孤立或18零加两极值能缩成零方差；两端有同值时也可能完全不变。原市场状态与H敏感性仍在。

策略、独立sorted/list-clamp原相关公式/原路径审计与原13域参数展开的聚焦合成检查通过；纯夹具失败及修正保存。父warmup不变，完整历史先计算后取信号日；无缺失填补。纯计算验证不代替经济目标。

完成判断：{'center_four_gates': False}

本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、确认天数网格或缩窄参数域。

新增机制业务账户1、实际评价2；新增参数业务账户0、实际评价0；精确复用机制对照2、参数对照0。重复评价仅核对串行/spawn一致性。

反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/47/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/47/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/47/evidence/97f98b25d3b53eb9d0a10e3b9e81c104130fc5c12b099d163398e99daf288355.json)
- [plan](../../../assets/deliveries/CANDIDATES/47/evidence/22c1824db0fa8e7632836639ed39b6650c1d36a25a97a65f3987907e63eaa460.json)
- [observed-winsor-acf-effect](../../../assets/deliveries/CANDIDATES/47/evidence/a9d0dd26f497ec8b3b1ac7cf52895102cd5637840a10e1628e7f1a4afc692380.json)
- [effect-method](../../../assets/deliveries/CANDIDATES/47/evidence/816c8d1250a3381678875debc4fe41286bcfb276123fe68eca336257d1019951.json)
- [geometry](../../../assets/deliveries/CANDIDATES/47/evidence/082bc87669fd99a13668ed046f3431baf8853fc1e7cb56d1fc65a07834ad9608.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/47/evidence/7ac586fa56cd9bf6e86e81a2a0e03a65a840b20ddae33de24fd1eb8d8f4db234.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/47/evidence/d87ffcf2d8b30ca1a50505bfec4b384cd805cf51fc092ec800d48b1a0c56d7b2.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/47/evidence/d4fa20de601a2c17efcf2a4789d63551464137dcdd966f92d4558b62d2bf3a86.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/47/evidence/644234e3e746963234f79d88ce6a1f904b6e196544a296762b8e4c1b1570e2c8.json)
- [protocols-effect-method-reference](../../../assets/deliveries/CANDIDATES/47/evidence/877f2e1c6bed344319a8513b39862390c446a1f517f31cb23dd29b44d8a66fce.json)
- [protocols-effect-reference](../../../assets/deliveries/CANDIDATES/47/evidence/7f579c8de0522e854b4e740801f4f86bd501cb26ed97101671c6b13ee2afa1f8.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/47/evidence/908b85f944c9c14f67cd7ab590da9d89aead842203bee4a5ef2f9b8f3a3709bf.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/47/evidence/a64d4e44bc425f17853555779b587323b645c04b5fed0fc0c1153cfd9fc2ff9b.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/47/evidence/361553da6b6f4fc167af2d045b1f041b05eebf0fa00ed551bef2fb9fd0458b56.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/47/evidence/ea74bfb1909563c13cf1e13b8e94b188a29f6c5a3b71e93028f40e48661af4d7.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/47/evidence/803053162db587465f10459408e8c3ecb5466b55928ccd33a0281953241332a9.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/47/evidence/ffc234c366526fe22fda3a86485d298690ce56427e2c7c478598d1aed68e950b.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/47/evidence/b1a060f744482bef3fcfdf3e61671fe63c37ad9d3dbeaddc8ef43b3c329c03de.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/47/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/47/evidence/9aa443a5776bb324a439cb58f05c1d288465babde0cb8510f1b99a8b7d1c2ff3.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/47/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/47/evidence/383ab353aaba26529803231f3d6091fd84f3d76da3e3be7add6a624b139f4b11.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/47/evidence/ec784196b18a33e67d116fac1f10887fe6f45e87b05ce3868ccd5c2e1f604bdf.json)
