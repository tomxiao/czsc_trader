# C9380 阶段四交付接口缺口：RSCH只读评估

状态：需求评估完成，未修改平台、未重跑策略账户。用户已授权RSCH继续阶段四；本文件不构成切换DEV或跨角色修改授权。

## 结论

当前已批准的C9380点集可以由公开参数设计、执行计划及SE自检接口承载，81个策略账户和2份共享买持已有真实证据。当前正式ASSESSMENT/schema15交付的阻断点是Calmar比较合同仍强制所有参数轴都是连续实数，不能表示本次合法整数轴及固定类别轴。

未找到能够保持既定点集、参数类型、Calmar/v8-v6口径而绕过该限制的其他公开完整ASSESSMENT路径。不能将整数改写为实数、删除固定轴、改变旧计划/点绑定、降为净年化排序，或伪造Comparison结果来取得形式上的交付通过。单候选也会遍历同一合同检查，并无单候选豁免分支。

研究族统计的内嵌限制是另一项接口能力缺口，但它不阻断独立公开统计及报告。它与上述正式交付阻断应分开处理。

## A．阻断正式交付：混合类型参数轴

调用链为：

`CalmarComparisonRequest.validate → DeclaredPointSetComparisonContract.authenticate → CommonNeighborhoodComparisonContract._scale_signature`。

[research_models.py](../../../../packages/strategy_evaluator/src/strategy_evaluator/research_models.py)第1495行起逐轴要求`type(axis.domain) is RealDomain and axis.domain.quantum is None`，随后要求`BoundedLocalStep`。C9380的真实设计包含：

- 1个可扰动整数轴`beta_window`：40→39/41，合法步长1日、相对2.5%。
- 4个固定短整数轴：`entry_days=2`、`earliest_add=3`、`review_after=3`、`max_hold=5`，最近合法整数变化超过5%，按规则固定。
- 1个固定类别轴`add_mode=repair_both`，规则为不改变类别的`ExplicitValues`。
- 7个连续实数轴，其中满仓预算只有向下合法方向，SOXX零中心门槛有事前声明的绝对尺度0.0005。

现有参数构造器正确保留了全部13轴、适用性、域和原点索引；错误位于比较合同接入能力，不是点集无效或策略自检失败。

其他公开路径的边界：

- `CandidateComparisonRequest`明确拒绝ranking-v5/v6，不能拿它包装当前Calmar排序。
- `CalmarComparisonRequest`要求每个中心都有完整声明设计，并对单候选也执行轴合同检查。
- 普通`CandidateAssessmentRequest`可承载完整账本，但仍不能绕过后续同一Calmar比较合同。
- [delivery_service.py](../../../../src/czsc_trader/application/delivery_service.py)第473行起约束：声明点集必须使用schema15；schema15必须使用`CandidatePerformanceAssessmentRequest`。切换schema14不能保留当前声明点集合同。
- 单独的目标数值检查或研究报告可呈现真实结果，但不能替代强类型`CandidateAssessmentDelivery`中的正式比较请求与结果。PARTIAL交付也不能凭空省去这些必填字段。

### 最小DEV修改需求

在现有比较合同中支持已被参数设计器正确处理的混合局部轴，优先复用原适用性/域/步长事实，不另加接口、不重造点集、不产生隐式认证或账户重算：

1. 连续`RealDomain`无quantum的现有相对/零中心绝对尺度检查保持原行为。
2. 对`IntegerDomain + BoundedLocalStep`，按真实整数域、step、origin、单位和已声明相对/绝对上限验证；允许适用整数和两侧均超限而固定的整数。禁止分数日和把整数改成实数。
3. 对局部研究中固定的`CategoricalDomain + ExplicitValues`，仅在所有声明值等于中心、不发生结构变化时接受；变化类别仍拒绝。不得将类别轴当作连续尺度处理。
4. 语义签名必须保留轴名称、真实kind/domain/unit/payload路径以及必要的固定类别语义；多候选比较不能把不同类别、不同步长或不同含义当作相同空间。源码、映射/可行性哈希、构造合同、点集索引和结果上下文绑定保持。
5. `DeclaredPointSetComparisonContract`与完整邻域合同共用同一明确尺度验证能力，但仍保留完整/声明点集的差别，不把79点声明集合标成4373点全邻域完成。

本次最小范围不要求顺带支持所有有序、数值集合、带quantum实数域等其他种类；未支持类型须继续清晰拒绝，不能兜底接受。若扩展这些类型，应作为独立范围评审。

### 影响与聚焦验证

影响集中于SE比较合同及其测试；不应修改C9380定义、13轴原计划、点索引、账户、DFLS、SRT或执行成本，不需要重新运行83个账户。

- 现有纯连续S017式点集的序列化、比较结果及拒绝边界保持不变。
- 混合13轴的单候选、79点声明集合成功构造并产生既定Calmar比较，79有效点、65最低通过数、79实际联合通过及全点绝对回撤门逐项一致。
- 可扰动整数40±1、20±1恰5%、固定3±1超5%、整数非1步长及单侧业务边界分别覆盖；拒绝分数值、超限变化和伪造域。
- 固定类别可接受，改变类别拒绝；不同候选固定类别或步长不一致不能悄悄可比。
- 错误零中心尺度、构造hash、源点索引、点集/面板上下文或参数payload仍拒绝。
- 使用已保存请求/面板做schema15聚焦发布和INTEGRITY校验；用监测断言确认发布不会重算SE面板或策略账户，仍不宣称FULL历史认证。
- 当前SE面板已保存在[panel.json](../../experiments/EX065_20261104/others/panel.json)，比较限制及真实执行状态分别在[comparison_blocker.json](../../experiments/EX065_20261104/others/comparison_blocker.json)和[assessment_execution.json](../../experiments/EX065_20261104/others/assessment_execution.json)。初次比较构造失败时未保存面板，随后在比较前显式保存面板和请求，统计结果已可复用；全部过程新增账户回放为0。请求将作为正式材料发布并在EX065保留引用。修复后只执行比较/交付，不重复账户或bootstrap计算。

## B．非阻断补充项：研究族收益矩阵与紧凑自检输入

[performance_assessment.py](../../../../packages/strategy_evaluator/src/strategy_evaluator/performance_assessment.py)第96行要求`baseline_request.evidence`只含中心账户，且不得带邻点绑定；参数邻点使用紧凑`ParameterPerformanceEvidence`。

而[research_assessment.py](../../../../packages/strategy_evaluator/src/strategy_evaluator/research_assessment.py)第145行起的`_family`要求研究族收益矩阵的每一列都在`request.evidence`中有同窗口/场景的真实账户证据，逐日收益完全一致，并且全族context、metric_version、scenario_context相同。因完整研究族包括非中心搜索配置，当前紧凑输入无法同时满足两者。

这不意味着收益矩阵不存在，也不要求只用C9380或493个赢家冒充研究族。可继续使用公开`cscv_pbo`、`effective_trial_count`、`calculate_dsr_bundle`等独立统计接口，保持真实候选、同口径群组、全部失败者和资料限制，将结果作为RSCH补充证据附入报告。不要把这些外部结果手写进SE内嵌诊断字段；内嵌未提供应如实保留。PBO/DSR的Sharpe统计与本研究Calmar选择目标不相同，亦须声明。

若以后需要将完整族统计原生纳入schema15，可另立强类型族收益证据/统计输入，或允许独立的非中心族账户证据容器；仍需显式来源、日历与语义一致性，不应取消验证或迫使紧凑邻点接口重新常驻全族账本。这是后续提效与表达能力需求，不是本次解除混合参数轴交付阻断的必要前置。

## RSCH当前可交付状态

可以交付真实的参数、费用、时间、集中性和统计诊断报告，并区分数值结论、证据充分性和接口阻断；不能把平台无法构造正式比较请求表述成策略经济失败，也不能宣布完整ASSESSMENT已发布。建议由用户决定是否切换DEV实施A项最小修复；B项可保留独立统计证据，不捆绑扩大平台改动范围。
