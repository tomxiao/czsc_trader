# 执行渠道（Execution Channels，EC）

EC 拥有交易规则、订单规划与渠道账户。输入为宿主已经准备的执行事实和策略意图；
不依赖 DFLS、SRT、PTE，也不负责数据查询、策略计算或调度。

## 富途 A 股、美股模拟渠道

`futu.channel.ChannelAccountConfig` 明确绑定市场、币种、模拟账户与交易时段。
`futu.futu_execution.ChannelExecution` 共享订单提交、未知提交结果恢复、累计成交归并、
现金与持仓对账，市场差异通过明确的渠道配置处理。账本位于 `futu.store.PaperStore`，
按渠道和策略账户隔离；现金差额归平账账户的既有规则保持不变。

`futu.adoption.DecisionAdoption` 是不可变决策文档与账户身份；
`AccountAdoption.adopt` 在事务内写入状态、估值快照、资金预占与订单意图，返回
`AdoptionResult` 中明确的决策和意图身份。宿主可在已有版本检查事务内调用，
采纳失败会与本次替换及资源变化一起回滚。

`futu.v4_admission.prepare_v4_adoption` 在采纳前校验执行腿、确认可卖数量、手数、价格单位、
日期价格限制和周期剩余预算，构造待提交账户状态与费用估计；这些规则不在 PTE 重算。
`decision_snapshot` 从已确认账本和卖出锁定时点生成权威账户快照。

`futu.equity_execution` 为阶段五受控成交提供相同账本的隔离执行适配。
`InspectionAccountPermit` 只认可指定的隔离目录和发布身份，不能用于正式账户。

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
A 股价格边界必须由逐日事实明确提供，美股使用明确的无涨跌停声明。

`planning.plan_account_decision` 接收 `TradeIntent`、决策点、账户快照和执行政策，
统一计算 V4 数量、委托价格、周期预算与计划身份。SRT 只产生策略意图和待采纳状态，
应用负责 `serialization.to_record/from_record` 的类型投影。字段类型、未知字段、
价格与数量边界在执行域校验；投影不重新计算策略。

冻结日频实现由 `planning.session.plan_session_decision` 处理，输入为 `SessionProposal`
及渠道账户、状态快照；历史股票二元目标由 `planning.frozen_equity.plan_frozen_equity`
处理。历史与在线调用同一个规划实现，不在宿主重复资金和数量算法。

## 历史回放渠道

`historical.HistoricalReplayChannel` 仅接受已经准备好的行情、执行约束和公司行动事实。
`advance` 推进模拟时钟并确认待执行区间，`snapshot` 提供账户、持仓周期、策略状态、
已确认事件和预算，`adopt` 采纳 `HistoricalDecision` 并返回 `ADOPTED`、
`ALREADY_ADOPTED`、`STALE_SNAPSHOT` 或 `BLOCKED`。采纳本身不制造成交；
`finish` 拒绝未完成或失败的区间，避免把中断回放报告为成功。

历史区间的模拟成交、账本修订号校验与状态推进一并确认；当前区间失败则回滚该区间，
之前已经确认的区间保留。重复计划不会产生重复成交，复用身份但改变内容会报错。
执行事实在绑定时拒绝缺失或无时区时间。宿主续跑身份包含规范化执行约束；同一约束的
时间字符串表示或行顺序变化不改变身份，切换未来区间的规则则不能接续原账户状态。
交易成本、买入后可卖时间、结算、拆股数量换算以及交易收入账本沿用渠道的计算规则。
现金派息不计入历史交易收益；输入筛选由研究宿主按已确认的收益口径完成。

应用的 V4 回放入口在 `src/czsc_trader/application/account_replay.py`，冻结二元目标入口在
`src/czsc_trader/application/frozen_equity_replay.py`。它们衔接 SRT 的计算和 EC 的账户，
EC 不导入或回调 SRT。旧 TXE 的历史实现已迁至本包，不保留旧包转发接口。

## 核心验证

聚焦验证覆盖 CN 决策采纳、原子预占/回滚、计划依赖、重启和幂等；US 验证覆盖累计成交、
未知提交恢复、手续费差异、现金平账及执行区间拒绝。测试通过不代表生产发布或真实渠道操作授权。
