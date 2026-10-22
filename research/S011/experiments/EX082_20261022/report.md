# S011-C9902 → S011-v2 正式技术检验

Status: COMPLETED（两目标PASS；尚未冻结、部署）

用户确认C9902进入S011-v2正式技术检验，冻结和部署另行审批。此报告交付可供精确审批的最终格式发布包及冻结计划。

## 两个技术目标

| 目标 | 范围 | 结论 |
| --- | --- | --- |
| A：Candidate与StrategyVersion行为等价 | 2025-02-06至2026-10-21，415个交易日，初始资金100000，费用0.001，ECONOMIC_V1，浮点容差0 | PASS |
| A的附加原账户复现 | EX080同一C9902的schema7正式账户；绑定候选、原输入、执行条件 | PASS |
| B：发布包在隔离PTE可运行 | 真实部署加载、决策、订单、账户、重复回报及重启恢复链路；历史输入与合成成交渠道 | PASS |

目标A比较信号、决策、订单、成交、账户、交易及观察事实，仅归一化纯运行身份。没有读取研究阶段一至四报告或重做策略选型。
目标B包含以下5项，全部PASS：

1. 2025-03-03至03-05入场、部分成交、重复回报、重启、持有、退出。
2. 零成交撤单：持仓0、可用现金100000、冻结现金0、订单数1；账户保持BLOCKED，重复回报和重启均不得静默解除。
3. 发布包损坏时拒绝加载。
4. 缺少输入时阻止决策。
5. 输入晚于决策时阻止执行。

多档权益调仓不适用：此候选为二元仓位及固定入场周期数量。完整周期合成订单预期独立计算：买入91400股，价格1.092，部分成交45700股；卖价1.097，最终现金100256.9254元。上述余额只验证PTE账户计算，不代表历史策略收益。

正式检验调用耗时 **40.32秒**，包含准备、等价、PTE及证据保存；不含先前场景编制、失败诊断和报告整理。上限600秒、最多2个worker、原生线程1；实际只有一个等价回放坐标，PTE场景按平台顺序执行。

## 审批对象

| 对象 | 精确身份 |
| --- | --- |
| 候选 | S011-C9902 |
| 内容SHA-256 | e3b172664d26eb396528dac9ccc812434c2314b465c25eaf60f459c909fb7a12 |
| 目标版本 / 父版本 | S011-v2 / S011-v1 |
| 检验报告SHA-256 | a65ad9553b27ff529920b609bd5dba20500064d13b1a8f2fbf007fb6028940b6 |
| 冻结计划SHA-256 | ecc9e6254c6274c0ee5ef37a98b4ea7432cbd434e8745796446c307127920bc1 |
| 最终版本SHA-256 | b48eb925eedc5fed9d93fcb6ad85f2c9c916807a25786f6d404fc5a281458472 |
| 最终发布包SHA-256 | f64fe280ac50cfb3d41d88fb356c9865dde0b99f0d5474bb5b8271707e7e117f |
| 数据选择截止 / forward_start | 2026-10-21 / 2026-10-22 |

[正式检验报告](others/inspection_report.json) · [冻结计划](others/freeze_plan.json) · [精确批准对象](others/freeze_approval_subject.json) · [运行摘要](others/inspection_summary.json)

候选仍只调整daily/bars最低20、market最低21，SPX最低30不变；公式、固定数据起点、参数及交易规则均不变。
本次构造的是保存在技术证据中的待冻结包，未创建正式 `strategies/S011/versions/v2.json`，未执行freeze_candidate。原v1及部署回执逐文件哈希与运行前相同。

## 失败保留及契约修正

前驱EX081首次因Windows沙箱进程权限被拒绝，申请进程权限后运行41.09秒：目标A与4项PTE检查PASS，但零成交撤单检查错误预期health=OK，实际BLOCKED。
EX081原协议、报告、失败证据及INSPECTION/1交付完整保留，不追认为PASS。

PTE既有契约 `futu_execution.py:518-527` 要求任何首次非完整成交终态进入BLOCKED，等待人工确认执行缺口。
后继EX082依据该契约，仅把 `entry_cancelled` 和 `cancel_repeated` 两个健康检查点改为BLOCKED；[协议差异核对](others/protocol_correction.json)确认协议只有这两个变化，其他输入、数量、金额、基线及比较容差完全一致。
没有修改策略或平台代码，没有自动确认执行缺口。

既有聚焦测试：
`.venv/Scripts/python.exe -B -m pytest -c pyproject.toml packages/paper_trading_engine/tests/functional/test_channel_safety.py::test_ft_pte03_incomplete_and_unknown_orders_never_silently_recover -q`
结果 **1 passed in 4.73s**。未运行仓库全量回归。

## 限制与待决定事项

- 技术PASS不代表新增研究绩效验收、独立前向样本、真实券商连通或流动性验证。
- EX078旧格式历史账户未认证；本次附加基线仅为EX080同一C9902当前契约证据。
- 本次未冻结、未部署、未切换PTE账户、未改生产；没有合并master、打tag或推送。
- 建议批准本报告列出的精确对象后执行S011-v2冻结；部署和生产账户切换仍需另行批准。
