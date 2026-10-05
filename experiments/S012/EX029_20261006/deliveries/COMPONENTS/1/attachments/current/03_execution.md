# EX029｜执行记录

预检PASS，3项合成检查PASS（因果截断及未来扰动、缺失边界、T+1标签/费用/尾部边界）。受管REX实际完成，结果INCONCLUSIVE。顺序执行worker=1、native_threads=1、seed=12029，未调用新外部市场数据源或改动平台。

实际10个原始源逐SHA复用；原1535上市交易日；19固定假设与11对照，600路径、4200年度、19主推断。真实回执SHA：6c9d66dd50db298aab27d96310abafdf082c902ca97b25014f1408620b239303。数量说明见[口径纠正](protocol_count_correction.md)，原固定定义和源文件不变。

[独立复算](artifacts/verification/independent.json)PASS：198004个数值字段、所有源哈希、源变化/可得时间、换月排除、20标签场景、600路径/4200年度及BH19一致。独立复算不重复bootstrap或循环移位随机抽样，不证明政策时刻等于真实历史发布日期，也不验证账户绩效。

复算入口reproduction/verify.py，工作目录为仓库根。原正式入口execution_driver.py；复算须使用新实验目录以保留实际回执，不覆盖既有正式执行工作区。全部历史开发池且已见，未创建账户或登记策略候选。
