# EX066：扣费后做多机会供给与实际持有期限

新研究目标是找出数量足够、扣费后有盈利余量、能在当时识别的做多机会，再形成原硬门达标且抗扰动更强的策略。本轮阶段二诊断完成；稳健达标总目标尚未达成。原四门、只做多、统一后复权、费用和执行合同不变。频率按全开发池平均计算；buyhold亏损年份仍要求策略实际净收益严格正，不改为非负。

## 机会存在，但随意买入平均亏损

|年份|理想开盘成交下，4日扣费正收益非重叠机会最多笔数|8日最多笔数|全部4日标签平均毛收益|全部4日标签平均扣费收益|
|---|---:|---:|---:|---:|
|2022|28|17|−0.2874%|−0.4867%|
|2023|30|20|−0.1532%|−0.3527%|

机会计数使用未来收益挑选、固定持有1/4/8/10日、每侧10bp、交易间留一个session。全池混合期限正收益非重叠机会最多512笔；事后最优增长组合353笔，施加至少110笔约束未改变该组合。这里不存在可执行策略，不模拟限价、跳动、整手、资金预算或真实状态。它只说明这组有限期限及放宽成交假设下有正收益机会，不能证明实际策略可实现全部硬门或原目标普遍可行。

原C8880资格样本固定4日标签，2022/2023毛收益均值分别+0.0852%/+0.1308%，扣费后分别−0.1148%/−0.0692%。这支持盈利余量不足的解释，不等同完整账户的原退出结果。

## 固定反向尾盘信息有条件性线索

两项为EX061尾盘变化及早段价位收复的负号表达，不产生新信息。h4/h8为原bear4/bull8持有期限匹配，h1辅助；控制原14项信息。过去20日动量负分层事前固定，不以2022/2023年份选择规则。训练只用此前且标签已经结束的数据；2021—2026顺序测试；500×40session块诊断、seed13。

|范围、h4|尾盘弱势控制后相关|早段收复弱势控制后相关|
|---|---:|---:|
|全池|+0.0032|+0.0023|
|原资格池|+0.0628|+0.0477|
|过去20日下跌池|+0.0034|−0.0465|
|下跌且原资格池|+0.1942|−0.0140|

全池两项的1/4/8日增广模型合并预测误差全部更差，h4/h8控制后区间跨零，年度和非重叠相位不稳定。不能形成一般的“尾盘越弱越买”规则。

最强正证：下跌且资格成立子集，尾盘弱势h4描述性块区间[+0.0406,+0.3302]，h8相关+0.1301及区间[+0.0143,+0.2242]；h4顺序预测加入尾盘后误差比原controls下降约2.37%。历史训练分位高弱势组h4净标签均值+0.7879%，n53。

最强反证：该子集h4模型仍不如过去训练标签均值的基准；h8非重叠相位正负交替。2023高/低组各仅5行，不足报告年内组均值；2026样本不足。相关区间不校正反复开发选择，不能声称独立显著优势。早段收复弱势在该子集h4/h8无稳定增量，停止固定反向表达策略化。

## 新入场机会与持仓观察需要分开

源码中entry_eligible只检查位置、动量、ACF或资格恢复，即使已经持仓也记录；confirmation_opportunity才是not holding AND eligible。原512个资格样本并不全是空仓可以买入的机会。有限正证可能来自持仓后的反弹，不能立即移成入场过滤器。下一轮先事前声明真实空仓/持仓资格拆分，再决定组件职责，不改本轮已发布结果。

## 验证与研究边界

原C8880完整原生缓存与公开证据序列化精确相等；原执行价格公开转换精确重建，1636执行session及最终9月30日端点完整。原14controls逐值保持。48项合成检查通过；真实统计294项独立相关、成熟训练、分组和预测误差检查，6540条费用标签检查、35项独立贪心容量计数检查通过。Bootstrap和ridge未重复运行。

标签按下一开盘至下一开盘+h扣两侧10bp，是分数份额的成交代理，不是TDR完整账户；未叠加现金分红。期限改变可能遗漏原提前退出。已有5个30m High/Low问题保持，本组件直接复用EX061 close/volume观察；价格风险标签仍有原数据局限。已见开发池不是封存验证，历史真实发布时间和修订未独立验证。

本轮新账户、32点、自检和候选登记均为0，C8880原五项自检和0/32联合达标事实保持。声明前标准库同名导入失败、声明后Windows文件链接拒绝均保留；同EX066继续公开发布，没有重复分配实验或改动经济方法。技术FULL PASS确认材料一致性，不代表策略目标达成。

## 正式证据引用

- [core.py](evidence/fa88d50f7d1044aa6977e0bf3f07c2bee748c080dbe27d1e63d737557183f79f.py)
- [checks.py](evidence/1b24a81829eabde9c136b3e1a6ffb1243e75f1be3141aef0d76168dddb7ee880.py)
- [opportunity_statistics.py](evidence/565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a.py)
- [statistics_checks.py](evidence/d48e3b61f4fd8eaacb20e55dbe7dbdf07036db09c70ba60502989f565c0e3ebb.py)
- [stats_test_module.py](evidence/565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a.py)
- [verify_statistics.py](evidence/2a7f7db9c32abbb50f4ccf4721c6167e8b797b8df6022e04acb15a1bb22791d6.py)
- [driver.py](evidence/0ef78f2ff09d582e0007623d0d08eae4152f07210020650544b47721467f22c4.py)
- [prepare_statistics.py](evidence/c2f42fd70eed6c8da573910934a1345215b542dec9004f4694ecf42072f3bd8c.py)
- [checks.json](evidence/3ddfe7f4315ab2422285d48db668d1d93b38ef114a2959d61cae8e0854a0ced4.json)
- [statistics_checks.json](evidence/3965d93913974d9952a7da428df352136b1e23ba8922c04fab614e1ec04602e9.json)
- [plan.json](evidence/676b4f8bd8c14d9824c3fcd978d393ecd6cea1cc0fa9531e94cd369c8299b28b.json)
- [failed_declare_v1.json](evidence/d6715a03f7a4fa5545f6ca3719fb9752360c30b196e9ed5c7371358676307164.json)
- [failed_declare_v2.json](evidence/feec61989d5597db88dd8d6c68b3995d07524a601d025669533ad07cad75b6b8.json)
- [recover_declare.py](evidence/febbffd1e5cb55a61ad43e09a7944364c3d7ea6d96d407b8ad9a2cc1062929df.py)
- [features.csv](evidence/aa2a816c802ed35932e8d879efcc75cb3876a9280e74b3e188461923bd5736bd.csv)
- [labels.csv](evidence/ade6c0b45a0de547ac941b0585a6e24a381bee87a8ac56b95f44b20c4be6af50.csv)
- [opportunity.csv](evidence/090742cf2ffbbc15d382569717debb45898ee5eb877d0310fab48899047133d1.csv)
- [prices.csv](evidence/4402aba79913c267c6785971b084f0ee1bf5cc0886a08a2db5b8352de28aa5dc.csv)
- [input_checks.json](evidence/aeacca69fc4caf1f6e8e96c0f51abe2dff205230d332ca4efacce52aba71f388.json)
- [supply.json](evidence/04c3b13fa655a0ec9f1fff96eae6b8b6fbdf3db5287d707f7197a30cbad80f1b.json)
- [statistics.json](evidence/fc409a8cd0d432cc16afc86d6fc3a385724029366ae431ef3fc1cfcf4e51e86a.json)
- [compact_statistics.json](evidence/231c283547cb7fa155b5b6f93b45cdb04e3aee2c7ca29f01bd999cce228ea10a.json)
- [judgment.json](evidence/fbeae9cf3594d62ca44e8c0d6f4082d1c2d64d7ef9c4ef2524da7f772f3134d4.json)
- [verification.json](evidence/c5b836fdc622feb0dd0ee0dc10307471d18f24f1656068842e06a81a34b528e3.json)
- [conclusion.json](evidence/5e352ae7a57306307ae3f71d2d9df0ab6e5eb78fe83f0ee9b3adc0185a150f59.json)
- [report.md](evidence/76391c2346e0120f3fe424f1ca11682c2d2c070903309122310c3499fdd66ce7.md)
- [finish.py](evidence/a252258fa178643a0dce02022f28ef611a970bec59d451afc3271fe7063d45e0.py)
