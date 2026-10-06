# S012 · MANDATE · 3

研究员声明状态：COMPLETE
归属：研究任务治理

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容


| 项目 | 类别 | 内容 | 确认状态 | 强类型约束 |
| --- | --- | --- | --- | --- |
| tradable_symbol | TRADABLE_SYMBOL | S012研究518850.SH。 | CONFIRMED | — |
| stage_scope | CONSTRAINT | 注册S012并开展阶段一任务与评价合同确认。 | CONFIRMED | — |
| success_targets | OBJECTIVE | 三项同时满足：扣除成本后净年化收益≥BuyHold净年化收益×1.5；最大回撤幅度严格小于BuyHold；全区间闭合交易总数×60÷评价交易日数≥5。 | CONFIRMED | (ResearchTarget(target_id='net_annual_return', metric=&lt;ResearchMetric.NET_ANNUAL_RETURN: 'NET_ANNUAL_RETURN'&gt;, lower=BenchmarkBound(multiplier=1.5, inclusive=True), upper=None, when=None), ResearchTarget(target_id='drawdown', metric=&lt;ResearchMetric.DRAWDOWN_MAGNITUDE: 'DRAWDOWN_MAGNITUDE'&gt;, lower=None, upper=BenchmarkBound(multiplier=1.0, inclusive=False), when=None), ResearchTarget(target_id='frequency', metric=&lt;ResearchMetric.FULL_SAMPLE_FREQUENCY: 'FULL_SAMPLE_FREQUENCY'&gt;, lower=ConstantBound(value=5.0, inclusive=True), upper=None, when=None)) |
| frequency_window | HORIZON | 交易频率以60个交易日折算平均值；未闭合持仓不计数。 | CONFIRMED | frequency_window_days: [60.0, 60.0] trading_days |
| history_policy | HORIZON | 使用全部可用历史；核验覆盖后由用户确认具体起止日期。 | CONFIRMED | — |
| evaluation_dates | HORIZON | 评价范围：2020-06-05至2026-09-30，共1535个交易日；组件预热减少起始区间时须披露，策略与基准采用相同实际评价区间。 | CONFIRMED | — |
| benchmark_policy | EXECUTION | 以518850.SH买入持有为可投资基准，在评价首个可成交日开盘买入并持有。 | CONFIRMED | — |
| benchmark | BENCHMARK | 完整基准执行合同为NextOpenBuyHold(lot_size=100)；首个可成交日开盘尽量满仓买入并预留0.1%买入成本，保留余款，期末持仓按市值评价。 | CONFIRMED | {'benchmark_id': 'BuyHold', 'kind': 'BUYHOLD', 'execution_version': 'buyhold-execution-v1', 'execution': {'type': 'NextOpenBuyHold', 'lot_size': 100}} |
| trading_rules | EXECUTION | 单标的择时、只做多、不加杠杆、每侧成交额0.1%成本、限价买入、市价卖出。 | CONFIRMED | — |
| initial_capital | EXECUTION | 策略与BuyHold初始资金均为100000元，交易单位100份。 | CONFIRMED | initial_capital: [100000.0, 100000.0] CNY |
| execution_details | EXECUTION | 决策周期、限价公式、订单有效期及仓位规则由RSCH在后续研究中确定，每次实验前显式声明；新增或改变已确认约束仍须用户批准。 | CONFIRMED | — |
| research_scope | OBJECTIVE | 围绕黄金ETF收益和风险机制检验竞争解释；三个成功标准共同约束，不增设其他经济硬门。 | CONFIRMED | — |
| data_scope | DATA_PERMISSION | 允许使用既有获授权DFLS/Tushare数据、公开文献及现有研究依赖；全部已查看历史属于开发池。新增外部数据源或依赖另行申请。 | CONFIRMED | — |
| resources | RESOURCE | 采用本机半核并发预算max(1, (os.cpu_count() or 1) // 2)，各库和进程统筹使用；阶段一仅核验可用性，后续研究在阶段获批后执行。 | CONFIRMED | — |

tradable_symbol 确认来源：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>)

stage_scope 确认来源：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>)

success_targets 确认来源：[attachments/materials/user_confirmation_20261004_01.json](<attachments/materials/user_confirmation_20261004_01.json>)

frequency_window 确认来源：[attachments/materials/user_confirmation_20261004_01.json](<attachments/materials/user_confirmation_20261004_01.json>)

history_policy 确认来源：[attachments/materials/user_confirmation_20261004_01.json](<attachments/materials/user_confirmation_20261004_01.json>)

evaluation_dates 确认来源：[attachments/materials/user_confirmation_20261004_02.json](<attachments/materials/user_confirmation_20261004_02.json>)

benchmark_policy 确认来源：[attachments/materials/user_confirmation_20261004_01.json](<attachments/materials/user_confirmation_20261004_01.json>)

benchmark 确认来源：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>)

trading_rules 确认来源：[attachments/materials/user_confirmation_20261004_01.json](<attachments/materials/user_confirmation_20261004_01.json>)

initial_capital 确认来源：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>)

execution_details 确认来源：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>)

research_scope 确认来源：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>)

data_scope 确认来源：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>)

resources 确认来源：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| confirmed_target_count | 3 | count | AVAILABLE | — |
| daily_coverage | 2020-06-05/2026-09-30 | date_range | AVAILABLE | — |
| daily_sessions | 1535 | trading_days | AVAILABLE | — |
| daily_missing_sessions | 0 | count | AVAILABLE | — |

confirmed_target_count 证据：[attachments/materials/user_confirmation_20261004_01.json](<attachments/materials/user_confirmation_20261004_01.json>) `180b4a05386a337cc747bb1f1fb14f433a88c6db0c7392439cd592445ee8c3c7`

daily_coverage 证据：[attachments/materials/data_coverage_v1.json](<attachments/materials/data_coverage_v1.json>) `c2c65ca4d96192a23cce438f095c867f396e39a5aafeef98c6e76fa005aadb2c`

daily_sessions 证据：[attachments/materials/data_coverage_v1.json](<attachments/materials/data_coverage_v1.json>) `c2c65ca4d96192a23cce438f095c867f396e39a5aafeef98c6e76fa005aadb2c`

daily_missing_sessions 证据：[attachments/materials/data_coverage_v1.json](<attachments/materials/data_coverage_v1.json>) `c2c65ca4d96192a23cce438f095c867f396e39a5aafeef98c6e76fa005aadb2c`

## 解释

**FACT**：用户已确认三个经济目标、评价区间、资金与基准参数，以及执行细节、数据与资源的研究授权范围。阶段一合同完整，阶段二推进待用户批准。

- confirmed_target_count：3 count
**FACT**：三组补充参数的直接确认依据见用户回复03。

- 支持证据：[attachments/materials/user_confirmation_20261004_03.json](<attachments/materials/user_confirmation_20261004_03.json>) `f7336eb8f9b5e4300285b7937753f0ee54fc3ced22487561c3f23c3eb495c868`
**FACT**：DFLS日历、不复权日线及后复权日线均READY；两种价格序列覆盖全部1535个开市日，无缺失、额外或重复日期。

- daily_coverage：2020-06-05/2026-09-30 date_range
- daily_sessions：1535 trading_days
- daily_missing_sessions：0 count
**RESEARCH_JUDGMENT**：本次仅核对数据可用性，未计算策略或基准绩效。正式实验必须重新绑定数据身份和实际截止日；本次READY不代表所有研究输入因果可用。

- 支持证据：[attachments/materials/data_coverage_v1.json](<attachments/materials/data_coverage_v1.json>) `c2c65ca4d96192a23cce438f095c867f396e39a5aafeef98c6e76fa005aadb2c`
**RESEARCH_JUDGMENT**：后复权因子的历史发布时间及修订历史未经核实；若用作信号输入，应先核验决策时点可得性。不复权价格用于实际成交与账户估值。

- 支持证据：[attachments/materials/data_coverage_v1.json](<attachments/materials/data_coverage_v1.json>) `c2c65ca4d96192a23cce438f095c867f396e39a5aafeef98c6e76fa005aadb2c`
**RESEARCH_JUDGMENT**：频率使用平台FULL_SAMPLE_FREQUENCY；滚动窗口中位数及低分位频率仅作诊断。收益目标按用户给定倍数直接计算，未额外添加基准正收益条件。

**RESEARCH_JUDGMENT**：当前会话包含平台开发背景及少量其他研究摘要；未直接读取其他策略批次档案，不将这些背景作为S012证据或复用其机制参数。


## 未完成事项


## 复算

调用validate_delivery核验本修订和前驱；核对用户原始回复、数据身份与日历差集。覆盖核验代码再次运行必须使用后继输出，不覆盖既有审计文件。

数据访问：本次通过DFLS公共Dataflows.fetch访问既有Tushare行情和SSE日历，仅保存覆盖与来源元数据；正式研究输入将在受管实验中获取并留证。

确定性及容差：合同及附件哈希确定；供应商数据可能修订，后继核验应记录新身份。无绩效计算。

- 环境：[attachments/materials/research_defaults.json](<attachments/materials/research_defaults.json>) `c0c0cbd3febca78bb0e5885a4737efe9d1b2e3ab85ae0a575c308bc4afd3f255`
- 环境：[attachments/deliverables/check_data_coverage.py](<attachments/deliverables/check_data_coverage.py>) `759954d581ab98e7b8ac18b41ad8d02d9ac625ff0e2d787f830a9d703601e0e4`
- 环境：[attachments/deliverables/mandate_v3.py](<attachments/deliverables/mandate_v3.py>) `39e72a230cd1bbe99330e5cdc2a7f589477543a3c61726363ed03673c8061115`
