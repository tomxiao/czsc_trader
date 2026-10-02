# EX38 设计

- 固定输入为 EX33/EX37 来源的 36 个中心和 576 个扰动候选。原源码、参数文件及历史评价回执保持原字节；不解析为当前研究认证结果。
- 中心编号按原数字部分归一，例如 CFG000621R2 → C0621。扰动按父编号和原 J 序号排序，分配 C1001—C1576；父子关系单列。
- 源码只升级 RuntimeDefinition schema 并增加 score、入场/退出阈值、reason、intent_age 观测声明。AST 验证排除这两处差异后必须与原源码一致。
- 612 个候选的参数须与原 payload 精确一致。每候选执行 40 行合成信号验证，并检查 typed observation 字段类型。
- 经真实预检后使用 TDR register_candidate 登记，再以 load_candidate / StrategyRuntime.identify 逐个验证持久化实体。
- 当前身份全部 NOT_EVALUATED。旧派生证据保留历史引用，不改写 candidate_id 或内容哈希；当前登记不生成 CandidateDerivation 认证。恢复真实评价后再建立对应认证关系。
- 技术结果与实体保存在本实验；research 仅更新交接导航。成功验证后删除被替代的 612 条旧格式现行登记；此前明确保留的 100 条 schema 1 历史记录不在本次迁移范围内。
