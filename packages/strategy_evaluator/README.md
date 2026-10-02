# 策略评估器（SE）

SE提供确定性的指标、协议校验、比较、帕累托分层、PBO、DSR、Bootstrap、参数邻域、压力及账本审计计算。先阅读[公共导出](src/strategy_evaluator/__init__.py)，再沿导入核对契约与测试。

研究员通过TDR受管评价API取得SRT/TXE账户事实，再组合SE公共函数。SE不获取行情、不加载策略、不写治理状态。旧资格裁定、冻结健康政策、自动冻结建议及对应报告入口已删除。

阶段四使用`assess_candidates`和`compare_candidates`，输入与输出均为强类型不可变记录。
`validate_protocol`、`screen_candidates`、`rank_candidates`保留既有协议计算语义；新阶段交付
按下述研究契约进行复算。统计风险标签不等于冻结决定或未来成功概率。

平台校验结构、计算和证据一致性，研究员解释与推荐，用户决定选型；检验和获批冻结使用
[TDR入口](../../src/czsc_trader/README.md#8-技术检验用户决定与冻结)。

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

`CandidateAssessmentRequest`显式指定中心候选、账户／成交／基准证据、参数扰动关系、
未完成评价和`SelfCheckProtocol`。协议指定场景、窗口、覆盖、分位数算法、Bootstrap种子及
容差。参数邻域仅接纳真实`PARAMETERS`派生；缺失或不可比诊断保留状态和原因，失败与取消
尝试保留记录，不填零或静默丢弃。主要结果包括净年化、回撤、已完成交易周期及频率、配对
滚动超额收益、利润集中度、压力损失和参数退化；置信区间及家族PBO/DSR作为诊断报告。

`CandidateComparisonRequest`显式传入比较候选集、`ResearchTargets`、自检面板和
`ComparisonPolicy`。TDR阶段交付将数值目标绑定到阶段一已确认的`MandateItem`；纯SE请求本身
不证明目标已获用户确认。诊断指标不自动升级为研究硬门。

比较先按原始净年化和回撤作帕累托分层，再按七项指标的显式分箱顺序比较：净年化、回撤、
参数收益退化、参数回撤退化、滚动超额Q10、压力年化损失、利润集中度。分箱由
`MetricBinSpec`指定分辨率、原点及舍入规则；同层同箱保留并列，候选ID只用于稳定展示。
交易频率用于目标核验，不参与上述层内排序；未达标、证据不足和不可比候选仍保留结果。
敏感性方案另列，不改写基准排序；输出不自动产生入选或冻结决定。

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
