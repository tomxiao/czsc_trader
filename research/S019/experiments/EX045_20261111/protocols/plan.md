# 第7轮／机制研究第3轮：四结构等预算参数适配

本轮仍处阶段二，承接用户批准的六轮机制研究。EX044完成、报告公开校验通过并结算第6轮后，才创建本实验。问题是：在原六门目标与相同提议额度下，四类退出／参与仓位结构经适配后，各自能够呈现怎样的收益回撤取舍？本轮产出限定为已见开发样本中的有限搜索证据，完整阶段四与独立验证另按原流程开展。

四家族依次为hard_hard、hard_linear、ramp_linear、daily_close_hard。统一固定入场信号、下跌1日、持有5日、参与跨度3日等非搜索参数；源码逐字节复用EX044的strategy.py，显式声明原七字段持仓周期状态。控制分别为EX044的hard_hard10_center、hard_linear10_center、ramp_linear10_center，以及EX043的daily_close_center。最后一组显式增加participation_policy=hard、participation_width=0.1两个中性参数，既有共同参数和其他经济定义逐项核对；其经济等价性由本轮首个新账户的逐日权益、bar路径、目标与成交精确parity确认，原账户header保留。

共同连续域：weak_fraction[0.2,0.5]、quiet_fraction[0.35,0.85]、participation_threshold[1,1.5]、trail_atr[2,2.8]。linear家族另搜索participation_width[0.05,0.3]；ramp_linear另搜索exit_width[0.25,1]。全部float使用step:null，直接采用Optuna连续提议。四家族分别有4、5、6、4个连续轴；相同24次提议表达本轮投入相同，搜索难度和覆盖充分性随维度与响应形态而异，因此结论只比较这次有限适配结果。

每族独立Optuna4.9.0 InMemoryStorage、多变量约束TPE、constant_liar，startup_trials=8，固定种子分别20261117／18／19／20；每族首提议固定上述控制，计入各自24次额度，旧观察导入0。先满足NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费用买持MDD的80%、滚动60日闭合中位数≥6、至少3笔覆盖率≥90%，再以未舍入NAR为优化目标。全部提议执行完整账户，指标失门仍完整反馈约束；无剪枝、无自定义加权目标。

每波先对全部家族各ask4，再统一反馈屏障。12个账户worker上限，每worker1原生线程；首波先执行4个控制，通过parity后按前三族9个、末族3个请求计算；后续五波按前三族12个、末族4个请求计算。全部家族当前4个观察齐备后，才按固定家族与trial顺序tell，再生成下一波；来源完全相同的精确重复可减少实际请求数量。该12+4分组提高可用12进程的利用上限，实际时长按记录披露。

候选提议槽位预留C0684—C0779，next_candidate_start为780。相同源码、完整参数和经济合同的精确重复沿用本轮首个正式candidate、handle及account_ref，当前trial保留proposed_candidate_id与alias_of；逐族披露24次提议、实际唯一配置、别名数量和完整反馈数量。公共TDR ResearchExecutionSession与checkpoint保存精确请求；所有ask、定义、账户引用、result和tell以不可变JSON保存于others/trials。恢复依固定seed重建ask/tell并逐项核验，已完成精确身份通过公开账户与checkpoint复用；失败与未知计算独立计数，技术错误先停审。

固定2021预热及2022-01-03至2026-10-30统一已见历史，10万美元、HFQ整数单位、原限买市卖合同、每侧0.1%费用；最多96个新策略账户及1种标准买持身份，实际计算次数与恢复情况按日志计。研究方案、源码、runner、状态声明、公共辅助依赖和控制引用冻结hash。动态summary、candidate_specs及close_inputs输出到others供显式搜索收口分支使用，protocols/search.json保持事前内容。

保留依据为各族原六门达标数量、约束下最高NAR、Calmar与MDD余量、同族提议分布和参数边界；同时呈现失门配置及费用，不由单个最高值宣称稳健。更高维家族若暂未找到达标组合，应结合本轮24次有限覆盖描述结果。任何后续阶段四候选仍需用户选择及完整自检。完成后结算本轮1次额度，本次六轮剩3；runner不直接修改预算。
