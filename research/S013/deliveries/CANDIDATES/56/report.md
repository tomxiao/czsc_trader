# 持仓管理最小机制对照

B0保留原规则；N_LOCK关闭行情类别变化时的立即退出；N_CURRENT在持仓中改用当前行情类别的管理规则。入场身份、持有时钟、锚点及退出记忆均保持冻结定义。

|组别|净年化|全期最大回撤|每60日闭合交易|原四门|32逐项通过率|32联合通过率|Q10净年化|Q90回撤|
|---|---:|---:|---:|---|---|---:|---:|---:|
|B0|17.1346%|13.6187%|4.2543|收益=通过；年度回撤=通过；交易频率=通过；基准亏损年盈利=通过|收益=7/32 (21.88%)；年度回撤=32/32 (100.00%)；交易频率=27/32 (84.38%)；基准亏损年盈利=2/32 (6.25%)|0/32 (0.00%)|6.3981%|28.3508%|
|N_LOCK|10.8884%|15.5932%|3.6308|收益=通过；年度回撤=通过；交易频率=未过；基准亏损年盈利=未过|中心未过原四门，完整32不适用|未运行|未运行|未运行|
|N_CURRENT|11.7887%|16.4513%|3.7775|收益=通过；年度回撤=通过；交易频率=未过；基准亏损年盈利=未过|中心未过原四门，完整32不适用|未运行|未运行|未运行|

四门依次检查净年化收益、各自然年回撤、交易频率及基准亏损年份盈利；自然年连续净值计算沿用原冻结口径。Q10表示扰动后较差一端的收益，Q90表示较差一端的回撤，都是开发池事实。

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
|N_LOCK|2020|17.4178%|7.0235%|22.1693%|14.9712%|
|N_LOCK|2021|10.8649%|3.7249%|17.2351%|9.7035%|
|N_LOCK|2022|-1.0369%|12.2170%|-18.3203%|28.4105%|
|N_LOCK|2023|1.4262%|6.5194%|-6.2450%|17.2665%|
|N_LOCK|2024|54.5736%|10.0204%|6.9559%|18.5736%|
|N_LOCK|2025|10.8787%|3.5335%|32.7098%|13.7975%|
|N_LOCK|2026|-12.6489%|15.5932%|0.9947%|18.7646%|
|N_CURRENT|2020|16.9870%|9.0421%|22.1693%|14.9712%|
|N_CURRENT|2021|4.9184%|6.9680%|17.2351%|9.7035%|
|N_CURRENT|2022|6.1136%|6.6458%|-18.3203%|28.4105%|
|N_CURRENT|2023|-0.2576%|8.1917%|-6.2450%|17.2665%|
|N_CURRENT|2024|52.9927%|10.0201%|6.9559%|18.5736%|
|N_CURRENT|2025|17.0381%|3.5328%|32.7098%|13.7975%|
|N_CURRENT|2026|-11.3733%|13.9933%|0.9947%|18.7646%|

实际评价与复用计数：{"standard_roles": 35, "standard_unique_configurations": 35, "reused_baseline_accounts": 33, "new_standard_business_evaluations": 2, "new_unique_standard_configurations": 2, "new_technical_evaluations": 2, "new_fee_evaluations": 0, "reused_fee_accounts": 1, "new_actual_evaluations": 4, "all_actual_native_evaluations_including_reuse": 38}

本轮使用同一已见开发池，研究族反复选择未校正，也没有新的封存样本验证。此前已知行情High/Low异常保留原状。既有现金审核与独立状态核对不能保证未来收益、未来回撤或全部成交政策。结果只评价这两个固定管理变化，不证明所有新策略表达都不可能。

没有优化参数、增加经济门或自动宣布总体稳健目标达成；阶段四交接与后续研究由用户的既有授权和具体结论另行处理。

- [证据 management-native-bundle](../../../assets/deliveries/CANDIDATES/56/evidence/bd93d874d029c4257a20e1ef84538bbb31a5641b1fd2a0083b6ba12b5839f912.json)
- [证据 management-closeout-e093462ebbb2c1cde58dea505fc7597f](../../../assets/deliveries/CANDIDATES/56/evidence/e093462ebbb2c1cde58dea505fc7597f313fb4aedd8f70f489514c90510a4cd9.json)
- [证据 management-closeout-0802d21ca081e39184204b9df07a5751](../../../assets/deliveries/CANDIDATES/56/evidence/0802d21ca081e39184204b9df07a575124f75eac920de6be5790ee86c1548cbf.json)
- [证据 management-closeout-6aa8d3ed38422964e6f4c109609b4652](../../../assets/deliveries/CANDIDATES/56/evidence/6aa8d3ed38422964e6f4c109609b4652c1c198c6dd351aec8a179ca5d4ab3db0.json)
- [证据 parameter-coordinate-mapping](../../../assets/deliveries/CANDIDATES/56/evidence/8311555eb89603e4768ba117d5db7a0610bc7baf45c6ccaadabdde854da15760.json)
- [证据 parameter-coordinate-feasibility](../../../assets/deliveries/CANDIDATES/56/evidence/9b6fe0400dd8a10418d3eb3faa01626be653a4dee64719896bc0d3db0b29e69e.json)
- [证据 management-prepared-centers](../../../assets/deliveries/CANDIDATES/56/evidence/fae577c2260e46b1652af913ee1075d5ea1a091447be0aeb1145f67616b19cd2.json)
- [证据 management-all-point-plans](../../../assets/deliveries/CANDIDATES/56/evidence/820683f38d4c6cdf91f410b1be23f726c1c1288fdf0f8cb5f472bf22408bd009.json)
- [证据 raw-boundary-body-local-bear-recovery-native-center-n0](../../../assets/deliveries/CANDIDATES/56/evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [证据 parameter-account-n0-p00](../../../assets/deliveries/CANDIDATES/56/evidence/cee623b26dcd6acfa525015d44499247fe7a6c66ab712923fdaa8a3601ff29bd.json)
- [证据 parameter-account-n0-p01](../../../assets/deliveries/CANDIDATES/56/evidence/b327425b049a0fe753e83a7b01091be2d890b04b0cfd0488462be5029d7bd768.json)
- [证据 parameter-account-n0-p02](../../../assets/deliveries/CANDIDATES/56/evidence/e5cfddd0149ca8ce280597e2abfaf0cca85f7c4620c31dae183813686f1ed932.json)
- [证据 parameter-account-n0-p03](../../../assets/deliveries/CANDIDATES/56/evidence/849fd521cb9b0130308c4b06a5911ee8e41736d7ee510d2531c108e8d886b8da.json)
- [证据 parameter-account-n0-p04](../../../assets/deliveries/CANDIDATES/56/evidence/82e4bae906ffa94ddf8fcbdf405aa00ab1cce7165687e8840c470419227a4a4e.json)
- [证据 parameter-account-n0-p05](../../../assets/deliveries/CANDIDATES/56/evidence/a8b4c60564326c4e0ea52f58f32d4ffe2105ce79ab2dfaa1309df92524415d60.json)
- [证据 parameter-account-n0-p06](../../../assets/deliveries/CANDIDATES/56/evidence/bf8ef610c86d3e90b0b096ae382c80546bf7a28e4038f6edd8af8478c7412f95.json)
- [证据 parameter-account-n0-p07](../../../assets/deliveries/CANDIDATES/56/evidence/2ad53d15d8df40d017bd970303d588fa637d362711852dab7afaa409af96a75f.json)
- [证据 parameter-account-n0-p08](../../../assets/deliveries/CANDIDATES/56/evidence/2b82f0c08ca2583c055f094faca1125cd5c65085403a5383245ea4f6aee2f094.json)
- [证据 parameter-account-n0-p09](../../../assets/deliveries/CANDIDATES/56/evidence/39290686de53f3ca99b6365e46c883553fa4f342d2cd9f379487dcc6900db8e2.json)
- [证据 parameter-account-n0-p10](../../../assets/deliveries/CANDIDATES/56/evidence/efb03e27d1ee59342366fa409f3e6fd55e721012e86e04ef61e4250e1368dfda.json)
- [证据 parameter-account-n0-p11](../../../assets/deliveries/CANDIDATES/56/evidence/be1fb154ec7b5bb0b3416ca4138a1eb4ed5e8481750f92aebcfd682255cc9f62.json)
- [证据 parameter-account-n0-p12](../../../assets/deliveries/CANDIDATES/56/evidence/3062e9603bcbeb307267149f63229ee4a788be3ea8aac2ac063503ed8b283f84.json)
- [证据 parameter-account-n0-p13](../../../assets/deliveries/CANDIDATES/56/evidence/64ef845c9baf70437fc2e1656fcc007ffbfe0f4603ed402ec32deec085205d7b.json)
- [证据 parameter-account-n0-p14](../../../assets/deliveries/CANDIDATES/56/evidence/c0b6a28a6594e881828b5fad44f5db3a78fb4f8e71ff71384173c7f9400f2dba.json)
- [证据 parameter-account-n0-p15](../../../assets/deliveries/CANDIDATES/56/evidence/43ee96d2936b18589f74b8751c2a4e10123971bc1ff0e48810d3c55b5fac546a.json)
- [证据 parameter-account-n0-p16](../../../assets/deliveries/CANDIDATES/56/evidence/cdd99fec32c78ccfce2e4f7a793cba9a93412e07ee4f99e1ad3985588632c990.json)
- [证据 parameter-account-n0-p17](../../../assets/deliveries/CANDIDATES/56/evidence/123d6ecc862096ad5e4bc2252f43de4cab4d2b7d6a475fd337ad2b7a658ccf32.json)
- [证据 parameter-account-n0-p18](../../../assets/deliveries/CANDIDATES/56/evidence/6d18284ef4d4cd335ceea9a9e2a22ccaaff90076c0a12fa1fa23e29f70511f59.json)
- [证据 parameter-account-n0-p19](../../../assets/deliveries/CANDIDATES/56/evidence/cad8e3ccab9bb725a004a7cfa756da93a07ec9edde5d2de02647d3aa8f1aa72b.json)
- [证据 parameter-account-n0-p20](../../../assets/deliveries/CANDIDATES/56/evidence/1fbb6a504e455186bd3a61b4b8faca88cc85dbf067ff04fc1cb2d1b2476d53fc.json)
- [证据 parameter-account-n0-p21](../../../assets/deliveries/CANDIDATES/56/evidence/0d271839516ab48ef9894be00ec8b8f827a6c39f8f9a258d3faa81899e0f05da.json)
- [证据 parameter-account-n0-p22](../../../assets/deliveries/CANDIDATES/56/evidence/ae13a43e9b6819c08f915de2fab0be1e4072b6f18e62e2914024f3dc831085fa.json)
- [证据 parameter-account-n0-p23](../../../assets/deliveries/CANDIDATES/56/evidence/2c0ce53b5b4338092777bf559b531d9c0fa104d53b656fd02705ce24099dca32.json)
- [证据 parameter-account-n0-p24](../../../assets/deliveries/CANDIDATES/56/evidence/a42a00697137b5af8c964e0fc50ab9a0549d1108879cc1c534ba777dabba68ad.json)
- [证据 parameter-account-n0-p25](../../../assets/deliveries/CANDIDATES/56/evidence/9305249660bf533e8d294df4b321a5196112f0445d6c386aab8c211f441c61d9.json)
- [证据 parameter-account-n0-p26](../../../assets/deliveries/CANDIDATES/56/evidence/b30ba1277764a4eb6752586c4ab1fa3fbcd2fccf05eab8c7c3c71b2cbe1c5a40.json)
- [证据 parameter-account-n0-p27](../../../assets/deliveries/CANDIDATES/56/evidence/9135515629cd9f9319a6111d4cde7565b41333809e9aba3c7ac6e13c6bffa8e5.json)
- [证据 parameter-account-n0-p28](../../../assets/deliveries/CANDIDATES/56/evidence/d6d48c97169d13bc605286d34804a2231b16e3dafd1af5f386cc18eecfaa6d45.json)
- [证据 parameter-account-n0-p29](../../../assets/deliveries/CANDIDATES/56/evidence/794facb34e0d733555d5f22422dc3a2f1520dff62b32bf734ff636a98b935dea.json)
- [证据 parameter-account-n0-p30](../../../assets/deliveries/CANDIDATES/56/evidence/93078f615c7e200ed64e5d141f96b88a8a1cf2ce13501f9a866123ea6abfbfff.json)
- [证据 parameter-account-n0-p31](../../../assets/deliveries/CANDIDATES/56/evidence/69539de24489f1bbcc4cf14f1a99e83ae6d309922248dff46937edaf22aa2cf1.json)
- [证据 parameter-plan-n0](../../../assets/deliveries/CANDIDATES/56/evidence/e3a1dfafc3e93ff1e138964e7aa3f3f064f6dfcc6fb203fc8b05089b6decec92.json)
- [证据 fee-stress-00](../../../assets/deliveries/CANDIDATES/56/evidence/45fdea3ec02a782181c33501a4eb12603b693fbc433d0ff71be69450e0bccb96.json)
- [证据 completed-full55-reference](../../../assets/deliveries/CANDIDATES/56/evidence/dce3e97556d8a78e264527f8c596abc2966ea7595e8c859e1f639a7dc93c6224.json)
- [证据 management-closeout-62faa9fecdf5bd480deb0e17326b9ac3](../../../assets/deliveries/CANDIDATES/56/evidence/62faa9fecdf5bd480deb0e17326b9ac31057efd4ffbae5055198c53b34fc0047.json)
- [证据 management-closeout-decc233cad4a9affb4e3dbfd8023a71a](../../../assets/deliveries/CANDIDATES/56/evidence/decc233cad4a9affb4e3dbfd8023a71a5d40ad3f9ed68b261719bc8fcb4214ea.json)
- [证据 management-closeout-0d1617bd6b8ba00ef1e2d44ed57212a3](../../../assets/deliveries/CANDIDATES/56/evidence/0d1617bd6b8ba00ef1e2d44ed57212a3d0dc87328e182dfd1fdfd4ffbfde9cc4.json)
- [证据 prior-unoccupied-metadata-snapshot](../../../assets/deliveries/CANDIDATES/56/evidence/1243dd72b4b10a1aca35275bc8cda5d0ccb96ba1f93ae764304dac2470626358.json)
- [证据 input-complete-identity-variants](../../../assets/deliveries/CANDIDATES/56/evidence/e0044b950c6dc499610b6bf3fa1d8943efb3434b77b393f69b5e499c79eb2cd6.json)
- [证据 input-verified-feature-state50](../../../assets/deliveries/CANDIDATES/56/evidence/580683742ee6ad10880ba32aac85f0e16d8b2c6e2dea4f10fbea3fc32b764f40.json)
- [证据 input-feature-scope-review](../../../assets/deliveries/CANDIDATES/56/evidence/4a72709312a8887c23bdd56f7c83ddf8612c7933f2b108c136e393a81c5ec54f.json)
- [证据 management-closeout-be75f9f9b7572ca4b8b1b1119de81a59](../../../assets/deliveries/CANDIDATES/56/evidence/be75f9f9b7572ca4b8b1b1119de81a59d1d63e2571722475ba9d536d9ef2d59b.json)
- [证据 frozen-material-25614d25286db6761964e744](../../../assets/deliveries/CANDIDATES/56/evidence/25614d25286db6761964e74471d76449f16249fed5325cf94602ba9a90748f4e.py)
- [证据 frozen-material-1a88c35a99a25b705c3d1e2f](../../../assets/deliveries/CANDIDATES/56/evidence/1a88c35a99a25b705c3d1e2fa00ef50a3c21d268d5132b1d06e20d12322fa04b.json)
- [证据 frozen-material-738d77c688edf3af75a4516b](../../../assets/deliveries/CANDIDATES/56/evidence/738d77c688edf3af75a4516b0df6a5907d7d2b27ce5fd64ceb80178f9f28f507.py)
- [证据 frozen-material-1bf630141bcc23bc6bc1c6e6](../../../assets/deliveries/CANDIDATES/56/evidence/1bf630141bcc23bc6bc1c6e635da70ba512313c6dbd779f31b983be6303b301a.json)
- [证据 frozen-material-944ac450f93dc5c4470370e0](../../../assets/deliveries/CANDIDATES/56/evidence/944ac450f93dc5c4470370e0357cfef6c28813e3913e00f9fa74ebaf3b2ef88a.json)
- [证据 frozen-material-96af7610edd8e4463bbbc800](../../../assets/deliveries/CANDIDATES/56/evidence/96af7610edd8e4463bbbc80090111e08a35900d1fb8da5b515ddd9588e2525fa.py)
- [证据 frozen-material-73b20cc8d6249daebd6fba77](../../../assets/deliveries/CANDIDATES/56/evidence/73b20cc8d6249daebd6fba77740bb960e9d13d4cc84537930a2a5083060d0581.py)
- [证据 frozen-material-311f85d7f9f18cf17088b82e](../../../assets/deliveries/CANDIDATES/56/evidence/311f85d7f9f18cf17088b82ecbae5d4c713a96a7bc4e84ef1810b483a8ac21b0.py)
- [证据 frozen-material-9b0bd61b3b8fc275daf24159](../../../assets/deliveries/CANDIDATES/56/evidence/9b0bd61b3b8fc275daf24159763af9ed3b80abd30791d3087b0b29ce69fa3d9a.py)
- [证据 frozen-material-129f238b0713de802e9e16ae](../../../assets/deliveries/CANDIDATES/56/evidence/129f238b0713de802e9e16ae4c22c66386d846211b4ea78189248c952ad91036.py)
- [证据 frozen-material-8a6ed1628ed17d85e7052ba5](../../../assets/deliveries/CANDIDATES/56/evidence/8a6ed1628ed17d85e7052ba5b701e029a55b1fb3571d7fbc11be269924317a87.json)
- [证据 frozen-material-ad8f4b9cc40a7444a4084479](../../../assets/deliveries/CANDIDATES/56/evidence/ad8f4b9cc40a7444a4084479d9b760c03ca96de4328bd5419f8a9350bc485dfc.json)
- [证据 frozen-material-2631e650456bccf2a092f6ff](../../../assets/deliveries/CANDIDATES/56/evidence/2631e650456bccf2a092f6ff8fc8dd8ad41b7a9931584c54d70c3dc6d58c22ce.json)
- [证据 frozen-material-15f066c079b9b11609196d74](../../../assets/deliveries/CANDIDATES/56/evidence/15f066c079b9b11609196d74c1937e994340309f3762a043a1b6f3d8c738e173.json)
- [证据 management-closeout-36d40d403ef884620d9ef769d6641c9b](../../../assets/deliveries/CANDIDATES/56/evidence/36d40d403ef884620d9ef769d6641c9bacf876585253c1de30963ae17ace7043.py)
- [证据 management-closeout-93a667987cfb3681a0d044985b4ed401](../../../assets/deliveries/CANDIDATES/56/evidence/93a667987cfb3681a0d044985b4ed401abda2ee80840acb8c80ec01af299e12d.json)
- [证据 management-closeout-fcc5e502719317624bee0741f8587cd2](../../../assets/deliveries/CANDIDATES/56/evidence/fcc5e502719317624bee0741f8587cd2fc5d00070be392742abe38978336b745.py)
- [证据 management-closeout-611936400540b8cc3c307bbf52df4f87](../../../assets/deliveries/CANDIDATES/56/evidence/611936400540b8cc3c307bbf52df4f87598d32b277b0646e0c40d4a39bda35c9.json)
- [证据 management-closeout-0fb764b9505e9f9045248313cfb9f1d0](../../../assets/deliveries/CANDIDATES/56/evidence/0fb764b9505e9f9045248313cfb9f1d09cf1b8151f124523170bf3c3e1da9ee9.json)
- [证据 management-closeout-3a22f3f8238ca881ab5df52142cc7e92](../../../assets/deliveries/CANDIDATES/56/evidence/3a22f3f8238ca881ab5df52142cc7e923ed264a2b2e57fa2bd3954549f3ee9a8.json)
- [证据 management-closeout-61955d733c35edcb8c052a9646c2894a](../../../assets/deliveries/CANDIDATES/56/evidence/61955d733c35edcb8c052a9646c2894af6c8ee96bb2881c20b1030d385fc55b4.py)
- [证据 management-closeout-e53700278e9c8647866fc927486703b5](../../../assets/deliveries/CANDIDATES/56/evidence/e53700278e9c8647866fc927486703b59d68aa60537c06679f2e42781af83186.py)
- [证据 management-closeout-a2922f0f0bb2613119bff56b62e39a05](../../../assets/deliveries/CANDIDATES/56/evidence/a2922f0f0bb2613119bff56b62e39a0549befb767b9bdbba7c4909d14941bddd.py)
- [证据 management-closeout-caf12faeededd7f511528545b03fbe40](../../../assets/deliveries/CANDIDATES/56/evidence/caf12faeededd7f511528545b03fbe40fffdd38fa1796b11af6aa47f12d0b877.py)
- [证据 management-closeout-857a6f746c1991d6ff649467d41bc76b](../../../assets/deliveries/CANDIDATES/56/evidence/857a6f746c1991d6ff649467d41bc76bbec0ddf6c481fb450173dccf32c6e6d6.py)
- [证据 management-closeout-eb26a16d5c7d6f2b655ca12537d73de2](../../../assets/deliveries/CANDIDATES/56/evidence/eb26a16d5c7d6f2b655ca12537d73de28888fe05d016bce8a0b71b34c96eb73a.py)
- [证据 management-closeout-14a41bc2069d9896aeddb7e2136b4c28](../../../assets/deliveries/CANDIDATES/56/evidence/14a41bc2069d9896aeddb7e2136b4c287a875bb4ece4e4e71ed96a3531508511.py)
- [证据 management-closeout-e18857d1549e55526d60b0ecad03e9dd](../../../assets/deliveries/CANDIDATES/56/evidence/e18857d1549e55526d60b0ecad03e9dded5ef9b97e80e3fdd95373aacd34b29c.json)
- [证据 management-closeout-5c9e627faba98a5fb309d3fc926efba8](../../../assets/deliveries/CANDIDATES/56/evidence/5c9e627faba98a5fb309d3fc926efba8bd6beb4b570676a607d1b67cb7d436fe.json)
- [证据 management-closeout-d2628c7ace32b9bd100a7311f1ee994d](../../../assets/deliveries/CANDIDATES/56/evidence/d2628c7ace32b9bd100a7311f1ee994d8e28bf3a784233e50714388b490febd2.json)
- [证据 management-closeout-01a38697c1cc830e3ada5e502431ac9f](../../../assets/deliveries/CANDIDATES/56/evidence/01a38697c1cc830e3ada5e502431ac9fc66e0e7ed0f2e8bf616311c7d9d602de.py)
- [证据 management-closeout-84a9c5af58c8f66798da89213c3054b6](../../../assets/deliveries/CANDIDATES/56/evidence/84a9c5af58c8f66798da89213c3054b6730afa5661ce2150105772bd2bbf1dfe.json)
- [证据 management-closeout-5c14a6abe757537e3214016b6f326e3c](../../../assets/deliveries/CANDIDATES/56/evidence/5c14a6abe757537e3214016b6f326e3c832d3a6765dec82a89145e41329b3e05.json)
- [证据 management-closeout-49c091e0c0eee81cdf2bccf7c50bd6a4](../../../assets/deliveries/CANDIDATES/56/evidence/49c091e0c0eee81cdf2bccf7c50bd6a4b6fc73b9a183b763abed6ee883e98305.json)
- [证据 management-closeout-4f2a781378f173bbfdf43029a57d62a6](../../../assets/deliveries/CANDIDATES/56/evidence/4f2a781378f173bbfdf43029a57d62a6b009893d2d7c84615d9638956819fbb1.py)
- [证据 management-closeout-f3a8a9e8a69cb61b326c1702bf8b471f](../../../assets/deliveries/CANDIDATES/56/evidence/f3a8a9e8a69cb61b326c1702bf8b471fa49105fd91cc58ec9d09dc27492669e4.py)
- [证据 management-closeout-3fc44c4bfe601b26a43cee533303d41e](../../../assets/deliveries/CANDIDATES/56/evidence/3fc44c4bfe601b26a43cee533303d41e54db365f98c526ccfcf004a9b8afdce8.py)
- [证据 management-closeout-b1e6b77bd0983791550106c7e468f396](../../../assets/deliveries/CANDIDATES/56/evidence/b1e6b77bd0983791550106c7e468f396371381f58f828cdcaf2c47ce1abf8a4a.py)
- [证据 management-closeout-899522b56a578190c1f254e21c2babc1](../../../assets/deliveries/CANDIDATES/56/evidence/899522b56a578190c1f254e21c2babc1fdce6ece58cc3f947cd5e76065d78dd3.py)
- [证据 management-closeout-6dfa9c7d37d8eef604a0dfccb82ebc37](../../../assets/deliveries/CANDIDATES/56/evidence/6dfa9c7d37d8eef604a0dfccb82ebc37ff4e87b44fff04686a27ad8bb7da518c.py)
- [证据 management-closeout-ba5162b6e2cbf99b77b42933fd6e1398](../../../assets/deliveries/CANDIDATES/56/evidence/ba5162b6e2cbf99b77b42933fd6e1398bbb66cbcfd1b0184654f378fcc6e70ca.py)
- [证据 management-closeout-7f07d54b12a180533fc6155d6c6a412a](../../../assets/deliveries/CANDIDATES/56/evidence/7f07d54b12a180533fc6155d6c6a412ae401586a0ce09ffb1a974c3a0c7e7ed9.py)
- [证据 management-closeout-d2a41e78e7df70c9cb75fb8883d71446](../../../assets/deliveries/CANDIDATES/56/evidence/d2a41e78e7df70c9cb75fb8883d71446bc26a4850361ba97e873efefd9d6c680.py)
- [证据 management-closeout-74af45fc5f6c1e5915b6fff7a968bf2b](../../../assets/deliveries/CANDIDATES/56/evidence/74af45fc5f6c1e5915b6fff7a968bf2b4577d8f5c3d3a53b47649cafa9b72ed6.json)
- [证据 management-closeout-62c861387aed05b9d34713c1e870e1e1](../../../assets/deliveries/CANDIDATES/56/evidence/62c861387aed05b9d34713c1e870e1e1f12cc8a459ed883462b5d57bd4595817.json)
- [证据 management-closeout-15655db74c7606143ff3041d71be7f27](../../../assets/deliveries/CANDIDATES/56/evidence/15655db74c7606143ff3041d71be7f27500a855f268f2cb3033a2b19340b9519.json)
- [证据 management-closeout-0e3bbf9058be24e80f1123b20e517c02](../../../assets/deliveries/CANDIDATES/56/evidence/0e3bbf9058be24e80f1123b20e517c0277840968eb950bcb32974e4ebf056c0a.py)
- [证据 management-closeout-f5eeddf499de58f46058f288c994c2e4](../../../assets/deliveries/CANDIDATES/56/evidence/f5eeddf499de58f46058f288c994c2e410f8e0ee4989240ade26972079083c6f.json)
- [证据 management-closeout-257b545bca6e2f19d5ebe23e3c02884a](../../../assets/deliveries/CANDIDATES/56/evidence/257b545bca6e2f19d5ebe23e3c02884a5ab9d087b4affed45595ccc1541d0a65.json)
- [证据 management-closeout-96c3bac2ba16fd6cdacb2e17211f2d6a](../../../assets/deliveries/CANDIDATES/56/evidence/96c3bac2ba16fd6cdacb2e17211f2d6ab68695154332f16da767d9e7a4e1986a.json)
- [证据 management-closeout-4c56eccb4a844d5dba7ff5103cce98eb](../../../assets/deliveries/CANDIDATES/56/evidence/4c56eccb4a844d5dba7ff5103cce98eb97483f9e94d3647d3b5251f8e7da3b45.py)
- [证据 management-closeout-03a5d3316a212bafbe2c0f892b3dd467](../../../assets/deliveries/CANDIDATES/56/evidence/03a5d3316a212bafbe2c0f892b3dd467cc786bd1adbe0b084ef471211cb32cba.py)
- [证据 management-closeout-8495b86b1dc2bcd8e48de5488b25a163](../../../assets/deliveries/CANDIDATES/56/evidence/8495b86b1dc2bcd8e48de5488b25a1637b4d5f31ccbb62231e79eb0317646c66.json)
- [证据 management-closeout-ab0fd50b91274a22f36e44c5761a721c](../../../assets/deliveries/CANDIDATES/56/evidence/ab0fd50b91274a22f36e44c5761a721c758de02bde64655df90190cd489e7710.py)
- [证据 management-closeout-05a7ed9ab7ccd299b84dcd489b8c9d64](../../../assets/deliveries/CANDIDATES/56/evidence/05a7ed9ab7ccd299b84dcd489b8c9d64b3a68e9f7ffd61fb41c70a8965f7e264.json)
- [证据 management-closeout-2768579e16ff3b2968032783fd98008a](../../../assets/deliveries/CANDIDATES/56/evidence/2768579e16ff3b2968032783fd98008adf173e35759c9fac60f8a4bc4a9b8aa6.json)
- [证据 management-closeout-2faf69e461f3b42cc82e58b436ac1352](../../../assets/deliveries/CANDIDATES/56/evidence/2faf69e461f3b42cc82e58b436ac13527d0af7a2ca9b79977def85b391e1dff3.json)
- [证据 frozen-material-6beefbf2c4fb42e7cb626999](../../../assets/deliveries/CANDIDATES/56/evidence/6beefbf2c4fb42e7cb6269996bb3166382cfc723b683492c4d04dcf02ec97637.py)
- [证据 frozen-material-85bf3774870d760998b3c2ff](../../../assets/deliveries/CANDIDATES/56/evidence/85bf3774870d760998b3c2ff171d6f3c87f34c8254181119c20b37f171119364.json)
- [证据 management-closeout-560689afbd21a388bbe8337730125a4b](../../../assets/deliveries/CANDIDATES/56/evidence/560689afbd21a388bbe8337730125a4bf805ca20e88e0b377d2402aa39cdb4b6.py)
- [证据 management-closeout-f38c71d3392fb791fdd064f366cc251e](../../../assets/deliveries/CANDIDATES/56/evidence/f38c71d3392fb791fdd064f366cc251e33c064d7b88a0cd8b737f2603ccf236b.py)
- [证据 management-closeout-e891e44c69236eee5fefa6bd7222e191](../../../assets/deliveries/CANDIDATES/56/evidence/e891e44c69236eee5fefa6bd7222e191b25333e4ece680f27abc13c2618bdf36.py)
- [证据 management-closeout-0ded5fbda31185c3cbec00bce9dc9941](../../../assets/deliveries/CANDIDATES/56/evidence/0ded5fbda31185c3cbec00bce9dc99414c2c21c634172ccf6b08d567e7072263.py)
- [证据 management-closeout-8a9d86a30d1c5f98a4a621ef1dc4c263](../../../assets/deliveries/CANDIDATES/56/evidence/8a9d86a30d1c5f98a4a621ef1dc4c26387ec7db0e1f365e8fc28952b364e82e8.py)
- [证据 N_LOCK](../../../assets/deliveries/CANDIDATES/56/evidence/dafa20647c83729ba765b0bf8b73d1f90b1713f373ae0726d47dd078c7e7551b.json)
- [证据 N_CURRENT](../../../assets/deliveries/CANDIDATES/56/evidence/a74dfe40659b4b02bde05253d132aace91def83855a6252c2af2109b34161306.json)
- [证据 strict-fee-request-equality-resume-source](../../../assets/deliveries/CANDIDATES/56/evidence/b080a382ce7e16406161485f09a147a5c765d7637c0d294a68e543f7159f7f9f.py)
- [证据 strict-fee-request-equality-pure-proof](../../../assets/deliveries/CANDIDATES/56/evidence/1744b9ddb286299b854cbc0ead9d30ebc9aae4ae24d31ed98bf0e5a433e3d4bb.json)
- [证据 management-closeout-9c651d57a9cc107efda88be0d5226568](../../../assets/deliveries/CANDIDATES/56/evidence/9c651d57a9cc107efda88be0d52265687449a435d967ef2cef74acfde0e90d30.json)
- [证据 management-closeout-a6ce5cefd28e28e89b96c94ca5c7b562](../../../assets/deliveries/CANDIDATES/56/evidence/a6ce5cefd28e28e89b96c94ca5c7b5621483e0bbb468da241cef766fe4357a99.json)
- [证据 management-closeout-2f24adff8770d08411b789f8085aa55b](../../../assets/deliveries/CANDIDATES/56/evidence/2f24adff8770d08411b789f8085aa55bde4f8e082fac5e7e564603ef25627670.json)
- [证据 management-closeout-70c08652493dee466487938bf725d64e](../../../assets/deliveries/CANDIDATES/56/evidence/70c08652493dee466487938bf725d64e92aa7a5b48c9972c5eecb262cf127c0d.json)
- [证据 management-closeout-2796082090a86361db7210fba99c37ac](../../../assets/deliveries/CANDIDATES/56/evidence/2796082090a86361db7210fba99c37ac132da9d73c4aa053507be420539e3cb3.json)
- [证据 management-closeout-5deadcbdab244d71491756e3959fdf74](../../../assets/deliveries/CANDIDATES/56/evidence/5deadcbdab244d71491756e3959fdf7408a2c46e001222e801a555c8d7caf821.json)
- [证据 management-closeout-c6859039bd63e4cfc7c6efcaabe1dfae](../../../assets/deliveries/CANDIDATES/56/evidence/c6859039bd63e4cfc7c6efcaabe1dfae6c793afd24cdf82c819797f9185c0116.json)
- [证据 management-closeout-a0bf3e80559b29a904409894f17f6a33](../../../assets/deliveries/CANDIDATES/56/evidence/a0bf3e80559b29a904409894f17f6a33bfa6ab67b5678bf51faff1e3223485b8.json)
- [证据 management-closeout-ff5008fcf3edf96784213219f1218bcf](../../../assets/deliveries/CANDIDATES/56/evidence/ff5008fcf3edf96784213219f1218bcf9c6a52e9c41cef98a2475a9ab804dc86.json)
- [证据 management-closeout-290dd4bc406e787156fda50be892f3e7](../../../assets/deliveries/CANDIDATES/56/evidence/290dd4bc406e787156fda50be892f3e78a15919527e85ef33b3892f2cf3b6521.json)
- [证据 management-closeout-a7507192e2fad73b9f9f3e8fba6923cc](../../../assets/deliveries/CANDIDATES/56/evidence/a7507192e2fad73b9f9f3e8fba6923cc3f095e331ec0da56d43635e7d136c878.json)
- [证据 management-closeout-c69f7a53bc7ad382a214388bee5c3580](../../../assets/deliveries/CANDIDATES/56/evidence/c69f7a53bc7ad382a214388bee5c3580b0dd51de0163667d9e5e55886ca2b6cf.json)
- [证据 management-closeout-81edb283f6f8935cd04a24e664e62afe](../../../assets/deliveries/CANDIDATES/56/evidence/81edb283f6f8935cd04a24e664e62afe0f219ed065156d2dc495fa32d6890c9e.json)
- [证据 management-closeout-e0b7313671c3a3b13bf53c31fbdd10b2](../../../assets/deliveries/CANDIDATES/56/evidence/e0b7313671c3a3b13bf53c31fbdd10b2738677add018ad7b26949ee1c9f18e40.json)
- [证据 management-closeout-3831f6f9e43935732b6a8177ee218d8c](../../../assets/deliveries/CANDIDATES/56/evidence/3831f6f9e43935732b6a8177ee218d8cbf9e212884ec69ea78a7b263ba15632f.json)
- [证据 management-closeout-8c87914f15c45c11bd5b455c49619435](../../../assets/deliveries/CANDIDATES/56/evidence/8c87914f15c45c11bd5b455c496194358012b7b76cb3b5993b8e91170595b05f.py)
- [证据 management-closeout-3651b47c6a529e1ca1dbfb88f8086073](../../../assets/deliveries/CANDIDATES/56/evidence/3651b47c6a529e1ca1dbfb88f8086073e9bb3342c263023639489c3dd45c6790.py)
- [证据 management-closeout-f687178ff6be15383c620663274f7368](../../../assets/deliveries/CANDIDATES/56/evidence/f687178ff6be15383c620663274f736890c3247a39f89f597915838c9bdc3bc1.json)
- [证据 management-closeout-6eb9a75c807703691c41d2022ee82629](../../../assets/deliveries/CANDIDATES/56/evidence/6eb9a75c807703691c41d2022ee826296fd55bd3c41e3e20af23b10e9ca228d3.json)
- [证据 management-closeout-826bf98c79c30be04af9a53055a04dfe](../../../assets/deliveries/CANDIDATES/56/evidence/826bf98c79c30be04af9a53055a04dfe578d1478a55056e2638b0b48dda39305.json)
- [证据 management-closeout-491639c811fdb8a8aff298434674058a](../../../assets/deliveries/CANDIDATES/56/evidence/491639c811fdb8a8aff298434674058a7ac2b4e9fceeaae1f1b0418d2b14724d.py)
- [证据 management-closeout-715cc4d606479cd140be921305abec89](../../../assets/deliveries/CANDIDATES/56/evidence/715cc4d606479cd140be921305abec89ba5a00891fd7e256e9dff2f98a0e6510.json)
- [证据 management-closeout-0c4fd9dbc6ecc97ebce5e821ee04088a](../../../assets/deliveries/CANDIDATES/56/evidence/0c4fd9dbc6ecc97ebce5e821ee04088af7ba07b3db27a6094746a61490ce2cb9.json)