# S012 · COMPONENTS · 1

研究员声明状态：COMPLETE
归属：EX005_20261004

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：EX001_20261004；用途：HISTORICAL_REFERENCE；回执：`07f196cd4dfebccf2a1906bb0b7d07f2b9644b1be02d716bf386a692b55dca8a`
- 实验证据：EX003_20261004；用途：HISTORICAL_REFERENCE；回执：`95f4b4dfc2f08ce0a0726dc7f8ac20787a436c25cdec93435950eba90e77f1a1`
- 实验证据：EX004_20261004；用途：CURRENT_EVALUATION；回执：`b4b318ae21c7b9f95c268b7f4a9b5cf1c0620da5f0234c073cdab1bda76187c8`
- 实验证据：EX005_20261004；用途：CURRENT_EVALUATION；回执：`528693224d850de4a288b0c899fe433bdec7da7f4b78a7e52c241fb4d2d5ba31`

阶段二完成：交付三个有明确状态/风险职责的核心组件和两项证据较弱的短期入场候选，连同无效、冗余及技术失败记录。详见附件research_report.md。建议获批后进入阶段三检验完整可证伪策略。

### C01_VOL20

职责：风险尺度与仓位/退出输入

研究判断：控制动量与年份后仍有风险信息；5日IC=0.182、延迟2日=0.160。不能直接推出最优减仓。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来3/5/10/20日最大不利价格幅度 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C01_VOL20_CENSUS：SUPPORTED；volatility_20：控制动量与年份后仍有风险信息；5日IC=0.182、延迟2日=0.160。不能直接推出最优减仓。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C01_VOL20_ROBUSTNESS：SUPPORTED；控制动量与年份后仍有风险信息；5日IC=0.182、延迟2日=0.160。不能直接推出最优减仓。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C02_MOM20

职责：上涨后的回撤风险状态

研究判断：控制波动与年份后仍有风险信息；20日IC=0.226、延迟2日=0.198。强趋势同时可能贡献收益，不机械反向交易。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来3/5/10/20日最大不利价格幅度 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C02_MOM20_CENSUS：SUPPORTED；momentum_20：控制波动与年份后仍有风险信息；20日IC=0.226、延迟2日=0.198。强趋势同时可能贡献收益，不机械反向交易。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C02_MOM20_ROBUSTNESS：SUPPORTED；控制波动与年份后仍有风险信息；20日IC=0.226、延迟2日=0.198。强趋势同时可能贡献收益，不机械反向交易。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C03_KURT60

职责：冲击集中后的风险/收益状态过滤

研究判断：20日收益IC=-0.279、普查q=0.047；延迟2日=-0.282，非重叠及留一年方向稳定。较长标签用于状态判断，不限定实际持仓期限。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来10/20日收益及不利价格幅度 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C03_KURT60_CENSUS：SUPPORTED；fresh60_return__kurtosis：20日收益IC=-0.279、普查q=0.047；延迟2日=-0.282，非重叠及留一年方向稳定。较长标签用于状态判断，不限定实际持仓期限。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C03_KURT60_ROBUSTNESS：SUPPORTED；20日收益IC=-0.279、普查q=0.047；延迟2日=-0.282，非重叠及留一年方向稳定。较长标签用于状态判断，不限定实际持仓期限。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C04_REV1

职责：候选短期入场信息

研究判断：5日IC=0.064，但普查多重调整q约0.331；可进入受控策略比较，不能宣称独立Alpha成立。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来3/5/10日开盘到开盘收益 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C04_REV1_CENSUS：INSUFFICIENT_DATA；reversal_1：5日IC=0.064，但普查多重调整q约0.331；可进入受控策略比较，不能宣称独立Alpha成立。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C04_REV1_ROBUSTNESS：INSUFFICIENT_DATA；5日IC=0.064，但普查多重调整q约0.331；可进入受控策略比较，不能宣称独立Alpha成立。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C05_MOM3

职责：候选短期入场信息

研究判断：5日IC=-0.089，延迟2日=-0.065；多重调整q约0.371，期限稳定性弱于状态组件。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来3/5/10日开盘到开盘收益 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C05_MOM3_CENSUS：INSUFFICIENT_DATA；momentum_3反向：5日IC=-0.089，延迟2日=-0.065；多重调整q约0.371，期限稳定性弱于状态组件。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C05_MOM3_ROBUSTNESS：INSUFFICIENT_DATA；5日IC=-0.089，延迟2日=-0.065；多重调整q约0.371，期限稳定性弱于状态组件。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C06_GAP

职责：与反转比较的短期信息

研究判断：与1日反转秩相关约-0.81；5日收益IC延迟2日从-0.061降至-0.007，下行风险方向反转，不叠加为独立核心组件。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来3/5/10日收益及3/5日下行风险 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C06_GAP_CENSUS：REDUNDANT；opening_gap：与1日反转秩相关约-0.81；5日收益IC延迟2日从-0.061降至-0.007，下行风险方向反转，不叠加为独立核心组件。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C06_GAP_ROBUSTNESS：REDUNDANT；与1日反转秩相关约-0.81；5日收益IC延迟2日从-0.061降至-0.007，下行风险方向反转，不叠加为独立核心组件。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C07_RANGE

职责：替代风险尺度

研究判断：与20日波动相关约0.68，控制后增量区间跨零，优先使用较简单的20日波动。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来3/5/10日不利价格幅度 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C07_RANGE_CENSUS：REDUNDANT；range_5：与20日波动相关约0.68，控制后增量区间跨零，优先使用较简单的20日波动。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C07_RANGE_ROBUSTNESS：REDUNDANT；与20日波动相关约0.68，控制后增量区间跨零，优先使用较简单的20日波动。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C08_AUTOCORR

职责：收益自相关的正向延续解释

研究判断：预设正方向被反证；负方向相关的区间仍跨零，保留全部结果，当前不作为核心组件。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：未来10/20日收益 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C08_AUTOCORR_CENSUS：INEFFECTIVE；fresh20_return__autocorrelation__lag_2：预设正方向被反证；负方向相关的区间仍跨零，保留全部结果，当前不作为核心组件。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
- C08_AUTOCORR_ROBUSTNESS：INEFFECTIVE；预设正方向被反证；负方向相关的区间仍跨零，保留全部结果，当前不作为核心组件。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
  - 证据：[experiments/EX005_20261004/redundancy.json](<experiments/EX005_20261004/redundancy.json>)
  - 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>)
### C09_MACRO

职责：宏观方向与风险信息

研究判断：当前日频滞后与控制口径下未见明确增量；不能从本轮结果推断经济机制不存在。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：3/5/10/20日收益及下行风险 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C09_MACRO_CENSUS：INSUFFICIENT_DATA；real_yield/nominal_yield/fx/vix/shibor各水平与变化：当前日频滞后与控制口径下未见明确增量；不能从本轮结果推断经济机制不存在。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
### C10_RELATIVE

职责：价格偏离和境内市场状态

研究判断：未纳入核心面板。ETF/现货价格比不是ETF净值溢价，期货不使用换月拼接收益。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：3/5/10/20日收益及下行风险 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C10_RELATIVE_CENSUS：INSUFFICIENT_DATA；ETF/SGE相对价格、SGE动量、期货基差与曲线：未纳入核心面板。ETF/现货价格比不是ETF净值溢价，期货不使用换月拼接收益。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
### C11_FLOWS

职责：份额变化与资金流线索

研究判断：年度事件均值存在差异，但控制趋势波动后证据不足；份额变化不等于可交易的即时资金冲击。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：3/5/10/20日收益及下行风险 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C11_FLOWS_CENSUS：INSUFFICIENT_DATA；shares_level/shares_change_5/shares_change_20：年度事件均值存在差异，但控制趋势波动后证据不足；份额变化不等于可交易的即时资金冲击。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)
### C12_REMAINDER

职责：广泛普查及去冗余对照

研究判断：完整保留63个特征和504路径；标准差等与原有波动同义的特征不重复计为新证据，其余未形成足够独立增量。

适用边界：仅限518850.SH、2020-06-05至2026-09-30开发池；成本/限价/仓位及完整账户目标尚未验证。

标签／期限／对照：3/5/10/20日收益及下行风险 / 详见标签和各次固定检验；全期开发池 / 20日动量、20日波动及年份效应；剔除被检验项自身，另报告年度与延迟对照。

可用时点／价格口径：ETF当日收盘后决策、次日开盘标签；外部数据严格早于决策日且最多陈旧7日。 / ETF不复权价格；本区间与后复权价一致；相对价格双腿同源日，期货同日跨期限。

- C12_REMAINDER_CENSUS：INSUFFICIENT_DATA；其余价量路径与tsfresh形态定义，完整列名见feature_definitions.json：完整保留63个特征和504路径；标准差等与原有波动同义的特征不重复计为新证据，其余未形成足够独立增量。
  - 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>)
  - 证据：[experiments/EX004_20261004/fold_metrics.json](<experiments/EX004_20261004/fold_metrics.json>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| features | 63 | count | AVAILABLE | — |
| census_paths | 504 | count | AVAILABLE | — |
| robustness_paths | 96 | count | AVAILABLE | — |
| interaction_cells | 51 | count | AVAILABLE | — |
| vol20_risk5_ic | 0.181756 | rank_correlation | AVAILABLE | — |
| mom20_risk20_ic | 0.225989 | rank_correlation | AVAILABLE | — |
| kurt60_return20_ic | -0.279206 | rank_correlation | AVAILABLE | — |

features 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>) `c21d621de821b22f092c28dddb6b1efb53baa7dc97e162a5b0e2fc312faed71a`

census_paths 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>) `c21d621de821b22f092c28dddb6b1efb53baa7dc97e162a5b0e2fc312faed71a`

robustness_paths 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

interaction_cells 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>) `b51a35e986e6520c163c6b2b27b8033f8dd101052b054e02eeaf3fdfa546a03d`

vol20_risk5_ic 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

mom20_risk20_ic 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

kurt60_return20_ic 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

## 解释

**FACT**：普查及复核覆盖63特征、504条主检验、96条复核及51个互补分组。

- features：63 count
- census_paths：504 count
- robustness_paths：96 count
- interaction_cells：51 count
**RESEARCH_JUDGMENT**：状态组件通过多个方向稳定性诊断；收益方向性仍较弱，用户三个经济目标尚未证明可同时达到。

- 支持证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`
- 不利证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>) `c21d621de821b22f092c28dddb6b1efb53baa7dc97e162a5b0e2fc312faed71a`
- 不利证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>) `b51a35e986e6520c163c6b2b27b8033f8dd101052b054e02eeaf3fdfa546a03d`
**RESEARCH_JUDGMENT**：低风险过滤与反转简单叠加未稳定改善；高峰度下5日反转在40bp费用压力时平均净事件收益约-0.084%。事件重叠，不是账户收益。

- 不利证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>) `b51a35e986e6520c163c6b2b27b8033f8dd101052b054e02eeaf3fdfa546a03d`
**RESEARCH_JUDGMENT**：全部年度/留一年/非重叠切片仍属于开发池；后继候选选择来自EX004，区间未修正选择偏差。统计诊断不新增用户经济硬门。

**RESEARCH_JUDGMENT**：两次技术失败均保留；EX003平台PASS对应零有效检验，未用于有效性判断。

- 不利证据：[attachments/EX002_technical_failure.json](<attachments/EX002_technical_failure.json>) `015947d27d0d1715cdcac3263266419c17d33191471631b7ed14b49f57fb177a`
- 不利证据：[attachments/EX003_zero_tests.json](<attachments/EX003_zero_tests.json>) `cbbb6c50f7638cf7e7371cd46a88c6ab8aa99bdebe5acf2242bc692c5552bb22`
**RESEARCH_JUDGMENT**：现有DFLS能力足以完成本阶段，未修改平台。未来策略使用外部字段仍需核验实际可得性；历史来源修订风险保留。


## 未完成事项


## 复算

先校验EX001至EX005档案及当前交付；核对源码绑定、EX004全路径台账和EX005复核。复算须通过后继REX实验沿用固定公式和绑定前驱，禁止覆盖已封存实验。

数据访问：实际数据经DFLS/Tushare受管取得并保存于artifacts/rex/data；本次复核逐文件校验已绑定前驱。Git忽略原始制品，跨机器恢复须同步完整制品和前驱链。

确定性及容差：种子12002/12005；tsfresh固定统计函数；环境版本见绑定及环境记录。研究统计允许机器浮点微小差异，身份哈希严格核验。

- 环境：[attachments/census_protocol.md](<attachments/census_protocol.md>) `67bb39eab62f4b2e4513fb97e80d63125c553e90d513c49fd29edd6341bc9ec8`
- 环境：[attachments/robustness_protocol.md](<attachments/robustness_protocol.md>) `01618a1d8c2211c53e9368fe45fdbe6333e9693333d03a7a3394841a38f31baa`
- 环境：[attachments/delivery.py](<attachments/delivery.py>) `5970caa4cd25c8203f30a96cfe88fb5dbf4890576ea97ec48bbd7d7ede416ce1`
