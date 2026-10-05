# 执行记录

2026-10-05，RSCH，完成 EX015 已选路径复核及真实 VWAP 8 方向补齐。执行前完成合成预检和受管前检；受管正式结果为 `INCONCLUSIVE`，该状态表示研究结论尚未确定。当前记录不预先宣称后续交付验证或归档验证通过。

源码与定义在正式执行前绑定：

- 源码 SHA256：`df2801f5d45f4072e0501d3d334f7f04d35d3ea9eaa2b064862568af035f4796`。
- 定义 SHA256：`6f6b5d457874a5d6799083fd0c2bdbbbcedea1b3093d18f84d638cc79b3a2851`。
- 回执 SHA256：`c57c2bbba0dff33facf4ea2ecaa78b7b143ad127c76ed79dada446aa50526b00`。
- 资源预算：半 CPU，并发上限 8，原生数学库线程为 1。
- 数据作用域：`DEVELOPMENT`；能力轨迹包含真实收益读取及开发选择，未创建策略候选或账户评估。

正式回执为 `artifacts/rex/execution_receipt.json`，结构化执行结果为 `artifacts/rex/execution_envelope.json`。全部源数据、派生特征、标签和统计文件由回执中的 SHA256 绑定。

逐文件核验 EX015 前驱制品 SHA，输入身份及前驱回执绑定记录于 `artifacts/rex/selection_history.json`。本轮没有新 vendor 数据请求，回执数据轨迹为空对应读取已验证前驱制品；并不表示使用未受管数据。

FSC 真实 VWAP 偏离与 EX015 表达式逐值核验通过。保留 6 个选后方向及 8 个新增方向，形成 14 个信号、336 条期限/延迟/费用/质量路径；同时记录 999 次非重叠事件块重抽样、6 个固定并集和年度前缀选型。

合成预检发现的 allowed_datasets 空声明及导入问题已在正式执行前修正，随后重新绑定源码和定义，正式前检为 PASS；这些前检修订没有改写已生成的正式收益结果。当前正式执行 workspace 为 `.tmp/s012-opportunity-20261005/confirm/execution`。

所有本文路径均为相对路径；涉及其他实验或 `.tmp/` 的路径以仓库根目录为起点。后续源码、供应商快照或机制修改必须建立后继实验，保留当前回执及全部结果。
