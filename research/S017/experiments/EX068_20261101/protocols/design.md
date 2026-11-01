# EX068：跨夜收复持仓的当日失效参考

## 尝试什么

EX067零账户拆解显示C222已经捕获多数隔夜重估，直接补空仓入口缺乏支持。新问题是：尚未得到结构接受确认的真实跨夜仓位，在开盘价格发现结束后，首柱Low能否提供当日风险失效信息？首柱区间后来被收盘跌破可能意味着当日价格接受失败；也可能只是正常回调，过早退出会损失后续日内及隔夜收益、增加重复入场费用。量价/新闻主体不据此识别。

固定C222的E0入口、alpha=.3435458360048906、a=.42823406094793653、b=.1569056351519751及U时g=.75/非U时g=0。初始及accepted支撑、候选L/H、strict排整个entry区间、下一段执行、0/1全资金和成本均不变。无新增入口、盈利资格、timer、阈值或参数搜索。

|候选|首柱Low附加失败职责|
|---|---|
|C0332 DISABLED|关闭，必要新源精确C222控制|
|C0333 INITIAL_ONLY|仅当前决策开始accepted_active=False的真实跨夜仓位|
|C0334 ALL_HELD|所有阶段的真实跨夜仓位|

39次initial failure和55次accepted属于旧路径事后分类，不是新策略白名单。所有accepted仓此前也经历initial；本组按当前可见状态判scope，不切掉旧亏损后保留旧赢家。

## 精确状态与顺序

1. 仅真实held且state.cycle与public portfolio.cycle_entry匹配时形成日参考。用公开history.tail27按最新已完成柱BarStart的NY日提取首RTH柱；首柱必须09:30开始、30分钟完成、当日可见prefix完整且连续。可见执行会话声明session_context=True，同日按公开TradingSession首段核对；观察前日末柱/执行次日首段时继续原观察日，不借ctx.session换参考。不私读calendar/cache/其他账户。
2. carryin严格为真实cycle_entry<该观察日firstBarStart；当天首段及以后新买都不属于carryin。首柱完成前没有当日Low；首柱完成后冻结该日Low/at/观察日，直到新的观察日首柱完成才更新，始终属于自己的真实cycle。新BUY proposal初值为空，失败BUY不激活；日内新BUY不继承旧cycle参考。
3. 每决策开始保存accepted_active作为scope；若原已due，保持旧原因及金融状态，日锚也不重写。否则先更新原accepted动态support并判断旧support失败；原due优先，原因不被附加guard覆盖。
4. 原尚未due时，scope成立且carryin且当前完成Date>首柱Date，Close严格小于当日冻结firstLow才新增OVERNIGHT_OPENING_LOW_BREAK，锁存到真实清仓。Close==Low持有；首柱本身Close>=其Low且Date等于参考at，因此不能触发。正常最早第二柱完成10:30判断、10:30–11:00执行段Open卖；不是10:00卖，不规避已发生gap/首30分钟损失。
5. 新due发生后阻止本根pending/pivot新接受；未due才继续原候选撤销、strict三柱pivot、同右接受及原High峰更新时序。本决策初始未accepted即使本根原本可能新接受，也不能豁免已成立的附加失败。
6. 日Low guard仅附加OR退出，不降低/替换原support。新日参考可能低于旧日，是每日信息重锚而非全cycle单向trail；有效旧support仍只升。已有due永远不反悔。提前退出会影响后续E0成员、资本占用、隔夜暴露，不能承诺保留以后所有gap收益或将差额归同笔纯退出因果。

## 依据、反证与停止

EX011/017曾将入场当日openingLow及openingRange用于日内策略且末段强平，不是现C222跨夜仓每天的可见风险参考。EX037/063是首柱gap后的入场条件，不是已有仓位退出。EX054宽E1及EX066恢复已负面，不能借本组重开补flat路线。EX052–059连续退出族均未解决原收益门，新的会话参考同样可能只是更早止损而丢掉正常恢复；原五门全部保留。

先在现有C222公开94周期/6490事实路径做仅触发可行性核：只读时间/报价/真实持仓/accepted/due，不读取新分组PnL或延续标签。计数不是收益证据，也不是C333/C334运行事件总数。若INITIAL_ONLY候选触发为0，根在正式前取消该经济重复臂，不凑账户。其余正式路径只用自身周期生成信息。

正式最多3candidate+1共享BH=4compute，根核最终source/precheck后才运行。C0332与原C222的candidate及BH六经济表各自全投影共12张PASS才解释经济结果；失败/不匹配实记停止。阶段二退出风险职责比较，E0已有多期普查，无新入口/新标签，不需重新择期限。2024–25训练、必要2023预热、原执行/成本/五门不变；2026封存，无新源/平台/阶段三四。报告四问正文、全三格关键数值及年度/closed-open/费用/完整取舍附录，不把0joint自动等同机制无用。
