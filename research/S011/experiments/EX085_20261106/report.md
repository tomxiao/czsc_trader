# S011-v1 原生 V4 迁移验证

Status: COMPLETED（等价性及隔离 PTE 技术检验 PASS；本地同版本原生 V4 升级已 COMMITTED）

本轮按用户授权保持原冻结参数、独立信号计时、周期数量锁、费用和补单规则，未开展新搜索或扩样。
后复权价格用于策略计算，未复权价格用于执行和估值。候选 `C9951` 内容身份为
`b7e73a7d9f8c2d394e773a387d69339e51f23a6eb56f053ed8c7cbc3d231779e`，与最后通过的完整账户定义及源码闭包完全一致；复用完整账户证据，没有重算。

## 验证结果

- 标准费用：405 个交易日，80 笔成交；现金/权益最大差 8.73114913702e-11，价格、数量、方向及日期完全相等。

逐前缀信号及其计时状态 405 次对照零差异。完整账户财务差异均低于 1e-8 容差。
公开技术检验 `inspection-a77aabbbc23b4cfcbcb562f17955100a`：候选与隔离冻结包账户比较 PASS，PTE 六个场景 PASS，覆盖部分成交、重复报告、
重启、完成成交、拒单、未知状态、过期及平账阻断。旧失败检验记录保持不变；新协议删除了成交后回到同一区间起点
再次决策的非因果步骤，未改变候选或降低平台必需能力覆盖。

详见 [完整标准账户对照](others/account_STANDARD.json)、[信号对照](others/signal_equivalence.json)、
[技术检验](others/inspection.json)、[迁移交付](others/migration_completion.json)。
正式技术证据位于 `research/S011/assets/evidence/EX085_20261106/inspection/005f7b36ffd873bef4f6acfd85234ef4f3f7472f135a5f70ec8ff6fdf6cb7360`，SHA-256 `005f7b36ffd873bef4f6acfd85234ef4f3f7472f135a5f70ec8ff6fdf6cb7360`。

## 数据来源与生产边界

- `s011-retained-tushare-observations`：BARS DAILY HFQ + SESSIONS；供应商 Tushare；已验区间 2024-12-26 至 2026-09-30。
- `s011-retained-tushare-observations`：BARS M30 HFQ + SESSIONS；供应商 Tushare；已验区间 2024-12-26 至 2026-09-30。
- `s011-retained-tushare-raw`：BARS DAILY RAW + SESSIONS + ACTIONS + CONSTRAINTS；供应商 Tushare retained OHLCV/trade calendar/limits and authenticated no-action receipt；已验区间 2024-09-09 至 2026-09-30。
- `DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY`：000300.SH；供应商 Tushare；已验区间 2024-12-26 至 2026-09-30。
- `GLOBAL_INDEX_DAILY`：SPX；供应商 Tushare；已验区间 2024-12-16 至 2026-09-30。

冻结辅助行情 SourceRef 固定为 s011-retained-tushare-observations/ex087-v1；当前 ProviderConfig 仅接入 Tushare 留存历史。后续不能直接改换 SourceRef，须为该逻辑来源配置符合相同价格、时间和覆盖合同的持续供数实现，并验证日历、交易约束、公司行动和观察数据；该接续尚未实现，是生产发布及重绑的前置项。当前 PASS 只证明留存区间上的等价性与隔离 PTE 运行，不代表生产已适配。

S011 的指数严格前日快照及 SPX 对齐、S015 的原盘中计算口径与修复规则均保留。
历史可用时间按原来源假设处理，不把历史研究等价性扩展为供应商实际发布时间已核实。
本地 `S011-v1` 已通过正式升级 API 原地提交，状态 `COMMITTED`，新发布身份为
`c1b70ddbef090bd70a887290461f8a72662f3e94ad4486ec6ac6c5d8d07fd941`，包指纹为 `6105ee339ce45472a71aa8a318cc1038d17205e212a43782b37e41ff11420b56`。
资格保持 `RESEARCH`；原版本号、历史研究证据、冻结参数及金融规则保留，旧发布包归档于
`strategies/revisions/S011-v1/eb8a23d56de5c13079f125fd3ac09b520aaf8925c71e729709189c3f99a7b7d9`，正式回执位于 `strategies/revisions/S011-v1/eb8a23d56de5c13079f125fd3ac09b520aaf8925c71e729709189c3f99a7b7d9/upgrade_receipt.json`。
详见 [本次升级回执](others/native_v4_upgrade_receipt.json)。旧实验、旧检验及既有比较证据未重写，未重跑账户或检验。
本轮未变更生产、未重绑账户，也未授予新发布生产准入资格；持续供数接入与验证仍是生产发布及重绑前置项。
下一步由主会话统一提交本轮本地迁移成果，生产发布另按授权安排。
