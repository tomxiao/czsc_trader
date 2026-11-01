# EX072：MF冻结保护与原连续参数的有界阶段三优化

## 目标与当前授权

用户2026-11-02明确批准自主阶段三，以原五门同时达标的候选为目标。历史阶段三提案与PROTOTYPES/12原件保留，不回改其当时PENDING状态；当前授权记于本新程序。只使用原LITE2024–25训练、必要2023预热及现有缓存，2026封存，无新来源/依赖/平台/生产或阶段四、SM冻结。

C337在原固定MF_PROTECT下有有限完整优势，但主要集中4次实际退出，净年化192.3364%仍比原门247.6340%少55.2975个百分点。071、070及全部先前负证与已见选择史继续有效，不预设六维联动足以达标或一次有限预算已寻优充分。

## 同一金融实现与六个参数

仅将071固定mode替换为g_when_mf六浮点接口：alpha∈[0,2]；initial_fraction/accepted_fraction/g_when_u/g_when_other/g_when_mf∈[0,1]。所有参数finite float，原E0/尺度/支撑公式不变，只有MF proposal选g_when_mf，其余按原U映射；真实BUY才激活entryMF/runLen/runR/cycle_g并冻结。持仓新U/MF/参数解释不会重路由原周期，原strict postfill、accepted/pending、动态线及due顺序不动。

原helper404c56f4887f74e8d0686e7a9b88385fed20cd405a585d4cf0ddbf938dfbaaaa逐字节保留。无真实负实体左边界明确失败，不以7/9或261假认FULL。零账户全域可得性已在实际6490clock（含2023末观察、2024首执行）核：alpha0 superset505，全部真实终止位于可见261内，最长run9，ATR非负。因delta>alpha·ATR及alpha/ATR非负，合法六维入场是该505的子集；不再把新trial锁成旧209/MF48，也不禁止合法首执行买入。最晚执行截至2025最后窗口，不制造2026决策。

g_mf=0仍保留L+b(H−L)及新accepted升级；g=1是自然端点，不凭完成新高等号自退出。初始a与接受后b/g观察线不tick取整，BUY cap沿原tick规则。真实fill可低于signal runR/支撑，仍不事后过滤；g保护新增价格推进而非保证净盈利。无时间cap、新入口、run长度阈值、shape或时钟搜索。

## 固定预算与真实Optuna顺序

唯一InMemoryStorage Study，Optuna本地4.9.0、seed17、TPESampler(multivariate=True,constant_liar=True,n_startup_trials=5)。每条trial实际suggest全部六FloatDistribution，所有锚/model分布一致；目标仅maximize净年化。sampler只用原四项风险/频率归一化违约，原五项vector/AND另存；tell前实际user_attrs和tell后system_attrs四维都保留，绝不将sampling-feasible称金融达标。

|预定ID|角色／g_mf|金融计算上限|
|---|---|---:|
|C0338|新源中心，与原C337同α/a/b/U路由，g_mf=.75|1|
|C0339|固定轴0，已知等价旧C336，单列非新独立发现|1|
|C0340|固定轴.25|1|
|C0341|固定轴.5|1|
|C0342|固定轴1|1|
|C0343–C0362|20个完整六维联合模型提案|20|

最多25候选含中心控制+最多2共享BH=27实际compute；4workers、每worker/native1，无嵌套，batch最多4。首session至多16候选：中心独立先算，candidate/BH12经济表对C337 PASS后才四轴；五锚全部COMPLETE后才11个model。次session至多9个model；每session共享一个BH。g_mf0轴再对旧C336全12投影，不另算旧账户。

若锚技术失败导致少于5 COMPLETE，不能以startup独立随机补作joint：停止并保留未完成及失败，不免费补点。20个model按固定proposal slot消费预算，重复复用已有真实结果并列明0新compute，不回收ID/不补抽；失败如实FAIL，也不免费替换。未知中断存原trial/源/参数/检查点及状态，禁止静默重建seed17新Study。预定编号不是提前SM注册，不注册未达标试点。

## 原验收、证据与诊断

Fresh100000、0/1全资金只多、原每侧.001成本、固定1%tick限价、nextinterval执行和同窗BH不变。原收益≥1.5正BH（247.633956%）、DD≤.8BH且≤25%、60session实际closed中位≥6且至少90%窗≥3，最终原五AND独立逐项筛全部实际COMPLETE unique点，不能只取best_trials或按过门数选采用。

所有成功点每batch当场公共发布完整V4，all_accounts.json保留原actor/request/result/source/input身份；compact同时保留6490 bar equity、502日末、真实closed exit_at/净额与终值/fee/openMark、全定义/六参数/原五门及实际Study状态。两次benchmark计算和已知经济等价点分别计账，不当独立证据。selected只从既有public refs认证所有joint、最高收益、其余四门过池最高收益、中心/必要g_mf0和1端点及首模型；不读私有cache或用RESUME/evaluate兜底重算。

按默认252session、21session步长事前固定12个重叠片（start0,21,…231），以原曲线窗前equity（首片100000）及继承持仓为基点，同窗BH比较净收益/BAR_CLOSE DD/excess和连续落后，仅诊断不加硬门或重跑。60日频率仍全部443逐日完整窗口，不降采样。年度、费用、闭合与期末未平估值分开；未来stage4须另获批准。

alpha上界附近事前定>=1.9，保留所有sampled边界及前沿/达标触发。不得越已批域/27预算自行扩；alpha>=2的原入场数≤29，而原双频门要求至少32closed，外域joint不可行是旧门必要界，不是新过滤器。自然分数端点不盲扩；有限域内尚未覆盖的边界/组合及未执行扩边原因如实写，不把预算用完说成全域验证。

## 预检与收口

同一strategy/common用于正式搜索及候选验证，不造私有加速器。真实合成前检覆盖原C337中心经济退化、MF轴/自然端点、run真实边界/doji/跨日/未来前缀、actual fill<R/failedBUY/blockedSELL、proposal继承与冻结g、旧holdingcore。Optuna API toy只检5固定点→20完整6D joint、同分布、0independent fallback及4system约束，不把人工toy目标当金融结果。

全部数值达标者最终登记并验证可加载，提交CANDIDATES；0达标也真实空交付，未达标前沿只作研究证据。root负责公共intent、最终交付执行及本地中文提交，本writer不改family/HANDOFF，不自动阶段四/测试/冻结/合并/tag/push。
