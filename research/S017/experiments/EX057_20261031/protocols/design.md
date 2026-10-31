# 已冻结入场背景保护：有界五维联合优化

## 尝试什么、为何继续

EX056反向映射C222在同原入口下提高完整收益，保持其余四个原门，但收益仍未达标。此前alpha/a/b来自静态g的C179，不必是两背景协作下同样合适的职责。本组在已经形成的金融模型内联合比较可执行收复余量、初始结构失效、接受后失效位置与两背景推进回吐容忍；不新增指标、背景类别或均价窗口，不因可增加常数就扩模型。

金融实现逐字复制EX056 strategy.py，raw SHA a932d2e28b47c24ec3609c6b2c252bf6fdd69803c4bed9dee5ce611670d16629，定义级equity_source_hash为6269f767e96e74051487c9999a25c2b7dd25265d95b44565e2b45e6a3973ea0e。本组无新金融源码，不能把原byte级自检称作新增独立验证。

## 收益、持有与失效

前阴后Close−R>alpha·ATR13[t−2]参与R以上的后续延续；R为前High，S0=min(前Low,当前Low)。初始线S0+a(R−S0)。候选更高Low L须收盘再过冻结此前推进高点H才获接受，旧有效线先失效/锁存退出；整entry区间排除，未接受候选不修改最后accepted配对。

接受后有效线L+b(H−L)+cycle_g·max(0,P−H)，P只用接受后完成Close峰。g保护新增推进，不是本周期净利润。前柱U严格为Close[t−1]>SMA65[t−1]>SMA260[t−1]；仅实际买入激活的cycle冻结entry_u及cycle_g，当前均价翻转不改g，非U不等于熊市，两均价排列不等于斜率向上。买失败不激活、due不反悔。全部具体动作、强类型state与原时序未变，无时间退出/盈利资格/rho门。

## 参数、预算与真实Study

参数域alpha∈[0,2]，a/b/g_when_u/g_when_other∈[0,1]。后四个是自然锚区间，不向域外盲扩。alpha≥2只有29原始可入场信号，原双频率联合要求至少32闭合，因此域外不可能全部达标；这是原目标必要界，不是新增硬门，也不宣称域外收益没有意义。

唯一InMemoryStorage Study，Optuna4.9.0 TPESampler seed17、n_startup_trials16、constant_liar=True、multivariate=False，最大年化/最小BAR_CLOSE DD两objective。原五门归一化约束符号只引导采样，不加权评分、不按门数采用。当前协议把4原点固定enqueue/ask/tell为历史COMPLETE，引入已认证原结果，0新compute；公开attrs保留原experiment/CID/EvidenceRef/actor identity。相同函数不能被当作四次新观察。

4 warm为056 C219/C220/C221/C222；认证EvidenceRef和三依赖、完整定义语义（含source、feature graph、state schema、参数、warmup、Spec）、content identity及主input SHA 2d2a98bfe9f04891e47cb6c938d0eb1b27bb28f41622f73aef010ae23d6d717c。不只比较analysis里的运行脚本hash，不新算旧点技术控制。

40次新初始提案目标40 unique：12事前g锚，alpha/a/b固定C179；(gu,gn)依次为(.25,0)、(.5,0)、(1,0)、(.75,.25)、(.75,.5)、(.75,1)、(0,.25)、(0,.5)、(0,1)、(.25,.75)、(.5,.75)、(1,.75)，都不与4 warm撞点。之后28次联合五维模型TPE；4 warm+12锚全部完成16后才第一模型批，不发生startup随机数量含混。

重复提案保留Study记录并引用既有已认证值，不重新计算、不默默补问突破预算；若意外重复导致初始unique少于40，明确列覆盖短缺，不宣称精确40新经济点。实际失败/未知计启动，FAIL/中断保留，不免费重试或静默重建seed17。

初始后最多6项匹配：在全部COMPLETE且其余四个原门全部通过的集合中按年化最大选代表，同收益按CID字典序，不加入目标内DD偏好。有joint时该最大收益代表自然joint，但所有joint独立完整保留，不能只保留代表或Study.best_trials。没有该集合则跳过并写原因，不用评分兜底。

冻结代表alpha/a/b，匹配静态g=0/.75/1/代表gu/代表gn，以及交换gu/gn。先与warm、初始和彼此去重；既有点引用原结果，不计新unique，不为用满预算补random。最多46新候选compute，4 warm+至多46=至多50 Study记录，另最多3共享BH，实际compute上限49。

## 执行与证据

单主Study、公开V4账户/SE、workers4/native1/batch4。session按16、16、最后8初始+至多6matched分段，第三session保持到匹配完成，单session最多16新unique、全组最多3BH。保留每批WorkingSet、checkpoint身份与全部成功/失败/重复，不私清平台缓存。中断显式停下并待审恢复，不自动另开Study。没有私有快账户。

复用056已认证同源合成及真实BAR_INTERVAL/冻结背景/未来后缀自检，不重跑同源旧账户。准备期只认证历史源与输入、公共Optuna API/锚唯一性，不计新经济试验。所有正式新trial使用同一strategy字节、参数仅在definition JSON，不改可变配置以冒称同源。

紧凑全trial公共材料保留完整参数、源/定义/request/result/SEcheckpoint身份、原5门与约束、502日末净值、6490 BAR_CLOSE equity数组、CLOSED真实exit_at序列、期末现金/仓位/费用/closed-open；共同时间与session index单列。可独立重算CAGR、DD及443真实频窗。全部joint和必要frontier/匹配完整V4原账用公开checkpoint RESUME留存，原result hash核对且不得重算为新样本。不为每个试点公开巨型解释账本，旧选择史全部承接。

## 决定与边界

形成完整原五门达标集合才可能作为后继候选；0joint也完整交付负证与非达标前沿，不能空集伪成功。有限预算不是全域最优证明，贴自然边界的取舍与未覆盖风险照实报告，不以预算耗尽当达标。没有自动阶段四/封存样本/生产。

2024—2025训练、必要2023指标暖机、2026封存。100000新空仓、0/1全资金只多、每侧.1%费、固定1%限价和原tick/严格Low/下一段执行，原收益/双DD/双频率均不变。旧报告与模型不改。目标缺口、年度集中和正常回踩/重复进出/跳价仍是强反证，不预设C222改善可推广。
