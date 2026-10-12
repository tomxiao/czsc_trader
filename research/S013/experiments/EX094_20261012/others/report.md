# EX094：先取得浮盈，再启用入场锚价撤退保护

浮盈激活后锚价保护未改善中心：净年化16.31%、回撤15.42%，盈利年份仍68笔不足77，2023由正转−1.19%；收益/逐年回撤通过，另两门失败，停止固定表达。

通俗说，先赚过一点再撤退，也可能提前卖掉随后反弹的机会。它没有增加所需的盈利年份交易，而且后续重入和费用使2023转亏。锚价是信号入场Close，次日成交可能不同，不表示实际扣费保本。

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前6/10轮完成，剩余4，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：保留C8880原入场与全部退出，仅在先有足够信号浮盈后回到signal entry Close时追加退出，能否改善净余量并满足新版四门与全32点？

依据：与始终成本锚floor和普通peak trailing不同，先激活再回锚的单向状态可让早期回落继续原恢复路径，之后保护已经出现的信号收益。这是持仓职责结构假说，未增加独立市场信息。

最强事前反证：EX025/26成本锚退出曾割断反弹并损害2023；EX077价格周期失败；新增activation表面可能增加参数脆弱性，先有浮盈并不保证实际扣费后保本或改善。

机制职责：原0/1持仓的收益保护出口；原entry/confirmation/BELOW恢复与所有原exit优先保持。原bull H8/bear H4及所有旧域保持；accepted signalentry锁定过去L个包含T的logClose变化RMS，L10..60/multiple .5..3完整域；只有旧exit均未触发时检查prior latch及当前signal floor

对照：同源C8880原完整参数及父策略；profit_latch.enabled=False父全部history与旧native决策逐字段精确核验，不混合EX093市场episode时钟

可得性：仅T已知价格及原confirmation；signalentry Close锚不等于真实成交cost，sigma在accepted entry T锁而非原机会资格T；T决策T+1执行，年份最终盈利不供预知

价格及执行：原510500HFQ固定锚、不叠加现金分红、100万元整手100、单侧10bp、固定1% LimitBuyHold及原数据。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：反复已见开发池；signal entry reference不是实际扣费保本，T+1跳空、限价延后及费用都可能侵蚀收益；两个新增参数形成新15维扰动，旧13点不可冒充新几何或逐点因果；中心通过不代表32/32

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|C8880原规则|17.1346%|13.6187%|116|68/1152|3.541667|4.254279|19.5931%|0.9181%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|
|C9094|16.3137%|15.4198%|116|68/1152|3.541667|4.254279|18.4046%|-1.1859%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': False}|

同口径buyhold净年化7.2193%，收益门槛10.8290%。盈利年份为[2020, 2021, 2024, 2025, 2026]，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|2020|22.1693%|14.9712%|16.5873%|16.5873%|6.6318%|19|243|True|
|2021|17.2351%|9.7035%|8.2925%|8.2925%|3.5940%|14|243|True|
|2022|-18.3203%|28.4105%|19.5931%|18.4046%|6.8793%|26|242|True|
|2023|-6.2450%|17.2665%|0.9181%|-1.1859%|6.5979%|22|242|True|
|2024|6.9559%|18.5736%|65.0176%|65.0050%|10.0225%|20|242|True|
|2025|32.7098%|13.7975%|11.0762%|9.4743%|3.5334%|10|243|True|
|2026|0.9947%|18.7646%|-0.0388%|-0.0386%|4.5427%|5|181|True|

## 有利结果与必要反证

有利事实：仍通过总体收益门和全部年度回撤门；2022实际+18.40%、2024+65.00%；2020/2021与原规则精确相同，没有人为重算这些控制年份。

必要反证：CAGR17.13%→16.31%，全期回撤13.62%→15.42%，2023+0.918%→−1.186%，2025+11.08%→+9.47%；116总闭合及68盈利年闭合都未增加。它新增激活边界，不能由单向latch推断更强参数稳健；未运行32，Q10/Q90不可得。

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
|FULL_SAMPLE_FREQUENCY|4.254278728606357|AVAILABLE|
|NET_ANNUAL_RETURN|0.16313654921217124|AVAILABLE|
|DRAWDOWN_MAGNITUDE|0.15419802701667817|AVAILABLE|
|FREQUENCY_MEDIAN|4.0|AVAILABLE|
|FREQUENCY_Q10|1.0|AVAILABLE|
|PARAMETER_RETURN_DEGRADATION|None|INSUFFICIENT_DATA|
|PARAMETER_DRAWDOWN_DEGRADATION|None|INSUFFICIENT_DATA|
|ROLLING_EXCESS_Q10|-0.1902023553079541|AVAILABLE|
|STRESS_ANNUAL_LOSS|None|INSUFFICIENT_DATA|
|PROFIT_CONCENTRATION|0.43730483346487886|AVAILABLE|
|策略减buyhold净年化差的成对bootstrap95%描述区间|[-7.8993%, 24.6764%]|AVAILABLE|
|PBO|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_RAW|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_EFFECTIVE|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|

仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。父OFF完整history和原C8880真实decisions全部字段精确相等；独立ON重建完整策略状态和决策。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。

## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。下一轮改检验参与职责：仅在当日和前日均因果rawbull且严格正BODY时解除确认分门，保留边界及下行确认；不再调整本轮波动窗口/激活倍数寻找事后好结果。

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。


正式证据（项目根目录相对路径）：

- [plan.json](evidence/c1dff01611dccd901c747b2ed6e65da849bbc3bb5ffa0225157f13d0c09b6597.json)
- [renewal_authorization.json](evidence/4f1ff9bc7a84bfbfb635e32d03ac5fe7aa03a146f1e92562f41e174bf634bd78.json)
- [.tmp/s013-new-goal/profit_latch/audit_checks.json](evidence/89a0b5674a6444e889d28308e2958e280d803be1a5aef9cbad7889cd6425b6a3.json)
- [.tmp/s013-new-goal/profit_latch/audit_checks.py](evidence/b3daac4769a87879ec46d43001ff4a21b28595bb0a05914cfe23bee9d7728ce0.py)
- [.tmp/s013-new-goal/profit_latch/audit_core.py](evidence/6e9fd16a10525fe8f86b98794354879439afffe8dc19ac05aa47932e0643600d.py)
- [.tmp/s013-new-goal/profit_latch/checks.json](evidence/6de832d0898238b168ddecd3ca7837a2e7aa3b66790213f0d6807136997fa377.json)
- [.tmp/s013-new-goal/profit_latch/checks.py](evidence/de62e2284640902a3becc53d4940043f3c3fae11ffa2d64d3870af09f4bcbec6.py)
- [.tmp/s013-new-goal/profit_latch/native_driver.py](evidence/ec07c91b53566fa1bd26d97241e89ed0e50e140d8832ed90bba12139d7ed29e5.py)
- [.tmp/s013-new-goal/profit_latch/native_driver_checks.json](evidence/f333c24ddcdee92d91d71dd65ad4ca175782005e8b21c80cd76f8a136619dddd.json)
- [.tmp/s013-new-goal/profit_latch/native_driver_checks.py](evidence/f091ca5f9ecaadd10dc99487c51391a94e8ca849901e77084be73cd5d7f3b5cb.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/adaptive_range.py](evidence/f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/boundary_bear_recovery_range.py](evidence/3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/confirmed_range.py](evidence/b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/locked_sigma.py](evidence/e3300e99c081bdfb21888afe43bdca04676ac48e767dc02379b3e13e74e1b2c0.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/policy_kernel.py](evidence/67edead89d8dd9b561074c6b181d7f2cb71c0042d06835160894ed9f82319305.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/profit_latch_range.py](evidence/a705c0f95bce2a3c7dd7bf15a5135fcd6f0bd9526a86233d535bc4128a869079.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/range_reversion.py](evidence/899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/reentry_confirmed_range.py](evidence/6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c.py)
- [.tmp/s013-new-goal/profit_latch/strategy_runtime/strategies/__init__.py](evidence/4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1.py)
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
- [prepare.json](evidence/96f2c6dcaab94b3ea4176675054f6609fd117ef6542c202368fcb076a3c01fed.json)
- [policy.csv](evidence/53c71a8399100f776678e515c31d9b3dc46cad29b270c5243c019ba3ac899925.csv)
- [disabled_policy.csv](evidence/a4f83bb470692b64b46511ffe4245381ae17b643773e3743ed4a2d96cb40e112.csv)
- [independent_preaccount.json](evidence/a65c00c41c7d034a1f91c47b5cefd78cbbf0143314fb891d75898080e9613d57.json)
- [verification.json](evidence/8d607a5a7719d9e0a9e21e4a93a4459e90ba0196b0357632fbb05467db8ce7ba.json)
- [audit_driver.py](evidence/ec07c91b53566fa1bd26d97241e89ed0e50e140d8832ed90bba12139d7ed29e5.py)
- [native.json](evidence/bc364a1da7a403b4b5d3cb3aa1ff86b1c0110ab114564c8213520d7171b1b30d.json)
- [root_review.json](evidence/8ee836ae821a8cc64da1433e01e5d8226858a191804d46cefbab6651792f4f95.json)
- [statistics.json](evidence/9588fe97829a835439165af0c766caa5ceb2b33e458effa75f0aa448f31e1b0d.json)
- [budget_receipt.json](evidence/e193f37bb1f7bdd7be8a7355b16fc047dda2f1bb04e1835f946ad4d56ed6e1c1.json)
- [native_failure_closeout.py](evidence/035e52d14ffc2d705f326d3fd2a27b99de313dd0f5f844286d472fdef491398a.py)
- [closeout_driver.py](evidence/4a0db3bed5495199ff9cab6604003a2d56bddb28c9b42e6369e3871ce444673a.py)
