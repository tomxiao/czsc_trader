# EX052 阶段三：连续收复状态与金融失效职责

Status: PREDECLARED。用户已明确批准进入阶段三改造及参数优化；原36+12已WITHDRAWN，不复活。以PROTOTYPES10的C113为精确退化基线。

## 收益期待、持有与失败

旧M006前阴High已被当前完成Close收复，买后赚之后继续上行。初始结构原低点S0与被收复价位R是两种失败解释；回调Low L被收盘重新超过此前推进High H接受后，深低点L与最后一次已接受H又是两种失败解释。本轮把这些位置变成连续状态/决策函数，不引入固定持仓时间、重新晋升时点、MA、仓位比例或新数据。

R=High[t-1]，S0=min(Low[t-1],Low[t])。M006固定prevClose<prevOpen且Close>R，严格不等号。σ=既有ATR13[t-2]（13个已完成TR简单均值，固定尺度不搜索）。入场只加(Close−R)>alpha*σ；alpha=0精确退化M006。q=(Close−R)/σ描述收复余量，setup_risk=(Close−S0)/σ是当前潜在setup参考风险，不能称实际成交成本或本周期初始风险；真实proposal另冻结entry_scale、signal_reference_close、rawS0/R，held时据此解释entry_signal_risk。σ=0用乘法原式，严格正收复仍通过，不加epsilon或波动兜底，归一化指标标为未定义，不除零。q不是Close−Open，也不证明主动买盘。

信号真实买入激活cycle后S_init=S0+a(R−S0)，a=0原低点、a=1收复价位。初始z0=(Close−S0)/(R−S0)，不clip；Close<S_init为初始失败，等号持有。rawS0与initial_support（实际S_init）分开，a>0第一次退出仍记INITIAL，不误记升级。

支撑候选、峰与完整排entry区间全部沿C113：strict三点L须>当前生效S，left.BarStart>cycle_entry；P只current.BarStart>cycle_entry才更新。候选H冻结截至left真实可用最高High，Low<L先撤，不用高小pivot替换，右柱Close>H可同柱接受。接受后S=L+b(H−L)，b=0深低点、b=1已接受H。因L>旧S且0<=b<=1，S天然严格升，不用隐藏max或允许降线。H/L只在真实candidate_accepted时冻结为lastAccepted配对，新的未接受pending/撤销不能覆盖。

接受后zA=(Close−L)/(H−L)是剩余推进位置，zA<b等价当前失效。以最后已接受配对记录推进u=(running_max_completed_Close−H)/(H−L)与回吐v=(running_max_completed_Close−Close)/(H−L)，不clip，不把观测峰当可实现卖价。只用于状态解释/失效函数等价表达，不新增优化参数。已有due锁存直到实际清仓，之后不能再candidate/峰操作；不承诺线价成交。

a/b会改变当前生效S及随后候选人口，因此是完整策略协作，不声称固定同交易纯退出因果。入场尚未成交不激活结构/风险/峰；S_init即时有效，排entry结构素材不构成最短持有时间。

## 域、预算、结构与参数贡献

精确[搜索空间](search_space.json)。三维参数alpha初始[0,1]、a/b各[0,1]；alpha下界0和a/b两端为自然金融边界，不向负或越1盲扩。alpha上界是暂定探索边界，固定金融source只校验finite alpha>=0，实际当前研究由冻结study上界限制。

initial40唯一参数点含12预定Optuna enqueue锚：alpha0下a/b∈{0,.5,1}的9点（含000），及alpha=.25/.5/1且a=b0的3点，余28由TPE联合提议。000=C0115计入40，旧原源C113 exact技术控制C0114额外不占unique，但计实际compute。固定轴/角显示结构职责，联合最优相对它们显示参数协作；末段最多8个新unique做最终代表的alpha0/a0/b0及a=b0匹配删项，不重新优化删项比较。

必要扩边预留16：alpha上边界点或接近边界的收益/DD前沿/达标点、或同a/b的强度轴继续改善，必须真实评价alpha1.5/2的匹配边界点，再用剩余额度补联合域；不因当前0—1未达标随意加维度。若2仍有改善且余量不足，如实报告边界覆盖未完成，不称充分验证。此轮总上限64 unique（40+16+<=8）；重复参数用已认证结果回填Study，不再耗独立compute，全部duplicate/失败/取消/未知状态留记录。

## 正式计算、Optuna与内存

Optuna4.9.0主进程唯一InMemoryStorage Study；seed17，TPESampler n_startup12、multivariate=False、constant_liar=True，明确采用独立密度模式以支持alpha域数值扩展，不发生隐式多变量动态域fallback；每trial仍是完整3维联合策略。公开ask/suggest_float/tell/enqueue、双目标return最大/DD最小。真实toy API测试（无市场账户）确认约束、数值扩域和状态处理。

约束向量为原五门各除以固定门尺度：1−ann/return_target，DD/relative_limit−1，DD/.25−1，1−median/6，1−coverage/.9。归一化仅为采样引导，最终逐COMPLETE trial用原五门原数值AND，保留所有达标配置，不只study.best_trials；无加权综合分/过几门评分。全不达标保留明确标注的非达标收益/DD前沿，不对空best_trials伪成功。达标区间内不增加偏好或自动冻结。

同一冻结strategy.py与参数JSON贯穿全部trial/复核；无快账户或私有加速。TDR公共ResearchExecutionSession、prepare/evaluate_many、SRT/TXE/SE；workers4、native_threads1，ask/tell批4固定顺序回填。一个public session最多16 unique，保留Study跨session，每段CREATE官方checkpoint，最终代表按原段显式RESUME认证/发布，不私改缓存。每batch记录主进程WorkingSet/PeakWorkingSet；实测解释约6.8KB/决策，估44MB级candidate，SE另持canonical ledger，16点分段限制保留量。新段额外BH计算、控制、恢复认证、真实compute分别统计，不当独立样本。

所有trial的状态/参数/定义与请求/账户hash、全指标/年度/费用/五门、域/边界/采样种子/版本、真实来源和选择历史以紧凑材料公开；关键零点/结构锚/最终代表公开完整原账户，不预注册参数网格或给全部点逐个公开巨型全账。全原结果保留官方.tmp checkpoint，持久科学依据包括公开完整trial表/关键原账户/源和证据hash，非只临时缓存。

## 原合同、前检与停止

2024-01-02—2025-12-31训练、2023-11指标暖机261、现EX042 main-only prepared；2026-01-02—09-30封存，无新源/下载/平台/生产/阶段四/冻结/merge/tag/push。全新100000空仓/零cycle，30分钟RTH可跨夜、全资金0或1只多、单侧.1%费/固定1%买限价/下一段严格执行不变。原年化>=正买持1.5（247.633956%）、DD<=买持.8（42.810252%）且<=25%、60日闭合中位>=6且>=90%窗至少3同时验；502会话6490点443全滚窗，末仓保留估值不读测试退出。

正式前public synthetic强制真实BAR_INTERVAL及整entry排除，alpha等号/σ0、a/b端点中点、真实初始/accepted/pending字段、候选人口协作/单向线/due锁存、价格量future suffix、解释体积。然后首先用Optuna真实trial000全训练与旧C113 exact源控制比较候选/买持六表12项完整经济路径（可再对原C113证据认证）；失败停止不启动adaptive，绝不只比最终绩效。早期无收益标签尺度诊断脚本/结果经SHA认证后pre_run公开，旧7年负证/重复训练选择史保留。

停止条件：原预算完成、必要扩边完成或明确未覆盖、匹配删项完成、或清晰公共接口/计算契约阻断；技术异常明确状态不自动重试/降级。目标达标与否分别报告，未达不改原门。当前授权不含阶段四/封存测试或生产。


### 原频率门的逻辑必要界与留证补充

443窗的中位>=6要求至少222窗>=6，覆盖>=90%要求至少399窗>=3，因此全窗闭合计数和至少1863；一笔最多贡献60窗，至少32闭合才有可能联合达标。因果原式alpha0/.25/.5/1/1.5/2分别505/258/145/69/47/29个raw收复信号，closed<=buy<=raw，alpha>=2在本训练任何a/b不可能联合达标。这是原门的数学推论，不是新筛选gate；alpha2只负面边界，不能伪填未运行点收益，也不说域外收益无价值。扩边以匹配1.25/1.5为主、一个2端点，余联合提议上界2，不能用alpha2不可达推断(1.5,2)也不可达；无需因2收益/DD改善再密集搜>2来找联合通过。

‘接近上界’量化为alpha>=.95*初始上界1。单纯预设alpha1锚不触发，须实际收益/DD前沿、达标贴边，或同a/b轴边界严格Pareto改善（至少一项严格）触发。自然a/b端点不扩。

每个unique结果另保留502日同口径净值/日期，支持后续研究族选择审视；不只年度摘要或.tmp缓存。Optuna中断保存完成/未知状态并明确停止，不自动重建seed17 Study。a>0后下一买区间仍可能跳到新支撑以下照原限价成交，等待下一完成决策才退出，不另加买单预过滤或假设立即线价止损。
