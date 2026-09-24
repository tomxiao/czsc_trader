# S008 EX79 预注册设计

- 完整继承 EX78 的研究问题、固定来源、共同窗口、P02/P06 代表、四项 T-1/T-21 因果观察、停止边界和 `DISCOVERY_ONLY_OPPORTUNITY_MAP_REVIEW_REQUIRED` 裁决。
- 精确修复：冻结 EX78 的源码与失败 manifest 哈希；只把两处 `negative_avoidance_ratio` 列引用改成账本真实的 `negative_log_return_avoidance_ratio`，并将实验身份改为 EX79。替换计数与内容不匹配则报错，不继续执行。
- 不加入因子、阈值、收益标签、外部数据或新决策规则；EX78 的失败档案保持不可变。仍以 EX68 receipt 作为 REX 机器前序，EX78 作为哈希锚定的失败技术前序。
