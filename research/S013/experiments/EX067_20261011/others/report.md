# EX067：真正空仓机会与持仓观察拆分

本轮目标是判断EX066尾盘弱势的条件性线索能否用于新买入。原四项经济硬门保持：频率按整个开发池平均，buyhold亏损年份要求策略净收益严格正。稳健达标总目标尚未达成。

## 原资格池多数是持仓行

|原信号状态|样本数|过去20日动量负的子集|
|---|---:|---:|
|真正空仓且资格成立|147|69|
|已经持仓但资格仍成立|365|154|

原entry_eligible即使持仓也记录，confirmation_opportunity才是空仓且资格成立。全部1635信号行均独立核验其等于资格成立且前一原target_position为0；这里按原策略信号状态拆分，并非实际账户数量。原512资格行不能全部称为可新买入机会。下跌子集223行；EX066 h4有限标签和controls后约220行，缺失端点不混为不同机会来源。

## 尾盘弱势不支持新买入

|样本、期限|控制原信息后相关|描述性40session块区间|
|---|---:|---|
|真正空仓、4日|+0.0879|[-0.1221,+0.2780]|
|真正空仓、8日|-0.0034|[-0.1477,+0.1598]|
|下跌空仓、4日|+0.0889|[-0.2432,+0.3628]|
|下跌空仓、8日|-0.0010|[-0.2462,+0.3190]|
|下跌持仓、4日|+0.2344|[+0.0516,+0.3682]|
|下跌持仓、8日|+0.1742|[+0.0066,+0.3133]|

真正空仓单独逐年成熟训练，4日加入尾盘弱势后预测误差由0.002068736升至0.002089899，8日也略差。下跌空仓单独模型因历史成熟训练不足没有预测记录，不能写成零收益或确定没有机会。

为排除小组分别拟合的影响，复用EX066同一套已训练预测和训练分位阈值再按原状态拆分，不重拟合。下跌原资格池4日共同预测：空仓40行误差由0.000472272升至0.000473230，持仓123行由0.000717789降至0.000696831，改善约2.92%。8日空仓误差小幅改善约0.20%，但其控制后相关接近零、区间跨零，不足支持入场。2023下跌空仓高/低尾盘弱势组分别1/2行，不能据此估计该亏损年份的经济效果。

下跌持仓配对4/8日最大不利变动相关为-0.2322/-0.2413，描述性块区间均负。这是有限的恢复线索；标签仍是假想新买入的固定期限收益和不利变动，不等同实际持仓剩余收益，更不能直接推出放宽退出会赚钱。持仓4日模型仍不如历史均值基准。

结论：停止“尾盘越弱越买”的入场路线；保留持仓恢复线索，暂不策略化。下一路线研究日内下跌发生的先后顺序与连续卖压，控制旧信息和总涨跌量，检验是否存在新增信息。

## 验证及限制

原C8880原生序列化与公开证据精确一致，资格逐值一致，无外部provider调用；EX066原features和费用标签精确复用。6项合成检查与256项独立Spearman、预测真值/MSE、成熟训练、分组阈值/计数/均值及状态划分核验通过。500x40块诊断与ridge未重复拟合复算，区间不是经开发选择校正的独立显著性。

本轮是已见开发池的自适应职责归因，原信号状态受原策略规则影响；不能推断所有其他策略的机会数量。分数份额、理想开盘成交、两侧10bp代理未含真实限价/跳动/整手执行，不能代替完整TDR账户。本轮新账户、新32点、自检及候选登记均为0；C8880已有五项自检及0/32联合达标事实保持。技术FULL校验不等同策略经济目标达成。

## 正式证据引用

- [prepare.py](../../../assets/deliveries/COMPONENTS/6/evidence/1b5fa952441b6296c8692860960accd2f4893585489334260f2a227242d22ffa.py)
- [opportunity_statistics.py](../../../assets/deliveries/COMPONENTS/6/evidence/9bf38138faab433d3ccec05b6a276c565e9479120392c7387c43e4a1f24bf45b.py)
- [driver.py](../../../assets/deliveries/COMPONENTS/6/evidence/a6c6a21b0e4bc47d6bef7d8fa60659855cd7c53696614f3e250a95ef53cf4ef8.py)
- [checks.json](../../../assets/deliveries/COMPONENTS/6/evidence/4fdb1e049a10da535b3a416426d9a406251465a9ad54add5cff57fc06c81970b.json)
- [plan.json](../../../assets/deliveries/COMPONENTS/6/evidence/c18e10832df277fd0b42507f51b656c8d187ea12de7dd8a1516f830833138552.json)
- [input_checks.json](../../../assets/deliveries/COMPONENTS/6/evidence/a9626cd5960aacba2a72f406a25bb22fb40a9eeb03fabebcb1526812aa1dfad8.json)
- [scopes.csv](../../../assets/deliveries/COMPONENTS/6/evidence/5157e7b83fa6d1856164e481dc367cbea536973e5ca1dbdee43c47f4b1d38f9a.csv)
- [features.csv](../../../assets/deliveries/COMPONENTS/6/evidence/aa2a816c802ed35932e8d879efcc75cb3876a9280e74b3e188461923bd5736bd.csv)
- [labels.csv](../../../assets/deliveries/COMPONENTS/6/evidence/ade6c0b45a0de547ac941b0585a6e24a381bee87a8ac56b95f44b20c4be6af50.csv)
- [statistics.json](../../../assets/deliveries/COMPONENTS/6/evidence/632e19b678d81df85714a6183077659809a32dfa84d37dfecb18e997122e8d42.json)
- [common_transfer.json](../../../assets/deliveries/COMPONENTS/6/evidence/4fea807ba1d090cbe650d589fb203045d6dd9a6d28759b7ac4f382d1c1824dc3.json)
- [compact_statistics.json](../../../assets/deliveries/COMPONENTS/6/evidence/3e1fbaf66299e56101b2bec26b14224fb9567dc1194693bd96b0d5c5a5884e5e.json)
- [judgment.json](../../../assets/deliveries/COMPONENTS/6/evidence/e9a30658c55836ca04638da0a2d1fbb0fbb3f93a22e326a66ca3e8f32681f07f.json)
- [conclusion.json](../../../assets/deliveries/COMPONENTS/6/evidence/de06f4797256d4591bb5846bdc8fcb720c2399b8161e37288e01140d8ffb7b41.json)
- [verification.json](../../../assets/deliveries/COMPONENTS/6/evidence/32b55e700ff2dc8e62a0b3d0b14b83afdbf6bb70b9b927d8fdd7d703770d6344.json)
- [report.md](../../../assets/deliveries/COMPONENTS/6/evidence/a65ce817e878c30e6bc953c066a0568429033af35f8fd86ca138c660dfcadae9.md)
- [finish.py](../../../assets/deliveries/COMPONENTS/6/evidence/0d471a9ab4c176916e0709be4ad70772307db4c20ee5968f592b814bd1b3c21e.py)
