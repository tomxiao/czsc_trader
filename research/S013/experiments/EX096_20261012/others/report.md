# EX096：固定浅树表达原14项净机会

浅树实际中心仅通过盈利年份频率：年化−2.23%、回撤39.94%，盈利年份101笔达标，收益、年度回撤和下跌年盈利均失败。

浅树把原信息分成几组条件，确实找到更多可以买的时点，却没有买到更可靠的盈利机会。固定深度2、叶至少40个成熟样本，没有新增市场信息，也没有试别的深度救援。原净价签并不等于固定1%限价规则下的实际利润。

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前8/10轮完成，剩余2，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：原14信息按固定浅树表达局部条件净机会，并按原完整执行兑现，中心能否通过新版四门？

依据：连续加法表达可能遗漏多条件交互；固定depth2/minleaf40浅树只改变表达，不增加市场信息，也不搜索深度或阈值。

最强事前反证：EX080真实净年化仅约2.45%，EX086局部收益改善没有转成净机会；greedy树小样本分裂易过拟合，严格根改进还不能发现对称XOR。

机制职责：原14年度成熟训练、ECDF、训练叶净收益均值的完整0/1做多策略原型；不沿C8880价格门。。holding_sessions4中心，原1..60全域；年度扩展2020起训练，2021..26可预测；2019只暖特征，2020不入场。

对照：EX079原14及净ridge预测公开引用作为元数据对照，不新拟合ridge；C8880只作原执行/费用/完整经济控制，不做OFF父等价。

可得性：当前完整原14价量可得；训练signal过去年度且label_end严格早于年首T；未来当前标签未知仍预测，无未来test数量门。最终BH年标签仅事后验收。

价格及执行：原510500HFQ2019-12-31固定锚0.2803、不叠加现金分红、100万元、整手100、单侧10bp、固定1% LimitBuyHold。。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：同开发池、无新独立信息；阈值候选固定node内orderstat .25/.5/.75，严格SSE改善及固定tie顺序；合成交互不证明真实Alpha。

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|C8880原规则|17.1346%|13.6187%|116|68/1152|3.541667|4.254279|19.5931%|0.9181%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|
|C9096|-2.2295%|39.9410%|154|101/1152|5.260417|5.647922|-30.4477%|10.4085%|{'return': False, 'annual_drawdown': False, 'positive_buyhold_year_frequency': True, 'negative_buyhold_year_profit': False}|

同口径buyhold净年化7.2193%，收益门槛10.8290%。盈利年份为[2020, 2021, 2024, 2025, 2026]，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|2020|22.1693%|14.9712%|16.5873%|0.0000%|0.0000%|0|243|True|
|2021|17.2351%|9.7035%|8.2925%|1.3123%|10.7470%|47|243|False|
|2022|-18.3203%|28.4105%|19.5931%|-30.4477%|32.1837%|35|242|False|
|2023|-6.2450%|17.2665%|0.9181%|10.4085%|5.6087%|18|242|True|
|2024|6.9559%|18.5736%|65.0176%|1.2935%|18.7697%|22|242|False|
|2025|32.7098%|13.7975%|11.0762%|17.5129%|5.1514%|14|243|True|
|2026|0.9947%|18.7646%|-0.0388%|-6.7203%|15.2620%|18|181|True|

## 有利结果与必要反证

有利事实：盈利年份101笔/1152交易日，每60日5.26笔，明确超过77笔要求；2023实际收益+10.41%、2025+17.51%，保留局部年度改善。2020没有足够过去年度训练，按事前定义不交易、不用当年未来标签补训练。

必要反证：2022实际−30.45%、2026截至截止日−6.72%；全期年化−2.23%、回撤39.94%，虽有154笔总闭合但盈利质量不够。固定贪心树还无法识别无根SSE改善的对称XOR，合成条件组合可拟合不证明真实优势。中心失败，32/双费未运行，Q10/Q90不可得。

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
|FULL_SAMPLE_FREQUENCY|5.647921760391198|AVAILABLE|
|NET_ANNUAL_RETURN|-0.022294514839210078|AVAILABLE|
|DRAWDOWN_MAGNITUDE|0.39941015572518435|AVAILABLE|
|FREQUENCY_MEDIAN|6.0|AVAILABLE|
|FREQUENCY_Q10|0.0|AVAILABLE|
|PARAMETER_RETURN_DEGRADATION|None|INSUFFICIENT_DATA|
|PARAMETER_DRAWDOWN_DEGRADATION|None|INSUFFICIENT_DATA|
|ROLLING_EXCESS_Q10|-0.1661540189887389|AVAILABLE|
|STRESS_ANNUAL_LOSS|None|INSUFFICIENT_DATA|
|PROFIT_CONCENTRATION|0.31118548094998993|AVAILABLE|
|策略减buyhold净年化差的成对bootstrap95%描述区间|[-22.7323%, 1.5815%]|AVAILABLE|
|PBO|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_RAW|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_EFFECTIVE|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|

仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。父OFF完整history和原C8880真实decisions全部字段精确相等；独立ON重建完整策略状态和决策。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。

## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。下一轮检验Huber稳健回归是否减少极端训练样本的影响；不改本轮树深/叶阈值。最后按已固定三模型当前多数准入表达做独立对照，完成额度即暂停。

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。


正式证据（项目根目录相对路径）：

- [plan.json](evidence/0fbda54d57ed050471eccc3af9d4e92ed54cf761543e21a9fa796dba2d416163.json)
- [renewal_authorization.json](evidence/4f1ff9bc7a84bfbfb635e32d03ac5fe7aa03a146f1e92562f41e174bf634bd78.json)
- [.tmp/s013-new-goal/cart_net/audit_checks.json](evidence/9521879ad061557d0a8938dcf7bd3d17e738336cacc92d311fc7634643e9cdc5.json)
- [.tmp/s013-new-goal/cart_net/audit_checks.py](evidence/5ca3e8509d00458e1bfccd2318d134d22db3d45e8d43083ad7ab48ebbab169bf.py)
- [.tmp/s013-new-goal/cart_net/audit_tree.py](evidence/12b1b706212a668c4c08f36270c81002664132bd6a828d958c2311d9bfa0e0d3.py)
- [.tmp/s013-new-goal/cart_net/checks.json](evidence/d9ada41a4528281e46bc712c711070b895b932bf2cc83de9bbb275ff416a3944.json)
- [.tmp/s013-new-goal/cart_net/checks.py](evidence/472e56e21eeab964f668e1a29ddb976026a20d5b79a5c3257b5abddd480d1313.py)
- [.tmp/s013-new-goal/cart_net/driver_checks.json](evidence/67511940d8cf26fcb13f87b86759537a2ea31aa1821a4b2a03dc08e7f313db68.json)
- [.tmp/s013-new-goal/cart_net/driver_checks.py](evidence/77e1dc65932fb28acac13937d713cd029bf138fd5ef40764b8bc8730c9e45847.py)
- [.tmp/s013-new-goal/cart_net/native_checks.json](evidence/c7e88548b80d1b7607ce0d117b1ba7303fe4ed4286992b95b14918ab84cad25a.json)
- [.tmp/s013-new-goal/cart_net/native_checks.py](evidence/d9690ca2af36fc578834053a08d645e88b687602a859d9028abf17bfdf3f1737.py)
- [.tmp/s013-new-goal/cart_net/native_driver.py](evidence/f4be304e8551fe90c59566f56d4cfeba95311d4e738494ae5b981eb8cf9fcf14.py)
- [.tmp/s013-new-goal/cart_net/tree_kernel.py](evidence/6d1dd10f4778620795e4e574bdb383ea2673207dd785e3857fb542efe0d6cd4e.py)
- [.tmp/s013-new-goal/cart_net/strategy_runtime/strategies/cart_net.py](evidence/8b20ddafa392101697aaeac2abc4ccbeb6b3bf3f95edbe62abb124639d3dbd87.py)
- [.tmp/s013-new-goal/cart_net/strategy_runtime/strategies/confirm_kernel.py](evidence/f4627a9a14984b4450afa12eb6e77e0b2060befea9b3d64602dcec9a675aa9b2.py)
- [.tmp/s013-new-goal/cart_net/strategy_runtime/strategies/confirm_net.py](evidence/19ac337b60a0b8ed5c024e8c76d80c22bf5764ea888d98ea97c85d860fc6d27f.py)
- [.tmp/s013-new-goal/cart_net/strategy_runtime/strategies/tree_kernel.py](evidence/6d1dd10f4778620795e4e574bdb383ea2673207dd785e3857fb542efe0d6cd4e.py)
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
- [prepare.json](evidence/ca5150db017536f6f5acfb24934cf2f7136c7a2bdf01fea17cd3a934e6dfd0da.json)
- [policy.csv](evidence/3be78c9231736088f3bfe3113ce8838d50c7a47e5b18566355ab2cda8514f744.csv)
- [features.csv](evidence/9f0d8a9580426e86be765f84e6ddc3eb54246ae32a3ea28cc4ea06f355020147.csv)
- [labels.csv](evidence/9393d6f7ab6e1318507a4dbab5913a8775494c8cb5881b11e7557b48083ef434.csv)
- [scores.csv](evidence/7c5e83c9450a45680d8296b282938e0add789e00e7c545e2fb708c165ec53ee9.csv)
- [fit.json](evidence/f0105ee51a37b70285d573b0b3f930067911ebacb456712a1ad734f8c569e937.json)
- [independent_preaccount.json](evidence/4edaa47e63d59d8864bf4f50ac515e96c535025af14dd6701f0ee6be2df5ff3e.json)
- [verification.json](evidence/e27cb555963b82078f20948a7d81e51cbce89681b0d79be334100a9e3aaeafee.json)
- [audit_driver.py](evidence/f4be304e8551fe90c59566f56d4cfeba95311d4e738494ae5b981eb8cf9fcf14.py)
- [native.json](evidence/13bb853ab75d03ba2bee9057c80f7cb6f91ae0ded4736061566171887a4895ee.json)
- [root_review.json](evidence/4f4429f103e9b9619542149c027ea73c2e83b73765c4921f8153faaf807158dc.json)
- [statistics.json](evidence/655bfcb89ffb5d25223a606c41450b3f9881714b3580c8dba87915c2adf0e3c0.json)
- [budget_receipt.json](evidence/142dcf186063b2f35aeb9f024a597d9b9c5e0453b8b32234931572ef386c8403.json)
- [native_failure_closeout.py](evidence/035e52d14ffc2d705f326d3fd2a27b99de313dd0f5f844286d472fdef491398a.py)
- [closeout_driver.py](evidence/6470fbe8a8e29d77a34b5172f1857fa2bb2d8552ad9b929f02881f1b760124bb.py)
