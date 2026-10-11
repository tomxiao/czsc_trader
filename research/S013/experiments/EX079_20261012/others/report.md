# EX079：原信息是否能挑出扣费后值得买的机会

结论：买入确认分数有有限的筛选线索；固定14项联合表达未证明更好。两者都没有建立稳定的净盈利能力，不能据此宣称原四项硬门或标准32点达标。

本轮是新增10轮额度的第1轮，EX079–EX088最多10轮，EX088完成后暂停，不启动EX089。原四门、只做多、HFQ及固定1%执行合同均未更改；本轮0新账户、0新数据请求。

## 方法与复用

固定四日全额小数份价格代理：T决定，下一OPEN买入，第5个未来OPEN卖出，每侧0.1%成本。三表达用相同14项完整特征、成熟历史训练：过去均值、买入确认单分数、原14项联合。年度外推2021–2026，2020仅训练；训练标签在测试年度首信号日前成熟。训练ECDF秩、ridge10、阈值预测净收益>0均固定，无扫描或翻向。

EX066的1388条成熟均值/14项联合预测逐条复用；四个未成熟尾日期保留因果预测、不虚造真实收益。只有确认单分数新增六个年度拟合。此前均值/联合模型的误差不是新发现。2020无事前预测，不能称完整原窗口账户比较。

原全轴1635T先定义五相位再筛选。旧EX066 opportunity.csv是entry_eligible，不能直接当空仓机会；本轮辅助组取完整C8880原政策confirmation_opportunity，含2019anchor历史前缀，147个事前机会，不使用未来成交或实际持仓替代政策状态。辅助组仅报告、不训练。

## 主池：预测为正的机会

| 表达 | 有真实结果的入选数 | 扣费后四日均值 | 胜率 | 误判比例 | 比全池提高 |
|---|---:|---:|---:|---:|---:|
|过去均值|485|-0.209992%|+47.628866%|+52.371134%|-0.123029%|
|仅买入确认分数|691|+0.121217%|+52.243126%|+47.756874%|+0.208180%|
|原14项联合预测|717|+0.032928%|+51.464435%|+48.535565%|+0.119892%|

全部同口径1388条成熟机会平均净收益为 -0.086964%。确认有1392个可预测日期，694个正预测，其中691个结果成熟；它的691个机会重叠，绝不是691笔闭合交易。

## 固定500×40共享时间块区间

| 数量 | 原值 | 95%区间 | 有效重采样 |
|---|---:|---|---:|
|training_mean_positive_mean|-0.209992%|[-0.642005%, +0.166083%]|500/500|
|training_mean_positive_minus_all|-0.123029%|[-0.518996%, +0.204046%]|500/500|
|confirmation_only_positive_mean|+0.121217%|[-0.208056%, +0.535451%]|500/500|
|confirmation_only_positive_minus_all|+0.208180%|[-0.000456%, +0.460365%]|500/500|
|original14_joint_positive_mean|+0.032928%|[-0.240352%, +0.425899%]|500/500|
|original14_joint_positive_minus_all|+0.119892%|[-0.060025%, +0.344820%]|500/500|
|joint_minus_confirmation_positive|-0.088289%|[-0.274776%, +0.106813%]|500/500|
|joint_minus_training_mean_positive|+0.242920%|[-0.102338%, +0.648013%]|500/500|

8个固定区间全部跨零。确认正组比全池提高约0.208个百分点，但差值下界仍略负；确认正组本身的净均值区间也跨亏损。因此是有限线索，不能把平均为正说成稳定盈利。区间保留全500次记录，不重拟合、不挑组；未校正同池反复研究。

## 年份与五相位反证

| 时段 | 确认正组n/均值 | 联合正组n/均值 | 全池均值 |
|---|---|---|---|
|year_2020|0 / 不可用|0 / 不可用|不可用|
|year_2021|158 / +0.046002%|155 / +0.144526%|+0.014491%|
|year_2022|187 / -0.231910%|145 / -0.708632%|-0.435404%|
|year_2023|90 / +0.006737%|143 / -0.108323%|-0.348961%|
|year_2024|95 / +0.618763%|79 / +0.670143%|-0.033087%|
|year_2025|78 / +1.409396%|76 / +1.403027%|+0.444369%|
|year_2026|83 / -0.595928%|119 / -0.337157%|-0.195371%|
|phase_0|138 / -0.190327%|142 / -0.369169%|-0.243679%|
|phase_1|139 / +0.464638%|149 / +0.213843%|+0.032507%|
|phase_2|142 / -0.012987%|150 / +0.077596%|-0.040486%|
|phase_3|134 / +0.382141%|138 / +0.232845%|+0.019148%|
|phase_4|138 / -0.028417%|138 / +0.002876%|-0.201711%|
|original_policy_flat_confirmation_opportunity|74 / +0.579099%|76 / +0.328711%|+0.128912%|

2022确认正组仍亏损，2026也亏；2023确认有改善而联合组仍亏。五相位确认有正有负，不能选择有利相位。2024/2025表现好，需完整保留：2024低胜率但均值为正，说明少量较大涨幅也可能影响均值。辅助空仓组是旧策略内生选择、样本小，不能直接推广成新策略。

## 误差与最强竞争解释

| 表达 | MSE相对均值的改善 | 秩相关 |
|---|---:|---:|
|过去均值|+0.000000%|0.00406928|
|仅买入确认分数|+0.944798%|0.09057083|
|原14项联合预测|-2.436834%|0.04555170|

确认误差比均值小约0.945%，联合模型误差反而大约2.437%；确认正组平均收益高于联合组，但组间区间跨零。更多信息在这个固定线性秩表达中没有自动变成更好筛选。过去均值正组平均亏损，单靠过去整体上涨不能识别未来机会。

## 下一步与限制

建议保留确认分数作为有待验证的信息，而不是直接保留所有确认规则；停止本轮固定14联合表达的阈值/邻参数救援。有限正面线索只支持进一步核对“机会如何被原限价与资金约束兑现”，不支持马上做大范围账户搜索。需要分清预测错、执行损耗与退出机会成本。

四日重叠价格代理忽略1%限价实际成交、整手、同时只能持一仓、真实退出与现金路径，不能推算账户年化/回撤/闭合次数，也未形成32点Q10/Q90。下跌年正收益仍是原硬门，不放宽。没有改进策略达标结论；当前研究目标未达成。

独立核验通过：1635T输入、原147空仓机会、1388旧预测精确复用、三个表达数学重建、全部年份/相位/辅助描述及500×8=4000重采样数值和状态。复算用于核验，不增加研究表达或额度。

正式报告保存于deliveries；本实验others/report.md保存逐字节副本，另留SHA256一致性凭据。文中证据路径按项目根目录解释。

正式证据（项目根目录相对路径）：

- [plan.json](evidence/247472e4afc056b57037f91f6b963a7a79c920aba72ad40440c6a6ec73831232.json)
- [focused_checks.json](evidence/331368e3ded3aa56fef19b610c6a98da3affd9bf6d4d106a4c189c8963b1ea53.json)
- [reuse_precheck.json](evidence/c4f5de78c7d72de673d730997acfe2dc3104eeda2378c2bf3f95fdcff5d48b6c.json)
- [.tmp/s013-base-net-opportunity/focused_checks.py](evidence/202d88f1976d310a1677368a332fa16ce7b0ed0fb0643bbec616b9c6253b4079.py)
- [.tmp/s013-base-net-opportunity/inputs.py](evidence/318cd51f2df0d52f8fafbeec0ba72fc33c60a547f008de53249290f28c5a365a.py)
- [.tmp/s013-base-net-opportunity/net_statistics.py](evidence/fdd68057f9d1f03fc8c15928c466f5b882a183caea01fa3e39557e6494b23793.py)
- [.tmp/s013_net_research.py](evidence/5dc857c0515e7ad81ae8753ed2bab8954c215ba50c9f774790d8fd4565e06638.py)
- [.tmp/s013_net_plan.py](evidence/f49dbbc7d988e8c8d510a467c265bbe469d25ebd03b6fa5e8ec0e53bbf1306c3.py)
- [research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [research/S013/experiments/EX066_20261011/src/opportunity_statistics.py](evidence/565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a.py)
- [input_checks.json](evidence/dc5a219d77284034294cb1d84f68e471dc31734a22dcd6524f8c5ce774903898.json)
- [features.csv](evidence/652f8e92a214964c124b65f3f1e46a130a3e86c31695336632c86694a09f0b9a.csv)
- [labels.csv](evidence/8f555f2eaac04c28c588bde3122e3ee1a248cc2326d77c33a45bb6057f669c75.csv)
- [auxiliary.csv](evidence/2ba487f191aea80f7b8c9533caec598aa5f555b76b0f30b196dd1461f160c8ce.csv)
- [original_history.csv](evidence/bb1177cd4466fc88e34f3fbc0fef1c314a911cf91782f7ff48aec96913ee9bd9.csv)
- [statistics.json](evidence/afc31de556fe6d4d4fa1189716d371cc0878aae3afea04d63a5253dc21714ea6.json)
- [study_complete.json](evidence/a9c5c84f1a78a2fa6b584e884bf3face987d8ab665dc82078065e09d5b941623.json)
- [verification.json](evidence/53895befcbd69da5622d76c3a65a353736bcbf97c8cd314cfa7bbcfed451a5e0.json)
- [audit_audit.py](evidence/8b31573915dc3d46232d1c6dc47b287e1b76898ac7744cd066e70778f06ff2df.py)
- [audit_freeze.json](evidence/b2c21cec3bb2eaff7957782e24390e8d865d587874097b41970d6684e9f68039.json)
- [audit_synthetic.json](evidence/552e781179ad69dbc49e63af276f790711d4d9d3cff2075545881139f1513adc.json)
- [audit_synthetic.py](evidence/d5c65029f230dd04f07900e3561fa508227d5780d8c3ba9ccf7d445c987b7e46.py)
- [audit_driver.py](evidence/7d0485ff4284179c9dec4353af1fa1fc4a55012e6c8aa5a737b9c3e7e10f8191.py)
- [root_review.json](evidence/f2069025ef28722b22bf37482ba876374b74ad471053b0aebf74025e9ee22560.json)
- [closeout.py](evidence/9f2f781eae5f0d3b1ad4878f370d0ae9b9d1c5d823a53f86e0b50e5b3607155e.py)
- [root_review.py](evidence/35ac8e8416ddf018cc31e555903d84b53c48721ee0c8d488f533c0c12c645e2c.py)
- [budget_receipt.json](evidence/67a851f9b14c5ac49b4c03925c35842cc8f59f4b883047db184ce268f5cfab83.json)
