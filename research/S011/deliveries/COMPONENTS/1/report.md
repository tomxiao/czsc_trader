# S011 · COMPONENTS · 1

研究员声明状态：PARTIAL

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：20260929_S011_EX01；用途：HISTORICAL_REFERENCE；回执：`2cfdb869fe0c2b41b1048b58655e423c53cf2e7618d154a26491db9d42633473`
- 实验证据：20260929_S011_EX02；用途：HISTORICAL_REFERENCE；回执：`d3bb256adbcb32cd09cdc7eca5a03c813c7741de2b9c2d49a71d7018c497c96e`
- 实验证据：20260929_S011_EX04；用途：HISTORICAL_REFERENCE；回执：`23c60187b0f7d94f0c54f513d6942e94b55f9a37d55db6443f0b8d2e7f072985`
- 实验证据：20260929_S011_EX06；用途：HISTORICAL_REFERENCE；回执：`b4b23abbca57b32e33be1f3de4111b0e31215c0caefc651e4ffb9323f3ff1b27`
- 实验证据：20260929_S011_EX07；用途：HISTORICAL_REFERENCE；回执：`18f9ba9232e5a8379573151ff151ba7fd2427ee98cd5c77c88d9a8f36018c395`
- 实验证据：20260929_S011_EX08；用途：HISTORICAL_REFERENCE；回执：`a71f701ef6a7a418081f91067d9f826315bbcf70ebc23961631b365c8932b6bb`
- 实验证据：20260929_S011_EX10；用途：HISTORICAL_REFERENCE；回执：`e4a532e7cc888cd5d770bb4c0e2cf41ce37cff0a731792197922d2e85bd9e78c`
- 实验证据：20260929_S011_EX12；用途：HISTORICAL_REFERENCE；回执：`19f9d2da8376080b046864ff01df40ed0be56506685e5c0c4252456126a8b067`

4个原职责组件完成正式引用迁移。历史执行和当前正式引用分别标识；不增加独立样本，不等于完整策略。

### S011-COMP-01

职责：OPPORTUNITY

研究判断：沪深300短期反向机会背景；Close_000300(T) / Close_000300(T-1) - 1；1/3-day raw and partial ranking positive in all three review segments; Three-day fixed high-low label spread positive in each segment; Complementary to ETF tail rather than identical information

适用边界：已见开发池内职责限定组件；Latest-segment 1/3-day magnitude prediction worse than training mean; Latest one-day fixed-tail difference slightly negative; Ten-day persistence is not established; Rank/loss evidence is selected development evidence, not independent alpha

标签／期限／对照：return_3 / [1, 3]个交易日 / 原EX12三段复核、训练均值、固定分组和其他组件控制；完整方法见协议。

可用时点／价格口径：Completed T domestic index session, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-01-ROLE：SUPPORTED；继承原职责判断，不宣称重新执行组件检验；原无效路线和失败实验见历史台账。
  - 证据：[experiments/20260929_S011_EX12/role_evidence.csv](<experiments/20260929_S011_EX12/role_evidence.csv>)
  - 证据：[experiments/20260929_S011_EX12/role_folds.csv](<experiments/20260929_S011_EX12/role_folds.csv>)
  - 证据：[experiments/20260929_S011_EX12/definition_checks.csv](<experiments/20260929_S011_EX12/definition_checks.csv>)
  - 证据：[experiments/20260929_S011_EX12/full_screening_ledger.csv](<experiments/20260929_S011_EX12/full_screening_ledger.csv>)
### S011-COMP-02

职责：ENTRY_TIMING

研究判断：ETF尾盘90分钟回吐入场信息；HFQ_Close_15:00(T) / HFQ_Close_13:30(T) - 1；One/three-day rank and fixed-tail effects have the same direction in all review segments; Three-day price-persistence label supports short-lived path interpretation; Independent reconstruction from3408 minute bars agrees with the inherited matrix

适用边界：已见开发池内职责限定组件；Latest-segment magnitude prediction deteriorates; Paired loss confidence interval crosses zero; Five/ten-day continuation and standalone risk-control roles are not established; Same-day ratio cancels common adjustment scale but historic bar revisions remain possible

标签／期限／对照：return_1 / [1, 3]个交易日 / 原EX12三段复核、训练均值、固定分组和其他组件控制；完整方法见协议。

可用时点／价格口径：Completed T session and scheduled adjustment availability at17:00, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-02-ROLE：SUPPORTED；继承原职责判断，不宣称重新执行组件检验；原无效路线和失败实验见历史台账。
  - 证据：[experiments/20260929_S011_EX12/role_evidence.csv](<experiments/20260929_S011_EX12/role_evidence.csv>)
  - 证据：[experiments/20260929_S011_EX12/role_folds.csv](<experiments/20260929_S011_EX12/role_folds.csv>)
  - 证据：[experiments/20260929_S011_EX12/definition_checks.csv](<experiments/20260929_S011_EX12/definition_checks.csv>)
  - 证据：[experiments/20260929_S011_EX12/full_screening_ledger.csv](<experiments/20260929_S011_EX12/full_screening_ledger.csv>)
### S011-COMP-03

职责：RISK_CONTEXT

研究判断：ETF五日平均振幅风险状态；mean((HFQ_High-HFQ_Low)/HFQ_Close over completed sessions T-4 through T)；Future range and adverse-price magnitude are positively related in all review segments; Each segment's standalone prediction improves on training-mean error for both risk labels; Paired risk-loss improvement90percent intervals remain positive

适用边界：已见开发池内职责限定组件；Historical fixed low-state bins are empty in later segments; Expanding linear models underpredict absolute risk in later periods; Future range association is not demonstrated avoided loss; Direction of expected return and exact position-sizing rule are not established

标签／期限／对照：range_5 / [5]个交易日 / 原EX12三段复核、训练均值、固定分组和其他组件控制；完整方法见协议。

可用时点／价格口径：Five completed daily sessions, scheduled adjustment availability at17:00, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-03-ROLE：SUPPORTED；继承原职责判断，不宣称重新执行组件检验；原无效路线和失败实验见历史台账。
  - 证据：[experiments/20260929_S011_EX12/role_evidence.csv](<experiments/20260929_S011_EX12/role_evidence.csv>)
  - 证据：[experiments/20260929_S011_EX12/role_folds.csv](<experiments/20260929_S011_EX12/role_folds.csv>)
  - 证据：[experiments/20260929_S011_EX12/definition_checks.csv](<experiments/20260929_S011_EX12/definition_checks.csv>)
  - 证据：[experiments/20260929_S011_EX12/full_screening_ledger.csv](<experiments/20260929_S011_EX12/full_screening_ledger.csv>)
### S011-COMP-04

职责：CONFIRMATION

研究判断：已完成美股SPX单日风险偏好确认；SPX decimal daily return on latest US source date strictly earlier than China T; missing if lag exceeds10 calendar days；One-day rank, fixed-tail difference and conditional rank are positive in all three review segments; Low correlation with ETF tail and positive residual information after other primary fields; Price-persistence proportion provides secondary, weak corroboration

适用边界：已见开发池内职责限定组件；Primary one-day regression coefficient is negative in the first training window; Magnitude prediction is worse than the mean and the paired improvement interval is negative; EX10 one-day BH q is about0.109 and persistence q about0.159; neither establishes global significance; Discovery persistence association is weak, and longer-horizon discovery directions differ; Previous US session is deliberately delayed; no claim of using current US close

标签／期限／对照：return_1 / [1]个交易日 / 原EX12三段复核、训练均值、固定分组和其他组件控制；完整方法见协议。

可用时点／价格口径：Strictly earlier source date than China decision date, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-04-ROLE：SUPPORTED；继承原职责判断，不宣称重新执行组件检验；原无效路线和失败实验见历史台账。
  - 证据：[experiments/20260929_S011_EX12/role_evidence.csv](<experiments/20260929_S011_EX12/role_evidence.csv>)
  - 证据：[experiments/20260929_S011_EX12/role_folds.csv](<experiments/20260929_S011_EX12/role_folds.csv>)
  - 证据：[experiments/20260929_S011_EX12/definition_checks.csv](<experiments/20260929_S011_EX12/definition_checks.csv>)
  - 证据：[experiments/20260929_S011_EX12/full_screening_ledger.csv](<experiments/20260929_S011_EX12/full_screening_ledger.csv>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |

## 解释


## 未完成事项

- EX12引用的EX01 manifest指纹差异仍未解释；原件和失败验证结果完整保留。

## 复算

用当前公共validate_delivery验证；复算使用新的实验编号，不覆盖已封存EX29。迁移构建脚本见research/S011/formal_migration/revision_01/build_deliveries.py。

数据访问：原S011权限范围；当前复算经DFLS，历史引用按原回执认证。

确定性及容差：原输入逐字节封存；身份和浮点公式版本显式记录。所有研究结果属于已见开发池。

