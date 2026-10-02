# S011 · COMPONENTS · 1

研究员声明状态：PARTIAL
归属：20261002_S011_EX34

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：20261002_S011_EX34；用途：CURRENT_EVALUATION；回执：`585404811cce879b743d80a19e35fb4bcf71566359063691d0450452c6519dfa`

4个职责组件由EX34当前受管复算承接；63角色检验、189折及留月统计重现原数值。广泛筛选台账仅作历史附件，不增加独立样本。

### S011-COMP-01

职责：OPPORTUNITY

研究判断：沪深300短期反向机会背景；Close_000300(T) / Close_000300(T-1) - 1；1/3-day raw and partial ranking positive in all three review segments; Three-day fixed high-low label spread positive in each segment; Complementary to ETF tail rather than identical information

适用边界：已见开发池内职责限定组件；Latest-segment 1/3-day magnitude prediction worse than training mean; Latest one-day fixed-tail difference slightly negative; Ten-day persistence is not established; Rank/loss evidence is selected development evidence, not independent alpha

标签／期限／对照：return_3 / [1, 3]个交易日 / EX34按EX12既定三段、训练均值、固定分组和其他组件控制重新计算；完整方法见协议。

可用时点／价格口径：Completed T domestic index session, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-01-ROLE：SUPPORTED；EX34重新执行9定义、7标签与63角色检验，核对原数值；原全部筛选路线和失败实验保留为历史附件。
  - 证据：[experiments/20261002_S011_EX34/role_evidence.csv](<experiments/20261002_S011_EX34/role_evidence.csv>)
  - 证据：[experiments/20261002_S011_EX34/role_folds.csv](<experiments/20261002_S011_EX34/role_folds.csv>)
  - 证据：[experiments/20261002_S011_EX34/definition_checks.csv](<experiments/20261002_S011_EX34/definition_checks.csv>)
  - 证据：[experiments/20261002_S011_EX34/leave_month.csv](<experiments/20261002_S011_EX34/leave_month.csv>)
### S011-COMP-02

职责：ENTRY_TIMING

研究判断：ETF尾盘90分钟回吐入场信息；HFQ_Close_15:00(T) / HFQ_Close_13:30(T) - 1；One/three-day rank and fixed-tail effects have the same direction in all review segments; Three-day price-persistence label supports short-lived path interpretation; Independent reconstruction from3408 minute bars agrees with the inherited matrix

适用边界：已见开发池内职责限定组件；Latest-segment magnitude prediction deteriorates; Paired loss confidence interval crosses zero; Five/ten-day continuation and standalone risk-control roles are not established; Same-day ratio cancels common adjustment scale but historic bar revisions remain possible

标签／期限／对照：return_1 / [1, 3]个交易日 / EX34按EX12既定三段、训练均值、固定分组和其他组件控制重新计算；完整方法见协议。

可用时点／价格口径：Completed T session and scheduled adjustment availability at17:00, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-02-ROLE：SUPPORTED；EX34重新执行9定义、7标签与63角色检验，核对原数值；原全部筛选路线和失败实验保留为历史附件。
  - 证据：[experiments/20261002_S011_EX34/role_evidence.csv](<experiments/20261002_S011_EX34/role_evidence.csv>)
  - 证据：[experiments/20261002_S011_EX34/role_folds.csv](<experiments/20261002_S011_EX34/role_folds.csv>)
  - 证据：[experiments/20261002_S011_EX34/definition_checks.csv](<experiments/20261002_S011_EX34/definition_checks.csv>)
  - 证据：[experiments/20261002_S011_EX34/leave_month.csv](<experiments/20261002_S011_EX34/leave_month.csv>)
### S011-COMP-03

职责：RISK_CONTEXT

研究判断：ETF五日平均振幅风险状态；mean((HFQ_High-HFQ_Low)/HFQ_Close over completed sessions T-4 through T)；Future range and adverse-price magnitude are positively related in all review segments; Each segment's standalone prediction improves on training-mean error for both risk labels; Paired risk-loss improvement90percent intervals remain positive

适用边界：已见开发池内职责限定组件；Historical fixed low-state bins are empty in later segments; Expanding linear models underpredict absolute risk in later periods; Future range association is not demonstrated avoided loss; Direction of expected return and exact position-sizing rule are not established

标签／期限／对照：range_5 / [5]个交易日 / EX34按EX12既定三段、训练均值、固定分组和其他组件控制重新计算；完整方法见协议。

可用时点／价格口径：Five completed daily sessions, scheduled adjustment availability at17:00, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-03-ROLE：SUPPORTED；EX34重新执行9定义、7标签与63角色检验，核对原数值；原全部筛选路线和失败实验保留为历史附件。
  - 证据：[experiments/20261002_S011_EX34/role_evidence.csv](<experiments/20261002_S011_EX34/role_evidence.csv>)
  - 证据：[experiments/20261002_S011_EX34/role_folds.csv](<experiments/20261002_S011_EX34/role_folds.csv>)
  - 证据：[experiments/20261002_S011_EX34/definition_checks.csv](<experiments/20261002_S011_EX34/definition_checks.csv>)
  - 证据：[experiments/20261002_S011_EX34/leave_month.csv](<experiments/20261002_S011_EX34/leave_month.csv>)
### S011-COMP-04

职责：CONFIRMATION

研究判断：已完成美股SPX单日风险偏好确认；SPX decimal daily return on latest US source date strictly earlier than China T; missing if lag exceeds10 calendar days；One-day rank, fixed-tail difference and conditional rank are positive in all three review segments; Low correlation with ETF tail and positive residual information after other primary fields; Price-persistence proportion provides secondary, weak corroboration

适用边界：已见开发池内职责限定组件；Primary one-day regression coefficient is negative in the first training window; Magnitude prediction is worse than the mean and the paired improvement interval is negative; EX10 one-day BH q is about0.109 and persistence q about0.159; neither establishes global significance; Discovery persistence association is weak, and longer-horizon discovery directions differ; Previous US session is deliberately delayed; no claim of using current US close

标签／期限／对照：return_1 / [1]个交易日 / EX34按EX12既定三段、训练均值、固定分组和其他组件控制重新计算；完整方法见协议。

可用时点／价格口径：Strictly earlier source date than China decision date, used at T20:30 / 信号/标签遵循EX12原复权合同；账户成交尚不在阶段二证明范围内。

- S011-COMP-04-ROLE：SUPPORTED；EX34重新执行9定义、7标签与63角色检验，核对原数值；原全部筛选路线和失败实验保留为历史附件。
  - 证据：[experiments/20261002_S011_EX34/role_evidence.csv](<experiments/20261002_S011_EX34/role_evidence.csv>)
  - 证据：[experiments/20261002_S011_EX34/role_folds.csv](<experiments/20261002_S011_EX34/role_folds.csv>)
  - 证据：[experiments/20261002_S011_EX34/definition_checks.csv](<experiments/20261002_S011_EX34/definition_checks.csv>)
  - 证据：[experiments/20261002_S011_EX34/leave_month.csv](<experiments/20261002_S011_EX34/leave_month.csv>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |

## 解释


## 未完成事项

- EX12引用的EX01 manifest指纹差异仍未解释；本次新复算不修复历史引用。
- 广泛筛选及二元路径未全量重跑，原台账与负面证据作为历史附件；组件检验仍属已见开发池。

## 复算

用公共validate_delivery验证；新实验复算，不覆盖封存原件。组装源码见附件build_current_deliveries.py；只读验收执行本实验verify_deliveries.py --sealed。

数据访问：原S011权限范围；当前复算经DFLS；历史原件仅按显式原字节哈希引用，不承诺旧回执机器复验。

确定性及容差：原输入逐字节封存；身份和浮点公式版本显式记录。所有研究结果属于已见开发池。

