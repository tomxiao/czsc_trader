# EX100：市场参与与份额变化的固定增量

EX100及两轮阶段二研究已完成，额度2/2、剩余0，现暂停。没有新增合格策略；这两轮是组件对照，没有完整策略账户或32点验收。成交标签更准确但不是主要救援方向；两个信息组的局部改善没有形成可信、稳定的交易增量。

## 对照和实际范围

A为原14信息，B增加中证500整体换手强度，C增加510500份额变化，D同时增加两组；新组各包括一个主项及其与区间位置的事前交互。0按原扣费开盘标签训练，1按实际成交合同标签训练，全部以实际合同尝试L1评分。固定ridge10、年度扩展训练、严格成熟共同支持，2020只训练，2021—2026预测，不优化期限或门槛。

两序列各1696行（60预热、1636开发日），逐日覆盖完整。仅2次供应商请求，0重试；未取得历史发布时间/修订凭据，新增信息统一滞后一个交易日，只能称条件探索。完整覆盖不证明信息当时可得，也不证明增量。

原1635T特征轴保留，1636执行日包含末日。单次尝试均从100万元空仓开始；公开SRT网格/整手规划及TXE成交、10bp费用、HFQ固定锚与1%合同保留。1635次尝试中1624买入、1620闭合、11未成交、4尾部持仓；两标签1631共同成熟，未成交归0但不是闭合交易，尾部不强制清仓。真实单次经济计算1635次，不是0计算；全窗完整策略账户、32点、费用账户及新增候选均0。

## 预测与选择结果

|表达|正预测成熟机会/均值|贪心成熟尝试/均值|真实闭合尝试|预测误差相对过去均值|
|---|---:|---:|---:|---:|
|A0|717 / 0.0478%|171 / 0.1662%|171|-2.3403%|
|A1|728 / 0.0560%|174 / 0.1520%|173|-2.1187%|
|B0|715 / 0.0646%|167 / 0.1234%|166|-2.5691%|
|B1|728 / 0.0783%|171 / 0.1093%|170|-2.3018%|
|C0|716 / 0.0492%|170 / 0.1516%|170|-2.4152%|
|C1|736 / 0.0456%|175 / 0.1674%|174|-2.1574%|
|D0|718 / 0.0517%|169 / 0.1085%|169|-2.6505%|
|D1|729 / 0.0537%|172 / 0.1257%|171|-2.3494%|

每个均值为独立尝试收益，不是复投账户年化。预测误差改善负值表示比过去均值更差。贪心仅按实际成交/取消/退出释放占用，释放日不再入场；采用各表达自己的路径，不把它解释为相同交易集合的利润增量。全部机会可以重叠，不得相加成账户可实现利润。

## 年度贪心结果：成熟尝试数 / 平均L1

|年份|A0|A1|B0|B1|C0|C1|D0|D1|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|2021|35 / 0.3627%|35 / 0.3627%|34 / 0.3358%|35 / 0.3627%|35 / 0.3871%|35 / 0.3627%|34 / 0.3609%|34 / 0.3609%|
|2022|30 / -0.7306%|30 / -0.7306%|28 / -0.9661%|28 / -0.9661%|30 / -0.8814%|29 / -0.8776%|29 / -0.9669%|29 / -0.9669%|
|2023|32 / -0.0276%|32 / -0.0276%|32 / -0.0163%|32 / 0.1354%|33 / 0.0133%|34 / 0.0002%|33 / -0.0552%|34 / 0.0002%|
|2024|25 / 0.0709%|25 / 0.1055%|22 / 0.4107%|23 / 0.4224%|24 / 0.1013%|25 / 0.2915%|22 / 0.4851%|23 / 0.4936%|
|2025|25 / 1.6295%|26 / 1.2634%|25 / 1.2925%|26 / 1.0071%|25 / 1.6295%|26 / 1.2630%|27 / 1.2928%|26 / 1.1779%|
|2026|24 / -0.1663%|26 / 0.0410%|26 / -0.1764%|27 / -0.2659%|23 / -0.2148%|26 / 0.0740%|24 / -0.4019%|26 / -0.1764%|

少于20个成熟选择的均值依约不作稳定性解释，显示不可得；逐尝试原值仍在证据中。自然年分组只描述结果；最终buyhold盈亏没有输入训练或决策。

## 全部主比较及不确定性

|主比较|MSE减少量及95%描述区间|正预测均值差及区间（百分点）|贪心均值差及区间（百分点）|
|---|---|---|---|
|B1-A1|-0.00000157; [-0.00000353, 0.00000033]|0.02228385; [-0.02150387, 0.08531104]|-0.04264503; [-0.11383220, 0.09209931]|
|C1-A1|-0.00000033; [-0.00000129, 0.00000061]|-0.01044051; [-0.03845759, 0.01420466]|0.01543708; [-0.07475319, 0.12146321]|
|D1-A1|-0.00000197; [-0.00000433, 0.00000011]|-0.00232821; [-0.05320505, 0.06689604]|-0.02624152; [-0.10595456, 0.12038128]|
|A1-A0|0.00000190; [-0.00000015, 0.00000423]|0.00820377; [-0.01478282, 0.03271900]|-0.01417124; [-0.09267267, 0.06221587]|

固定共同交易日轴40日区块、500次、seed13，预测与既有选择成对重抽样，不重新训练或在拼接块内重做持仓。区间未经整个S013选择历史校正，是条件性描述，不是未来盈利概率或新经济硬门。所有五个固定相位、六种选择安排、被持仓占用信号和A原信息全可用预测附表均见statistics和selections证据，不挑最优安排。

## 研究判断、最强反证与限制

G1有利证据：全部正预测机会均值由A1的0.0560%升至B1的0.0783%，2023与2024贪心尝试均值也改善。最强反证：贪心整体从0.1520%降至0.1093%，2022从−0.7306%降至−0.9661%，2026由正转负。不能只取全部重叠机会的赢家改善，也不能把增加换手变量直接视为风险识别成功。

G2有利证据：贪心整体均值升至0.1674%，2023接近零、2024和2026改善。最强反证：全部正预测机会均值反而降至0.0456%，2022更差，五个固定安排仅两个比A1改善，均值增量区间跨零。这是局部线索，不是已证明能补足频率而守住收益回撤的机制。

两组联合D1的全部机会均值0.0537%、贪心0.1257%，均低于A1；2024局部改善必须保留，但2022与2026恶化。三个新增组均未降低全窗预测误差；全部八种表达的MSE较同支持过去均值差约2.12%—2.65%。四项主比较三类区间全部跨零，证据不足不能冒充明确证明所有信息无效。

值得保留：实际成交/未成交/尾部/占用计量，配对训练与共同支持、全部入场安排和反证报告；有利年份和G2局部线索作为后续假设材料。应停止：把标签替换当主要收益补救，以及继续微调当前指数换手/ETF份额的固定线性与低位交互组合。暂停后优先讨论更直接描述市场内部涨跌扩散的信息（如历史成分股广度）及其当时可得性；这是待评审方向，不是已有有效组件，不采集、不运行EX101。

学习反馈：原诊断将标签/执行衔接列为竞争解释，本轮可削弱“只是标签错误”的归因；源权限和覆盖已实际核实，不能继续归咎Tushare只能提供单ETF价量。已有信息与这些外部信息的固定表达仍缺少可信的经济增量；该结论不外推到未检验数据、非线性结构或新的独立样本。

L0/L1相关约0.9932、平均绝对差约0.05715个百分点；6次真正正负翻转，另11次未成交归0。更真实标签不等于更强信息。新组可能重复ETF成交量、反映恐慌或套利，不能把换手/申购方向直接当作看多。份额最大日变化约36.93%保留，尚无独立来源核验。

没有新的封存样本，原开发池已反复使用。本次固定线性及交互表达的支持/负面结果不能证明所有模型或供应商信息有效/无效，也不能代替S013中心及全部32点四门验收。

全日最低价包络含入场前及开盘退出后行情，不是真实持仓风险或账户回撤。公开TXE市价卖出为开盘成交，未验证现实卖出延迟。原5个分钟极值异常涉及23个尝试窗口（5个入场日），不删除或修补，映射另存；日线/30m覆盖核对每执行日8根。

## 验证、额度与下一步

模型26项、成交14项合成检查通过。12/36年度模型系数由独立训练秩、正规方程与预测重建核验，未另拟合；全部选择安排、配对均值及500次重抽样独立核验。公开账本8165逐日现金/数量/权益独立复算一致。FULL与报告副本核对仅表示交付身份和关联文件完整，不表示经济目标通过。

旧PreparedDataRef缺版本通过已保存正式迁移映射更正绑定，公开DFLS内容哈希保持；两次实数构造前停止及源码修订留证，实际标签仅构造一次，0新增行情下载。当前CLI没有历史experiment preflight/archive命令，采用公开创建、不可变证据发布、组件研究前检查及FULL交付验证，不冒称执行不存在的命令。

本轮实际年度拟合36次；额度完成2/2，剩余0。两轮结束暂停；没有EX101授权，不自动进入阶段三、选型、冻结或生产。总体策略目标仍未达成。


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
- [preflight.json](evidence/21ea935dd93d2d1a7c00eb342bbbb80cb6e7f887c42e9e3e4d58facfa3ed4d20.json)
- [actual-fit-input/.tmp/s013-stage2-20261013/inputs/features.csv](evidence/2aeb8cb63cc658a4efa6acc82ee5a4b8be9a731b08db37eba536bd393f6903c1.csv)
- [actual-fit-input/.tmp/s013-stage2-20261013/execution/model/labels.csv](evidence/5c59d1fdd335a66818602091781cda35b90890a77cea9a547081b392c12fcb4c.csv)
- [actual-fit-input/.tmp/s013-stage2-20261013/execution/model/attempts.csv](evidence/f627db85b901ed31070fdfe16fa3c447ff897b87bfb221655e5ae257fafded91.csv)
- [actual-fit-input/.tmp/s013-stage2-20261013/input_adapter.py](evidence/b866a6611fb546c4450435c6e65b692514e465baa1a629d4e256015ff79a95b4.py)
- [actual-fit-input/.tmp/s013-stage2-20261013/run_fit.py](evidence/8cc50c4ed8f5d06a8c3b12d45a9b4f6bea02cda6ee6fab20eb0020f0a44a2a8f.py)
- [fit_input_binding.json](evidence/14867bfa66795e1140a8a5b74a99b2d1b682c11372f40ffd11bdc291c8b23e39.json)
- [EX099/statistics.json](evidence/dee6d2f0ce0b90c9e27e6aa9daf19e366e675717d9771cfdb951960e9aee946c.json)
- [EX099/scores.csv](evidence/b7e60e9b7ba0cadf6fd8aedd271cb9caffcdeadf37d401651959ba5217ea97b4.csv)
- [EX099/means.csv](evidence/32ec537e431a0d9f438d735e7dbe4c0de3146fb1a488676c4e24afb90c534bdc.csv)
- [bootstrap_peer_verification.json](evidence/c1a746e4c7dee07b4f5709001c0e841c5b311d692a33da776507c30b8f500c2f.json)
- [root_conclusion.json](evidence/185710314b74905f5f1e348dfa6ffe615825f1c02bc245e2e78d55c796b43f5a.json)
- [statistics.json](evidence/ad25070f1d093c02e4c18e121eda607191a9c1ef3ffd5d253bbe8ce9c7b17220.json)
- [study_attempt.json](evidence/612a4fb967440542758ba84f7fc36987469f8811a8b2fe5e0006ec2d0b862746.json)
- [study_complete.json](evidence/bc291f7b7a27b1757b29c102bfa8e2a65bb39efc5ae63528b405e6c405335cf8.json)
- [verification.json](evidence/8165ead25615f80787ef3f40f9f34da81f4e88d3b5223579c4adf791f548aa9f.json)
- [all_scores.csv](evidence/851794290dbf0b8b6ee6fc5577f2fa5475b30ac7a0178c0761b56da41106b1a4.csv)
- [means.csv](evidence/32ec537e431a0d9f438d735e7dbe4c0de3146fb1a488676c4e24afb90c534bdc.csv)
- [reasons.csv](evidence/cdc13267626875e65608fcc43b9fac0ade16e3b94afc5e7c4b954167b058a730.csv)
- [scores.csv](evidence/b68e035eb0464f12adac4c5c118be599e4dae8b00231fa3e6eef2b5204b87688.csv)
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
- [B0_clock_0.csv](evidence/ea410df03a2c206c593499436614e8ac6cc0ad2c36928c641996fafd190bf115.csv)
- [B0_clock_1.csv](evidence/3770806450fdf224ad3709c60a367644850f35856641b6fab96e882d8f5fde53.csv)
- [B0_clock_2.csv](evidence/f38c39c7f48968b21c820f079e0f97bf2a8dc1712d8c34ba8f86dd84ad3e5dc3.csv)
- [B0_clock_3.csv](evidence/0969d8e584263cf6c0a5f3d1c3c712b46da42984526f706414c99384d163d67b.csv)
- [B0_clock_4.csv](evidence/7ef2beb45d250cf6b2fe82ab30b7f88254cd1a7d9884d9a330cd5ebe4ffe8967.csv)
- [B0_greedy.csv](evidence/8cc5db55518edf9167d03ff90e625ae1e4ae41e9137a07e7731191afb1c0819b.csv)
- [B1_clock_0.csv](evidence/4e36e69d4df60c5bd0118f5bc57e757573a9f1de1c7246b13f6d0d2a84a52dd2.csv)
- [B1_clock_1.csv](evidence/6db9f43d2c533ed91508d74f34f2eae66329d0c6fcf41be730a9c9bc0c3be584.csv)
- [B1_clock_2.csv](evidence/731131824dc1a2e9a1e56fd0a36dcc4841fa3894eb353cad911f98c1e67b4632.csv)
- [B1_clock_3.csv](evidence/ac6ccdaff479385c7b92ae18a8b215c8eea30db438a521b0de2edfe41e739ed3.csv)
- [B1_clock_4.csv](evidence/4e2a6ad07eee12695daffb3698df6b9eeacd672c869f706f70cf264db9ba5f6d.csv)
- [B1_greedy.csv](evidence/d36b2d7b65094f0ca8d2a306a6aad3887f62856cd730d831656ff9152acb2242.csv)
- [C0_clock_0.csv](evidence/633610eb98c63f0151c124586c1350b793769632fb56edba3b27857bf599f6ce.csv)
- [C0_clock_1.csv](evidence/2647e56fa86f2cc011f79f0e483f1d85f663f6583bfe3827bbf3e07d83b64f2a.csv)
- [C0_clock_2.csv](evidence/83e0c7758dcf4987774fb44ac1ac200dc6a233144c9b35415732663ccdcd5c6b.csv)
- [C0_clock_3.csv](evidence/d40c220c49d5dcd8d0bffbeca3416ebd215269ee5dc94f793191f330d125a6fc.csv)
- [C0_clock_4.csv](evidence/bfb80e72bb1f022198b19479606875033d629c1b2163ce352a69bbc892be8192.csv)
- [C0_greedy.csv](evidence/65f20ba41f33e9c1860953be682d9486f25491486aaf6e02b8999575cc6215ae.csv)
- [C1_clock_0.csv](evidence/cdc81c8a66e45b30a2716a8ad8e675a81f0ff938fcc2d10357ecff37f0a75ef5.csv)
- [C1_clock_1.csv](evidence/04c725adea1db6b7c8d75d4c49c4605486029e8fbf4e32d4b8e3e7aad2808805.csv)
- [C1_clock_2.csv](evidence/2fb7e80f21818c36fbb4737e627b01c4e1daa2903b798cb2a791514a71d8d88b.csv)
- [C1_clock_3.csv](evidence/fedd588be3ac1d5e9e58c23b78a8248645358671f196c8a8c1d4a7e73c9961cd.csv)
- [C1_clock_4.csv](evidence/5377809a00ca3117d1df566653fc15c7bdd815de7bb0fe24e396c237f49d35b1.csv)
- [C1_greedy.csv](evidence/4d1ff873f5e0f5d9145431ed424724df05f6eb60546a9008961db9073fe59470.csv)
- [D0_clock_0.csv](evidence/f17c9ffc0752bdbef27bf25c66e9d31d75e0705961df7bf85d912ea4e58d0927.csv)
- [D0_clock_1.csv](evidence/19bd534af1ad605f5f33c7339041e557aeef4794a569b68a727413c09b211e12.csv)
- [D0_clock_2.csv](evidence/a213434b4247ad4f742f7377b07c0aff16db450a5296015f9812d011d1f5313d.csv)
- [D0_clock_3.csv](evidence/1c37ba697679f90e0d0adf15465dd4fa56a5f5e2c58ff20a91e4c70b2ac20e9c.csv)
- [D0_clock_4.csv](evidence/d63e78ebbb610f690c140984439af7f4196f22d5668407748ec2a5669dcd112a.csv)
- [D0_greedy.csv](evidence/01b70952d4fff8f11158e661b49fbf86759498fbcdad60dc38fac0d8394a39fd.csv)
- [D1_clock_0.csv](evidence/fbbccbf5bc67895f86222e175ed27febf9391852e94017d09ce4f1c0a56267f9.csv)
- [D1_clock_1.csv](evidence/e369320962853e3fc3d4cbdd5af045f60285c8829a7e3e7d2363c12f4498412c.csv)
- [D1_clock_2.csv](evidence/a683d05bbe6108fe341e6364ac6d41ab332769fd1b5d6f5b89ac3d1a1875a14f.csv)
- [D1_clock_3.csv](evidence/ab360f67c45b549426525b0738d86473360ac8eabacd4983c93e72aa466253bc.csv)
- [D1_clock_4.csv](evidence/b77151bf659fb5b65366391d2bf11565aba925f135672427cc0c7182d9761d7d.csv)
- [D1_greedy.csv](evidence/6260b6f79246442281ad7624ba2b3e00b6c5f18c2fea33c9e742078f7fd1debe.csv)
- [audit.py](evidence/9eb991aac9cfa3987b23275001ab9b61e0fb946b39f60d9c4258996c7629410e.py)
- [bootstrap_peer_audit.py](evidence/b60fef0e799de9f9c94f334773614fce55fa4e9e38988858ac2dff0b4d90cdb9.py)
- [driver_peer_review.json](evidence/b36ccd7010cae14d449f21daff0a1cc11d4de7a720d5d2d070c3bb00ccacb948.json)
- [execution_peer_review.json](evidence/0b2421659b75a26d18c29f13fb4c9e5a15762450efaf48dfb6d44f65addf1682.json)
- [closeout.py](evidence/c2c892bee6babba2740cfdd638379cb7bfe3726c53239c2afe5ae475b02cb0f0.py)
- [budget_receipt.json](evidence/5ef3fcc5ee97b3a8dc4ae5cf758a6b0f65dbdf258e60e7e5cfeb57507c37c768.json)
