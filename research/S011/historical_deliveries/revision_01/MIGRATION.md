# S011 正式阶段交付迁移清单

本清单为RSCH需求评审材料。范围是保持原研究目标、证据和用户决定的可追溯性；平台模块修改尚未实施。本包补全了历史阅读与机器索引，正式`DeliveryReceipt`仍待以下事项闭合。

## 1. 阶段一目标依赖

阶段四`CandidateAssessmentDelivery.source_mandate`要求引用正式阶段一`ResearchMandate`。S011原目标位于研究登记和阶段四协议：收益相对同口径BuyHold、回撤严格小于BuyHold、全样本每60日折算闭合交易4—6笔。先补建目标来源与确认材料，使用原用户要求，不因新平台字段缺失而改换目标。

| 原要求 | 当前公共契约 | 需要评审的具体差异 |
| --- | --- | --- |
| `60 × 闭合交易数 / 完整评价交易日数`在[4,6] | SE `ResearchMetric.FREQUENCY_MEDIAN/FREQUENCY_Q10`、`ResearchTarget`、`ResearchTargets.frequency_window_days` | 当前两个指标统计滚动窗口交易数的分位数。需要显式的全样本标准化频率指标及计算口径；不能将原区间直接绑定到滚动中位数或Q10。 |
| CAGR≥1.5×同口径BuyHold；基准非正时要求策略为正且取得超额 | `ResearchTarget`只有单指标常数上下界 | 需要显式基准比较及条件语义，或评审受证据绑定的门槛物化方案；保留基准身份、实际数值和分支条件。固定开发池门槛不能冒充所有窗口的通用目标。 |
| 回撤幅度严格小于同口径BuyHold | `ResearchTarget`和TDR `NumericRequirement`为包含边界的常数上下界 | 需要表达严格比较和基准引用；不通过任意减去epsilon伪造严格不等式。 |

涉及SE `ResearchMetric/ResearchTarget/ResearchTargets`、`assess_candidates/compare_candidates`及TDR `NumericRequirement/TargetMandateBinding`和交付目标核验。最小修改方案须由DEV评审后实施；RSCH本次仅记录输入输出需求。

## 2. 阶段二：组件证据

原件：EX12 `component_panel.json`、`COMPONENT_PANEL.md`、计算源码及EX10/EX12回执；前序无效路线与技术失败同样保留。

目标：`ComponentPanel`、`ComponentEntry`、`ComponentTestResult`、`ExperimentDefinitionRef`，通过`assemble_delivery/validate_delivery`发布和校验。

当前`assemble_delivery`要求所声明实验使用REX schema 2回执，历史成功实验回执均为schema 1。后继实验须区分“读取并认证历史结论”和“重新计算组件证据”，明确实际操作与证据身份；选择何种方式须先验证公共契约能真实表达它。不得补写旧回执、把历史文件包装成未实际发生的新收益检验，或因此增加独立样本数。

验收：4项组件定义、职责、标签、期限、对照、因果可得性与反证逐项可追溯；EX01—EX12失败及未通过路线继续可读；新交付技术PASS与历史组件判断分别展示。

## 3. 阶段三：身份、搜索与账户证据

原阶段三收口范围为573条可比较评价、559组参数、521种账户行为、26组达标参数、18种达标账户。阶段四的36配置范围包含后续自检过程积累的配置；迁移时须展示扩展来源，不能将两个阶段计数混为一谈。

- 按原实现、参数、执行规则和来源记录创建当前`StrategyCandidate`，以`StrategyRuntime.identify`取得当前内容身份。
- 保留`config_id/config_fingerprint/first_reference/source_root`到新`CandidateKey/content_sha256`的显式映射；原配置指纹不直接填入新版内容哈希字段。源码为满足当前运行契约发生变化时，保留派生理由与前后等价性证据。
- 经TDR `register_candidate`登记拟交接集合，并通过`load_candidate`验证载荷和源码可恢复。
- 在新正式REX执行中，通过`context.evaluation.evaluate`生成真实`EvaluationRecord`及schema 3评价产物。完整评价使用原数据截止、交易规则与显式`lot_size=100`。
- 用`SearchRecord/SearchTrial`保存原Optuna和网格搜索的提议、状态、继承、失败、去重与停止理由；不能伪造新评价ID，也不为迁移重新搜索参数。
- `CandidateSet.handoff`须覆盖已批准迁移的完整阶段四集合。登记与评价不只覆盖621；既有诊断缺口可以继续显式缺失。

验收：登记可读取、身份映射无歧义、评价可认证、搜索计数可核对、原账户与新复算差异有解释；原失败实验和错误预热范围的EX14保持原件。

## 4. 阶段四：计算及排序口径

原件：`iteration_04`的36配置面板、七项比较规则、完整成对说明、分箱敏感性、EX28扰动证据和`closeout_01`用户决定。

| 检查项 | 历史语义 | 当前SE语义／迁移要求 |
| --- | --- | --- |
| 帕累托分层 | 收益和回撤先按明确经济分辨率分箱，再分层 | `compare_candidates`对原始收益和回撤分层；需要评审保留历史政策的显式方案，或由用户确认新排序是后继规则。 |
| 分箱舍入 | `ROUND_HALF_UP` | 当前`BinRounding`提供`FLOOR/HALF_EVEN`；恰在边界时可能不同，须显式保留或由用户确认变更。 |
| 同层缺失 | 按七项顺序逐项比较，较早已知差异可决定先后；遇到缺失则保留该对不可比及可能名次区间 | 当前SE诊断缺失会影响排序资格，未完整表达原成对偏序和名次区间；不得用0补缺、删去配置或将旧名次伪称新API输出。 |
| 标准／压力 | 10bp／20bp完整账户，压力不是任意同名结果 | 新请求标准为`FORMAL/SCREENING`，压力为`STRESS`且费用更高；基准、窗口及公共上下文须一致。 |
| 参数扰动 | 四中心固定2日16位置六参数联合设计；相同参数可在设计位置出现 | 使用真实`PARAMETERS`派生和显式权重，保留位置数、唯一参数数、账户数的区别；其余32配置继续标为缺失。 |
| 统计范围 | 旧Bootstrap和研究族PBO/DSR；不覆盖EX28扩大后的全部历史 | 保持原范围及污染说明，迁移不自动获得扩展统计覆盖或独立性。 |

在目标及排序方案明确后，经`build_assessment_evidence`、`assess_candidates`、`compare_candidates`生成新请求与结果，由`CandidateAssessmentDelivery`及`assemble_delivery/validate_delivery`绑定正式阶段一和阶段三交付。目标、全部36配置范围、缺失状态和解释必须一致。

验收：原目标逐项可判、全36配置不遗漏、32配置联合扰动缺口、000193成本缺口、9对不可比及15配置的不确定名次如实保留。新规则造成的数值或排序变化须单列，旧排序不回写。

## 5. 用户决定与实施顺序

621的历史选择依据、机会成本和反证沿用`closeout_01`。历史`candidate_id=null`及旧候选包/CIO字段保留其原始意义。新流程使用贯穿阶段三至五的`StrategyCandidate`，正式决定通过`record_research_decision`绑定真实用户确认、新交付引用和确切内容身份。

建议顺序：DEV评审目标与排序契约差异 → 确认迁移范围及必要的新执行 → 补齐目标交付和身份映射 → 发布阶段二、三、四正式交付 → 核对621选择记录 → 再推进阶段五技术检验。阶段五、冻结、部署及生产操作保持各自授权边界。

平台补足能力不会自动改变S011的原目标或排序；任何研究规则变化须先获得用户明确确认。

## 6. 历史复核的已知限制

本次原脚本专项执行结果见`focused_validation.json`。EX12旧验证器在最终前序身份检查处失败：其记录的EX01 manifest原始字节哈希为`18a0e08588f67e71187fca687129172e0b389da118cf55696b16fca00f88e884`，当前文件为`9330e462427f79ce4ec7981e256e530c91eed69beaaa3bf83b6289ea986107a4`。此差异不能由换行解释，原因尚待追溯；EX01当前档案自身及REX回执的公共验证均通过。保留原记录，不重新签署它来消除差异。

iteration_04与closeout原验证器引用当前`research/RSCH_AGENT.md`而失败，原输入要求的哈希与iteration_04已封存的`inputs/RSCH_AGENT.md`完全一致。本次补充核验明确声明该历史引用映射，原脚本执行结果仍保持FAIL。此映射仅用于核验当年的合同文本，不替换当前研究规则。
