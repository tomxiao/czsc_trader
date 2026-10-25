# 模拟交易引擎（Paper Trading Engine，PTE）

本文面向策略研究员（RSCH），说明前瞻观察事实的含义与使用边界。
账户、服务、Futu渠道和生产发布的操作属于独立授权的DEV/运维任务，见
[DEV Agent](../../docs/DEV_AGENT.md)及[PTE运维手册](../../docs/PTE_OPERATIONS.md)。

## 资金模式与代码兼容

PTE按SRT计划中的目标份额和订单执行，不重新计算策略目标比例。原有`full_available_cash`、
`available_cash_fraction`继续使用`target_scope=entry_cycle`；新增`target_equity_fraction`须使用
`target_scope=decision`且`allocation_fraction=1`，用于[SRT多档位目标仓位](../strategy_runtime/README.md#执行计划)。
资金模式与作用范围不匹配时明确拒绝；部分减仓不结束仍有持仓的周期。

支持新模式的PTE代码继续接受原有计划。旧PTE不识别新模式，不能直接消费新多档位计划；
使用前须同步升级SRT/PTE运行包，并按现有流程检验、冻结、部署及取得PTE资格。
`target_equity_fraction`沿用`advice.v4`普通订单结构。
本地代码更新不代表生产运行包已升级，不会自动改写既有冻结策略或生产账户。

### 信号决定投入比例、按开仓周期锁定

`signal_cash_fraction / entry_cycle`使用`advice.v6`。策略通过`CycleTarget`给出本次可用现金投入比例；
SRT产生无副作用的计划，PTE在采纳决策的同一事务中保存`EntryCycleState`：周期身份、开仓信号身份、
投入比例、含买入费用的现金预算、目标份额、累计实际买入成本和`ACTIVE / EXITING`状态。
`cycle_target`、`entry_cycle_before`、`entry_cycle_after`、`cycle_status`均为显式传输字段；
`identity_facts`保留原始Decimal字符串价格、分配比例、可用现金和费用率，以及信号目标与价格身份，接收端结合可执行订单
重新核验信号与计划哈希。缺字段、篡改、模式与版本错配均拒绝。旧模式序列化不增加这些字段。

当前数据库schema为6，`virtual_accounts.entry_cycle_json`保存可恢复周期状态。启动迁移只新增可空字段，
不从旧`cycle_target`推断资金预算。新模式首次采纳要求空仓、无旧周期目标且全部历史意图已终结。
采用前核对当前账户状态与`entry_cycle_before`一致，并核对周期身份属于当前账户和开仓信号；
重复采纳同一决策不覆盖成交后状态。决策、订单、成交和账本通过`decision_id`追溯周期身份。

未成交及部分成交后重试沿用原预算与份额；持有时信号比例改变仅影响下一周期。
累计成交新增部分及其费用在成交账本事务中计入`buy_cost_including_fees`，重复回报不重复扣款。
实际成本超预算仍保留真实事实，剩余预算归零并阻止继续补买。退出后只在持仓为零、全部相关意图和
渠道订单已终结、报告累计成交全部入账时释放周期；未知结果、撤单未完成或未入账成交均继续保留状态。
不足一手不建立周期。账户升级、生产迁移和新模式实际生效仍按独立授权执行。

## 正常限价未成交与执行异常

限价买单因计划时窗结束而撤单，且渠道明确回报`CANCELLED_ALL`、累计成交与账本均为零、
无渠道错误时，可以正常结束本次尝试。PTE要求对应订单具有引擎产生的`CANCEL_REQUESTED`
审计，`details.reason=planned_deadline`，且不存在人工撤单记录。请求来源在调用渠道前持久化；
请求成功、经过截止时间或单独一个取消状态都不代表已确认正常终结。

带`submit_before`的计划单沿用原截止时间；普通`DAY`限价买单在有效交易日15:00之后，
对仍有效的渠道订单请求撤单。恢复运行后也会处理已超过截止时间的活动单，不提前结束成交窗口。
若渠道先自行取消且没有可核验的到期撤单来源，本版本仍保留人工确认；不按收盘时间猜测取消原因。

确认正常零成交后，订单保留渠道原始状态，意图`payload.termination_reason=NORMAL_UNFILLED`，
`attention_required=false`；决策为`INCOMPLETE / NORMAL_UNFILLED`，控制台显示“正常未成交”。
剩余冻结资金只释放一次，持仓、实际成交费用和入场周期预算保持真实事实。不新增账户阻塞，
也不清除无关阻塞或暂停。重复回报和服务重启不重复释放资金，不重新产生人工确认事项。

同交易日同计划不重新挂单。入场周期由`OPEN`变为`HOLD`导致计划哈希变化时，如果同一信号
及可执行订单、计划腿均未改变，也复用已结束的尝试。下一交易日由SRT新决策决定是否再次买入，
PTE不自动追价或强制补单。依赖该买单`FILLED_ALL`的未提交卖单记为`SKIPPED_DEPENDENCY`，
原因为`DEPENDENCY_NOT_TRIGGERED`，追加`EXECUTION_PLAN_LEG_SKIPPED`审计，不卖出原有底仓。

拒单、提交失败、部分成交撤单、人工撤单、卖单失败及本地漏提交维持原人工确认边界。
提交、订单或撤单结果未知时继续阻塞、保留未释放资金并对账；后续明确终态才能结束不确定性。
订单、资金或持仓不一致时仍阻止新单。`release_account_intent`在存储事务内根据真实回报、账本和
审计分类，不接受“忽略阻塞”的调用参数；`SKIPPED_DEPENDENCY`只接受有上述正常零成交依赖证据的
未提交卖单。`update_channel_order_report`仍接收原始渠道事实，不接受调用方指定终结解释。

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

`InspectionControl.max_workers`默认取本机逻辑核的70%（向下取整、至少1），
显式值覆盖默认值。TDR完成等价性并行回放并关闭其工作进程后，将同一预算传给PTE，
不会在父子检验叠加并发预算。PTE场景及恢复/连续路径目前顺序执行，每个子进程原生线程为1，
运行摘要如实记录`effective_workers=1`；资源上限不表示强制创建同等数量的进程。

本检验只支持声明环境和场景的部署运行结论，不证明生产已启用、真实券商可连接、真实流动性或收益。
协议、字段及存储设计见[阶段五公共契约](../../docs/superpowers/specs/2026-10-22-stage5-public-contracts.md)。

## 前瞻事实怎样产生

每个账户绑定一个不可变策略版本、标的和Futu模拟渠道。SRT根据该版本声明准备策略数据，
生成目标仓位及执行计划；PTE按账户保存决策、订单意图、Futu订单、成交回报和账本。渠道
受理委托不等于成交，只有明确的累计成交增量才能改变现金与持仓。未知订单结果或账户对账
异常时必须阻止新单，不能把部分成功汇总为成功。

PTE前瞻观察图由三类事实组成：SRT随决策输出的`strategy_observation.v1`解释序列、PTE通过
DFLS独立获取的行情背景，以及账户订单、成交和持仓。图表由PTE统一渲染，不读取候选包中的
前瞻图代码，也不解析SRT私有准备数据。独立行情只用于展示，不能反向改变策略计算。

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
