# EX095：连续上行且当日收涨时放过买入确认分门

中心三门通过但盈利年份频率仍失败：年化14.72%、回撤13.62%，盈利年份70笔低于77笔要求，停止本固定表达。

只在连续两天处于当时可知的上行状态、当天收盘高于开盘时，允许原本被确认分拒绝的买入。增加了两笔盈利年份交易，却降低了总体收益；增加参与次数没有自动带来有效参与。年度最终盈亏没有进入决策。

本轮完整研究已结束，总体“中心及标准32均通过新版四门”目标尚未达成。当前7/10轮完成，剩余3，本轮实际新增完整账户1，未重复经济评价，未运行新32或双费用。技术FULL和报告核对仅表示证据完整。

## 问题、方法和竞争解释

问题：保留C8880其他规则，仅对当前及前日rawbull且当T严格正BODY豁免score，能否恢复有效参与并满足新版四门？

依据：EX006/012全面解除确认增加频率但损害收益，当前窄scope与全面或bull单侧Off有合成差异；固定stable rawbull及严格正BODY条件检验恢复参与，没有新增信息。

最强事前反证：窄豁免仍可能引入低质量买入，早入场改变后续交易年龄、价格锚和资金，可能使2023薄净盈利转负；因果上行近似不是最终buyhold盈利年预知。

机制职责：原0/1策略的稳定上行参与窄score豁免；其他入场、全部退出、持仓H和锚保持原职责。原bull H8、bear H4仍是实际被接受的交易信号年龄；合法1..60域及原13参数完整保留，无新数值参数

对照：同源C8880原完整参数及父策略；bypass_enabled=False父全部history与旧native决策逐字段精确核验

可得性：仅当T和完整前日rawbull且Close>Open可免score；原opportunity/scorepassed仍保留诊断；不使用当年最终盈利标签，T决策T+1执行

价格及执行：原510500HFQ固定锚、不叠加现金分红、100万元整手100、单侧10bp、固定1% LimitBuyHold及原数据。同原510500.SH、2020-01-02..2026-09-30、1636交易日和2019已授权特征预热，完整signal首T2019-12-31冷启动，最后T2026-09-29。未新增数据、平台、依赖、生产操作或实际账户资金；“原生账户”指完整研究账本。

局限：同开发池反复研究；原13数值语义完整保持，固定结构豁免仍改变路径；旧扰动账户不能作为新策略扰动，中心通过不代表32/32

## 新版硬门及完整中心

净年化至少同期正buyhold的1.5倍、每自然年回撤严格更小、所有buyhold盈利年份合并每60日4真实闭合交易、每个buyhold亏损年实际净收益严格为正。中心及标准32全部要通过；最终年度盈亏只事后验收，未作为策略信号。全期频率仅诊断；历史资格保持原状。

|实际中心|净年化|全期最大回撤|真实闭合数|盈利年份闭合数/日数|盈利年份每60日频率|全期频率诊断|2022净收益|2023净收益|新版四门|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|C8880原规则|17.1346%|13.6187%|116|68/1152|3.541667|4.254279|19.5931%|0.9181%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|
|C9095|14.7220%|13.6178%|118|70/1152|3.645833|4.327628|19.5893%|0.9184%|{'return': True, 'annual_drawdown': True, 'positive_buyhold_year_frequency': False, 'negative_buyhold_year_profit': True}|

同口径buyhold净年化7.2193%，收益门槛10.8290%。盈利年份为[2020, 2021, 2024, 2025, 2026]，真实1152日须至少77笔闭合；按实际退出日归年，尾部未闭合不计。不从价格代理或意图数量推断频率。

## 全年度连续账本

每年从上年末实际权益开始，包含跨年持仓与所有费用；2026仅截止日。下表亏损年度分类仅用于事后核验。

|年|buyhold收益|buyhold回撤|原策略收益|新策略收益|新策略回撤|真实闭合数|实际交易日|回撤严格更小|
|---|---:|---:|---:|---:|---:|---:|---:|---|
|2020|22.1693%|14.9712%|16.5873%|14.3775%|8.4014%|19|243|True|
|2021|17.2351%|9.7035%|8.2925%|8.5624%|3.5942%|14|243|True|
|2022|-18.3203%|28.4105%|19.5931%|19.5893%|6.8802%|26|242|True|
|2023|-6.2450%|17.2665%|0.9181%|0.9184%|5.0762%|22|242|True|
|2024|6.9559%|18.5736%|65.0176%|57.9552%|10.0218%|21|242|True|
|2025|32.7098%|13.7975%|11.0762%|8.3167%|3.5333%|11|243|True|
|2026|0.9947%|18.7646%|-0.0388%|-4.8699%|8.2262%|5|181|True|

## 有利结果与必要反证

有利事实：总体收益、逐年回撤及两个下跌年份盈利三门仍通过；2022收益19.59%、2023收益0.918%；2021从8.29%小幅升至8.56%，全期回撤13.6187%微降至13.6178%，均保留但不夸大。

必要反证：盈利年份68→70笔，仍差7笔；总闭合116→118笔，年化17.13%→14.72%；2024收益65.02%→57.96%，2025收益11.08%→8.32%，2026截至研究截止日−0.039%→−4.87%。中心失败，32点与双费未运行，Q10/Q90及扰动达标率不可得。

## 最新五项自检的实际范围

完整中心失败，按事前计划停止参数账户和费用账户；没有用旧C8880扰动代替新策略32。参数绝对收益Q10、回撤Q90、32逐项/联合达标率和2倍费用影响不可得，不填0或通过。原3个账本诊断由公共SE按最新定义计算：rolling126/21/min20、最大ceil10%正闭合利润/全部正闭合利润、2000stationary成对bootstrap均块20seed13；完整搜索族缺失使PBO10blocks不可得，不填0。它们没有添加经济否决门。

|诊断|数值|状态|
|---|---:|---|
|FULL_SAMPLE_FREQUENCY|4.32762836185819|AVAILABLE|
|NET_ANNUAL_RETURN|0.14721987156907645|AVAILABLE|
|DRAWDOWN_MAGNITUDE|0.13617831058444785|AVAILABLE|
|FREQUENCY_MEDIAN|4.0|AVAILABLE|
|FREQUENCY_Q10|1.0|AVAILABLE|
|PARAMETER_RETURN_DEGRADATION|None|INSUFFICIENT_DATA|
|PARAMETER_DRAWDOWN_DEGRADATION|None|INSUFFICIENT_DATA|
|ROLLING_EXCESS_Q10|-0.19156330063110205|AVAILABLE|
|STRESS_ANNUAL_LOSS|None|INSUFFICIENT_DATA|
|PROFIT_CONCENTRATION|0.44449708737316995|AVAILABLE|
|策略减buyhold净年化差的成对bootstrap95%描述区间|[-8.9667%, 22.6092%]|AVAILABLE|
|PBO|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_RAW|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|
|DSR_EFFECTIVE|None|INSUFFICIENT_DATA：FAMILY_RETURN_MATRIX_NOT_SUPPLIED|

仅把已有诊断值如实列出；缺32/双费时不声称五项完整。统计区间不是未来收益概率或新增硬门，同池研究和多重选择风险仍在。

## 身份、执行和会计核验

先冻结科学机制、源码与完整数值域，再准备原生账户。父OFF完整history和原C8880真实decisions全部字段精确相等；独立ON重建完整策略状态和决策。输入请求、已有prepared资产、运行内容SHA、原执行/基准/HFQ身份均核对，0提供者调用。

独立真实订单首触、费用、现金/数量/权益、闭合周期及连续年度对账通过，完整公共原生序列化与缓存逐值一致；真实执行decisions与预账户核验全字段一致。只做多、现金非负、无杠杆、剩余持仓按实际账本保留，未强制清仓凑频率。原已知日线Low/30m低价差只审核相关真实订单，没有修补数据或另改执行模型。

源码合成/独立边界及相应修正说明见checks和audit_checks关联证据；它们在真实数据前完成，技术PASS不等于经济有效。未做仓库级回归。

## 收口及下一步

中心新版四门未联合通过，停止本固定机制，不邻窗/阈值/相位优化救援。接下来分别检验固定浅树及Huber稳健回归对原14项信息的不同表达，最后检验三种表达的当前入场多数一致；不再调整本轮旁路条件救援。所有阶段均保留新版中心及全部32点四门要求。

本轮没有合格新增候选，正式CANDIDATES交付以空候选集合保留完整负结果，不改变旧候选登记或原资格。新版中心和全部32门仍是最终验收条件，未因失败放宽。


正式证据（项目根目录相对路径）：

- [plan.json](evidence/aaa7985fa79e80d17570347d3cc705b16baf70f61fd3b41a4664152cc49f22f9.json)
- [renewal_authorization.json](evidence/4f1ff9bc7a84bfbfb635e32d03ac5fe7aa03a146f1e92562f41e174bf634bd78.json)
- [.tmp/s013-new-goal/stable_bull_bypass/audit_checks.json](evidence/06413edec791af07db274c16b159a0e2ce8fa7a3d121a2d04c205be127375e92.json)
- [.tmp/s013-new-goal/stable_bull_bypass/audit_checks.py](evidence/ac11ffb2a0d6312a8053e7e804d04140641073edb6e69c0fb7c279cea17d34b4.py)
- [.tmp/s013-new-goal/stable_bull_bypass/audit_core.py](evidence/b5752d82d0236c3afd3682f73ab0311b24831c9587e0198d0e33e91cf2ca6297.py)
- [.tmp/s013-new-goal/stable_bull_bypass/checks.json](evidence/ba6162c7a87a8273c6067c9894ef757bc12d04bae9a6b1459b0a0e00a4297d99.json)
- [.tmp/s013-new-goal/stable_bull_bypass/checks.py](evidence/cfc72fec1f1343739ff6f785acb3a5a03df2c005f855783db0e64a72d66cc5fe.py)
- [.tmp/s013-new-goal/stable_bull_bypass/native_driver.py](evidence/f4acd94d9ed018dda9f982db37cc7e4e73156e6c5d3e401dff5c553892db1d21.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/adaptive_range.py](evidence/f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/boundary_bear_recovery_range.py](evidence/3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/confirmed_range.py](evidence/b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/policy_kernel.py](evidence/81eec42acd52730c996a0376d86f796be202f7f149539ac3a3e7a649b12f093c.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/range_reversion.py](evidence/899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/reentry_confirmed_range.py](evidence/6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/stable_bull_bypass_range.py](evidence/8d85b90bcd81a3e64846edf2d1d9024cd05614f50741fd72547d0589222f4c43.py)
- [.tmp/s013-new-goal/stable_bull_bypass/strategy_runtime/strategies/__init__.py](evidence/4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1.py)
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
- [prepare.json](evidence/a6f13a50af77c894a572fbaf51be02bae16c0627ecc40a3df6827a5869557fc2.json)
- [policy.csv](evidence/603aaff21a158b1fb849e737df81d1fb4bd2eda5f961837b430b69705305996f.csv)
- [disabled_policy.csv](evidence/a4f83bb470692b64b46511ffe4245381ae17b643773e3743ed4a2d96cb40e112.csv)
- [independent_preaccount.json](evidence/f8fac681fd86a7c1975214dad59757abfde4d22a6eb963b99ef0aad03ec810f4.json)
- [verification.json](evidence/32d2e0e72cfbe8ae9a2734cb566cd01f9aec5946dab4348e1d6190fb73af9ef1.json)
- [audit_driver.py](evidence/f4acd94d9ed018dda9f982db37cc7e4e73156e6c5d3e401dff5c553892db1d21.py)
- [native.json](evidence/e02799603ab4db869e53805ef73e639169527c45700cc3f7872a12353098fbe3.json)
- [root_review.json](evidence/1a44d57f85dfaddde9ea22d2d4dd454d2a5ed3950684164bc25c0bd0e46c9e1f.json)
- [statistics.json](evidence/7e222d0009b42d850ca3118f25ab2c67b668bc0c5233f405a6f46959e2cdc1b4.json)
- [budget_receipt.json](evidence/221e29347e2709623211180d315a62b5eca436e8f68ca68a7a47fc74e395bc93.json)
- [native_failure_closeout.py](evidence/035e52d14ffc2d705f326d3fd2a27b99de313dd0f5f844286d472fdef491398a.py)
- [closeout_driver.py](evidence/e810575d92d50622663e7a1c4cc232f5c86f79c83992de36e34b98047c42dbee.py)
