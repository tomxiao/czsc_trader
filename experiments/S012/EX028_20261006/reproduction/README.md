# 阶段三独立复核

在仓库根目录、原平台依赖环境下运行。保留本目录工具同级关系，动态导入需要相邻的审计与加速器源码。下列工具只读原始账户及受管DFLS输入，新报告统一写入.tmp，不覆盖封存证据。

账户审计命令：

    .venv/Scripts/python.exe experiments/S012/EX028_20261006/reproduction/independent_account_check.py --experiments EX023_20261005 EX025_20261005 EX028_20261006 --output .tmp/s012-stage3-recheck-account.json

完整经济账本等价核验命令：

    .venv/Scripts/python.exe experiments/S012/EX028_20261006/reproduction/compare_accelerator.py --experiment EX028_20261006 --output .tmp/s012-stage3-recheck-equivalence.json

合成核验工具会在.tmp创建独立合成受管资源；重复核验时先保留旧输出，使用新的报告路径。已运行的8场景结果见../artifacts/verification/synthetic_equivalence.json。最终审计字节映射见../artifacts/verification/final_audit_evidence_manifest.json；其中.tmp路径记录原计算位置，文件名对应本目录源码或../artifacts/verification内同SHA副本，无运行时读取这些旧输出路径的要求。

真实输入需要原S012实验前驱与data/backtest受管资产及准备记录。仅检出Git源码不能恢复被忽略的完整账本、受管数据和交付证据。按实验binding及execution_driver重放须使用后继实验，保留绑定源码、协议、依赖、种子与交易合同，不覆盖已经封存的实验。

EX026原执行没有完整REX回执；其计算及账本从EX027认证的inherited_search_bundle.tar.gz读取，原失败状态保持。局部搜索和正式复算的成功不改写前轮技术失败。CandidateSet校验与账户经济目标分别解释，0个达标候选保持。
