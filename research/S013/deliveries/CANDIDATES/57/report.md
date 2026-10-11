# 负跳空修复后的持仓退出对照

B0精确复用原C8880；N_GAP_EXIT仅在原规则会继续持仓时，遇当日开盘低于上一交易日收盘且收盘高于开盘，发出下一交易日市价退出。原入场、13数值参数、时间/区间/状态退出优先级保持。

|组别|净年化|全期最大回撤|每60日闭合交易|原四门|32逐项通过率|32联合通过率|Q10净年化|Q90回撤|
|---|---:|---:|---:|---|---|---:|---:|---:|
|B0|17.1346%|13.6187%|4.2543|收益=通过；年度回撤=通过；交易频率=通过；基准亏损年盈利=通过|收益=7/32 (21.88%)；年度回撤=32/32 (100.00%)；交易频率=27/32 (84.38%)；基准亏损年盈利=2/32 (6.25%)|0/32 (0.00%)|6.3981%|28.3508%|
|N_GAP_EXIT|7.6439%|17.8414%|5.8680|收益=未过；年度回撤=通过；交易频率=通过；基准亏损年盈利=未过|中心未过原四门，完整32不适用|未运行|未运行|未运行|

四门依次检查净年化收益、各自然年回撤、交易频率及基准亏损年份盈利；自然年连续净值计算沿用原冻结口径。Q10表示扰动后较差一端的收益，Q90表示较差一端的回撤，都是开发池事实。

新增退出沿用原策略的signal holding状态，不按实际账户position事后挑选。限价买单未成交也可能产生后续hold/exit信号；本轮经济指标只取完整原生订单、成交与现金账本，不能将信号退出直接当实际卖出收益。

优选：None。仅原四门合格的新中心登记；没有优选或全部新机制失败时也完整交付负面结果。自检与尾部诊断不增加经济资格门。

五项自检（参数、时间、盈利集中、独立双倍费用、统计不确定性）：

B0：

|诊断|实际值|公共状态|
|---|---:|---|
|全样本交易频率|4.254278728606357|AVAILABLE|
|净年化收益|0.17134559076619493|AVAILABLE|
|回撤幅度|0.13618731411686769|AVAILABLE|
|窗口频率中位数|4.0|AVAILABLE|
|窗口频率较差端|1.0|AVAILABLE|
|参数扰动收益退化|0.10736428879639186|AVAILABLE|
|参数扰动回撤退化|0.14732048204209386|AVAILABLE|
|时间窗口较差端超额收益|-0.19020221278503346|AVAILABLE|
|双倍费用年化损失|0.040899123668934445|AVAILABLE|
|盈利集中度|0.43805631757326063|AVAILABLE|

统计不确定性（公共SE原始结果）：{"type": "UncertaintyInterval", "status": "AVAILABLE", "lower_95": -0.07156187357254973, "upper_95": 0.25249278093695354, "reason": null}


|组别|自然年|策略净收益|策略回撤|基准净收益|基准回撤|
|---|---|---:|---:|---:|---:|
|B0|2020|16.5873%|6.6318%|22.1693%|14.9712%|
|B0|2021|8.2925%|3.5940%|17.2351%|9.7035%|
|B0|2022|19.5931%|6.8793%|-18.3203%|28.4105%|
|B0|2023|0.9181%|5.0771%|-6.2450%|17.2665%|
|B0|2024|65.0176%|10.0222%|6.9559%|18.5736%|
|B0|2025|11.0762%|3.5334%|32.7098%|13.7975%|
|B0|2026|-0.0388%|4.5430%|0.9947%|18.7646%|
|N_GAP_EXIT|2020|15.9929%|7.8476%|22.1693%|14.9712%|
|N_GAP_EXIT|2021|6.2937%|2.7007%|17.2351%|9.7035%|
|N_GAP_EXIT|2022|6.4970%|10.2585%|-18.3203%|28.4105%|
|N_GAP_EXIT|2023|-2.9412%|8.4075%|-6.2450%|17.2665%|
|N_GAP_EXIT|2024|18.4234%|11.2507%|6.9559%|18.5736%|
|N_GAP_EXIT|2025|5.3585%|3.9319%|32.7098%|13.7975%|
|N_GAP_EXIT|2026|1.4517%|4.5420%|0.9947%|18.7646%|

实际评价与复用计数：{"standard_roles": 34, "standard_unique_configurations": 34, "reused_baseline_accounts": 33, "new_standard_business_evaluations": 1, "new_unique_standard_configurations": 1, "new_technical_evaluations": 1, "new_fee_evaluations": 0, "reused_fee_accounts": 1, "new_actual_evaluations": 2, "all_actual_native_evaluations_including_reuse": 36}

本轮为EX064负面预测结果启发的探索性后继：原修复越强未来收益越好假说失败，5日控制后IC=-0.054454、95%块区间[-0.099498,-0.006396]、6相位5负；原C8880事前机会池不稳。本次改持仓退出位置，不反转原假说结论。修复也可能是好反弹，提前卖出可能错过恢复并增加费用；全池相关性不是账户改善或因果证据。

同一已见开发池反复选择未校正，没有新的封存验证。原已知High/Low异常不修价，输入审核按声明严格拒绝。T信号只能在T收盘得到；次日开盘前发生的价格变化不能当成可赚收益。信号BELOW类别不等于实际成交亏损。现金审核与独立状态核对不保证未来绩效。

没有优化参数、增加经济门或自动宣布总体稳健目标达成；阶段四交接与后续研究由用户的既有授权和具体结论另行处理。

- [证据 management-native-bundle](../../../assets/deliveries/CANDIDATES/57/evidence/37b89c3e3c14c0870e8bfe7cc8932399a411362ae7bb57ac724208a8ba4f4cf0.json)
- [证据 gap-exit-closeout-bfa907772bfb69523d530e129fad1b5c](../../../assets/deliveries/CANDIDATES/57/evidence/bfa907772bfb69523d530e129fad1b5ce01019e00a54d0a610adcd7744fad7ad.json)
- [证据 gap-exit-closeout-b4b636213540f6bac9cf6ddbb630b6b4](../../../assets/deliveries/CANDIDATES/57/evidence/b4b636213540f6bac9cf6ddbb630b6b41f90c51158b0064fbd53c15c46361bf8.json)
- [证据 gap-exit-closeout-6aa8d3ed38422964e6f4c109609b4652](../../../assets/deliveries/CANDIDATES/57/evidence/6aa8d3ed38422964e6f4c109609b4652c1c198c6dd351aec8a179ca5d4ab3db0.json)
- [证据 parameter-coordinate-mapping](../../../assets/deliveries/CANDIDATES/57/evidence/8311555eb89603e4768ba117d5db7a0610bc7baf45c6ccaadabdde854da15760.json)
- [证据 parameter-coordinate-feasibility](../../../assets/deliveries/CANDIDATES/57/evidence/9b6fe0400dd8a10418d3eb3faa01626be653a4dee64719896bc0d3db0b29e69e.json)
- [证据 management-prepared-centers](../../../assets/deliveries/CANDIDATES/57/evidence/a52d732065482230dbff6eecfe83ce95becfded4c6910cdbd3afcd0b4cbf0917.json)
- [证据 management-all-point-plans](../../../assets/deliveries/CANDIDATES/57/evidence/a6f593b4a11467b218b38706c9a2aa1490cdab4bb47cbc8aa6578d210e93e560.json)
- [证据 center-serial-spawn-exact](../../../assets/deliveries/CANDIDATES/57/evidence/68ae0dccc51a75ffce6e855b27f5ceb9bfb69ed9907dd0f291eb635ca7189e12.json)
- [证据 statistics](../../../assets/deliveries/CANDIDATES/57/evidence/1f24f113c9d46c1d2ff61f0afdad8dffeb283abf9ee202e1234f99f8a5873a1a.json)
- [证据 raw-boundary-body-local-bear-recovery-native-center-n0](../../../assets/deliveries/CANDIDATES/57/evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [证据 parameter-account-n0-p00](../../../assets/deliveries/CANDIDATES/57/evidence/cee623b26dcd6acfa525015d44499247fe7a6c66ab712923fdaa8a3601ff29bd.json)
- [证据 parameter-account-n0-p01](../../../assets/deliveries/CANDIDATES/57/evidence/b327425b049a0fe753e83a7b01091be2d890b04b0cfd0488462be5029d7bd768.json)
- [证据 parameter-account-n0-p02](../../../assets/deliveries/CANDIDATES/57/evidence/e5cfddd0149ca8ce280597e2abfaf0cca85f7c4620c31dae183813686f1ed932.json)
- [证据 parameter-account-n0-p03](../../../assets/deliveries/CANDIDATES/57/evidence/849fd521cb9b0130308c4b06a5911ee8e41736d7ee510d2531c108e8d886b8da.json)
- [证据 parameter-account-n0-p04](../../../assets/deliveries/CANDIDATES/57/evidence/82e4bae906ffa94ddf8fcbdf405aa00ab1cce7165687e8840c470419227a4a4e.json)
- [证据 parameter-account-n0-p05](../../../assets/deliveries/CANDIDATES/57/evidence/a8b4c60564326c4e0ea52f58f32d4ffe2105ce79ab2dfaa1309df92524415d60.json)
- [证据 parameter-account-n0-p06](../../../assets/deliveries/CANDIDATES/57/evidence/bf8ef610c86d3e90b0b096ae382c80546bf7a28e4038f6edd8af8478c7412f95.json)
- [证据 parameter-account-n0-p07](../../../assets/deliveries/CANDIDATES/57/evidence/2ad53d15d8df40d017bd970303d588fa637d362711852dab7afaa409af96a75f.json)
- [证据 parameter-account-n0-p08](../../../assets/deliveries/CANDIDATES/57/evidence/2b82f0c08ca2583c055f094faca1125cd5c65085403a5383245ea4f6aee2f094.json)
- [证据 parameter-account-n0-p09](../../../assets/deliveries/CANDIDATES/57/evidence/39290686de53f3ca99b6365e46c883553fa4f342d2cd9f379487dcc6900db8e2.json)
- [证据 parameter-account-n0-p10](../../../assets/deliveries/CANDIDATES/57/evidence/efb03e27d1ee59342366fa409f3e6fd55e721012e86e04ef61e4250e1368dfda.json)
- [证据 parameter-account-n0-p11](../../../assets/deliveries/CANDIDATES/57/evidence/be1fb154ec7b5bb0b3416ca4138a1eb4ed5e8481750f92aebcfd682255cc9f62.json)
- [证据 parameter-account-n0-p12](../../../assets/deliveries/CANDIDATES/57/evidence/3062e9603bcbeb307267149f63229ee4a788be3ea8aac2ac063503ed8b283f84.json)
- [证据 parameter-account-n0-p13](../../../assets/deliveries/CANDIDATES/57/evidence/64ef845c9baf70437fc2e1656fcc007ffbfe0f4603ed402ec32deec085205d7b.json)
- [证据 parameter-account-n0-p14](../../../assets/deliveries/CANDIDATES/57/evidence/c0b6a28a6594e881828b5fad44f5db3a78fb4f8e71ff71384173c7f9400f2dba.json)
- [证据 parameter-account-n0-p15](../../../assets/deliveries/CANDIDATES/57/evidence/43ee96d2936b18589f74b8751c2a4e10123971bc1ff0e48810d3c55b5fac546a.json)
- [证据 parameter-account-n0-p16](../../../assets/deliveries/CANDIDATES/57/evidence/cdd99fec32c78ccfce2e4f7a793cba9a93412e07ee4f99e1ad3985588632c990.json)
- [证据 parameter-account-n0-p17](../../../assets/deliveries/CANDIDATES/57/evidence/123d6ecc862096ad5e4bc2252f43de4cab4d2b7d6a475fd337ad2b7a658ccf32.json)
- [证据 parameter-account-n0-p18](../../../assets/deliveries/CANDIDATES/57/evidence/6d18284ef4d4cd335ceea9a9e2a22ccaaff90076c0a12fa1fa23e29f70511f59.json)
- [证据 parameter-account-n0-p19](../../../assets/deliveries/CANDIDATES/57/evidence/cad8e3ccab9bb725a004a7cfa756da93a07ec9edde5d2de02647d3aa8f1aa72b.json)
- [证据 parameter-account-n0-p20](../../../assets/deliveries/CANDIDATES/57/evidence/1fbb6a504e455186bd3a61b4b8faca88cc85dbf067ff04fc1cb2d1b2476d53fc.json)
- [证据 parameter-account-n0-p21](../../../assets/deliveries/CANDIDATES/57/evidence/0d271839516ab48ef9894be00ec8b8f827a6c39f8f9a258d3faa81899e0f05da.json)
- [证据 parameter-account-n0-p22](../../../assets/deliveries/CANDIDATES/57/evidence/ae13a43e9b6819c08f915de2fab0be1e4072b6f18e62e2914024f3dc831085fa.json)
- [证据 parameter-account-n0-p23](../../../assets/deliveries/CANDIDATES/57/evidence/2c0ce53b5b4338092777bf559b531d9c0fa104d53b656fd02705ce24099dca32.json)
- [证据 parameter-account-n0-p24](../../../assets/deliveries/CANDIDATES/57/evidence/a42a00697137b5af8c964e0fc50ab9a0549d1108879cc1c534ba777dabba68ad.json)
- [证据 parameter-account-n0-p25](../../../assets/deliveries/CANDIDATES/57/evidence/9305249660bf533e8d294df4b321a5196112f0445d6c386aab8c211f441c61d9.json)
- [证据 parameter-account-n0-p26](../../../assets/deliveries/CANDIDATES/57/evidence/b30ba1277764a4eb6752586c4ab1fa3fbcd2fccf05eab8c7c3c71b2cbe1c5a40.json)
- [证据 parameter-account-n0-p27](../../../assets/deliveries/CANDIDATES/57/evidence/9135515629cd9f9319a6111d4cde7565b41333809e9aba3c7ac6e13c6bffa8e5.json)
- [证据 parameter-account-n0-p28](../../../assets/deliveries/CANDIDATES/57/evidence/d6d48c97169d13bc605286d34804a2231b16e3dafd1af5f386cc18eecfaa6d45.json)
- [证据 parameter-account-n0-p29](../../../assets/deliveries/CANDIDATES/57/evidence/794facb34e0d733555d5f22422dc3a2f1520dff62b32bf734ff636a98b935dea.json)
- [证据 parameter-account-n0-p30](../../../assets/deliveries/CANDIDATES/57/evidence/93078f615c7e200ed64e5d141f96b88a8a1cf2ce13501f9a866123ea6abfbfff.json)
- [证据 parameter-account-n0-p31](../../../assets/deliveries/CANDIDATES/57/evidence/69539de24489f1bbcc4cf14f1a99e83ae6d309922248dff46937edaf22aa2cf1.json)
- [证据 parameter-plan-n0](../../../assets/deliveries/CANDIDATES/57/evidence/e3a1dfafc3e93ff1e138964e7aa3f3f064f6dfcc6fb203fc8b05089b6decec92.json)
- [证据 fee-stress-00](../../../assets/deliveries/CANDIDATES/57/evidence/45fdea3ec02a782181c33501a4eb12603b693fbc433d0ff71be69450e0bccb96.json)
- [证据 completed-full56-reference](../../../assets/deliveries/CANDIDATES/57/evidence/97a9e3d8329a8664db1841c5da431b820438d3edf1c7ac2de011ecd78a441c8e.json)
- [证据 completed-components4-reference](../../../assets/deliveries/CANDIDATES/57/evidence/6f27a04f7fe8b0b46f227d7aae7e1fc3188144948eeb5980fccd7c70717663a2.json)
- [证据 gap-exit-closeout-c2ffdbcc272cf5233e2cb05b61aef77f](../../../assets/deliveries/CANDIDATES/57/evidence/c2ffdbcc272cf5233e2cb05b61aef77f26d1eb1d4e13cddfb6b1e5cfab9db870.json)
- [证据 gap-exit-closeout-335f818255773af8563b508b8c14d93a](../../../assets/deliveries/CANDIDATES/57/evidence/335f818255773af8563b508b8c14d93a4ece693a6cc4a29c48c9c4484c3f736b.json)
- [证据 fixed-management-comparison-method](../../../assets/deliveries/CANDIDATES/57/evidence/e093462ebbb2c1cde58dea505fc7597f313fb4aedd8f70f489514c90510a4cd9.json)
- [证据 gap-exit-closeout-eb28987222fe11af722adcd37b78b091](../../../assets/deliveries/CANDIDATES/57/evidence/eb28987222fe11af722adcd37b78b09107660c8c84d1a885b35f29834b25817f.json)
- [证据 gap-exit-closeout-652f7fd9eddccdaa404ca755ecdbd15a](../../../assets/deliveries/CANDIDATES/57/evidence/652f7fd9eddccdaa404ca755ecdbd15aed8d546abf44a4f34f3984ffcfec2de8.json)
- [证据 fresh33-metadata-snapshot](../../../assets/deliveries/CANDIDATES/57/evidence/7f106bfd661aaf1dfc22e49af758ed02320c20ba036dd1b7c2f0bb076cc3fca4.json)
- [证据 rejected-first-id-reservation](../../../assets/deliveries/CANDIDATES/57/evidence/17511f272bea648415378998c4444501d52e7201b037009443d13e5af5939f0c.json)
- [证据 rejected-second-id-reservation](../../../assets/deliveries/CANDIDATES/57/evidence/05c088f86ad14756e23b1db86fd22f5ebb8581bf8e3881c3a9aeb59af1159927.json)
- [证据 frozen-material-4c232cadd3e898a4acc2a1a4](../../../assets/deliveries/CANDIDATES/57/evidence/4c232cadd3e898a4acc2a1a4b754d965c1dcaaf80231d4848c621cce2324523a.py)
- [证据 frozen-material-ade8fa6b4fe0b75d06c1458e](../../../assets/deliveries/CANDIDATES/57/evidence/ade8fa6b4fe0b75d06c1458e2f39a7c81e678733e3dd8679e12384073b5616e1.json)
- [证据 frozen-material-3e12a1e757194441a91608c1](../../../assets/deliveries/CANDIDATES/57/evidence/3e12a1e757194441a91608c16aa468059e7aeba314a2d315534cda24babbf51f.py)
- [证据 frozen-material-2c10e6b8de5c231eeaa8578c](../../../assets/deliveries/CANDIDATES/57/evidence/2c10e6b8de5c231eeaa8578c89c88d1b90412539dc0f6433a6dcdcdfd5435612.json)
- [证据 frozen-material-ad6e9a25ca7cd83f2e13420d](../../../assets/deliveries/CANDIDATES/57/evidence/ad6e9a25ca7cd83f2e13420dcb9ca7dc9f6416b959f69ada2e6f9d78facd8087.json)
- [证据 frozen-material-4464c626c06666fd58486436](../../../assets/deliveries/CANDIDATES/57/evidence/4464c626c06666fd584864364dc44eba9cb78f8891e5c596d4d89f765ab58b4f.py)
- [证据 frozen-material-3e91dfd22a15d28f76e9afa8](../../../assets/deliveries/CANDIDATES/57/evidence/3e91dfd22a15d28f76e9afa8f32a1d31e8a09620300a86797173051600337078.py)
- [证据 frozen-material-a955a23f50338dbf8b37f307](../../../assets/deliveries/CANDIDATES/57/evidence/a955a23f50338dbf8b37f307fc3b0cebde16c678b1fd21d17794c366b8400e0d.py)
- [证据 frozen-material-83cdba46de6ca6a38691ce31](../../../assets/deliveries/CANDIDATES/57/evidence/83cdba46de6ca6a38691ce316f85db90bf1586386df0015ed0ed9ae6eb0ecadb.py)
- [证据 gap-exit-closeout-0ff0eeb919ca317a9ec00553847a7425](../../../assets/deliveries/CANDIDATES/57/evidence/0ff0eeb919ca317a9ec00553847a74259c89e5c8d801a6c93416f0d4ed18b49a.py)
- [证据 gap-exit-closeout-eb4cea62e3300ab1da75a0cb8ab705b8](../../../assets/deliveries/CANDIDATES/57/evidence/eb4cea62e3300ab1da75a0cb8ab705b8d50a67eeb088255a69f66a7463c1ff36.py)
- [证据 gap-exit-closeout-784ee70ab3b6372f8bc3d1aadf00b38b](../../../assets/deliveries/CANDIDATES/57/evidence/784ee70ab3b6372f8bc3d1aadf00b38bcbed6d42eea3673fba32e7a7cefd3511.json)
- [证据 gap-exit-closeout-fd950359bf71e779e937212ee03bd458](../../../assets/deliveries/CANDIDATES/57/evidence/fd950359bf71e779e937212ee03bd458180f32ee4975b5418b224a578086a3f0.json)
- [证据 gap-exit-closeout-a2a086c51ebe0db67f8cab1355e61746](../../../assets/deliveries/CANDIDATES/57/evidence/a2a086c51ebe0db67f8cab1355e617465984c4b2d0e3e6fc79bdd5ba1fce8922.json)
- [证据 gap-exit-closeout-ebad0def26ec4d62e6466de87c6e99b0](../../../assets/deliveries/CANDIDATES/57/evidence/ebad0def26ec4d62e6466de87c6e99b01cf9a0e815ef15abae819cdabc50ee4d.py)
- [证据 gap-exit-closeout-62c8a7d2433496fb562e5d7daa45e926](../../../assets/deliveries/CANDIDATES/57/evidence/62c8a7d2433496fb562e5d7daa45e926ddc23e48d553b4c6b4fbd7e7570c7415.py)
- [证据 gap-exit-closeout-d4b75aa68eb67eb2c99320d6fa9fb0a6](../../../assets/deliveries/CANDIDATES/57/evidence/d4b75aa68eb67eb2c99320d6fa9fb0a68b76b4bb500c38a4dab8463fe782b795.py)
- [证据 gap-exit-closeout-ddf6e5443433519eade6d3beecc94ee9](../../../assets/deliveries/CANDIDATES/57/evidence/ddf6e5443433519eade6d3beecc94ee9f9a778baba2c73e540da7cf3e5516074.py)
- [证据 gap-exit-closeout-7bfd9a95b6803075d43529c3db8ce550](../../../assets/deliveries/CANDIDATES/57/evidence/7bfd9a95b6803075d43529c3db8ce55065095ca2a6ce12c5d898f8644c0ab65e.json)
- [证据 gap-exit-closeout-4f2a781378f173bbfdf43029a57d62a6](../../../assets/deliveries/CANDIDATES/57/evidence/4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1.py)
- [证据 gap-exit-closeout-be475734c9624be3d4270e5ad9c5119f](../../../assets/deliveries/CANDIDATES/57/evidence/be475734c9624be3d4270e5ad9c5119f18aea129551bff9054ea607d04a8e5d2.py)
- [证据 gap-exit-closeout-f3a8a9e8a69cb61b326c1702bf8b471f](../../../assets/deliveries/CANDIDATES/57/evidence/f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4.py)
- [证据 gap-exit-closeout-3fc44c4bfe601b26a43cee533303d41e](../../../assets/deliveries/CANDIDATES/57/evidence/3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8.py)
- [证据 gap-exit-closeout-b1e6b77bd0983791550106c7e468f396](../../../assets/deliveries/CANDIDATES/57/evidence/b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a.py)
- [证据 gap-exit-closeout-74844784a16073e2301925011939c56b](../../../assets/deliveries/CANDIDATES/57/evidence/74844784a16073e2301925011939c56bb35ba7bc727442a3a256324bfd1fc37e.py)
- [证据 gap-exit-closeout-899522b56a578190c1f254e21c2babc1](../../../assets/deliveries/CANDIDATES/57/evidence/899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3.py)
- [证据 gap-exit-closeout-6dfa9c7d37d8eef604a0dfccb82ebc37](../../../assets/deliveries/CANDIDATES/57/evidence/6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c.py)
- [证据 frozen-material-def4fa64088fd69e412f6b0c](../../../assets/deliveries/CANDIDATES/57/evidence/def4fa64088fd69e412f6b0c05174405840ed2f888e4f2d53cd116ce10cea364.py)
- [证据 frozen-material-ad63c7cf7ec1a6e9bc940db8](../../../assets/deliveries/CANDIDATES/57/evidence/ad63c7cf7ec1a6e9bc940db86b4c602900aad94f782210d16dfcf5e2cc1fcee1.py)
- [证据 gap-exit-closeout-c6d7f0bd8fa008b394042a9bb91dc7bf](../../../assets/deliveries/CANDIDATES/57/evidence/c6d7f0bd8fa008b394042a9bb91dc7bfc605714819b85b948808df0e886d857c.py)
- [证据 frozen-material-3c5d53047696a9a6d6b8d31d](../../../assets/deliveries/CANDIDATES/57/evidence/3c5d53047696a9a6d6b8d31d8da9acbedd214db24c88cfccb2e9002359cfc2bd.json)
- [证据 frozen-material-e1b490e4665dcb674170cd37](../../../assets/deliveries/CANDIDATES/57/evidence/e1b490e4665dcb674170cd373337784479dc80c0a79b09baa1c66e45e26155c3.py)
- [证据 frozen-material-151503fc556d92de19c83485](../../../assets/deliveries/CANDIDATES/57/evidence/151503fc556d92de19c83485cfb06efc7c9c2552075b86d76f4857a03eb82d1f.json)
- [证据 frozen-material-c78780d8352c898a8b93b997](../../../assets/deliveries/CANDIDATES/57/evidence/c78780d8352c898a8b93b9972e02a6b1c08f72a285fdd252350dca8e5b5cdbb2.json)
- [证据 frozen-material-cba1461c52270e0c86df45cf](../../../assets/deliveries/CANDIDATES/57/evidence/cba1461c52270e0c86df45cf18da88dd61b77f89329f322cb9caf484fdb5ee1e.json)
- [证据 frozen-material-38db7f7f3fe5450a7022b348](../../../assets/deliveries/CANDIDATES/57/evidence/38db7f7f3fe5450a7022b348b5414cc185140acd8a95c42027223a2d32a4586b.py)
- [证据 gap-exit-closeout-a4ab30e97202d2ce5ba26128dc877e7d](../../../assets/deliveries/CANDIDATES/57/evidence/a4ab30e97202d2ce5ba26128dc877e7d156fe5b2f02d64792b9b9c84de6694f5.py)
- [证据 frozen-material-6067f896cfdc6d493f2aafcd](../../../assets/deliveries/CANDIDATES/57/evidence/6067f896cfdc6d493f2aafcd0e07bfabe2507f79380ef19d0d4ed4aa678647cb.json)
- [证据 gap-exit-closeout-4c665de0464dcf8949272ce331d618a5](../../../assets/deliveries/CANDIDATES/57/evidence/4c665de0464dcf8949272ce331d618a5d39509592c587023557253e600a34af0.py)
- [证据 frozen-material-ac9a5951db0e578770a4a9a0](../../../assets/deliveries/CANDIDATES/57/evidence/ac9a5951db0e578770a4a9a0fe4e3dc9b974094616eb421adfd8ea2e4628c228.py)
- [证据 gap-exit-closeout-4ad1bee7a64228885a98df8dbf8c114c](../../../assets/deliveries/CANDIDATES/57/evidence/4ad1bee7a64228885a98df8dbf8c114ceb2f01a3bce8d4f0190915dd7f8ed995.py)
- [证据 gap-exit-closeout-348fa312a49e9f2ab3775be59a58399d](../../../assets/deliveries/CANDIDATES/57/evidence/348fa312a49e9f2ab3775be59a58399d2947952fd7947d937d285281bc17d720.py)
- [证据 frozen-material-b100cbed9ec1fcb60c08c26d](../../../assets/deliveries/CANDIDATES/57/evidence/b100cbed9ec1fcb60c08c26d74975890b722493f219212f26fc709ea5e9fdba6.py)
- [证据 frozen-material-05c692bd33951a9ba77f66df](../../../assets/deliveries/CANDIDATES/57/evidence/05c692bd33951a9ba77f66dfbdbf0bd388f4f98a4f52e59f22f5d3e5af7eadca.txt)
- [证据 gap-exit-closeout-36d40d403ef884620d9ef769d6641c9b](../../../assets/deliveries/CANDIDATES/57/evidence/36d40d403ef884620d9ef769d6641c9bacf876585253c1de30963ae17ace7043.py)
- [证据 gap-exit-closeout-93a667987cfb3681a0d044985b4ed401](../../../assets/deliveries/CANDIDATES/57/evidence/93a667987cfb3681a0d044985b4ed401abda2ee80840acb8c80ec01af299e12d.json)
- [证据 gap-exit-closeout-fcc5e502719317624bee0741f8587cd2](../../../assets/deliveries/CANDIDATES/57/evidence/fcc5e502719317624bee0741f8587cd2fc5d00070be392742abe38978336b745.py)
- [证据 gap-exit-closeout-611936400540b8cc3c307bbf52df4f87](../../../assets/deliveries/CANDIDATES/57/evidence/611936400540b8cc3c307bbf52df4f87598d32b277b0646e0c40d4a39bda35c9.json)
- [证据 gap-exit-closeout-0fb764b9505e9f9045248313cfb9f1d0](../../../assets/deliveries/CANDIDATES/57/evidence/0fb764b9505e9f9045248313cfb9f1d09cf1b8151f124523170bf3c3e1da9ee9.json)
- [证据 gap-exit-closeout-3a22f3f8238ca881ab5df52142cc7e92](../../../assets/deliveries/CANDIDATES/57/evidence/3a22f3f8238ca881ab5df52142cc7e923ed264a2b2e57fa2bd3954549f3ee9a8.json)
- [证据 gap-exit-closeout-61955d733c35edcb8c052a9646c2894a](../../../assets/deliveries/CANDIDATES/57/evidence/61955d733c35edcb8c052a9646c2894af6c8ee96bb2881c20b1030d385fc55b4.py)
- [证据 gap-exit-closeout-e53700278e9c8647866fc927486703b5](../../../assets/deliveries/CANDIDATES/57/evidence/e53700278e9c8647866fc927486703b59d68aa60537c06679f2e42781af83186.py)
- [证据 gap-exit-closeout-a2922f0f0bb2613119bff56b62e39a05](../../../assets/deliveries/CANDIDATES/57/evidence/a2922f0f0bb2613119bff56b62e39a0549befb767b9bdbba7c4909d14941bddd.py)
- [证据 gap-exit-closeout-caf12faeededd7f511528545b03fbe40](../../../assets/deliveries/CANDIDATES/57/evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [证据 gap-exit-closeout-857a6f746c1991d6ff649467d41bc76b](../../../assets/deliveries/CANDIDATES/57/evidence/857a6f746c1991d6ff649467d41bc76bbec0ddf6c481fb450173dccf32c6e6d6.py)
- [证据 gap-exit-closeout-eb26a16d5c7d6f2b655ca12537d73de2](../../../assets/deliveries/CANDIDATES/57/evidence/eb26a16d5c7d6f2b655ca12537d73de28888fe05d016bce8a0b71b34c96eb73a.py)
- [证据 gap-exit-closeout-14a41bc2069d9896aeddb7e2136b4c28](../../../assets/deliveries/CANDIDATES/57/evidence/14a41bc2069d9896aeddb7e2136b4c287a875bb4ece4e4e71ed96a3531508511.py)
- [证据 gap-exit-closeout-e18857d1549e55526d60b0ecad03e9dd](../../../assets/deliveries/CANDIDATES/57/evidence/e18857d1549e55526d60b0ecad03e9dded5ef9b97e80e3fdd95373aacd34b29c.json)
- [证据 gap-exit-closeout-5c9e627faba98a5fb309d3fc926efba8](../../../assets/deliveries/CANDIDATES/57/evidence/5c9e627faba98a5fb309d3fc926efba8bd6beb4b570676a607d1b67cb7d436fe.json)
- [证据 gap-exit-closeout-d2628c7ace32b9bd100a7311f1ee994d](../../../assets/deliveries/CANDIDATES/57/evidence/d2628c7ace32b9bd100a7311f1ee994d8e28bf3a784233e50714388b490febd2.json)
- [证据 gap-exit-closeout-01a38697c1cc830e3ada5e502431ac9f](../../../assets/deliveries/CANDIDATES/57/evidence/01a38697c1cc830e3ada5e502431ac9fc66e0e7ed0f2e8bf616311c7d9d602de.py)
- [证据 gap-exit-closeout-84a9c5af58c8f66798da89213c3054b6](../../../assets/deliveries/CANDIDATES/57/evidence/84a9c5af58c8f66798da89213c3054b6730afa5661ce2150105772bd2bbf1dfe.json)
- [证据 gap-exit-closeout-5c14a6abe757537e3214016b6f326e3c](../../../assets/deliveries/CANDIDATES/57/evidence/5c14a6abe757537e3214016b6f326e3c832d3a6765dec82a89145e41329b3e05.json)
- [证据 gap-exit-closeout-49c091e0c0eee81cdf2bccf7c50bd6a4](../../../assets/deliveries/CANDIDATES/57/evidence/49c091e0c0eee81cdf2bccf7c50bd6a4b6fc73b9a183b763abed6ee883e98305.json)
- [证据 gap-exit-closeout-ba5162b6e2cbf99b77b42933fd6e1398](../../../assets/deliveries/CANDIDATES/57/evidence/ba5162b6e2cbf99b77b42933fd6e1398bbb66cbcfd1b0184654f378fcc6e70ca.py)
- [证据 gap-exit-closeout-7f07d54b12a180533fc6155d6c6a412a](../../../assets/deliveries/CANDIDATES/57/evidence/7f07d54b12a180533fc6155d6c6a412ae401586a0ce09ffb1a974c3a0c7e7ed9.py)
- [证据 gap-exit-closeout-d2a41e78e7df70c9cb75fb8883d71446](../../../assets/deliveries/CANDIDATES/57/evidence/d2a41e78e7df70c9cb75fb8883d71446bc26a4850361ba97e873efefd9d6c680.py)
- [证据 gap-exit-closeout-74af45fc5f6c1e5915b6fff7a968bf2b](../../../assets/deliveries/CANDIDATES/57/evidence/74af45fc5f6c1e5915b6fff7a968bf2b4577d8f5c3d3a53b47649cafa9b72ed6.json)
- [证据 gap-exit-closeout-62c861387aed05b9d34713c1e870e1e1](../../../assets/deliveries/CANDIDATES/57/evidence/62c861387aed05b9d34713c1e870e1e1f12cc8a459ed883462b5d57bd4595817.json)
- [证据 gap-exit-closeout-15655db74c7606143ff3041d71be7f27](../../../assets/deliveries/CANDIDATES/57/evidence/15655db74c7606143ff3041d71be7f27500a855f268f2cb3033a2b19340b9519.json)
- [证据 gap-exit-closeout-0e3bbf9058be24e80f1123b20e517c02](../../../assets/deliveries/CANDIDATES/57/evidence/0e3bbf9058be24e80f1123b20e517c0277840968eb950bcb32974e4ebf056c0a.py)
- [证据 gap-exit-closeout-f5eeddf499de58f46058f288c994c2e4](../../../assets/deliveries/CANDIDATES/57/evidence/f5eeddf499de58f46058f288c994c2e410f8e0ee4989240ade26972079083c6f.json)
- [证据 gap-exit-closeout-257b545bca6e2f19d5ebe23e3c02884a](../../../assets/deliveries/CANDIDATES/57/evidence/257b545bca6e2f19d5ebe23e3c02884a5ab9d087b4affed45595ccc1541d0a65.json)
- [证据 gap-exit-closeout-96c3bac2ba16fd6cdacb2e17211f2d6a](../../../assets/deliveries/CANDIDATES/57/evidence/96c3bac2ba16fd6cdacb2e17211f2d6ab68695154332f16da767d9e7a4e1986a.json)
- [证据 gap-exit-closeout-4c56eccb4a844d5dba7ff5103cce98eb](../../../assets/deliveries/CANDIDATES/57/evidence/4c56eccb4a844d5dba7ff5103cce98eb97483f9e94d3647d3b5251f8e7da3b45.py)
- [证据 gap-exit-closeout-03a5d3316a212bafbe2c0f892b3dd467](../../../assets/deliveries/CANDIDATES/57/evidence/03a5d3316a212bafbe2c0f892b3dd467cc786bd1adbe0b084ef471211cb32cba.py)
- [证据 gap-exit-closeout-8495b86b1dc2bcd8e48de5488b25a163](../../../assets/deliveries/CANDIDATES/57/evidence/8495b86b1dc2bcd8e48de5488b25a1637b4d5f31ccbb62231e79eb0317646c66.json)
- [证据 gap-exit-closeout-ab0fd50b91274a22f36e44c5761a721c](../../../assets/deliveries/CANDIDATES/57/evidence/ab0fd50b91274a22f36e44c5761a721c758de02bde64655df90190cd489e7710.py)
- [证据 gap-exit-closeout-05a7ed9ab7ccd299b84dcd489b8c9d64](../../../assets/deliveries/CANDIDATES/57/evidence/05a7ed9ab7ccd299b84dcd489b8c9d64b3a68e9f7ffd61fb41c70a8965f7e264.json)
- [证据 gap-exit-closeout-2768579e16ff3b2968032783fd98008a](../../../assets/deliveries/CANDIDATES/57/evidence/2768579e16ff3b2968032783fd98008adf173e35759c9fac60f8a4bc4a9b8aa6.json)
- [证据 gap-exit-closeout-2faf69e461f3b42cc82e58b436ac1352](../../../assets/deliveries/CANDIDATES/57/evidence/2faf69e461f3b42cc82e58b436ac13527d0af7a2ca9b79977def85b391e1dff3.json)
- [证据 gap-exit-closeout-560689afbd21a388bbe8337730125a4b](../../../assets/deliveries/CANDIDATES/57/evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [证据 gap-exit-closeout-f38c71d3392fb791fdd064f366cc251e](../../../assets/deliveries/CANDIDATES/57/evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [证据 gap-exit-closeout-e891e44c69236eee5fefa6bd7222e191](../../../assets/deliveries/CANDIDATES/57/evidence/e891e44c69236eee5fefa6bd7222e191b25333e4ece680f27abc13c2618bdf36.py)
- [证据 gap-exit-closeout-b080a382ce7e16406161485f09a147a5](../../../assets/deliveries/CANDIDATES/57/evidence/b080a382ce7e16406161485f09a147a5c765d7637c0d294a68e543f7159f7f9f.py)
- [证据 gap-exit-closeout-8a9d86a30d1c5f98a4a621ef1dc4c263](../../../assets/deliveries/CANDIDATES/57/evidence/8a9d86a30d1c5f98a4a621ef1dc4c26387ec7db0e1f365e8fc28952b364e82e8.py)
- [证据 input-overall-conflict-summary](../../../assets/deliveries/CANDIDATES/57/evidence/be75f9f9b7572ca4b8b1b1119de81a59d1d63e2571722475ba9d536d9ef2d59b.json)
- [证据 input-complete-identity-variants](../../../assets/deliveries/CANDIDATES/57/evidence/e0044b950c6dc499610b6bf3fa1d8943efb3434b77b393f69b5e499c79eb2cd6.json)
- [证据 input-verified-feature-state50](../../../assets/deliveries/CANDIDATES/57/evidence/580683742ee6ad10880ba32aac85f0e16d8b2c6e2dea4f10fbea3fc32b764f40.json)
- [证据 input-feature-scope-review](../../../assets/deliveries/CANDIDATES/57/evidence/4a72709312a8887c23bdd56f7c83ddf8612c7933f2b108c136e393a81c5ec54f.json)
- [证据 N_GAP_EXIT](../../../assets/deliveries/CANDIDATES/57/evidence/2f17a53fad43cac517447575216921df93af0f66ab64f8b41c0de1e84a37da74.json)
- [证据 gap-exit-closeout-0be60ec8dfd9364518f104a5c285146c](../../../assets/deliveries/CANDIDATES/57/evidence/0be60ec8dfd9364518f104a5c285146ce9e5a4b01291cb2743b4bb80c49f3c73.json)
- [证据 gap-exit-closeout-4fe329d7974fcc46901aacdafae34493](../../../assets/deliveries/CANDIDATES/57/evidence/4fe329d7974fcc46901aacdafae34493a5e5debc0f58b8e4ecfd76c68c74cc9a.json)
- [证据 gap-exit-closeout-2f61328e52d2a8bf9f1901267176ffd7](../../../assets/deliveries/CANDIDATES/57/evidence/2f61328e52d2a8bf9f1901267176ffd74d5cf16f8fcf29c6cdfddae501e6d6ed.json)
- [证据 gap-exit-closeout-2796082090a86361db7210fba99c37ac](../../../assets/deliveries/CANDIDATES/57/evidence/2796082090a86361db7210fba99c37ac132da9d73c4aa053507be420539e3cb3.json)
- [证据 gap-exit-closeout-cfeec61c377493781489967bac85ec96](../../../assets/deliveries/CANDIDATES/57/evidence/cfeec61c377493781489967bac85ec96df679252889f2bd99a52a1e776ae22b3.json)
- [证据 gap-exit-closeout-4d9a6b214999bb5a075b46e534e7738b](../../../assets/deliveries/CANDIDATES/57/evidence/4d9a6b214999bb5a075b46e534e7738b79ce8539cb5792150796e21522c4c64d.json)
- [证据 gap-exit-closeout-1a0ab4f7279e86da521cd9fa02feb131](../../../assets/deliveries/CANDIDATES/57/evidence/1a0ab4f7279e86da521cd9fa02feb1315a583d93db2e916745d25add6d21b3ea.json)
- [证据 gap-exit-closeout-8fd0ceed721e04014911c0d280c716a5](../../../assets/deliveries/CANDIDATES/57/evidence/8fd0ceed721e04014911c0d280c716a5692de2bd1b5ed6840651022d0354144f.json)
- [证据 gap-exit-closeout-4c4ccf45849bace9047685f8395d8e27](../../../assets/deliveries/CANDIDATES/57/evidence/4c4ccf45849bace9047685f8395d8e27e5f92937cdce202ce65a60f67c6df6f6.json)
- [证据 gap-exit-closeout-057b170fa39b3d060c73ae7be5192f07](../../../assets/deliveries/CANDIDATES/57/evidence/057b170fa39b3d060c73ae7be5192f071aba21d6f2cf2a1eb4fc5ffe4fb48d35.json)
- [证据 gap-exit-closeout-6f27a04f7fe8b0b46f227d7aae7e1fc3](../../../assets/deliveries/CANDIDATES/57/evidence/6f27a04f7fe8b0b46f227d7aae7e1fc3188144948eeb5980fccd7c70717663a2.json)
- [证据 gap-exit-closeout-97a9e3d8329a8664db1841c5da431b82](../../../assets/deliveries/CANDIDATES/57/evidence/97a9e3d8329a8664db1841c5da431b820438d3edf1c7ac2de011ecd78a441c8e.json)
- [证据 gap-exit-closeout-987bea64f2c1fa7e6d021eb551095cc9](../../../assets/deliveries/CANDIDATES/57/evidence/987bea64f2c1fa7e6d021eb551095cc9147d8e8358a70fe575b877a156429532.json)
- [证据 gap-exit-closeout-7779f40a49216b75db99e958e3a6b063](../../../assets/deliveries/CANDIDATES/57/evidence/7779f40a49216b75db99e958e3a6b063e862c7ca7890913ae03ff18931bac94e.json)
- [证据 gap-exit-closeout-5035164a8f1dc1d39b8701ff63ec2230](../../../assets/deliveries/CANDIDATES/57/evidence/5035164a8f1dc1d39b8701ff63ec223024fbd4e31e057226252ce6d2e8801be1.py)
- [证据 gap-exit-closeout-4a87d1b1867f713f142e33b5e53412f2](../../../assets/deliveries/CANDIDATES/57/evidence/4a87d1b1867f713f142e33b5e53412f293fe91ddc2cb76ff927bbebca88571c4.json)
- [证据 gap-exit-closeout-2bd20332f0dab00897afa80ef2ab1d60](../../../assets/deliveries/CANDIDATES/57/evidence/2bd20332f0dab00897afa80ef2ab1d60613d02d834296459b554fdef3aa636f0.json)
- [证据 gap-exit-closeout-4e5fe59ba13b9c97b3af66d96aecc5c0](../../../assets/deliveries/CANDIDATES/57/evidence/4e5fe59ba13b9c97b3af66d96aecc5c04bba51bd4cdc5d45fddbab9e2e079ffa.json)
- [证据 gap-exit-closeout-db9d787a3f1a9ff004bbe3417a8179bd](../../../assets/deliveries/CANDIDATES/57/evidence/db9d787a3f1a9ff004bbe3417a8179bd5e9ac78d484a70004414b95ed9580376.json)
- [证据 gap-exit-closeout-ca7c66182886fc0eff142f89c297aa4f](../../../assets/deliveries/CANDIDATES/57/evidence/ca7c66182886fc0eff142f89c297aa4f14f433a14fdb1af98d799a32865e9263.py)
- [证据 gap-exit-closeout-c6d75a728613bac711ca8eb648b14d57](../../../assets/deliveries/CANDIDATES/57/evidence/c6d75a728613bac711ca8eb648b14d57f54f23acee68d99e3afe980b855c7887.py)
- [证据 gap-exit-closeout-ea9e3d79626aed8954db12f73c8b18e4](../../../assets/deliveries/CANDIDATES/57/evidence/ea9e3d79626aed8954db12f73c8b18e437e59515bf8273fd95e192283d51d46b.py)
- [证据 gap-exit-closeout-0899aa3d041849ae45b14ae1cf9d1814](../../../assets/deliveries/CANDIDATES/57/evidence/0899aa3d041849ae45b14ae1cf9d1814bf74d451799096084c7034ccb80c487d.py)
- [证据 gap-exit-closeout-bd1363041641cfe2225683f3dd5b7e31](../../../assets/deliveries/CANDIDATES/57/evidence/bd1363041641cfe2225683f3dd5b7e318c958428a55aca0f389f74a65391e275.py)
- [证据 gap-exit-closeout-cb17427ca8fdd71a914ffdf9e06f284d](../../../assets/deliveries/CANDIDATES/57/evidence/cb17427ca8fdd71a914ffdf9e06f284db0446f691737306bab726e91e3f48475.json)
- [证据 gap-exit-closeout-8abc2a9f0d11d9160acf4c540e5b93f8](../../../assets/deliveries/CANDIDATES/57/evidence/8abc2a9f0d11d9160acf4c540e5b93f8cd308de4985546aca13de5955a0a43e7.py)
- [证据 gap-exit-closeout-9a95b069e81388594db6a99777502d55](../../../assets/deliveries/CANDIDATES/57/evidence/9a95b069e81388594db6a99777502d55e8cf1bd693b7b52afae5350ca3d08d5a.py)
- [证据 gap-exit-closeout-8748b9fac17c26deb85c44505d4b6cb6](../../../assets/deliveries/CANDIDATES/57/evidence/8748b9fac17c26deb85c44505d4b6cb62a31559127e6e1785a4e96f5f27c4090.py)
- [证据 gap-exit-closeout-715cc4d606479cd140be921305abec89](../../../assets/deliveries/CANDIDATES/57/evidence/715cc4d606479cd140be921305abec89ba5a00891fd7e256e9dff2f98a0e6510.json)
- [证据 gap-exit-closeout-f24ecbe2d712bbb13b2f4383fc94b4f3](../../../assets/deliveries/CANDIDATES/57/evidence/f24ecbe2d712bbb13b2f4383fc94b4f3b6d79443f4992b65c500b04145737de6.json)