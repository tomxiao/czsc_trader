# EX38 技术适配执行

612 个固定候选经 `register_candidate` 登记，并经 `load_candidate` 与 `StrategyRuntime.identify` 逐个校验。36 个中心、576 个扰动；2 份源码通过 AST 差异约束，参数保持不变。预检使用每候选 40 行合成信号；未读取行情、未搜索参数、未执行真实市场评价。
