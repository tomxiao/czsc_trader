# EX052 下跌入场原相关与缩尾相关共同确认对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

保留原下跌ACF过滤，并要求固定缩尾ACF在同一阈值上也通过：min(raw,winsor)>=原bear.acf_min。缩尾只限制20日收益各端唯一极值，保留20样本时间顺序和原mean20/cov19/var20公式。原买入确认、rawacf1列、市场状态、持仓期限与退出保持。

原13数值中心、完整原域及同32坐标保持；一个原cutoff用于两统计量，阈值没有缩放或映射，但过滤更严格，不等价原强度。固定AND是结构选择，无额外权重/窗口/阈值搜索。requiredT无法定义缩尾值时严格拒绝，即使原过滤本会拒绝也不降级；父warmup保持。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原C2132 | 16.1572% | 14.1599% | 112 | 通过 |
| 既有多结构对照C4900 | 10.8889% | 21.2540% | 119 | 通过 |
| 下跌共同确认C7280 | 12.5897% | 14.1599% | 107 | 未通过 |

新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。

新中心逐项判断：年化收益通过；各自然年回撤通过；闭合交易频率未通过；基准亏损年份仍盈利未通过。

与原中心的1636个信号日相比，目标仓位不同27天，最终信号原因不同41天；首次仓位分歧为2020-02-03 00:00:00。全部日期与实际资金路径保存在完整账户及分析材料中，不由删除旧交易推算新收益。

新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。

## 最强反证与证据边界

原33完整观察路径核对：中心过滤判断不同37天，固定原既有状态的目标变化5天；32点共176个目标作用点。次数不等于利润，只有新完整账户能判断经济效果。

最强反证：EX051缩尾替换118笔、年化12.4007%但2022亏损3.1372%、2023亏损2.1294%，秩替换也损害2022保护。共同确认保留原过滤，但可能错过好交易或下降频率；原112笔只比最低110多2。原状态中心只删5个条件入场，32点删176，不能当作新账户交易或利润预测。原状态/H敏感性仍在，缩尾退化明确拒绝。

策略、独立sorted/list-clamp原相关公式与Python min/AND同阈值真值/原路径审计与原13域参数展开的聚焦合成检查通过；纯夹具失败及修正保存。父warmup不变，完整历史先计算后取信号日；无缺失填补。纯计算验证不代替经济目标。

完成判断：{'center_four_gates': False}

本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、确认天数网格或缩窄参数域。

新增机制业务账户1、实际评价2；新增参数业务账户0、实际评价0；精确复用机制对照2、参数对照0。重复评价仅核对串行/spawn一致性。

反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/48/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/48/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/48/evidence/0a7681a32fdf2fb6cd8e8c8ff934f56ff3a36bee5d61ff47ce9deed9923791dc.json)
- [plan](../../../assets/deliveries/CANDIDATES/48/evidence/47006acee6527392e2f68db1ce761cb7212952fdf522d07664d81cf0cb9551ca.json)
- [observed-consensus-acf-effect](../../../assets/deliveries/CANDIDATES/48/evidence/d4f1865b84fec58bf0e75ff24707b1c8f68a9d7abad538a08b9c7863406872fc.json)
- [effect-method](../../../assets/deliveries/CANDIDATES/48/evidence/d449e2979e555f54475ee7d269141879891bbb2767bf7d39e6eb956df59489ec.json)
- [geometry](../../../assets/deliveries/CANDIDATES/48/evidence/1b96adc8a9a33b349c19fd28226e7dbdd8097879823dea1dca0bfcaf79c6ad69.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/48/evidence/baa4b236038f332d0bf76a8a809c533be58cb05a4f7c3ccb0cfbaec9713af0d5.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/48/evidence/70ed1354f56d5e28a2df3663a23c9ea72b735e6e4396560a64671a3f32ceae0f.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/48/evidence/24a2a0ab13fed5f4bb88e285a8b9d988fc937dad9bc979f3df847cc48f70aefc.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/48/evidence/644234e3e746963234f79d88ce6a1f904b6e196544a296762b8e4c1b1570e2c8.json)
- [protocols-effect-method-reference](../../../assets/deliveries/CANDIDATES/48/evidence/0614e167ba1f65b4a9e33109fd7dd8b7348554e679a56f4f52307cfd205a35e3.json)
- [protocols-effect-reference](../../../assets/deliveries/CANDIDATES/48/evidence/be203a7f70a156aed0b0a11df61a9a10230627398ddfee47ab6e36b8cdf029f8.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/48/evidence/b5a0e742470fbfc2becb38207176b578475a4b5fb248d5daa779e8da2a3dea9c.json)
- [protocols-native-loss-actual-fill-diagnosis](../../../assets/deliveries/CANDIDATES/48/evidence/3a3a9c430482c9a14c614957f57101de23ccff6cb44a66c245eb3bb1c559cfb2.json)
- [protocols-native-loss-actual-fill-diagnosis-reference](../../../assets/deliveries/CANDIDATES/48/evidence/907cea53fbc4cf05a7aa60ab1126f833f24f98bffb8468c3ce63a3461745228e.json)
- [protocols-native-loss-diagnosis](../../../assets/deliveries/CANDIDATES/48/evidence/5f83100e6f967eac1fd1b190c3789948552d83f3925a6aacc66b78c612c2dd47.json)
- [protocols-native-loss-diagnosis-reference](../../../assets/deliveries/CANDIDATES/48/evidence/3bbeb56bff29adefc01bf4d255a83e2fdca412f69ae625ee75d0fd37b4d5c9f9.json)
- [protocols-native-loss-method](../../../assets/deliveries/CANDIDATES/48/evidence/1d76cc92486453aafffaef239a68244e1a321c9cfa3de7fee73b949afd3ea5f7.json)
- [protocols-native-loss-method-reference](../../../assets/deliveries/CANDIDATES/48/evidence/55100dfc85017963e67bcec177e0c3e29675fe9b0aaffd2fffff601fd6821f3c.json)
- [protocols-native-loss-method-v2](../../../assets/deliveries/CANDIDATES/48/evidence/6b6a3f770aa513c334a0e0e4fa6680c00f239d0fec46299da5867d792d76f8fe.json)
- [protocols-native-loss-method-v2-reference](../../../assets/deliveries/CANDIDATES/48/evidence/e99b26e90150978179cd9d2b0be70ac3659fd6f3263211119238133f6316d4a4.json)
- [protocols-native-loss-method-v3](../../../assets/deliveries/CANDIDATES/48/evidence/06dca5549eff52898de253727f4a6b5db429343c7f647e902b3411dc6d188ff0.json)
- [protocols-native-loss-method-v3-reference](../../../assets/deliveries/CANDIDATES/48/evidence/733f2e01fcd3a6a5a6845e825439291de0ca89e2feb390809d61fb1cf8c0c828.json)
- [protocols-native-loss-method-v4](../../../assets/deliveries/CANDIDATES/48/evidence/32c553437d1e1fcdfae40927c32829994c98cf5dbd0c2887b23115c976003726.json)
- [protocols-native-loss-method-v4-reference](../../../assets/deliveries/CANDIDATES/48/evidence/48707a11b2abb30159a45fc9a751313d15196f2e0c60cde3fbe3941e3705465f.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/48/evidence/96ebb8f5a58bf64e6463b1db851069b2ab186e7ca283a3d73a5e0c9e52fdc11f.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/48/evidence/4f30338c781dd7d2a8b204851106df02aa1f01ff53ae556f4a33f7a6f3b50e11.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/48/evidence/b8453961ddc22c7c11a26e426e478a401a3b5d05359543f072a3a3d43a9d2b1d.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/48/evidence/81434da7b0a2d8bab485e0dbcbf3f5201e6f291d5818fa319bdd462df5c22347.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/48/evidence/01492d257be9fecb0d02d5b47899fbcd322c4b7f6b05d46fdc3833086be2be14.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/48/evidence/b1a060f744482bef3fcfdf3e61671fe63c37ad9d3dbeaddc8ef43b3c329c03de.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/48/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/48/evidence/183920b476b7dd3eb079deca6ceb7002db6fbc6c61a5b0a8ae924e60009efad9.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/48/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/48/evidence/e3d43920f3e85d0359b8536fd2804e217a611dd9112139d42bb1f081c1319f7c.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/48/evidence/928f4516712961c9402b0e882e6016ed9105b39e2f66b716f32887eb2ee06676.json)
