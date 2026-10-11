# EX046 退出类别记忆跨市场段的最小机制对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

仅改变退出价格类别记忆的有效期：空仓遇当日上涨状态时，在当日判断之前只清除类别；持仓最终因下跌TIME退出但当日已是上涨状态时，不再保存类别。退出原因、路由与原确认上下文保持；原确认评分、按实际L计算的下跌自相关历史均值、入场价格条件、持仓期限和所有退出优先级均保留。

原13项参数、完整域与原数字中心保持。状态段由当日因果市场状态定义，未增加日期例外、等待期、新阈值或额外窗口；本轮不沿用EX045固定120天均值结构。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原C2132 | 16.1572% | 14.1599% | 112 | 通过 |
| 类别长期保留 | 10.8889% | 21.2540% | 119 | 通过 |
| 类别在市场段内有效 | 10.6245% | 21.2547% | 120 | 未通过 |

新中心使用自己独立的原生完整账户，串行与spawn预检的信号及双方五账本精确一致。旧两个中心逐身份和完整序列化精确复用；三者基准五账本精确相同，所有现金、成交费用与年度结果分别核验。

中心逐项经济判断：{'return': False, 'annual_drawdown': True, 'frequency': True, 'negative_buyhold_year_profit': True}

中心原生路径对照：{'signal_days': 1636, 'target_different_days': 7, 'reason_different_days': 12, 'first_target_divergence': '2020-10-14 00:00:00', 'changed_signal_days': ['2020-10-14 00:00:00', '2020-10-15 00:00:00', '2020-10-26 00:00:00', '2020-10-27 00:00:00', '2020-10-28 00:00:00', '2020-10-30 00:00:00', '2020-11-02 00:00:00', '2020-11-03 00:00:00', '2026-06-01 00:00:00', '2026-06-02 00:00:00', '2026-06-05 00:00:00', '2026-06-08 00:00:00'], 'basis': 'Two distinct authenticated complete native policies; inherited cash and decisions propagate separately. No trade deletion or counterfactual cash replay.'}

新中心未达原四门，不扩展参数点：准备、评价及复用参数账户均为零。没有用未达标中心生成虚假的相对稳健性结论。

## 最强反证与证据边界

事前只读诊断覆盖66条原生路径、107976个信号日；旧共用窗口与固定窗口组各26/33条路径存在跨上涨状态遗留类别的增量拒绝，累计135/137次，两个中心各3次。计数是原路径上的规则作用，不是盈利被错过的证据，也不是相互独立的样本。完整源、纯检查、覆盖检查的一次字段取值失败与显式修正均正式留存。

最强竞争解释：遗留记忆可能是有效保护；清除记忆也会增加市场状态阈值跨线的影响。原C2132没有这类新增类别记忆仍敏感，因此这不是已证明的主要病因。中心旧路径直接影响仅2020两次与2026一次，2023/2024直接拒绝为零；后续资金和持仓传播必须以本轮完整原生账户判断，不能删除旧交易后累加收益。

完成判断：{'center_four_gates': False}

本机制尚未满足原经济与参数敏感性联合目标。保留完整负面结果，以已认证原生路径的差异核对作用及竞争解释；不追加年份例外、记忆时长网格或缩窄参数域。

新增机制业务账户1、实际评价2；新增参数业务账户0、实际评价0；精确复用机制对照2、参数对照0。重复评价仅核对串行/spawn一致性。

反复使用已见S013开发池，未做独立市场验证。FULL只核验证据、身份与来源完整性，不替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/42/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/42/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/42/evidence/5e4c852f5dfc2246e3bc6e89d4ae3440680d4e69163f2fd0b6f2ea71d8d9e7ff.json)
- [plan](../../../assets/deliveries/CANDIDATES/42/evidence/0100a3201952a5bfa1aa3ec66b5452cea8b7b5f5ceae5a02617ca4ef2b2ee5ed.json)
- [native-context-diagnosis](../../../assets/deliveries/CANDIDATES/42/evidence/b556b986209a7dc1ff1463113ac26f93c3fcad51a443c40abaeedc3408da4be8.json)
- [geometry](../../../assets/deliveries/CANDIDATES/42/evidence/c8ea6038fcd47c19f75bb6de2b47c05a4f58b3135725b19bb68bbf3481e45ca7.json)
- [context-source-history](../../../assets/deliveries/CANDIDATES/42/evidence/bf36cb9e2e9cb504c403066f52a38473f640937a1668eb594f691fd91ee2a56d.json)
- [protocols-context-diagnosis-references](../../../assets/deliveries/CANDIDATES/42/evidence/1b7de6e004a15ff8433eb457f640afa2bb4728aa8bc35029ceb5fefd61427d9b.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/42/evidence/77b63f0b514c7050044d1e9b11a9b718784cbdffba3748cacceac23e8fa1b4a8.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/42/evidence/db19741ecf127052891830adc5dbbc6c2c3d60f381967302bdde6655489bcd90.json)
- [protocols-parameter-helper-checks](../../../assets/deliveries/CANDIDATES/42/evidence/edee89be7ad8ed846792d5493ac69f9b1cea3a5d4ab3e7253a8865e734b190d4.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/42/evidence/3a485daa6dcc620f45b1e4dcf8c148e72ab44fd2fd7d983b614e7ab5d6816eac.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/42/evidence/dc4d59b9982e46c637db9352eefa374d8bd66fed2fad4e8bad284c1e8a6c2581.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/42/evidence/9defe44f556953656760c6a6506639b3dfd915e4f78ebf03ef6acd61a3065c4b.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/42/evidence/d3decca7da7f6d3ab12c4dc1a70accd1d8630c225f6eee9b553deefa20b5e900.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/42/evidence/d7914fd4f9bc692b5b6aa4d5e5411590ca1b4a0500a7d618be73cbedb3151632.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/42/evidence/b1a060f744482bef3fcfdf3e61671fe63c37ad9d3dbeaddc8ef43b3c329c03de.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/42/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/42/evidence/075a2b0f816f0ca112ee47e2c36ce9158871b20b16e5838e7f6937f2397ab46b.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/42/evidence/69bbf5f78c30018dad4053b597ac7e0da32bdc02cc7fbb50eddc0f2d2f80c3b8.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/42/evidence/71168f9bb7aabfde884fff66908c79cd6b95736030ad0c2eb805266c03153f59.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/42/evidence/fb8dfe11f6feb108f27cbed9742b3d183084bc5cd549f3b4020373cd7721cea5.json)
