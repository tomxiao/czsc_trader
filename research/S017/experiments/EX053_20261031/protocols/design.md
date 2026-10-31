# EX053 已确认突破后新增推进的动态回吐容忍

Status: PREDECLARED，获既有阶段三授权的有界继任；不是EX052原预算内追加，不改52冻结源/48结果。

## 金融问题与最强反证

EX05248个实际参数点全部收益门失败，18个通过绝对DD、全部通过相对DD及双频率；max-return C136185.69%/DD32.74%，强风险频率C147171.90%/22.54%。当前静态接受线L+b(H−L)允许回吐随H之后的新增推进等额增长。本组检验是否把这段已完成的价格推进部分纳保护，而非添加预测信息或净利润资格。

C136主DD的accepted正mark相关区间贡献约64.39%，但跨夜至次日首个完成点区间约51.78%（不是自动全等于纯Close到Open跳空）；这些是会计归因，不是可收回损失。若lastClose已触发，nextOpen退出仍可能影响首30分钟部分；g不能保证更早触发、线价成交或躲开Close到Open跳价。新保护可能截断正常回踩后的大盈利、加大重复交易/费用。全部旧族、旧M011移动线负证、七年及长档负证、重复训练选择史保留，不复活旧36+12或时间规则。

## 参数与连续决策函数

仍原M006和alpha过滤：前阴Close<Open且当前Close>前High R，另(C−R)>alpha*ATR13[t−2]。初始S_init=S0+a(R−S0)，S0=min前阴Low/信号Low。只改变接受后的容忍函数，原三维在g0严格退化。

最后一次已经ACCEPTED配对L/H冻结；P为自该接受起已完成Close的运行最高（接受当柱P=C）。动态有效线：

S_dyn=L+b(H−L)+g*max(0,P−H)，g∈[0,1]。

q/r、初始结构位置、zA=(C−L)/(H−L)、u=(P−H)/(H−L)、v=(P−C)/(H−L)持续记录不clip。zA<b+g*u等价v>(1−g)*u+1−b：g0容许回吐随新增推进1:1增加，g1容许回吐固定为(1−b)个冻结结构宽度。g不是净利润保护，H及S_dyn仍可能低于真实含费入场成本，不加profit>0门。g1采用数学等价P−(1−b)(H−L)稳定自然端点，b1g1线=P，新高Close=P等号不会自退出；不是隐藏价格round/clamp。g0直接沿原L+b(H−L)计算以保持精确退化。

## 每完成柱的严格顺序

1. 已有due：金融峰、线、pending、配对全部冻结，退出目标0不能反悔；诊断时间计数沿原周期推进。
2. 非due先将旧lastAccepted配对P推进到max(P,C)，算旧配对动态线；必须自然不降低。若Close<该有效线，立即锁存退出，不再让新候选/接受挽回。
3. 仍alive才撤pending：Low<候选L或候选L<=当前有效线即失资格。随后找原strict完整三点pivot，L须>当前有效线；left.BarStart>真实cycle_entry，整entry interval（含OPEN）排除。H只冻结截至left的全持仓最高High，未接受pending不覆盖lastAccepted配对。
4. 有效pending的Close>H才接受；重核L>当时动态线，新pair P=C，新线须自然>旧线且<=C，不用max(previous,new)隐藏降线。三个字段rawS0、实际初始线、accepted L/H/有效线分开，不能把pending H当失效线。
5. 全持仓High峰按C113原顺序最后更新（仅BarStart>entry）；首次触发due的本柱仍保留该High更新时间，之后已due柱不再更新，避免用诊断顺序暗改g0。

所有入场仅真实买入激活，失败proposal不建金融状态；初始线即时有效，没有最短持仓或计时退出。下区间跳低可能在初始线下成交，不新增订单预过滤或模拟立即止损；仅完成柱确认后下一段执行。

support_raised/support_raises保留为accepted事件，不把g随推进的抬线算成新接受；另存dynamic_line_raised/old_effective_line/accepted_base_failure_line/progress_increment。CONFIRMED_HIGHER_SUPPORT_BREAK指最后accepted配对的当前有效失效线，不必等L或H本身破位；base_failure与dynamic_failure_only分列。

## 最小基线、预算和Optuna

[搜索域/锚](search_space.json)：alpha初始[0,1]、a/b/g自然[0,1]；必要alpha扩至2保留12，最后<=8匹配g0/alpha0/a0/b0，max56个本族唯一参数向量。初始36含3个g0基线（原C113、C136、C147），每base另g=.25/.5/.75/1共12锚，剩21 TPE联合4D。n_startup15，首batch三个g0→4+4+4锚后15完成再TPE，不把052那个正常startup随机计数改写/补点。

C163/C164/C165为精确旧源控制，在56 unique之外计实际compute；C166/C167/C168三g0计入36。各先对原公开账户12经济投影、再对g0另12，共72，全部通过才adaptive。只承诺经济路径退化，不隐瞒pending诊断先后差异。旧52未用16不挪入/重置本预算，跨族g0也不是新独立信息。

alpha必要扩边沿>=.95上边界实际前沿/达标贴边或匹配轴严格改善，不因预设上界锚而强开；匹配1.25/1.5、一个2负端点，其余joint上界2不漏1.5—2。原频率逻辑必要至少32闭合，alpha>=2 raw29使所有a/b/g不能联合通过；不伪填未运行点经济值，不声称域外收益无价值。自然a/b/g端点不盲扩，未覆盖如实报告。

唯一Optuna4.9 InMemory Study，seed17、TPESampler n_startup15、multivariateFalse/constant_liarTrue、ask/tell批4，目标ann最大/DD最小，五门无量纲constraints仅引导，逐全部COMPLETE原5门AND保留所有通过点，不加评分、不只best_trials。每点保存502日净值、参数/定义/hash/五门、全采样和选择历史；公开紧凑族与关键完整原账，不预注册巨型网格。公共V4/SRT/TXE/SE同实现，worker4/native1、16unique分段、WorkingSet日志、官方checkpoint/最终显式RESUME，不私清cache/加速账户。source trial间不变，中断显式停止不重seed。

## 不变合同与前检

2024-01-02—2025-12-31训练、2023-11指标暖机261/原prepared缓存，100000新空仓/周期；RTH30分钟可跨夜、全资金0/1只多、每侧.1%费、固定1%买限价、下一段严格执行。502会话6490点443全滚窗，原年化>=247.633956%、DD<=42.810252%且<=25%、中位>=6及90%窗>=3全部保持。2026封存，无新源/平台/生产/阶段四/冻结/merge/tag/push。

真实public BAR_INTERVAL、价格量future suffix；直接覆盖g1/b1新高等号不自退、动态线越pending L撤资格、旧线due先于新候选、blocked due金融冻结、无net-profit门、旧globalHigh首due时序与a/b/alpha原边界。控制sourceSHA按C163=EX05154e864…、C164/165=EX052a406…分别保存，toy旧控制仅C163不夸覆盖；正式三g0全路径守卫。报告四问正文、绩效/全族及反证附录；单家族完成不等于阶段三整体或原目标达成。
