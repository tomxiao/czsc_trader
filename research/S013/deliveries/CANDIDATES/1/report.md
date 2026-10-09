# S013阶段三：后复权研究账户结果

6个配置同时通过三项目标，建议进入阶段四自检。

本轮成功评价378个独立配置，实际评价尝试394次；其中固定重算旧搜索270个独立配置。净年化门槛为10.8342%（1.5×同窗BuyHold 7.2228%），逐自然年回撤须严格更小，1636日须至少110笔闭合交易。三项同时核验，未降低目标。

## 口径与平台交付

采用用户选择的方案A：100表示100个研究单位。2019-12-31固定归一化锚点，因子0.2803；成交价格、现金、费用、持仓及BuyHold共用同一账户单位。研究单位包含供应商复权处理所对应的权益影响，不重复增加现金派息。PTE始终输出未复权价格和真实ETF份额。

平台价格契约已本地提交9caede79，95个聚焦测试节点通过；候选登记暴露的独立审计价格尺度遗漏另以3a8ab3a7补齐，57个相关节点通过（两批节点有重叠），修改文件Ruff通过。本轮未执行全仓回归。尚未合并master、打tag、推送、同步或部署。研究模型的收益不直接等于真实整份额PTE账户收益。

旧基线账户证据保持原件。此次审计修正为每日证据补充原始收盘与研究价格尺度，在原始网格核验参考限价，再按T日尺度转换；从相同缓存结果重新发布审计证据，不改请求、成交账本或经济结果哈希。正式登记的全部14个候选通过完整审计和加载核验。

基线限价依据T日未复权收盘参考加20bp，在原始0.001报价网格取整后按T日因子转换；后续溢价对照采用实验前发布的参数计划，用户确认的限价买入约束保持。T+1使用同口径历史行情撮合，卖出市价，计划形成不读取下一日开盘或复权因子。旧协议中的“下一日开盘加20bp”文字与实际实现不一致，本轮明示修正，旧证据原件保留。

持有期限与损失控制锚点按信号目标仓位序列计算；限价入场延后时，实际持有天数与成交成本会有差异。完整账本采用实际成交，不把信号次数当成闭合交易次数。

### 口径修正的经济影响

| 指标 | 原始价格口径 | 后复权研究口径 |
| --- | ---: | ---: |
| 同一基线策略净年化 | 7.4194% | 7.9839% |
| BuyHold净年化 | 4.0773% | 7.2228% |
| 1.5倍收益门槛 | 6.1159% | 10.8342% |

基准的口径修正幅度大于基线策略，旧收益门槛不再适用。旧schema3账户原件保留，本轮采用含明确价格契约的schema4请求；旧统计只用于历史对照，达标判断使用新账户。

## 前沿与反证

下表保留逐年回撤通过集合中净年化/频率的非支配配置、全部达标配置，以及基线、最高收益和最小搜索缺口对照。频率在达标线处截断，达标后不偏好更高频率。这是阶段三的取舍展示，尚未进行阶段四自检或排序。

| 配置 | 净年化 | 闭合交易 | 每60日 | 逐年回撤 | 未满足项 | 全账户证据 |
| --- | ---: | ---: | ---: | --- | --- | --- |
| C0375 | 14.2072% | 65 | 2.384 | 通过 | 频率 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/b51ed48585ef336a55944819de71c9abbcd5b01d02382bce4005ff8cbc897756.json) |
| C0385 | 13.5570% | 111 | 4.071 | 通过 | 无 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/53a2a66fdbb9cd58925ac37c5f6acec84f59feb6b39bdd92a39ba5d26295f1bb.json) |
| C0357 | 12.6950% | 61 | 2.237 | 未通过 | 逐年回撤、频率 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/fe286c0b52838fc4f36f3a565497c4b09bd393806518d52c18ed6d41d5e48683.json) |
| C0384 | 12.3396% | 111 | 4.071 | 通过 | 无 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/5e5f8167e80be3a3d8d6212208d729b594e46046d826a56c7acfe0247371730d.json) |
| C0371 | 12.3300% | 111 | 4.071 | 通过 | 无 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/11de885cfa94375565ec452dac283aaade098e4d412b6a742a282e38ae145ec9.json) |
| C0387 | 11.9643% | 111 | 4.071 | 通过 | 无 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/2f4ace7978c3623b2e4b33ea6ad480469938834c92fa16c6348cbb9674f245be.json) |
| C0392 | 11.8446% | 112 | 4.108 | 通过 | 无 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/3e2226319625c50d6fa8f62860ddc9e13d75807ed8397b2ca85e23580718ff2d.json) |
| C0386 | 11.8098% | 111 | 4.071 | 通过 | 无 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/fb1f003618e5cf283828e5a02b0e5c4fc19f9314d3e57a7a1fa4fda6d647bd4a.json) |
| C0351 | 10.2119% | 144 | 5.281 | 未通过 | 收益、逐年回撤 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/30b2c5d2b3364e517a9bf9cf8aa384ef39dc9e6e11cc820498840cc5df59c27e.json) |
| C0343 | 9.7606% | 64 | 2.347 | 通过 | 收益、频率 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/c75acb8a307dc29c8f5d0a70ea3482c19ce00063e891b0e0e263eaa44987cef4.json) |
| C0176 | 9.0571% | 64 | 2.347 | 通过 | 收益、频率 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/fc0913e345e505145ea18cde13a2903accf3676aabca3ee5e3a4f71b4b70fb49.json) |
| C0339 | 8.6802% | 147 | 5.391 | 通过 | 收益 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/7587861b9794991548ea00be69037f21ecd0ae746ff43a10cb07376ae2b08e49.json) |
| C0195 | 8.2497% | 146 | 5.355 | 通过 | 收益 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/d06979c6355e9cd080e2e454e39be6872f2b2cebb6a23509995b8e9e20e6c12f.json) |
| C0001 | 7.9839% | 74 | 2.714 | 通过 | 收益、频率 | [账本](../../../assets/deliveries/CANDIDATES/1/evidence/2ccd698e1b2c1e9bfeb9fedb02028703f4490ef41100b123a348f2aec246e06b.json) |

### 全部达标候选的交易机制

共同参数：180日高低区间，收盘价区间位置≤0.675时目标满仓；最长信号持有8个交易日；无相关性、动量或移动止损过滤，冷却期0。区间位置达到退出阈值、达到持有期限或触发已启用的信号锚点止损时目标清仓。买入限价按T日原始收盘与下表溢价形成，卖出市价；成交金额每侧费用仍为10bp。

| 配置 | 退出区间位置 | 限价溢价 | 信号锚点止损 | 最小逐年回撤优势 |
| --- | ---: | ---: | ---: | ---: |
| C0371 | 0.90 | 1.00% | 未启用 | 1.5311个百分点 |
| C0384 | 0.85 | 1.00% | 未启用 | 1.5314个百分点 |
| C0385 | 0.95 | 1.00% | 未启用 | 1.5305个百分点 |
| C0386 | 0.90 | 0.50% | 未启用 | 1.5134个百分点 |
| C0387 | 0.90 | 2.00% | 未启用 | 0.8918个百分点 |
| C0392 | 0.90 | 1.00% | 6% | 1.5567个百分点 |

![净年化与闭合交易取舍](../../../assets/deliveries/CANDIDATES/1/evidence/e7eac87543f67ee7980cf2197e935529ebfb99562d0f0ec6ce876a4715c73229.png)

## 逐年回撤核验

展示逐年回撤通过集合中收益最高的C0375（频率未通过），以及全部达标集合中收益最高的C0385。每年从初始资金或上一年末权益开始取峰值，现金和持仓跨年连续；2026年截至9月30日。

| 年份 | BuyHold回撤幅度 | C0375（频率未达标） | C0385（全部达标） |
| --- | ---: | ---: | ---: |
| 2020 | 14.9790% | 6.4460% | 9.3229% |
| 2021 | 9.7079% | 3.1768% | 5.0657% |
| 2022 | 28.4220% | 21.9599% | 24.9559% |
| 2023 | 17.2743% | 14.3635% | 15.7140% |
| 2024 | 18.5832% | 17.1471% | 17.0527% |
| 2025 | 13.8038% | 6.9289% | 6.4102% |
| 2026 | 18.7703% | 9.1003% | 10.0582% |

## 搜索与选择历史

旧实验EX003保持原位。本轮在EX004先固定重算旧成功配置，再依新账本选择局部扩边与反证；旧原始价格排名和阈值未参与新达标判定。Optuna管理固定队列，种子13；最多8个spawn进程，每个1个原生线程，单请求workers=1。固定队列中的重复配置复用同口径结果，失败状态显式保存。

本轮两次Windows spawn管道句柄失效，保留16项UNKNOWN原状态和失败trial；新计划显式重试并补齐剩余未执行项，成功后逐配置核对完整覆盖。第二次中断后明确调整为4个工作进程，每个父进程仅发起一批，继续多进程完整评价。未知状态未计作成功，也未作为策略失败。

| 搜索组 | 实际评价 | 独立配置 | 达标 |
| --- | ---: | ---: | ---: |
| hfq_followup_1 | 60 | 60 | 0 |
| hfq_followup_2 | 11 | 11 | 0 |
| hfq_followup_3 | 22 | 22 | 1 |
| hfq_followup_4 | 15 | 15 | 5 |
| hfq_initial | 1 | 1 | 0 |
| hfq_replay_completion | 24 | 16 | 0 |
| hfq_replay_recovery4 | 22 | 22 | 0 |
| old_configuration_hfq_replay | 239 | 231 | 0 |

完整参数、指标、年度账本核验值、对应身份及原始/后复权同配置对照见关联搜索证据。已保留全部达标配置；其余正式保留点覆盖已声明前沿和重要反证，其完整账户及源码可公开加载。

## 数据与结论边界

当前检查覆盖378个成功配置。四处High偏差未进入本策略买入LIMIT/卖出MARKET的撮合输入；2020-12-01的Low偏差未发现会改变成交金额的订单（潜在改变数量0）。保留原异常和核对证据，没有手工改写行情。

全部开发池用于研究和参数选择，逐年比较属于用户回撤约束，不能解释为独立样本外验证。组件与旧搜索结果已见，供应商复权因子历史发布时间、修订及实盘馈送延迟未重建。采用当前历史版本的复权研究模型；后续真实份额交易仍须单独评价。

## 停止评审与下一步

### 已验证方向与收口依据

固定重算旧实验270个成功配置后，按新账本开展四轮已事前发布的对照计划，分别产生60、11、22和15个新配置；加上基线，共378个不同配置成功完成完整账户评价。四轮覆盖区间窗口、入场位置、退出位置、持有期限、相关性与动量过滤、止损、移动止损、冷却期和限价溢价。重复配置复用结果，16次运行状态未知的尝试保留原件并关联成功重试。

收益改善并非仅来自价格口径修正：相同旧配置固定重算后仍无同时达标点。限价溢价、区间窗口与持有期限的联合对照产生了新的改善线索。120日窗口的高频中心从C0195扩到C0339，收益改善仍低于门槛；180日窗口、18日持有的C0357收益通过，但交易次数和2024年回撤未通过。加6%信号锚点止损的C0375收益达到14.2072%、逐年回撤通过，但65笔闭合交易仍未满足频率。

将180日窗口路线的最长信号持有期限缩至8日得到C0371。随后完成相邻持有期限、入场位置、退出位置、限价溢价、窗口和止损对照，新增五个同时达标点。全部六点予以交接：C0371、C0384、C0385、C0386、C0387、C0392。阶段三的排序展示仅用于解释结果，正式自检及选型留待阶段四获批后进行。

窗口上限180日曾为暂定边界，已扩至240、360日；持有期限的短端与长端、限价溢价及止损邻域也已检验。长窗口对照、7/9日持有、0.65/0.70入场阈值及3%止损均出现目标缺口。因此当前证据支持一组有局部执行与退出容忍度、同时对入场、持有期限和窗口较敏感的候选，不能推断整个参数域普遍有效。

### 最强反证与剩余问题

六个达标点只有111或112笔闭合交易，最低要求为110笔，频率余量小。中心相邻的7日持有有124笔交易，但收益和2020年回撤不达标；9日持有只有103笔。入场阈值从0.675变为0.65或0.70、窗口变为150/240/360日也未同时达标。六个候选共享大部分参数和同一研究族，不能解释为六条独立发现。

全开发池反复用于研究和选择，未保留独立样本；供应商历史复权因子的可得时点与修订未重建；止损和持有期限的信号锚点与实际限价成交存在差异。标准参数联合扰动、滚动时间稳定性、盈利交易集中度、成本与执行压力、统计不确定性尚未完成。它们是阶段四应回答的问题，不在本轮自行增加经济否决条件。

### 研究员判断与下一步

当前已完成旧域重算、改善来源对照、暂定边界扩展和首个达标点之后的邻域反证，已足以提交阶段三候选集合。继续扩展同池搜索可能增加选择偏差；下一步价值更高的是在事前声明的阶段四协议下比较全部六个候选的脆弱性与取舍。因此建议用户批准进入阶段四，完成五项标准自检和既定排序政策，再决定具体候选。此建议不表示已完成稳健性检验或未来收益承诺。

若阶段四揭示执行、时间稳定性或交易集中性存在可解释的机制缺口，可据明确证据提出重新进入阶段三的方向；新增数据、平台变更或目标调整仍须相应授权。冻结与真实份额PTE评价须分别处理。

## 关联证据

- [hfq-search-results](../../../assets/deliveries/CANDIDATES/1/evidence/057d1c88889bbc410fa2828f1527e04c02859dcbdbce9ae447c9816f1cbb9ee7.json)
- [hfq-search-analysis](../../../assets/deliveries/CANDIDATES/1/evidence/5f919a558ed0cad267da012eb7667ab1151a9d4ba66cd749e0c218943830dea1.json)
- [hfq-quality-impact](../../../assets/deliveries/CANDIDATES/1/evidence/5f5654a0d0c54581d5c8910e1557149cee2335e021db3429b225bc233398ed33.json)
- [hfq-stopping-review](../../../assets/deliveries/CANDIDATES/1/evidence/089f517d509946be31e36ec95e3e097129ac510772c4ae9e06897c21273c751e.md)
- [hfq-replay-plan](../../../assets/deliveries/CANDIDATES/1/evidence/ccb2532439065abecefffa845912593dcd1f4aac3bb600401bd6b1d904185292.json)
- [hfq-replay-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/2c6e880283fe4f49fbb8f9455b0929d875bdf7002ac429ea6b5e1022bdce7860.json)
- [hfq-replay-interruption-history](../../../assets/deliveries/CANDIDATES/1/evidence/fb432e3ed345c6dd2f3ce0162cc1668e4e6f1816e492f321b7158d39e9bf1573.json)
- [hfq-explicit-replay-completion-plan](../../../assets/deliveries/CANDIDATES/1/evidence/137ef9d7fe328997fb3f5e5d5aa422130895cfe30b96df977aec8e512c48f010.json)
- [hfq-explicit-replay-completion-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/949a3ac1093efa50e2f6f1eba58ebf7090f32b060b0ca0a96413a6749557c458.json)
- [hfq-parallel-interruption](../../../assets/deliveries/CANDIDATES/1/evidence/72d65685f483c355bf77f352221d5a995404e6d6d5b069dcf67d517f1ae293f0.json)
- [hfq-parallel-interruption-r2](../../../assets/deliveries/CANDIDATES/1/evidence/9ae28d885932a1afdb1d73ea0005f35b1d98676235c792841d7506dc988166f2.json)
- [hfq-explicit-recovery4-plan](../../../assets/deliveries/CANDIDATES/1/evidence/d6ed0c031ba08871f7e7650b18500ff57d6a28bb38771008257414f72b59c4ed.json)
- [hfq-explicit-recovery4-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/8d11b2a61576b58414be72a2f4ad28c017324702aee85529c106b4dc9e7fea65.json)
- [hfq-extended-preparation-rejection](../../../assets/deliveries/CANDIDATES/1/evidence/dfdaf4e0603610ec7a59afe9bf55542ae68d783eff029fece71769ee1c51c5f3.json)
- [hfq-audit-contract-correction](../../../assets/deliveries/CANDIDATES/1/evidence/81fc050cd02c523a04b5740e239a4c84b95de07da116416102d980a3bc8cc53d.json)
- [hfq-followup-1-plan](../../../assets/deliveries/CANDIDATES/1/evidence/2f533192e981e533c5c75c7bb831eb2ea75307ef045d34f5e4fd1b31ca86150a.json)
- [hfq-followup-1-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/08b67489ac59be2e7a960f6a2a563d48484dc06f6e65cdf7890cd4f7aa03586a.json)
- [hfq-followup-2-plan](../../../assets/deliveries/CANDIDATES/1/evidence/84c350942ed4afddbb732a9a9e777fdfba6c31a21698d562402e5cab6c641ae0.json)
- [hfq-followup-2-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/6337ecbf24d9c4c026b93726cf62a093f399aad8f3406c5d9b86e0bc5250a689.json)
- [hfq-followup-3-plan](../../../assets/deliveries/CANDIDATES/1/evidence/0521b6f86e067c32dca07652ec1d5d4847090c125d3753755cc73232cc02af95.json)
- [hfq-followup-3-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/d039e97568ac1e75fdd76224009e7e13fdfa1ab82a0d6f5ff0f4ce3e63e1470d.json)
- [hfq-followup-4-plan](../../../assets/deliveries/CANDIDATES/1/evidence/4d64b06936a3610b92052cb3138ab9f975b6132e91ba5fd254ce0300e1238993.json)
- [hfq-followup-4-coverage](../../../assets/deliveries/CANDIDATES/1/evidence/8d348e3d7ab288e9a4044e8c1ab091fa00c79f45dc1640b188ee9c565441aa8e.json)
- [authorization](../../../assets/deliveries/CANDIDATES/1/evidence/05dba9d42fe47ab54f4a5e5db6e9be37abe8f0267345a2541152fbb61ba8251a.json)
- [protocol](../../../assets/deliveries/CANDIDATES/1/evidence/e265b2f26e8042bf78981950ddfe53ed8aebcf35d4d87247a44d004af0879c2b.md)
- [hfq-reproduction-sources](../../../assets/deliveries/CANDIDATES/1/evidence/61116860dbfe462c0f36db02511004b914b6306d8c7ee8c9e6c0868b271c349f.json)
- [hfq-performance-frequency](../../../assets/deliveries/CANDIDATES/1/evidence/e7eac87543f67ee7980cf2197e935529ebfb99562d0f0ec6ce876a4715c73229.png)
- [hfq-selected-account-diagnostics](../../../assets/deliveries/CANDIDATES/1/evidence/cc222f22d7bfbee4db49cf01382e8339b745638a81b59a3117a8643eeb39c803.json)
