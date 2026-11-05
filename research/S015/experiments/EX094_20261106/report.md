# S015-v1 原生 V4 迁移验证

Status: COMPLETED（等价性及隔离 PTE 技术检验 PASS；本地同版本原生 V4 升级已 COMMITTED）

本轮按用户授权保持原冻结参数、独立信号计时、周期数量锁、费用和补单规则，未开展新搜索或扩样。
后复权价格用于策略计算，未复权价格用于执行和估值。候选 `C9901` 内容身份为
`288a3331a060652d9d31c2495b37302041aa30f506c6fdbdb372682b4cafd9d5`，与最后通过的完整账户定义及源码闭包完全一致；复用完整账户证据，没有重算。

## 验证结果

- 标准费用：434 个交易日，108 笔成交；现金/权益最大差 5.82076609135e-11，价格、数量、方向及日期完全相等。
- 双倍费用：434 个交易日，108 笔成交；现金/权益最大差 5.82076609135e-11，价格、数量、方向及日期完全相等。

逐前缀信号及其计时状态 434 次对照零差异。完整账户财务差异均低于 1e-8 容差。
公开技术检验 `inspection-4e795b322e2244d889774117ad9d3e3b`：候选与隔离冻结包账户比较 PASS，PTE 六个场景 PASS，覆盖部分成交、重复报告、
重启、完成成交、拒单、未知状态、过期及平账阻断。旧失败检验记录保持不变；新协议删除了成交后回到同一区间起点
再次决策的非因果步骤，未改变候选或降低平台必需能力覆盖。

详见 [完整标准账户对照](others/account_STANDARD.json)、[信号对照](others/signal_equivalence.json)、
[技术检验](others/inspection.json)、[迁移交付](others/migration_completion.json)。
正式技术证据位于 `research/S015/assets/evidence/EX094_20261106/inspection/87b639b57b5dc824b993bc48f079cfbde507e7e024b363c5bcd6fe251a42f2bc`，SHA-256 `87b639b57b5dc824b993bc48f079cfbde507e7e024b363c5bcd6fe251a42f2bc`。

## 数据来源与生产边界

- `s015-saved-tushare-observations`：BARS DAILY HFQ + SESSIONS；供应商 Tushare；已验区间 2024-09-09 至 2026-10-21。
- `s015-saved-tushare-observations`：BARS M30 RAW + SESSIONS；供应商 Tushare；已验区间 2025-01-02 至 2026-10-21。
- `s015-saved-tushare-raw`：BARS DAILY RAW + SESSIONS + ACTIONS + CONSTRAINTS；供应商 Tushare retained OHLCV/trade calendar/limits and authenticated no-action receipt；已验区间 2024-09-09 至 2026-10-21。

冻结辅助行情 SourceRef 固定为 s015-saved-tushare-observations/ex087-v1；当前 ProviderConfig 仅接入 Tushare 留存历史。后续不能直接改换 SourceRef，须为该逻辑来源配置符合相同价格、时间和覆盖合同的持续供数实现，并验证日历、交易约束、公司行动和观察数据；该接续尚未实现，是生产发布及重绑的前置项。当前 PASS 只证明留存区间上的等价性与隔离 PTE 运行，不代表生产已适配。

S011 的指数严格前日快照及 SPX 对齐、S015 的原盘中计算口径与修复规则均保留。
历史可用时间按原来源假设处理，不把历史研究等价性扩展为供应商实际发布时间已核实。
本地 `S015-v1` 已通过正式升级 API 原地提交，状态 `COMMITTED`，新发布身份为
`7a3af2d794da4f875e2123193f4590523eab54a9bfbe32611ba682f166aef884`，包指纹为 `42fc759bcfeaa82ea185114f13e2b2c8bdb9f7a3680f699964b9f9772f2a9086`。
资格保持 `RESEARCH`；原版本号、历史研究证据、冻结参数及金融规则保留，旧发布包归档于
`strategies/revisions/S015-v1/42213c1d07a712f712bcaef5a2fad21dc03b7660e6b24247209af51ece605cfc`，正式回执位于 `strategies/revisions/S015-v1/42213c1d07a712f712bcaef5a2fad21dc03b7660e6b24247209af51ece605cfc/upgrade_receipt.json`。
详见 [本次升级回执](others/native_v4_upgrade_receipt.json)。旧实验、旧检验及既有比较证据未重写，未重跑账户或检验。
本轮未变更生产、未重绑账户，也未授予新发布生产准入资格；持续供数接入与验证仍是生产发布及重绑前置项。
下一步由主会话统一提交本轮本地迁移成果，生产发布另按授权安排。
