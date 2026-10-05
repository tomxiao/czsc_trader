# S012 · COMPONENTS · 1

研究员声明状态：COMPLETE
归属：EX014_20261005

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
- 实验证据：EX012_20261004；用途：HISTORICAL_REFERENCE；回执：`cf6662926bcb40240a0f7cb863417118b9aad8575df6317d5284326a18b90cc6`
- 实验证据：EX013_20261005；用途：HISTORICAL_REFERENCE；回执：`f6453dda0b2585bc1637857af35de021b8c5c04d35daf5d4406f571790eddfbe`
- 实验证据：EX014_20261005；用途：CURRENT_EVALUATION；回执：`609de5505aba3edee6bed6247b5fd11f2df9d19373477f4c56cd2dcb1cc3fca2`

EX010原机会面板保留；本轮只交付独立相对落后机制增量，阶段二继续，未进入阶段三。

### O02_LAST_HOUR_RELATIVE_LAG

职责：机会机制诊断

研究判断：主路径费用后增量或异常敏感性未支持机制；保留负面证据。

适用边界：全上市开发池；只做多、各侧0.1%费用；异常敏感性预声明

标签／期限／对照：T+1至T+4开盘净收益 / 3交易日；1/5日诊断 / 年度毛收益基线、绝对下跌事件、O01及并集

可用时点／价格口径：T日17:00观察，T+1执行；历史API发布未验证 / 不复权实际价格；分钟仅同步14:00 Close与日线收盘

- RELATIVE_LAG_3D：INEFFECTIVE；主路径费用后增量或异常敏感性未支持机制；保留负面证据。
  - 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>)
  - 证据：[experiments/EX014_20261005/annual.json](<experiments/EX014_20261005/annual.json>)
  - 证据：[experiments/EX014_20261005/feature_coverage.json](<experiments/EX014_20261005/feature_coverage.json>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |
| inputs_ready | True | boolean | AVAILABLE | — |
| main_events | 8 | count | AVAILABLE | — |
| main_net_mean | 0.0003548269891021638 | ratio | AVAILABLE | — |
| main_increment | -0.0011886953572947476 | ratio | AVAILABLE | — |
| clean_increment | 0.004678309917810535 | ratio | AVAILABLE | — |
| limit_capacity | 0.11726384364820847 | ratio | AVAILABLE | — |

inputs_ready 证据：[experiments/EX014_20261005/data_audit.json](<experiments/EX014_20261005/data_audit.json>) `34973ee2cca0c635eb2ab4efeb1697d745e0c017284099adf9a6de04aa587105`

main_events 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

main_net_mean 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

main_increment 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

clean_increment 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

limit_capacity 证据：[experiments/EX014_20261005/opportunities.json](<experiments/EX014_20261005/opportunities.json>) `b624cd9c5d95b3463c4bbebc2a086e650878f15c3c6e16481bb74949cd42ac62`

## 解释

**FACT**：所有收益研究前先检查目标与参考全历史数据准备。

- inputs_ready：True boolean
- 支持证据：[experiments/EX014_20261005/data_audit.json](<experiments/EX014_20261005/data_audit.json>) `34973ee2cca0c635eb2ab4efeb1697d745e0c017284099adf9a6de04aa587105`
**RESEARCH_JUDGMENT**：事件收益与日线触价不能代替完整账户目标或真实成交验证。

- 支持证据：[attachments/research_report.md](<attachments/research_report.md>) `2dfb5bfeae8fe9e3f55135cd15a99300903cfc66412533a87ca90329fa808958`

## 未完成事项


## 复算

按固定协议执行预检、受管prepare/fetch和REX执行，再验证本次交付及档案。

数据访问：既有Tushare；保留S012数据空间及全部前驱制品。

确定性及容差：源码、定义、输入及回执绑定；供应商修订创建后继实验。

- 环境：[attachments/protocol.md](<attachments/protocol.md>) `2c52e6a23f7b5dc9505569817b11ef1dce6519f4f2a5d9560d941ead97fdcb7e`
