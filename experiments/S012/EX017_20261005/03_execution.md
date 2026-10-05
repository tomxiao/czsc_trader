# 执行记录

2026-10-05，RSCH，完成真实 VWAP 正常定价状态竞争检验。源码和固定协议在正式执行前绑定，合成预检及受管前检完成后执行。正式结果为 `INCONCLUSIVE`，表示组件研究结论保留不确定性。交付 FULL 和档案核验由后续发布流程执行，本文不预先声明通过。

- 源码 SHA256：`42682d843e49952d7c30fe315abab128064a3976da1054a37e537e1e9cd51611`。
- 定义 SHA256：`15f5c23514eabff7ba3c0112c56f4e50cf8df2b5ac55bcd3782db0518d715c3e`。
- 回执 SHA256：`ee1c6e995c13e0c8e9970b66c0a8c7c354961f8821ce748184deb449b62e9beb`。
- 直接前驱 EX015：`17d9453c45bb67b9a517546c644d8071688b636aea2774b114739b8a7600071b`。
- 直接前驱 EX016：`c57c2bbba0dff33facf4ea2ecaa78b7b143ad127c76ed79dada446aa50526b00`。
- 数据作用域 `DEVELOPMENT`；实际能力轨迹为真实收益读取及开发选择，数据请求和账户评价轨迹为空。
- 资源预算半 CPU、并发上限 8、native 线程 1。源码闭包为 `experiment.py`、`mechanism.py`、`statistics.py`；定义声明 NumPy、pandas、SciPy、tsfresh、expr_codegen 的实际安装版本。

受管输入来自已验证前驱制品：EX015 的 `data/daily.parquet`、`coverage.json`；EX016 的 `features.parquet`、`signals.parquet`、`valids.parquet`、`thresholds.parquet`。每项实际读取文件按正式前驱回执逐 SHA 核验，记录见 [输入与选择历史](artifacts/rex/selection_history.json)。年度 VWAP 阈值重算与继承值逐值核验；相同计算输入复用既有 FSC、tsfresh 和表达式结果，无新取数来源或平台修改。

合成预检实际核对中段含边界、零归非负组、NaN 和缺阈值无效、缺子组输入无效，未来数据扰动不改变历史阈值/信号/有效掩码；4 个非重叠事件区间为空并附原因。统计并集与区间沿用主标签有效掩码，与机会台账一致。合成输出严格 JSON 序列化及源码 Ruff 校验通过。

11 项信号、264 条期限/延迟/费用/质量路径正式完成，保留 7 项新增及 4 项对照的全部结果，另留逐年分项、11 项本轮主标签排列/BH、11 项非重叠区间与 5 项固定并集。完整结果由 [真实执行回执](artifacts/rex/execution_receipt.json) 和 [执行结果](artifacts/rex/execution_envelope.json) 绑定，原始源码与制品不再改写。

所有本文路径为相对路径。数据空间及前驱制品需一并保留；跨机器复验需同步真实制品和依赖闭包，Git 文件本身不能替代数据资产。
