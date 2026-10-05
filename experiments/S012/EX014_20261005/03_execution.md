# 受管执行记录

执行前固定协议及源码闭包，合成预检PASS；半数CPU上限8个worker、数值库单线程。EX013数据门PASS之后正式执行；输入为S012独立数据空间，通过prepare及持引用fetch获取。

518850日线及30分钟线、参考518880日线及30分钟线全部READY，完整覆盖2020-06-05至2026-09-30共1535日。目标日线准确率100%、30分钟98.3062%；参考日线和30分钟准确率100%。现行准备门通过不代表分钟真值逐根验证。

14:00双腿特征可评价1531日，4日因目标无成交等时点条件不可评价：2020-09-11、2020-09-16、2021-09-14、2023-08-28；不填充。3日标签另损失尾部4日，主事件可评价交集1527日。容量始终使用全部1535日分母，未缩短历史。O01信号来自EX010的哈希绑定制品，保留其自身训练空窗，不受本轮分钟缺失日阻断。

执行固定1/3/5日标签，主判据为3日；零参数搜索。26个目标30分钟异常日预先纳入敏感性，排除任一异常覆盖的决策日至标签退出日。执行回执给出研究FAIL，实际执行与留证成功。

机器证据：[预检](artifacts/preflight.json)、[输入审计](artifacts/rex/data_audit.json)、[事件面板](artifacts/rex/event_panel.parquet)、[全部路径](artifacts/rex/opportunities.json)、[年度](artifacts/rex/annual.json)、[覆盖](artifacts/rex/feature_coverage.json)、[独立性](artifacts/rex/independence.json)、[回执](artifacts/rex/execution_receipt.json)。

制品及交付中的实验副本仅在本机；跨机器复验须保留完整S012数据与前驱链。执行回执完成后未追加受管评价；阶段交付在档案manifest生成前完成。
