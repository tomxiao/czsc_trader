# 交易执行引擎（Trading Execution Engine，TXE）

本文面向策略研究员（RSCH）和平台开发者（DEV）。平台实现与测试入口见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

TXE 是统一成交执行器，位于 DFLS 同一基础能力层。它接收SRT决策及执行计划，生成可审计的
订单、成交、费用、现金、持仓和净值事实，供研究复算及候选／版本回测共同使用。

## 能力边界

TXE 负责：

- 按 SRT 已确定的订单类型、参考价和委托价执行市价单或限价单；
- 对交易者不利的滑点处理；
- 费用、现金、持仓和净值的确定性记账；
- 对非法价格、数量、费率、滑点和目标仓位明确失败。

TXE 不负责：

- 生成策略信号或目标仓位；
- 获取、发布或修补行情数据；
- 搜索参数或评价策略优劣；
- 管理策略版本、PTE账户或券商订单状态。

PTE仍以渠道成交回报作为模拟账户事实来源。TXE用于研究与回测的统一执行口径，
不能替代Futu订单与成交对账。

## 使用入口与结果

RSCH正式比较策略时，通过TDR的`context.evaluation.evaluate(EvaluationRequest)`或
`run_backtest(context, strategy, request)`取得完整账户事实。由SRT生成逐日计划、TXE执行。
需要自行组织合成或专门回放场景时，可
直接使用TXE公共接口：

- `HistoricalExecutor`：实现SRT的`WindowExecutor`协议，向SRT提供逐日账户快照，接收
  `ExecutionPlan`并管理历史订单、成交、费用、账户状态和完整账本；研究参数搜索、候选/冻结
  策略回测、TDR复核共用这条执行链路；
- `resolve_fill(...)`：根据订单与历史行情判断单笔委托是否成交；
- `execute_target_positions(...)`：供受控数值场景使用的仓位序列辅助接口，按交易日开盘生成订单、
  费用和账户日状态。

后两者是数值能力接口；正式策略回放由 `StrategyInstance.run_window(...)` 驱动
`HistoricalExecutor`，不能用简化仓位收益替代完整执行证据。SRT决定委托类型、参考价、委托价
和生效时点，TXE根据历史行情完成触发、成交、滑点和记账。TDR指定评价窗口、初始资金和
执行数据；回测调用方还必须显式提供与策略执行合同一致的`lot_size`。TDR负责审计、报告与图表。

结果应同时核对订单、成交、费用、现金、持仓和逐日净值；只看信号收益或最终净值不足以判断
执行可行性。限价触碰默认采用保守的严格穿越规则；如研究协议明确要求“触价即成交”，必须
显式传入`inclusive_touch=True`并在证据中记录。PTE模拟账户仍以Futu成交回报为准。

阶段四由TDR将受管TXE事实转换为SE的`AssessmentEvidence`，保留实际成交、费用、周期和
账户轨迹；阶段五技术检验还会重放拟冻结版本并进行独立账本审计与经济等价比较。
调用方不改写原始订单或成交ID来制造一致性，比较时的身份归一化由SE在内部副本完成。

## 整手数量与完成状态

`execute_target_positions(..., lot_size=100)`要求`lot_size`为正整数，拒绝`bool`、浮点数、
字符串及非正数。通用辅助接口的`lot_size=None`表示允许小数数量；TDR回测及基准始终显式传入
整手单位，BuyHold与MA5/MA20共享这一数量口径。资金不足一手时保留现金，不生成零数量订单。

`HistoricalExecutor`向SRT返回`ExecutionOutcome`，状态使用
`ExecutionOutcomeStatus.SETTLED`。它表示该计划执行处理完成并已记账，可以包含未成交委托；
订单是否成交、原因及数量仍以明细为准。自定义`WindowExecutor`同样必须返回强类型结果及
匹配的计划身份，失败使用`FAILED`；SRT遇到失败状态会停止窗口执行。

执行器必须在`ExecutionCapabilities`中如实声明`OrderType`枚举元组和检查点能力。
SRT在首次账户快照前检查策略要求，并逐计划复核，避免运行到不支持的订单后才发现能力不足。

## 研究账户评价口径

先核对[TXE公共导出](src/trading_execution_engine/__init__.py)及[SRT公共导出](../strategy_runtime/src/strategy_runtime/__init__.py)。下表为研究评价合同要求，不代表现有执行器自动覆盖全部场景；能力不满足合同时须报告限制并请求用户决定。

| 项目 | 合同要求 |
| --- | --- |
| 决策与成交时间 | T日收盘信息只能驱动之后可执行的订单 |
| 账户价格 | 真实报单、数量、费用及账户估值采用真实市场价格口径 |
| 复权换算 | 不得未经换算将后复权价格用于真实持仓估值 |
| 权益事件 | 账户核算包含分红、拆分等权益事件 |
| 独立窗口 | 按合同重置资金与持仓 |
| 原账户切片 | 单独标识，不作为独立窗口回测 |
| 比较口径 | 基准和策略分别声明日期、价格、成本、资金、订单及整手规则 |
| 口径差异 | 显式披露，不擅自替换研究基准 |
| 账本 | 下单、成交、持仓和收益分别记录 |

研究流程以[RSCH Agent](../../research/RSCH_AGENT.md)为准；TDR公共调用示例见[TDR说明](../../src/czsc_trader/README.md)。
