# S008 EX72 预注册设计

- 固定新输入为 EX71 20 日主周期的 `AfternoonReturn`、`CloseLocation`、`OvernightGap` 三条 `DIRECTIONALLY_STABLE` 路径；EX71 receipt 为 `57f2d74df5429e0c7dd0ad689d9b4d34c485932b1ab080d1d272702b5a49ae6c`。三者在 EX71 发现期确定的方向均为 `NEGATIVE`，本实验不得重新定向。
- 对照输入为 EX18 的全部 13 个组件及其冻结方向；组件值来自 EX16 的受管因果面板。新路径值来自 EX70 的日内面板。EX16/EX18 的 manifest 和 EX70/EX71 的 receipt 必须先通过身份校验。
- 仅比较同一 ETF 交易日的已形成特征值。发现期截至 2018-12-31，确认期 2019-01-01 至 2024-12-31；两个阶段分别报告 3 条新路径对 13 个既有组件及彼此的 Spearman 相关，确认期配对样本至少 1000 个。绝对相关达到 0.80 即为数值冗余，沿用 EX18 阈值。以传递闭包建簇；新路径与既有组件同簇则不增加独立组件；仅含新路径的簇按 EX71 Bootstrap 同向概率、残差 IC、名称依次选代表。完整矩阵、全部比较与去留理由入档。
- 金融职责在读取相关矩阵前固定：三条新路径均反映 ETF 当日走弱后的潜在回补，属于 `ENTRY_TIMING`；它们不能自行证明黄金上涨机会来源。报告与 EX18 既有入场组件在业务职责上的重合，即使数值相关未达 0.80。
- 机器裁决：无独立新代表则 `STOP_INTRADAY_REDUNDANT`；若有独立代表且其 EX71 证据至少为 `NOMINAL_SUPPORT`，则 `REVIEW_ENTRY_OVERLAY_PROTOTYPE`；若仅有方向稳定代表，则 `HOLD_INTRADAY_DISCOVERY_ONLY`。裁决不修改用户年化收益、回撤、仓位和执行口径。
- 本实验只读取已封存的开发期特征和 EX71 评价账本，不读取新的未来收益或 2025 年起密封区，不启动搜索、选择原型、创建候选、触及平台或 PTE。
