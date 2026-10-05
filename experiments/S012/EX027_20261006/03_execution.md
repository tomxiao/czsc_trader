# EX027_20261006｜执行留证

预检见[preflight](artifacts/preflight.json)，完整执行证据见[REX receipt](artifacts/rex/execution_receipt.json)。回执哈希`aee52fd3e31b3386f0c11344448af0f216d0cd51ca2ee93f93806eb05277b171`。

单批实际最多4账户（EX023首批1账户），每worker原生线程1；声明资源上限与实际并发见执行回执，并发实验总体不超过半CPU。复用已认证DFLS PreparedDataRef，公开fetch核验输入身份，不覆盖旧prepare或原质量证据。

本实验Optuna提案状态：{'COMPLETE': 144, 'PRUNED': 38}。每个成功研究账户的完整signals/decisions/account/orders/fills/trades gzip均进入受管制品闭包。EX026封存计算全量bundle和真实failure已逐SHA继承并正式登记，不将EX026伪装为完整REX。

技术前轮EX020/21/22封存保留；EX022显式中断，不能声称存在完整REX回执或账户绩效。
