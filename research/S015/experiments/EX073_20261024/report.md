# S015 EX073：跨尺度组件对照

Status: COMPLETED

阶段二第7轮，18配置、36正式账户、2技术账户。

六组同尺度、同入场对照中，中心失效保护均降低纯固定锚修复的回撤，并提高闭合频率中位；五组以牺牲收益换取风险改善，median10则收益与回撤同时改善。这支持组件风险/资金占用职责可在其他尺度重复，不意味着任何尺度都达标。

相对固定三日退出，2日与5日的mean/median完整事件原型均提高收益并降低回撤；10日mean收益更低且回撤更差，10日median收益较高但回撤更差。最强反证必须保留：事件规则没有普遍支配固定期限，三日的双目标过线不能推广为尺度稳健。

本轮不继续枚举更多尺度寻找过线点。当前机制与组件协作已有发展依据，下一步清理原型表达、核验实际成交与成本代价。

| 身份 | 中心/尺度/退出 | 434收益 | 回撤 | 频率中位 | 联合中心 |
| --- | --- | --- | --- | --- | --- |
| C7300 | mean/2/anchor_center_origin | 48.2224% | 10.0502% | 10 | False |
| C7301 | mean/2/anchor_repair | 86.5892% | 19.5461% | 6 | False |
| C7302 | mean/2/fixed | 45.8749% | 16.1865% | 8 | False |
| C7303 | mean/5/anchor_center_origin | 58.2831% | 9.1869% | 9 | False |
| C7304 | mean/5/anchor_repair | 114.5466% | 14.5330% | 6 | False |
| C7305 | mean/5/fixed | 57.6582% | 12.7678% | 8 | False |
| C7306 | mean/10/anchor_center_origin | 50.8059% | 11.6122% | 9 | False |
| C7307 | mean/10/anchor_repair | 57.8804% | 30.9377% | 5 | False |
| C7308 | mean/10/fixed | 71.2813% | 11.1782% | 8 | False |
| C7309 | median/2/anchor_center_origin | 53.9882% | 13.9230% | 9 | False |
| C7310 | median/2/anchor_repair | 98.0295% | 19.5564% | 5 | False |
| C7311 | median/2/fixed | 47.2208% | 16.8453% | 7 | False |
| C7312 | median/5/anchor_center_origin | 87.2262% | 9.1844% | 9 | False |
| C7313 | median/5/anchor_repair | 121.0963% | 14.5313% | 6 | False |
| C7314 | median/5/fixed | 60.0166% | 12.7676% | 8 | False |
| C7315 | median/10/anchor_center_origin | 87.4599% | 11.6223% | 9 | False |
| C7316 | median/10/anchor_repair | 61.6020% | 30.9405% | 5 | False |
| C7317 | median/10/fixed | 77.0482% | 8.8130% | 8 | False |

[事前协议](protocols/accounts.json)、[完整结果](others/results.json)、[账户算术与公开诊断](others/audit.json)、[因果前缀](others/runtime_checks.json)。公开归因不支持的状态保留；不是因果分解。全部数据已见，本轮重复的完整事件原型不计为独立发现，也不是阶段四局部扰动自检。
