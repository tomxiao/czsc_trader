# 执行与证据

合成预检、受管执行结果及数据质量事实见artifacts/preflight.json、artifacts/result.json、artifacts/rex/data_audit.json。供应商SDK诊断仅为DEV数据修复证据，保存于artifacts/dev_source_support，不用作收益计算输入。

平台聚焦验证：30项测试通过，覆盖未复权分钟入口、可得时间声明、历史修复注册、未知签名失败和价格冲突阻断。

交付组装入口为research/S012/deliverables/intraday_data_gate.py，显式声明完整前驱证据闭包。实验绑定中的delivery.py草稿未发布；执行后未修改绑定源码。
