# EX004：S013后复权阶段三研究与阶段四自检

本工作区组织获批的阶段三重跑、新增约束复核及续研，以及2026-10-08获批的阶段四。当前结论见[阶段四ASSESSMENT/1](../../../deliveries/ASSESSMENT/1/report.md)；[阶段三修订三](../../../deliveries/CANDIDATES/3/report.md)、旧[修订二](../../../deliveries/CANDIDATES/2/report.md)与[原阶段三交付](../../../deliveries/CANDIDATES/1/report.md)保持原件；工作文件不替代交付与正式证据。

## 结果与口径

旧378个不同配置原三项目标下六个达标；新增“BuyHold亏损年份策略须盈利”后均不通过。用户批准继续阶段三，本次新增116个完整账户配置，累计494成功，历史16次UNKNOWN保留；四项同时达标10个，全部交接，七个前沿/反证一并保留。CANDIDATES/3的FULL校验及17份正式账本独立复算均PASS。阶段四已对全部10个中心完成五项自检与比较；80个联合扰动和10个双成本请求全部成功，标准中心资格保留，扰动0/80达标。ASSESSMENT/1 FULL PASS，建议暂缓阶段五，待用户决定。MANDATE/5仅修订既定约定的类型表示，四项经济要求保持。

`review_negative_benchmark_years.py`从已发布统计复核378个成功配置，并从14份正式完整账本独立复算年度收益；核对严格大于零与基准零收益不触发边界。本次没有刷新数据或新增策略评价。新计算证据、用户原文和旧交付引用均随修订关联；旧统计及旧判定保持原件。

价格采用HFQ_RESEARCH，锚点2019-12-31、因子0.2803；100个研究单位整手、100万元、单侧10bp。BuyHold同价格单位和同一连续账户。原始网格形成T日限价后转换研究价格，T+1历史撮合；计划不读取T+1开盘或因子。PTE真实份额与未复权价格边界保持。

## 实际执行与复算入口

- `economics_r4.py`单独应用新增严格盈利条件，年度实际净收益沿用连续账户；`search_results_r4.json`保存新判定与本次搜索，旧统计原件不改。
- `four_gate_*_plan.json`在各轮评价前发布；两种固定队列执行器以Optuna管理，最多4个spawn进程、每个原生线程1、单请求1，每个Python父进程只评价一批。原策略由`fixed_search_r4.py`运行，状态组合由`fixed_search_adaptive.py`运行；相同配置复用。
- `adaptive_range/strategy_runtime/strategies/`保存独立组合实现和360日原区间实现字节副本。动量只选择入场路线、锁定至退出，可在状态变化时退出；不按年份路由。`adaptive_synthetic_precheck.py`检查未来隔离、相同路线、锁定/退出及14个非法参数；`check_adaptive_controls.py`比较三个FULL同路线账户。
- `check_adaptive_input_control.py`使用公共DFLS fetch，验真C0439/C0440所有准备输入，包括180条2019预热。`analyse_adaptive_attribution.py`按实际每日权益对账价格与费用贡献，保留2023余量、2024集中及退出政策不一致反证；正式复现以交付中关联的实际源码快照与哈希为准。
- `analyse_four_gate_search.py`保留全部10个达标和可行前沿/反证；`quality_audit_r4.py`核对494个成功配置在已声明分钟异常日期的实际订单。`four_gate_stopping_review.md`给出机制、扩边饱和和转入标准自检的依据。
- `deliver_four_gate_search.py`包含公共治理写入，保存控制两侧完整账户，登记达标/必要配置及发布CANDIDATES/3。现有交付不可覆盖；未来结论另立修订。`verify_four_gate_delivery.py`从正式账户独立重算17个保留配置，核对全部四门与交接完整性。
- 本次过程状态位于`.tmp/s013-negative-years/`，完整结果缓存沿用`.tmp/s013-stage3-hfq/`；原缓存和工作材料不能代替正式证据、登记源码、DFLS资产及准备引用。

- `bootstrap.py`保存初始协议、约定修订及基线。它包含正式写入，不能作为普通复算脚本直接重复运行。旧EX003及旧基线发布证据不可改写。
- `replay_plan.json`固定旧270个成功配置，`fixed_search.py`以Optuna固定队列和配置哈希去重组织完整账户评价；四轮`hfq_followup_*_plan.json`在各轮评价前发布。计划重复点复用同口径结果。
- 两次Windows多进程句柄失败保留16次UNKNOWN；`replay_completion_plan.json`和`replay_recovery4_plan.json`显式记录重试与未执行项。`all_replay_comparisons.json`证明旧270个配置完整覆盖，UNKNOWN原状态未改写。
- `strategy_runtime/strategies/range_reversion.py`沿用旧策略字节；`extended_window/strategy_runtime/strategies/range_reversion.py`仅将暂定窗口上限180扩至360，以检验240/360日。正式保留候选均有源快照和依赖身份。
- `analyse_search.py`重算组统计、价格口径对照和阶段三前沿；`economics.py`从连续账本计算净年化、逐自然年回撤和实际闭合交易次数；`quality_audit.py`核验已声明行情异常是否影响实际成交金额。
- `deliver_stage3.py`通过公共API保存14个账户证据、登记候选和组装交付；包含治理写入，已有交付保持不可变。新增结论使用新修订与新引用，不能直接覆盖原交付。
- 过程缓存与Optuna研究状态位于仓库`.tmp/s013-stage3-hfq/`，不作为正式复现的唯一输入。正式交付中关联的源码材料、参数、账本、身份与数据准备引用支持已交接候选复算。恢复后通过TDR公共评价入口从登记候选及原准备引用重建输入，而非读取缺失缓存并降级。

## 平台修正与保存边界

DEV提交`9caede79`补齐研究价格契约；`3a8ab3a7`补齐独立审计。后者在候选登记时发现：审计按固定研究网格核验，而实际执行先在原始网格取整再转换研究价格。新审计证据增加原始收盘和每日尺度，原始请求、信号、成交、费用、权益与结果哈希保持；旧基线证据原件保留并关联修正说明。

正式结果的数据资产位于本批次`assets/data/`，Git不包含DFLS资产。需连同登记记录、正式证据和交付保存数据空间；仅复制Git或交付目录不能恢复行情。整个开发池已用于研究和参数选择，阶段四已完成但没有独立保留样本，研究单位收益不能直接等同真实份额PTE收益。具体执行及复算入口见[阶段四说明](stage4/README.md)。
