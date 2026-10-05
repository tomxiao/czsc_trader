# S012 · COMPONENTS · 1

研究员声明状态：COMPLETE
归属：EX017_20261005

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：EX001_20261004；用途：HISTORICAL_REFERENCE；回执：`07f196cd4dfebccf2a1906bb0b7d07f2b9644b1be02d716bf386a692b55dca8a`
- 实验证据：EX003_20261004；用途：HISTORICAL_REFERENCE；回执：`95f4b4dfc2f08ce0a0726dc7f8ac20787a436c25cdec93435950eba90e77f1a1`
- 实验证据：EX004_20261004；用途：HISTORICAL_REFERENCE；回执：`b4b318ae21c7b9f95c268b7f4a9b5cf1c0620da5f0234c073cdab1bda76187c8`
- 实验证据：EX005_20261004；用途：HISTORICAL_REFERENCE；回执：`528693224d850de4a288b0c899fe433bdec7da7f4b78a7e52c241fb4d2d5ba31`
- 实验证据：EX006_20261004；用途：HISTORICAL_REFERENCE；回执：`e594996ec1d42f2e4b8b30fc56862d4447bf94376d60266ff6e7f9ad3f24fdf7`
- 实验证据：EX007_20261004；用途：HISTORICAL_REFERENCE；回执：`d0d8605fa130c1c155879db033017ce65efbc4c999954121fcd18cf0253fe72d`
- 实验证据：EX008_20261004；用途：HISTORICAL_REFERENCE；回执：`18fdf3b220cd34d8e91c5a6a37997e2dbec1a0dc2e533151305a8a386438b8c8`
- 实验证据：EX010_20261004；用途：HISTORICAL_REFERENCE；回执：`c287c177f9cd1abb049c772d5eebc14f097e0329888e6ac6f409999c21d35727`
- 实验证据：EX011_20261004；用途：HISTORICAL_REFERENCE；回执：`7d6756219224c657b8d98c3aa04d2aa50299faa1a22d35b5e146686f1f5eddc7`
- 实验证据：EX012_20261004；用途：HISTORICAL_REFERENCE；回执：`cf6662926bcb40240a0f7cb863417118b9aad8575df6317d5284326a18b90cc6`
- 实验证据：EX013_20261005；用途：HISTORICAL_REFERENCE；回执：`f6453dda0b2585bc1637857af35de021b8c5c04d35daf5d4406f571790eddfbe`
- 实验证据：EX014_20261005；用途：HISTORICAL_REFERENCE；回执：`609de5505aba3edee6bed6247b5fd11f2df9d19373477f4c56cd2dcb1cc3fca2`
- 实验证据：EX015_20261005；用途：CURRENT_EVALUATION；回执：`17d9453c45bb67b9a517546c644d8071688b636aea2774b114739b8a7600071b`
- 实验证据：EX016_20261005；用途：CURRENT_EVALUATION；回执：`c57c2bbba0dff33facf4ea2ecaa78b7b143ad127c76ed79dada446aa50526b00`
- 实验证据：EX017_20261005；用途：CURRENT_EVALUATION；回执：`ee1c6e995c13e0c8e9970b66c0a8c7c354961f8821ce748184deb449b62e9beb`

本轮阶段二汇总交付完成：延续三风险/状态组件及O01，新增正常定价下短期上涨的条件性机会候选；所有弱、无效及重复信息留证。收益与机会密度仍不足以证明账户三个目标，下一阶段需用户批准。

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
### O01_FX_DIP

职责：有条件的低频收益机会候选

研究判断：强汇率支持叠加ETF回调：保守可得边界后5日净0.779%、匹配毛增量0.722%；支持开发池机会线索。q=0.280，限价去重1.10次/60日，尚不能作为已确认独立Alpha。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益；1/10日为期限反证 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O01_FX_DIP_ROLE：SUPPORTED；强汇率支持叠加ETF回调：保守可得边界后5日净0.779%、匹配毛增量0.722%；支持开发池机会线索。q=0.280，限价去重1.10次/60日，尚不能作为已确认独立Alpha。
  - 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>)
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
  - 证据：[experiments/EX010_20261004/fx/sensitivity.json](<experiments/EX010_20261004/fx/sensitivity.json>)
  - 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>)
  - 证据：[experiments/EX010_20261004/data_audit.json](<experiments/EX010_20261004/data_audit.json>)
- O01_FX_DIP_SUFFICIENCY：INSUFFICIENT_DATA；年度有反例、平移多重q=0.280、限价机会容量不足；用户账户目标尚未验证。
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
  - 证据：[experiments/EX010_20261004/fx/sensitivity.json](<experiments/EX010_20261004/fx/sensitivity.json>)
  - 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>)
### O02_FX_CALENDAR

职责：O01的时间尺度敏感性定义

研究判断：改用5个ETF交易日计算汇率仍同向，属于O01同一信息来源，不重复算独立机会。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O02_FX_CALENDAR_ROLE：REDUNDANT；改用5个ETF交易日计算汇率仍同向，属于O01同一信息来源，不重复算独立机会。
  - 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>)
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
  - 证据：[experiments/EX010_20261004/fx/sensitivity.json](<experiments/EX010_20261004/fx/sensitivity.json>)
  - 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>)
### O03_FX_ALONE

职责：汇率支持的方向性候选

研究判断：5日净0.577%、匹配扣费后增量0.191%；3日开盘事件密度5.65/60日但扣费后增量仅0.030%，年度与实际限价容量仍弱。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O03_FX_ALONE_ROLE：INSUFFICIENT_DATA；5日净0.577%、匹配扣费后增量0.191%；3日开盘事件密度5.65/60日但扣费后增量仅0.030%，年度与实际限价容量仍弱。
  - 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>)
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
### O04_TURN

职责：回调后转强的入场候选

研究判断：5日净0.342%，但匹配扣费后增量仅0.007%，不能将市场本身上涨当作择时优势。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O04_TURN_ROLE：INSUFFICIENT_DATA；5日净0.342%，但匹配扣费后增量仅0.007%，不能将市场本身上涨当作择时优势。
  - 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>)
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
  - 证据：[experiments/EX010_20261004/fx/sensitivity.json](<experiments/EX010_20261004/fx/sensitivity.json>)
  - 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>)
### O05_SGE_RELATIVE

职责：相对境内黄金价格修复候选

研究判断：5日净0.363%，匹配扣费后增量仅0.004%；SGE比值不代表ETF净值折溢价。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O05_SGE_RELATIVE_ROLE：INSUFFICIENT_DATA；5日净0.363%，匹配扣费后增量仅0.004%；SGE比值不代表ETF净值折溢价。
  - 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>)
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
  - 证据：[experiments/EX010_20261004/fx/sensitivity.json](<experiments/EX010_20261004/fx/sensitivity.json>)
  - 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>)
### O06_BROAD_FX

职责：扩大机会密度的竞争条件

研究判断：放宽后5日匹配扣费后增量-0.165%；前收盘限价去重事件净-0.467%，增加密度稀释质量。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O06_BROAD_FX_ROLE：INEFFECTIVE；放宽后5日匹配扣费后增量-0.165%；前收盘限价去重事件净-0.467%，增加密度稀释质量。
  - 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>)
  - 证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>)
  - 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>)
### O07_OVERSEAS_GOLD

职责：境外黄金补涨与相对价格修复

研究判断：原强信号受时间语义污染；保守可用时间后大部分扣费增量转负，少量正事件不足以成为独立机会。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：盘前决定后的1/3/5/10日开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O07_OVERSEAS_GOLD_ROLE：INSUFFICIENT_DATA；原强信号受时间语义污染；保守可用时间后大部分扣费增量转负，少量正事件不足以成为独立机会。
  - 证据：[experiments/EX010_20261004/gold/opportunities.json](<experiments/EX010_20261004/gold/opportunities.json>)
  - 证据：[experiments/EX010_20261004/data_audit.json](<experiments/EX010_20261004/data_audit.json>)
  - 证据：[experiments/EX008_20261004/opportunities.json](<experiments/EX008_20261004/opportunities.json>)
### O08_BREAKOUT

职责：突破延续的竞争解释

研究判断：EX006固定价量条件在主要期限未提供足够费用后增量；相关检验不依赖受影响的FX字段。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：3/5日次开盘收益 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- O08_BREAKOUT_ROLE：INEFFECTIVE；EX006固定价量条件在主要期限未提供足够费用后增量；相关检验不依赖受影响的FX字段。
  - 证据：[experiments/EX006_20261004/opportunities.json](<experiments/EX006_20261004/opportunities.json>)
### R01_AUXILIARY

职责：原波动、趋势后回撤、冲击集中度风险/状态辅助

研究判断：继承EX005三项角色证据；原风险定义及证据不依赖FXCM数据，不作为本轮新机会数。

适用边界：仅518850.SH开发池，2020-2021年度阈值训练、2022起事件评价；时间政策为保守假设。

标签／期限／对照：风险3/5/10/20日；收益状态10/20日 / 按上述期限固定检验，全部为已见开发池 / 同年、20日趋势正负及训练波动三分位；年度、延迟、极值和费用反证。

可用时点／价格口径：FXCM按AvailableDate（源日+2自然日08:00中国时间）对齐；ETF按收盘或盘前角色使用，细节见协议。 / ETF不复权成交价格；外部BidClose是信息代理，相对价格不等于净值溢价。

- R01_AUXILIARY_ROLE：SUPPORTED；继承EX005三项角色证据；原风险定义及证据不依赖FXCM数据，不作为本轮新机会数。
  - 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>)
### O02_LAST_HOUR_RELATIVE_LAG

职责：机会机制诊断

研究判断：主路径费用后增量或异常敏感性未支持机制；保留负面证据。

适用边界：全上市开发池；只做多、各侧0.1%费用；异常敏感性预声明

标签／期限／对照：T+1至T+4开盘净收益 / 3交易日；1/5日诊断 / 年度毛收益基线、绝对下跌事件、O01及并集

可用时点／价格口径：T日17:00观察，T+1执行；历史API发布未验证 / 不复权实际价格；分钟仅同步14:00 Close与日线收盘

- RELATIVE_LAG_3D：INEFFECTIVE；主路径费用后增量或异常敏感性未支持机制；保留负面证据。
  - 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>)
  - 证据：[experiments/EX014_20261005/annual.json](<experiments/EX014_20261005/annual.json>)
  - 证据：[experiments/EX014_20261005/feature_coverage.json](<experiments/EX014_20261005/feature_coverage.json>)
### N01_LATE_VOLUME

职责：低尾盘成交占比的弱机会线索

研究判断：5日匹配增量0.0619%、OLS0.0114%；延迟两日匹配转负，筛查48信号q=1，保留候选线索。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N01_LATE_VOLUME_EVIDENCE：INSUFFICIENT_DATA；5日匹配增量0.0619%、OLS0.0114%；延迟两日匹配转负，筛查48信号q=1，保留候选线索。
  - 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>)
  - 证据：[experiments/EX015_20261005/annual.json](<experiments/EX015_20261005/annual.json>)
  - 证据：[experiments/EX015_20261005/multiplicity.json](<experiments/EX015_20261005/multiplicity.json>)
### N02_DRY_PULLBACK

职责：趋势内缩量回调的机会诊断

研究判断：24事件，匹配增量0.1166%；排异常匹配转负、剔除最佳5次均值负，样本弱。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N02_DRY_PULLBACK_EVIDENCE：INSUFFICIENT_DATA；24事件，匹配增量0.1166%；排异常匹配转负、剔除最佳5次均值负，样本弱。
  - 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>)
  - 证据：[experiments/EX015_20261005/annual.json](<experiments/EX015_20261005/annual.json>)
  - 证据：[experiments/EX015_20261005/multiplicity.json](<experiments/EX015_20261005/multiplicity.json>)
### N03_LONG_CLOSURE

职责：假期持有补偿与后续修复的竞争解释

研究判断：T+1休市前最后开市日入场，1/3日净收益负；5日正结果不能证明假期补偿，最佳5次剔除后负。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N03_LONG_CLOSURE_EVIDENCE：INEFFECTIVE；T+1休市前最后开市日入场，1/3日净收益负；5日正结果不能证明假期补偿，最佳5次剔除后负。
  - 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>)
  - 证据：[experiments/EX015_20261005/annual.json](<experiments/EX015_20261005/annual.json>)
  - 证据：[experiments/EX015_20261005/multiplicity.json](<experiments/EX015_20261005/multiplicity.json>)
### N04_THIN_IMPACT

职责：低量冲击结构的稀疏线索

研究判断：9事件、4非重叠事件，2025/2026无事件；EX016四事件循环块区间退化，无有效区间证据。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N04_THIN_IMPACT_EVIDENCE：INSUFFICIENT_DATA；9事件、4非重叠事件，2025/2026无事件；EX016四事件循环块区间退化，无有效区间证据。
  - 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>)
  - 证据：[experiments/EX015_20261005/annual.json](<experiments/EX015_20261005/annual.json>)
  - 证据：[experiments/EX015_20261005/multiplicity.json](<experiments/EX015_20261005/multiplicity.json>)
### N05_PEER_ABSORPTION

职责：同类价格落后后吸收的机制反证

研究判断：5日匹配与OLS增量均负；成交子集净收益不能代替因果预测或相对真值。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N05_PEER_ABSORPTION_EVIDENCE：INEFFECTIVE；5日匹配与OLS增量均负；成交子集净收益不能代替因果预测或相对真值。
  - 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>)
  - 证据：[experiments/EX015_20261005/annual.json](<experiments/EX015_20261005/annual.json>)
  - 证据：[experiments/EX015_20261005/multiplicity.json](<experiments/EX015_20261005/multiplicity.json>)
### N06_INTRADAY_SHAPE_CENSUS

职责：日内顺序、趋势效率与tsfresh形态的广泛对照

研究判断：所有48信号完整台账；多数匹配增量负，tsfresh形态未支持独立收益；主方向q全1。代表时点统计仅为入口，完整族见协议及台账。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N06_INTRADAY_SHAPE_CENSUS_EVIDENCE：INSUFFICIENT_DATA；所有48信号完整台账；多数匹配增量负，tsfresh形态未支持独立收益；主方向q全1。代表时点统计仅为入口，完整族见协议及台账。
  - 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>)
  - 证据：[experiments/EX015_20261005/annual.json](<experiments/EX015_20261005/annual.json>)
  - 证据：[experiments/EX015_20261005/multiplicity.json](<experiments/EX015_20261005/multiplicity.json>)
### N07_ACTUAL_VWAP_DISCOUNT

职责：收盘低于实际成交重心的修复假设

研究判断：278事件，5日净均值-0.0033%、匹配增量-0.3588%；8实际VWAP方向已测，不能把低于均价自动视为便宜。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N07_ACTUAL_VWAP_DISCOUNT_EVIDENCE：INEFFECTIVE；278事件，5日净均值-0.0033%、匹配增量-0.3588%；8实际VWAP方向已测，不能把低于均价自动视为便宜。
  - 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>)
  - 证据：[experiments/EX016_20261005/annual.json](<experiments/EX016_20261005/annual.json>)
  - 证据：[experiments/EX016_20261005/multiplicity.json](<experiments/EX016_20261005/multiplicity.json>)
### N08_NORMAL_PRICING_STATE

职责：正常定价状态的候选用途

研究判断：538事件绝对均值正，但匹配和OLS增量负；不能单独作为有收益增量的机会。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N08_NORMAL_PRICING_STATE_EVIDENCE：INSUFFICIENT_DATA；538事件绝对均值正，但匹配和OLS增量负；不能单独作为有收益增量的机会。
  - 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>)
  - 证据：[experiments/EX017_20261005/annual.json](<experiments/EX017_20261005/annual.json>)
  - 证据：[experiments/EX017_20261005/multiplicity.json](<experiments/EX017_20261005/multiplicity.json>)
### N09_NORMAL_PRICING_MOMENTUM

职责：正常定价下短期上涨的条件性机会候选

研究判断：298事件，5日净0.4956%、匹配增量0.1396%、OLS0.1705%；限价2.658次/60日。支持开发池条件线索；q=0.407、双倍费用/延迟转负，账户目标未验证。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N09_NORMAL_PRICING_MOMENTUM_EVIDENCE：SUPPORTED；298事件，5日净0.4956%、匹配增量0.1396%、OLS0.1705%；限价2.658次/60日。支持开发池条件线索；q=0.407、双倍费用/延迟转负，账户目标未验证。
  - 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>)
  - 证据：[experiments/EX017_20261005/annual.json](<experiments/EX017_20261005/annual.json>)
  - 证据：[experiments/EX017_20261005/multiplicity.json](<experiments/EX017_20261005/multiplicity.json>)
### N10_O01_MID_FILTER

职责：O01正常定价过滤的竞争解释

研究判断：O01从79事件缩为35，5日净0.0086%、匹配增量-0.4275%；当前不建议将中段机械叠加于O01。

适用边界：518850.SH，2020-06-05至2026-09-30全开发池；2022起年度阈值评价，全1535容量分母；限价触价不是成交证明

标签／期限／对照：T+1至T+6开盘净事件收益；1/3日及其他期限/成本为反证 / 5日主标签；完整主及敏感性见协议 / 年度日收益/3日动量/量比匹配毛收益、7价量风险变量OLS；不是可交易对照

可用时点／价格口径：T17:00市场观察假设，T+1执行；历史逐日发布延迟未验证 / 不复权实际价格，真实VWAP=Amount/Volume；偏离为无量纲比例

- N10_O01_MID_FILTER_EVIDENCE：INEFFECTIVE；O01从79事件缩为35，5日净0.0086%、匹配增量-0.4275%；当前不建议将中段机械叠加于O01。
  - 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>)
  - 证据：[experiments/EX017_20261005/annual.json](<experiments/EX017_20261005/annual.json>)
  - 证据：[experiments/EX017_20261005/multiplicity.json](<experiments/EX017_20261005/multiplicity.json>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| EX005_20261004__features | 63 | count | AVAILABLE | — |
| EX005_20261004__census_paths | 504 | count | AVAILABLE | — |
| EX005_20261004__robustness_paths | 96 | count | AVAILABLE | — |
| EX005_20261004__interaction_cells | 51 | count | AVAILABLE | — |
| EX005_20261004__vol20_risk5_ic | 0.181756 | rank_correlation | AVAILABLE | — |
| EX005_20261004__mom20_risk20_ic | 0.225989 | rank_correlation | AVAILABLE | — |
| EX005_20261004__kurt60_return20_ic | -0.279206 | rank_correlation | AVAILABLE | — |
| EX010_20261004__fx_paths | 168 | count | AVAILABLE | — |
| EX010_20261004__gold_paths | 96 | count | AVAILABLE | — |
| EX010_20261004__opportunity_n | 79 | count | AVAILABLE | — |
| EX010_20261004__opportunity_net5 | 0.0077855862523994075 | fraction | AVAILABLE | — |
| EX010_20261004__opportunity_increment5 | 0.007223064107235631 | fraction | AVAILABLE | — |
| EX010_20261004__opportunity_surplus5 | 0.005205475345969683 | fraction | AVAILABLE | — |
| EX010_20261004__opportunity_q | 0.28 | probability | AVAILABLE | — |
| EX010_20261004__limit_capacity60 | 1.1013986013986015 | events_per_60_sessions | AVAILABLE | — |
| EX014_20261005__inputs_ready | True | boolean | AVAILABLE | — |
| EX014_20261005__main_events | 8 | count | AVAILABLE | — |
| EX014_20261005__main_net_mean | 0.0003548269891021638 | ratio | AVAILABLE | — |
| EX014_20261005__main_increment | -0.0011886953572947476 | ratio | AVAILABLE | — |
| EX014_20261005__clean_increment | 0.004678309917810535 | ratio | AVAILABLE | — |
| EX014_20261005__limit_capacity | 0.11726384364820847 | ratio | AVAILABLE | — |
| N01_LATE_VOLUME__events | 82 | count | AVAILABLE | — |
| N01_LATE_VOLUME__net_mean | 0.003611363688338565 | fraction | AVAILABLE | — |
| N01_LATE_VOLUME__increment | 0.0006194368873294802 | fraction | AVAILABLE | — |
| N01_LATE_VOLUME__price_volume_control_increment | 0.00011399869595968557 | fraction | AVAILABLE | — |
| N01_LATE_VOLUME__limit_per60 | 1.289902280130293 | events_per_60_sessions | AVAILABLE | — |
| N01_LATE_VOLUME__limit_net | 0.0034285570916042112 | fraction | AVAILABLE | — |
| N02_DRY_PULLBACK__events | 24 | count | AVAILABLE | — |
| N02_DRY_PULLBACK__net_mean | 0.003479971990872318 | fraction | AVAILABLE | — |
| N02_DRY_PULLBACK__increment | 0.0011657425983051897 | fraction | AVAILABLE | — |
| N02_DRY_PULLBACK__price_volume_control_increment | 0.0009073476772940402 | fraction | AVAILABLE | — |
| N02_DRY_PULLBACK__limit_per60 | 0.7035830618892508 | events_per_60_sessions | AVAILABLE | — |
| N02_DRY_PULLBACK__limit_net | 0.0014308804224308542 | fraction | AVAILABLE | — |
| N03_LONG_CLOSURE__events | 28 | count | AVAILABLE | — |
| N03_LONG_CLOSURE__net_mean | 0.008363695071539442 | fraction | AVAILABLE | — |
| N03_LONG_CLOSURE__increment | 0.004276033019122461 | fraction | AVAILABLE | — |
| N03_LONG_CLOSURE__price_volume_control_increment | 0.004100299620166322 | fraction | AVAILABLE | — |
| N03_LONG_CLOSURE__limit_per60 | 0.6644951140065146 | events_per_60_sessions | AVAILABLE | — |
| N03_LONG_CLOSURE__limit_net | 0.0029547063421283743 | fraction | AVAILABLE | — |
| N04_THIN_IMPACT__events | 9 | count | AVAILABLE | — |
| N04_THIN_IMPACT__net_mean | 0.009168873758709648 | fraction | AVAILABLE | — |
| N04_THIN_IMPACT__increment | 0.0011370070359774118 | fraction | AVAILABLE | — |
| N04_THIN_IMPACT__price_volume_control_increment | 0.002076902682299321 | fraction | AVAILABLE | — |
| N04_THIN_IMPACT__limit_per60 | 0.11726384364820847 | events_per_60_sessions | AVAILABLE | — |
| N04_THIN_IMPACT__limit_net | 0.011919597412681412 | fraction | AVAILABLE | — |
| N05_PEER_ABSORPTION__events | 63 | count | AVAILABLE | — |
| N05_PEER_ABSORPTION__net_mean | 0.00462802803093772 | fraction | AVAILABLE | — |
| N05_PEER_ABSORPTION__increment | -0.0006024232547263465 | fraction | AVAILABLE | — |
| N05_PEER_ABSORPTION__price_volume_control_increment | -0.00023880540006286766 | fraction | AVAILABLE | — |
| N05_PEER_ABSORPTION__limit_per60 | 0.8990228013029316 | events_per_60_sessions | AVAILABLE | — |
| N05_PEER_ABSORPTION__limit_net | 0.013452596967490368 | fraction | AVAILABLE | — |
| N06_INTRADAY_SHAPE_CENSUS__events | 320 | count | AVAILABLE | — |
| N06_INTRADAY_SHAPE_CENSUS__net_mean | 0.0033018896303665542 | fraction | AVAILABLE | — |
| N06_INTRADAY_SHAPE_CENSUS__increment | -0.00032029405764398035 | fraction | AVAILABLE | — |
| N06_INTRADAY_SHAPE_CENSUS__price_volume_control_increment | -0.0009250200843209138 | fraction | AVAILABLE | — |
| N06_INTRADAY_SHAPE_CENSUS__limit_per60 | 3.439739413680782 | events_per_60_sessions | AVAILABLE | — |
| N06_INTRADAY_SHAPE_CENSUS__limit_net | 0.003163386880201256 | fraction | AVAILABLE | — |
| N07_ACTUAL_VWAP_DISCOUNT__events | 278 | count | AVAILABLE | — |
| N07_ACTUAL_VWAP_DISCOUNT__net_mean | -3.295226624045111e-05 | fraction | AVAILABLE | — |
| N07_ACTUAL_VWAP_DISCOUNT__increment | -0.0035877256985094065 | fraction | AVAILABLE | — |
| N07_ACTUAL_VWAP_DISCOUNT__price_volume_control_increment | -0.0036783236058321954 | fraction | AVAILABLE | — |
| N07_ACTUAL_VWAP_DISCOUNT__limit_per60 | 3.2833876221498373 | events_per_60_sessions | AVAILABLE | — |
| N07_ACTUAL_VWAP_DISCOUNT__limit_net | -0.0032535519099560523 | fraction | AVAILABLE | — |
| N08_NORMAL_PRICING_STATE__events | 538 | count | AVAILABLE | — |
| N08_NORMAL_PRICING_STATE__net_mean | 0.0033916267269049733 | fraction | AVAILABLE | — |
| N08_NORMAL_PRICING_STATE__increment | -0.0005062891649617847 | fraction | AVAILABLE | — |
| N08_NORMAL_PRICING_STATE__price_volume_control_increment | -0.00044728822366592465 | fraction | AVAILABLE | — |
| N08_NORMAL_PRICING_STATE__limit_per60 | 3.478827361563518 | events_per_60_sessions | AVAILABLE | — |
| N08_NORMAL_PRICING_STATE__limit_net | 2.738216893846211e-05 | fraction | AVAILABLE | — |
| N09_NORMAL_PRICING_MOMENTUM__events | 298 | count | AVAILABLE | — |
| N09_NORMAL_PRICING_MOMENTUM__net_mean | 0.0049559558956460414 | fraction | AVAILABLE | — |
| N09_NORMAL_PRICING_MOMENTUM__increment | 0.0013963099181635106 | fraction | AVAILABLE | — |
| N09_NORMAL_PRICING_MOMENTUM__price_volume_control_increment | 0.0017051723319196556 | fraction | AVAILABLE | — |
| N09_NORMAL_PRICING_MOMENTUM__limit_per60 | 2.6579804560260585 | events_per_60_sessions | AVAILABLE | — |
| N09_NORMAL_PRICING_MOMENTUM__limit_net | 0.001215607740060073 | fraction | AVAILABLE | — |
| N10_O01_MID_FILTER__events | 35 | count | AVAILABLE | — |
| N10_O01_MID_FILTER__net_mean | 8.568153872514321e-05 | fraction | AVAILABLE | — |
| N10_O01_MID_FILTER__increment | -0.004275374366518127 | fraction | AVAILABLE | — |
| N10_O01_MID_FILTER__price_volume_control_increment | -0.0035652672234923037 | fraction | AVAILABLE | — |
| N10_O01_MID_FILTER__limit_per60 | 0.7035830618892508 | events_per_60_sessions | AVAILABLE | — |
| N10_O01_MID_FILTER__limit_net | 0.00010064568799625671 | fraction | AVAILABLE | — |
| new_diagnostic_paths | 1752 | count | AVAILABLE | — |
| new_unique_signal_definitions | 64 | count | AVAILABLE | — |
| new_experiments | 3 | count | AVAILABLE | — |
| o01_normal_union_capacity60 | 3.0879478827361564 | events_per_60_sessions | AVAILABLE | — |
| o01_normal_union_limit_net | 0.0007795010188953286 | fraction | AVAILABLE | — |

EX005_20261004__features 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>) `c21d621de821b22f092c28dddb6b1efb53baa7dc97e162a5b0e2fc312faed71a`

EX005_20261004__census_paths 证据：[experiments/EX004_20261004/component_metrics.json](<experiments/EX004_20261004/component_metrics.json>) `c21d621de821b22f092c28dddb6b1efb53baa7dc97e162a5b0e2fc312faed71a`

EX005_20261004__robustness_paths 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

EX005_20261004__interaction_cells 证据：[experiments/EX005_20261004/interactions.json](<experiments/EX005_20261004/interactions.json>) `b51a35e986e6520c163c6b2b27b8033f8dd101052b054e02eeaf3fdfa546a03d`

EX005_20261004__vol20_risk5_ic 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

EX005_20261004__mom20_risk20_ic 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

EX005_20261004__kurt60_return20_ic 证据：[experiments/EX005_20261004/robustness.json](<experiments/EX005_20261004/robustness.json>) `5aec110063d4ae3c125d783d39ce02dc005f5f3e3bb34001e41093b1af17b9c6`

EX010_20261004__fx_paths 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

EX010_20261004__gold_paths 证据：[experiments/EX010_20261004/gold/opportunities.json](<experiments/EX010_20261004/gold/opportunities.json>) `da633b7747679c700464c8c5ffb7df1418873fd56e0855ceb1de1466e239297d`

EX010_20261004__opportunity_n 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

EX010_20261004__opportunity_net5 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

EX010_20261004__opportunity_increment5 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

EX010_20261004__opportunity_surplus5 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

EX010_20261004__opportunity_q 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

EX010_20261004__limit_capacity60 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>) `e146fa48e7d43da8f2527c108da1cd2a0855dcb648208419d2802990aaa8ec22`

EX014_20261005__inputs_ready 证据：[experiments/EX014_20261005/data_audit.json](<experiments/EX014_20261005/data_audit.json>) `34973ee2cca0c635eb2ab4efeb1697d745e0c017284099adf9a6de04aa587105`

EX014_20261005__main_events 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

EX014_20261005__main_net_mean 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

EX014_20261005__main_increment 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

EX014_20261005__clean_increment 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

EX014_20261005__limit_capacity 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

N01_LATE_VOLUME__events 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N01_LATE_VOLUME__net_mean 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N01_LATE_VOLUME__increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N01_LATE_VOLUME__price_volume_control_increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N01_LATE_VOLUME__limit_per60 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N01_LATE_VOLUME__limit_net 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N02_DRY_PULLBACK__events 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N02_DRY_PULLBACK__net_mean 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N02_DRY_PULLBACK__increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N02_DRY_PULLBACK__price_volume_control_increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N02_DRY_PULLBACK__limit_per60 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N02_DRY_PULLBACK__limit_net 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N03_LONG_CLOSURE__events 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N03_LONG_CLOSURE__net_mean 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N03_LONG_CLOSURE__increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N03_LONG_CLOSURE__price_volume_control_increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N03_LONG_CLOSURE__limit_per60 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N03_LONG_CLOSURE__limit_net 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N04_THIN_IMPACT__events 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N04_THIN_IMPACT__net_mean 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N04_THIN_IMPACT__increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N04_THIN_IMPACT__price_volume_control_increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N04_THIN_IMPACT__limit_per60 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N04_THIN_IMPACT__limit_net 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N05_PEER_ABSORPTION__events 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N05_PEER_ABSORPTION__net_mean 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N05_PEER_ABSORPTION__increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N05_PEER_ABSORPTION__price_volume_control_increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N05_PEER_ABSORPTION__limit_per60 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N05_PEER_ABSORPTION__limit_net 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N06_INTRADAY_SHAPE_CENSUS__events 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N06_INTRADAY_SHAPE_CENSUS__net_mean 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N06_INTRADAY_SHAPE_CENSUS__increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N06_INTRADAY_SHAPE_CENSUS__price_volume_control_increment 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N06_INTRADAY_SHAPE_CENSUS__limit_per60 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N06_INTRADAY_SHAPE_CENSUS__limit_net 证据：[experiments/EX015_20261005/opportunities.json](<experiments/EX015_20261005/opportunities.json>) `5066b3828a40684f5815559f09077093b692a304792d77992bed01936a23a34b`

N07_ACTUAL_VWAP_DISCOUNT__events 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>) `a05cd0dd288807b341a15233f15ba97865e948ddc061210e204c0cb3dad8285f`

N07_ACTUAL_VWAP_DISCOUNT__net_mean 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>) `a05cd0dd288807b341a15233f15ba97865e948ddc061210e204c0cb3dad8285f`

N07_ACTUAL_VWAP_DISCOUNT__increment 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>) `a05cd0dd288807b341a15233f15ba97865e948ddc061210e204c0cb3dad8285f`

N07_ACTUAL_VWAP_DISCOUNT__price_volume_control_increment 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>) `a05cd0dd288807b341a15233f15ba97865e948ddc061210e204c0cb3dad8285f`

N07_ACTUAL_VWAP_DISCOUNT__limit_per60 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>) `a05cd0dd288807b341a15233f15ba97865e948ddc061210e204c0cb3dad8285f`

N07_ACTUAL_VWAP_DISCOUNT__limit_net 证据：[experiments/EX016_20261005/opportunities.json](<experiments/EX016_20261005/opportunities.json>) `a05cd0dd288807b341a15233f15ba97865e948ddc061210e204c0cb3dad8285f`

N08_NORMAL_PRICING_STATE__events 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N08_NORMAL_PRICING_STATE__net_mean 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N08_NORMAL_PRICING_STATE__increment 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N08_NORMAL_PRICING_STATE__price_volume_control_increment 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N08_NORMAL_PRICING_STATE__limit_per60 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N08_NORMAL_PRICING_STATE__limit_net 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N09_NORMAL_PRICING_MOMENTUM__events 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N09_NORMAL_PRICING_MOMENTUM__net_mean 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N09_NORMAL_PRICING_MOMENTUM__increment 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N09_NORMAL_PRICING_MOMENTUM__price_volume_control_increment 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N09_NORMAL_PRICING_MOMENTUM__limit_per60 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N09_NORMAL_PRICING_MOMENTUM__limit_net 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N10_O01_MID_FILTER__events 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N10_O01_MID_FILTER__net_mean 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N10_O01_MID_FILTER__increment 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N10_O01_MID_FILTER__price_volume_control_increment 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N10_O01_MID_FILTER__limit_per60 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

N10_O01_MID_FILTER__limit_net 证据：[experiments/EX017_20261005/opportunities.json](<experiments/EX017_20261005/opportunities.json>) `536e4c8bad7f049e97023feb5a7b6805b4f3b494e27e374d321cc58de0041362`

new_diagnostic_paths 证据：[attachments/current/coverage_reference.json](<attachments/current/coverage_reference.json>) `a4a7d7f746eaaa718933e4111b5b8726b85093d74f22a015f4aebabf78fae38b`

new_unique_signal_definitions 证据：[attachments/current/coverage_reference.json](<attachments/current/coverage_reference.json>) `a4a7d7f746eaaa718933e4111b5b8726b85093d74f22a015f4aebabf78fae38b`

new_experiments 证据：[attachments/current/coverage_reference.json](<attachments/current/coverage_reference.json>) `a4a7d7f746eaaa718933e4111b5b8726b85093d74f22a015f4aebabf78fae38b`

o01_normal_union_capacity60 证据：[experiments/EX017_20261005/confirmation.json](<experiments/EX017_20261005/confirmation.json>) `a013cc215d8d6e9b6e7d68c53bf2fa39c8d129cfe6db7c686d8c7a4932bb90de`

o01_normal_union_limit_net 证据：[experiments/EX017_20261005/confirmation.json](<experiments/EX017_20261005/confirmation.json>) `a013cc215d8d6e9b6e7d68c53bf2fa39c8d129cfe6db7c686d8c7a4932bb90de`

## 解释

**RESEARCH_JUDGMENT**：历史组件沿用原始定义、协议和检验；本轮新增机会按新实验报告解释。历史风险指标未在本轮复算。

- 支持证据：[attachments/current/stage2_report.md](<attachments/current/stage2_report.md>) `7518c4151b6d742d842ae06de6d5eb5f279edb2c00d53cfb1217608995448f10`
**RESEARCH_JUDGMENT**：阶段二组件证据及机会密度用于后续账户方案设计；完整账户三项目标仍待独立验证。

- 支持证据：[attachments/current/stage2_report.md](<attachments/current/stage2_report.md>) `7518c4151b6d742d842ae06de6d5eb5f279edb2c00d53cfb1217608995448f10`
**RESEARCH_JUDGMENT**：N09支持条件性开发线索，不意味着已确认独立Alpha；所有区间、q和年度切片仍属已见开发池。

- 支持证据：[attachments/current/stage2_report.md](<attachments/current/stage2_report.md>) `7518c4151b6d742d842ae06de6d5eb5f279edb2c00d53cfb1217608995448f10`
**RESEARCH_JUDGMENT**：全部前驱保留；EX015真实VWAP覆盖描述由EX016承接纠正；EX016稀疏四事件区间不可解释，EX017少于6事件显式不报区间。

- 支持证据：[attachments/current/stage2_report.md](<attachments/current/stage2_report.md>) `7518c4151b6d742d842ae06de6d5eb5f279edb2c00d53cfb1217608995448f10`
**RESEARCH_JUDGMENT**：历史三风险指标未本轮重算；技术FULL与研究员COMPLETE分别表示核验及交付完整度，不代表收益或账户达标。

- 支持证据：[attachments/current/stage2_report.md](<attachments/current/stage2_report.md>) `7518c4151b6d742d842ae06de6d5eb5f279edb2c00d53cfb1217608995448f10`

## 未完成事项


## 复算

按本轮固定协议执行预检、受管数据准备及REX，再复算关键事实并验证阶段二交付和档案。

数据访问：使用现有S012数据空间、原始前驱制品和现有依赖；历史附件完整保留。

确定性及容差：历史结果不改写；供应商修订、方法改变或新机制必须形成后继实验。

- 环境：[attachments/current/EX017_protocol.md](<attachments/current/EX017_protocol.md>) `bf830eee1c70ce74eda009690d1c2433b1421d71bd6bd1b229e581796bcca20c`
