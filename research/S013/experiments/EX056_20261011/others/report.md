# EX056 双价格方向条件的中心等价反证

本轮只读核验完成；改善参数敏感性的总目标尚未达成。

事前提出：在EX055局部日内回升恢复相关资格的例外中，再要求收盘高于昨收，检验向下跳空后的反弹。其他原13数值中心、全部上下文、确认和持仓退出规则保持；原相关合格买点不加门。

新的账本反证先于新账户实验出现：EX055的12个实际恢复机会（7次信号入场并成交、5次被原确认评分拒绝）全部已经收盘高于昨收。随后按事前独立方法认证旧完整原生身份、绑定行情和日历，重算新公式并逐日核对全部业务信号、资格、分数、上下文、目标与退出，证明中心路径完全相同。仅用于观察的entry_direction_up字段可以在非恢复日不同，完整保留差异，不能假称所有诊断字段也相同。

第一次实际只读核验因退出原因列的可空字符串存储类型与新公式object类型不一致而严格拒绝，失败和原方法完整留存。后继方法只对退出原因、路线、类别三列校验合法字符串与空值并归一存储空值表示，其余列仍精确比较。第二次在输出公共身份对象报告时因错误调用to_dict中止；再次事前声明后继方法，仅按公共dataclass四字段准确序列化。最终核验1636日通过，诊断方向字段103日不同全部保留；没有修改状态、公式、数据或经济规则。

因此不运行新金融账户，不登记C8280，不启动原32参数账户。对新规则的中心经济判断引用旧C7980原生结果；没有伪造新native账户，也没有从旧交易盈利相减推算收益。尚未证明32个参数路径相同。

## 实际既有账户证据

| 策略 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2023收益 | 原四门 |
|---|---|---:|---:|---:|---:|---|
| 原策略 | C2132 | 16.1572% | 14.1599% | 112 | +0.2841% | 通过 |
| 历史均值+CLOSE门 | C4900 | 10.8889% | 21.2540% | 119 | +0.5491% | 通过 |
| 旧局部BODY资格恢复 | C7980 | 16.8663% | 14.4246% | 118 | -0.0252% | 未通过 |

旧恢复规则2023价格收益增加约4,168.46元，费用增加约8,635.70元，全年净收益相对原策略减少约4,467.24元。全7年、1,636天、全部成交及尾仓归因完整保留；这不是把两笔额外交易简单删除后的预测。

相关性上升、清除跨上涨路线的上下文和上下文年龄都有实际反例：相关性上升仍有两笔恢复交易亏损，未上升也有大赢交易；原2023两个恢复上下文均未跨上涨路线。不能凭单个标签推断改善。

纯runtime272项、独立oracle189项及72项拒绝、原13参数辅助73项检查通过；纯证明及其失败修正保留。它们验证语义，中心只读等价核验验证此路径无增量，均不代表经济改善。反复使用已见S013开发池，无独立市场验证；FULL只检验材料完整性。RSCH阶段三。

下一步：保持原四门和原参数域，检验具有增量信息的最小机制；不重复已证明相同且未达标的中心账户。

新增金融准备0、账户评价0、参数账户0、登记0；信号公式核算使用既有绑定数据，不回放订单或现金。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/52/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/52/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/52/evidence/90462cbc1be6b86ac691bee3f2f921d6c3db33e6e6b1d9ca12fd26b8e008707b.json)
- [prospective-mechanism-method](../../../assets/deliveries/CANDIDATES/52/evidence/77f6bba6cbae13f054498e8cb216bb954db964ed2634bd234382615b8e1a95c0.json)
- [center-equivalence-method](../../../assets/deliveries/CANDIDATES/52/evidence/6c51d826da6bc88251125c4229e0ed64f44b2c734ec3ea580cbb37217cdd3628.json)
- [center-equivalence-v2-method](../../../assets/deliveries/CANDIDATES/52/evidence/168d2afa29e810e032593267ce36cf333722f390052d118e340d443b609663fa.json)
- [center-equivalence-v3-method](../../../assets/deliveries/CANDIDATES/52/evidence/48f92664a0747f894bd45a470ba867fc55bf22e834ee3222f770eb7e30675fdd.json)
- [center-equivalence-v1-failure](../../../assets/deliveries/CANDIDATES/52/evidence/9f88e72d63bbfe5e2efa608821d363d3ba08a824856730af2a1aec67f34c0a29.json)
- [center-equivalence-v2-failure](../../../assets/deliveries/CANDIDATES/52/evidence/20c6ec89534322d1cef6966d347fc79cb681b698fb8817423b7ba790e99bdb49.json)
- [center-equivalence-result](../../../assets/deliveries/CANDIDATES/52/evidence/d9b5be6eefc46282a763a2e22118e23b2d6cea6c0ce207f50a7add8c83a40cf7.json)
- [previous-two-account-loss-method](../../../assets/deliveries/CANDIDATES/52/evidence/693d16622106d6f970b526a89584b50421dba222ec54d387cc60d7abc7454cce.json)
- [previous-two-account-loss-result](../../../assets/deliveries/CANDIDATES/52/evidence/cc1335d321a6fa4e5a6a6a2395d57526e584b6292cfa75b88dbe5217ccfc1e9e.json)
- [pure-sources-and-proof-history](../../../assets/deliveries/CANDIDATES/52/evidence/bcebb1943524a9aa8d429ee023267163e07174d2c4cb7f4da30997a82c1c0380.json)
- [conclusion](../../../assets/deliveries/CANDIDATES/52/evidence/1826d5dbf3fe98b7637a2550217026678ebd9188d7e940910135edd485676a97.json)
