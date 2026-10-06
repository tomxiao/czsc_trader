# S012｜阶段三进行中：收益优先的完整账户研究

当前身份RSCH，分支`codex/s012-research-resume`。用户已批准基于EX041组件交付继续并自主完成阶段三，授权留证见[继续研究决定](materials/stage3_resume_after_native_decision_20261006.json)。研究使用S012既有数据与资源、完整GVZ和有限美元篮子；全部窗口为已见开发池。

按净年化收益、最大回撤幅度、实际闭合交易频率依次排序，保留三个同时达标门槛：净年化至少为同执行BuyHold的1.5倍（当前21.4300%）、回撤幅度严格小于基准（当前30.2906%）、闭合周期数乘60除1535至少为5（至少128个闭合周期）。末尾开放周期不计闭合。

- EX043完成12组初始FULL；EX045保留1成功及11输入身份技术失败；EX046完成11组退出/风险FULL。全部原件及反面结果保留，目前均无三门同时达标方案。
- EX047实际完成8组FULL，但空批次调度导致缺失完整REX回执，属于部分技术失败。其证据只作历史参考。
- [EX048账户结论](../../experiments/S012/EX048_20261006/04_conclusion.md)：同参数重执行8组FULL，完整REX、独立账户审计和逐笔等价检查均通过，档案封存验证通过。收益最高方案净年化9.0546%、回撤幅度18.4388%、29闭合、频率1.1336；收益和频率未达标。
- [EX049搜索设计](../../experiments/S012/EX049_20261006/02_design.md)：已绑定当前有效等价证据，正在正式运行1040项持有期、限价和机会组合的条件网格。8进程、每进程1计算线程，单目标最大化净年化。运行中的结果只作为部分进展，筛选达标和选定前沿仍须后继FULL。

阶段三尚未完成。下一步完成搜索、检验有依据的收益改善与参数边界、补齐完整账户复验，随后发布CandidateSet及人工报告；不得以固定网格完成或空达标集合自动推导研究收口。阶段四、新数据或依赖、DEV、生产及合并/tag/推送仍须相应授权。DFLS受管资产和实际REX制品保存在本机，Git不携带全部制品。

# 历史：阶段二收益组件完整交付（EX041）

用户本次授权自主主导阶段二收益组件挖掘；沿用codex/s012-research-resume、既有资源、完整GVZ及有限USDOLLAR，未运行阶段三账户、接入新源或修改平台。

[期限竞争补充](materials/stage2_native_horizon_review_20261006.md)汇总已封存1/3/5/10日对照：10日亦有正收益证据，但动量并集只有74次潜在触价，不能以5日负证据概括全部期限，也不能将潜在次数当闭合频率。

- [本轮人工报告](../../experiments/S012/EX041_20261006/stage2_report.md)、[147条完整台账](../../experiments/S012/EX041_20261006/full_research_ledger.json)、[当前角色](../../experiments/S012/EX041_20261006/role_coverage.json)。前轮142条历史判据保持；本轮新增5条用途/反证记录，无新增独立支持收益机制。当前推荐5组件：O01/M05两机会、C01/C02/C03三风险状态；Q07调整为O01内可选确认候选，N09仍候选，不覆盖历史SUPPORTED。
- 原生M05保留163信号，共同域160；纯动量全域836信号，共同域646，差额不能称因子增量。190额外成熟动量事件收益负，全域主5日128潜在触价净−0.0062%；动量加O01/M05134潜在触价净0.1206%，双费转负。潜在触价不等于真实成交、账户收益或闭合频率。
- 直接O01/M05互补同域六相位基础边际+0.04285个百分点，去2025后−0.00328个百分点。Q07主5日所有费用/延迟六相位加权贡献负；保留高事件收益和原稀疏时间表正证据，作为可选候选对照。
- 正式REX INCONCLUSIVE，216路径、1512年度、6624相位/去单年；独立复算49728字段PASS。限价为收盘向下取整到0.001价格档（通常等于收盘），没有再减0.001；发布前报告澄清不改变执行源码或制品。
- [精确交付引用](materials/stage2_native_components_reference_20261006.json)、[FULL](materials/stage2_native_components_validation_20261006.json)、[档案核验](materials/stage2_native_archive_validation_20261006.json)、[封存完整性](materials/stage2_native_sealed_integrity_20261006.json)。owner=EX041_20261006、COMPONENTS修订1、content_sha256=42f663cfa2299b78792ea3eb73a32ee478215de164356da0b56947d305471bf4。

阶段二目标已达成；原三个完整账户目标未复验，全部开发池已见，历史发布时间、代理资源、分钟异常及年度/费用敏感保留。下一步建议获批后做机会独立/联合、有无Q07、纯动量及其加机会完整账户对照。阶段三、新源/依赖、DEV、prod、合并tag推送需各自授权。EX040未执行空目录保留编号，先前阶段三启动记录保留追溯，本轮当前范围以stage2_native_scope_authorization及登记COMPONENTS COMPLETE为准。

# 历史交付交接记录

# S012｜阶段二完整交付交接

## 当前状态：COMPONENTS COMPLETE，等待阶段三新批准（2026-10-06）

用户授权自主主导阶段二，以挖掘收益组件和完整交付为目标。RSCH在codex/s012-research-resume使用既有S012资源、完整GVZ及有限USDOLLAR代理完成研究；无新来源/依赖、DEV、生产或远端变更。

- [完整人工报告](../../experiments/S012/EX039_20261006/stage2_report.md)、[角色及原记录映射](../../experiments/S012/EX039_20261006/role_coverage.json)、[完整研究台账](../../experiments/S012/EX039_20261006/full_research_ledger.json)、[全实验索引](../../experiments/S012/EX039_20261006/experiment_inventory.json)。完整面板142记录、1536事实，当前推荐6不同职责：O01/M05两有边界机会、C01/C02/C03三风险/状态、Q07仅O01确认。N09保留候选，不计当前推荐；原支持和失败记录保持。
- EX037—39正式新增22主记录、594路径、4158年度，另306分钟异常子样本、1152父相位及288集合相位；三独立复算580068字段PASS，当前绑定/真实制品SHA、旧风险原价1535日一致、角色台账、人工机器事实及收口检查PASS。
- M05为原第一性原理重建后的新增有边界机会：163事件5日净0.6345%、EX036父内+0.2289pp、固定父限价+0.1030pp；年度、双费绝对贡献及延期OLS反证保留。O01低频、双费触价负；Q07延期与去2026贡献负，不作通用强制门。
- N09正常定价门相对纯动量父基础固定贡献−0.08355pp，全部六相位加权−0.04314pp；双费相对节省为正，保留场景差异，当前不推荐默认门。M05强制确认N09六相位全部费用/延期加权贡献负。
- 旧O01/N09集合加M05六相位平均小幅正，但去2025后基础/延期1/2为−0.02060/−0.00929/−0.01421pp，双费也负；单一起点原贡献负，不能承诺组合收益。相位汇总是重叠事件信息诊断，非完整账户。
- 无新增分钟推荐组件：M05内尾盘回调/午后上涨的高均值在延期、去2026及异常子窗反证下未支持。主信号保持26异常日；离线影响窗排除重排日历，仅子样本诊断。
- [精确交付](materials/stage2_complete_components_reference_20261006.json)、[FULL](materials/stage2_complete_components_validation_20261006.json)、[三档案](materials/stage2_complete_archives_validation_20261006.json)、[封存INTEGRITY](materials/stage2_complete_sealed_integrity_20261006.json)、[登记结果](materials/stage2_complete_result_20261006.json)。owner=EX039_20261006，revision=1，content_sha256=2e03ca47d9eaff2793317984b87c3bfc39fc06107f183d0cc54a27d0e735b97d。

阶段二完整交付目标已达成，停止该阶段自主探索。原净年化≥1.5BH、回撤幅度<BH、闭合交易≥5/60三个完整账户目标未复验；全部开发池已见、真实发布时刻、数据异常、限价潜在成交及年度集中仍是边界。旧阶段三未达结果保持。建议获批后做O01有无Q07、M05独立原型及两机会组合的最小完整账户对照，N09仅候选/纯动量删门对照。阶段三、新数据/依赖、DEV、prod及合并/tag/推送须新授权；真实证据与DFLS资产的本机闭包保存，Git不携带所有制品。

# 历史EX032—36增量交接

# S012｜阶段二收益深化交接

## 当前状态：本轮交付完成，1个有边界机会环境，整体阶段二IN_PROGRESS（2026-10-06）

用户授权“同意。请你以挖掘收益组件为目标主导阶段二的执行”。RSCH在codex/s012-research-resume使用既有S012资源、完整GVZ与有限美元篮子；无新来源/依赖、平台、账户或生产变更。

- [当前主要发现](../../experiments/S012/EX036_20261006/stage2_report.md)、[收益组件完整报告](../../experiments/S012/EX036_20261006/04_conclusion.md)、[全轮机器摘要](../../experiments/S012/EX036_20261006/cycle_summary.json)。五正式后继EX032—36、47主记录、1152路径、8064年度，包含继承/重复，不等于独立机制数。增量面板47条记录、672事实，PARTIAL。
- 新SUPPORTED为1个有边界机会环境：原M05“风险上升且黄金涨，黄金/VIX固定60期相关>0”。163事件5日净0.6345%，同父匹配+0.2289pp，34去重潜在触价净0.7277%；固定117父槽限价增量+0.1030pp，延期1/2日+0.0635/+0.1409pp，去任意单年聚合增量仍正。
- 反证：2021/24事件净亏、2023/24/26基础固定贡献负，延期2日父OLS负；主增量区间跨零、所有历史已见。频率仅1.329潜在成交/60日，原账户目标5/60未满足。每侧0.2%无额外延迟时绝对固定贡献−0.00907%/父槽，正增量只是相对改善。不是账户年化或目标达标。
- GVZ纯价格消融、低比值M05确认、黄金/汇率与本地补涨、严格同日端点、去单年和阳线/非阳线确认均主动检验；附加门未改善为推荐组件，年度/延期反证不隐藏。此前四轮原结论保持，EX036新增支持不改写历史。
- 五项独立复算1050058数值字段PASS；独立只读审查另复算固定父限价与区间及去单年。统一FULL、五档案及封存INTEGRITY PASS。技术通过与研究SUPPORTED和完整账户目标分开。
- [最新交付身份](materials/return_discovery_final_components_reference_20261006.json)、[FULL](materials/return_discovery_final_components_validation_20261006.json)、[五档案](materials/return_discovery_final_archives_validation_20261006.json)、[封存](materials/return_discovery_final_sealed_integrity_20261006.json)、[授权](materials/stage2_return_discovery_authorization_20261006.json)。EX035继承范围文字的计数差异以[勘误](materials/return_discovery_scope_note_20261006.md)共同阅读，实际数据和数值未改变。

本轮收益深化与增量交付已完成，整体阶段二尚未完成，原三个账户经济目标未复验。下一优先方向是已有日线/30分钟线的盘中收益形成与限价兼容互补机会，披露原分钟线质量问题，不用未来质量标签筛交易。若批准阶段三，先做M05有无的最小完整账户对照；新资源、DEV、生产、合并/tag/推送均另需用户授权。历史六角色组件保留原身份与边界。正式制品及DFLS资产本机闭包保存，Git不携带全部真实证据。

# 历史GVZ初步验证交接

# S012｜GVZ与有限美元篮子初步验证交接

## 当前状态：初步验证完成，整体阶段二研究进行中（2026-10-06）

用户最新授权“切换RSCH。先用完整GVZ和有限美元篮子数据做初步验证”。当前身份RSCH，分支codex/s012-research-resume。DEV接入已在9ece96ad本地提交；研究保持原518850.SH全部上市历史开发池、原三个经济目标及成本约束，未进入阶段三。

- [初步研究报告](../../experiments/S012/EX031_20261006/04_conclusion.md)、[结果机器摘要](../../experiments/S012/EX031_20261006/preliminary_result_summary.json)、[授权](materials/gvz_usdollar_preliminary_authorization_20261006.json)。
- 正式GVZ初版1694条覆盖2020-01-02—2026-09-30；USDOLLAR四币代理976条仅至2023-06-01，其中90条周末观测标签。美元检验决策日截止2023-06-01，不补齐后期、不作为ICE DXY。源五期为五个原生观察数，不称五个交易日。
- EX031完成九固定主假设、四对照、260路径、1820年度及九项主诊断，增量面板九条记录、105事实，新成熟有效收益组件0。高VIX/GVZ避险5日净均值−0.1333%、低比值0.5500%；低比值匹配+0.2394个百分点但额外延迟两日转−0.0780个百分点，2022/2024负。美元走弱趋势10日净0.2572%、匹配+0.2019个百分点，仅有限历史，潜在触价净接近零。
- 九项匹配增量区间均跨零；研究判断不以诊断新增经济硬门。低比值及美元趋势只保留后继线索，原三个完整账户经济目标未复验。
- EX030保留原同可得时点排序局限；EX031双键选取最新观测，七特征单元修正而全部信号、260路径点估计未变。EX030结果已经见，EX031为同源修正，不是样本外。
- [独立复算](../../experiments/S012/EX031_20261006/artifacts/verification/independent.json)PASS，核验233009字段及源SHA、可得政策、信号/标签、路径、年度、BH9；不复现随机抽样，不证明真实发布时间或账户绩效。
- [正式增量组件报告](../../experiments/S012/EX031_20261006/deliveries/COMPONENTS/1/report.md)、[FULL核验](materials/gvz_preliminary_components_validation_20261006.json)、[EX031档案](materials/gvz_preliminary_archive_validation_20261006.json)、[EX030局限档案](materials/gvz_preliminary_original_archive_20261006.json)。准确交付身份以[引用](materials/gvz_preliminary_components_reference_20261006.json)为准。

初步验证目标已达成，整体阶段二IN_PROGRESS。建议后继拆分低比值的VIX/GVZ分子分母作用、年度集中与延迟损失；保持同有效窗口父对照，不直接反转为买入策略。新增美元来源、其他资源、平台修改、阶段三和生产／合并／tag／推送须另获授权。本轮仅本地提交，真实机器制品及DFLS资产按本机档案保存，跨机器复验须同步完整前驱闭包。

# 历史第一性原理首轮交接

# S012｜518850.SH 阶段二第一性原理交接

## 当前状态：重建及首轮普查完成，阶段二研究进行中（2026-10-06）

用户批准按黄金第一性原理回到阶段二重做收益假设，并提供宏观金融、资金流与持仓、微观量价建议。当前分支codex/s012-research-resume；RSCH使用既有S012来源，无新外部行情接入、DEV或阶段三授权。研究登记RESEARCHING、意图COMPONENTS/IN_PROGRESS、正式交付PARTIAL。

- [新收益假设与全主结果](../../experiments/S012/EX029_20261006/04_conclusion.md)、[外部建议审查](../../experiments/S012/EX029_20261006/external_advice_review.md)、[正式25记录面板](../../experiments/S012/EX029_20261006/deliveries/COMPONENTS/1/report.md)。19已检验定义、6缺资源记录；新确认有效收益组件0，历史39记录和阶段三空达标结果保留前驱，不改写原判断。
- EX029受管REX为INCONCLUSIVE；实际19假设、11对照、600路径、4200年度，全部1535上市日已见开发池。[原协议数量说明](../../experiments/S012/EX029_20261006/protocol_count_correction.md)只纠正18文字计数，未改固定19定义或计算。
- M05时变避险确认5日净均值0.6345%、匹配+0.3674pp，34潜在触价、1.329/60日；年度2024负、延迟匹配负、区间跨0、q=0.9685。M01趋势质量10日净均值1.2651%、107事件、13触价，2025集中、2026负、延迟失效。两者仅后继线索，不是账户或Alpha。
- L03份额增长未涨组5日净均值-0.1980%，相对父对照-0.2985pp；追涨组匹配增量负。回调修复G08/L06及低ATR/缩量直接门未得到稳定增量。全部正负结果完整留存。
- [独立复算](../../experiments/S012/EX029_20261006/artifacts/verification/independent.json)PASS，198004字段、源SHA、时间与换月排除、全部标签/路径/年度/BH一致；不重复随机抽样，不证明源政策等于历史公布时间或账户绩效。[交付FULL](materials/first_principles_components_validation_20261006.json)、[EX029档案](materials/first_principles_archive_validation_20261006.json)PASS。
- 用户要求优先核实Tushare；实查69个FXCM标的仅USDOLLAR.FXCM命中，它是四币篮子，不能标为六币ICE DXY。Tushare公开目录未确认DXY/GVZ。[核查及最小实施方案](../../experiments/S012/EX029_20261006/tushare_resource_verification.md)：USDOLLAR可复用现有DFLS FXCM入口，但尚未验证全历史；GVZ建议FRED GVZCLS，需要DEV最小新增明确语义的数据契约和提供器；坚持DXY则需ICE历史许可路线，未确认免费完整获取。
- 原阶段三19正式账户/603搜索成功账户均无达标候选；原净年化≥1.5BH、回撤<BH、闭合频率≥5/60日不变。本轮不建账户。新来源、DEV、阶段三、prod、合并/tag/推送均须各自授权。

精确新交付：owner=ExperimentOwner(S012, EX029_20261006)，stage=COMPONENTS，revision=1，content_sha256=a196cfdd5f9d84634adb9e08392d748cd431042e25dcb013826efc56d6e777eb。

重建假设与首轮检验目标已达成。下一步请用户决定USDOLLAR明确命名代理+FRED GVZ的最小路线，或坚持ICE DXY原序列；获批相应资源和DEV契约后回RSCH继续固定机制检验，阶段二尚未完成。仅本地提交，完整真实证据闭包需跨机器同步。

# 历史阶段三交接

## 当前状态：阶段三交付完成，达标候选0（2026-10-06）

用户已批准阶段三自主完成；本轮在codex/s012-research-resume交付CANDIDATES修订1，登记保持RESEARCHING，阶段意图CANDIDATES/COMPLETE。原三个经济目标尚未共同达成。下一阶段待用户决定。

- [人工研究报告](../../experiments/S012/EX028_20261006/stage3_report.md)、[正式交付报告](../../experiments/S012/EX028_20261006/deliveries/CANDIDATES/1/report.md)、[实际回执](materials/stage3_candidates_reference_20261006.json)。
- 广域与局部累计772项Optuna提议，603个成功研究账户、169项因果容量或语义等价剪枝；747个唯一参数、589种实际经济交易行为。搜索次数不等于独立策略机制。
- 19个正式完整账户（EX023 11、EX025 4、EX028 4）全部完成，原三门共同达标0；CandidateSet保留19项正式评价及3份搜索记录，handoff为空，未登记负结果为可交接策略。
- 满足回撤和频率的最佳C3000：净年化10.2881%、回撤幅度20.9307%、132闭合交易、5.1596次/60日。原BuyHold净年化14.2867%，收益目标21.4300%；最佳可行方案比初始联合h5的5.9853%改善4.3028个百分点，仍差11.1420个百分点。
- 最高净年化15.0934%的配置只有19次闭合、0.7427次/60日；1%限价附近、邻近持有期、退出及75%仓位未再改善可行前沿，广域和局部扩边增量均0。按经济反证停止当前原型，不按固定次数宣称全局不可达。
- [FULL交付核验](materials/stage3_candidates_validation_20261006.json)、[本轮8实验档案核验](materials/stage3_archives_validation_20261006.json)及[19账户独立审计](../../experiments/S012/EX028_20261006/artifacts/verification/audit_all_19.json)均PASS；逐信号及全部经济账本11+4+4账户等价核验PASS，8项合成场景PASS。技术通过只表达契约和复算一致性。
- EX020/21技术失败无账户，EX022保留1个FAILED尝试及不完整REX；EX026全部计算完成但Windows制品登记失败，原失败封存，由EX027逐SHA承接真实原始账本并完成后继受管执行。两者均无伪造完整执行回执。
- 实际账户2020-06-08至2026-09-30为1534日；上市首日真实热身，频率仍用1535日分母。每侧0.1%成本、100股整手、只做多无杠杆、T+1执行；期末开放交易按市值计入权益，排除闭合频率。
- 所有历史已见且跨轮选择，正式FULL复算不构成独立样本外证明；DFLS现有容差、26日30分钟异常、历史外部数据可得时间假设继续披露。

精确交付：owner=ExperimentOwner(S012, EX028_20261006)，stage=CANDIDATES，revision=1，content_sha256=f3547d436382c506e29ae5a275bc2ad53c12e919d2ec9b4c8dc8b5acc9bbc922。

阶段三交付目标已达成，经济目标未达成。建议用户审阅后决定回退阶段二，研究成交后保留更强净优势的机会。阶段四、新资源依赖、DEV、生产、合并/tag/推送均未授权。本轮仅本地提交；完整制品、失败继承bundle及DFLS受管缓存本机保存，跨机器须同步真实证据闭包。

# 历史阶段二交接

## 当前状态：职责补齐后继交付完成，等待用户批准阶段三（2026-10-05）

用户授权“基本认同。你来主导继续完成阶段二，达成目标”。在`codex/s012-research-resume`完成EX018/EX019，发布EX019 COMPONENTS修订1。登记保持RESEARCHING，阶段二COMPLETE；阶段三未进入。

- [阶段二人工报告](../../experiments/S012/EX019_20261005/04_conclusion.md)、[正式组件面板](../../experiments/S012/EX019_20261005/deliveries/COMPONENTS/1/report.md)、[职责覆盖](../../experiments/S012/EX019_20261005/role_coverage.json)。
- 面板39条研究记录、204事实；按独立定义及支持职责去重6个：2条件机会、3风险/状态、1有边界确认。R01重复汇总风险，确认每父机会测试不另计组件。
- 新确认Q07为目标Close>Open，仅O01主5日有条件支持。79原事件保留30，净均值1.6977%，条件提升0.9192pp；原父固定时间表贡献+0.2308pp、限价贡献+0.1619pp。重新去重17潜在触价，0.6645/60日，触价净均值0.9213%。q=.24、贡献区间跨0、2024/年度及延迟限价反证、容量损失保留。
- N09无推荐强制确认门。同类ETF方向Q05仍为候选，自身符号不一致子组不足；不加算第二个独立确认。风险组件保持原定义；机会内短周期原价上下文支持波动尺度，动量/峰度不能机械成为共同过滤。
- EX018/19共480确认诊断（含重复和敏感性）、12风险上下文，7新增门及20主条件检验，检验数量不等于独立组件。
- [独立复算EX018](materials/confirmation_independent_verification_20261005.json)和[EX019](materials/confirmation_competition_verification_20261005.json)均PASS：90,684及75,168个数值字段，含全部路径、年度、推断、原始输入门和哈希链。
- [交付FULL](materials/confirmation_components_validation_20261005.json)、[两档案核验](materials/confirmation_archives_validation_20261005.json)均PASS。技术PASS与角色支持、用户经济目标分别解释。
- [本轮授权](materials/confirmation_stage2_authorization_20261005.json)。完整账户三个经济目标尚未联合验证；阶段三、来源依赖、DEV、合并和推送各自另行授权。

精确交付：owner=`ExperimentOwner(S012, EX019_20261005)`，stage=`COMPONENTS`，revision=`1`，content_sha256=`d5ed294ec2f3e585c5cd0a56f2dd6b5c08b4531c6e18689d2d59c793c9a65c57`。

阶段二本轮目标已达成：形成明确用途、适用边界、反证与完整台账的后继面板。建议用户审阅并批准阶段三，最小完整账户对照O01有无Q07、N09基础机会和三风险组件的仓位/退出职责，再检验原收益、回撤、频率目标。现有事件和日线触价不是账户达标证据。本轮仅本地提交；完整制品与17实验引用闭包本地保存，跨机器复验须同步被Git忽略的真实制品。

## 上一轮EX017交付与恢复历史


## 当前状态：阶段二汇总交付完成，等待用户决定下一阶段（2026-10-05）

用户授权“以阶段二交付产物为目标，充分利用已有资源，重点挖掘收益机会，请你自主进行研究”。已在`codex/s012-research-resume`完成EX015—EX017，并发布EX017的COMPONENTS修订1。登记保持`RESEARCHING`，意图`COMPONENTS/COMPLETE`；阶段三未进入。

- [阶段二人工汇总](../../experiments/S012/EX017_20261005/04_conclusion.md)、[正式组件面板](../../experiments/S012/EX017_20261005/deliveries/COMPONENTS/1/report.md)、[研究覆盖台账](../../experiments/S012/EX017_20261005/research_coverage.json)。
- 32项组件记录、86项事实，包含旧风险状态、机会、弱线索、冗余和失败反证；32不等于32项有效收益组件。三轮1752次路径比较、64项不同信号定义含对照，次数包含重算和敏感性，不等于独立机制数量。
- 延续原三风险/状态组件及O01，新增“实际VWAP偏离处于历史中段且三日动量为正”的条件性机会候选：298事件，5日净均值0.4956%、价量匹配增量0.1396%、OLS增量0.1705%，各侧0.1%费用。68次限价潜在触价，全1535日容量2.658次/60日，触价净均值0.1216%。q=0.407，双倍费用或延迟两日增量转负；不能解释为已确认独立Alpha。
- O01仍为79事件、36非重叠及21次触价；新全1535日分母容量0.82085次/60日，旧1.10采用1144个有效日，信号和次数保持。与新候选联合79次触价、3.08795次/60日，触价净均值0.0780%。三个完整账户目标尚未验证；容量诊断不能代替闭合交易或实际成交。
- 日内冲击顺序、成交权重、低量冲击、路径效率、tsfresh、同类相对状态、休市、真实VWAP及正常状态均形成竞争检验。真实VWAP旧覆盖描述由EX016补齐；稀疏区间、年度选型失败、1/3日期限反证保留。历史风险指标本轮未重算。
- [自主研究授权](materials/autonomous_stage2_authorization_20261005.json)、[FULL交付核验](materials/autonomous_components_validation_20261005.json)、[三档案核验](materials/autonomous_archives_validation_20261005.json)均留证。交付COMPLETE、FULL及三档案PASS分别表达交付完整度与技术核验，不能代替经济目标。
- [独立复算](materials/autonomous_independent_verification_20261005.json)：1152路径10368数字及EX016四年成熟标签选型一致；[正常状态独立复算](materials/normal_independent_verification_20261005.json)：264路径2376数字、21490信号/有效位一致。完整计算代码位于EX017，正式输入及前驱逐SHA核验。

精确交付：owner=`ExperimentOwner(S012, EX017_20261005)`，stage=`COMPONENTS`，revision=`1`，content_sha256=`76073767078a8ff1a935322cd796ae39f8e83a53996432dcbd0bb2f39ef22632`。

下一步建议：用户审阅后批准阶段三最小完整账户比较，分别验证O01、新正常定价正动量及风险组件职责；保持阶段一修订3三个目标和成本约束。机会仍弱、跨轮选择偏差未消除，若账户中费用或成交消除增量则停止对应方案。新来源/依赖、DEV修改、合并及推送另行授权。当前研究提交仅本地，跨机器复验须同步真实制品与完整S012前驱闭包。

## 恢复与前轮记录：阶段二研究进行中（2026-10-05）

用户明确要求“提交研究员Agent文档。新开分支继续S012的研究工作”。研究员Agent文档已提交为`41c7f25b`，当前分支`codex/s012-research-resume`，登记恢复为`RESEARCHING`。标的518850.SH、阶段一修订3的三个经济目标及全部上市历史开发池保持；采用T日收盘后决策、T+1执行的日频研究口径，未进入阶段三。

- [恢复授权](materials/resume_authorization_20261005.json)、[最小DEV性能修复授权](materials/dev_performance_authorization_20261005.json)。
- EX013全历史正式数据门通过：1535日日线完整率/准确率100%；5分钟完整率100%、准确率1483/1535=96.6124%；30分钟完整率100%、准确率1509/1535=98.3062%。保持DFLS现有容差，52日及26日异常明细保留，不能解释为独立真值修复。
- [数据门报告](../../experiments/S012/EX013_20261005/04_conclusion.md)、[独立重算](materials/resume_data_independent_verification_20261005.json)、[档案核验](materials/resume_data_archive_validation_20261005.json)。
- EX014固定“收盘前相对落后”机制主检验FAIL：8个事件，3日平均净收益0.0355%、年度匹配费用后增量-0.1189%；异常排除后7个事件增量转正，结果敏感。限价触价容量0.1173次/60日；与O01事件不重叠，但3日并集容量仅1.0945次/60日。
- [机制报告](../../experiments/S012/EX014_20261005/04_conclusion.md)、[增量COMPONENTS](../../experiments/S012/EX014_20261005/deliveries/COMPONENTS/1/report.md)、[交付核验](materials/relative_lag_delivery_validation_20261005.json)、[档案核验](materials/relative_lag_archive_validation_20261005.json)。EX010原面板保留，本轮负结果完整留证，未完成账户三个经济目标验证。
- 用户另授权暂切DEV，两处校验局部副本清空attrs以避免pandas逐行/分组重复复制整窗元数据。提交`7a053451`，63项聚焦测试、Ruff及真实日线元数据保持验证通过；未变更价格、容差或质量判据。原未完成执行空间保留，独立新空间重试EX013约101秒完成三请求执行。

当前人工结论和正式增量以EX014为准，既有有效O01组件仍以EX010为准；暂停时EX012的历史阻断结论保持。新分支及本轮提交均在本地，正式数据制品及交付实验副本由Git忽略，跨机器复验需要同步S012真实制品和前驱链。

## 历史暂停记录（2026-10-04）

用户于2026-10-04明确要求“暂停S012，合并到master”。登记状态为`PAUSED`，停止研究和数据排查，等待用户明确恢复。
标的仍为518850.SH，518880.SH仅完成替代可行性的数据诊断，未切换标的、未进入阶段三。
暂停时收口分支为master；既有实验、交付和阶段一合同保持原样。该暂停已由上述2026-10-05恢复授权撤销。

- [暂停授权](materials/pause_authorization_20261004.json)
- [暂停时的数据诊断摘要](materials/pause_data_diagnostics_20261004.json)

EX012之后的DEV补充核验发现：518880在2020-01-02至2026-09-30的1636日数据完整，已有修复后的1/5/30分钟通过现有校验；
进一步检查仍有91日高低价差异、56根1分钟及3根5分钟量价不一致。TDX日线与Tushare原始日线价格一致，未支持本地三个日线修复值；
五个目标日期的TDX分钟导出均为空。通过现有容差校验不代表这些问题已经解决。
补充核验仅为DEV诊断，原始大数据制品留在本机临时目录，不能替代正式研究证据。

## 历史封存增量：全历史日内数据门（EX012）

EX012_20261004的COMPONENTS修订1为BLOCKED，交付FULL核验与EX012档案核验PASS。
完整历史价格修复尚未达成：518850的7日5分钟成交量错误已用1分钟修复，仍有52日价格跨周期冲突；未开展任何日内收益检验。
518880参考ETF全历史73680根/1535日校验通过。原组件面板仍为EX010，不因本轮空增量面板失效。

- [本轮报告](../../experiments/S012/EX012_20261004/04_conclusion.md)
- [交付核验](materials/intraday_data_gate_v2_validation.json)、[档案核验](materials/intraday_archive_v2_validation.json)
- [独立来源探查](materials/independent_source_probe_20261004/summary.json)
- 当前精确交付哈希：68b039e183d50562596cd40ec256ef96c42b8e2fc6accdc86043d4538b88948f。

用户要求先解决全历史数据，再检验收益；已允许独立来源、付费另确认。
免费来源未取得三个代表日分钟数据，富途现有服务缺A股ETF行情权限。用户暂无其他来源，将自行联系Tushare申请修复。
暂停时建议：取得可追溯修订数据或独立分钟证据，再创建后继实验复验完整历史；数据到达不自动恢复研究。2026-10-05用户明确恢复后，按新确认的统计验收口径完成EX013，结果见本文件首节。
EX011执行回执与交付有效，但档案因执行文档文件名不符合契约而失败，原件保留；由EX012补齐可复验归档，不宣称全库档案通过。
该轮DFLS新增未复权分钟和显式市场观察时间假设，30项聚焦测试通过。

## 前轮组件结论（EX010）


本轮机会优先迭代已完成。当前交付为EX010的COMPONENTS修订1，完整度COMPLETE、FULL技术核验PASS。
找到一个有条件的低频机会候选：人民币贬值较强时，ETF三日回调后的约3—5日修复。
保守时间口径下5日净事件均值0.779%、匹配毛增量0.722%；q=0.280。前收盘限价去重容量约1.10次/60日。
原波动、趋势后回撤、冲击集中度仍为风险/状态辅助。当前机会覆盖不足，不建议直接进入阶段三。
阶段一修订3继续有效，三个账户经济目标均未在完整策略中验证；无候选或冻结版本，阶段三尚未授权。

## EX010历史组件面板入口

| 事项 | 入口 |
| --- | --- |
| 当前人工研究报告 | [机会研究结论](../../experiments/S012/EX010_20261004/04_conclusion.md) |
| 当前正式组件报告 | [COMPONENTS修订1](../../experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/report.md) |
| 当前合同与回执 | [delivery.json](../../experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/delivery.json)、[receipt.json](../../experiments/S012/EX010_20261004/deliveries/COMPONENTS/1/receipt.json) |
| 已批准阶段一合同 | [修订3](mandates/3/report.md) |
| 当前注册意图 | [family.json](../registrations/S012/family.json) |
| 阶段二初始授权 | [用户指令](materials/stage2_authorization_20261004.json)、[阶段推进决定](decisions/S012-STAGE2-20261004.json) |
| 本轮继续授权 | [机会优先用户指令](materials/opportunity_authorization_20261004.json) |
| 当前交付验证 | [FULL验证](materials/components_opportunities_v2_validation.json)、[10档案验证](materials/opportunity_archives_validation.json) |
| 当前实现与协议 | [delivery.py](../../experiments/S012/EX010_20261004/delivery.py)、[固定协议](../../experiments/S012/EX010_20261004/02_design.md) |
| 当前机会台账 | [汇率168路径](../../experiments/S012/EX010_20261004/artifacts/rex/fx/opportunities.json)、[境外黄金96路径](../../experiments/S012/EX010_20261004/artifacts/rex/gold/opportunities.json) |
| 反证与容量 | [年度](../../experiments/S012/EX010_20261004/artifacts/rex/fx/annual.json)、[252项敏感性](../../experiments/S012/EX010_20261004/artifacts/rex/fx/sensitivity.json)、[36项限价诊断](../../experiments/S012/EX010_20261004/artifacts/rex/fx/limit_events.json) |
| 旧风险/状态面板 | [EX005结论](../../experiments/S012/EX005_20261004/04_conclusion.md) |

精确引用：owner=ExperimentOwner(S012, EX010_20261004)，stage=COMPONENTS，revision=1，
content_sha256=fdf27e7c93e9f73b0ed6ae9b3b6d77f6e42451b1d0d0bdc18b6140c6bcdff532。

## 时间与证据边界

FXCM源日期可能标记跨日K线起点。EX008的境外黄金强信号被隔离；EX006/007涉汇率结论须以EX010重算为准。
DFLS已增加AvailableDate=源日后2自然日08:00中国时间，明确为保守研究政策，历史逐日发布时间未核实。
旧缓存和旧发布不自动兼容新时间契约；本轮用s012-fx-availability-v2缓存命名空间。
EX009因报价计数快照修订停止，无收益结果；EX010证实全部OHLC与日期不变，计数修订单独保存。
所有已封存实验保持原样；平台PASS不代表时间语义、机会充分性或账户目标达成。

机会研究轮按既有DEV授权修改DFLS时间契约，22项聚焦测试通过。
全部历史为开发池。2020-2021用于年度阈值训练，具体有效日期与标签尾部损失见当前报告。
各实验artifacts及交付实验副本仅在本机，Git不包含完整数据制品；跨机器恢复需同步完整S012前驱链并核验哈希。
2026-10-04暂停收口时仅合并至本地master，当时未推送、未部署。没有配置外部备份目的地。

## 下一步

继续阶段二独立机会来源研究，优先解释能提高限价实际成交密度的经济机制，再预注册可证伪实验；保留EX010的O01及本轮EX014负面证据，停止沿本轮固定机制继续放宽条件。全历史数据已按用户确认的现行DFLS规则通过，异常与实时可得性限制继续披露。
更换研究标的、修改既定目标或进入阶段三仍须取得用户批准。
