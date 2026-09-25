# S008 EX67 执行

REX执行结果：`PASS`；receipt：`b5677eb58d844166dd8e255a4afa04e9c07569ab3b613b54a360da6af784056b`。

有效trial=1395，收益门通过=0，回撤门通过=1281。随后仓库`archive validate --all`发现生成的
manifest缺少策略实验必填字段`symbol`，因此本实验最终状态记为`ARCHIVE_VALIDATION_FAILED`。
该问题发生在结果归档阶段，不构成金融结论；后继实验只能修正归档实现并消费本次固定receipt。
本实验没有读取封存验证区、运行搜索、选择参数、形成候选或修改平台。
