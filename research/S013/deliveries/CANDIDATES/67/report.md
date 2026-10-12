# EX097：Huber稳健回归表达原14项净机会

稳健回归中心仅通过盈利年份频率：年化−2.15%、回撤41.39%，盈利年份107笔达标，但收益、年度回撤、两个下跌年盈利均失败。

让极端样本少影响拟合，仍没有产生足够好的实际买入机会。107笔盈利年份交易超过要求，但2022亏损25.41%、2023亏损1.93%。拟合稳定和策略抗扰动是不同问题；Huber估计稳健位置，也不等于平均净收益。

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前9/10轮完成，剩余1，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：原14成熟年度训练采用固定Huber残差损失，再兑现完整账户，能否通过新版四门并保留必要大赚？

依据：平方损失中极端净回报可能主导系数；Huber只降低大残差影响，不剪裁或删掉目标样本。表达变化不等于新增价量信息或正条件期望。

最强事前反证：历史最高约10percent盈利交易贡献约43percent；EX086条件赚幅有局部支持，EX090每日净更新仍不足。Huber可能压掉达标所需少数大赚；EX050 winsor ACF已有失败，不能包装成相同输入处理的新发现。

机制职责：原14年度Huber净机会位置分数严格正入场，原EX080固定H时钟及执行，不沿C8880价格门。。centre holding4；原1..60完整域；2020起成熟过去年度训练、2021..26预测，2019仅暖特征、2020不入场。

对照：EX079原14和净ridge公开引用只作原中心元数据对照，不重新拟合ridge；C8880只完整经济/执行控制，不能声称OFF=C8880策略等价。

可得性：当前完整原14即可预测未知truth尾部；无未来test count gate；delta=1.345*training rawMAD，不乘1.4826。ConstantMAD0定义常值/零斜率，variedMAD0明确NA，不fallback。年度最终BH盈亏仅事后验收。

价格及执行：原510500HFQ固定2019-12-31锚0.2803、不另叠加分红、100万元、整手100、单侧10bp、固定1percent LimitBuyHold。。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：同开发池反复研究；Huber位置一般不是条件净收益均值，正分数不证明正条件期望；可能失去关键大赚。无新信息、参数优化、数据或独立封存样本。

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|C8880原规则|17.1346%|13.6187%|116|68/1152|3.541667|4.254279|19.5931%|0.9181%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|
|C9097|-2.1541%|41.3922%|178|107/1152|5.572917|6.528117|-25.4071%|-1.9294%|{'return': False, 'annual_drawdown': False, 'positive_buyhold_year_frequency': True, 'negative_buyhold_year_profit': False}|

同口径buyhold净年化7.2193%，收益门槛10.8290%。盈利年份为[2020, 2021, 2024, 2025, 2026]，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|2020|22.1693%|14.9712%|16.5873%|0.0000%|0.0000%|0|243|True|
|2021|17.2351%|9.7035%|8.2925%|-0.5293%|9.8728%|34|243|False|
|2022|-18.3203%|28.4105%|19.5931%|-25.4071%|26.4416%|30|242|True|
|2023|-6.2450%|17.2665%|0.9181%|-1.9294%|13.9225%|41|242|True|
|2024|6.9559%|18.5736%|65.0176%|2.0619%|12.7806%|24|242|True|
|2025|32.7098%|13.7975%|11.0762%|15.3067%|6.8988%|20|243|True|
|2026|0.9947%|18.7646%|-0.0388%|1.3800%|16.5313%|29|181|True|

## 有利结果与必要反证

有利事实：盈利年份107笔/1152交易日、每60日5.57笔，频率通过；2025收益15.31%、2026截至截止日1.38%，这些局部表现保留。所有年度训练成熟来源、原14及真实IRLS最终驻点均独立核验，没有未来年度选择。

必要反证：全期年化−2.15%、回撤41.39%，178笔总闭合没有形成净优势；2021−0.53%、2022−25.41%、2023−1.93%。少数大涨可能是策略必要收益来源，稳健位置并不保证更高条件净期望；MAD尺度/阈值不事后调整。中心失败，32点及双费未运行，Q10/Q90不可得。

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
|FULL_SAMPLE_FREQUENCY|6.528117359413203|AVAILABLE|
|NET_ANNUAL_RETURN|-0.021541215967301297|AVAILABLE|
|DRAWDOWN_MAGNITUDE|0.4139216489637412|AVAILABLE|
|FREQUENCY_MEDIAN|8.0|AVAILABLE|
|FREQUENCY_Q10|0.0|AVAILABLE|
|PARAMETER_RETURN_DEGRADATION|None|INSUFFICIENT_DATA|
|PARAMETER_DRAWDOWN_DEGRADATION|None|INSUFFICIENT_DATA|
|ROLLING_EXCESS_Q10|-0.18727182481397409|AVAILABLE|
|STRESS_ANNUAL_LOSS|None|INSUFFICIENT_DATA|
|PROFIT_CONCENTRATION|0.2790359728737662|AVAILABLE|
|策略减buyhold净年化差的成对bootstrap95%描述区间|[-22.9598%, 1.8205%]|AVAILABLE|
|PBO|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_RAW|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_EFFECTIVE|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|

仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。父OFF完整history和原C8880真实decisions全部字段精确相等；独立ON重建完整策略状态和决策。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。

## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。只执行已事前固定的最后一轮：联合岭回归、浅树、Huber三种当前分数至少两种为正才准入，并共用一个H持仓时钟。三模型同源且可能共同犯错，不借本轮结果换票数/权重；EX098完成后暂停。

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。


正式证据（项目根目录相对路径）：

- [plan.json](evidence/dc174dcd0ce52fd8eb3f9aa9a3423e5234dec0f3ed2dd849c7164f2052f2354d.json)
- [renewal_authorization.json](evidence/4f1ff9bc7a84bfbfb635e32d03ac5fe7aa03a146f1e92562f41e174bf634bd78.json)
- [.tmp/s013-new-goal/huber_net/audit_checks.json](evidence/4d3b9cf3aef2e6d204ce61d68a7887bf61db6ba6cfffe717725cebb0e68c7362.json)
- [.tmp/s013-new-goal/huber_net/audit_checks.py](evidence/2fa642e40c5b7ad1bc45357b4cfe757495d8ac3094330172ac7cf0bc4e1afd38.py)
- [.tmp/s013-new-goal/huber_net/audit_huber.py](evidence/9988729d6ffbf669c3f3a58147afa92d39e39ea2514b652bc2c92be5fbdff60e.py)
- [.tmp/s013-new-goal/huber_net/checks.json](evidence/3174dda4a0b5d02b550d38d000c5a9030d2a41e5ff11bb9031b6106d438896de.json)
- [.tmp/s013-new-goal/huber_net/checks.py](evidence/3240ba22039888b48ba01cef02023749b308bac9e5ca1de74ca57794209cd93d.py)
- [.tmp/s013-new-goal/huber_net/huber_kernel.py](evidence/fd948dc44a129bfcfee039d37154d9782f571e7ef84186af890875e46488e939.py)
- [.tmp/s013-new-goal/huber_net/native_contract_checks.json](evidence/5b267a699526f336bbf3f2d1c176a2fa27efb72dea9f92ff197ca7a2e34dbc2b.json)
- [.tmp/s013-new-goal/huber_net/native_contract_checks.py](evidence/4e3686d2ffdca119805283f2a2b450f8b14328fafd38d0bd10c4fa3d3a1ff85e.py)
- [.tmp/s013-new-goal/huber_net/native_driver.py](evidence/be8cbbedf75c967ef85efe0d52a0b248c3f8419ba507eccfe070e898d955ee2b.py)
- [.tmp/s013-new-goal/huber_net/native_driver_checks.json](evidence/8a6945817f991bd1243c4304a51ebe651c0610e65e1240262d9e459f041fca5d.json)
- [.tmp/s013-new-goal/huber_net/native_driver_checks.py](evidence/c30d3c4e4638843db683a1a0391e8e0f9724b82197789cde27b78f33db6c423f.py)
- [.tmp/s013-new-goal/huber_net/strategy_runtime/strategies/confirm_kernel.py](evidence/f4627a9a14984b4450afa12eb6e77e0b2060befea9b3d64602dcec9a675aa9b2.py)
- [.tmp/s013-new-goal/huber_net/strategy_runtime/strategies/confirm_net.py](evidence/19ac337b60a0b8ed5c024e8c76d80c22bf5764ea888d98ea97c85d860fc6d27f.py)
- [.tmp/s013-new-goal/huber_net/strategy_runtime/strategies/huber_kernel.py](evidence/fd948dc44a129bfcfee039d37154d9782f571e7ef84186af890875e46488e939.py)
- [.tmp/s013-new-goal/huber_net/strategy_runtime/strategies/huber_net.py](evidence/b95c602587661ff48961dd81463b82401b801457a56c81fbe4de807972a756a4.py)
- [.tmp/s013-new-goal/governance.py](evidence/1e8049fca6ac817cbdd885152e126d19659beadc18f9df3e8df50b825897025a.py)
- [.tmp/s013-new-goal/gates_v2.py](evidence/b04ad39f5e121ed4334644c26def970184708f3a379785c40f34603c844d8eb5.py)
- [.tmp/s013-new-goal/prospective_expression_review.json](evidence/1c96ae1375262de832657f2e4c4e2e641d1397480f1f4aa09aa579dc9e9d0a45.json)
- [.tmp/s013_confirm_execution.py](evidence/769e9cd21a405239f776d26bd33455e6e7a10d69de500d4d6e46fd869cb2ed64.py)
- [research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [research/S013/experiments/EX080_20261012/src/reproduction/82670d42c540_audit.py](evidence/82670d42c54092a50f2af74f95086ee5150d1bf9223415e7d0bad7ba49cbdc71.py)
- [research/S013/experiments/EX080_20261012/src/reproduction/02c394b35938_s013_confirm_execution_v3.py](evidence/02c394b35938f5ebc6e3fb7d3e44a07ee32428ca9a7904fb6802d149c6822048.py)
- [research/S013/experiments/EX080_20261012/src/reproduction/f78efbb0b1da_audit_driver.py](evidence/f78efbb0b1da9045187ab8ab7ba5dfa2afbb33f8df2826984a0131689b99ac52.py)
- [research/S013/experiments/EX080_20261012/src/adapter_revision2/strategy_runtime/strategies/confirm_kernel.py](evidence/f4627a9a14984b4450afa12eb6e77e0b2060befea9b3d64602dcec9a675aa9b2.py)
- [research/S013/experiments/EX080_20261012/src/adapter_revision2/strategy_runtime/strategies/confirm_net.py](evidence/19ac337b60a0b8ed5c024e8c76d80c22bf5764ea888d98ea97c85d860fc6d27f.py)
- [research/S013/experiments/EX066_20261011/src/opportunity_statistics.py](evidence/565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a.py)
- [research/S013/experiments/EX074_20261011/src/economics_reference.py](evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [research/S013/experiments/EX074_20261011/src/account_reference.py](evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [research/S013/experiments/EX074_20261011/src/execution_links.py](evidence/b7aa3220794b93000cffbde4410c97b95f3cc798f7348244b4113cbf7d5da198.py)
- [prepare.json](evidence/ddf17985cf83cde10387b295203c1eacaf70774353752e1f67c55fed7074d79f.json)
- [policy.csv](evidence/4a0a75fb7186e23f364af0d12988a08988c0abb13844dc03f55b343dc75dbe05.csv)
- [features.csv](evidence/9f0d8a9580426e86be765f84e6ddc3eb54246ae32a3ea28cc4ea06f355020147.csv)
- [labels.csv](evidence/9393d6f7ab6e1318507a4dbab5913a8775494c8cb5881b11e7557b48083ef434.csv)
- [scores.csv](evidence/0ab0448d13fd9bd9c1d08143e40e849b30e1d0ccf1d5e808e60a98d96316d081.csv)
- [fit.json](evidence/a39e20b8e0512f3bb8d2fa5c3fda4f9c4d0fe4ae0d4fc49732e23bd24916f81b.json)
- [independent_preaccount.json](evidence/644f70243996dad79200521d2cf7138814a069ac199b9cf90cd6667350877c5c.json)
- [verification.json](evidence/0086e792ceeedc6de1f79b3f79320e93cbabfa26a15d7683a005f48e8b5321c4.json)
- [audit_driver.py](evidence/be8cbbedf75c967ef85efe0d52a0b248c3f8419ba507eccfe070e898d955ee2b.py)
- [native.json](evidence/5e9559021a6e11edf8c6fef3687d5b7a641516cf79286f63515f8ed43b32e6df.json)
- [root_review.json](evidence/e95ad82dc89156232c79e8763ecaeb82000f47da4985489664476f00df87a75f.json)
- [statistics.json](evidence/618f892f30160a25f2bd97f7521230f7a8ddfad5b78ce00d3d3c8ccbcf793487.json)
- [budget_receipt.json](evidence/d932f5629470122ebfd623b546a36df033db0c19add50dc9c7cde0f954f55375.json)
- [native_failure_closeout.py](evidence/035e52d14ffc2d705f326d3fd2a27b99de313dd0f5f844286d472fdef491398a.py)
- [closeout_driver.py](evidence/2b0fc2dd492cb61b18abbe029e978c5642a90f7d653163ce27395af891f85e6a.py)
