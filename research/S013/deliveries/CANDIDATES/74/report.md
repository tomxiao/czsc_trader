# S013：用户决定暂停研究及收尾（2026-10-12）

研究状态为PAUSED，研究目标尚未达成。用户认为现有候选在年化收益、最大回撤、交易频率和稳健性方面不足，决定在没有新的数据来源与研究方法之前暂停。收尾资料完成不表示策略验收通过。

用户原话：S013的候选在年化收益、最大回撤、交易频率、稳健性方面都稍显逊色。在没找到新的数据源以及研究方法之前，我决定暂停研究。请完成收尾工作。

## 截止结果及关键资料

- 研究推进至EX098，共98个实验目录；并非98套均按新四门和32点完成验收的策略。最后授权EX089–EX098完成10/10，剩余0，EX099没有授权。
- 203个正式登记候选，按原策略实际账本和统一固定1%buyhold基准检查中心，新四门联合通过0；收益147、年度回撤195、盈利年份频率8、下跌年份盈利134分别通过。182个原策略溢价为1%，另21个保留原溢价，未规范改参重跑。195份旧schema5证据未冒充当前schema6；登记资格不更改。
- 117个仅缺盈利年份频率的候选，在这段历史有58条不同交易路径。最近六个均72笔、差5笔，实际同一路径且无买入确认；收益余量约0.165个百分点。规则挡过赢家，也挡过输家，尚无在T日可识别并保留其余三门的新增有效交易证据。事后盈利价格片段不是可执行机会或可追回利润。
- C8880中心净年化17.13%、全期回撤13.62%、盈利年份68笔不足77；13参数总距离5%的32点，收益Q10 6.40%、回撤Q90 28.35%。新四门逐项通过7/32、32/32、5/32、2/32，联合0/32。旧全期频率27/32不能充当新盈利年份频率5/32。
- EX089–EX092为组件检验，0新完整账户；EX093–EX098各1个完整中心，均未过新四门，按事前规则停止新32和双费评价。没有这些新策略的扰动Q10/Q90，不能填0或继承C8880扰动。

主要报告：[EX098额度收口](research/S013/experiments/EX098_20261012/others/report.md)、[203中心检查](research/S013/reviews/20261012_new_four_203/report.md)、[203明细](research/S013/reviews/20261012_new_four_203/centres.csv)、[117频率缺口](research/S013/reviews/20261012_frequency_117/report.md)、[117排名](research/S013/reviews/20261012_frequency_117/ranking117.csv)。EX096及EX097最终阅读采用[EX096修订报告](research/S013/experiments/EX096_20261012/others/report_v2.md)、[EX097修订报告](research/S013/experiments/EX097_20261012/others/report_v2.md)，原件保留。

## 已完成的收尾与保存边界

最新十轮正式FULL记录、报告副本及修订关系逐一核对，两个只读审查报告与正式报告逐字节一致。已核对203登记数量；暂停前S013命名计算进程及相关自动任务配置匹配均为0，协作任务已结束。仅补录暂停决定、收尾资料和已有C8880新门统计；0新实验/账户/模型，不新增机制、数据或优化。

历史实验、候选登记、价格和账户证据保持不可变；不删除assets或必要缓存。Git保存源码、报告和引用，不能替代被忽略的本地assets；本次保留本地资料，不声称已完成远端或完整环境备份。现有用户修改的DEV与RSCH文档保持原样，仅更新S013可变HANDOFF为最新暂停状态。

保留研究分支codex/s013-mechanism-robustness，本地保存收尾；没有合并master、打tag或推送。没有选型、冻结、PTE或生产变更。旧资格按旧依据解释，不把本次暂停等同候选注销。

## 恢复条件与下一步

此前自主研究授权按本次用户决定暂停。发现线索不自动恢复；下次先提出新的数据源/研究方法、适用权限和具体增量，明确机制、最强反证、最小验证方案及预算，由用户决定是否恢复。不得以改名、邻窗或调阈值冒充新方法，不沿用已用完的十轮额度。

下一步是保持暂停，等待用户的新方向及明确授权。当前没有待运行实验、待补账户或自动继续计划；目标未达成不因收尾变为完成。

## 正式关联证据（项目根目录相对路径）

- [research/S013/materials/research_pause_20261012.json](research/S013/assets/evidence/EX098_20261012/a888a962f97ecb78c5409fe857494c65dae1c1bdd2a03ff51270d65b3ed05ab3.json)
- [research/S013/materials/research_pause_provenance_20261012.json](research/S013/assets/evidence/EX098_20261012/45d9df336dc9584a4b64d8a116d9d97582e21f6695284c8cf98729ab97e016fa.json)
- [research/S013/materials/c8880_new_four_parameter_review_20261012.json](research/S013/assets/evidence/EX098_20261012/d35bfbcf9c1acebcf1b84f51bcfc51af137c937cc2e9644619a77c618be96252.json)
- [research/S013/materials/research_pause_20261012_src/closeout.py](research/S013/assets/evidence/EX098_20261012/33cf732d7bde91dc1be2ee8bf35943a3343914e9b58f08b11d5e20dbf8c72b56.py)
- [research/S013/reviews/20261012_new_four_203/summary.json](research/S013/assets/evidence/EX098_20261012/5e001b81c23b595c7db653ec928f6a6deb788d5cb0def085f6119e92e5f15ee9.json)
- [research/S013/reviews/20261012_frequency_117/review.json](research/S013/assets/evidence/EX098_20261012/3baec28f7b611040654926407f8e4e5aca7540a340ffcde6cceceb6f47b3c1ac.json)


## 证据导航修订（v2）

仅将收尾报告中的内部逻辑路径改为项目根目录实际相对路径；原报告及SHA保留，经济结果、暂停决定、额度和资格均不变。[203审查及117复盘证据索引](research/S013/materials/research_evidence_index_20261012.md)提供旧报告关联证据的实际路径。此修订没有新研究计算。
