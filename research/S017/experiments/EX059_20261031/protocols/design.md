# 单收入目标与联合参数分量：条件有界继任

## 尝试什么、启动条件

只有EX058最终原五门0joint时才启本程序；setup与正式历史认证均显式检查，若已有joint则取消而不继续搜索。当前条件已满足。金融模型、均价背景、域、执行和原五门全部保持，不增加指标、映射类别或持有期限。

采样同时作两项改变：单objective最大化净年化，以及multivariate=True用同一历史观测的联合分量保留五个参数共同出现的信息。前者与“原风险/频率合格后寻找足够收入”一致，后者针对已知参数协作。不能对两项变化作单因素金融归因，不能称学习完整协方差、自动更局部或已经提高收益。

## 金融与验收不变

strategy.py逐字复用raw SHA a932d2e28b47c24ec3609c6b2c252bf6fdd69803c4bed9dee5ce611670d16629；定义级source6269f767e96e74051487c9999a25c2b7dd25265d95b44565e2b45e6a3973ea0e。E0收复后参与延续，初始S0+a(R−S0)，接受后L+b(H−L)+冻结cycle_g·max(0,P−H)，真实entry背景、候选与最后accepted分离、旧线先失效、整entry区间排除和due锁存均不改。

alpha[0,2]、a/b/gu/gn自然[0,1]保持。alpha≥2固定训练29原信号低于双频必要32闭合的域外逻辑界复用，不增加硬门。sampling仍为原四项风险/频率归一化违约量；最终仍原收益/双DD/双频率五门AND。移除DD作为额外采样objective不意味着删除DD指标或放宽25%门，也不加入目标内更低DD偏好。

## 历史、实际API与反证

认证EX058完整公family及独立全族序列审，导入全部69成功唯一历史点，0新compute，保留原actor/参数/source/input/request/result及原序列、经济和资格。原来两objective观测[ann,DD]另外保留；新Study directions只有MAXIMIZE，trial.values与tell只传ann一个值，DD仍在metrics、原硬门及诊断前沿。实际system_attrs.constraints由公开tell重新派生四项，不抄旧system attrs。

同域全五维FloatDistribution完整，联合relative search space必须包含五参数。通过公开sampler hooks记录空间；若发生sample_independent fallback立即明确停止，不能静默降级。独立0账户API前检先检查联合5维、0独立fallback以及新的单目标联合首四expected；正式首batch evaluate前再次逐参数断言。expected只验证接线，不enqueue它，不给未评分draw伪造绩效。

独立诊断保留重要反证：同69观察下，单目标独立版本首四到旧代表距离约.087/.192/.100/.168，联合版约.216/.171/.257/.371；已知较好g中心profile的密度rank由独立1/7变为联合7/7。这不能用来拒绝或重抽提议，也不能称联合模型已更有效。选择联合分量的理由是金融交互，而非事后收益、邻域或密度排名优势。全部6临时算法Study/24未评分draw/126纯密度probe为0账户/SE/新市场标签，非金融试验。

## 唯一Study与有限预算

Optuna4.9.0 TPESampler seed17、n_startup_trials16、constant_liar=True、multivariate=True；不改库。69旧点足够启动模型，24次新model TPE，无新轴锚。重复提议占记录、引用原值0compute，不免费补问；失败/未知保留，不静默重试或重建Study。

初始后最多6项匹配：全部COMPLETE其余四个原门同时过池按年化最大、同分CID字典序选代表，所有joint另完整保留。固定其alpha/a/b，静态g0/.75/1/代表gu/代表gn及交换gu/gn先与所有历史/初始/彼此去重。空池跳过写明，不用评分兜底、不递归匹配、不补random；匹配可能成为最终最好或joint，最终集合不能只看初始24。

最多30新候选+2共享BH=32compute，69旧+至多30=99 Study记录；69历史不是新独立样本。单主Study、workers4/native1/batch4，session16和末8+至多6matched同session、单session不超过16新unique。保留WorkingSet/checkpoint/全部成功负面记录和原序列，必要原账只公开RESUME原hash并检查0compute。

## 决定与边界

完整五门达标才有后继候选资格；算法metadata通过、sampling-feasible或四门通过均不能采用。0joint仍保留完整负证及未达标前沿，不把预算耗尽称最优或达标。多轮同训练选择史全部承接，有限搜索不构成独立市场验证。

2024—2025训练、必要2023预热、2026封存；100000新空仓、0/1全资金只多、每侧.1%费、1%买限价/原tick与严格Low、下一段执行不变。无阶段四、生产、新源或平台变更。若本组仍无达标，后继必须另有具体可证伪问题，不在本协议中私扩预算或随未评分draw再改sampler。
