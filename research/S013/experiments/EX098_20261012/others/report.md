# EX098：三模型当前两票同意准入及单持仓时钟

最后一轮实际中心仍仅频率达标：年化−0.73%、回撤43.16%，盈利年份115笔，2022亏损28.67%、2023亏损3.15%；十轮额度已用完，目标未达成，暂停研究。

三种模型共同同意，并没有消除它们共享信息中的错误。盈利年份交易115笔足够，2025赚23.96%仍难弥补下跌期损失。相比单浅树或Huber，年化亏损缩小，但回撤更大，不能视为满足要求的进展。

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前10/10轮完成，剩余0，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：原14联合岭回归/CART/Huber的当前固定2of3同意门，共用一个H持仓时钟，在完整执行下能否通过新版四门？

依据：异质平方损失加法、浅树条件交互、Huber残差表达可能有不同错误；只检验当前严格正分数同意是否减少错误入场，不添加信息、权重或参数搜索。

最强事前反证：三个模型共享同一原14和成熟标签，错误可能高度相关；多数票不是正条件净收益保证，可能减少盈利年参与或错失关键大赚。单模型已有失败不能用投票包装成新增独立证据。

机制职责：当前全3分数可用时至少2严格正才入场；只有一个H资金/持仓/age/退出状态，持仓期间票数变动或缺失不提前退出。。H4中心/原1..60完整域；2020起过去年度扩展训练，2021..26预测；2019只暖特征，2020现金。

对照：原14JOINT ridge所有14列且无罚截距，不是旧80确认单列；原96/97纯kernels字节原样。原79公开refs作元数据，C8880只经济/执行控制。

可得性：各模型仅年首前成熟完整原14样本、当前原14可得性；当前未知truth仍能预测。年度最终BH盈亏只事后验收，永不作为输入。

价格及执行：原510500HFQ2019-12-31锚0.2803、不叠加分红、100万元、整手100、单侧10bp、固定1percent LimitBuyHold。。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：相同信息且可能共同错；固定2of3不是expectedvalue，不能MSE对标签；不加权、不扫描票数、不救援缺失。不将开发池当独立检验。

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|C8880原规则|17.1346%|13.6187%|116|68/1152|3.541667|4.254279|19.5931%|0.9181%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|
|C9098|-0.7319%|43.1635%|185|115/1152|5.989583|6.784841|-28.6733%|-3.1543%|{'return': False, 'annual_drawdown': False, 'positive_buyhold_year_frequency': True, 'negative_buyhold_year_profit': False}|

同口径buyhold净年化7.2193%，收益门槛10.8290%。盈利年份为[2020, 2021, 2024, 2025, 2026]，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|2020|22.1693%|14.9712%|16.5873%|0.0000%|0.0000%|0|243|True|
|2021|17.2351%|9.7035%|8.2925%|11.2695%|7.1904%|40|243|True|
|2022|-18.3203%|28.4105%|19.5931%|-28.6733%|29.6624%|32|242|False|
|2023|-6.2450%|17.2665%|0.9181%|-3.1543%|14.1351%|38|242|True|
|2024|6.9559%|18.5736%|65.0176%|0.9343%|16.8655%|24|242|True|
|2025|32.7098%|13.7975%|11.0762%|23.9609%|5.3634%|23|243|True|
|2026|0.9947%|18.7646%|-0.0388%|-0.8586%|16.5304%|28|181|True|

## 有利结果与必要反证

有利事实：盈利年份115笔/1152日、每60日5.99笔达标；2021实际11.27%、2025实际23.96%，保留局部改善。三模型训练来源、全三可得条件、当前严格两票正准入和唯一H时钟均独立核验；没有按最终年度盈亏选模型或事后调票数。

必要反证：总体年化−0.73%、回撤43.16%，185笔总闭合；2022−28.67%、2023−3.15%。三模型同源价量和标签，投票不构成独立信息，Huber位置及票数也不等于净期望收益。当前两票准入和共用时钟不同于EX018虚拟持仓票决，但仍未产生达标净优势。中心失败，32/双费未运行，Q10/Q90不可得。

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
|FULL_SAMPLE_FREQUENCY|6.784841075794621|AVAILABLE|
|NET_ANNUAL_RETURN|-0.007319433467137815|AVAILABLE|
|DRAWDOWN_MAGNITUDE|0.4316349116795223|AVAILABLE|
|FREQUENCY_MEDIAN|8.0|AVAILABLE|
|FREQUENCY_Q10|0.0|AVAILABLE|
|PARAMETER_RETURN_DEGRADATION|None|INSUFFICIENT_DATA|
|PARAMETER_DRAWDOWN_DEGRADATION|None|INSUFFICIENT_DATA|
|ROLLING_EXCESS_Q10|-0.17152568416884198|AVAILABLE|
|STRESS_ANNUAL_LOSS|None|INSUFFICIENT_DATA|
|PROFIT_CONCENTRATION|0.28745649522887606|AVAILABLE|
|策略减buyhold净年化差的成对bootstrap95%描述区间|[-20.6803%, 2.9146%]|AVAILABLE|
|PBO|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_RAW|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_EFFECTIVE|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|

仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。本轮是新的学习策略，原C8880只作经济及执行对照，没有进行父OFF等价核验。新策略自身的预测、完整策略状态、真实决策及会计账本已独立核验。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。

## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。EX089–EX098已完成10/10，剩余0，无EX099；完成交付、副本与额度终核后暂停。保留C8880基准和买入质量约束、各轮局部有利反证；停止这批固定校准/更新/交互/退出/旁路/浅树/Huber/投票表达。若以后获得新授权，优先检验与实际成交及持仓占用一致的净机会定义，并先证明对旧信息有增量；这是待验证方向，不是本轮已证明的失败根因。

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。


正式证据（项目根目录相对路径）：

- [plan.json](evidence/5311d9311a8d421d8dffe7e60c8100c9c865096ccddda2c08114383d8b35c4dc.json)
- [renewal_authorization.json](evidence/4f1ff9bc7a84bfbfb635e32d03ac5fe7aa03a146f1e92562f41e174bf634bd78.json)
- [.tmp/s013-new-goal/model_agreement/agreement_kernel.py](evidence/ed888b2db31f683f29e56a4510f285151e5d49aaab3d9e04dfbe3d16db4169f3.py)
- [.tmp/s013-new-goal/model_agreement/audit_agreement.py](evidence/0891f986b57e7c9b39e58a5583fe3459415f7db4e77eb36d72c575b272560f37.py)
- [.tmp/s013-new-goal/model_agreement/audit_checks.json](evidence/8cb2763db2f13cfc612ba7330f4a39951f9ed292d0bc38e307de1d1ab27cacc0.json)
- [.tmp/s013-new-goal/model_agreement/audit_checks.py](evidence/c25fafd5bd9f7b11fb3abfce368690e6530dd24d6c42090f006e77f6058398d7.py)
- [.tmp/s013-new-goal/model_agreement/audit_huber.py](evidence/9988729d6ffbf669c3f3a58147afa92d39e39ea2514b652bc2c92be5fbdff60e.py)
- [.tmp/s013-new-goal/model_agreement/audit_tree.py](evidence/12b1b706212a668c4c08f36270c81002664132bd6a828d958c2311d9bfa0e0d3.py)
- [.tmp/s013-new-goal/model_agreement/checks.json](evidence/a4c618eb38dd77fa586ef0c9638881cb652d191cc416b0cae115eaf3b39cbc06.json)
- [.tmp/s013-new-goal/model_agreement/checks.py](evidence/a6c2bc442288a00787bedc7e69c13f5d7dded2a125ed981ebe5e3c296f5989f0.py)
- [.tmp/s013-new-goal/model_agreement/driver_checks.json](evidence/652121411f130ab8bda7f25a898a7abec49a188ee243493afc7615ca4f3fd8f4.json)
- [.tmp/s013-new-goal/model_agreement/driver_checks.py](evidence/34eda1eab9a0280819c4ff435dce1c8c909a479e5b712cc29c9307feb67a62b3.py)
- [.tmp/s013-new-goal/model_agreement/huber_kernel.py](evidence/fd948dc44a129bfcfee039d37154d9782f571e7ef84186af890875e46488e939.py)
- [.tmp/s013-new-goal/model_agreement/native_checks.json](evidence/119ca349f70d813ef9d7cac40f81ec68517e0c09d779ab71c497f9be314fc0f4.json)
- [.tmp/s013-new-goal/model_agreement/native_checks.py](evidence/4b5da3227e15ca1f59f349d93d744efc08a236d99fe97eccda8fb270c7029e85.py)
- [.tmp/s013-new-goal/model_agreement/native_driver.py](evidence/16e0936d4605963f37f658a14e87ffbfaca1df3adafcc06398abe7498a827793.py)
- [.tmp/s013-new-goal/model_agreement/tree_kernel.py](evidence/6d1dd10f4778620795e4e574bdb383ea2673207dd785e3857fb542efe0d6cd4e.py)
- [.tmp/s013-new-goal/model_agreement/strategy_runtime/strategies/agreement_kernel.py](evidence/ed888b2db31f683f29e56a4510f285151e5d49aaab3d9e04dfbe3d16db4169f3.py)
- [.tmp/s013-new-goal/model_agreement/strategy_runtime/strategies/confirm_kernel.py](evidence/f4627a9a14984b4450afa12eb6e77e0b2060befea9b3d64602dcec9a675aa9b2.py)
- [.tmp/s013-new-goal/model_agreement/strategy_runtime/strategies/confirm_net.py](evidence/19ac337b60a0b8ed5c024e8c76d80c22bf5764ea888d98ea97c85d860fc6d27f.py)
- [.tmp/s013-new-goal/model_agreement/strategy_runtime/strategies/huber_kernel.py](evidence/fd948dc44a129bfcfee039d37154d9782f571e7ef84186af890875e46488e939.py)
- [.tmp/s013-new-goal/model_agreement/strategy_runtime/strategies/model_agreement.py](evidence/0be9842afd450912045b3354b75381b414af177633e8c9d4514f950deb0345a8.py)
- [.tmp/s013-new-goal/model_agreement/strategy_runtime/strategies/tree_kernel.py](evidence/6d1dd10f4778620795e4e574bdb383ea2673207dd785e3857fb542efe0d6cd4e.py)
- [.tmp/s013-new-goal/governance.py](evidence/1e8049fca6ac817cbdd885152e126d19659beadc18f9df3e8df50b825897025a.py)
- [.tmp/s013-new-goal/gates_v2.py](evidence/b04ad39f5e121ed4334644c26def970184708f3a379785c40f34603c844d8eb5.py)
- [.tmp/s013-new-goal/prospective_expression_review.json](evidence/1c96ae1375262de832657f2e4c4e2e641d1397480f1f4aa09aa579dc9e9d0a45.json)
- [.tmp/s013_confirm_execution.py](evidence/769e9cd21a405239f776d26bd33455e6e7a10d69de500d4d6e46fd869cb2ed64.py)
- [.tmp/s013-new-goal/cart_net/tree_kernel.py](evidence/6d1dd10f4778620795e4e574bdb383ea2673207dd785e3857fb542efe0d6cd4e.py)
- [.tmp/s013-new-goal/huber_net/huber_kernel.py](evidence/fd948dc44a129bfcfee039d37154d9782f571e7ef84186af890875e46488e939.py)
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
- [prepare.json](evidence/2f90c3ffcf722d990b343f1112690a4a75961a2b5850736004e21a89f3476f17.json)
- [policy.csv](evidence/102aef6b02cd45ece2e05fe401738075df602fd74ad37a001d067cc6cdb8f50a.csv)
- [features.csv](evidence/9f0d8a9580426e86be765f84e6ddc3eb54246ae32a3ea28cc4ea06f355020147.csv)
- [labels.csv](evidence/9393d6f7ab6e1318507a4dbab5913a8775494c8cb5881b11e7557b48083ef434.csv)
- [scores.csv](evidence/9d3589b510c5f9aabbc9acd8c5183fe875f23f958d0f2b034400397061b45ac4.csv)
- [fit.json](evidence/c5b3c0c4d77292f6355b551456345a90de5c0176c1aa28c41c9d581d0328d6db.json)
- [independent_preaccount.json](evidence/03c8494f479e6da1219e1de335b70419ac89ff1b5d8861c33ba2aaade2c9684a.json)
- [verification.json](evidence/75192c9dedaf298f7e7c59ec58b83e30bbe931f55b32a12680e66e8176fdc7a7.json)
- [audit_driver.py](evidence/16e0936d4605963f37f658a14e87ffbfaca1df3adafcc06398abe7498a827793.py)
- [native.json](evidence/9cd62ba536a1026687003886f8aa6a514baddf017b99d3ce94cb5a095d886de1.json)
- [root_review.json](evidence/e9cd2e39bec1921d38322412a147414f08adf2bd0874d7ea48a8c98ad704c598.json)
- [statistics.json](evidence/c0125a2c368590735e704cd889b48e0d773b4ecbd28e8dbcaac5bd38e5658ef4.json)
- [budget_receipt.json](evidence/20e18a058fbd29622fda931df5a9161b1e1d02aa847303df24842486b12acdfd.json)
- [native_failure_closeout.py](evidence/36ba16e26a0526e1e9fa9d42e75673998e5e8a07ff12105c1cf411441f2722db.py)
- [closeout_driver.py](evidence/8e662bcb1dc7d9c96368aec385031f7bdf847a4ffc28d04cc0c1efcbff72b71a.py)
