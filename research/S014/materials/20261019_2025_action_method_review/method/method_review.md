# C0056 两个 2025 节点的最小动作比较方案

状态：方法与可审核原型已准备；只完成纯合成预检。没有注册候选、准备新数据绑定、生成真实分支历史、派发账户或计算新动作收益。真实 NOOP 经济等价与数据绑定兼容性均待执行授权后验证。本方案回答两个已知节点的一次动作如何改变 2025 剩余年份的最终财富，不能当作一般交易信号或独立获利能力的验证。

## 固定比较与预算

沿用 EX023 原 C0056：600722.SH，完整 1642 个交易日的账户窗口 2020-01-02 至 2026-10-15，预热与起始状态均保留；每方向费用 0.001、初始现金 100000、原 LimitBuyHold 整手/限价/涨跌停/数量约束及原数据请求均保留。价格是原账户 `HFQ_RESEARCH` 锚定表示，锚点 2019-12-31、因子 5.892，数量单位为 `RESEARCH_UNIT`；现金与数量×价格必须保持原尺度。

未来最多派发 3 个 FULL 账户，失败、取消或结果未知也计入额度；不自动重试、不另派账户作现金参考。每个评估一个窗口、一个原费率，workers=1，max_workers<=2、native_threads=1、seed=17。顺序为 NOOP 控制通过后 SKIP 试点，通过执行/审计后 FORCE；任一技术门失败即停止。这里的门只确认实现与账务正确，不按获利正负决定继续。

| 独立分支 | 唯一干预决策收盘日 D | 当时原路径资格与一次动作 |
| --- | --- | --- |
| NOOP | 空字符串 | 原参数行为；仅增加分开的诊断列 |
| SKIP_BUY_ONCE | 2025-06-18 | 原路径空仓且已接受次日 BUY 意图；取消该次 intent、target 与 accepted |
| FORCE_SELL_ONCE | 2025-06-19 | 原路径当天已买入、收盘 HOLD、没有待卖状态；设置次日 MARKET SELL 意图 |

两个处理均各自从原始路径独立分叉，不能先 skip 再 force。参数必须是固定 C0056 variant、严格枚举 mode 和规范 `YYYY-MM-DD` 日期；NOOP 日期只能为空。节点不存在或不合资格直接拒绝，禁止寻找替代日期。

**唯一经济主终点 T=2025-12-31 收盘**。所有分支同价估值，尚持仓不强制卖出；披露末仓、现金、待卖/待买及未完成周期。2026 尾部只保留完整执行合同与 NOOP 控制审计，不用于选择终点、动作或结论。曾考虑 E+21 的局部终点，但本方案不执行或报告该额外终点；年末更直接回答 2025 年度问题，代价是包含更长的后续参与路径影响。

## 原状态机边界

SKIP 仅取消一个计划，不伪造失败买单、不触发 failed_buy_reset、不建立假 entry/deadline/reservation。次一决策日若原规则重新符合条件，可重新发 BUY；只有真实成交才建立该新周期锚点。因此 SKIP 并不代表永久避开这轮行情。

FORCE 只改收盘动作，不改原持仓 entry、deadline、reservation。若次日停牌或跌停而卖不出，按原执行约束保持持仓与待卖，随后可执行时成交；不假设按不可成交价格出逃。提前卖出也不能提前释放预约：原 2025-06-19 成交对应 deadline 决策日 07-02、reservation 决策日 07-03，通常最早新买成交 07-04。后续实际新买成交再建立新锚点。原 `action=SELL` 可能只是失败买入后归零，不能用它代替真实持仓/BUY 意图/待卖状态。

原型由 `research/S014/experiments/EX023_20261018/src/strategy_runtime/strategies/repair.py` 最小逻辑复制；格式整理不改变原执行 helper 与数据请求的 AST。干预点在当天原规则形成意图之后、输出行之前。原 observed 与 target 字段保持，新增诊断列 `intervention_today`、`intervention_done` 单列审计。原完整 SRT 输入、决策、执行、监控与能力合同由合成检查逐项比较；生产平台源码不修改。

## 公共 API 身份与数据边界

公共 `EvaluationRequest.strategy` 要求 `StrategyCandidate`，不能传没有身份的匿名函数。`packages/strategy_runtime/src/strategy_runtime/models.py` 的类注释明确每个参数集构造新不可变值，试跑不要求 SM 注册。可采用 EX035 相同的有明确诊断 ID、未登记的策略输入，不修改或重新命名 C0056，也不调用 register_candidate；三个诊断 ID 须在未来准备阶段核未占用。本轮没有创建这些对象或 payload。

每个分支须声明独立 parameter payload、真实源闭包、implementation hash 和对应 runtime_binding；不能把原 C0056 身份绑定直接嫁接到新源码。通过公共 `ctx.evaluation.prepare` 形成/核验 strategy-specific 输入计划，再 `evaluate_many`，最后明确发布回执。原绑定中的 calendar、clock/signal session、prepared ref、execution_data 内容身份均须审计；带 input_bindings 的请求仍需 execution_data。新 runtime 的 binding 可能需要新的 preparation/clock contract 身份，尚未证明可原样复用。

可审计复用的数据来源是 EX023 正式 binding 中的既有 PreparedDataRef 和内容身份，见 `source_bindings.json`。必要时沿用 EX017 的 S014 专属 pinned offline provider，通过公共 prepare 构造新计划；封禁外部请求，比较原内容摘要/预窗/截止日，任何缺项直接拒绝。禁止私拼未认证 BacktestExecutionData，禁止临时接入新行情 API。原正式账户与运行 result_hash 也在该文件中。

公共合同定位：`src/czsc_trader/research_tools/evaluation.py` 的 EvaluationRequest、_request_contract、_bind_evaluation_inputs；`src/czsc_trader/research_tools/evaluation_access.py` 的 prepare、evaluate_many；`packages/strategy_runtime/src/strategy_runtime/models.py` 的 StrategyCandidate。局部干预先例是 EX034/EX035 的 protocols/design.json 与 src/run_accounts.py，但不能搬用 C0011 H3/E9 动作收益；EX034 已指出 C0056 的预约仍阻止原 E+10 前再参与。

## 结果口径与精确拆解（仅预设，未计算）

每一节点的原策略 B 与处理 K/S 在 D 收盘拥有相同现金、数量和净值 W_D，不重置现金。报告主差额 `W_treatment(T)-W_B(T)`，并除以同一 W_D 报告该节点剩余年份财富差；另除以原 2025 年初净值可报告全年收益贡献差，两种分母不得混用。两个节点初始状态不同，不直接相加或当作两个独立样本估计一般均值。

空仓节点现金参考是 `C_flat=W_D`，冻结不参与；SKIP 恢复策略后的每次买卖、费用及末仓全部计入 K。`K-B` 是主动作总影响，`K-C_flat` 只是后续参与相对现金的财富差。

持仓节点对每条路径 j 定义 F_j(T)：D 已有仓位首次真实全部卖出后的账户现金冻结至 T（包括原有零钱与实际卖费）；若到 T 仍未卖出，则用 D 现金加 D 数量×T 同一价格，且不虚构卖费，此时明确标为末仓估值、并非现金。`G_j(T)=W_j(T)-F_j(T)` 是卖后再参与的净贡献。于是 `S-B=(F_S-F_B)+(G_S-G_B)` 精确成立；前项是当前原仓退出现金/末仓估值差，后项是再参与差。现金参考 C 可直接取 F_S，来自 S 首次实际卖出，不增加账户；若 S 尚未卖出则不称现金参考，延迟成交不能提前假设现金可用。若报告 `(S-C)/W_D` 与 `(B-C)/W_D`，后者包含 B 的再参与，不能称为纯持有价值。

## 下一阶段必要验证

1. 用户批准范围、账户额度、固定节点/终点及不可重试纪律；发布设计、源码与源身份锁。
2. 公共离线 prepare/preflight：源闭包与 binding 一致、输入内容/时钟等价、两节点资格与完整预窗、账户执行参数不变；不从数据中搜索节点。
3. NOOP 真实控制逐字段比较原 observed/target、orders/fills/attempts、每日现金/数量/净值与费用。新诊断身份导致 request/result hash 变化可以预期，不能要求身份哈希等同；原经济内容必须等价。
4. 先 SKIP 后 FORCE。比较所有 D 之前原字段/账本一致、各一次干预、计划/执行日期、保留锚点预约、成交与费用、逐日对账和上述年末拆解；第三方独立审计。无获利阈值门。

合成预检通过不证明真实节点财富、全年表现、NOOP 经济等价或 binding 复用成功。方法和实现准备目标已达成；建议主会话将此具体包交用户决定是否授权上述最多 3 个账户，当前停止在待执行状态。
