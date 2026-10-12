# EX099：成交标签与数据覆盖

EX099已完成，总体策略目标尚未达成。旧价格代理与实际成交尝试总体接近；用更真实标签训练略微改善预测误差和全部正预测机会均值，却没有改善贪心单持仓选择。按获准额度继续EX100信息增量检验，不增加参数或模型。

## 对照和实际范围

A为原14信息，B增加中证500整体换手强度，C增加510500份额变化，D同时增加两组；新组各包括一个主项及其与区间位置的事前交互。0按原扣费开盘标签训练，1按实际成交合同标签训练，全部以实际合同尝试L1评分。固定ridge10、年度扩展训练、严格成熟共同支持，2020只训练，2021—2026预测，不优化期限或门槛。

两序列各1696行（60预热、1636开发日），逐日覆盖完整。仅2次供应商请求，0重试；未取得历史发布时间/修订凭据，新增信息统一滞后一个交易日，只能称条件探索。完整覆盖不证明信息当时可得，也不证明增量。

原1635T特征轴保留，1636执行日包含末日。单次尝试均从100万元空仓开始；公开SRT网格/整手规划及TXE成交、10bp费用、HFQ固定锚与1%合同保留。1635次尝试中1624买入、1620闭合、11未成交、4尾部持仓；两标签1631共同成熟，未成交归0但不是闭合交易，尾部不强制清仓。真实单次经济计算1635次，不是0计算；全窗完整策略账户、32点、费用账户及新增候选均0。

## 预测与选择结果

|表达|正预测成熟机会/均值|贪心成熟尝试/均值|真实闭合尝试|预测误差相对过去均值|
|---|---:|---:|---:|---:|
|A0|717 / 0.0478%|171 / 0.1662%|171|-2.3403%|
|A1|728 / 0.0560%|174 / 0.1520%|173|-2.1187%|

每个均值为独立尝试收益，不是复投账户年化。预测误差改善负值表示比过去均值更差。贪心仅按实际成交/取消/退出释放占用，释放日不再入场；采用各表达自己的路径，不把它解释为相同交易集合的利润增量。全部机会可以重叠，不得相加成账户可实现利润。

## 年度贪心结果：成熟尝试数 / 平均L1

|年份|A0|A1|
|---|---:|---:|
|2021|35 / 0.3627%|35 / 0.3627%|
|2022|30 / -0.7306%|30 / -0.7306%|
|2023|32 / -0.0276%|32 / -0.0276%|
|2024|25 / 0.0709%|25 / 0.1055%|
|2025|25 / 1.6295%|26 / 1.2634%|
|2026|24 / -0.1663%|26 / 0.0410%|

少于20个成熟选择的均值依约不作稳定性解释，显示不可得；逐尝试原值仍在证据中。自然年分组只描述结果；最终buyhold盈亏没有输入训练或决策。

## 全部主比较及不确定性

|主比较|MSE减少量及95%描述区间|正预测均值差及区间（百分点）|贪心均值差及区间（百分点）|
|---|---|---|---|
|A1-A0|0.00000190; [-0.00000015, 0.00000423]|0.00820377; [-0.01478282, 0.03271900]|-0.01417124; [-0.09267267, 0.06221587]|

固定共同交易日轴40日区块、500次、seed13，预测与既有选择成对重抽样，不重新训练或在拼接块内重做持仓。区间未经整个S013选择历史校正，是条件性描述，不是未来盈利概率或新经济硬门。所有五个固定相位、六种选择安排、被持仓占用信号和A原信息全可用预测附表均见statistics和selections证据，不挑最优安排。

## 研究判断、最强反证与限制

标签应保留，因为它明确了11次未成交与整手/首触差异；但这不是一项已证明的收益改进机制。两种训练的MSE仍比同支持过去L1均值更差，全部三项增量区间跨零。贪心选择下A1平均尝试收益由A0约0.1662%降至0.1520%，不能仅凭全部正预测机会的微小改善宣布解决问题。

L0/L1相关约0.9932、平均绝对差约0.05715个百分点；6次真正正负翻转，另11次未成交归0。更真实标签不等于更强信息。新组可能重复ETF成交量、反映恐慌或套利，不能把换手/申购方向直接当作看多。份额最大日变化约36.93%保留，尚无独立来源核验。

没有新的封存样本，原开发池已反复使用。本次固定线性及交互表达的支持/负面结果不能证明所有模型或供应商信息有效/无效，也不能代替S013中心及全部32点四门验收。

全日最低价包络含入场前及开盘退出后行情，不是真实持仓风险或账户回撤。公开TXE市价卖出为开盘成交，未验证现实卖出延迟。原5个分钟极值异常涉及23个尝试窗口（5个入场日），不删除或修补，映射另存；日线/30m覆盖核对每执行日8根。

## 验证、额度与下一步

模型26项、成交14项合成检查通过。12/36年度模型系数由独立训练秩、正规方程与预测重建核验，未另拟合；全部选择安排、配对均值及500次重抽样独立核验。公开账本8165逐日现金/数量/权益独立复算一致。FULL与报告副本核对仅表示交付身份和关联文件完整，不表示经济目标通过。

旧PreparedDataRef缺版本通过已保存正式迁移映射更正绑定，公开DFLS内容哈希保持；两次实数构造前停止及源码修订留证，实际标签仅构造一次，0新增行情下载。当前CLI没有历史experiment preflight/archive命令，采用公开创建、不可变证据发布、组件研究前检查及FULL交付验证，不冒称执行不存在的命令。

本轮实际年度拟合12次；额度完成1/2，剩余1。下一步按原批准范围执行EX100，研究目标不变。


正式证据（交付包相对路径）：

- [authorization.json](evidence/375c1e67cc823403200b1711a3f21be88fba989e556a1855c851eae3c6f9eb96.json)
- [approved_plan.md](evidence/3f633803d73892e8e81ca63458b7384232508655e29af7de6cbe9dacf0928f88.md)
- [.tmp/s013-stage2-20261013/governance.py](evidence/78166994450b218a25fefbcfc309e07d68bcb26a93c91505fb180c33adcac099.py)
- [.tmp/s013-stage2-20261013/driver.py](evidence/e97bf65ebd87ffc9bf76ee42d0e48b347df27eaed96136d0b24a5374d5914c32.py)
- [.tmp/s013-stage2-20261013/models/stage2_models.py](evidence/0067a25f83aa3b0d6466d96c49f066a57477e5144a1f3ce346ee778e8b7d3dcc.py)
- [.tmp/s013-stage2-20261013/models/synthetic_checks.py](evidence/df1f930a2ed160f2a2697af2a65cac051e7c4c43ce73f2489af0a423fc241eaf.py)
- [.tmp/s013-stage2-20261013/models/synthetic_checks.json](evidence/5bfc8e43a6093facdcfc5b67a529cf8a2f01bd32992a1e841bfe9dde2aedea4c.json)
- [.tmp/s013-stage2-20261013/execution/label_kernel.py](evidence/c4efc57e3024fed7e94e2c3c3ba35b950103ca5bfb46e99860437d931eaa7eab.py)
- [.tmp/s013-stage2-20261013/execution/synthetic_checks.py](evidence/9e394ac8635033b14616749baa0cd8ea78c343612dcc24580128f3f18f6296df.py)
- [.tmp/s013-stage2-20261013/execution/synthetic_checks.json](evidence/51d8e39df270ba2e1ef73d0021264bf08fd453bd1da96cdad7d9250eb7ea878c.json)
- [.tmp/s013-stage2-20261013/data/collect.py](evidence/66f44838275d299099cc3cb3e6820b50073456c0812e2a6fe18d01d89e53a1ba.py)
- [.tmp/s013-stage2-20261013/data/audit.py](evidence/688b0a0fb48423e1270da2564570cf3bacf2d7b0ce3da10400f07905583a826e.py)
- [.tmp/s013-stage2-20261013/inputs/input_checks.json](evidence/a343b10c93e25a6905a3850ea320678805a99f793026f24e5216b1c9178a2ff5.json)
- [.tmp/s013-stage2-20261013/data/data_review.json](evidence/e0c18734093883a227fff669b0448483f9f5c99d85a6dd8f7360105786b7e17d.json)
- [.tmp/s013-stage2-20261013/data/request_ledger.json](evidence/8dedadc96e4c8917d467c29884ceb67cb838bcb1901807e12e7e5dac1ecc194d.json)
- [.tmp/s013-stage2-20261013/data/response_01.json](evidence/3cbd1ea39d8506a7d21d0dea25892be81d59f73205cc078608f4cffdcae09234.json)
- [.tmp/s013-stage2-20261013/data/response_02.json](evidence/86f91d45aae0299dd075f347985dce6f897b3a5647c2bcf29ee6ec5fcdeea636.json)
- [.tmp/s013-stage2-20261013/data/G1_ordered.csv](evidence/097f58e5c5cedf843e0cf782f979739570cda1e907a5addef211627144ece918.csv)
- [.tmp/s013-stage2-20261013/data/G1_raw.csv](evidence/d219656809f0aa81f4d497f6ad227e8a95d5d6394fea5084f4de54e8ba35865d.csv)
- [.tmp/s013-stage2-20261013/data/G2_ordered.csv](evidence/2dcc64acdc7ab4938ec93ddebf7c377b7e66f13ad81e787799738f11aa4be62b.csv)
- [.tmp/s013-stage2-20261013/data/G2_raw.csv](evidence/f1f9ce1afc079101af298fa65b24b69e2b1baf44fcb44bd4319979c6cf34761b.csv)
- [preflight.json](evidence/f445b9fdbe8b41947ee109d60a2d512bd13236454803c1152b245cde4b4b1152.json)
- [actual-fit-input/.tmp/s013-stage2-20261013/inputs/features.csv](evidence/2aeb8cb63cc658a4efa6acc82ee5a4b8be9a731b08db37eba536bd393f6903c1.csv)
- [actual-fit-input/.tmp/s013-stage2-20261013/execution/model/labels.csv](evidence/5c59d1fdd335a66818602091781cda35b90890a77cea9a547081b392c12fcb4c.csv)
- [actual-fit-input/.tmp/s013-stage2-20261013/execution/model/attempts.csv](evidence/f627db85b901ed31070fdfe16fa3c447ff897b87bfb221655e5ae257fafded91.csv)
- [actual-fit-input/.tmp/s013-stage2-20261013/input_adapter.py](evidence/b866a6611fb546c4450435c6e65b692514e465baa1a629d4e256015ff79a95b4.py)
- [actual-fit-input/.tmp/s013-stage2-20261013/run_fit.py](evidence/8cc50c4ed8f5d06a8c3b12d45a9b4f6bea02cda6ee6fab20eb0020f0a44a2a8f.py)
- [fit_input_binding.json](evidence/79cd72bc7d52a82524eef7398c0c9321d77766fef41d1f29b11f8339aeda90c1.json)
- [bootstrap_peer_verification.json](evidence/3044d882f2b65c5aa139fc8df30724d13c4a1072b7dc95263a5a1fda3ca464a8.json)
- [statistics.json](evidence/dee6d2f0ce0b90c9e27e6aa9daf19e366e675717d9771cfdb951960e9aee946c.json)
- [study_attempt.json](evidence/d58eb9188c5e11f426285cf089116ec7b5d3084ab622e72ea0a98a68acbb5ae9.json)
- [study_complete.json](evidence/b0016f5cf08a087127d4103192531c6dd18867efb591f103e874239a4a2b2c5a.json)
- [verification.json](evidence/42e253742f00e7e0602a21ff2e218c16d2df5e46e5ea39fbccfe7df58bd30a3c.json)
- [all_scores.csv](evidence/b7e60e9b7ba0cadf6fd8aedd271cb9caffcdeadf37d401651959ba5217ea97b4.csv)
- [means.csv](evidence/32ec537e431a0d9f438d735e7dbe4c0de3146fb1a488676c4e24afb90c534bdc.csv)
- [reasons.csv](evidence/045913f312f4915bfb9dddd088d792c1d8961eec20cecd832dfad16abea2682f.csv)
- [scores.csv](evidence/b7e60e9b7ba0cadf6fd8aedd271cb9caffcdeadf37d401651959ba5217ea97b4.csv)
- [A0_clock_0.csv](evidence/9582751f0a3a38b2bdb7650088be40821439b2150d2600ef61579028ebaed798.csv)
- [A0_clock_1.csv](evidence/fe4e182615f0a988e4d00b470d8cd78141311f915caf90c4e6f7bf9f202b6d7b.csv)
- [A0_clock_2.csv](evidence/db6470189080075d2b8d496e486428c5e6f60f51783eb07f9aae5a4eed143089.csv)
- [A0_clock_3.csv](evidence/a7e6c2be288c81a534a020b805ba8fc3d195e3a9d2735c7e40b0c422cc0856b6.csv)
- [A0_clock_4.csv](evidence/20acfa84e8ec2ec554feff74d4209c60e267ee2dac5a5d2e5c7aa4e5392c6c3e.csv)
- [A0_greedy.csv](evidence/2232ea5ce5a2a4287111aa0af271c785e69c38d920c22ecf8cc80b1966600109.csv)
- [A1_clock_0.csv](evidence/f05591ba1278d95257888cc8dcd0dfee21549954ccb508fa748e1f2429792032.csv)
- [A1_clock_1.csv](evidence/ade5d84aa0a57fc9fe1daeaccce63bc0019a2905d9a820148bf4a39c5bfacafc.csv)
- [A1_clock_2.csv](evidence/427e2cac35a4b3d7a68b6acb5b25dd10a98a8f15b1080b8b34c16399fe7a505e.csv)
- [A1_clock_3.csv](evidence/3c48f612b39deaf9c7bb2f1c02928e2a94a7d5b11b54297e9143aaf8d656215f.csv)
- [A1_clock_4.csv](evidence/4c69673c5e723a7d8805ca4920c9efc29b26df6cf70b4a8cc84791d8925844d6.csv)
- [A1_greedy.csv](evidence/34746d380dabb7becefffcb36f5df9c2a45b7ee50c92ea182a5c6a1ea9bc5110.csv)
- [audit.py](evidence/9eb991aac9cfa3987b23275001ab9b61e0fb946b39f60d9c4258996c7629410e.py)
- [bootstrap_peer_audit.py](evidence/b60fef0e799de9f9c94f334773614fce55fa4e9e38988858ac2dff0b4d90cdb9.py)
- [driver_peer_review.json](evidence/b36ccd7010cae14d449f21daff0a1cc11d4de7a720d5d2d070c3bb00ccacb948.json)
- [execution_peer_review.json](evidence/0b2421659b75a26d18c29f13fb4c9e5a15762450efaf48dfb6d44f65addf1682.json)
- [closeout.py](evidence/c2c892bee6babba2740cfdd638379cb7bfe3726c53239c2afe5ae475b02cb0f0.py)
- [adaptation_audit.json](evidence/ff889c19b44e4b66c2faac933374ba9c1181c41ecc71b3451ec893b0d5893e14.json)
- [attempt_started.json](evidence/fad68ef8e14b2bb8a0d5114dca00cabca27ed2776d0cd4b42a52ab75a2f6df57.json)
- [construction_receipt.json](evidence/57ccbeaf22d06b9374d1f39917bd19ecfd65a25a9452be7288ced6d9e479d64e.json)
- [freeze.json](evidence/6fe73d51fda0522baed2fe275b3014639a88d492fc61452112b38fb4ff6f2029.json)
- [freeze_v2.json](evidence/3b4b545dcb77ab02c8ea85953af229b2afff0d0b12acdcf61b5874981177aa17.json)
- [freeze_v3.json](evidence/0d2e161ddc864c869bf1146bc2b6ac1b88c01632afb912d1b278efb360bfeebd.json)
- [input_preflight.json](evidence/438979a41e700ab9b7e5ddfe4a7494bc86493ce69d540877eb7fa3b723fd859b.json)
- [ledger_verification.json](evidence/daaa8f3b8983de6c6c2f8a278b08a3074aa784cf52fbb258e55926af94b6c3f1.json)
- [synthetic_checks.json](evidence/51d8e39df270ba2e1ef73d0021264bf08fd453bd1da96cdad7d9250eb7ea878c.json)
- [anomaly_attempts.csv](evidence/b6a293a7c4dc6941694067f87bb32f31c101a2ada59bcfab33b81e19c7c7976e.csv)
- [features_original14.csv](evidence/39705277cf4a395f0c16c16df9e1634d42153a79cfd4b9646c974e134e826169.csv)
- [labels.csv](evidence/cf8c6aee17434cf744e4df4f9d952f01174bb42c8983268c8cc95248d83b8b9c.csv)
- [ledger_account_daily.csv](evidence/83b76a424437c63624354a15fdc2001f2c9b62c3675f9f46665952c84cd12b89.csv)
- [ledger_decisions.csv](evidence/e7e8efb8bdd49469b1e72c45d8407c46fb223da78b8d1c3046e66e3553dd7bfb.csv)
- [ledger_fills.csv](evidence/ceed8b06e3397de4786203f84e5634d657c7babd5372ddfbe854b46f0758cfeb.csv)
- [ledger_orders.csv](evidence/573a2b6d4c59bae036f4675fa2d49df5397c2be51d8ca1e25cd1989f872415dc.csv)
- [ledger_trades.csv](evidence/f78fb25fa4e2dba5be109c8c3f40ab8dc973510afbdba91d0667f5a2bac77cf4.csv)
- [normalized_daily.csv](evidence/677ac340b722c5b5b1d5a984fd0cdd74543fd681447e0dcadd67541d8c17f152.csv)
- [normalized_intraday.csv](evidence/8b46c6907b5a781aadcd9de70f816333507ee5773207f374086a4301191b0c9c.csv)
- [raw_daily.csv](evidence/7573076a83b5491f8bb3bd8e5e245ebea273fe8e90b4adb185ead3f3289146f9.csv)
- [real_driver.py](evidence/dfed634d2ddfa337cd76ef9fce3ef917620cd0daa4df3e0cc214535ef463e386.py)
- [adapt_and_audit.py](evidence/c58e28740d61c61e5d7818895968aed783acebd5fc327bee1b089867585244d3.py)
- [budget_receipt.json](evidence/99c083b3c9cf2fd3d312c833b35b98d040ce3eec31431a15defe3ab67811dff1.json)
