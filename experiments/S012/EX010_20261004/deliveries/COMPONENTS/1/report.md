# S012 · COMPONENTS · 1

研究员声明状态：COMPLETE
归属：EX010_20261004

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
- 实验证据：EX010_20261004；用途：CURRENT_EVALUATION；回执：`c287c177f9cd1abb049c772d5eebc14f097e0329888e6ac6f409999c21d35727`

本轮机会研究交付完成：一个有条件的低频机会候选、弱备选及竞争解释反证，原三项风险/状态组件作为辅助。当前机会能力不足以证明用户收益与频率目标，不建议直接进入阶段三。详见research_report.md。

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

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| fx_paths | 168 | count | AVAILABLE | — |
| gold_paths | 96 | count | AVAILABLE | — |
| opportunity_n | 79 | count | AVAILABLE | — |
| opportunity_net5 | 0.0077855862523994075 | fraction | AVAILABLE | — |
| opportunity_increment5 | 0.007223064107235631 | fraction | AVAILABLE | — |
| opportunity_surplus5 | 0.005205475345969683 | fraction | AVAILABLE | — |
| opportunity_q | 0.28 | probability | AVAILABLE | — |
| limit_capacity60 | 1.1013986013986015 | events_per_60_sessions | AVAILABLE | — |

fx_paths 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

gold_paths 证据：[experiments/EX010_20261004/gold/opportunities.json](<experiments/EX010_20261004/gold/opportunities.json>) `da633b7747679c700464c8c5ffb7df1418873fd56e0855ceb1de1466e239297d`

opportunity_n 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

opportunity_net5 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

opportunity_increment5 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

opportunity_surplus5 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

opportunity_q 证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`

limit_capacity60 证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>) `e146fa48e7d43da8f2527c108da1cd2a0855dcb648208419d2802990aaa8ec22`

## 解释

**FACT**：保守可用时间下完成168条FX与96条境外黄金路径，O01存在正向事件收益和匹配增量。

- fx_paths：168 count
- gold_paths：96 count
- opportunity_n：79 count
- opportunity_net5：0.0077855862523994075 fraction
- opportunity_increment5：0.007223064107235631 fraction
**RESEARCH_JUDGMENT**：O01作为条件性机会候选保留；统计、年度、非重叠和限价约束仍不足，未确认独立Alpha或完整账户达标。

- opportunity_q：0.28 probability
- limit_capacity60：1.1013986013986015 events_per_60_sessions
- 支持证据：[experiments/EX010_20261004/fx/opportunities.json](<experiments/EX010_20261004/fx/opportunities.json>) `04ad259618f1f2b4c5470e0bddac248b50c6e379807c4275592e2feea186899f`
- 不利证据：[experiments/EX010_20261004/fx/annual.json](<experiments/EX010_20261004/fx/annual.json>) `20476be454f31150de48ea4929c89947800506831b8af87c3ab8988dcc820669`
- 不利证据：[experiments/EX010_20261004/fx/sensitivity.json](<experiments/EX010_20261004/fx/sensitivity.json>) `aa2150cbc8df8d9a0bfbbbd9c6577524f81d4c11b1de428bcc26bccf70350323`
- 不利证据：[experiments/EX010_20261004/fx/limit_events.json](<experiments/EX010_20261004/fx/limit_events.json>) `e146fa48e7d43da8f2527c108da1cd2a0855dcb648208419d2802990aaa8ec22`
**RESEARCH_JUDGMENT**：EX008强信号因源日不等于可用时刻而隔离，修订后境外金价的多数增量消失。

- 不利证据：[attachments/time_failure.md](<attachments/time_failure.md>) `c0080de91b1871d24763f21f7d1a2f9e3e46b6377e518ace44c55b27e99c3161`
- 不利证据：[experiments/EX010_20261004/gold/opportunities.json](<experiments/EX010_20261004/gold/opportunities.json>) `da633b7747679c700464c8c5ffb7df1418873fd56e0855ceb1de1466e239297d`
- 不利证据：[experiments/EX008_20261004/opportunities.json](<experiments/EX008_20261004/opportunities.json>) `32f9add5bcf156e5edf596287661d4277e1498577c039abef36eb55071f68fa7`
**FACT**：DFLS已显式发布保守可用时刻；历史发布时间仍未知。两行报价计数修订留证，全部OHLC与日期不变。

- 支持证据：[experiments/EX010_20261004/data_audit.json](<experiments/EX010_20261004/data_audit.json>) `0873ee06ed80af303064cb6abfa6ab88d79782525067407cb85e9aa4b2e3eca1`
- 支持证据：[experiments/EX010_20261004/snapshot_revision.json](<experiments/EX010_20261004/snapshot_revision.json>) `fe4829de955326e8b7aed7fb2ed39aa6c514eae23089f61355ef282dea9050af`
**RESEARCH_JUDGMENT**：全历史开发池，多轮选择偏差未消除；每轮多重调整不能当作跨轮独立验证。原技术失败及旧交付原样保留。

**RESEARCH_JUDGMENT**：下一步优先补充可核验时点的黄金/ETF日内独立机会；阶段三及生产、推送均未执行。


## 未完成事项


## 复算

先核验EX001—EX010档案及当前交付；复算须创建后继REX实验，按固定条件与显式AvailableDate执行，不覆盖已有回执或manifest。

数据访问：数据经DFLS/Tushare取得；EX010新源数据与EX004前驱共同绑定。完整原始制品被Git忽略，跨机器复算需同步完整前驱链并验证哈希。

确定性及容差：条件与种子固定；浮点统计允许微小误差，身份哈希严格；供应商修订须新实验留证。

- 环境：[attachments/corrected_protocol.md](<attachments/corrected_protocol.md>) `240d4d3ba8e0260d383720293a410a5faa4dadc2153fa5bd364c39885ee40199`
- 环境：[attachments/opportunity_protocol.md](<attachments/opportunity_protocol.md>) `9ddbb7ad255a9c26f98ca116dca6dcf057323f6c1d5fe867bfbeba955e3adda2`
- 环境：[attachments/gold_protocol.md](<attachments/gold_protocol.md>) `ae336706108dee4344f2a2a7c8c823946efdc4f1eae3181c8b6b5f750dfeab84`
- 环境：[attachments/delivery.py](<attachments/delivery.py>) `e2cf0af853b1bb54d8f9fe1064c6aa98af600e30d9a76586e0e47969ba3d707b`
