# S018/C9380 阶段五：技术通过，等待精确冻结批准

Status: TECHNICAL_PASS_AWAITING_FREEZE_APPROVAL

## 结论

在平台提交 `57f925496` 上，固定 C9380 的定义、参数及执行合同，正式调用公开 `inspect_candidate`，候选与最终格式包行为等价、隔离 PTE 运行两个目标均为 **PASS**。已形成可供批准的 S018-v1 精确冻结计划；尚未执行冻结，阶段五待用户批准后完成冻结事务及收口。

本次为 EX067 原生 V4 能力缺口修复后的新实验；[原失败报告](../../../experiments/EX067_20261105/report.md)与 INSPECTION/1 保留。阶段四 [ASSESSMENT/2](../../ASSESSMENT/2/report.md)、C9380 参数、候选登记及历史资格不变。本次没有搜索或重新选优。

## 固定输入与检验范围

- 复用 EX064 中心账户已准备的 8 个数据角色，逐项核对内容哈希，未访问新行情或供应商。
- 开发窗口仍为 2023-01-03 至 2026-10-30。MU/SOXX 后复权辅助价格用于策略观察；MU 未复权价格用于报价、成交和账户估值，公司行动进入真实数量及现金/应收账。
- 每侧费用仍为成交额 0.1%。PTE 金额预期采用四位小数及累计费用差额，修正原协议的金额精度；没有更改费率。
- 原有 5 个场景补齐决策前已知且生效的公司行动和到期支付；增加连续两周期、包含补仓和退出的场景，逐次成交后重启，保留无订单决策日。
- PTE 回报由既有历史模型成交录制并注入，属于隔离合成通道事实，不是券商真实成交或独立前瞻业绩。
- 使用最多 2 个工作进程、240 秒总预算；本次实际 45.70 秒。

协议见 [inspection_protocol.json](../../../experiments/EX068_20261105/protocols/inspection_protocol.json)，输入见 [inspection_inputs.json](../../../experiments/EX068_20261105/others/inspection_inputs.json)，精确合同见 [inspection_scope.json](../../../experiments/EX068_20261105/protocols/inspection_scope.json)。

## 技术结果

行为等价覆盖 961 个决策点、244 个订单、230 笔成交及 95 个闭合周期，候选与最终格式包的观察、决策、订单、成交、公司行动、账户和最终策略状态精确一致，容差为 0。该结论是技术实现等价，不是新增经济验收。

| PTE 场景 | 结果 |
| --- | --- |
| historical-first-buy-partial-duplicate-restart | PASS |
| rejected | PASS |
| unknown | PASS |
| expired | PASS |
| reconciliation-blocked | PASS |
| recorded-two-cycles-with-add | PASS |

标准覆盖项无缺失，连续两周期场景实际覆盖 5 笔成交及状态恢复。完整结果见 [technical_summary.json](../../../experiments/EX068_20261105/others/technical_summary.json)、[inspection_report.json](../../../experiments/EX068_20261105/others/inspection_report.json)及 [inspection_validation.json](../../../experiments/EX068_20261105/others/inspection_validation.json)。

## 待批准的精确冻结计划

拟首次冻结为 **S018-v1**，无父版本，初始资格为 RESEARCH。选型数据截止日为 2026-10-30，计划元数据中的前瞻起始日为 2026-11-06；该日期不代表生产启动承诺。

| 身份 | SHA256 |
| --- | --- |
| 候选 C9380 内容 | `186dffc6fe4df3aec1638030d7c0f65d594b6c9578593c39b5676796fe3c5d4a` |
| 候选登记 | `55b0f366422789959d822913acd2718884dbb1ce37e04983e6fcfcf60da10970` |
| 本次技术检验报告 | `db4744d3c893c2570a211e16c398394bda693d3481f6996984286cbd6633b41c` |
| 精确冻结计划 | `2b1a664203176f58f82dd4c106ef90c08fe6f3a8dce4aaae5e855819c8ae7030` |
| 待冻结发布版本 | `3157c3cc7744a24a77f5119cfd4b8ed60e557854f14f62bbf78677f845fb7772` |
| 待冻结包 | `994d23f4a7c12f1963c0d006c3f92f8062bd9b3ab5f25bbda860aa8c47f28e7e` |

[freeze_approval_plan.json](../../../experiments/EX068_20261105/protocols/freeze_approval_plan.json)完整列出待批准对象、计划、运行绑定和包内文件。批准后只提交检验保存的同一发布字节，并核对真实 COMMITTED 回执；当前没有生成正式冻结版本。

## 剩余边界与下一步

技术检验仅覆盖已声明历史窗口与 6 个隔离场景。阶段四披露的开发样本复用、时点可得性及跨时期稳定性限制保持，不能将技术 PASS 解释为未来收益保证。

当前检验执行支持限价买入及限价/市价卖出；市价买入、带前置依赖的订单明确拒绝，C9380 不使用这两类表达。富途美股模拟通道、旧冻结策略原地升级、生产版本升级及账户绑定仍是后续独立实施事项，本次未部署或修改生产。

根据 [RSCH 指南第 3.5 节](../../../../RSCH_AGENT.md#35-阶段五技术检验与获批冻结)：“冻结必须具备完整计划、通过检查，并取得用户对候选、内容、检验报告、计划及版本的精确批准。”本轮“同意”授权继续正式阶段五检验，发生于上述新报告与计划生成之前；因此下一步呈请用户批准本计划冻结为 S018-v1。

本次技术检验目标已达成；阶段五等待精确冻结批准。正式交付 INSPECTION/2 标记 PARTIAL，待冻结项明确列出，原交付保留。
