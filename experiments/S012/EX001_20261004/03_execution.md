# 执行

正式REX合成预检通过；数据探测未在预检联网执行，实际请求在受管执行中完成。
11项请求中10项READY。VIX因缺少必填symbol返回DATA_CONTRACT_MISMATCH，后继实验显式改为VIX。
期货12280行按日期与合约联合主键解释，同一天多合约不属于重复记录。
完整来源及错误见artifacts/rex/data_audit.json；实际执行回执见artifacts/rex/execution_receipt.json。
