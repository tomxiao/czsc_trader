# 策略评估器（SE）

SE按显式协议提供指标、协议校验、比较、帕累托分层、PBO、DSR、Bootstrap、参数邻域、压力及账本审计计算。先阅读[公共导出](src/strategy_evaluator/__init__.py)，再沿导入核对契约与测试。

`strategy_evaluator.equity.audit_equity_account` 独立审计区间成交、整数股持仓、分红应收款和交收，
输出交易日指标及区间采样回撤；不导入 SRT/TXE。其研究证据与正式阶段交付的边界见
[TDR美股研究接口](../../src/czsc_trader/README.md#us-equity-research)。

账户会计分解使用`diagnose_account_replays`纯计算入口，输入为认证后的`ReplayEvidence`、评价身份、诊断起止日期及可选对照；返回`AccountDiagnosisCalculation`。它不读取文件、不执行策略，也不寻找分类或解释金融机制。RSCH使用TDR的`diagnose_accounts`完成正式证据认证及人群覆盖适配；金额、单位、首版支持范围及发布示例见[TDR账户诊断](../../src/czsc_trader/README.md#账户损益与路径诊断)。账本差异等价性仍使用`compare_ledgers`，不被路径诊断替代。

研究员通过TDR受管评价API取得SRT/TXE账户事实，再组合SE公共函数。SE不获取行情、不加载策略、不写治理状态。旧资格裁定、冻结健康政策、自动冻结建议及对应报告入口已删除。

`audit_replay`对`signal_cash_fraction / entry_cycle`额外执行`ENTRY_CYCLE_ALLOCATION`检查，独立核对信号比例、
开仓现金预算、整手目标、周期内不变性、后续补买数量与剩余预算、成交含费累计和退出后的状态释放。
检查消费正式决策/账户账本中的周期事实，不调用SRT规划器或TXE执行器；外层哈希重新计算也不能使不一致周期事实通过。
动态周期的历史回放限定LIMIT买入，按照配置费用核对成交不超过剩余预算；这与PTE保存渠道实际异常费用事实的通路分别处理。
当前`diagnose_account_replays`的全仓/现金分解不支持动态周期分配，明确返回`UNSUPPORTED`，不将其解释成固定100%资金策略。

阶段四使用`assess_candidates`和`compare_candidates`，输入与输出均为强类型不可变记录。
`validate_protocol`、`screen_candidates`、`rank_candidates`保留既有协议计算语义；新阶段交付
按下述研究契约进行复算。统计风险标签不等于冻结决定或未来成功概率。

平台校验结构、计算和证据一致性，研究员解释与推荐，用户决定选型；检验和获批冻结使用
[TDR入口](../../src/czsc_trader/README.md#8-技术检验用户决定与冻结)。

## 当前协议与计算入口

`EvaluationProtocol.standard_version`使用`opc-v3`，公共标准常量为`OPC_V3`；
`resolve_margins`拒绝其他标准版本。各计算入口按其显式版本和强类型合同校验证据。
历史产物原件保持不变；本次明确保留的v5自检和旧球面计划只读认证见下节，不推及其他旧格式。

工程压力审计的必需场景由`required_stress_scenarios()`返回：
`total_cost_15bp/total_cost_20bp/total_cost_30bp/total_cost_50bp`。
`audit_stress_results`缺少任一必需场景时返回`INSUFFICIENT`，旧别名不能替代。
新阶段四自检按`NeighborhoodSelfCheckProtocol`显式指定标准和压力场景，研究员负责确定研究口径。

## 候选自检与比较

| 公共API | 输入 | 输出 |
| --- | --- | --- |
| `assess_candidates(request)` | `CandidateAssessmentRequest` | `AssessmentPanel` |
| `compare_candidates(request)` | `CandidateComparisonRequest` | `CandidateComparison` |

全部类型和函数从`strategy_evaluator`顶层导入。TDR的
`build_assessment_evidence(EvaluationRequest, EvaluationResult)`先认证受管评价，再适配为
`AssessmentEvidence`。SE只计算传入事实，不读取仓库、调度搜索或代替执行证据认证。

`AssessmentEvidence.scenario_context`必须使用`EvaluationScenarioContext`，字段为
`one_way_cost: float`、`measurement_tier: str`、`benchmark_id: str`、`benchmark_kind: str`
及`benchmark_contract_sha256: str`。后者绑定基准执行策略、参数和执行语义版本，须为合法SHA-256。
费率须有限且满足`0 <= one_way_cost < 1`，名称字段须非空；由TDR从实际评价请求提取，
相同场景名称不能代替实际口径一致性。

`CandidateAssessment.baseline_scenario/stress_scenario`保留标准／压力场景的强类型口径；
证据缺失时相应字段可为`None`，缺少场景口径的诊断不能标为可用。标准候选之间比较同时核对
公共上下文、指标版本、频率窗口和两类场景口径；不一致返回`INCOMPARABLE`及
`EVALUATION_CONTEXTS_DIFFER`。参数邻域要求与中心标准场景一致；研究族收益矩阵要求成员的
标准场景一致。标准与压力场景按角色校验：标准层级为`FORMAL/SCREENING`，压力层级为
`STRESS`且费用严格高于标准场景；基准ID、基准类型、基准合同哈希、指标版本和公共上下文须一致。
这项角色差异仅用于标准／压力配对，候选之间及参数邻域之间仍要求场景口径严格一致。
TDR允许研究员自由定义成本评价场景，包括单场景及零成本对照；上述配对要求只约束采用该诊断的
证据可比性。费用必须来自显式评价合同，场景名称不承担费率计算语义。

`CandidateAssessmentRequest`显式指定中心候选、账户／成交／基准证据、参数扰动关系、
未完成评价和`NeighborhoodSelfCheckProtocol`。协议指定场景、窗口、覆盖、分位数算法、Bootstrap种子及
容差。参数邻域仅接纳真实`PARAMETERS`派生；缺失或不可比诊断保留状态和原因，失败与取消
尝试保留记录，不填零或静默丢弃。主要结果包括净年化、回撤、已完成交易周期及频率、配对
滚动超额收益、利润集中度、压力损失和参数退化；置信区间及家族PBO/DSR作为诊断报告。

### 自检指标口径

以下为[RSCH阶段四](../../research/RSCH_AGENT.md#44-阶段四自检比较并支持选型)使用的指标定义；研究员解释适用条件，SE计算显式协议中的事实。

以标准净年化、最大回撤幅度和原交易频率为基准绩效，完成以下五项自检。

| 自检项 | 主要问题 | 主指标定义 |
| --- | --- | --- |
| 参数敏感性 | 参数变化后，绩效退化多少 | 联合扰动年化退化=`max(0, 中心净年化 - 联合扰动净年化Q10)`；联合扰动回撤恶化=`max(0, 联合扰动回撤幅度Q90 - 中心回撤幅度)` |
| 时间稳定性 | 相对优势是否随时段变化 | 滚动超额收益Q10：同窗口策略与同口径基准累计收益差的Q10 |
| 收益集中性 | 收益是否依赖少数交易 | 最大盈利交易贡献比例：盈利闭合交易中前`ceil(0.1 × 盈利交易数)`笔净损益／全部正净损益；无盈利时不适用 |
| 执行敏感性 | 成本与执行条件变化造成多少损失 | 指定压力场景年化损失=`标准净年化 - 压力净年化`，保留负值 |
| 统计不确定性 | 样本和反复搜索如何影响结论可信度 | 配置超额收益区间及研究族选择偏差，按方法适用条件解释 |

五项默认按独立因素评估：参数项仅使用基准窗口、标准费用的中心和联合扰动点；费用压力项仅使用中心。
时间滚动、收益集中性和收益区间复用中心标准账本，滚动及重抽样不触发账户重算。
SE使用显式协议，不自动扩展窗口、压力档位或参数点组合；研究族选择偏差每份评价计算一次。
阶段四收益区间内部只计算CAGR重抽样，保持原有分块、随机调用、种子及分位数口径；
公开`paired_stationary_bootstrap`仍返回CAGR、最大回撤和Calmar全部指标。
同次评价的两种DSR共享相关矩阵和公共统计计算，失败仍分别报告状态和原因，指标公式及版本不变。

`effective_trial_count`通过收益相关矩阵的特征值估算有效试验数；原生计算库的线程数变化
可能使该值及`DSR_EFFECTIVE`出现浮点尾差，固定协议与种子不保证跨线程配置逐位相同。
SE保留原始计算结果，不统一舍入或强制线程数。受管交付的复算比较由
[TDR交付API](../../src/czsc_trader/README.md#7-五阶段交付)负责，仅对`DSR_EFFECTIVE`
应用`rel_tol=1e-12`、`abs_tol=0.0`；其余自检字段及候选比较结果仍精确核验。

### 参数扰动

参数邻域与账户评价分开。RSCH事前声明有效参数的自然尺度、精确类型、合法域、局部取值规则、
载荷路径及纯参数约束；SE展开完整联合点集，TDR把每个具名点绑定到实际策略载荷。
不再使用通用半径或固定点数，也不根据账户收益筛选点。

`ParameterAxis(name, center, domain, rule, payload_path, unit)`描述一个有效参数。
`payload_path`是相对于策略载荷`parameters`的非空字符串元组，路径不得重复或互为父子；
`unit`说明业务单位。五类参数及其合法域如下：

| 参数类别 | 合法域 | 局部规则 |
| --- | --- | --- |
| REAL | `RealDomain`的有限上下界、开闭边界及可选`quantum/origin`，或`RealSetDomain`精确值集 | 局部自检使用`BoundedLocalStep`；值必须为float |
| INTEGER | `IntegerDomain(lower, upper, step, origin)`或`IntegerSetDomain` | 局部自检使用`BoundedLocalStep`；bool不能冒充int |
| ORDINAL | `OrdinalDomain(levels)`，同型标签按声明顺序排列 | 局部自检使用`BoundedLocalStep`及显式尺度 |
| CATEGORICAL | `CategoricalDomain(values)`，非空字符串集合 | `ExplicitValues` |
| BOOLEAN | `BooleanDomain()` | `ExplicitValues`，值必须为bool |

类别只描述值的性质；单位、用途、合法域和邻域规则独立表达。新增类型、规则或设计方法须扩展具体强类型并显式校验版本，不以任意字典或`CUSTOM`兜底。当前不支持条件激活表达式；生效参数集发生变化时另立结构对照。

当前局部方法为`parameter-cartesian-neighborhood-v2`。`BoundedLocalStep`接收
`RelativeChangeLimit(fraction)`或`AbsoluteChangeLimit(amount)`，均为显式正有限float；相对限额
按非零中心绝对值计算，零中心须使用绝对限额。连续实数尝试限额端点；整数、量化实数、数值集合
从合法域取得最近合法变化，按精确十进制数值比较是否超限，等于上限允许。按方向分别判定，可保留单侧。
数值有序参数按标签数值差计算变化；字符串有序参数须显式使用按等级步数计的绝对限额，
不将字符串等级编号当作百分比。研究员负责数值标签与业务尺度的对应关系。
连续实数的精确合法端点转换成float后若因表示误差越过变化上限，取朝中心方向相邻的可表示值，
再核对合法域及原上限；这不放宽限额，也不把整数或量化参数的超限步长裁成合法点。
`NumericOffsets/AdjacentLevels/ExplicitValues`仍服务于结构对照和历史读取，不能绕过当前局部限幅。

每轴隐式包含中心。`build_parameter_neighborhood_design`展开全部轴的笛卡尔积，剔除中心、
越域、重复及纯约束不成立的组合；拒绝原因与组合数留证，合法点全部保留并等权。
不裁剪、不四舍五入、不随机抽样、不截取成功前缀；超过`max_combinations`直接返回
`DESIGN_FAILED / COMBINATION_LIMIT_EXCEEDED`，不调用约束或返回部分设计。
完整核验后无合法非中心点时，局部设计返回`NOT_APPLICABLE`，保留非空设计对象及空点集；不等于稳健性通过。
参数和上下文错误仍拒绝，资源超限或中心不满足约束仍为`DESIGN_FAILED`。连续域中存在较小合法变化、
但给定的两个端点均越域时，须改用明确的较小限额，不能据此声称最小合法变化超限，也不自动裁剪。

```python
from strategy_evaluator import (
    ParameterAxis, IntegerDomain, RealDomain, BoundedLocalStep, RelativeChangeLimit,
    ParameterNeighborhoodSpace, ParameterNeighborhoodProtocol,
    ParameterNeighborhoodRequest, ParameterDesignStatus,
    build_parameter_neighborhood_design,
)

# center为AssessmentCandidate；两个哈希来自事前发布的映射和纯约束材料。
space = ParameterNeighborhoodSpace(
    axes=(
        ParameterAxis("lookback", 3, IntegerDomain(2, 10), BoundedLocalStep(RelativeChangeLimit(0.05)),
                      ("lookback",), "sessions"),
        ParameterAxis("hold", 3, IntegerDomain(1, 30), BoundedLocalStep(RelativeChangeLimit(0.05)),
                      ("hold",), "sessions"),
        ParameterAxis("allocation", 1.0, RealDomain(0.0, 1.0, lower_closed=False),
                      BoundedLocalStep(RelativeChangeLimit(0.05)), ("allocation",), "cash_fraction"),
    ),
    mapping_sha256=mapping_source_sha256,
    feasibility_sha256=constraint_source_sha256,
)
result = build_parameter_neighborhood_design(
    ParameterNeighborhoodRequest(center, ParameterNeighborhoodProtocol(), space),
    feasibility=lambda named_values: True,
)
if result.status is ParameterDesignStatus.COMPLETE:
    # 两个3日参数的最小变化为33.3%，保持中心；仅投入比例变为0.95。
    assert result.design.point_count == 1
    point_binding = result.design.bind_point(0)
```

`ParameterNeighborhoodPoint.values`与`ParameterNeighborhoodBinding.values`保存
`NamedParameterValue(name, value)`元组；名字顺序与轴一致，精确保留float/int/str/bool类型。
设计包含完整点集、组合计数及拒绝原因，`N = design.point_count`在评价前固定。
纯约束排除点逐一保存在`constraint_exclusions: tuple[NeighborhoodConstraintExclusion, ...]`。
反序列化时重枚举域内组合，核对保留点与排除点的完整分区；只删除点并调整拒绝计数不能通过。
约束回调必须返回真正的bool；源码哈希不能证明其未使用收益筛选，研究员仍须说明纯度。
`design.axis_applicability`返回按序的强类型逐轴判断，`design.is_applicable`标识是否有实际邻点；
两者从已入哈希的域、规则、点集与排除证据重建，不另存可与设计矛盾的豁免声明。
只有整体不适用时允许零点；空点集不能绑定任何点。部分轴不适用时，其中心值仍在全部点中保留。

`StudyPurpose.LOCAL_SENSITIVITY`用于固定结构的局部参数敏感性；类别或布尔取值的改变必须
声明`STRUCTURAL_CONTROL`。结构对照可另用普通账户评价取得证据，不使用局部参数计划，也不能进入局部稳健性验收或
混入局部分位数。纯整数及有序参数可直接使用相应邻域，不因缺少连续坐标而失败。

新自检使用`NeighborhoodSelfCheckProtocol`，必须提供`parameter_protocol`，不含
`minimum_perturbations`。`CandidateAssessmentRequest.parameter_designs`逐中心携带设计，
每个`PerturbationLink`和`AssessmentEvidence.parameter_point`须绑定同一具名点。
全部N点在中心相同的标准评价条件下有效后，才用等权LINEAR分位数计算
`PARAMETER_RETURN_Q10`和`PARAMETER_DRAWDOWN_Q90`；缺失、失败或不可比点不缩小分母，
不填零、不替换，也不以已完成子集冒充完整分位数。相对中心的退化仍单独报告。
整项不适用时仍提供正式设计，四项参数诊断均为`NOT_APPLICABLE`且`value=None`，不生成邻域账户，
其余诊断照常执行。缺失设计、缺点、失败和不适用是不同状态。

`CandidateAssessment.parameter_context`保存`ParameterNeighborhoodContext`，包括协议、
设计和空间哈希、维度、规定及有效点数、`comparison_sha256`。
比较不仅核对算法名，还核对参数名称、类别、单位、域/规则以及完整局部形状和约束身份；
边界造成单侧点集、约束删点或其他形状不同，可能使比较档案不一致。不能只因使用同一生成器
便声称分位数可直接同排。普通候选排序还要求经济上下文可比；缺失或不一致明确保留原因。
`compare_parameter_robustness`只返回参数诊断及可比性，不产生总体候选赢家。

新公式版本为`research-assessment-v7`。`assess_candidates`只接收当前v2邻域协议；历史
`SelfCheckProtocol`、球面设计、v1邻域及v5/v6面板保留精确读取身份。必要的历史数值复核由
`strategy_evaluator.research_assessment.recompute_historical_assessment`执行；该入口不升级旧协议，
不创建新版本交付。生成器拒绝旧方法，新评价不得重新绑定旧计划。既有证据和资格不自动迁移或改写。

相关账户计划与绑定详见[TDR公开API](../../src/czsc_trader/README.md)。

### 比较请求与政策

`CandidateComparisonRequest`显式传入比较候选集、`ResearchTargets`、自检面板和
`ComparisonPolicy`。TDR阶段交付将数值目标绑定到阶段一已确认的`MandateItem`；纯SE请求本身
不证明目标已获用户确认。诊断指标不自动升级为研究硬门。
本入口核验`ResearchTargets`显式声明的中心、窗口覆盖率、参数组及压力目标，输入与结果见下节。
年度表现、集中度、区间和PBO/DSR仍是诊断，不自动生成数值门槛。

`ComparisonPolicy(version, bins, pareto_basis, missing_evidence_policy, sensitivities=(),
formula_version="research-ranking-v4")`
必须显式声明分层基础及缺失证据政策：

| 字段 | 支持选项与语义 |
| --- | --- |
| `pareto_basis` | `ParetoBasis.RAW`使用原始净年化与回撤；`BINNED`使用协议分箱后的两项指标分层 |
| `missing_evidence_policy` | `MissingEvidencePolicy.REQUIRE_COMPLETE`要求全部适用证据齐备；参数项确认不适用时两项敏感度采用最低得分。`PREFIX_PARTIAL`允许按已知指标前缀判断部分先后关系，遇到影响判断的缺失值保留成对不可比 |
| `formula_version` | 当前`research-ranking-v4`，连同研究协议`version`进入请求身份；v3仅用于历史读取和明确的历史复核，不自动升级交付 |

`bins`恰含净年化、回撤、上述五项稳健性及一个`FREQUENCY_METRICS`指标。
层级优先；层内固定按六项指标比较：扰动净年化Q10（高）、扰动回撤Q90（低）、滚动超额Q10（高）、
压力年化损失（低，可为负）、利润集中度（低）、所选交易频率（高）。中心收益和回撤仅用于分层，
相对中心退化仅作诊断。`MetricBinSpec`指定分辨率、原点及舍入规则；元组排列不改变优先级。
`policy.frequency_metric`与`policy.ranking_metrics`明确所选频率及六项层内顺序，
`CandidateRank.bin_values`按该顺序输出六项分箱值。同层同箱保留并列，
候选ID只用于稳定展示。结果包含`pairs`两两比较关系以及每个候选的`rank_min/rank_max`；
`rank_in_layer`仅在能确定名次时填写，完整并列采用竞赛排名。状态为
`TARGET_NOT_MET/INCOMPARABLE/RANKED/TIED/PARTIALLY_ORDERED`，缺失值不填零。
`CandidateRank.floor_metrics`在当前结果中是空元组或恰好两项参数排序指标；仅正式参数项不适用
时由比较器填入后者。相应`bin_values`仍为`None`，排序使用明确的最低得分标记，低于有效实测得分；
双方均为最低得分时继续比较后续项。收益/回撤方向不影响最低得分的统一最差待遇，不能填成0回撤。
两项参数指标不适用不阻止候选参与同一排序，中心收益和回撤分层仍优先。真实缺失与计算失败不取得此待遇，
两个实际邻域的不可比也不因此消除。`compare_candidates`要求v7面板及v4排序协议；历史v3排序通过
`strategy_evaluator.research_assessment.recompute_historical_comparison`复核，旧结果不增加最低得分字段或改变哈希。
交易频率最后参与层内排序。排序只选择一项频率，验收可同时声明中位数及覆盖率等多项条件；
它们不必等于排序指标，但窗口须与面板一致。选择覆盖率排序时，必须显式声明同口径覆盖率目标。
未达标、证据不足和不可比候选仍保留结果。
采用部分排序时，目标、净年化和回撤仍须可核验；评价口径不一致的候选保留为不可比。
敏感性方案另列，不改写基准排序；`adjacent_swap`取0至4，只交换六项层内指标的相邻优先级，
不改变分层指标或所选频率口径。输出不自动产生入选或冻结决定。

`BENCHMARK_POSITIVE_YEAR_FREQUENCY`将buyhold收益严格大于零年份的实际交易日与闭合交易合并，
计算`frequency_window_days × 闭合交易数 / 实际交易日数`，不平均各年度频率。
年度收益按基准年末净值相对上一年末净值计算，研究首年使用`initial_cash`；
研究窗口边缘年份只使用窗口内实际日期。闭合交易按实际退出年份归属，未退出持仓不计。
年度分类仅用于事后评价。缺少基准或没有盈利年份时明确返回缺失或不适用，
不填零、不改用`FULL_SAMPLE_FREQUENCY`；选择该指标的比较因此不可比。
既有全期、滚动中位数和滚动Q10频率可按获批研究协议显式选用。

平台提供上述政策能力；当前RSCH研究政策使用原始值分层及完整证据比较，具体以
[RSCH排序规则](../../research/RSCH_AGENT.md#研究族内排序规则)和获批协议为准，调用方不得据工具能力自行改政策。
按该研究政策构造请求时，显式设置`ParetoBasis.RAW`和`MissingEvidencePolicy.REQUIRE_COMPLETE`；
其他政策须先获用户批准并另立协议版本。

### 经济、频率及稳健性验收

验收复用上述两个入口，不新增账户回放或独立准入服务。SE计算声明的条件，TDR认证来源并绑定
阶段一确认；数值通过不等于统计独立性充分，也不授予冻结或PTE权限。

| 输入类型 | 字段与语义 |
| --- | --- |
| `ResearchTarget` | `target_id/metric/lower/upper/when`；`scope=TargetScope.STANDARD`使用中心，`STRESS`只支持压力净年化和回撤；可用`one_way_cost`声明必需每侧费用，缺失或不符为证据不足 |
| `FrequencyCoverageTarget` | `target_id/window_days/minimum_closed_cycles/minimum_numerator/minimum_denominator`；例如`("coverage", 60, 3, 9, 10)`表示至少90%的完整60交易日窗口有至少3笔闭合交易 |
| `ParameterNeighborhoodTarget` | `target_id/minimum_numerator/minimum_denominator/joint_targets/all_point_targets`；按完整设计N点要求至少ceil(N×分子/分母)点联合通过，全部N点须满足全部点条件；内层仅支持标准场景收益和回撤 |
| `NeighborhoodSelfCheckProtocol.frequency_min_closed_cycles` | 显式传入覆盖统计的闭合笔数阈值，例如3；`None`表示未请求该统计，不能用中位数或Q10补齐 |

这些目标组成`ResearchTargets.requirements`。参数与窗口数接受有约束的整数，拒绝布尔值冒充整数。
正式局部设计不适用时，参数目标返回`NOT_APPLICABLE`，不当作零点通过；其他目标继续验收。
总体验收仍优先保留失败和证据不足，只在全部适用条件通过时返回通过，逐项不适用状态不丢失。
参数条件按每个点自己的标准场景基准计算；压力条件只使用压力账户自己的基准。成本未声明表示
该原子目标没有费用约束；下例明确声明标准0.001、压力0.002，不从场景名称推断费用。

`CandidateAssessment`增加三类事实：

- `frequency_coverage: FrequencyCoverageFacts | None`：窗口长度、笔数阈值、总窗口数N、达标数K及评价ID。
  每交易日移动一次，按退出日计闭合交易，窗口前入场、窗口内退出计入；未退出不计入。
  N为账户日数减窗口长度加一，不足窗口时N=0，验收为`INDETERMINATE`。
  `FREQUENCY_COVERAGE`诊断为K/N，单位`RATIO`；门槛用整数交叉相乘，避免插值分位数替代覆盖率。
- `parameter_performances: tuple[PerformanceFacts, ...]`：保留有效点序号、候选及评价ID、场景、策略和基准净年化/回撤。
  只接纳与中心的上下文、版本、费用、基准净值和设计绑定一致的点；缺点不缩小规定分母。
- `stress_performance: PerformanceFacts | None`：同一中心的压力场景策略与基准绩效、场景和评价ID。
  只有压力损失诊断不足以完成压力验收。

净年化使用`(末期净值/初始资金) ** (252/交易日数) - 1`，回撤包含初始资金及持仓市值。
比较使用未作展示舍入的数值；v3将基准值与倍数的最短十进制表示相乘后转换为float作为边界，
避免`0.1 * 1.5`的乘法尾差误拒绝`0.15`；不加入额外容差，严格不等号仍严格执行。

以下是新比例参数标准的目标构造示例；`performance`是示例内的本地构造函数，不是平台API。
研究协议需显式配置60日频率、完整邻域、标准/压力场景与覆盖阈值3，再取得面板。13/16为81.25%；N=17需至少14点联合通过，17点全部满足风险上限。旧32点/26点目标不自动转换。

```python
from strategy_evaluator import (
    ResearchMetric as M, ResearchTarget, ResearchTargets, TargetScope,
    ConstantBound as C, BenchmarkBound as B, BenchmarkCondition, ComparisonOperator as Op,
    FrequencyCoverageTarget, ParameterNeighborhoodTarget,
)

def performance(prefix, multiple, dd_multiple):
    return (
        ResearchTarget(prefix + "-positive", M.NET_ANNUAL_RETURN, lower=B(multiple, True),
            when=BenchmarkCondition(M.NET_ANNUAL_RETURN, Op.GT, 0.0), one_way_cost=0.001),
        ResearchTarget(prefix + "-nonpositive", M.NET_ANNUAL_RETURN, lower=C(0.0, False),
            when=BenchmarkCondition(M.NET_ANNUAL_RETURN, Op.LE, 0.0), one_way_cost=0.001),
        ResearchTarget(prefix + "-relative-dd", M.DRAWDOWN_MAGNITUDE,
            upper=B(dd_multiple, True), one_way_cost=0.001),
    )

pressure = {"scope": TargetScope.STRESS, "one_way_cost": 0.002}
targets = ResearchTargets((
    *performance("center", 1.5, 0.8),
    ResearchTarget("center-cap", M.DRAWDOWN_MAGNITUDE, upper=C(0.25, True), one_way_cost=0.001),
    ResearchTarget("median", M.FREQUENCY_MEDIAN, lower=C(6.0, True), one_way_cost=0.001),
    FrequencyCoverageTarget("coverage", 60, 3, 9, 10),
    ParameterNeighborhoodTarget("parameters", 13, 16, performance("point", 1.25, 0.9), (
        ResearchTarget("point-cap", M.DRAWDOWN_MAGNITUDE, upper=C(0.25, True), one_way_cost=0.001),
    )),
    ResearchTarget("stress-profit", M.NET_ANNUAL_RETURN, lower=C(0.0, False), **pressure),
    ResearchTarget("stress-excess", M.NET_ANNUAL_RETURN, lower=B(1.0, False), **pressure),
    ResearchTarget("stress-dd-positive", M.DRAWDOWN_MAGNITUDE, upper=B(1.0, False),
        when=BenchmarkCondition(M.DRAWDOWN_MAGNITUDE, Op.GT, 0.0), **pressure),
    ResearchTarget("stress-dd-zero", M.DRAWDOWN_MAGNITUDE, upper=C(0.0, True),
        when=BenchmarkCondition(M.DRAWDOWN_MAGNITUDE, Op.LE, 0.0), **pressure),
    ResearchTarget("stress-cap", M.DRAWDOWN_MAGNITUDE, upper=C(0.25, True), **pressure),
), frequency_window_days=60)
```

`CandidateRank.target_checks`按目标返回`TargetCheck/FrequencyCoverageCheck/ParameterNeighborhoodCheck`。
原子结果有观察值、解析后边界、条件值和评价ID；覆盖结果带N/K；参数结果带有效点数、联合通过数、
逐点联合与全部点检查。输出状态为`PASSED/FAILED/INDETERMINATE/NOT_APPLICABLE`：条件分支未触发
仅该原子项不适用；不能把全不适用或空目标集合视为通过。参数组完整通过要求全部规定点有效，
且联合通过数和全部点条件同时成立；已发现风险上限失败可直接报告失败，缺失项仍保留。

`CandidateRank.acceptance_status`汇总已声明目标：任一失败为`FAILED`；没有失败但有证据不足则为
`INDETERMINATE`；所有适用条件通过且至少一项适用才为`PASSED`。没有目标时可作普通排序，验收状态
仍为`INDETERMINATE`。声明目标未通过的候选不进入推荐排序；目标通过但排序证据不全仍不可比。
此字段只证明所传目标集合，完整获批集合由TDR阶段一绑定校验，不能用删减目标的纯SE请求宣称完整通过。

## `compare_ledgers`：保留原始身份的账本比较

调用方传入两份`ReplayEvidence`和强类型请求，SE只在内部副本上做比较，不改写原证据。

```python
from strategy_evaluator import (
    LedgerComparisonMode, LedgerComparisonRequest, compare_ledgers,
)

# left、right 是两份完整的 ReplayEvidence。
result = compare_ledgers(LedgerComparisonRequest(
    left=left,
    right=right,
    mode=LedgerComparisonMode.ECONOMIC,
    tolerance=0.0,
))
```

| 模式 | 比较规则 |
| --- | --- |
| `STRICT`（默认） | 保留策略哈希及全部决策、订单、成交、周期身份进行比较 |
| `ECONOMIC` | 忽略`strategy_hash`，对五张账本中的顶层`decision_id/order_id/fill_id/cycle_id`作一一对应重命名；保留业务字段、附加列、行顺序及引用关系 |

比较前核验证据JSON可序列化且数值有限、已填写的内容哈希、账户日期覆盖、身份唯一性和关联引用。
`data_hash`、初始资金、评价日期、执行规则及日内／日线执行数据必须精确一致；
`tolerance`仅用于其他数值字段的绝对误差比较，必须有限且非负。

`LedgerComparisonResult`包含`status`、`mode`、两侧原始证据哈希及最多20条
`LedgerDifference(path, reason)`。无法计算有效哈希时对应哈希为`None`。

| 状态 | 含义 |
| --- | --- |
| `EQUIVALENT` | 在指定模式和容差下等价 |
| `DIFFERENT` | 上下文可比，账本内容存在差异 |
| `INCOMPARABLE` | 数据、资金、窗口或执行上下文存在差异 |
| `INVALID` | 证据序列化、内容哈希、日期覆盖或引用关系不合格 |

经济等价模式仍比较诊断等附加字段；相同成交并不自动得到`EQUIVALENT`。
仅在`ECONOMIC`、零容差且等价时返回`economic_sha256`，用于确定性行为分组；容差内近似一致
不生成同一经济哈希。双方原始证据哈希及身份始终保留。
账本比较用于定位两次运行的差异，执行正确性仍由`audit_replay`独立审计。

发布包升级的等价验证由RSCH选择比较范围、模式和容差，并解释允许变化的展示字段与发布身份。
SE不会因为一次账本等价而批准升级，也不会把`DIFFERENT`自动转换为研究否决。
TDR的[同版本升级API](../../src/czsc_trader/README.md#同版本发布包升级)可关联这些报告作为审计材料，
不强制运行SE或要求报告PASS。`compare_ledgers`本身仍按上述规则比较附加字段，不自动删除观察列。

## 美股个股研究事实

显式缺口研究口径的行情带 `BarStatus=OBSERVED/MISSING/ZERO_VOLUME` 和 `ExecutionBlocked`。
独立账户审计分别核对缺失、零量和已声明中断导致的订单过期原因，并拒绝这些区间中的成交。
信号抑制只能依据执行开始前已完成且可得的行情：当前执行区间最终缺失不能提前影响该区间的决策。
缺失或零量后的下一次决策记录 `SUPPRESSED_UNOBSERVED_BAR`，保持持仓、不创建订单；有量行情恢复后再评价策略。
估值沿用最近有效收盘价，拆股同步调整估值价；`valuation_stale` 和 `valuation_price_at` 必须与行情及公司行动一致。
这些字段表明研究假设与估值盲区，不证明历史停牌，也不代表缺口期间净值没有波动。

美股正式账户仍通过 `assess_candidates`、`compare_candidates` 完成自检与比较。
TDR 的 `build_assessment_evidence` 将 `equity-research/v2` 档案适配为 `AssessmentEvidence`，
附加 `EquityAssessmentFacts`，保存候选与 `EquityBuyHold` 基准的原始账户及公司行动账本。
SE 独立核对成交、拆并股、股息应收与到账、周期损益，以及现金、持仓、应收款共同构成的净值。
已平仓周期中的股息只计入一次；未平仓头寸不作为完整周期。
正式 v2 两账户显式启用 `decision_contract="FORMAL_V2"`，独立重建因果行情和事件生效后的账户、目标仓位到交易计划，
并校验所有订单（包括 `EXPIRED` 未成交订单）的关联、数量、区间及执行结果；既有默认和 legacy 审计入口不变。

| 口径 | 显式选择与计算 |
| --- | --- |
| 年化、频率 | 按纽约市场交易日聚合，年化使用交易日数；60 日频率按完整周期的平仓日计数，30 分钟 bar 不充当独立交易日 |
| 最大回撤 | `SESSION_CLOSE` 使用每日最后净值；`BAR_CLOSE` 使用每个 30 分钟净值。候选和基准使用相同选择，包含初始资金基点 |
| 盈利集中度 | `TOP_DECILE` 使用盈利周期中最大的前 10%（向上取整）占比；`MAX_SINGLE` 使用最大单个盈利周期占比。无盈利周期时标记不适用 |
| 交付认证 | 仅根据档案中的定义、输入绑定、完整窗口、原始事实及哈希独立重算，不依赖当前策略源代码 |

回撤和集中度选择进入指标版本与比较上下文，禁止混用口径。诊断结果不会自动变成硬性研究目标。
旧 A 股 `AssessmentEvidence` 未设置附加事实时不序列化新字段，既有语义、档案及哈希保持不变。

美股连续账户分解由 `strategy_evaluator.equity_diagnosis.diagnose_equity_accounts` 消费认证后的原始账本。
事件按账户修订序号归属，避免下一根 bar 开盘事件被提前计入上一根收盘；切片从已有连续账户保留期初持仓和净值。
股息权益计入持有损益，到账与卖出交收只做资产内部转移；同日多个周期按实际入场区间匹配，无法唯一归属每日周期时保留空值。

## 基准整手审计

`BenchmarkEvidence`必须显式填写正整数`lot_size`，拒绝布尔值及浮点数；该字段进入序列化结果
和证据哈希。基准审计独立复算整手取整、现金、持仓、费用及净值，不调用TXE重放作为审计答案。
BuyHold及MA5/MA20的基准证据必须携带实际现金与持仓数量，不能只提供仓位比例收益。
历史证据保持原样；新证据按当前合同生成，不补写旧档案。

## `pareto_layers`：输入适配

先阅读[公共导出](src/strategy_evaluator/__init__.py)，核对`CandidateProfile`和[分层实现](src/strategy_evaluator/pareto.py)。函数按`worst_scores`执行各指标越大越好的帕累托分层，返回带`pareto_layer`的配置；不自带研究目标核验、层内排序或缺失值政策。

| 检查 | 调用方要求 |
| --- | --- |
| 指标集合 | 指标键非空、唯一且完全一致；重复候选ID或不同指标集合立即拒绝 |
| 数值 | 只接受有限整数／浮点数，拒绝布尔值和非有限值 |
| 方向 | 越大越好；收益／回撤双指标分层传入净年化及负的最大回撤幅度 |
| 缺失 | 影响比较的缺失值标记不可比，不填零或静默丢弃指标 |
| 政策 | `pareto_layers`只分层；阶段四目标核验和分箱排序使用`compare_candidates` |

最小适配测试应覆盖指标键不一致、非有限值、完全并列及已知支配关系。工具分层结果不替代研究员解释或用户选型。
