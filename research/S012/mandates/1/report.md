# S012 · MANDATE · 1

研究员声明状态：PARTIAL
归属：研究任务治理

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容


| 项目 | 类别 | 内容 | 确认状态 | 强类型约束 |
| --- | --- | --- | --- | --- |
| tradable_symbol | TRADABLE_SYMBOL | 研究标的518850.SH（华夏黄金ETF）；用户确认代码，交易所身份由官方资料核对。 | CONFIRMED | — |
| stage_scope | CONSTRAINT | 注册S012并启动阶段一；当前授权为研究任务与评价合同确认。 | CONFIRMED | — |
| research_question | OBJECTIVE | 建议研究黄金ETF择时能否改善用户关心的收益与回撤；优先级和数值成功标准待确认。 | PROPOSED | — |
| evaluation_horizon | HORIZON | 建议评价全部可用历史；起止日期、开发池与后续数据边界待确认及覆盖核验。 | PROPOSED | — |
| trading_rules | EXECUTION | 沿用角色默认：单标的择时、只做多、不加杠杆、每侧0.1%成本、限价买入、市价卖出；资金、交易单位、成交时点及限价参数待确认。 | PROPOSED | — |
| data_scope | DATA_PERMISSION | 建议使用现有获授权DFLS/Tushare数据及公开资料；具体数据集、范围与新增外部数据需求逐项明确。 | PROPOSED | — |
| resources | RESOURCE | 建议采用角色默认本机并发预算；正式实验前声明实际资源，阶段一不进行因子筛选或参数搜索。 | PROPOSED | — |

tradable_symbol 确认来源：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>)

stage_scope 确认来源：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| strategy_id | S012 | identifier | AVAILABLE | — |
| tradable_symbol | 518850.SH | symbol | AVAILABLE | — |
| authorized_stage | MANDATE | stage | AVAILABLE | — |

strategy_id 证据：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>) `a983303c14e671383fe4db56ec3f49a285eda7cc7eadb5ce9b6f2806a68e4d10`

strategy_id 证据：[attachments/materials/registration_request.json](<attachments/materials/registration_request.json>) `2c7e677c3f5c34c168fb1062a8d32eafab2871225476b87cde62595eab6d65bd`

tradable_symbol 证据：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>) `a983303c14e671383fe4db56ec3f49a285eda7cc7eadb5ce9b6f2806a68e4d10`

tradable_symbol 证据：[attachments/materials/instrument_identity.json](<attachments/materials/instrument_identity.json>) `0ac6e554e9d994adc82aa89be1d677ac765e28f29302b9277c270ae52f1f3e7c`

authorized_stage 证据：[attachments/materials/stage1_start_authorization.json](<attachments/materials/stage1_start_authorization.json>) `a983303c14e671383fe4db56ec3f49a285eda7cc7eadb5ce9b6f2806a68e4d10`

## 解释

**FACT**：用户已授权注册S012并启动阶段一。当前修订记录立项事实、默认口径和未确定项。

- strategy_id：S012 identifier
- authorized_stage：MANDATE stage
**FACT**：标的名称与交易所已按上交所公开公告核对，尚未读取收益样本或开展研究实验。

- tradable_symbol：518850.SH symbol
- 支持证据：[attachments/materials/instrument_identity.json](<attachments/materials/instrument_identity.json>) `0ac6e554e9d994adc82aa89be1d677ac765e28f29302b9277c270ae52f1f3e7c`
**RESEARCH_JUDGMENT**：建议以本ETF买入持有作为可投资基准，拟在评价首个可成交日开盘买入；仅为建议，完整执行合同待用户确认。

**RESEARCH_JUDGMENT**：默认行为依据当前RSCH契约；PROPOSED表示S012合同细节尚未逐项确认，不将默认规则或研究诊断转换为额外经济硬门。

- 支持证据：[attachments/materials/research_defaults.json](<attachments/materials/research_defaults.json>) `c0c0cbd3febca78bb0e5885a4737efe9d1b2e3ab85ae0a575c308bc4afd3f255`
**RESEARCH_JUDGMENT**：当前会话包含平台开发背景、其他策略名称及少量历史研究摘要；本次未直接读取其他策略批次档案。这些背景不作为S012研究证据，不复用其他策略的机制或参数结论。


## 未完成事项

- 明确研究职责、收益与风险优先级，以及机制探索范围。
- 确认净年化收益、最大回撤和交易频率目标；频率须说明交易日统计窗口和计数方式。
- 确认评价区间、数据截止日及开发池范围，并核验可用数据覆盖。
- 确认518850.SH买入持有基准及其资金、交易单位、首次成交时点和执行参数后，加入强类型BenchmarkRequirement。
- 明确策略限价买入、市价卖出的执行时点、价格参数、资金和交易单位。
- 确认具体数据权限及资源范围；完成合同后由用户决定是否进入阶段二。

## 复算

使用公开validate_delivery核验本修订；对照附件中的原始授权、标的身份、默认规则快照和交付实现。后续确认生成新修订，不覆盖本修订。

数据访问：本次仅访问公开标的身份资料和平台合同，未拉取行情或访问生产状态。

确定性及容差：文件和合同哈希确定性校验；本修订不含绩效计算。

- 环境：[attachments/materials/research_defaults.json](<attachments/materials/research_defaults.json>) `c0c0cbd3febca78bb0e5885a4737efe9d1b2e3ab85ae0a575c308bc4afd3f255`
- 环境：[attachments/deliverables/mandate_v1.py](<attachments/deliverables/mandate_v1.py>) `12714f9af2f3de838d6561b10f4f495c3326280eb732356bd9f41742decb1eea`
