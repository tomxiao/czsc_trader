# S013：互补买入确认与费用归因

身份为RSCH，继续已批准的阶段三。沿用研究分支、S013原开发池与原四项验收条件；全部固定冷却日为零。没有进入阶段四、冻结、生产、合并或推送。S007-v1仅作为“基础机会 AND 确认分达门才买入”的表达来源，沿用上一修订已核验的定义，不读取其研究数据或结果。

完成42个去重配置的TDR FULL完整账户评价，其中2个关闭新增确认的原策略对照精确复现C2308/C2132；价格幅度0档控制精确复现C3107。新增达标技术身份14个；相同实际经济路径按独立材料分组，不能把身份数当独立发现次数。所有达标新身份交接，3个等价控制仅作证据，不重复登记。

新达标配置最高净年化为C3107：12.7130%、110笔闭合交易、2022/2023最小净收益3.6875%。C2308对照为12.3144%、111笔、最小净收益3.6891%。收益提高与盈利余量增厚必须分别判断。

新增达标配置中最小负基准年净收益最大的是C3100：3.6891%。相对各自原策略同时通过四门且增厚此余量的身份：无。

## 研究问题、原约定与已见信息

原成交归因已核验6个上轮代表配置、每侧10/20/30bp共18个真实账户。C2308共111笔闭合交易中，57笔毛收益不超过40bp，45笔毛收益非正；2023年5笔bull入场且regime退出的交易平均毛收益约-0.8121%、平均持有2.2个交易日。它们提示短持仓价格收益不足，不能直接证明某个过滤条件具有因果预测力。

开发池为510500.SH，2020-01-02至2026-09-30，共1636个交易日，使用既有预热。初始现金100万元；100个HFQ研究单位一手；2019-12-31复权因子锚0.2803；逐日price_scale映射原价0.001跳动；T日收盘已知信息、T+1限价买/市价卖，只做多、不加杠杆，每侧10bp，同口径可执行NextOpenBuyHold(100)。信号HFQ价格与锚定研究执行价格量纲不同，经济归因使用实际fill价格及数量，不用信号Close直接代替成交价。

四门不变：净年化≥1.5×同口径买持基准；每个自然年最大回撤严格小于基准；闭合笔数×60/1636≥4（至少110笔）；2022/2023负基准年实际净收益严格为正。年度权益连续，上年末权益为当年锚，2026截至9月底。费用压力、盈利余量、集中度、邻域、样本量均为诊断，不新增资格门。

完整开发池已在此前反复使用。初始计划在评价前发布；边界计划基于已见初始结果追加并在新评价前发布，选择偏差明确存在，没有独立封存验证。Optuna固定队列、主进程研究、4个FULL子进程、每进程原生线程1、请求workers1、种子13。没有外部获取或新增依赖。

## 确认分职责和对照

保留C2308的状态重入成交额门：最近一次信号退出原因为regime时，成交额分≥-0.175才允许重入。额外门只用于声明路线的买入机会，使用已有20日收益一期自相关、成交额/过去20日均值、过去20日log成交量变化均值，每项完整120日当前分位居中。等块组合为0.5×自相关分+0.25×成交额分+0.25×成交量分，价格状态与量能各占一半；acf_volume两项固定等权。分数[-0.5,0.5]不表示盈利概率。

新增门和原门按AND联合。“普通入场”包括首次入场、上次信号退出非regime的机会；regime上下文在拒绝的空仓期间持续，到信号entry才清空。这是内部信号状态，不是实际成交退出记忆。所有入场模式也对regime重入施加新增门。弱分在持仓期间不触发退出；原退出优先级和活动路线锁定保持，只有计划明确列出的持有期对照改变max_hold。

初始22组包含两原策略控制、6个原始自相关硬门、8个组合分应用范围/阈值对照、2个单项分以及4个持有期与评分组合。随后16组检验all分-0.45至-0.25的邻域、acf_volume宽松边界及2个独立持有期对照。根据这38组的实际归因，再追加4组价格幅度买入确认；每组实际执行前发布协议，不存在冷却天数等待条件。

## 全部配置与原四门

|身份|母体|净年化|闭合笔数|2022净收益|2023净收益|四门|研究配置|
|---|---|---:|---:|---:|---:|---|---|
|C3100|C2308|12.3144%|111|5.7848%|3.6891%|通过|all-bull--0.45-all_entries-boundary|
|C3101|C2308|12.3144%|111|5.7848%|3.6891%|通过|all-bull--0.45-ordinary_entries-boundary|
|C3102|C2308|12.4373%|111|5.7848%|3.6891%|通过|all-bull--0.4-all_entries-boundary|
|C3103|C2308|12.4373%|111|5.7848%|3.6891%|通过|all-bull--0.4-ordinary_entries-boundary|
|C3104|C2308|12.5604%|111|5.7808%|3.6889%|通过|all-bull--0.35-all_entries-boundary|
|C3105|C2308|12.5890%|111|5.7831%|3.6875%|通过|all-bull--0.35-ordinary_entries-boundary|
|C3106|C2308|12.6842%|110|5.7808%|3.6889%|通过|all-bull--0.325-all_entries-boundary|
|C3107|C2308|12.7130%|110|5.7831%|3.6875%|通过|all-bull--0.325-ordinary_entries-boundary|
|C3108|C2308|11.8211%|110|0.6360%|3.6897%|通过|all-bull--0.275-all_entries-boundary|
|C3109|C2308|12.7130%|110|5.7831%|3.6875%|通过|all-bull--0.275-ordinary_entries-boundary|
|C3110|C2308|12.1538%|109|0.5967%|3.6896%|未通过：frequency|all-bull--0.25-all_entries-boundary|
|C3111|C2308|12.1808%|109|0.5951%|3.6902%|未通过：frequency|all-bull--0.25-ordinary_entries-boundary|
|C3112|C2308|12.4373%|111|5.7848%|3.6891%|通过|acf-volume-bull--0.4-ordinary-boundary|
|C3113|C2308|10.9720%|111|0.4004%|3.6900%|通过|acf-volume-bull--0.35-ordinary-boundary|
|C3114|C2308|10.5829%|113|-1.6432%|2.9362%|未通过：return、negative_buyhold_year_profit|isolated-bull-max-hold-7-without-extra-score|
|C3115|C2308|8.5543%|120|-5.8555%|2.0235%|未通过：return、negative_buyhold_year_profit|isolated-bear-max-hold-3-without-extra-score|
|C3000|C2308|12.3144%|111|5.7848%|3.6891%|通过|C2308-all--0.2-ordinary_entries-disabled|
|C3001|C2132|16.1572%|112|12.1687%|0.2841%|通过|C2132-all--0.2-ordinary_entries-disabled|
|C3002|C2308|10.5420%|83|0.6822%|3.9832%|未通过：return、frequency|C2308-all--0.2-ordinary_entries-enabled-bull-raw-acf-0.0|
|C3003|C2308|5.8590%|78|-1.5945%|6.0730%|未通过：return、frequency、negative_buyhold_year_profit|C2308-all--0.2-ordinary_entries-enabled-bull-raw-acf-0.05|
|C3004|C2308|6.0973%|74|1.2889%|7.0493%|未通过：return、frequency|C2308-all--0.2-ordinary_entries-enabled-bull-raw-acf-0.1|
|C3005|C2132|13.5519%|83|10.2463%|0.9811%|未通过：frequency|C2132-all--0.2-ordinary_entries-enabled-bull-raw-acf-0.0|
|C3006|C2132|8.9110%|77|7.7884%|4.0174%|未通过：return、frequency|C2132-all--0.2-ordinary_entries-enabled-bull-raw-acf-0.05|
|C3007|C2132|7.8395%|72|3.1536%|4.9750%|未通过：return、frequency|C2132-all--0.2-ordinary_entries-enabled-bull-raw-acf-0.1|
|C3008|C2308|12.6842%|110|5.7808%|3.6889%|通过|C2308-all--0.3-all_entries-enabled|
|C3009|C2308|12.7130%|110|5.7831%|3.6875%|通过|C2308-all--0.3-ordinary_entries-enabled|
|C3010|C2308|12.5202%|107|1.8715%|3.6888%|未通过：frequency|C2308-all--0.2-all_entries-enabled|
|C3011|C2308|12.5511%|108|1.8734%|3.6915%|未通过：frequency|C2308-all--0.2-ordinary_entries-enabled|
|C3012|C2308|11.3788%|108|0.5957%|2.3718%|未通过：frequency|C2308-acf_volume--0.3-all_entries-enabled|
|C3013|C2308|11.6286%|109|0.5996%|3.6898%|未通过：frequency|C2308-acf_volume--0.3-ordinary_entries-enabled|
|C3014|C2308|12.6766%|104|0.5980%|1.8648%|未通过：frequency|C2308-acf_volume--0.2-all_entries-enabled|
|C3015|C2308|12.3275%|108|0.5983%|3.6890%|未通过：frequency|C2308-acf_volume--0.2-ordinary_entries-enabled|
|C3016|C2308|12.1494%|106|3.4090%|4.5743%|未通过：frequency|C2308-acf--0.2-ordinary_entries-enabled|
|C3017|C2308|11.9260%|107|1.8750%|5.7736%|未通过：frequency|C2308-volume--0.2-ordinary_entries-enabled|
|C3018|C2308|9.8629%|109|-4.4117%|2.9359%|未通过：return、frequency、negative_buyhold_year_profit|C2308-all--0.2-all_entries-enabled-hold-('bull', 7)|
|C3019|C2308|9.8921%|110|-4.4096%|2.9363%|未通过：return、negative_buyhold_year_profit|C2308-all--0.2-ordinary_entries-enabled-hold-('bull', 7)|
|C3020|C2308|10.2577%|117|0.9625%|2.0237%|未通过：return|C2308-all--0.2-all_entries-enabled-hold-('bear', 3)|
|C3021|C2308|10.2853%|118|0.9635%|2.0235%|未通过：return|C2308-all--0.2-ordinary_entries-enabled-hold-('bear', 3)|
|C3200|C2308|12.7130%|110|5.7831%|3.6875%|通过|C3107-bull-all-entries-price-margin-0|
|C3201|C2308|12.5186%|104|0.5611%|6.6021%|未通过：frequency|C3107-bull-all-entries-price-margin-0.0025|
|C3202|C2308|12.3745%|104|0.5611%|6.6021%|未通过：frequency|C3107-bull-all-entries-price-margin-0.005|
|C3203|C2308|12.3037%|100|1.3038%|7.5609%|未通过：frequency|C3107-bull-all-entries-price-margin-0.01|

## 价格收益与真实费用

每个成功账户逐日复算数量、现金、持仓价格变化、成交相对收盘收益和真实费用；年度价格与费用贡献均除以各自当年期初权益。尾仓按最终实际收盘标记，闭合与尾仓收益之和核对完整期末权益。交易按入场/退出年份和路线分组仅作描述，跨年周期不得替代连续自然年账户收益。

|身份|年份|价格贡献|费用贡献|净收益|
|---|---|---:|---:|---:|
|C3000|2022|10.5357%|4.7509%|5.7848%|
|C3000|2023|7.4408%|3.7518%|3.6891%|
|C3001|2022|17.9489%|5.7802%|12.1687%|
|C3001|2023|4.5466%|4.2625%|0.2841%|
|C3107|2022|10.5341%|4.7510%|5.7831%|
|C3107|2023|7.4393%|3.7518%|3.6875%|
|C3100|2022|10.5357%|4.7509%|5.7848%|
|C3100|2023|7.4408%|3.7518%|3.6891%|
|C3006|2022|10.7745%|2.9861%|7.7884%|
|C3006|2023|7.1129%|3.0956%|4.0174%|
|C3019|2022|0.1120%|4.5216%|-4.4096%|
|C3019|2023|6.6770%|3.7407%|2.9363%|
|C3021|2022|5.7438%|4.7803%|0.9635%|
|C3021|2023|6.0272%|4.0038%|2.0235%|
|C3114|2022|3.1557%|4.7989%|-1.6432%|
|C3114|2023|6.6771%|3.7409%|2.9362%|
|C3115|2022|-1.1360%|4.7195%|-5.8555%|
|C3115|2023|6.0268%|4.0033%|2.0235%|
|C3201|2022|5.0781%|4.5170%|0.5611%|
|C3201|2023|9.9905%|3.3884%|6.6021%|
|C3202|2022|5.0781%|4.5170%|0.5611%|
|C3202|2023|9.9905%|3.3884%|6.6021%|
|C3203|2022|5.6247%|4.3210%|1.3038%|
|C3203|2023|10.7395%|3.1786%|7.5609%|

最高年化新配置2023年的价格贡献从7.4408%变为7.4393%，费用贡献从3.7518%变为3.7518%。这组差异用于解释实际账户取舍，不把被拒绝旧交易的盈利直接相加当新政策收益。


最高年化配置相对C2308的收益变化主要发生在其它年份：

|年份|连续账户净收益变化（百分点）|价格贡献变化（百分点）|费用贡献变化（百分点）|
|---|---:|---:|---:|
|2020|-2.27327|-2.33043|-0.05716|
|2021|-0.00072|-0.00139|-0.00067|
|2022|-0.00170|-0.00163|+0.00007|
|2023|-0.00155|-0.00154|+0.00002|
|2024|+6.06193|+5.96999|-0.09194|
|2025|+0.48484|+0.49168|+0.00684|
|2026|+0.00036|+0.00043|+0.00007|

## 买入门实际作用与经济路径

所有成功配置的机会、原门/附加门拒绝、信号entry、执行BUY决策、BUY订单和实际BUY成交分别计数。确认字段在持仓日也计算；拒绝统计限定confirmation_opportunity和confirmation_rejected，避免把持仓弱分算成过滤交易。

|身份|基础机会|原门未通过|新增门未通过|两门均未通过|联合拒绝|信号入场|实际买入成交|
|---|---:|---:|---:|---:|---:|---:|---:|
|C3000|133|22|0|0|22|111|111|
|C3001|136|23|0|0|23|113|113|
|C3107|141|22|9|0|31|110|110|
|C3100|133|22|1|1|22|111|111|
|C3006|78|0|0|0|0|78|78|
|C3019|150|20|20|0|40|110|110|
|C3021|158|22|18|0|40|118|118|
|C3114|135|22|0|0|22|113|113|
|C3115|144|24|0|0|24|120|120|
|C3201|135|19|12|0|31|104|104|
|C3202|132|16|12|0|28|104|104|
|C3203|126|15|11|0|26|100|100|

严格经济字段投影、ID关联正规化及相同路径成员见behavior_groups正式材料；完整账本与诊断列保留，分组不等于完整策略政策相同。

经济路径分组材料状态：PASS，42个配置共34条严格投影路径；14个新达标技术身份对应8条路径，其中1条与原控制相同。源码、参数或分值不同但经济路径相同的技术身份不形成独立预测证据。

互补分代表C3107的2023年bull路线只有3个原机会实际应用新增门，拒绝0个；原5笔bull入场且regime退出的交易成交起止日期及价格相同，手数随继承资金变化，毛收益比例差小于1e-12。它的总年化改善主要在2024/2025年，2023问题交易没有被改变，不能解释为新增门已识别这些亏损。


## 价格状态幅度确认：针对归因的受限后续

将已知的20日价格状态幅度定义为confirmation_margin=momentum20-0.005，只用于所有bull买入（含状态重入）。现有组件与状态判断使用同一20日价格变化，因此直接使用bull.momentum_min=0.005+门槛实现，保留互补门和全部退出。0、0.0025、0.005、0.01四档分别对应C3200—C3203；0档是严格等价控制。该分有价格变化的量纲，不是分位或盈利概率，也没有等待天数。

设计依据来自已见2023交易：两个亏损入场的边界余量约0.000797和0.002371，一次盈利重入约0.011786；只是待检验线索，不能预判完整账户、其它年份或交易频率。方案保留已见信息和选择偏差说明，不新增经济验收门。

|身份|价格余量阈值|净年化|闭合笔数|2022净收益|2023净收益|四门|
|---|---:|---:|---:|---:|---:|---|
|C3200|0.0000|12.7130%|110|5.7831%|3.6875%|通过|
|C3201|0.0025|12.5186%|104|0.5611%|6.6021%|未通过：frequency|
|C3202|0.0050|12.3745%|104|0.5611%|6.6021%|未通过：frequency|
|C3203|0.0100|12.3037%|100|1.3038%|7.5609%|未通过：frequency|

## 每侧20/30bp费用压力

压力计划在压力执行前发布，覆盖两原策略控制、新达标最大年化/余量代表、新最大余量及最小四门缺口对照；不是全体候选覆盖。每次10bp分支的五类账本精确复现原账户。20/30bp会改变实际现金、手数和可执行买持基准，以下“四门场景诊断”不改变10bp候选资格。

|身份|每侧费用|净年化|闭合笔数|2022净收益|2023净收益|四门场景诊断|
|---|---:|---:|---:|---:|---:|---|
|C3000|10bp|12.3144%|111|5.7848%|3.6891%|同时满足|
|C3000|20bp|8.5773%|111|0.9767%|0.0619%|未同时满足|
|C3000|30bp|4.9643%|111|-3.6084%|-3.4379%|未同时满足|
|C3001|10bp|16.1572%|112|12.1687%|0.2841%|同时满足|
|C3001|20bp|12.2417%|112|6.2278%|-3.7959%|未同时满足|
|C3001|30bp|8.4568%|112|0.5987%|-7.7100%|未同时满足|
|C3107|10bp|12.7130%|110|5.7831%|3.6875%|同时满足|
|C3107|20bp|8.9963%|110|0.9829%|0.0636%|未同时满足|
|C3107|30bp|5.4020%|110|-3.6038%|-3.4388%|未同时满足|
|C3100|10bp|12.3144%|111|5.7848%|3.6891%|同时满足|
|C3100|20bp|8.5773%|111|0.9767%|0.0619%|未同时满足|
|C3100|30bp|4.9643%|111|-3.6084%|-3.4379%|未同时满足|
|C3006|10bp|8.9110%|77|7.7884%|4.0174%|未同时满足|
|C3006|20bp|6.3678%|77|4.7381%|0.9751%|未同时满足|
|C3006|30bp|3.8838%|77|1.7723%|-1.9789%|未同时满足|
|C3203|10bp|12.3037%|100|1.3038%|7.5609%|未同时满足|
|C3203|20bp|8.9311%|100|-2.9134%|4.4143%|未同时满足|
|C3203|30bp|5.6578%|100|-6.9588%|1.3624%|未同时满足|

## 技术验证、局限与研究判断

关闭新增门的两原策略实际账户完整等价，价格余量0档与C3107全部信号/五账本/基准严格等价；8组真实特征的因果前缀/未来变动不变检查通过；10项确定性分支检查覆盖等阈值、普通拒绝、regime豁免、原门独立拒绝、AND、弱分不退出、退出上下文、路由、权重和原退出AST一致。已发布源码和计划哈希核验通过。每个成功账户现金、数量、逐日归因及年度收益/回撤复算通过。

已知2020-12-01分钟Low差异的潜在受影响订单为零；已有四处分钟High偏差不参与当前可信日特征及限价买/市价卖成交。原31个数据资产及28个准备记录逐行保持。不把已知问题排查解释为不存在未知误差。执行Ruff、聚焦验证及交付FULL完整性校验，不做仓库全量回归；FULL PASS只证明契约、身份和证据可核验。

原C2308在2024-09-25至2024-10-08的一笔交易毛收益约36.66%，占所有盈利交易现金盈利约22.91%。新配置的实际大盈利集中性及短持仓分组全部保留；集中度是诊断。反复使用已见开发池和少量大盈利交易，限制未来有效性判断。

既有组件通过合理确认表达可以提高净年化，之前成交额状态重入门已经增厚过盈利余量，不能断言“已有组件无法解决”。本轮互补门提高年化但未明显增厚较弱年份余量；原始自相关硬门大幅损失频率；缩短持有期虽可能增加频率，却牺牲价格收益。价格幅度确认产生新买入路径，但闭合笔数仅100—104，2022/2023最小净收益0.56%—1.30%，没有接近同时改善原配置的余量和四门。上述取舍不是所有组件或权重的穷尽结论。

本轮宽松边界与邻域已有实际账户，新增门可保留频率，因此没有按条件启动价格状态幅度迟滞路线。相邻阈值若同路径只说明本开发池局部离散平台，不证明稳定性。未做新权重全面搜索、其它归一化窗口或独立样本验证；这些方向须根据机制证据决定，不能以固定次数宣称研究充分。

本轮沿绝对确认水平、应用范围、独立持有期和价格边界幅度完成必要对照；宽松门局部已呈相同路径平台，强门和价格幅度的收益取舍均受频率约束，没有当前联合改善方向的边界线索。因此收口本轮，不以42组数量宣称研究充分。剩余更有针对性的方向是确认信息在入场前后的变化：先以原策略机会验证相对变化是否具有增量，再决定是否构建新完整策略。

阶段三本轮交付目标完成。建议继续阶段三检验成交额与价格状态的变化信息；是否继续此方向或进入阶段四由用户决定。

## 正式证据索引

- [control-C3000](../../../assets/deliveries/CANDIDATES/6/evidence/8f9a4a15554bbc88ab3a2df768ce9102d1e235023cde8fefbb660eca44612c21.json)
- [control-C3001](../../../assets/deliveries/CANDIDATES/6/evidence/3dc7ee4a3e9094e47ed7b2d91d767418a894c1812bb12102b5a02018d755aa53.json)
- [control-C3200](../../../assets/deliveries/CANDIDATES/6/evidence/78b215412e7564f5cd1efb918f62cfa45025b9c88663e20ebef1191ff16b6dab.json)
- [cost-confirmation-account-references](../../../assets/deliveries/CANDIDATES/6/evidence/cf4936c5e5009c17a2cb843a20c05e6d0724eed0b98636e24ef6a5043108756b.json)
- [cost-confirmation-authorization](../../../assets/deliveries/CANDIDATES/6/evidence/9a8fbde23543ac4dafd731ce6715604bd7c87a2a4deeec466ade7fe40aed839b.json)
- [cost-confirmation-behavior-groups](../../../assets/deliveries/CANDIDATES/6/evidence/738679574130fd7cb32a155a5eb7f891cb6347961fe0702787fea4b6b14d4e39.json)
- [cost-confirmation-boundary](../../../assets/deliveries/CANDIDATES/6/evidence/b823be1940f871567f005bb09df4611078b351a2125bd3a43ce40e4269d72f39.json)
- [cost-confirmation-boundary-plan](../../../assets/deliveries/CANDIDATES/6/evidence/1533acb4966ce6b552299daec9c0404825b6e625238cab73cf9fd2ba8e32bdaf.json)
- [cost-confirmation-complement-synthetic-check](../../../assets/deliveries/CANDIDATES/6/evidence/3b91d7b24a1ad2022151329497b99de0a3e8ac83797119d4ea89d554564b45c4.json)
- [cost-confirmation-cost-diagnostics](../../../assets/deliveries/CANDIDATES/6/evidence/7f169e687fa8dfdd9df1783b0f94917d0fa78ac996fd3742d746dcbefddb2e77.json)
- [cost-confirmation-diagnostics](../../../assets/deliveries/CANDIDATES/6/evidence/c59f21542dcf7aae9aefe28dca9df74a1513977fe651a8ba92ddfb45f9af6729.json)
- [cost-confirmation-extra-stress-plan](../../../assets/deliveries/CANDIDATES/6/evidence/4c864416c60c75f77a0099bdb781775abedc732e700ea507005db1962615bef9.json)
- [cost-confirmation-initial](../../../assets/deliveries/CANDIDATES/6/evidence/b777f939eb3d878ebcc633be8a227f3c02ff5482a3e5c49c19cbff46cce882a9.json)
- [cost-confirmation-initial-plan](../../../assets/deliveries/CANDIDATES/6/evidence/0404331dca7ddad389c9cfbed6fc92808681ad4aeb2b4e53a362d04394635295.json)
- [cost-confirmation-path-attribution](../../../assets/deliveries/CANDIDATES/6/evidence/ba29f7f5cd484ce96a40dfbd10a54c0f10f8cd897f6acb15882bc64bfe547719.json)
- [cost-confirmation-precheck](../../../assets/deliveries/CANDIDATES/6/evidence/6ded8c2bec9f251a1290d8a752d8ae709b400304623890d6b44e49921499986d.json)
- [cost-confirmation-preservation](../../../assets/deliveries/CANDIDATES/6/evidence/935e34a4232784aab52313925b4633a937b5f8f09afabf8054950a80288b74fd.json)
- [cost-confirmation-price-margin](../../../assets/deliveries/CANDIDATES/6/evidence/fad4616a0b063e08999e5f9c5c4325a397eab91211e0092703816ef52c637fb3.json)
- [cost-confirmation-price-margin-plan](../../../assets/deliveries/CANDIDATES/6/evidence/ddf84b72cd1e394a4613c412500094e9dde158e08fe071488a7b993e6b83404b.json)
- [cost-confirmation-price-margin-precheck](../../../assets/deliveries/CANDIDATES/6/evidence/fd6b1ddd344fc610856bed9f385cda9fc522b21e2d2eb89c42e9c037263f8b4f.json)
- [cost-confirmation-reproduction](../../../assets/deliveries/CANDIDATES/6/evidence/55cc950110ac70295552006b407e146904b1ddf72c5a4ca152bc942225367b53.json)
- [cost-confirmation-selection](../../../assets/deliveries/CANDIDATES/6/evidence/8198494b048855f977fd737990004a703f50f2e1cfb9defb98fbdc0eb2fbdd3b.json)
- [cost-confirmation-stress-plan](../../../assets/deliveries/CANDIDATES/6/evidence/25008057bb03e4bdfd24dbd91f312c64d90a21bf7f5a36d1452ad13170206755.json)
- [cost-confirmation-synthetic-check](../../../assets/deliveries/CANDIDATES/6/evidence/faf093f0c53e81565c17de0696bca4a65a8d8e0c3bb6e87e323c773d53d1fe5e.json)
- [cost-confirmation-trade-attribution](../../../assets/deliveries/CANDIDATES/6/evidence/90818588f35f4362bc53d563e3115809b5e4f118cb62062975edf9ece6dc4bff.json)
- [pressure-C3000](../../../assets/deliveries/CANDIDATES/6/evidence/1dcb04f6b5e304b8dca9ba37ec6dcbbb1f4f101eb0f0b4ade9a27faac9201008.json)
- [pressure-C3001](../../../assets/deliveries/CANDIDATES/6/evidence/25e2a498b9501dbeaf47acab9e5674dd32125b02b44a88fd2c8211fe02cf75e0.json)
- [pressure-C3006](../../../assets/deliveries/CANDIDATES/6/evidence/980541da17a58ff864d2fde37fad1e45f28dc3138d16e6307855386bd0a51c03.json)
- [pressure-C3100](../../../assets/deliveries/CANDIDATES/6/evidence/72e94ebb2b3545cbb21768f0738b5ee10e64a5e5de82055836b17f7e5896bffc.json)
- [pressure-C3107](../../../assets/deliveries/CANDIDATES/6/evidence/55d0b1991e46bff14cc7ef9adbd2c1b823127632d871e4af7f65d1803e37f7d5.json)
- [pressure-C3203](../../../assets/deliveries/CANDIDATES/6/evidence/3bf8a4396d997fa9ec98a09e0c17de08bc890276b0057587baed3e82d20a501d.json)
- [C1000完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/3bdddb97c03cce6da5b963a353bde216c4c2c14aa243e725927a26be57cb6305.json)
- [C1013完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/61dd042547a4a59b85ff17ea2be1192e757028c223d862b70474d727c87e15c0.json)
- [C1124完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/0b40189dd4aade40918ea4119ecbe17aa81ffb8ef641fd32d30715cc929e5b17.json)
- [C2000完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/957b9394adff4e9058ed515b36dbe2f188519ebb31d67487da4ca5cddebd879c.json)
- [C2001完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/66f74b2f03e5e702bb254663acd97026a97ac3b63a3630995043817d5877ec3b.json)
- [C2002完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/979264848ee887c6ec7acda51237961665ea0bb68f0623fbd26ebb01b726fcc6.json)
- [C2003完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/4f50265e5c2294f89e6513f1158f813968f2a23f6c3aee75c5c126a4b58ee015.json)
- [C2004完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ae658cc6b53ae16eade0058021b3fc6fd871e7a4a90ad2ac519a1f2343b01753.json)
- [C2005完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/e9bc3e4efeeb52857cd6bbd91efc305d5d9313c30bb6ba03563edb04af1ab5ab.json)
- [C2006完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/46a05729a536095d1b28111dcbeac38619ae73a7d5590ed9c2367b8becb87056.json)
- [C2007完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/97b5f8b0f25ee450c785a660a7d34fce785b06f99df31245f7cd390aa627dbaf.json)
- [C2008完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/0bd586aec0342d91583fc14716cdb606d1d8ed0a7e6cc853dbf76d6b627a920b.json)
- [C2009完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/675dbf0764258f1b0cb535e4acd0fa01209708c12fad83f4c3ac36a7cef567ff.json)
- [C2018完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/4e3981c0877e868db62a45770905401e053eec20d93159b2d7d5920f6bbff6f2.json)
- [C2026完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/3a9c6f26671f58b506d6b2d9164d72538655864b299aa55e7c5bc0ab08c4555b.json)
- [C2030完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1de71dae12bd061bbcebac11ace314089e5a24c5a200a718f58d6aa41ea9b428.json)
- [C2034完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/13ba93c6b869a7eb6a2d07c406713ff098e5382b3b5e93a47765cf84dd1c9a9b.json)
- [C2038完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/fefcb5123336d308b19e4ae20e2357534d50fe9d0bff7c63be5a604b3efb853c.json)
- [C2059完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/5fcb6667c41708cda2225196438a39bb5ee679948d89b557d802c03588ade9ef.json)
- [C2080完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/8769030e3f793f1ae4a733d37dbfb933d96cbfaae69205a8f8a7e577e266ff3f.json)
- [C2100完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/b513c6c31af7238526c2b6ff9c17b9d7b19c2b2ee38c7f00501578606df4edb3.json)
- [C2101完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/eee7b27978c03dc81fd79a11998d3dfca5eaf5f9cfc652dd18fb50952decdc57.json)
- [C2102完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/5e377a303c7441d0ff20e294b701c451ac7153ad119a1b42196850a041fc00c5.json)
- [C2103完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/a77df7899f2ddee4e91ec3f3987046b21bee95ee0d1b3f5d94d2e9f35baecffd.json)
- [C2109完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ced36ec09ec83aa5d90b4f5d3b27c4ac71d1f26147b0bb6980efea93e5d61993.json)
- [C2111完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1cf6dce0cb4d0c65260c2a6a48db54293cdb2fb795ed0e2a840c696da3801f20.json)
- [C2126完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1550c39485e6e62f461a6ed17027cd646b6f57b537492bbd5c9a1c6fc0683a4e.json)
- [C2127完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/413983cbc7ff93fb572a9c968c5bfb92acc0f2e8153ef549febfbcc873964d8c.json)
- [C2132完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/6f1e172710f3ad124b05b710b45f568145969f2e41da3ed57e4c3f2700423d3e.json)
- [C2133完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/6ba4195ab511127b3a2d1374cefc87c54ebfe863e03ffc7a40992eb4d444a570.json)
- [C2136完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/d8253dbc6b7a3559f1754819e768341a28a75659c7dce42a3c464453907e8306.json)
- [C2142完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/fb0cf379c30775fb101a97c3e821ecda010d1d464f15bdbff61d638ea2ca807f.json)
- [C2144完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/94455deface2044ae25a011463411274c4fa489719432f51848561b685ff3c6c.json)
- [C2145完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/46fde9af811ac43bb0d09d0ad38551d0e89179f7ba83074ccd7f61d9bfc81b17.json)
- [C2203完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ac99395a6514869b4afb9a404b5c55bab8fdfc48a1ddf3a3ed9e71ca5a4b1c6d.json)
- [C2204完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/7c1930c45bdba4a3c4d3465e3c2d19aa5e401c83bd84d28cecd716ecc14113b3.json)
- [C2208完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/5a3019466071c5852bcd9a89dde111877409dc3c8e71673889431aff238e2e72.json)
- [C2209完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/4f441a83cf1774fb2cf209fd9f2ff39b70402ca55be412450af1423ac2d8b4cb.json)
- [C2212完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/18806c40f3927ffd57184f195789e4498bede1c06550090b4c9eb9261e350958.json)
- [C2213完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/e8f542d55b1cf9d032a7c6371e5d9b9f7ddde6035e0a76c19b13173256e9535f.json)
- [C2214完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/030e066473f9f1f001d3918656fb49c8358d25bcc77fbd4d143ef5988a8e7abb.json)
- [C2215完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/0d730fdf3f39411a8f0f866d58074494a2460d54f1947d68577f3479389ee02e.json)
- [C2216完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/41f63e0da2debe2fbc50397d5d0ab9d1f9e15c5a19c6e3f4c513608002f8a1b6.json)
- [C2300完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/2848e95c0a5be18a6986509392d184f5c38c93ebf827244e4a790ed159200707.json)
- [C2301完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/41922578ae365d0d70820db53ef7aec0edfa0e7c6d6de2ff12aaeb2c80de873e.json)
- [C2302完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1a81aa32200310368dfb87c3ec5d73bb33596250b2e205bdc0cb0a11a6e665b3.json)
- [C2303完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/9a9d9941c7156147c092a02d3fa25bf6a28d7c09bfaea79db708564179f7148c.json)
- [C2304完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/d302c519ec65ec7119accee89b890ef3c29983688299c61141dbada6d2116de9.json)
- [C2307完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ea655d834a3ce3d8339647fc99dc98769449b269fec9ab2ff391a98ea873b387.json)
- [C2308完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/479891b2fdb62943b3d636396675274087edaf6f509e35960351f46e4d888e06.json)
- [C2310完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/57353a22e8a326565cb25bd15f60b35e094d436274afa56444cc7ce953688ff7.json)
- [C2311完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/eec8a62a466014830dedb8dd7da0620b96e674eafdd8314608e9370a7b4d0586.json)
- [C2312完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1ec67863051b0f32e18ed77e86b53a044b8424f55aa635fabc87b0631060101a.json)
- [C2401完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/82c62a56c6d73849594162c36d9813023e95ef542814ba984822e4d9efc2be0d.json)
- [C2402完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ce3c70033c8c2d9e6e5eb2771d958597889d22cdc0d6d64cb32f65ac6f5919bc.json)
- [C3006完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ad1f5adc4e782696221dd6947880b6cb9bf7d343cf1737f78d8e3a1823f96dbc.json)
- [C3008完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/dea6ac2a3477254016f7c6f315517a86b2773274c2a21b0ecce021e1caa35b4f.json)
- [C3009完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/5eb743abe4d6fc71bbe9f6c03058bdcb87a428270660d2a9489598855ad1b3ff.json)
- [C3011完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/575ae256d3e140a3b9c06df09def05a41b5cf950b400facf71c7be82439f91aa.json)
- [C3019完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/89c06dfa93b567ce7a5eea89bf7f8efa27e3ee761fad21541eb6ce4fa26daeef.json)
- [C3021完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/ffce88cbff20697e117c60e1e48623952c365934a6d7bee146669a3fb329329f.json)
- [C3100完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1d2afbdcbfe8130cfb95ff3aa344f09b9316f133b8ff065e69ebc68b3d02bb76.json)
- [C3101完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/2cf769d96355e8a6b61bb5decff6ac17ac18f80d475e69b5d3143b4f53970666.json)
- [C3102完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/51e2cb2b333c1f042874f21b96f6383c7b1b17955b8ab312cf87b78b1f472073.json)
- [C3103完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/a7c022139c4dd596cb7b6471e90edafe7753d8bfa3c8e3e141f1594115cf513b.json)
- [C3104完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/3565be8a703c4bcdea07978fc14bb0003b50190c54ed109ca0333a0a7546c53a.json)
- [C3105完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/77192482dafd22bde5ceb23d9f71b708bb188f565b3175563f8c00bbb37d570d.json)
- [C3106完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/67b327f1cca603abb46bf857fd554f457e53974a173f586f02d47ea8cd5ca972.json)
- [C3107完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/933065ade4e25eec3d8280aaf827023ed5a855f74eda33f1d88805b5e6721019.json)
- [C3108完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/58c9dddcb27486f1636a70cd5e5f303d32c763a156b34e5e33c0b6d7442a287b.json)
- [C3109完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/263eb5c27af72a3b88f609254af716a483ee6f7558d7ee59f0da7e77a427a176.json)
- [C3112完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/a84befefea2f8ab5f663aea0ad9ef56f87c2077527229b2e04556cfd893f6c2f.json)
- [C3113完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/84edd2dc37ff5f75cd91e9a846b2e49bc74e63cdb3046652d829bad6ec280433.json)
- [C3114完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/c58827b6ada19177a79236615b721e88b5e146cfa61bd807c3e52603d664b175.json)
- [C3115完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/0e37e70ea012eec22846bccb450c41504b9cc0de9ac01af629042b024e01f7f9.json)
- [C3201完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/781f721d99da515495bad908f0bf37a91e53ba4a21f16ec386dfcfeae11233b3.json)
- [C3203完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/fa6369e42f795f2eada510210ebc5172528de74b6c5880362f9f33a20cea5f73.json)
- [C9018完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/12b1103556638e4902d6ef9a3ba7b76fc0502cc3a68c3ee90c2bf0e2c5480f28.json)
- [C9020完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/8f570966ef68704c918e45d556e43649e0b9c0f0700186054e36ffc0b83784c3.json)
- [C9023完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/fcf6e9bef89a648056226e3b0a10b791e1a3636df8d18246dc649f3719bd785c.json)
- [C9024完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/1a5f42dd206eccc6049e3b5bf55afaadb3b2d60999b385f633452c557ab565e8.json)
- [C9025完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/049a622eb6d24a3105cbb37ef182539e9698d0794d6eb4c7ae07e7774583e005.json)
- [C9026完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/dd1808b47afe3ef0efd4dab3a5ce0d71a55b857e3b76cdc9e641050d3cddea27.json)
- [C9027完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/91685cd72cd716eeac212a1618aca2432fc70a53bac76a00217dce418ce8f1f9.json)
- [C9028完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/402aab2547a5476fc629adb32412080f8f921fa8f19bc39b84812cceba437ef4.json)
- [C9029完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/86a299e660ffe9f4489c426cb763aec340e0e34116fce08eb57b79fc7ecfb2dc.json)
- [C9030完整账户](../../../assets/deliveries/CANDIDATES/6/evidence/b2fd6abba44aa22148fef49e05aa21215aa1437598e4eeed393d0468872b55a8.json)
