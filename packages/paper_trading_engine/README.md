# 模拟交易引擎（Paper Trading Engine，PTE）

本文面向策略研究员（RSCH），说明前瞻观察事实的含义与使用边界。
账户、服务、Futu渠道和生产发布的操作属于独立授权的DEV/运维任务，见
[DEV Agent](../../docs/DEV_AGENT.md)及[PTE运维手册](../../docs/PTE_OPERATIONS.md)。

## 与执行渠道 EC 的边界

PTE 负责调度、发布绑定、Web 运维和策略计算编排；SRT 返回策略提议，PTE 通过
`ec_boundary` 将明确的记录投影为 EC 自有类型，再调用 EC 的统一订单规划。
`execution_channels.futu` 统一承担 A 股、美股模拟渠道的富途适配、累计成交归并、
账户账本、资金预占、订单生命周期、对账及相关执行审计。原 PTE 对应实现文件已移除，
调用方应引用 EC 的业务模块。旧模块路径及原包级执行类型导出均已删除，不保留转发或兼容别名。

决策采纳由 EC `AccountAdoption.adopt(DecisionAdoption)` 完成：同一事务内保存决策与
账户状态、估值快照及订单意图。PTE 在调用前仍持有账户版本检查和替换决策事务，
保证计算期间账户变化会阻止采纳。富途累计回报及真实余额仍是模拟渠道的执行依据；
EC 不导入 DFLS 或 SRT，也不自行查询数据。PTE 的 `ScheduledDecision` 留在
`scheduling_contracts`，用于宿主日历调度，不是 EC 的交易执行合同。

隔离检验使用宿主许可投影得到的 EC `InspectionAccountPermit`，保留发布哈希、协议哈希和
隔离目录约束。正式账户与隔离账户继续使用同一账本及成交处理逻辑。

策略账户退役复用 `POST /api/virtual-accounts/{account_id}/retire`，以控制令牌、
当前发布哈希、操作者和原因受理。账户进入 `RETIRING` 后停止策略加载、数据准备、
新决策和恢复操作，EC 继续处理撤单、成交回报、对账、市价清仓及资金回笼。
退役不要求旧策略通过当前 SRT 合同，也不生成策略目标仓位决策。
已暂停账户在平台启动时延迟策略加载，同时停止自动和人工数据准备、决策；恢复后完整校验。旧合同策略上线前应先
经授权暂停。正常运行账户仍须通过启动校验。
尚在处理返回 HTTP 202，完成返回 HTTP 200；账户快照的 `retirement` 字段展示
`DRAINING`、`WAITING_MARKET`、`WAITING_SELLABLE`、`LIQUIDATING`、
`WAITING_SETTLEMENT`、`BLOCKED`、`RETIRED` 及剩余股数、已回笼资金和原因。
只有 `RETIRED` 表示清仓、结算和回笼均已完成；请求受理不保证即时成交。

`retirement_calendar` 独立准备 DFLS 交易日历，再投影为 EC `RetirementSession`；
不加载冻结策略。V4 使用已登记运行绑定的日历源与费率；旧账户使用环境中该市场
唯一的正式日历源及最后持久决策中明确保存的费率。A 股午休分段、美股提前收市和
下一结算交易日均取日历事实；资料缺失明确阻断清仓，不推测交易日，也不影响其他账户对账。
空仓账户的退役无需行情或日历。未决订单、实际可卖量及实际成交由 EC 和富途处理，
资金回到所属渠道资本池，历史记录保留。操作方法见[PTE 运维手册](../../docs/PTE_OPERATIONS.md)。

V4决策在 `strategy_output.execution_plan` 留存原目标与EC规划结果。资金不足或可卖量不足
可以形成受约束计划或无单受阻计划，仍采纳决策并保存金融状态；HOLD/WAIT或零订单不代表目标已达成。
`PaperStore.decision_execution_effect(account_id, decision_id, valuation_price=..., at=...)`
从确认账本返回执行进度、实际仓位、资金和目标偏差，CN与US模拟渠道共用该入口。
已提交、部分成交、订单完成和结果未知分别呈现；需要人工或券商核实的未知订单保持未决，不自动重发。
查询只返回当前确认账户，不能用过去的at伪装历史快照；估值价格由调用方明确提供。

现有账户快照 API 的 `decision.execution_effect` 返回 EC 执行效果；控制台在原决策摘要和
详情中展示目标／实际仓位、偏差、约束和执行状态。`availability=UNAVAILABLE` 表示旧决策
缺少规划证据，不推测补齐。可用结果的 `scope=CURRENT_ACCOUNT_VS_DECISION` 表示当前确认
账户与所选决策比较，`price_basis=RAW`、`valuation_source=DECISION_EXECUTION_REFERENCE`
及 `valuation_at` 标明该决策的执行参考价和观测时点；`as_of` 是查询时点，不能解释为实时行情
或该决策发生时的历史账户。`COMPLETED` 只表示可执行订单完成或无需调整，不保证目标精确达成。

## 资金模式与代码兼容

SRT 计算策略目标，EC 规划目标份额和订单，PTE 编排执行。原有`full_available_cash`、
`available_cash_fraction`继续使用`target_scope=entry_cycle`；新增`target_equity_fraction`须使用
`target_scope=decision`且`allocation_fraction=1`，用于[SRT多档位目标仓位](../strategy_runtime/README.md#执行计划)。
资金模式与作用范围不匹配时明确拒绝；部分减仓不结束仍有持仓的周期。

支持新模式的PTE代码继续接受原有计划。旧PTE不识别新模式，不能直接消费新多档位计划；
使用前须确认SRT/PTE运行包支持该契约，并按获准的首次冻结或同版本升级流程形成发布包，
再核对部署与精确发布身份的PTE资格。
`target_equity_fraction`沿用`advice.v4`普通订单结构。
本地代码更新不代表生产运行包已升级，不会自动改写既有冻结策略或生产账户。

### 信号决定投入比例、按开仓周期锁定

`signal_cash_fraction / entry_cycle`使用`advice.v6`。策略通过`CycleTarget`给出本次可用现金投入比例；
SRT 产生策略提案，EC 在采纳决策的同一事务中保存`EntryCycleState`：周期身份、开仓信号身份、
投入比例、含买入费用的现金预算、目标份额、累计实际买入成本和`ACTIVE / EXITING`状态。
`cycle_target`、`entry_cycle_before`、`entry_cycle_after`、`cycle_status`均为显式传输字段；
`identity_facts`保留原始Decimal字符串价格、分配比例、可用现金和费用率，以及信号目标与价格身份，接收端结合可执行订单
重新核验信号与计划哈希。缺字段、篡改、模式与版本错配均拒绝。旧模式序列化不增加这些字段。

当前数据库schema为8，`virtual_accounts.entry_cycle_json`保存可恢复周期状态。周期状态迁移只新增可空字段，
不从旧`cycle_target`推断资金预算。新模式首次采纳要求空仓、无旧周期目标且全部历史意图已终结。
采用前核对当前账户状态与`entry_cycle_before`一致，并核对周期身份属于当前账户和开仓信号；
重复采纳同一决策不覆盖成交后状态。决策、订单、成交和账本通过`decision_id`追溯周期身份。

未成交及部分成交后重试沿用原预算与份额；持有时信号比例改变仅影响下一周期。
累计成交新增部分及其费用在成交账本事务中计入`buy_cost_including_fees`，重复回报不重复扣款。
实际成本超预算仍保留真实事实，剩余预算归零并阻止继续补买。退出后只在持仓为零、全部相关意图和
渠道订单已终结、报告累计成交全部入账时释放周期；未知结果、撤单未完成或未入账成交均继续保留状态。
不足一手不建立周期。账户升级、生产迁移和新模式实际生效仍按独立授权执行。

## 双市场隔离技术检验

A 股与美股原生 V4 隔离检验使用独立数据库和显式许可，复用正式
`FormalV4AdviceClient → AccountEngine → ChannelExecution → PaperStore` 链路。
仅将外部券商、时钟和运行存储替换为受控环境；拒单、未知回报、资金释放及健康状态采用正式实现。
`FormalV4AdviceClient` 的 `inspection_permit` 只允许加载指定隔离目录中身份匹配的待冻结包；
普通入口仍要求正式安装记录和模拟交易资格，不为检验创建虚假的 `PAPER_READY` 资格。
离线 `RecordedInspectionBroker` 按协议提供合成回报及撤单确认，仅验证平台处理能力，
不代表连接真实富途完成交易验收。此入口只接受原生 V4，旧 RAW 合同在执行前拒绝。
`prepare_equity_decision` 认证 SRT 的 HFQ 行情、辅助行情及观察表；独立的
`ExecutionReferenceBinding` 指定 DFLS RAW 行情请求、准备引用和内容指纹，生成
`PreparedExecutionReference`。该 RAW 价格只进入 EC，不能放进 SRT 输入绑定或上下文。
两种价格必须对应同一已完成观察时间，缺失或过期数据明确阻断。

`EquityPteInspectionProtocol` 保存决策、独立对账快照、累计成交回报、卖出款交收和重启场景。
`inspect_equity_release` 显式接受 `execution_reference`；它先校验发布包与隔离许可，再调用
正常业务组件。通过需要完整成交、部分成交、重复回报、重启、明确拒绝、未知提交结果、
时窗过期和对账阻断覆盖。未知提交结果保留冻结资金，不能解释为拒单或自动重发。

不读取或应用分红、拆合股事件。卖出款按声明的现金交收规则处理；富途现金残差仍由渠道平账账户承接。
实际股数以确认成交后的渠道对账结果为准，无法确定原因的差额明确记录为 UNKNOWN；
不可归属持仓或未确认交易必须阻断。正常服务不能打开隔离检验数据库。

## 双市场正式模拟运行

`futu_simulate_cn` 与 `futu_US_sim_channel` 共用调度、决策采纳、虚拟账户、平账、订单、成交和审计链路。
`ChannelAccountConfig` 显式绑定本地渠道账户 ID、渠道、富途账户 ID 和 `RTH / ETH` 时段。
美股仅接受具备 US 权限的股票期权保证金模拟账户，但执行预算只使用确认现金及可卖股数，不使用融资购买力。
CN 使用 CNY、上海时间和百股步长；US 使用 USD、纽约时间和整数股。ETH 只接受限价 DAY 订单，
还必须位于策略的数据日历及执行区间内；渠道允许盘前盘后不改变冻结策略原来的执行时段。

schema 8 将历史记录归入 `futu-cn-default`，保留旧订单 ID。新渠道订单 ID 带渠道账户前缀，
向富途发送查询及撤单时还原原始 ID。现金、冻结、平账、设置、审计和监控失败均按渠道账户隔离；
根存储不提供跨币种资金合计。控制台顶部市场开关统一切换虚拟账户、模拟渠道、审计事件、账户比较和活动告警。
调度按各自日历生成稳定任务 ID，以有界工作池执行；每个账户串行、各渠道独立退避。

同版本升级的 schema 2 包通过经 SRT 认证的 `runtime_candidate_id` 加载当前候选；历史
`source_candidate` 只表示原冻结来源，不用于构造运行键。schema 1 包按原协议读取。
隔离检验中，显式订单腿到期后正常返回 `NO_ORDER` 的语义保持不变；若本次提交确实将尚待提交的
intent 转为 `EXPIRED`，记录该状态转换并计入过期能力覆盖。过去已经过期的 intent、拒单或未知
提交状态不能提供这项覆盖，保存事实复核也核对转换及订单时间窗。

已部署且精确发布身份具备 `PAPER_READY / LIVE_READY` 的原生 V4，可创建正式模拟账户。
V4 可声明 `DatasetObservationInput` 观察表，使用 `EquityInputBinding.observation_bindings`
保存完整 DFLS 请求与内容指纹。成分权重、资金流、宏观及指数数据保持表格复合主键，不伪造 OHLCV；
技术检验、研究回放和正式决策复用同一可用时点裁剪。日期型发布必须显式声明时区、发布时间和日期偏移，
市场开盘时间不能替代数据实际可用时间；严格前日快照、滞后及填充仍由冻结策略规则决定。

`FormalV4Inputs` 使用 schema 3，独立保存 SRT 的 HFQ `binding` 与 PTE 的 RAW `execution_reference`。
`strategy_requests` 仅交给 SRT；`requests` 包含两类独立请求，用于 DFLS 准备。自动配方按观察表自身的
发布时点推进查询范围，资金流先用声明交易日历生成日期集合；冻结种子保持原固定区间，
通过包内相对路径和指纹解析。新一轮准备只生成新的区间绑定，已采用区间复用原内容，重启不重新取数。
缺数据、声明与绑定不符或资源内容漂移明确失败；观察数据不能替换 RAW 执行行情。旧输入配方明确拒绝，须显式迁移。
后复权周线请求使用完整源交易周日历，只包含已经过该周最后开市日收盘的周；周中不把临时周线
当作完整周，周五休市和整周长假按日历处理。研究与正式准备复用同一周界计算，发布时间声明仍同时生效。

动态观察的可选 `required_from` 明确种子覆盖期间尚未启用的增量输入。正式配方在其发布时间前
保留 INACTIVE 绑定，不发送该观察的物理请求、不生成内容指纹；启用后从 `history_start` 读取预热
并生成真实请求及内容身份。已采用区间仍固定原绑定；启用后缺数据明确失败，不能继续当作未启用。
该状态和可用时点计算由 CN/US 研究、隔离技术检验与正式 PTE 共用。

EC 根据冻结的 `execution_policy` 和目标仓位生成 `ReplayLeg`，支持基于已持有库存的日内依赖执行。每条腿保留带时区的提交子时间窗，
后续腿只有在声明的前序腿确认全部成交后才可提交；部分成交、未知或失败不能视为依赖完成。
该条件在历史 EC及PTE统一写为 `FILLED_ALL`。前腿撤销、失败或提交窗过期不会激活后腿；
部分成交或未获明确回报继续保留未解决状态，重启也不能将其解释为全部成交。
计划采纳时提前预留全部买腿所需现金，不依赖未来卖出收入。重启及重复回报继续沿用既有意图、
成交和周期预算记录，依赖执行不改变冻结策略的核心持仓数量及信号计时规则。

正式与隔离运行复用 SRT 目标仓位决策和 EC 的执行反馈、订单回报入账核心。
SRT 只计算后复权行情并输出仓位和解释；EC 使用独立的未复权参考价决定报价、股数、预算和依赖订单。
不识别 T 日与 T+1 日之间的除权除息事件，接受旧报价可能无法成交或产生损失；下一次已完成行情更新后
重新生成报价。平台不据此改变策略信号或执行规则。
日线 `DAILY_FORWARD_V2` 配方只取已完成交易日行情及可得日历，每个执行区间保存固定绑定。
自动 M30 准备仍需要 DFLS 部分交易时段产品，当前明确拒绝；显式准备的 M30 技术检验保持支持。
EC V4 账户文档使用 schema 2，`locked_quantity` 与周期预算由 EC 持久化；策略私有状态不承载数量锁。
旧文档必须通过显式 `V4StateMigration.execution_locked_quantity` 迁移，禁止运行时猜测字段含义。

维护命令使用数据库单写锁，应在服务停止时运行。`pte channel list / status` 只读本地快照，不连接富途。
`register` 接受 `--definition` JSON：

```json
{"account":{"channel_account_id":"us-main","channel_id":"futu_US_sim_channel","broker_account_id":123,"session":"RTH"},"capital":"10000","fee_policy":{"max_variable_rate":"0.01","max_fixed_fee_per_order":"5","rounding_tolerance":"0.01"}}
```

示例中的账户和费用上限仅说明字段，使用前必须按目标账户明确配置。费用策略是现金差额归因边界，不是实际费率。
富途美股模拟不提供费用明细时，只有成交和现金变化能唯一解释且在配置边界内才记入平账账户，标记 `INFERRED_CASH`；
无法解释、无对应成交或超界则阻断。策略账本保留模型费用，不将推导费用伪称渠道明细。

其余命令均显式传入 `--channel-account-id`，并沿用公共 `--database / --data-dir / --repo-root`：

- `create-v4 --definition`：字段为 `account_id/name/strategy_id/strategy_version/release_hash/symbol/asset/fee_rate/initial_cash`，新账户暂停。
- `bind-inputs --definition` 固定输入，或 `bind-recipe --definition` 注册连续日线准备；字段为 `account_id/release_hash/fee_rate/binding`，其中 `binding` 使用 `EquityInputBinding.to_dict()`。
- `prepare-data --account-id --interval-start --interval-end --as-of` 以带时区的时间戳准备当前 V4 配方的 DFLS 数据。按实际 `as_of` 和执行区间起点中较早的时点选择历史价格与观察输入。结果包含准备引用及逐请求状态，账户库以只读方式打开。准备引用可用于数据审计，正式执行区间仍由调度器独立采纳。
- `pause-account / resume-account --account-id` 仅改变指定策略账户运行状态；启用要求冻结绑定、已注册输入和现有账户健康检查通过。
- `pause / resume` 仅改变渠道状态；恢复必须先完成富途对账。渠道恢复不连带启用策略账户。

注册、输入绑定及代码交付均不等于生产部署或账户生效；既有冻结包升级和生产切换按单独批准的维护方案执行。

### 正式 V4 数据源配置与重绑

在宿主 `--config-root` 下用 `equity-sources.json` 注册行情、交易日历及动态数据。下方域名和来源名称仅用于展示配置结构。账户配方中的角色和 `SourceRef(provider, revision)` 必须对应实际注册项。

```json
{
  "schema_version": 2,
  "sources": [
    {"market": "CN", "adapter": "TUSHARE_CN", "provider": "cn-feed", "revision": "v1"},
    {"market": "US", "adapter": "FUTU_US", "provider": "us-feed", "revision": "v1"},
    {"market": "CN", "adapter": "DYNAMIC_FACTS", "provider": "cn-facts", "revision": "v1", "endpoint": "https://cn.example.test/equity", "calendar_source": {"provider": "cn-feed", "revision": "v1"}},
    {"market": "US", "adapter": "DYNAMIC_FACTS", "provider": "us-facts", "revision": "v1", "endpoint": "https://us.example.test/equity", "calendar_source": {"provider": "us-feed", "revision": "v1"}}
  ]
}
```

`DYNAMIC_FACTS` 在 DFLS 内部按请求查询可交易状态及价格上下限。宿主的报价连接在首次取数时建立，同一宿主共享并在退出时关闭。固定市场规则随 EC 平台制品分发，独立于 DFLS 配置。接口和覆盖要求见 [DFLS](../dataflows/README.md) 和 [EC 市场规则](../execution_channels/README.md)。

账户重绑时用新版输入配方显式绑定 `trading_facts`。生产来源缺失或请求不完整会导致数据准备失败。发布前需要逐市场核实真实动态来源及其覆盖范围。

离线维护使用 `update_account_bindings(runtime_root, target_release_id, updates)`。原 `AccountBindingUpdate` 继续服务旧账户合同。原生 V4 请求使用 `V4AccountBindingUpdate`，显式携带当前与目标发布身份、渠道、账户事实指纹、生效区间、目标规则、`FormalV4Inputs` 和状态处理方式。用 `account_binding_facts_sha256` 取得已暂停账户的事实指纹。

- 首次迁入 V4 使用 `V4StateMigration`。已确认的仓位周期取自真实成交及账本，策略私有字段和证据由调用者提供。迁移边界前已结清的公司行动随原账本保留，跨边界待支付的股息需要先核对。
- 已运行 V4 账户可以重绑同版本的新哈希或同策略族的后继版本。兼容状态使用 `V4StateContinuation`，字段变更使用显式 `V4StateMigration`。两者均核对旧发布身份，延续确认周期、预算及已确认账户事件游标。
- 所有目标账户及生效配方在一个 SQLite 事务中切换，返回 `COMMITTED`。相同计划重试返回 `ALREADY_APPLIED`。配方由同一数据库记录持久化，运行、重启和发布预检读取同一身份。历史区间和原已采纳决策保留用于追溯，调度从新绑定的生效区间开始。

发布快照完整保留冻结包和部署记录。`strategies/deployments/` 根目录组成当前发布集合，
执行运行合同验收；`deployments/history/` 保存退出集合的凭据原件，只验证凭据、版本、
源码闭包和包哈希，不加载旧策略。尚未部署且未转入历史集合的 V4 包仍执行技术校验。
当前 S002-v1、S003-v1 转入历史集合，不删除冻结包、资格历史或账户账本。

只读发布预检对当前集合账户验证精确发布资格、执行规则、输入配方与已确认持仓。
历史集合账户须处于 `PAUSED` 或 `RETIRING`，只核验发布哈希、选型截止日及包完整性；
`RUNNING` 历史账户阻断发布，`RETIRED` 账户不参加运行绑定预检。预检返回的 `accounts`／
`releases` 表示已核对的账户数和绑定身份，不授予历史策略运行资格。行情准备由正常调度
或显式维护完成；退出发布集合不会替代账户清仓退役。

### Web API 在线验证

在线验证连接正在运行的 PTE，通过 HTTP 检查发布身份、调度心跳、指定渠道账户的对账状态，以及策略账户绑定和决策。双市场服务提供以下查询：

| 路由 | 验证事实 |
| --- | --- |
| `GET /api/health` | 发布标识、Git 提交、制品清单哈希、实例和调度心跳 |
| `GET /api/channel-accounts/{channel_account_id}/snapshot` | 指定渠道账户的市场、币种、策略账户 ID、资金、平账账户、对账和失败状态 |
| `GET /api/virtual-accounts/{account_id}/snapshot` | 实际渠道归属、发布哈希、决策（含 V4 解释和订单腿）、订单、成交及仓位 |
| `GET /api/audit-events?channel_account_id=…&account_id=…` | 按渠道账户隔离的事件，可继续按 `event_type`、`decision_id` 筛选 |

`channel_account_id` 是注册的渠道账户 ID，例如 `futu-cn-default`，与渠道类型 `futu_simulate_cn` 不同。
控制台通过 `GET /api/channel-accounts?market=CN|US` 发现当前市场的渠道账户；账户列表、比较、系统状态和审计也接受 `market`。
渠道暂停、恢复、获取撤单令牌和撤单分别使用 `POST /api/channel-accounts/{channel_account_id}/{pause,resume,cancel-token,cancel}`，订单和策略账户按注册归属核验。
已移除聚合 `GET /api/status` 和无渠道限定的 `POST /api/{pause,resume,cancel-token,cancel}`。旧 A 股渠道 URL 继续供现有运维调用使用。
运行、维护及技术检验统一使用 `ChannelExecution`，历史导入名 `FutuExecution` 已移除。

现有 `POST /api/virtual-accounts/{account_id}/decision` 接受 JSON `{}`。对 V4，它通过账户所属渠道复用正式日历、区间数据准备和决策采纳逻辑。账户须健康且处于 `RUNNING`；暂停账户禁止人工和自动数据准备、决策。日线决策在 T 交易日实际收盘满 5 小时后才允许准备完整 T 日数据，执行区间仍为下一个交易日，按所属市场日历处理周末、节假日、夏令时及提前收盘。人工驱动遵守同一时间门槛。返回 `DECISION_COMPLETED` 或 `DECISION_REUSED`，附发布哈希、区间、数据身份和决策 ID。它保存正式决策、账户状态及审计，并可产生待提交订单意图；需要阻止渠道提交时使用渠道暂停。重复调用复用当前区间已采纳的决策。运行冲突或无有效区间时返回 HTTP 409。旧 CN 调度配置不得早于 20:00，配置更晚时仍按配置执行；渠道订单轮询和账户对账不因策略账户暂停而停止。

在 PTE 所在宿主用该版本的 Python 执行：

```powershell
python -m paper_trading_engine.online_verify --port 8080 --plan .tmp/pte-verify-plan.json --json-output .tmp/pte-verify-result.json
```

工具默认只发 GET，连接限定为 `127.0.0.1`。下面是单渠道清单示例，执行前填写真实身份与预期；同一清单可增加另一个市场的渠道账户及策略账户。

```json
{
  "release": {
    "mode": "PTE",
    "release_id": "v0.0.0",
    "git_commit": "0000000000000000000000000000000000000000",
    "manifest_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "channels": {
    "futu-cn-default": {"channel_id": "futu_simulate_cn", "market": "CN", "currency": "CNY"}
  },
  "accounts": {
    "example-cn": {
      "channel_account_id": "futu-cn-default",
      "release_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "run_state": "PAUSED"
    }
  }
}
```

如需验收指定的 V4 决策，增加 `decision`，包含带时区的 `interval.start/end`、预期 `action` 和 `target_quantity`，可用 `case_key`、`judgment` 核对决策分支与解释。工具关联数据准备与决策生成事件；缺少对应周期或审计证据时返回 `BLOCKED`。可选的 `quantity`、`orders`、`fills` 分别核对当前持仓及账户累计订单、成交笔数。

仅隔离 DEV 可以显式加 `--drive-dev`。此时 `release` 使用 `{"mode":"DEV","repo_root":"<隔离工作目录绝对路径>"}`，所有目标账户须为 `RUNNING` 并提供预期决策；需要仅验证决策时暂停对应渠道以阻止订单提交。设 `decision.fresh=true` 要求本次实际生成，复用视为不达标。固定时点的双市场闭环使用聚焦测试中的受控时钟和模拟渠道。工具报告逐项 `PASS`、`FAIL`、`BLOCKED`，退出码分别为 0、1、2，输出路径须是新文件。生产恢复顺序见 [PTE 发布与运维](../../docs/PTE_OPERATIONS.md#web-api-在线验收)。

## 尽力执行与账户异常（A 股、美股渠道）

订单因计划时窗结束而撤单，且渠道明确回报`CANCELLED_ALL`或`CANCELLED_PART`、累计成交
与账本一致且无渠道错误时，可以正常结束本次尝试。对应订单须具有引擎产生的`CANCEL_REQUESTED`
审计，`details.reason=planned_deadline`，且不存在人工撤单记录。请求来源在调用渠道前持久化；
请求成功、经过截止时间或单独一个取消状态都不代表已确认正常终结。

带`submit_before`的计划单沿用原截止时间；普通`DAY`限价买单在有效交易日15:00之后，
对仍有效的渠道订单请求撤单。恢复运行后也会处理已超过截止时间的活动单，不提前结束成交窗口。
若渠道先自行取消，只有明确执行区间及不早于区间终点的带时区回报才能确认到期；
缺少这两类证据时保留人工确认，不按本地收盘时间猜测取消原因。US按明确执行区间处理。

确认正常零成交后，订单保留渠道原始状态，意图`payload.termination_reason=NORMAL_UNFILLED`，
`attention_required=false`；决策为`INCOMPLETE / NORMAL_UNFILLED`，控制台展示未执行及正常结束原因。
剩余冻结资金只释放一次，持仓、实际成交费用和入场周期预算保持真实事实。不新增账户阻塞，
也不清除无关阻塞或暂停。重复回报和服务重启不重复释放资金，不重新产生人工确认事项。

同一已终结尝试不重新挂单。V4同一份认证输入、观察时点和执行区间，即使部分成交改变账户
并使重算的剩余订单或计划哈希变化，也复用已结束的尝试。旧入场周期由`OPEN`变为`HOLD`
时，同信号、同有效交易日的已终结计划仍按既有身份规则复用。下一执行周期由SRT新决策决定是否再次买入，
PTE不自动追价或强制补单。依赖该买单`FILLED_ALL`的未提交卖单记为`SKIPPED_DEPENDENCY`，
原因为`DEPENDENCY_NOT_TRIGGERED`，追加`EXECUTION_PLAN_LEG_SKIPPED`审计，不卖出原有底仓。

明确拒单记为`ORDER_REJECTED`，提交前确认现金或可卖量不足记为`EXECUTION_CONSTRAINED`，
本地尚未提交而错过窗口记为`EXECUTION_EXPIRED`，正常到期部分成交撤余记为`NORMAL_PARTIAL`。
这些结果终结本次委托并保留原目标、实际成交和具体原因，不阻断账户或自动重发同单。
部分成交只释放未成交部分的预占资金；依赖完整成交的后续腿不因部分成交而擅自调整数量执行。
人工撤单、缺少终结依据的回报、非法输入及实际安全错误仍需处理。
提交、订单或撤单结果未知时继续阻塞、保留未释放资金并对账；后续明确终态才能结束不确定性。
订单、资金或持仓不一致时仍阻止新单。`release_account_intent`在存储事务内根据真实回报、账本和
审计分类。本地未向渠道提交或渠道已明确拒绝的意图，可传强类型`termination_reason`，
仅允许与当前状态和无渠道订单事实一致的终结原因，不能作为通用“忽略阻塞”开关。
`SKIPPED_DEPENDENCY`须有已确认终结且未满足完整成交条件的依赖证据。
`update_channel_order_report`仍接收原始渠道事实，不接受调用方指定终结解释。

上述信息复用现有意图JSON和审计表，不新增HTTP接口或数据库字段。启动回填只保留已明确记录的
正常终结，不批量放行历史取消单、改写历史研究证据或自动解除生产账户阻塞。

## 何时使用

正式PTE入口只运行已冻结、已部署且具备`PAPER_READY`或`LIVE_READY`资格的策略版本；研究候选包与正式PTE无直接关联。
RSCH可将授权导出的模拟盘事实作为后续研究问题的线索，但不得把同一批前瞻数据重新用于原
版本的参数选择。研究员可在已授权的策略生命周期评审中核对账户决策、执行缺口、绩效快照和
自包含里程碑证据；模拟盘表现不自动改变冻结裁决或策略版本。

冻结、SRT部署、创建PTE账户分别需要相应授权。TDR `deploy_strategy` API只写入SRT部署凭据，
不会创建或驱动PTE账户；在生产环境中操作账户、驱动决策、启停服务和写入数据都需要单独授权。

当前冻结流程返回`FreezeReceipt`，只有`COMMITTED`携带完整版本引用。schema 5版本初始资格为
`RESEARCH`，仍需取得绑定发布哈希的模拟交易批准及部署。PTE的`SrtAdviceClient`只加载schema 5版本，
核验运行资格、部署、版本、发布包和运行绑定；旧schema 1/2/3/4、身份缺失或内容不符时明确失败。
研究决定、技术检验和冻结日志独立保存在研究及实验目录，PTE运行不读取这些材料。
历史发布原件保留供人工查阅，不承诺当前平台机器复验。PTE数据库及启动迁移的兼容范围保持现状，
具体生产版本升级和策略发布仍须独立授权。账户列表和绩效导出读取当前数据库schema的一致性
只读快照；数据库缺失或schema不符时明确失败，不创建数据库或触发迁移。
技术检验、冻结、部署及PTE运行状态分别记录，调用方应分别核对。

同版本发布包升级由[TDR升级API](../../src/czsc_trader/README.md#同版本发布包升级)负责追溯和审计，
不以源码结构、研究等价证明或技术检验PASS作为升级门槛。升级后的新发布哈希从`RESEARCH`资格开始，
不能因策略版本号未变而沿用旧哈希的资格或账户绑定。PTE继续核对精确发布、包和部署身份；
账户改绑与生产生效分别授权，本地升级回执不代表生产已经切换。研究验证结论由RSCH负责。

## 阶段五隔离运行检验

`paper_trading_engine.inspection.inspect_release(PteReleaseInspectionRequest, control=...)`
供TDR阶段五入口调用。RSCH通过TDR提交`PteInspectionProtocol`，明确带时区的决策/提交时点、
`StrategyInputBinding`、渠道累计回报及独立检查点预期。该协议只有固定业务事件，不接受Python、
SQL、任意断言或券商回调。输出`PteInspectionOutcome`分别保存场景、覆盖和受管轨迹文件；
只有TDR认证并发布这些文件后才形成正式研究证据。

输入使用`DataSpaceBinding`和`InspectionInputCopy`显式定位私有DFLS空间及准备引用。映射的
`InputContentIdentity.role`是规范化请求的SHA256键；每个实际请求的隔离内容必须与源内容相等。
输入缺失或身份不符即失败，不联网补取、不借用研究目录中的源码。发布包按正常SRT完整性合同认证。

运行器在`.tmp/strategy-inspection/<run_id>/`内启动有限子进程，调用真实账户准备、SRT决策、
PTE订单处理和SQLite记账代码；外部渠道使用`RECORDED_FILLS_V1`受控模型。模型依据初始资金、
累计成交量/均价及独立累计费用推导现金和持仓，不从PTE账本生成渠道事实。市价单须在提交时
给出完整成交或明确拒绝，不能跨事件悬挂。`expected_orders`是完整策略计划，
`cumulative_order_count`统计全部真实渠道提交调用，包含拒绝和未知结果。

技术许可绑定发布/包/协议身份，账户数据库记录`INSPECTION`准入，不伪造正式`PAPER_READY`。
普通账户数据库入口（含只读入口）拒绝带检验标记的数据库；普通部署入口拒绝测试凭据。
技术许可及测试库不得用于正式PTE服务，不改变既有冻结包和生产账户的格式或资格。

恢复场景重建数据库连接、策略适配器、账户及执行组件，并与不中断路径比较；重复请求和回报
不得增加委托或成交。覆盖必须由实际轨迹及声明检查点支持，未覆盖必需场景返回`INCOMPLETE`。
取消或预算耗尽先停止并等待工作进程，再收集已完成诊断；不返回虚假PASS。

`InspectionControl.max_workers`默认取本机逻辑核的75%（向下取整、至少1），16个逻辑核默认12，
显式值覆盖默认值。TDR完成等价性并行回放并关闭其工作进程后，将同一预算传给PTE，
不会在父子检验叠加并发预算。PTE按独立普通场景及故障场景限额并行，每个场景有独立数据库、
渠道实例及输出目录；包损坏故障操作独立副本。同一场景的重启/连续对照顺序执行，每个子进程原生线程为1。
主进程调度、收集及比较结果，按协议顺序返回场景及证据；一个场景执行失败不阻止其他独立场景。
取消、总超时及控制回调异常停止派发并等待全部活动子进程退出，保留实际完成的结果；无法确认退出时明确失败，不发布完成摘要。
运行摘要`effective_workers`记录峰值活动worker数，未启动进程时为0；资源上限不表示强制创建同等数量的进程。

本检验只支持声明环境和场景的部署运行结论，不证明生产已启用、真实券商可连接、真实流动性或收益。
协议、字段及存储设计见[阶段五公共契约](../../docs/superpowers/specs/2026-10-22-stage5-public-contracts.md)。

## 前瞻事实怎样产生

每个账户绑定一个不可变策略版本、标的和Futu模拟渠道。SRT根据该版本声明准备策略数据，
生成目标仓位及执行计划；PTE按账户保存决策、订单意图、Futu订单、成交回报和账本。渠道
受理委托不等于成交，只有明确的累计成交增量才能改变现金与持仓。未知订单结果或账户对账
异常时必须阻止新单，不能把部分成功汇总为成功。

PTE前瞻观察图由三类事实组成：SRT随决策记录的观察快照、PTE通过DFLS独立获取的行情背景，
以及账户订单、成交和持仓。PTE与TDR复用[共享图表组件](../strategy_chart/README.md)，
按价格、持仓、信号、事件顺序展示，不读取候选包中的前瞻图代码，也不解析SRT私有准备数据。
独立行情只用于展示，不能反向改变策略计算。

`strategy_observation.v4`携带由策略声明并由SRT解析的解释快照；页面直接展示“当前判断、
判断依据、接下来关注”，展开解释仅替换中栏为“怎么看这个判断”。历史v2/v3记录按其原合同读取，
未声明解释时明确标注，不用最新策略或前端规则推断历史原因。观察不可用显示明确原因；
`observe_execution_plan`在隔离观察错误前严格校验策略与执行计划身份。金融语义由RSCH验收，
平台校验声明、值与身份；模型信号不代表账户已经成交。
观察计算及显示字段错误仅隔离为“观察不可用”，保留已成功生成的交易结果；交易计算、资金、订单和
身份校验错误仍严格阻断相应执行。信号区不会展示部分或伪造的解释来掩盖观察失败。

共享静态资源随发布包分发，图表缓存按渲染版本失效。工作区修改不改变生产服务；
冻结策略升级、生产发布及账户改绑分别按授权执行。

图表可能返回`BUILDING`、`REFRESHING`、`READY`、`EMPTY`或`UNAVAILABLE`。这些是图表
生成状态，不是策略收益或账户健康结论；图表失败应结合决策、数据身份和审计记录判断。

## 数据空间与输入绑定

PTE环境配置`shared/config/pte.json`使用schema 1，其中`data_space`声明相对于
`shared/data`的DFLS数据空间，例如`"data_space": "market"`。它必须是非空相对路径，
不能包含`..`或越出数据根目录。空间独立于发布目录，同一环境的日历、策略准备和图表
共用宿主创建的DFLS实例；不同环境使用各自的数据根目录。

WDG使用独立的schema 1配置`shared/config/watchdog.json`，只管理生产根目录及健康检查地址。
每次启动时，WDG核验活动发布身份，调用该发布的`pte serve-runtime`；PTE自行读取`pte.json`，
并转换为`--data-space`等运行参数。WDG宿主与PTE发布独立版本化，不绑定PTE版本。
直接运行PTE时也可通过`--data-space`指定空间，基准为
`--data-dir`。PTE将配置转换为强类型`DataSpace`，供应商配置由宿主提供。业务层只调用
`prepare`和绑定准备引用的`fetch`，不直接解析DFLS内部文件。

PTE先准备日历，再让SRT推导完整输入需求，将整批准备结果绑定为`StrategyInputBinding`。
相同策略、窗口及需求的账户共享该绑定；账户仍各自保留准备记录和决策。同一信号日重试或
服务重启时，读取账户记录中的原绑定；资产损坏或缺失时明确失败，不通过重新取数替换。
新的信号日按新需求准备数据。决策及`MARKET_DATA_PREPARED`审计记录保存完整准备引用，
可关联空间身份、准备记录身份和清单哈希；图表数据不改变这份决策输入。

升级要求：旧服务配置及旧账户准备索引不自动转换。需分别生成WDG和PTE配置，明确数据空间，
并安排schema 3账户准备索引及输入绑定的切换；历史数据和证据原件保留。新版本不读取旧SRT
CSV作为行情来源。生产配置更新、准备记录切换和服务部署仍按独立授权执行。

`shared/data/market/`保存DFLS管理的数据资产；`shared/data/input-bindings/`保存共享输入绑定；
`shared/data/accounts/`保存账户准备索引、记录及计算上下文。这些共同支持策略运行、重启恢复
及审计追溯，不能按临时缓存整体清理。根目录的旧CSV、压缩数据及发布清单继续保留，供历史
审计查阅；保留原件不要求当前版本读取旧格式。目录维护与数据库备份保留策略见
[PTE运维手册](../../docs/PTE_OPERATIONS.md)。

## 阅读决策与绩效

- `DECISION_COMPLETED`表示首次形成该信号日决策；`DECISION_REUSED`表示输入未变而复用记录，
  不代表新成交。
- `DECISION_SUPERSEDED`及`DECISION_AND_INTENTS_SUPERSEDED`表示以新事实追加替代旧决策或
  尚未提交渠道的意图；已有渠道订单或结果未知时不得覆盖。
- 决策、订单、成交、账户快照和前瞻执行缺口需要按关联身份一起阅读；净值图不能代替成交
  对账或投资判断。
- PTE生产状态在独立运行环境，不由Git工作树、研究档案或本地开发数据库推断。

区间绩效以所选首个快照之前最近一个账户快照的总资产为期初；从完整观察序列起点计算时
使用开户资金。导出证据的`initial_capital`表示区间期初资产，`source.opening_assets`保存期初
依据，开户资金保存在`source.account.initial_cash`。观察数和年化状态保存于`source.statistics`；
不足20个观察快照时不提供年化指标，零回撤时Calmar比率（年化收益与最大回撤之比）
未定义，以`None`保存。

研究权限见[RSCH Agent](../../research/RSCH_AGENT.md)，生产操作按DEV独立授权。

## 测试与回归

退役测试分工：EC 验证清仓、成交和资金账本；本模块验证策略停调度、真实交易日历、
Web 202／200、CLI 状态和账户快照。资金回笼、事务回滚及控制令牌保留真实存储／HTTP链路。
原生 V4 前瞻集成复用按市场及版本形态生成的不可变冻结包；每例仍独立准备 DFLS 输入、
复制发布包并创建账户，不共享审批、运行状态或可变行情。准备不改账断言由前瞻主场景承接。

聚焦入口见[宿主退役](tests/functional/test_retirement_host.py)、
[回笼与控制接口](tests/functional/test_account_retirement.py)和
[原生 V4 前瞻](../../tests/functional/test_formal_v4_runtime.py)。
全仓验收统一使用[回归脚本](../../scripts/test-all.ps1)，保留发布包验收、前端用例与 Ruff；
失败修复后只补测受影响用例，并分别记录首次全仓结果与补测证据。
