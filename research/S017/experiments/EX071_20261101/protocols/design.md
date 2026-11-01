# EX071：多阴整串收复后的固定推进保护职责

## 为什么比较这项职责

EX070多阴整串已收复的MF群，在去重26/65/130相对普通机会的两年差均为正，但13较弱、主族内支持只有raw9/47和thin7/23，MP也不是普遍差。线索只支持一次有限完整用途比较，不证明MF独立预测因子或长档收益能兑现。持有解释是整段价区恢复后，已接受L/H结构尚存时是否值得容忍正常回调，与更早保护H以上新增完成价格推进相竞争。

保留全部原209E0、alpha=.3435458360048906、a=.42823406094793653、b=.1569056351519751、初始及accepted原支撑、执行/费用与资金合同。不存在FULL/MF入场过滤、新入场时点、timecap、插值或参数搜索。

|配置|仅MF入场proposal的g选择|SINGLE／MP|
|---|---|---|
|C0335 KEEP|原U时.75／非U0，精确新源控制|原U映射|
|C0336 MF_STRUCTURE|强制g0|原U映射|
|C0337 MF_PROTECT|强制g.75|原U映射|

g0仍是L+b(H−L)基础失效，不是只L或不控风险。g.75保护已接受H以上的新增完成价格推进，不保证真实周期含费盈利。原U为proposal当时前Close>前MA65>前MA260，strict排列不是均线斜率。056及057—059只按U全局选择/调gu和gn，没有按本次整串收复区分相同U内的entry context；本次是新的上下文×风险职责问题，原负证及选择史不清零。

## 精确可见状态

仅raw E0为真时读取public history.to_frame(tail=261)，从t−1跨session连续Close<Open向前直到真实Close>=Open；R为负实体串最大High，不含当前或终止柱。若261可见观察内缺真实边界，明确ValueError，不假用261边界、不fallback、不用实际max7设窗口参数。原261预热保证已完成可见图，当前70全时钟实际max7/censor0只作可执行性证据。

MF=runLen>=2且signalClose>R；等号为MP。每个当前raw E0的currentMF可解释，但entryMF、entryRunLen、entryRunHigh与选定cycle_g只进入当根BUY proposal，实际BUY才激活并冻结。失败BUY不创建/留上下文，新signal重算；持仓后新currentMF、U或新日都不改变自己的entryMF和cycle_g。原初始收复价位仍是prevHigh，a仍作用于原S0→prevHigh；新增runR不替换初始结构价位。

真实nextinterval BUY可能跌回runR下，仍保留原signal MF和g，不事后拒绝、重分组或假按R成交。既有strict BarStart>cycle_entry排整个entry interval、原accepted/pending分离、峰/动态线顺序、旧due锁存、下一段Open卖等全部原holding core不变；不读旧48日期或原baseline交易名单作新运行事实。

## 事前非惰性、预检与预算

0收益计数按原市场raw、原flat proposal、原实际BUY三种分母列MF×U及所选g相对原映射改变数。MF_STRUCTURE仅改变MF&Utrue，MF_PROTECT仅改变MF&Ufalse；如果原所有实际BUY的g没有变化，根取消该惰性账户，不以新样本门凑计算。计数不是新策略交易总数或收益依据；新策略资金路径独立重算，两个新臂也不必是相同成交成员。

全6490原时钟MF集合须与070公锁48精确同刻；真实前检覆盖run/doji/跨日/leftcensor/strict等号及未来前缀、proposal实际继承/失败BUY不激活、真实fill<runR保留、held currentMF/U翻转不改g、strict entry及due保持和KEEP完整经济退化。阶段二风险职责比较无需新的入场标签，复用E0和070普查，不用130设退出。

根核最终source/precheck后最多3candidate+1同session共享BH=4compute；先C0335与原C222 candidate/BH全12经济表PASS，再同session两新臂。原五门AND、2024–25训练、必要2023预热、2026sealed、100000新现金、0/1只多、.001单边费/1%tick限价/下一段执行均不变。金融失败或control不匹配实记停止解释。

两新没有新增完整价值就停止本context-g全部细调，不扫run长、阈值、中间g或其他映射，不增金融家族。全部三格及年度/fees/closed-open/原五门代价完整报告，0joint不被低DD或分组盈利抵消；这也是本轮最后金融比较，后继阶段/完整用途仍由根按证据决定。
