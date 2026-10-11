# EX055 原相关策略局部日内回升恢复相关失格机会

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

保留原策略全部入场与退出规则，仅增加局部相关资格恢复：空仓、当前下跌路线、上次最终下跌到期退出的信号价低于该次入场信号价且今天收盘高于开盘时，原相关性未达门的机会仍可在原区间、动量及买入确认全部通过后入场。原相关性通过的机会不受日内方向限制，持仓日无豁免。分类是信号价格比较，不能当作实际亏损。

记忆跨空仓、资格不满足及市场状态变化保留，任意路线成功发出入场信号后清空。持仓期限、全部退出优先级、费用及执行保持；不按日期或未来收益分类。原13数值中心、全域、同32坐标和父暖启动均保持；固定类别、日内方向及局部豁免选择仍有结构风险。

## 完整账户背景对照

| 背景与门控 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 四项目标 |
|---|---|---:|---:|---:|---:|---:|---|
| 原策略 | C2132 | 16.1572% | 14.1599% | 112 | +12.1687% | +0.2841% | 通过 |
| 历史均值相关+CLOSE门 | C4900 | 10.8889% | 21.2540% | 119 | +9.4200% | +0.5491% | 通过 |
| 原相关+BODY局部门 | C7880 | 13.0062% | 14.6157% | 108 | +3.2530% | +0.2856% | 未通过 |
| 原相关+局部ACF资格恢复 | C7980 | 16.8663% | 14.4246% | 118 | +18.9454% | -0.0252% | 未通过 |

新中心逐项判断：年化收益通过；各自然年回撤通过；闭合交易频率通过；基准亏损年份仍盈利未通过。

四行是按精确身份与完整原生账本认证的独立完整策略，三个旧账户不新增评价；局部相关资格恢复是本轮唯一新增业务账户。原相关BODY局部门即使未达标也完整呈现，仅作机制诊断，不成为参数面板或新增资格条件。全期回撤与逐自然年回撤口径不同，资格使用原逐年门。

新中心串行与spawn信号及双方五账本精确一致，独立公式与全部状态/入场锚点/分类审计通过，所有成交、现金、费用与年度权益分别核对。不同完整策略间差异不等于删除旧交易利润；信号入场与实际首次成交可不同，实际多次成交按全量账本核验。

相对原中心，目标仓位不同30天，原因不同44天；首个仓位分歧2020-11-09 00:00:00。

原33路径的条件机会计数在新账户运行前独立声明并留证，只描述每条旧路径自身的状态；投影不入场、不更新上下文、不回放资金，重复日期不能当作多笔新增交易。诊断工具曾因未识别执行账本action字段拒绝计数，该失败及新技术方法完整保留。

13坐标合成作用审计未发现删维、缩域、单位重映射或半径改变；局部恢复窗口会屏蔽相关门对入场的影响，但原资格标记和其他路径仍按原阈值处理。这是明确声明的条件机制，不能解释为所有市场下参数都不敏感。

新账户前的原路径条件投影：原中心24个候选日期，属于4段原上下文；33条路径合计974个候选日期，各路径15至46个。原中心执行年2023包含8个日期，不能解释为相同笔数的实际交易或正收益。

新中心未达原四门，不运行32点；新增和复用参数账户均为零。

## 最强反证与解释边界

原中心2023年低价到期后重入来源实际贡献+2.3049个百分点，而全年只有+0.2841%；该来源含有维持年度盈利的机会。全下跌价格方向门先前只剩96笔且2023亏损。均值背景CLOSE门中心达标，但参数较差一端收益和回撤均劣于原C2132；它同时改变相关算法及方向，不能当作本轮局部资格恢复的单项证据。局部资格恢复也可能引入坏交易，不能把低价退出自动当作实际亏损。

全取消ACF虽217笔，却2022亏损3.2809%、2023亏损9.1143%、全期回撤29.5711%；局部豁免同样可能引入坏交易。原相关CLOSE和BODY局部门均只有108笔而未达频率门；均值背景BODY局部门2024回撤19.7928%高于基准18.5736%。BODY与CLOSE机会不嵌套，不能从旧机会计数预言增加交易数。更早双相关共同确认年化12.5897%、107笔且2022亏损3.4613%，费用下降未抵消实际价格路径收益损失；据此保留原相关算法，本轮只改变局部再次入场条件。原112笔仅比最低110笔多2，2023盈利余量很小，频率与年度盈利的失败都会按原门完整呈现。

纯runtime、独立oracle、原13域参数辅助及33条合成完整路径互证通过，失败和修正证据保留。合成检查确认实现语义，不代替经济目标。反复使用已见S013开发池，未获独立市场验证；FULL只检验证据完整性。RSCH阶段三。

完成判断：{'center_four_gates': False}

本机制未满足原联合目标；保留负面结果，按实际原生路径继续机制反证，不追加年份例外或缩窄参数域。

新增机制业务账户1、实际评价2；旧中心精确复用3；新增参数业务账户0、实际评价0、复用参数账户0。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/51/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/51/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [B0-RAW-BODY](../../../assets/deliveries/CANDIDATES/51/evidence/c5da2788202b76d909adf5bba14fc5da3716be98bf4fb88bbc85b7252b7905a6.json)
- [N0](../../../assets/deliveries/CANDIDATES/51/evidence/90462cbc1be6b86ac691bee3f2f921d6c3db33e6e6b1d9ca12fd26b8e008707b.json)
- [plan](../../../assets/deliveries/CANDIDATES/51/evidence/83b493ac099e2ff3f4f79b245536f5cb1f6e5edddead35033f6ee41d043d28ee.json)
- [raw-below-reentry-method](../../../assets/deliveries/CANDIDATES/51/evidence/0b5d48a4c1395fe903a1ab1b7da6e6d7590f95dbfb6e69e43343ca7f61204f82.json)
- [original33-opportunity-projection](../../../assets/deliveries/CANDIDATES/51/evidence/640109597833ad0af54d802fae022d9f7ea21bcd20994641f9cfccfb047c41a1.json)
- [original13-parameter-applicability](../../../assets/deliveries/CANDIDATES/51/evidence/1b6bad0f8abda05d6a500060ed5539f0ed244a009d0f8cf6519a12418da19e8e.json)
- [geometry](../../../assets/deliveries/CANDIDATES/51/evidence/6d344825cf731d612361f1dfac99cb9bc6f157adf05d4b4a48ceb7582f9e49cd.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/51/evidence/191896dde36f1a927d939ef94668359cc86b8ba937c85a9b6c2692489d9558af.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/51/evidence/9d30599a7f37745e9477ace8ba4414948f96ad289c21c6b7f8ac5a7264382dac.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/51/evidence/006f496e2319652aa347712e2a255976b07c0badd7a96756a99e79851b24d4ad.json)
- [crosscheck-pure-prototype](../../../assets/deliveries/CANDIDATES/51/evidence/14cc0035afbf12b2cfde0672495980f2e7647875c721c0cf971f91e953265d18.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/51/evidence/af8e24435056264eb71c6a5ce145edc5c9579b48a9df9436d098f4c777113392.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/51/evidence/3b498df4b9e34c5de19602cdafc12c8d432b6dbac6d8a92f0cb58259c0683615.json)
- [protocols-method-reference](../../../assets/deliveries/CANDIDATES/51/evidence/7bd6e4aaeea9822cf6577d7940e29abfc837b284fc5c81edfb864c30db9e37a2.json)
- [protocols-parameter-applicability-reference](../../../assets/deliveries/CANDIDATES/51/evidence/5cd9a6b97f3a965702cf9402f1e25d0e8f135a63436a9fd9c116991cc35e2f5c.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/51/evidence/c11bd14ee5a573af8ea1ad91474f695d1309594ee83e66c84d29d56f0d74fd15.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/51/evidence/14107fc91a5a43e01f69a7993b87127a2085ed39d044b24b4fa68d4afb84cd40.json)
- [protocols-projection-failure](../../../assets/deliveries/CANDIDATES/51/evidence/b0acad3a31a1a53223dfd17918d463686f3238f5afac23325181ea4004cde7b0.json)
- [protocols-projection-failure-reference](../../../assets/deliveries/CANDIDATES/51/evidence/9d89ae4b7362374f4f4c44cf75d3e8b716d7e24619d9f6b23cf74b7be5b1e621.json)
- [protocols-projection-method](../../../assets/deliveries/CANDIDATES/51/evidence/5602176e668b364c7613aa17a059c8b7f29232f586059856eec57730a56974a1.json)
- [protocols-projection-method-reference](../../../assets/deliveries/CANDIDATES/51/evidence/ea881687745b0ae5ba6227e515e3f5eb8562c00e4b39cfe54737f81299108ccb.json)
- [protocols-projection-reference](../../../assets/deliveries/CANDIDATES/51/evidence/be973f13838cd673a4979cf29475679e61c39623d4d354a0f94c826870eaeffb.json)
- [protocols-projection-summary](../../../assets/deliveries/CANDIDATES/51/evidence/10cb14e9e7e6929a157430a36a18a4b1360c83e5e7d545962120c30e1502887b.json)
- [protocols-projection-v2-method](../../../assets/deliveries/CANDIDATES/51/evidence/01bb84d87cba2c5f98cd1ae6eefc0ef401346abd96c3d61dd8db84087e73206c.json)
- [protocols-projection-v2-method-reference](../../../assets/deliveries/CANDIDATES/51/evidence/4ee45000a2f4390a7c369407ba69c1ce4bbe8442be0eff359631b768227ac5aa.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/51/evidence/b020a6aaa3e324d8dea54a3ccf69587d7c09449b96fc1ed18efaed0208b0d05c.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/51/evidence/73b2dba9a2279da2a152ea069278fc06af6ea3569443ab7a27252c655d898489.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/51/evidence/5edf9b1b46931b3ed8ad4050450ba1a051ebf26bb20e9c97a1ad6ba395a942b6.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/51/evidence/dba93b869e52fe96755734e96779d89510698ebe7044019d68b7b409e75ee689.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/51/evidence/7b2ec2e27ffc401a9bd4ad56068ea2db5cbe6b9a3bde46f60c26df2b76428ce9.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/51/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/51/evidence/43a56e9ad525b6fc3f5908e8adfa7124e96ddd39871500c1bc09c0e43375e5c2.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/51/evidence/ab21061e59c3e068a4e91189221f1cc17405ea7ce92f5d90bb201bce978c47d1.json)
