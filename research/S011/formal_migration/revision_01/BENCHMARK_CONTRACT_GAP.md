# 阶段四迁移阻断：基准执行契约缺失

状态：`PLAN_REVIEW_REQUESTED`。2026-10-01用户明确选择“先评审方案，暂不修改平台”。RSCH已完成EX29的135份策略账户复算，675张策略账本对账通过。阶段一、二、三正式交付已发布并通过公共验证。阶段四未发布；当前SE输出仅作差异诊断，不替代原排名或621选择。

## 已验证的差异

| 项目 | 原S011基准：EX16 | 当前TDR内置BuyHold |
| --- | --- | --- |
| 建仓日、实际成交价 | 2025-02-06，1.062元 | 相同 |
| 委托及资金预占 | LIMIT，限价1.065元，按限价预占 | 开盘目标仓位回放，按1.062元计算数量 |
| lot_size | 100 | 100 |
| 标准成本买入数量 | 938,000股 | 940,600股 |
| 标准成本末权益 | 1,461,437.844元 | 1,462,716.8828元 |
| 基准CAGR | 26.7765207386% | 26.8458899101% |
| 策略收益门槛：1.5倍基准 | 40.1647811078% | 40.2688348652% |

000244的策略CAGR为40.2208913965%，因此原判定通过、当前内置基准判定失败。621仍满足原目标且仍位于第一层第3位，但其60日滚动超额Q10等依赖基准的指标改变。原36配置及选择完整保留，禁止用当前35个达标配置冒称原集合迁移完成。

证据（相对于仓库根目录）：`experiments/S011/20260930_S011_EX16/artifacts/benchmark_orders.csv.gz`及同目录`benchmark_fills.csv.gz`；新证据为`experiments/S011/20261001_S011_EX29/artifacts/evaluations/`。具体身份、数值和代码定位见同目录`benchmark_gap.json`。

## 建议的DEV改动：待用户评审

1. **TDR契约：显式选择基准实现。** 保留现有`EvaluationBenchmark`表示内置开盘BuyHold；新增强类型`CandidateBenchmark(strategy: StrategyCandidate, dependencies: tuple[ImplementationDependency, ...])`。将`EvaluationRequest.benchmark`改为二者联合类型。`CandidateBenchmark`使用已存在SRT候选载荷及源码闭包，从候选得到执行规则；无需再提供弱类型策略字典或回调。不把S011的LIMIT参数写死在平台。
2. **TDR执行：`evaluate_strategy`支持受管候选基准。** 每个窗口和成本场景，通过SRT/TXE执行固定基准候选，使用与被评策略相同的数据、资金、窗口及成本覆盖；以基准自己的LIMIT、资金预占、整手和未成交规则形成完整账户。历史S011直接复用EX16基准实现及固定premium=0.003，先逐账本验证，之后用于后继评价。基准是账户计算，不产生参数搜索预算或选择管理。
3. **TDR身份及持久化：绑定真实基准内容。** 修改`EvaluationIdentity`关联的请求身份投影、`EvaluationRun`的基准结果契约及评价产物写入：绑定基准候选内容哈希、源码/依赖身份、实际执行规则、窗口、成本和数据上下文；保存基准五张账本。新评价产物使用明确的新schema版本，旧schema 3回执按原语义只读。不得沿用相同`benchmark_id="BuyHold"`掩盖执行差异。
4. **SE与TDR适配：`EvaluationScenarioContext`显式携带基准内容身份。** `build_assessment_evidence`仅从受认证的实际基准结果投影`benchmark_equity`及身份；`assess_candidates/compare_candidates`拒绝基准内容不同的混合比较。阶段四交付读取和验证同步新schema，保留既有schema只读路径。
5. **聚焦验收。** 覆盖相同成交价但LIMIT预占数量不同、LIMIT未成交、100股取整、10/20bp成本覆盖、跨基准身份拒绝比较，以及旧评价读取。研究验收使用后继实验：保留EX29，复算EX16标准/压力基准并逐账本核对，再生成可认证的新评价身份；不得把历史权益序列手工塞进EX29或改写它的回执。

上述为待评审技术方案，不代表平台已经实现。只在取得跨角色授权后切换DEV；本轮不修改平台源码、不改研究门槛、不以SE手工替换基准规避认证。
