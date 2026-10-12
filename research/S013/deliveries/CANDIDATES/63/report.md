# EX093：机会窗口独立计时，能否减轻参数引发的连锁变化

独立市场TIME时钟未改善中心经济：净年化12.50%、回撤19.19%、盈利年份67笔不足77，2023转为−0.61%；收益/逐年回撤两门通过，另两门失败，停止固定表达。

通俗说，从市场机会出现时开始计时，确实让计时不再跟着买入日期改变，但晚买可能很快到期。独立计时也会改变下一笔买入和现金路径，实际收益变低、回撤变大；减少状态依赖不等于稳健达标。

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前5/10轮完成，剩余5，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：保留C8880买入确认及其他退出，仅使TIME由不依赖实际入场的市场episode计时，能否减少路径耦合且满足新版四门？

依据：只读表达覆盖评审显示交易接受才启动计时会使过滤扰动改变后续TIME与重入；独立市场episode尚未按此完整政策验证。这是结构假说，不是新增价量信息。

最强事前反证：市场episode早于实际入场，迟入场可能剩余期限很短、失去盈利年机会；旧刷新/周期/提前退出已有失败反证，降低状态耦合不等于经济或32点改善。

机制职责：原0/1策略TIME时钟的固定市场episode表达，买入与其他退出保持原职责。原bull H8、bear H4业务参数改为市场episode年龄，合法1..60域完整保留，无新数值参数

对照：同源C8880原完整参数及父策略；episode_enabled=False父全部history与旧native决策逐字段精确核验

可得性：仅T已知完整价格/原确认/资格及市场observer，不使用当年最终盈利标签；T决策T+1执行

价格及执行：原510500HFQ固定锚、不叠加现金分红、100万元整手100、单侧10bp、固定1% LimitBuyHold及原数据。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：同开发池反复研究；原数值坐标相同但H职责变更，旧扰动账户不能作为新策略扰动；中心通过不代表32/32

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|C8880原规则|17.1346%|13.6187%|116|68/1152|3.541667|4.254279|19.5931%|0.9181%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|
|C9093|12.5008%|19.1853%|115|67/1152|3.489583|4.217604|12.3328%|-0.6097%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': False}|

同口径buyhold净年化7.2193%，收益门槛10.8290%。盈利年份为[2020, 2021, 2024, 2025, 2026]，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|2020|22.1693%|14.9712%|16.5873%|15.3004%|6.8519%|19|243|True|
|2021|17.2351%|9.7035%|8.2925%|7.0147%|2.7130%|12|243|True|
|2022|-18.3203%|28.4105%|19.5931%|12.3328%|10.0306%|25|242|True|
|2023|-6.2450%|17.2665%|0.9181%|-0.6097%|6.0356%|23|242|True|
|2024|6.9559%|18.5736%|65.0176%|54.8445%|15.1833%|21|242|True|
|2025|32.7098%|13.7975%|11.0762%|5.5302%|4.3919%|11|243|True|
|2026|0.9947%|18.7646%|-0.0388%|-4.5651%|6.3750%|4|181|True|

## 有利结果与必要反证

有利事实：中心仍有12.50%净年化，高于10.829%门槛；每个自然年回撤严格小于buyhold；2022实际+12.33%、2024+54.84%。不删除仍通过两门与正收益事实。

必要反证：原C8880净年化17.13%/回撤13.62%，新为12.50%/19.19%；2023由+0.918%转−0.610%，盈利年闭合68降67。计时只与市场独立，交易anchor/peak/TIME-BELOW记忆仍反馈；episode资格/范围/期限的参数边界也仍存在。未运行32，不能宣称路径或绝对扰动尾部改善。

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
|FULL_SAMPLE_FREQUENCY|4.21760391198044|AVAILABLE|
|NET_ANNUAL_RETURN|0.1250076557244597|AVAILABLE|
|DRAWDOWN_MAGNITUDE|0.19185301765979956|AVAILABLE|
|FREQUENCY_MEDIAN|4.0|AVAILABLE|
|FREQUENCY_Q10|1.0|AVAILABLE|
|PARAMETER_RETURN_DEGRADATION|None|INSUFFICIENT_DATA|
|PARAMETER_DRAWDOWN_DEGRADATION|None|INSUFFICIENT_DATA|
|ROLLING_EXCESS_Q10|-0.20271366268513172|AVAILABLE|
|STRESS_ANNUAL_LOSS|None|INSUFFICIENT_DATA|
|PROFIT_CONCENTRATION|0.44629069883047284|AVAILABLE|
|策略减buyhold净年化差的成对bootstrap95%描述区间|[-11.3633%, 20.0399%]|AVAILABLE|
|PBO|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_RAW|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_EFFECTIVE|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|

仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。父OFF完整history和原C8880真实decisions全部字段精确相等；独立ON重建完整策略状态和决策。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。

## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。下一不同职责检验是先取得已知信号浮盈后再锁存入场锚保护，控制原其他规则，明确该锚不是实际成本或保证保本；不调整本轮episode期限来救援。

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。


正式证据（项目根目录相对路径）：

- [plan.json](evidence/2d96f8b4cff5dbd833555a266768df62b153bb3607cdec1cb3cdbf28c9227dc8.json)
- [renewal_authorization.json](evidence/4f1ff9bc7a84bfbfb635e32d03ac5fe7aa03a146f1e92562f41e174bf634bd78.json)
- [.tmp/s013-new-goal/episode_clock/audit_checks.json](evidence/011956a667e7f45faa51ad7f0abc0710c03a961941597c94e5b3cff94edcaf12.json)
- [.tmp/s013-new-goal/episode_clock/audit_checks.py](evidence/7a90bd21a4739d16b6e8dee6175a8cd00aa372a85e0a2a2ef44cd572cc390a34.py)
- [.tmp/s013-new-goal/episode_clock/audit_core.py](evidence/971156c24dcdcec8a9e7eceba4ef52e527827ad63e5f54abdf1c51b96c58e23b.py)
- [.tmp/s013-new-goal/episode_clock/checks.json](evidence/a60a2b9704c2b89530c480a772ae23362cad3c83598782953400729840e80c15.json)
- [.tmp/s013-new-goal/episode_clock/checks.py](evidence/1b64c4bac681251dbe66306fa368eb0db7b17ffc0be5964bad1f6f649e9d57fe.py)
- [.tmp/s013-new-goal/episode_clock/native_driver.py](evidence/cfedb8d9ab801579cb126ebbe982611e1a7b45ee8d1da421325bd8f4c6d160f8.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/adaptive_range.py](evidence/f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/boundary_bear_recovery_range.py](evidence/3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/confirmed_range.py](evidence/b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/episode_clock_range.py](evidence/980a69daa2128b13297fc4d9f2e149b15340f9344f5e02a5827bb7010216c86c.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/policy_kernel.py](evidence/daf980c8a888f2e333b1537256f2d98d9936e28c4526a53d61a6d4808fcefa59.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/pureobserver.py](evidence/a41f1ae36eb28d3dae7f60da8866c4a582c16058312a151201c01bbabe4b632a.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/range_reversion.py](evidence/899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/reentry_confirmed_range.py](evidence/6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c.py)
- [.tmp/s013-new-goal/episode_clock/strategy_runtime/strategies/__init__.py](evidence/4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1.py)
- [.tmp/s013-new-goal/governance.py](evidence/1e8049fca6ac817cbdd885152e126d19659beadc18f9df3e8df50b825897025a.py)
- [.tmp/s013-new-goal/gates_v2.py](evidence/b04ad39f5e121ed4334644c26def970184708f3a379785c40f34603c844d8eb5.py)
- [.tmp/s013-new-goal/prospective_expression_review.json](evidence/1c96ae1375262de832657f2e4c4e2e641d1397480f1f4aa09aa579dc9e9d0a45.json)
- [.tmp/s013_confirm_execution.py](evidence/769e9cd21a405239f776d26bd33455e6e7a10d69de500d4d6e46fd869cb2ed64.py)
- [research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [research/S013/experiments/EX080_20261012/src/reproduction/02c394b35938_s013_confirm_execution_v3.py](evidence/02c394b35938f5ebc6e3fb7d3e44a07ee32428ca9a7904fb6802d149c6822048.py)
- [research/S013/experiments/EX080_20261012/src/reproduction/f78efbb0b1da_audit_driver.py](evidence/f78efbb0b1da9045187ab8ab7ba5dfa2afbb33f8df2826984a0131689b99ac52.py)
- [research/S013/experiments/EX074_20261011/src/economics_reference.py](evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [research/S013/experiments/EX074_20261011/src/account_reference.py](evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [research/S013/experiments/EX074_20261011/src/execution_links.py](evidence/b7aa3220794b93000cffbde4410c97b95f3cc798f7348244b4113cbf7d5da198.py)
- [prepare.json](evidence/8097575b30963682cccf71ad5db7627e84b6494515d7b158ddc482d6567cf396.json)
- [policy.csv](evidence/629dd5299ca208523d5b2aa58f4323654233863d5e49175ad3558c88d41e5472.csv)
- [disabled_policy.csv](evidence/a4f83bb470692b64b46511ffe4245381ae17b643773e3743ed4a2d96cb40e112.csv)
- [independent_preaccount.json](evidence/f72bbb7be498ab26ff9adb835019aec9ffd2431f1f1aafdefeab276a87cf6404.json)
- [verification.json](evidence/e4afcd343fca901a1f58f8000ae3725938786f94e2f6de3d9c93ddf18552a525.json)
- [audit_driver.py](evidence/cfedb8d9ab801579cb126ebbe982611e1a7b45ee8d1da421325bd8f4c6d160f8.py)
- [native.json](evidence/b8a15efc8641016b72662f24afb3d2a293962db267c824db2782ba6b9dbb7bc5.json)
- [root_review.json](evidence/2a261817ad9956f74b71ddec171d2fabc02d4d285e48a3cc5fbcc032d45b3321.json)
- [statistics.json](evidence/ebd83dd2d4df64ead6323cf81b66a827fd8eae6d0070e0414e0e20962adfd0aa.json)
- [budget_receipt.json](evidence/b69a7c95b2e65013905caa4eb68bc573bc2d4b6c0b73023cb28e3adcb9de15ac.json)
- [native_failure_closeout.py](evidence/035e52d14ffc2d705f326d3fd2a27b99de313dd0f5f844286d472fdef491398a.py)
- [closeout_driver.py](evidence/b2e08741366cb8db2f790f35b2513491ab1c1aea6d6688381516df176662d170.py)
