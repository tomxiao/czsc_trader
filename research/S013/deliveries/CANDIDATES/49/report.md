# EX053 原相关背景下下跌低价定时退出后重入方向对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

保留C2132原相关性过滤和原买入确认，只增加固定的再次入场条件：上次持仓是下跌路线、最终因到期退出、退出信号收盘价低于该次入场信号收盘价时，后续原本满足条件的下跌买入还需今天收盘价高于前一交易日。这里的低于是信号价格比较，不代表实际交易亏损。

记忆跨空仓、资格不满足及市场状态变化保留，任意路线成功发出入场信号后清空。持仓期限、全部退出优先级、费用及执行保持；不按日期或未来收益分类。原13数值中心、全域、同32坐标和父暖启动均保持；固定方向与类别选择仍有结构风险。

## 完整账户背景对照

| 背景与门控 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 四项目标 |
|---|---|---:|---:|---:|---:|---:|---|
| 原相关、无门 | C2132 | 16.1572% | 14.1599% | 112 | +12.1687% | +0.2841% | 通过 |
| 原相关、低价到期后重入门 | C7580 | 12.8588% | 14.6157% | 108 | +3.2530% | +0.2856% | 未通过 |
| 均值调整相关、无门 | C8701 | 13.5405% | 23.9087% | 123 | +11.4638% | +0.5481% | 未通过 |
| 均值调整相关、相同重入门 | C4900 | 10.8889% | 21.2540% | 119 | +9.4200% | +0.5491% | 通过 |

新中心逐项判断：年化收益通过；各自然年回撤通过；闭合交易频率未通过；基准亏损年份仍盈利通过。

四行是按精确身份与完整原生账本认证的独立完整策略，前三个旧账户不新增评价；原相关新门是本轮唯一新增业务账户。均值背景无门对照即使未达标也完整呈现，仅作机制诊断，不成为参数面板或新增资格条件。全期回撤与逐自然年回撤口径不同，资格使用原逐年门。

新中心串行与spawn信号及双方五账本精确一致，独立公式与全部状态/入场锚点/分类审计通过，所有成交、现金、费用与年度权益分别核对。不同完整策略间差异不等于删除旧交易利润；信号入场与实际首次成交可不同，实际多次成交按全量账本核验。

相对原中心，目标仓位不同28天，原因不同44天；首个仓位分歧2020-09-10 00:00:00。

新中心未达原四门，不运行32点；新增和复用参数账户均为零。

## 最强反证与解释边界

原中心2023年低价到期后重入来源实际贡献+2.3049个百分点，而全年只有+0.2841%；该来源含有维持年度盈利的机会。全下跌价格方向门先前只剩96笔且2023亏损。均值背景相同门虽中心达标，参数较差一端收益和回撤均劣于原C2132。局部门也可能伤害恢复机会，不能把低价退出自动当作坏交易。

上一轮双相关共同确认年化12.5897%、107笔且2022亏损3.4613%，费用下降未抵消实际价格路径收益损失；据此保留原相关算法，本轮只改变局部再次入场条件。原112笔仅比最低110笔多2，2023盈利余量很小，频率与年度盈利的失败都会按原门完整呈现。

纯runtime、独立oracle、原13域参数辅助及33条合成完整路径互证通过，失败和修正证据保留。合成检查确认实现语义，不代替经济目标。反复使用已见S013开发池，未获独立市场验证；FULL只检验证据完整性。RSCH阶段三。

完成判断：{'center_four_gates': False}

本机制未满足原联合目标；保留负面结果，按实际原生路径继续机制反证，不追加年份例外或缩窄参数域。

新增机制业务账户1、实际评价2；旧中心精确复用3；新增参数业务账户0、实际评价0、复用参数账户0。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/49/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/49/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [B0-MEAN](../../../assets/deliveries/CANDIDATES/49/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [N0](../../../assets/deliveries/CANDIDATES/49/evidence/5f96a39ece6ff78ac7c22324e3bee87e8bbe0a7314622800c5621f75d410152d.json)
- [plan](../../../assets/deliveries/CANDIDATES/49/evidence/bb7d2b29cec39f3e6aeac0e1727de91835c380e27f59ea86f61f4ebf9d3c79f8.json)
- [raw-below-reentry-method](../../../assets/deliveries/CANDIDATES/49/evidence/d28adcc2d8c3ff9ccc6ec946583f857446425ede75c0b3ccfab3d155656053ad.json)
- [geometry](../../../assets/deliveries/CANDIDATES/49/evidence/5f7526dc5d1c9d7ce9da0235efbe15ae8ed85db3b526fa1dfb6d87353c5f7f6f.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/49/evidence/7edff8bc25397b2c230c5a32c66424d29a60f9f7883216985e8ca8cb21ff0ad0.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/49/evidence/88ee055c8d459c0f0694867a04c2e0c38d5445722ee6a4e06108d43387470e0c.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/49/evidence/df43a16b21584a8ec14cddb43f3ffc3535a02e355785d2bf0a1e2d7c6ca6927b.json)
- [crosscheck-pure-prototype](../../../assets/deliveries/CANDIDATES/49/evidence/3c96692de799eaa7c3d9c7ace9770f051cab175a5dac1c3403ebe3e9234a9bd3.json)
- [protocols-analysis-repair-method](../../../assets/deliveries/CANDIDATES/49/evidence/8199206be6d6904e42fd5bca0a50de364e60a5fcfa63dcab144908b134382a19.json)
- [protocols-analysis-repair-method-reference](../../../assets/deliveries/CANDIDATES/49/evidence/6ee6ccd458c13e4308f7531d0299db0f0d0ce5780a0e71131eb061b995b2c48b.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/49/evidence/af8e24435056264eb71c6a5ce145edc5c9579b48a9df9436d098f4c777113392.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/49/evidence/99ebbef8f8f700195c063d589189ef7dcadafbe54dacd51070dd5d1167d83e00.json)
- [protocols-method-reference](../../../assets/deliveries/CANDIDATES/49/evidence/77865cb9961fb56dcfb1d7c363a94c68c0a92b9e51da6a8532f93b7a21e3760f.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/49/evidence/a64ab366553acb79e28331af76b8e4188c7fc150ecc46784a1ee10dd240ed99e.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/49/evidence/9bf1710ae6a9fb8f6664919dda8d6d88c512a5df6746007d520507aed186ba00.json)
- [protocols-technical-oracle-newline-failure](../../../assets/deliveries/CANDIDATES/49/evidence/698292d32b21c5162cc8c1b57e79c51677abb8e37ce751b51d2663d2da8d8b3c.json)
- [protocols-technical-proof-status-failure](../../../assets/deliveries/CANDIDATES/49/evidence/58a0876a1960e15490a74acb8208ef9cbf9a4fb891ea00082c9fe53022591d25.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/49/evidence/280f8a352faceca2caa01536eb0c0c251aa0ea4d5373647f62f152c7b49535d9.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/49/evidence/68ea96c249e689ff75aa72a369fdfde1a1b9dc0bb1839971827833e0b259bf8e.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/49/evidence/913f24e707320ffda4a933d525d15f677a878189871bd7945f3bca0e1dd3d34e.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/49/evidence/f21b5f23d00d17d445969ad004a72f88e591ffaee636c1d55163fd354fabd632.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/49/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/49/evidence/4a56ef6f58f4b6d6fd4e4f8227f45bcedb83456f1754b0dc556619ba65444452.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/49/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/49/evidence/78e7c236d6dcf8eb07595ff3465d8a051753163dfe8d0ba871a0d0f05ba947bd.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/49/evidence/d96d0d71175f946c7c7dc620c56956bcdff2f10f04caf3f89272f4d6cad3d364.json)
