# S012 · COMPONENTS · 1

研究员声明状态：BLOCKED
归属：EX012_20261004

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容

- 实验证据：EX001_20261004；用途：HISTORICAL_REFERENCE；回执：`07f196cd4dfebccf2a1906bb0b7d07f2b9644b1be02d716bf386a692b55dca8a`
- 实验证据：EX003_20261004；用途：HISTORICAL_REFERENCE；回执：`95f4b4dfc2f08ce0a0726dc7f8ac20787a436c25cdec93435950eba90e77f1a1`
- 实验证据：EX004_20261004；用途：HISTORICAL_REFERENCE；回执：`b4b318ae21c7b9f95c268b7f4a9b5cf1c0620da5f0234c073cdab1bda76187c8`
- 实验证据：EX005_20261004；用途：HISTORICAL_REFERENCE；回执：`528693224d850de4a288b0c899fe433bdec7da7f4b78a7e52c241fb4d2d5ba31`
- 实验证据：EX006_20261004；用途：HISTORICAL_REFERENCE；回执：`e594996ec1d42f2e4b8b30fc56862d4447bf94376d60266ff6e7f9ad3f24fdf7`
- 实验证据：EX007_20261004；用途：HISTORICAL_REFERENCE；回执：`d0d8605fa130c1c155879db033017ce65efbc4c999954121fcd18cf0253fe72d`
- 实验证据：EX008_20261004；用途：HISTORICAL_REFERENCE；回执：`18fdf3b220cd34d8e91c5a6a37997e2dbec1a0dc2e533151305a8a386438b8c8`
- 实验证据：EX010_20261004；用途：HISTORICAL_REFERENCE；回执：`c287c177f9cd1abb049c772d5eebc14f097e0329888e6ac6f409999c21d35727`
- 实验证据：EX011_20261004；用途：HISTORICAL_REFERENCE；回执：`7d6756219224c657b8d98c3aa04d2aa50299faa1a22d35b5e146686f1f5eddc7`
- 实验证据：EX012_20261004；用途：CURRENT_EVALUATION；回执：`cf6662926bcb40240a0f7cb863417118b9aad8575df6317d5284326a18b90cc6`

本轮为EX010后继数据门补充。原组件面板保持EX010；全历史目标分钟价格冲突未解决，未新增日内收益组件。


## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| target_full_history_ready | False | boolean | AVAILABLE | — |
| peer_full_history_ready | True | boolean | AVAILABLE | — |
| return_paths | 0 | count | AVAILABLE | — |

target_full_history_ready 证据：[experiments/EX012_20261004/data_audit.json](<experiments/EX012_20261004/data_audit.json>) `c1bae0dfbc603c9b510420a7178ec6ee12f4b925be4f8432f93462afec7c88fa`

peer_full_history_ready 证据：[experiments/EX012_20261004/data_audit.json](<experiments/EX012_20261004/data_audit.json>) `c1bae0dfbc603c9b510420a7178ec6ee12f4b925be4f8432f93462afec7c88fa`

return_paths 证据：[experiments/EX012_20261004/data_audit.json](<experiments/EX012_20261004/data_audit.json>) `c1bae0dfbc603c9b510420a7178ec6ee12f4b925be4f8432f93462afec7c88fa`

## 解释

**FACT**：目标全历史分钟请求仍失败；已核验7日成交量修复。

- target_full_history_ready：False boolean
- 支持证据：[experiments/EX012_20261004/data_audit.json](<experiments/EX012_20261004/data_audit.json>) `c1bae0dfbc603c9b510420a7178ec6ee12f4b925be4f8432f93462afec7c88fa`
**RESEARCH_JUDGMENT**：遵照用户要求，完整历史通过前暂停收益检验；不能以日线值覆盖分钟路径后的一致性作为独立真值证据。

- 支持证据：[attachments/scope.json](<attachments/scope.json>) `7ceb1b632a7f920697236746392ac5953849dff95322c43abcff47f8dc21c092`
- 支持证据：[attachments/dev_diagnostic_summary.json](<attachments/dev_diagnostic_summary.json>) `7ef26b8d632979922064b1d1c0938382d45f9fb0b2ec6688a4d418cb1b33085c`
**FACT**：AvailableDate是明确的市场观察假设，历史API逐条发布时间及实时延迟未验证。

- 支持证据：[experiments/EX012_20261004/data_audit.json](<experiments/EX012_20261004/data_audit.json>) `c1bae0dfbc603c9b510420a7178ec6ee12f4b925be4f8432f93462afec7c88fa`

## 未完成事项

- 解决目标ETF全历史分钟价格冲突，并复验完整覆盖。
- 期货分钟权限缺失，真实实时数据可得性待核验。
- 尚未进行新增日内机会收益检验。

## 复算

核验EX011及前驱；新数据快照或修复通过后创建后继实验复验完整历史，不覆盖本实验。

数据访问：受管输入为DFLS/Tushare；DEV原始诊断保存在本机artifacts/dev_source_support，未用于收益计算。

确定性及容差：身份与文件哈希严格；供应商修订需重新留证。

- 环境：[attachments/protocol.md](<attachments/protocol.md>) `a0e398084a29e417c24fcd3fae4e749363c1ab83f66f451bf5efe8030668aef6`
