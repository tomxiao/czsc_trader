# EX042：退出机制对照的技术失败收口

Status: FAILED；RSCH；技术失败，研究轮扣减0。

本实验计划19个退出机制配置，尚未形成有效策略账户或买持账户。C0622—C0640的原定义、策略源码与执行记录保留，经济结论尚未形成。既有10轮额度仍已用4轮、剩6轮；本次批准的6轮完整保留。

## 执行事实

|执行事件|账户计算|记录结果|预算影响|
|---|---|---|---|
|第一次池执行|提交4项任务|4 UNKNOWN；策略0、买持0|0研究轮|
|第一次恢复的容器比较|在results.manifest相等断言处停止|tuple/list表示差异，尚未启动新账户计算|0研究轮|
|规范化后第二次池执行|提交4项任务|4 UNKNOWN；策略0、买持0|0研究轮|

两次真实池执行均返回BrokenProcessPool，合计8项UNKNOWN按原状态留存。已记录成功回放为0；统计完整性为False。两段执行记录累计34.119851秒，容器比较及后续诊断另计。资源均为12账户进程、各1原生线程。详见[执行记录](others/attempts.json)、[原始结果](others/results.json)、[第一次池执行](others/failure_pool_attempt1.md)、[容器比较失败](others/failure_container_comparison.md)及[第二次池执行](others/failure_pool_attempt2.md)。

## 已复现的阻断原因

策略返回7个周期状态字段，原定义从C0355继承5字段声明，遗漏`risk_fraction`与`breach_count`。独立调用公开`StrategyStateSchema.validate_record`，原声明确定报出`state fields differ from declared cycle schema`。在内存中补充float风险乘数及int连续穿越计数后，同一7字段记录验证PASS；该检查新增账户0，原实验声明与源码保持原值。

策略在入场信号成立时就会返回完整周期状态，此处已构成账户推进的确定阻断。两次池日志暴露的是BrokenProcessPool/UNKNOWN，原工作器异常栈未透出，具体映射保留这一证据限制。[EX005历史记录](../EX005_20261110/report.md)已记载策略ReplayFailure在并行执行中的未知结果呈现，供平台问题后续追踪。两组独立12进程依赖与数值运算检查均完成，见[检查一](others/pool_smoke_before.md)、[检查二](others/pool_smoke_after.md)及[检查源码](others/pool_worker_diagnostic_source.txt)。

源、19个定义、请求清单、两版runner及日志的哈希绑定与公开接口复现结果见[技术诊断](others/technical_failure_diagnosis.json)。此前容器规范化恢复仅调整表示和诊断记录，其原件及合同不变核对见[恢复修订](protocols/technical_recovery_amendment.json)。

## 修正路线与研究目标

按主方决定，将同一19配置机制方案承接至EX043，使用新身份C0641—C0659及完整7字段声明；策略金融逻辑、参数、原数据样本和费用合同保持。新实验先核对状态声明与实际返回，再以三条hard控制执行完整经济parity，验证相对C0355及其ATR上下5%账户的经济一致性，通过后开展机制对照。EX042在此关闭，成功机制实验仍待新实验完成。

原目标NAR≥55%、Calmar≥5、MDD与双频率门槛，以及正式邻域通过率≥80%均保持。本次只发布技术失败实验报告，阶段交付和研究额度均保持原状态。原方案见[机制计划](protocols/plan.md)、[19配置](protocols/specs.json)及[准备请求](protocols/prepared_request_manifest.json)。
