# 同金融模型的采样引导修订

## 尝试什么、为何继续

EX057每个经济结果有效，但多目标TPE把尚无人满足的收益门同时作为采样约束，below组的观测权重退到EPS量级。算法A精确复现实际首批模型参数，表明这是采样机制与约束设计的相互作用，不是历史导入、账户或策略源码错误。不能用那批远域提议证伪有希望的配置附近或全域，也不能由修订后的未评分draw宣称收益改善。

本组只改采样引导：收益继续maximize objective，BAR_CLOSE DD继续minimize objective；采样可行性用原相对DD、绝对DD、闭合中位、覆盖四项归一化违约量。**最终策略资格仍是原五门AND，原收益目标没有放宽。** 不改Optuna库、不跨DEV、不新增金融模型或参数。

## 金融职责与源保持

逐字复用EX056/057 strategy.py，raw SHA a932d2e28b47c24ec3609c6b2c252bf6fdd69803c4bed9dee5ce611670d16629，定义级源6269f767e96e74051487c9999a25c2b7dd25265d95b44565e2b45e6a3973ea0e。入口前阴后Close−R>alpha·ATR13[t−2]，初始S0+a(R−S0)，接受后L+b(H−L)+cycle_g·max(0,P−H)，原候选/冻结H/整entry区间排除/旧线先失效/due锁存完全不变。

U仍为前Close>前SMA65>前SMA260，仅实际买入激活entry_u及cycle_g，持仓不随当前均价改变；非U不是熊市，均价排列不是斜率。g保护新增推进不保证真实净盈利，无时间退出/rho/盈利门。参数域alpha[0,2]、a/b/gu/gn自然[0,1]不变；alpha≥2的29原始信号低于原双频联合所需至少32闭合，域外不可能在本训练同时达标，不新增硬门或宣称域外收益无价值。

## 历史导入与约束双列

等待EX057全族、独立统计、必要原账和正式报告公开后，认证同一family及calendar，按原trial_number顺序导入45个成功唯一点（含最初056四历史点）。逐点认证原actor/content identity、定义/source/feature graph/state schema/有效参数/Spec、主input SHA2d2a98bfe9f04891e47cb6c938d0eb1b27bb28f41622f73aef010ae23d6d717c，以及原request/result身份。

旧公开全族原序列及其独立统计审承接每点原checkpoint认证，不将family EvidenceRef冒充每点V4，也不重算45技术控制。有独立完整V4 ref的点另外保留该ref，未单独公开的点保留原family/参数/actor/request/result/输入/曲线及checkpoint来源。45旧点0新compute、不是45次新观察。

通过公共enqueue/ask/tell把旧结果以COMPLETE导入新唯一Study；每点保留原五goals与原五约束向量，另外派生新的sampling_constraint_vector=原向量后四项。tell前设置二者，实际FrozenTrial.system_attrs.constraints由公开tell重新产生四项并导出；不复制旧五项system attrs，不用旁注冒称接线修复。原45点最终五门仍0joint，而采样四项可行27，仅表示可引导采样。

## 预检与正式预算

Optuna4.9.0、单InMemoryStorage Study、seed17/n_startup_trials16/constant_liar=True/multivariate=False及相同KEYS顺序保持。45历史已足够启动模型，不新增12锚。24次新model TPE提案目标24 unique，意外重复占提案记录、引用原值0compute，不免费补问；失败/未知保留不自动重试或重建Study。

首批四个实际提议在evaluate前必须与已冻结的最终45观察B四风险/频率设置的未评分参数逐点相同。expected仅用于metadata断言，不enqueue这些draw、不当金融门、不伪造收益。准备期已在0账户/0SE临时算法Study验证45导入、实际system attrs四项及首四精确一致；正式仍重新核验并留证。若不符，先查顺序/kwargs/RNG，停止而不覆盖expected。

24初始后最多6固定匹配，完全沿既定规则：全部COMPLETE且其余四个原门同时通过的集合按年化最大、同分CID字典序选代表；若有joint该代表自然joint，但所有joint独立完整保留，不只用Study.best_trials。冻结其alpha/a/b，比较静态g0/.75/1/代表gu/代表gn及交换gu/gn，先与全部历史/初始及彼此去重。空集合跳过写明，不用评分兜底；匹配不递归、不补random，匹配若新胜出也进入最终资格与前沿。

最多30新候选+2共享BH=32compute；45历史+至多30=75 Study记录。workers4/native1/batch4，session16和最后8+至多6匹配同session，单session最多16新unique、只2BH。沿旧checkpoint/内存日志与全部紧凑原序列留证，必要full V4只公开RESUME原hash并断言0compute；不为全部点复制巨型解释账本。

## 判断与反证

比较采样引导是否恢复对有效观察的利用，以及实际新完整账户是否接近或满足原五门；权重修订成功不等于策略目标达成。旧负面点、全部选择史和有限覆盖风险不删，0joint如实交付，不以四项sampling-feasible冒称金融达标。没有新源、MA窗口/映射类别、阶段四、封存测试或生产。

2024—2025训练、必要2023预热、2026封存；100000新空仓、0/1全资金只多、每侧.1%成本、1%买限价及原tick/严格Low/下一段执行保持。官方算法依据与独立复现仅用于技术核验，无新市场数据：[v4.9 sampler](https://github.com/optuna/optuna/blob/v4.9.0/optuna/samplers/_tpe/sampler.py#L895-L906)、[v4.9 Parzen](https://github.com/optuna/optuna/blob/v4.9.0/optuna/samplers/_tpe/parzen_estimator.py#L56-L69)。
