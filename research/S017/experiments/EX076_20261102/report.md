# EX076：按用户最新指令暂停，保留结果与显式恢复清单

用户先批准按统一Calmar约定恢复阶段四，随后明确要求“完成当前进程的计算任务后请先暂停”。当前原邻点进程池已因技术故障退出，16既有账户两路数值验收已完成，已核实无运行中的自检进程。控制已设pause_requested=true；未启动独立进程恢复探针或任何新批次，保持暂停等待下一步指令。

## 做了哪些尝试

本次恢复沿用MANDATE/8、原prospective完整2829点及真实边界，最多12批并发、每进程1线程。252旧点保留，其中108点完成冷读复核；192个新点完成回放、认证、发布及批次收尾。检查点另有两批共8份发布回执，尚未完成恢复收尾，未混入192点计数。其余在途缓存及未派单点均保留，不重置N或自动重试。

原ProcessPoolExecutor工作进程回收时，在multiprocessing.Queue._sem.release报告WinError 6无效句柄，进而BrokenProcessPool。调度明确失败并停派单；没有证明内存不足，也没有确认其与公开Python相近问题属于同一根因。RSCH已核对旧进程退出、全部在途文件、断点存在和实现身份；原故障状态及11份未收尾工作JSON按SHA归档，已完成结果保持原位。

显式v3恢复清单覆盖全部剩余点。新研究编排改用每批一个独立Popen进程，保留最多12批、48GiB进程树预算、至少16GiB可用内存和35%批峰值余量；现存断点只用公开RESUME，不匹配时明确失败，不回退CREATE。该脚本仅通过Ruff及AST静态检查，真实恢复尚未验收。按最新暂停指令没有启动探针或全队列。

## 有哪些收获

RSCH提出逐点绩效事实的完整聚合需求，DEV在SE新增强类型纯数值输入，复用v8计算和v6排序，本地提交ed75fda1d。281项单进程SE聚焦检查、Ruff和差异空白检查通过，未执行全仓回归。RSCH复用六标准、六压力、四邻点共16个已发布账户，原账与绩效输入两路的全部数值行、分位数、覆盖、目标判定及比较一致，标准投影与真实来源准备一致；认证18份唯一账本，零新研究回放。

新面板明确标为PERFORMANCE_PROJECTION，不宣称该输入调用重新执行所有原账TDR FULL审计；该类型尚未整合原全账CandidateAssessmentDelivery/FULL。正式ASSESSMENT交付未发布，完整N尚未齐备，当前没有六配置最终排名或策略通过结论。RSCH制定并最终核验用户确认的硬门，平台按显式事实和规则计算。当前无独立净年化收益门，旧annual joint_pass和压力年化失败仅属于旧规则历史。

## 下一步建议

当前保持暂停。用户明确恢复后，先用单批验证公开RESUME能复用4个已算结果和4份发布，再按资源约定恢复剩余完整点集；全部N齐备后才计算完整分位数和平台排序，RSCH独立核验研究条件。2026封存价格及绩效未读取，未新搜、冻结、部署、合并或推送。

## 有什么依据

[暂停状态](others/calmar_v3_pause_state.json)、[实时控制](others/neighborhood_execution_v2_control.json)、[故障清点](others/calmar_v2_pool_failure_inventory.json)、[恢复清单](others/calmar_v3_recovery_manifest.json)、[DEV聚焦验证](others/complete_numeric_aggregation_dev_completion.json)、[RSCH真实账户等价验收](others/complete_numeric_aggregation_rsch_acceptance.json)、[现行Calmar规则](protocols/confirmed_calmar_selfcheck_v2.json)。原账、历史失败、原计划及旧交付保留，assets中的正式依赖须与Git材料共同保存。
