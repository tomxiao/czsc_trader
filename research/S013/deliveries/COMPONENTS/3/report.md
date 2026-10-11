# EX061：尾盘收复能否提供新的盈利机会

本轮阶段二组件检验与证据复核已完成。结论是：没有足够证据支持“尾盘收复越强，次日开盘买入后越赚钱”。停止这两个固定组件的正向策略化，不倒方向或扫阈值挽救本实验。稳健达标的策略目标仍未完成。

检验两项固定观察：最后60分钟价格变化 `log(C8/C6)`，以及收盘相对前6根30分钟收盘价的成交量加权收复程度。后者只是价位代理，不能称为真实成交均价、资金流或买方力量。固定14项旧信息控制、4个预测模型；2020初始训练，2021—2026逐年预测。主标签为买入后完整3/5日收益，1日为事前声明的辅助；均从T+1开盘到T+1+h开盘，不把买入前隔夜跳空当可赚收益。

全池为主，原C8880事前入场资格机会池为辅助。机会池由旧策略状态决定，不能视为独立新市场样本，也未按盈利挑选。信号日2020-01-02至2026-09-29共1635日，9/30仅供标签；原账户验收区间仍为1636日。使用原HFQ_RESEARCH后复权口径、2019-12-31锚点，未叠加现金分红。

| 已完成统计 | 尾盘变化 | 量加权收复 |
|---|---:|---:|
| 机会池1日收益，高组减低组 | −0.4500个百分点 | −0.4917个百分点 |
| 机会池3日收益，高组减低组 | −0.3432个百分点 | −0.6100个百分点 |
| 机会池1日控制后相关 | −0.0591 | −0.0481 |
| 全池1日原相关 → 控制后相关 | −0.0669 → +0.0119 | −0.1000 → −0.0199 |

最强反证是机会池收益方向与原假说相反，控制后关系弱，3/5日分年和非重叠相位方向不稳定。全池1日和5日增广模型均比旧信息模型更差。相关区间跨零描述不确定性，不是新增硬门。

最强正证也保留：全池3日尾盘变化控制后相关+0.0284，四个非重叠相位均正；加入该项预测误差下降0.0333%，幅度很小。机会池1日加入两项的预测误差下降0.6639%，六个预测年度中五年改善，但2025恶化2.1338%。这些局部结果支持继续追问机制，不能替代策略验证。

2022机会组尾盘低/高38/38、收复39/37，1/3日组差反向，5日翻为正。2023机会组尾盘15/11、收复19/21，至少一组不足，三种持有期均不能报告高低组差；不得声称该年已验证。2021、2025以及2026也有薄分组；完整逐年和全部非重叠相位保存在评审证据。收复指标Q75经常等于上端值1，高组人数不是固定四分之一；得分为1时成交量权重不再影响得分，不能将高组差全部归因成交量分配。年度组没有高低组重叠。

反向低组1日平均毛收益约+0.3443%/+0.3859%，可以作为“暂时卖压后短期回归”的前瞻反假说线索。但旧BODY（日内涨跌）与收盘位置已解释大量表象；新指标并非数学上等同旧指标，也没有证明独立盈利能力。低组1日不利波动还略高，风险模型退化，不能预设回撤改善。若继续，需要单独冻结反假说，与同样本旧日线反向信息做有限对照；不把本批事后发现包装成独立新证据。

从已发布CSV独立复算相关、精确持有日标签成熟日期、年度训练/测试数量、预测真值及合并/年度误差，共152项检查通过。纯组件及统计检查通过。固定统计的bootstrap与模型拟合未重复运行。COMPONENTS/3关联不可变证据，并以MANDATE/6及COMPONENTS/2为前驱执行FULL校验。

已见开发池的年度顺序预测不是封存验证；历史真实发布时间及修订未独立验证。首19日旧控制信息缺失未填补，标签尾部缺失保留；5个既有30分钟High/Low偏差不修复，本组件不使用它们。价格标签没有扣费用、限价成交、复投及持仓重叠，不能宣称提高账户绝对Q10收益、降低Q90回撤或提高32点原四门联合达标率。本轮新账户、参数扰动点、候选登记、平台和生产变更均为0，原经济目标保持不变。

下一步建议：保留反向短期回归为有限待证线索，先排除旧日线重复，再决定是否构建可执行策略。EX061正向组件检验已收尾，整个稳健达标目标仍在研究中。

## 正式证据引用

- [plan.json](evidence/1a5776fea86484f38cdb64807336206089b8421597a843db63312af239bf2ab5.json)
- [hypothesis_review.json](evidence/11059cfefd4d42c36299fba9f89e4dff637c97ddf3f17dd5cb0024519fffd8eb.json)
- [late_recovery_method.json](evidence/2fb79ff7d34ce3496a39c86830dbe2b9f8ea4e929332333c429f0246602be16f.json)
- [late_recovery_focused.json](evidence/6705e473733b8661979640c8de816906052229a2d6ceca68e53bc3ba88327d61.json)
- [statistics_checks.json](evidence/37edb1ad6e58b71fc77593e006e2efd0a342e56aff05ba30d2e81a9381223b7e.json)
- [late_recovery_component.py](evidence/3cd87ec20d4bd8f043aaf5448fc85ba8f486350d65cf0828249cf8650c9ea54e.py)
- [late_recovery_focused.py](evidence/897083bb0b3cb263a760449ea00bda55fc0d74f143f0dfef38888b1dde6e7bcf.py)
- [opportunity_statistics.py](evidence/326e269450d6d61168d4571861d946ca2753ddcd6daf951c14c679adcd0a07af.py)
- [statistics_checks.py](evidence/f0e713ce2214d5f6eb49a38a84072caf44cd799ca4c6caf1e16d555f5722e231.py)
- [run_opportunity_study.py](evidence/335b2d3f552c53b07f42fc22641031fe88b3f8e77921cb3a5638f2fa45d5ec20.py)
- [input_checks.json](evidence/e236498c1e4626a412dbe241de940080d8447184cd6ac3ecc6dd8a9d1de165dd.json)
- [features.csv](evidence/c555100471d51e1e34f8f050e91cfa11d6b7fe8c7b21243d79fe3e4dc6038346.csv)
- [labels.csv](evidence/93f4b58fdfbdeef844922137302d8f457c4cb1deb3d927ea667f4fac7651e40b.csv)
- [opportunity.csv](evidence/090742cf2ffbbc15d382569717debb45898ee5eb877d0310fab48899047133d1.csv)
- [tail_observations.csv](evidence/4db8eea0578bf12db5494f1a9fe6c674ecfbed9fb4e1dd2be0b6401fb669f513.csv)
- [statistics.json](evidence/7b6dfeeb8050c89dbae6138525dec07b496eae16b172d143aac77203da4cd6dc.json)
- [compact_statistics.json](evidence/45170962882a19a603a11c02cd313130520f26a3cc8a5dff0dc10ac8f2476489.json)
- [judgment.json](evidence/3015761e4820bc41ba5c456e8dddca467616c5cb18008ab01affa7d5533acee6.json)
- [verification.json](evidence/ba20fb6218f439756b414011acdb1ffd9633cb146571c0acb891b6e4a53382e3.json)
- [conclusion.json](evidence/9d3dc283bea69377e63de4a6016692fd1e7a2fcab14fa4b1db06c7eeb999ae44.json)
- [verify_results.py](evidence/f37b5ea6d14658e7cc0e4bb12fa762eea2da3db50d0495a4b843bfcfa2c92902.py)
- [write_judgment.py](evidence/ec25fb2a5dab93c5225f20ba4edd33308ece92da73a4492136980b578623d411.py)
- [deliver_study.py](evidence/feb43cd5e304e52d8cb756948015db6b1acb7be37c9584911c558a10ce58749b.py)
- [report.md](evidence/db959114481d7ae8712246fbf7386fb9ba3a40b86d68d924b36458429eab3486.md)
