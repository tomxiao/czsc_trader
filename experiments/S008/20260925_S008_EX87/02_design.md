# S008 EX87 预注册设计

- EX86 在 `load_execution_prices` 返回带 `dt` 列、默认 `RangeIndex` 的 DataFrame 时，直接用其 `open` 列按日期重索引，产生全空开盘价并停止。它没有形成金融结论。
- 锁定 EX86 源码闭包 SHA-256 `41a0d63246e9eae06758d74f0a7c4c2509780435444a7e88299299cc4b69b260` 和失败 manifest SHA-256 `979a7ff63b2cf93adb12a784fb34bbb24942ba10cbba4aa2c4ffb6ff5c3907a6`；任一不符立即失败。
- 仅做两处精确变换：实验身份 `EX86`→`EX87`；`prices["open"].reindex(positions.index)`→`prices.set_index("dt")["open"].reindex(positions.index)`。两处各须出现一次。其余研究合同完全继承 EX86 `02_design.md`。
- 合成数据预检日期索引和季度收益恒等式后，才读取截至 2024-12-31 的已见开发期收益。不读取密封验证，不搜索或创建候选。
