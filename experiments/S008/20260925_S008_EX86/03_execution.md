# S008 EX86 执行

预注册提交 `6114d948` 后启动。EX79、EX85 前序收据及 EX48/EX16/执行价输入哈希均通过；读取受管执行价后，源码把返回的 `RangeIndex` 当作交易日期索引，`reindex` 得到全空开盘价，于 `execution open prices unavailable` 中止。尚未计算日收益、季度排名或金融归因；没有签发 REX receipt。
