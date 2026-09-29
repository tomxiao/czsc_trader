# S011 EX05 执行

schema v3 `experiment preflight` 通过，源码 SHA-256 为 `d7a370236206b771ec551baed91298441c61b300afff69137bea60ccbf8f18b6`，定义 SHA-256 为 `3cf1cd8c0b9ab5a249d7c503e04390ef1b193488044c99c9f431cfa7e47a9029`。首次正式执行读取 DFLS 数据后、统计汇总前，在 `features.join(labels)` 处报 `ValueError: columns overlap but no suffix specified: Index(['etf_return_5'], dtype='str')`。该名称同时用于 ETF 过去五日收益基线和未来五日收益标签。

此次没有形成因子分数、实验 receipt 或 `PASS` 结果；保留本次源码与失败记录，不在本档案内修复。后继 EX06 将使用不重名的标签并重新 preflight。未写入生产或平台模块。
