# 执行渠道（Execution Channels，EC）

EC 拥有交易规则、订单规划与渠道账户。输入为宿主已经准备的执行事实和策略意图；
不依赖 DFLS、SRT、PTE，也不负责数据查询、策略计算或调度。

账户输入更新使用 `PaperStore.replace_v4_runtime_inputs(account_id, inputs, expected_inputs=..., forward=...)`。
新旧输入均为 `futu.input_identity.AccountInputIdentity`，由宿主在完整校验配方后显式投影；
其不可变 JSON 文档由 EC 原样持久化，EC 不解释宿主 schema、数据角色或 RAW 引用。
EC 核对发布、标的、执行规范、模型费率及当前旧文档快照，在同一事务内保存新输入和历史记录，
保留生效区间与账户状态。过期快照、身份不符或持久化失败均不产生部分更新。

## 富途 A 股、美股模拟渠道

`futu.channel.ChannelAccountConfig` 明确绑定市场、币种、模拟账户与交易时段。
`futu.futu_execution.ChannelExecution` 共享订单提交、未知提交结果恢复、累计成交归并、
现金与持仓对账，市场差异通过明确的渠道配置处理。账本位于 `futu.store.PaperStore`，
按渠道和策略账户隔离；现金差额归平账账户的既有规则保持不变。

`PaperStore.first_account_signal_date(account_id)` 读取账户最早的已保存决策信号日，包含无需下单的决策。无记录时返回 `None`。`update_virtual_account_name(account_id, name)` 只更新策略账户的显示名和更新时间，并在同一事务内审计。名称格式由 PTE 管理。

`ChannelExecution.retire_account(AccountRetirementRequest)` 受理账户退役，支持 CN／US 模拟渠道。
请求绑定账户和预期发布哈希，持久化为 `RETIRING`；重复请求返回当前进度。
先终止未提交策略意图、撤销在途策略订单并等待确认，再以 `MARKET SELL` 清理实际可卖持仓。
运维清仓采用独立的 `account.retirement.v1` 计划，复用订单、成交、费用和账户账本；
不加载旧策略，也不伪造 V4 策略建议。普通策略决策不能写入或执行退役计划。

宿主通过 `RetirementSession` 提供实际交易区间、明确模型费率和必要的结算时点；
EC 不访问 DFLS，不推测交易日，不把市价单降级为限价单。`refresh_orders` 持续推进退役，
只额外提交对应退役账户的清仓单。部分成交继续等待；不可卖或非交易时段等待后续事实。
未知提交先追认，明确拒单须通过既有执行异常确认接口处理后才能重试，不盲目重复报单。
市价清仓要求渠道采用 `RTH` 时段政策；`ETH` 仅允许限价单，退役明确阻断而不改变订单类型。
整仓卖出可携带经账户账本确认的 `full_liquidation`，允许清理 A 股零股；部分减仓仍按数量步长校验。

`retirement_status` 返回阶段、剩余数量、已归还现金和原因。
只有持仓、冻结现金和应收均为零、订单终结且渠道与账本对账通过，才原子记入
`CAPITAL_RETURN`、将实际现金归还本渠道资金池并标记 `RETIRED`，保留全部历史。
数据库 v9 迁移扩展账户状态约束并新增退役请求表，原账户和交易记录保持不变。

`futu.adoption.DecisionAdoption` 是不可变决策文档与账户身份；
`AccountAdoption.adopt` 在事务内写入状态、估值快照、资金预占与订单意图，返回
`AdoptionResult` 中明确的决策和意图身份。宿主可在已有版本检查事务内调用，
事务内再次要求账户为 `RUNNING`；暂停账户不能采纳决策、写入决策快照或预占资金。
采纳失败会与本次替换及资源变化一起回滚。

`futu.v4_admission.prepare_v4_adoption` 在采纳前校验执行腿、确认可卖数量、手数、价格单位、
日期价格限制和周期剩余预算，构造待提交账户状态与费用估计；这些规则不在 PTE 重算。
`decision_snapshot` 从已确认账本和卖出锁定时点生成权威账户快照。
`V4ExecutionContext.as_of` 必须显式提供带时区的实际观测时点，且不晚于执行区间起点。
为下一交易日提前规划时，持仓可卖量按执行时点评估，但入账状态只清理 `as_of` 已到期的
买入锁；不得因计划在次日执行而提前解除当前持仓锁定。委托仍受各自执行区间约束。

原生 V4 阶段五受控成交通过同一个 `ChannelExecution` 驱动，外部券商替换为离线记录渠道。
`InspectionAccountPermit` 只认可指定的隔离目录和发布身份，不能用于正式账户。

明确拒单、提交前确认的现金／可卖量不足、本地未提交过期及有证据的到期部分成交撤余，
分别记录 `ORDER_REJECTED`、`EXECUTION_CONSTRAINED`、`EXECUTION_EXPIRED`、`NORMAL_PARTIAL`。
它们终结本次尝试并返回实际效果，不因目标未完全实现而阻断账户，不重复提交已终结意图。
资金预占仅释放未成交部分，依赖完整成交的后续腿在条件未满足时跳过，保留已有持仓与策略目标。
结果未知、账本不一致和非法输入仍阻断。没有足够依据的取消不能解释为正常到期。
`release_account_intent` 的可选强类型 `termination_reason` 只用于无渠道订单的已知本地终结，
校验对应状态及具体说明；渠道回报仍由存储根据回报、成交及撤单审计分类。

执行域合同由 `instruments`、`policy`、`contracts`、`state`、`entry_cycle` 等业务模块拥有。
应用应显式投影到这些类型，不能将 SRT 或 DFLS 的同名类直接传入。

## 交易规则与订单规划

`market_rules.resolve_market_rule` 按市场、资产类型、标的和交易日解析有版本的静态规则，
包括数量步长、价格精度、卖出可用时间、零股处理和结算时点。
`market_rules.constraints.resolve_execution_context` 接收EC标的、执行规范和显式日历区间，
统一推导买入后可卖时间及现金结算时间；在线和历史调用同一函数。其结果不包含可交易状态或动态限价，
历史路径另合并DFLS事实，在线路径明确由渠道核验动态可交易性，不生成虚构的 `Tradable`。
`market_rules.constraints`
将静态规则与宿主提供的交易日历、停牌和当日价格边界组合成执行约束；不查询数据源。
历史价格边界必须与 HFQ 行情使用相同单位；在线价格边界使用 RAW 单位。美股使用明确的无涨跌停声明。

`planning.plan_account_decision` 接收 `TradeIntent`、决策点、账户快照和执行政策，
统一计算 V4 数量、委托价格、周期预算与计划身份。SRT 只产生策略意图和待采纳状态，
应用负责 `serialization.to_record/from_record` 的类型投影。字段类型、未知字段、
价格与数量边界在执行域校验；投影不重新计算策略。

EC对合法目标采用尽力执行语义。`AccountExecutionPlan.planning_result` 返回强类型
`PlanningResult`：`READY`表示生成计划，`CONSTRAINED`表示仅部分要求可规划，`BLOCKED`
表示本次没有合法可执行委托，`NO_CHANGE`表示无需调整，`SUPPRESSED`表示观察不足而暂停规划。
目标比例及期望数量保留，可执行计划数量另列；原因区分可用现金不足、低于最小单位、
低于价格单位、可卖量不足及依赖不可执行。READY不是成交成功，NO_CHANGE也不保证精确仓位比例。
首次进场或后续增仓买不起最低单位时，委托受阻但账户继续推进；不缩放价格、不修改目标或交易单位。
无可执行入场不建立虚构的持仓或预算周期。非法合同、账户不一致及数据损坏仍明确异常。

确认后的实际效果由 `HistoricalReplayChannel.decision_execution_effect` 和
`PaperStore.decision_execution_effect` 查询；后者由CN、US模拟渠道共用。
调用方传入决策身份、明确估值价格和查询时点，接口只读取现有账本，不拉取行情或触发交易。
`DecisionExecutionEffect` 返回目标、实际数量/资金/仓位偏差，以及每笔订单的确认成交量、
在途状态和原因。`WAITING/PARTIAL/COMPLETED/NOT_EXECUTED/UNKNOWN`描述执行进度；
`terminal`独立标识是否仍有未决订单。COMPLETED仅表示本次订单完成或无需订单，不能当作100%达到目标。
市值及偏差采用调用方明确给定的估值价格，不冒称实时市价。查询要求当前规划证据，旧决策不猜测目标语义。

冻结日频实现由 `planning.session.plan_session_decision` 处理，输入为 `SessionProposal`
及渠道账户、状态快照；历史股票二元目标由 `planning.frozen_equity.plan_frozen_equity`
处理。历史与在线调用同一个规划实现，不在宿主重复资金和数量算法。

日频与盘中重试分别用适用的交易日或交易区间识别上一轮计划。`PREVIOUS_ZERO_FILL`
表示上轮计划已终结且确认成交量为零。是否提交应查上轮委托和渠道状态。PTE 在采纳新计划时
可保存当时引用的上轮决策及委托事实，供策略说明重试原因。计划、渠道受理、终结和确认成交
各自以 EC 记录为准，策略借这些事实撰写说明。见
[PTE 的前瞻事实来源](../paper_trading_engine/README.md#前瞻事实怎样产生)。

## 历史回放渠道

`historical.HistoricalReplayChannel` 仅接受已经准备好的 HFQ 行情与执行约束。
`advance` 推进模拟时钟并确认待执行区间，`snapshot` 提供账户、持仓周期、策略状态、
已确认事件和预算，`adopt` 采纳 `HistoricalDecision` 并返回 `ADOPTED`、
`ALREADY_ADOPTED`、`STALE_SNAPSHOT` 或 `BLOCKED`。采纳本身不制造成交；
`finish` 拒绝未完成或失败的区间，避免把中断回放报告为成功。

历史区间的模拟成交、账本修订号校验与状态推进一并确认；当前区间失败则回滚该区间，
之前已经确认的区间保留。重复计划不会产生重复成交，复用身份但改变内容会报错。
执行事实在绑定时拒绝缺失或无时区时间。宿主续跑身份包含规范化执行约束；同一约束的
时间字符串表示或行顺序变化不改变身份，切换未来区间的规则则不能接续原账户状态。
交易成本、买入后可卖时间、结算、整数步长与数字成交量上限保持。历史账户不识别、缩放或入账拆股、合股与派息。

应用的 V4 回放入口在 `src/czsc_trader/application/account_replay.py`，衔接 SRT 的计算和 EC 的账户。
旧V2 RAW技术回放入口明确要求迁移至HFQ V4，不作为失败后的替代通道；
EC 不导入或回调 SRT。旧 TXE 的历史实现已迁至本包，不保留旧包转发接口。

## 核心验证

聚焦验证覆盖 CN 决策采纳、原子预占/回滚、计划依赖、重启和幂等；US 验证覆盖累计成交、
未知提交恢复、手续费差异、现金平账及执行区间拒绝。测试通过不代表生产发布或真实渠道操作授权。

[账户退役用例](tests/functional/test_retirement_liquidation.py)按市场、旧账户／V4及结算政策
建立不可变数据库种子；每例复制后使用独立连接和券商状态，保留真实 WAL、事务与重启。
拒单等待及人工确认后恢复由同一生命周期场景覆盖；双市场成交、可卖量、撤单、结算和迁移
边界独立保留。用例不得通过关闭持久化或共享可变账户降低耗时，也不依赖 PTE 测试路径。

## HFQ 历史模型与目标仓位边界

`TradeIntent` 只有 `target` 和 `explanation`。`plan_account_decision` 显式接收执行参考价、
`ExecutionPolicy`、`cycle_budget` 与 `locked_quantity`，不从解释中提取订单参数。
`TARGET_POSITION` 支持目标权益比例和持仓后不追加的全现金模式；`FROZEN_RULE` 复用冻结规则；
`INTRADAY_OVERLAY` 复用核心仓位和依赖腿。EC负责报价、费用预算、取整、股数和资金。
`signal_cash_fraction` 的首次正目标本身是开仓资金比例，预算锁定到退出；历史快照暴露
`budget` 和 `locked_quantity` 供下一次规划使用。无法买入最低单位返回明确的规划受阻结果，保留目标并继续账户处理。

`PortfolioHistoricalExecutor(price_basis="HFQ")` 拒绝 RAW 和公司行动参数。
报价、成交、估值及账户使用 HFQ 和整数模拟单位，不缩放行情、不降低手数、不使用小数股。
结果标记 `price_basis=HFQ`、`quantity_basis=SIMULATED_INTEGER_UNITS`；`account_entries`
只保留 `SALE_SETTLEMENT`。数字成交量上限是模拟容量约束，不承诺模拟单位与真实股数等价。
模拟渠道则独立使用 RAW 执行、富途事实账户；数量对账变化标记 `POSITION_ADJUSTMENT`
及 `reason=UNKNOWN`，不推断公司行动；未知现金差额归渠道平账账户。

`PaperStore.reconcile_equity_positions` 仅接收已确认的渠道实际数量。多个策略账户按原持仓比例和
最大余数分配整数变化，余数以账户ID稳定排序；存在未确认订单、缺少归属或旧账不一致时阻断。
账本、成本、活动周期、预算目标、数量锁和可卖锁在同一事务更新，并记录
`CHANNEL_POSITION_RECONCILED`。旧 `apply_equity_event`、`record_v4_action` 接口已删除。
