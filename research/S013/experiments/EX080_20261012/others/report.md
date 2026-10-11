# EX080：确认净机会落实为真实账户

固定四日确认净预测不能独立支撑原四项经济要求。保留确认信息的有限条件性线索，放弃当前年度单分数预测>0加四日时钟这一策略表达；不调邻近阈值、期限或正则系数补救。

这一轮把 EX079 的原确认分数年度净收益预测原样落实为一次完整账户：预测大于0且政策空仓时入场，持有四个交易日，到期退出，退出信号当天不能重新入场。采用原510500.SH、完整2020-01-02至2026-09-30开发池、100万元、后复权固定锚、每侧0.1%费用、整手及原1%限价执行合同；2020训练期空仓也计入完整区间。

## 原四项经济硬门

|项目|EX080 C9080|原对照 C8880|原要求|EX080判断|
|---|---:|---:|---|---|
|净年化收益|2.4529%|17.1346%|至少10.8290%|未达标|
|完整区间最大回撤|30.8919%|13.6187%|验收按逐自然年严格小于相同buyhold，不用全区间回撤替代年度门|见年度表|
|闭合交易|193|116|完整1636交易日平均每60日至少4次，即至少110次|达标|
|平均每60日闭合交易|7.0782|4.2543|至少4|同上|
|逐年回撤门|未达标|达标|每年回撤严格小于同年buyhold|保持原定义|
|buyhold亏损年份盈利门|未达标|达标|按实际buyhold负收益年份触发，策略净收益严格大于0|保持原定义|

## 年度结果

|年份|EX080净收益|C8880净收益|buyhold净收益|EX080回撤|buyhold回撤|EX080费用|
|---|---:|---:|---:|---:|---:|---:|
|2020|0.0000%|16.5873%|22.1693%|0.0000%|14.9712%|0.00|
|2021|5.0253%|8.2925%|17.2351%|11.6159%|9.7035%|81117.83|
|2022|-10.5013%|19.5931%|-18.3203%|19.6878%|28.4105%|84363.99|
|2023|-3.8489%|0.9181%|-6.2450%|12.8582%|17.2665%|54850.05|
|2024|-1.6227%|65.0176%|6.9559%|19.5119%|18.5736%|44032.12|
|2025|35.2159%|11.0762%|32.7098%|5.7833%|13.7975%|57032.98|
|2026|-2.6501%|-0.0388%|0.9947%|17.2095%|18.7646%|56468.24|

共同可预测执行区间2021-01-05至2026-09-30仅作描述：EX080净年化2.8890%、回撤30.8919%；C8880净年化17.1274%、回撤13.6187%；相同buyhold净年化4.3540%、回撤39.4419%。两者保持原账本期初持仓和权益，没有新账户；完整1636日原四门仍是验收口径。

## 信号机会为什么不等于账户盈利

EX079 有694个预测为正的信号，其中691个四日标签成熟；每个信号允许资金重叠的均值约+0.1212%，这只是扣两侧费用后的OPEN价格代理。其均值置信区间跨零，2022和2026分组仍亏损，不能视为稳定盈利证明。

本轮政策接受194次入场意图，拒绝在已有持仓或到期退出信号上重复入场的正预测500次。接受意图中193个代理标签成熟，其非重叠四日OPEN代理均值为0.0996%，复合代理收益为12.9979%。这依然不是第二个可执行账户：不能代替真实限价成交、整手、晚成交、未成交、补买、现金占用及末期持仓。真实闭合交易只按原生账本计数，二者差异不作可加总的因果利润解释。

逐个接受意图的计划日期、实际买卖成交、未成交与费用已经留证。最终未结束持仓保留，未强平或缩短持有期，不计入闭合交易。

## 自检与结论边界

仅复用这一个中心账本计算126日/21日步长滚动超额收益Q10、最大正盈利交易前10%贡献、2000次/平均20日块/种子13的配对超额年化区间；结果见核验JSON。中心原四门失败，按事前停项规则不运行新标准32点或双费账户。参数收益Q10、回撤Q90及32点逐项/联合达标率均不可得，不能填0或写成通过；PBO/DSR因完整研究族证据不足不可得。本轮没有完成完整五项自检，也没有达成整体抗扰动研究目标。


复用中心账本的三项实际诊断：

|诊断|实际结果|解释|
|---|---:|---|
|126日滚动超额收益Q10|-15.7184个百分点|较差的一批半年窗口明显落后buyhold|
|前10%正盈利交易贡献|31.2506%|只对严格正盈利闭合交易计算，不新增集中度硬门|
|配对超额年化95%区间|[-17.1013, 6.2044]个百分点|跨零；是固定账本重抽样区间，不是未来成功概率|

全区间实际费用合计377865.21元，最终净增值170369.97元。实际订单389份、买入成交195笔、卖出成交193笔，未成交订单1份。交易频率够了，但每次机会留下的净盈利及下跌年份保护不够，不能靠多交易弥补。

## 技术核验及修正

准备阶段的候选标识格式已独立修正留证。首个C9079评价调用在SRT输入准备阶段因重复日线成交价输入而拒绝，未进入交易账户计算、未生成完整原生结果。原方案与源码保留，技术修订C9080删除冗余输入，复用原成交价表重建相同特征；参数、预测表达、持仓政策和经济要求未改。另分离非数值DataFrame元数据以避免重复复制，保留输入身份认证。

修订后1635个历史预测及正负判定与EX079相符，独立复算22904个特征值、六次成熟年度训练和全部政策字段通过；完整原生序列化、现金数量费用、年度边界、订单成交链接及首触核验通过。技术通过与经济达标、信息有效和未来稳健是不同结论。实际新增完整账户1个，账户重跑0；早于账户的失败评价调用1次完整披露。

## 下一步与额度

停止这一固定策略表达，回到信息组件：优先检验确认信息与价格状态的作用关系，先取得增量证据，才允许进入新完整账户。原对照的较高收益仍不能抵消其标准扰动脆弱性。 同一已见开发池上的适应性研究不能冒充独立封存验证，不扩大数据范围，不新增经济硬门。

新增10轮额度已完成2/10（EX079、EX080），剩余8轮，最后允许EX088；额度用完暂停，不启动EX089。正式报告完整副本存入本实验others/report.md并逐字节/SHA256校验。


正式证据（项目根目录相对路径）：

- [v1/plan.json](evidence/a81227ad34c8997a3987053a04c411c03fc75de7365bac07b57e8a3e9a2accb7.json)
- [v1/.tmp/s013_confirm_execution.py](evidence/769e9cd21a405239f776d26bd33455e6e7a10d69de500d4d6e46fd869cb2ed64.py)
- [v1/.tmp/s013_confirm_freeze.py](evidence/484efbc6a22beceaac7663d987be174c9d683785d57d8fdf9640fc38ed757ee6.py)
- [v1/.tmp/s013-confirm-net-execution/confirm_kernel.py](evidence/ef0e346443ff977a2b41068a95e1da48e6ae9fb88e56080bbd83569228a62ae0.py)
- [v1/.tmp/s013-confirm-net-execution/confirm_net.py](evidence/746e36d2f0a6371811b54e3a95f9fa46ded29fbf0c9bffbaa0a3af267194710c.py)
- [v1/.tmp/s013-confirm-net-execution/focused_checks.py](evidence/22cd509dc996fb6b3e56ba9aa2505361c4eabb8dfc15c678d747017be5ee1934.py)
- [v1/.tmp/s013-confirm-net-execution/focused_checks.json](evidence/0bb067b63e6a89841f1d96a869b5c9aa0674d5c4186b8ff899411b3d0cc879cb.json)
- [v1/.tmp/s013-confirm-net-execution/scientific_plan.json](evidence/77ab96f6ac6a4c0b203ab4372583575b0f6535b6904edace47becd73f8b067dc.json)
- [v1/.tmp/s013-confirm-net-execution/original_binding_metadata.json](evidence/1f1767d4481f9f6142870fb31eb47d73e8d29abef2f54564c63bd36899eb64ff.json)
- [v1/.tmp/s013-confirm-net-execution-audit/audit.py](evidence/82670d42c54092a50f2af74f95086ee5150d1bf9223415e7d0bad7ba49cbdc71.py)
- [v1/.tmp/s013-confirm-net-execution-audit/synthetic.py](evidence/a3a0360eef574815087b2c4642bbe3adb86ab919484beff8b9fe94eadccf4dd5.py)
- [v1/.tmp/s013-confirm-net-execution-audit/synthetic.json](evidence/161f298c178764993bf580946e24c6f68378bd45ff826f790f0f441f02fb4c44.json)
- [v1/.tmp/s013-confirm-net-execution-audit/freeze.json](evidence/62daa02a4455dbfa66f6cbc37ffa9dca41cc5152415562dd4522b852815ef5f8.json)
- [v1/research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [v1/research/S013/experiments/EX066_20261011/src/opportunity_statistics.py](evidence/565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a.py)
- [v1/research/S013/experiments/EX074_20261011/src/economics_reference.py](evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [v1/research/S013/experiments/EX074_20261011/src/account_reference.py](evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [v1/research/S013/experiments/EX074_20261011/src/execution_links.py](evidence/b7aa3220794b93000cffbde4410c97b95f3cc798f7348244b4113cbf7d5da198.py)
- [v1/focused_checks.json](evidence/0bb067b63e6a89841f1d96a869b5c9aa0674d5c4186b8ff899411b3d0cc879cb.json)
- [v1/scientific_plan.json](evidence/77ab96f6ac6a4c0b203ab4372583575b0f6535b6904edace47becd73f8b067dc.json)
- [v1/original_binding_metadata.json](evidence/1f1767d4481f9f6142870fb31eb47d73e8d29abef2f54564c63bd36899eb64ff.json)
- [v1/technical_repair.json](evidence/36c7d0d5c6b72aeb8455e004e39b343f9df9656eb0b6564a9d7bd724e5f7ed65.json)
- [v1/driver_v2.py](evidence/d1ec386ed06cd679ab780f4b813612856634ba60184d689d21699447a797bc41.py)
- [v1/repair.py](evidence/daab03c9af69336e8b9d5c3420075b0a2af996dafacc5813d118284475802e1e.py)
- [v1/prepare_attempt_v1.json](evidence/1a484e65c0eb3e9fe0fc03a4bc6229b0d26ede2489f07b8c7c5f8f6a471f9eb3.json)
- [plan.json](evidence/032b482fa24cea63280b4b1a4752cdfac6084f649685fb219427d3ba40531064.json)
- [binding_repair.json](evidence/d8404b5015b65c9b99fadbb7143de52ecc8a541cb88c175fe3300c4d425c2f5b.json)
- [failed_execute_attempt.json](evidence/42f8d6578f7595a5af452e32e8b618ce8d3851dfa85614126cd483797edd8d5d.json)
- [.tmp/s013_confirm_execution.py](evidence/769e9cd21a405239f776d26bd33455e6e7a10d69de500d4d6e46fd869cb2ed64.py)
- [.tmp/s013_confirm_freeze.py](evidence/484efbc6a22beceaac7663d987be174c9d683785d57d8fdf9640fc38ed757ee6.py)
- [.tmp/s013-confirm-net-execution/confirm_kernel.py](evidence/ef0e346443ff977a2b41068a95e1da48e6ae9fb88e56080bbd83569228a62ae0.py)
- [.tmp/s013-confirm-net-execution/confirm_net.py](evidence/746e36d2f0a6371811b54e3a95f9fa46ded29fbf0c9bffbaa0a3af267194710c.py)
- [.tmp/s013-confirm-net-execution/focused_checks.py](evidence/22cd509dc996fb6b3e56ba9aa2505361c4eabb8dfc15c678d747017be5ee1934.py)
- [.tmp/s013-confirm-net-execution/focused_checks.json](evidence/0bb067b63e6a89841f1d96a869b5c9aa0674d5c4186b8ff899411b3d0cc879cb.json)
- [.tmp/s013-confirm-net-execution/scientific_plan.json](evidence/77ab96f6ac6a4c0b203ab4372583575b0f6535b6904edace47becd73f8b067dc.json)
- [.tmp/s013-confirm-net-execution/original_binding_metadata.json](evidence/1f1767d4481f9f6142870fb31eb47d73e8d29abef2f54564c63bd36899eb64ff.json)
- [.tmp/s013-confirm-net-execution-audit/audit.py](evidence/82670d42c54092a50f2af74f95086ee5150d1bf9223415e7d0bad7ba49cbdc71.py)
- [.tmp/s013-confirm-net-execution-audit/synthetic.py](evidence/a3a0360eef574815087b2c4642bbe3adb86ab919484beff8b9fe94eadccf4dd5.py)
- [.tmp/s013-confirm-net-execution-audit/synthetic.json](evidence/161f298c178764993bf580946e24c6f68378bd45ff826f790f0f441f02fb4c44.json)
- [.tmp/s013-confirm-net-execution-audit/freeze.json](evidence/62daa02a4455dbfa66f6cbc37ffa9dca41cc5152415562dd4522b852815ef5f8.json)
- [research/S013/experiments/EX058_20261011/src/common.py](evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [research/S013/experiments/EX066_20261011/src/opportunity_statistics.py](evidence/565db5bb8e50a49ce303e10c0e0f44eab4f707e8f8c6eed0ec19f528c7b94d9a.py)
- [research/S013/experiments/EX074_20261011/src/economics_reference.py](evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [research/S013/experiments/EX074_20261011/src/account_reference.py](evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [research/S013/experiments/EX074_20261011/src/execution_links.py](evidence/b7aa3220794b93000cffbde4410c97b95f3cc798f7348244b4113cbf7d5da198.py)
- [.tmp/s013_confirm_execution_v3.py](evidence/02c394b35938f5ebc6e3fb7d3e44a07ee32428ca9a7904fb6802d149c6822048.py)
- [.tmp/s013_confirm_binding_revision.py](evidence/a01a2c83355af35abb6f36fbffbc9e35ffb75b1f335329fa7c00593189a3ee3f.py)
- [.tmp/s013-confirm-net-execution-v2/confirm_kernel.py](evidence/f4627a9a14984b4450afa12eb6e77e0b2060befea9b3d64602dcec9a675aa9b2.py)
- [.tmp/s013-confirm-net-execution-v2/confirm_net.py](evidence/19ac337b60a0b8ed5c024e8c76d80c22bf5764ea888d98ea97c85d860fc6d27f.py)
- [prepare.json](evidence/31a992c2a0812c06b20dd392d62f46295157a9e8cab32634cbd21a86edf62bfd.json)
- [features.csv](evidence/9f0d8a9580426e86be765f84e6ddc3eb54246ae32a3ea28cc4ea06f355020147.csv)
- [scores.csv](evidence/aeaf6b4196793e1820be7322894c46294cdaac91092d4ec3f58344e35f95ab53.csv)
- [fit.json](evidence/e17baa162824e505a8263c3f9eb9d9b50e4d58f4c12eaefe18318d931de1efd2.json)
- [policy.csv](evidence/b83c1a9da44a87fadc8eff7416771a50947d402bfa5013ecff7cd52d84405fbc.csv)
- [verification.json](evidence/972a75d94f47ebcb1021dba6b67ce9f3114d3f6ea561fa78dabc989e6ca99f60.json)
- [audit_driver.py](evidence/f78efbb0b1da9045187ab8ab7ba5dfa2afbb33f8df2826984a0131689b99ac52.py)
- [root_review.json](evidence/5b8b22603076168f96bd021c6666bed06af7b96fcf2b8a88427c0e0ccc15c25a.json)
- [episode_attribution.json](evidence/e2cd4a60ff465b10127c3b2baf4f222f9412a07772d46b6e9573217b426c8588.json)
- [review_driver.py](evidence/a6a62b03e2fcb59a4f6270d3a88d97e656227fedd18810408a54514a04f024e9.py)
- [native.json](evidence/8f4bb83f4c8a3892c19b9ecd6bca69073c2a239e0a1e5ecc55b8b8fae42dc357.json)
- [independent_preaccount.json](evidence/7a4ad2d08d708cb57a0b8fadc538b6ce867306efc92d3800c27f1ef1f10586b1.json)
- [budget_receipt.json](evidence/a79d90d006b7d3bd507674840dfc6c1b349c99a3df8d83421c85e913018eaf95.json)
- [closeout_driver.py](evidence/7b519824c5b362b64d8d1b8900cb4017a5a982fa9c75156bf2370ee81c29c0e0.py)
