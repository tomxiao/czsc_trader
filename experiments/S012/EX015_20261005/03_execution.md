# 执行记录

2026-10-05，RSCH，完成既有数据上的日内机会广泛筛查。执行前完成合成预检和受管前检；受管正式结果为 `INCONCLUSIVE`，该状态表示研究结论尚未确定。当前记录不预先宣称后续交付验证或归档验证通过。

源码与定义在正式执行前绑定：

- 源码 SHA256：`8fffa1c74ea1f838aac4387150c441391b016a71f76c1694b2a78efb6814f4ff`。
- 定义 SHA256：`0869c639e61762be30c7773c0427dfd2e26efa2e77e0f820624616c9aa317d25`。
- 回执 SHA256：`17d9453c45bb67b9a517546c644d8071688b636aea2774b114739b8a7600071b`。
- 资源预算：半 CPU，并发上限 8，原生数学库线程为 1。
- 数据作用域：`DEVELOPMENT`；能力轨迹包含真实收益读取及开发选择，未创建策略候选或账户评估。

正式回执为 `artifacts/rex/execution_receipt.json`，结构化执行结果为 `artifacts/rex/execution_envelope.json`。全部源数据、派生特征、标签和统计文件由回执中的 SHA256 绑定。

先经 DFLS `REUSE` 受管准备及读取目标日线、目标 5 分钟和参考日线，三项均为 READY。目标及参考日线各 1535 行，目标分钟 73680 行。完整率与准确率、数据身份和 prepared 引用见 `artifacts/rex/data_audit.json`。27 个特征、48 个信号、1152 条路径；完整日内记录检查没有整日缺口。

第一次执行 workspace `.tmp/s012-opportunity-20261005/mechanism-execution` 因沙箱权限产生 `PermissionError: [WinError 5]`。失败记录保留在其 `execution_failure.json`；以相同源码和定义、在获得执行授权后改用新 workspace `.tmp/s012-opportunity-20261005/mechanism-execution-authorized` 重试并完成。失败 workspace 未覆盖、未继续追加。成功回执和制品复制至当前 `artifacts/rex`。

真实日线 VWAP 的历史普查覆盖描述在选后核对时未获源码支持；本轮生成表达式但未加入检验，修订依据及补齐方案记录于 `04_conclusion.md` 与 EX016 协议。

所有本文路径均为相对路径；涉及其他实验或 `.tmp/` 的路径以仓库根目录为起点。后续源码、供应商快照或机制修改必须建立后继实验，保留当前回执及全部结果。
