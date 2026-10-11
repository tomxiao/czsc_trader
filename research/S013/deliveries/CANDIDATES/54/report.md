# EX058 上涨切换价格门与下跌局部资格恢复的联合对照

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

在原C2132数值中心组合两个已有业务规则：空仓遇到原下跌路线刚切换至上涨路线，原入场资格成立时要求收盘严格高于当天开盘，之后仍须原买入确认；下跌到期退出信号价低于本轮入场信号价后，空仓且当前仍属下跌路线并收阳线时，允许原相关性失格机会恢复资格，仍须原区间、动量及买入确认。没有新增零分确认门。

价格门只作用于切换当天，之后稳定上涨日沿用原规则。任意成功入场信号清空旧退出记忆，空仓价格或分数拒绝则保留；持仓日不适用资格例外。到期、区间、路线切换和风险退出及优先级、年龄、信号锚点全部沿用原规则。退出价格分类不是实际成交盈亏。

原策略、单独上涨边界BODY门、单独下跌局部BODY恢复、联合规则构成四格。四个实际完整政策分别传播持仓和资金，旧收益、交易数量及利润不能相加预测组合结果。历史均值相关+CLOSE账户额外复用，只作历史反证。

选择依据来自已见开发池：原32点2023下跌到期退出来源平均贡献为正，上涨路线切换退出来源为负；单独边界门改善年度收益与回撤，却少1笔闭合交易达标，单独恢复资格增加交易却2023亏损。它们只支持互补机制的可证伪假说，不证明组合一定改善。选择偏差完整披露，没有独立市场验证。

## 完整中心账户

| 对照 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 原四门 |
|---|---|---:|---:|---:|---:|---:|---|
| 原策略 | C2132 | 16.1572% | 14.1599% | 112 | +12.1687% | +0.2841% | 通过 |
| 单独上涨边界BODY门 | C9102 | 16.6697% | 13.3493% | 109 | +14.3291% | +1.2316% | 未通过 |
| 单独下跌局部BODY恢复 | C7980 | 16.8663% | 14.4246% | 118 | +18.9454% | -0.0252% | 未通过 |
| 联合机制 | C8880 | 17.1346% | 13.6187% | 116 | +19.5931% | +0.9181% | 通过 |
| 历史均值相关+CLOSE门 | C4900 | 10.8889% | 21.2540% | 119 | +9.4200% | +0.5491% | 通过 |

联合中心：年化收益通过；各自然年回撤通过；闭合交易频率通过；基准亏损年份仍盈利通过。

四个旧账户按原身份、请求、载荷、数据、依赖和原生序列化认证复用。C9102与C7980均未达原四门，不升级为参数面板或新否决条件。一个新业务中心串行与spawn技术重复两次，信号及策略、基准双方五账本精确一致；现金、数量、价格、费用、年度、周期与尾仓核验通过，新策略完整逐日独立公式和状态机核验通过。技术PASS不代表经济达标。

联合与原中心目标仓位不同33天，原因不同51天；首个仓位分歧2020-11-09 00:00:00。

原确认分数及阈值计算不变。固定相同决策前状态时，稳定上涨日保留原资格，下跌资格包含原机会并可能恢复例外，上涨切换当天新增方向门；这些逻辑关系不代表整个完整政策的交易集合包含关系。局部OR例外会条件性屏蔽下跌相关门，原数值坐标仍在其他路径保持作用；不能把屏蔽本身当作稳健性证明。

## 原13完整域与同32坐标

| 指标 | 原C2132 | 历史C4900 | 联合C8880 |
|---|---:|---:|---:|
| 较差一端年化Q10（%） | 5.8974 | 1.7843 | 6.3981 |
| 较差一端全期回撤Q90（%） | 30.5044 | 34.6163 | 28.3508 |
| 相对中心收益下降（百分点） | 10.2598 | 9.1046 | 10.7364 |
| 相对中心回撤增加（百分点） | 16.3446 | 13.3624 | 14.7320 |

原13数值中心、全域、类型和单位保持，同域宽标准化联合L2=5%、32点、seed13、HALF_EVEN整数、LINEAR分位数。旧两组64原生账户认证复用，新32完整执行，不删维、不缩域、不替换坐标。邻居四门通过数量仅诊断，不新增否决条件。

## 最强反证及适用边界

单独边界BODY门C9102只有109笔，低于最低110笔；单独恢复C7980虽118笔、年化16.8663%，2023仍亏损0.0252%。历史均值相关叠加边界BODY的EX029仍未过年度回撤门。互补描述不能保证组合保住频率、收益或回撤，更不能代替参数两尾检验。

EX057将局部恢复分数限制为中性以上，中心2023反而亏损1.1162%；完整归因显示其保留退出记忆后触发不同的后来入场，原全年净利润约+4088.72元变成−16547.08元，实际价差利润下降16465.00元且费用增加4170.80元。不能删除旧负分交易来推算新收益，也不能把确认分数更高当作盈利保证。

原C2132虽然中心达标，原32点年化Q10仅5.8974%、全期回撤Q90为30.5044%；历史C4900中心达标但两项绝对尾部均更差。联合中心达标与少量局部改善不构成目标完成，必须同时改善绝对尾部与相对中心的两项退化。

previous raw路线来自完整因果日线动量先shift再重索引。暖启动为max(原父需求,路线窗口+2)，原中心及同32实际父需求已覆盖+2，实际准备区间不变；完整域路线窗口60、其他窗口小且确认40时需求62较原61多一条因果历史，明确披露，不缩域或补缺失值。所有原13数值仍可检验；固定类别、价格方向及两规则的组合不是数值检验已证明的普适规律。

仅S013既有数据和原交易合同，已见开发池反复研究，没有独立市场验证。RSCH阶段三，未推进其他阶段、冻结、PTE或生产；FULL只校验关联证据完整性，Git不是完整数据资产备份。

目标判断：{'center_four_gates': True, 'absolute_q10_return_better': True, 'absolute_q90_drawdown_better': True, 'relative_return_degradation_better': False, 'relative_drawdown_degradation_better': True}

联合机制未满足原目标，依据完整路径反证继续研究，保持原目标与原参数域。

新增机制业务账户1、实际评价2、旧中心复用4；新参数业务账户32、实际评价33、旧参数复用64。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/54/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/54/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [B0-RAW-RECOVERY](../../../assets/deliveries/CANDIDATES/54/evidence/90462cbc1be6b86ac691bee3f2f921d6c3db33e6e6b1d9ca12fd26b8e008707b.json)
- [B0-BULL-BOUNDARY](../../../assets/deliveries/CANDIDATES/54/evidence/7be615850fb5672f0d9920e1033e425a0d99affc0d3e3d03c206b93885d3cda7.json)
- [N0](../../../assets/deliveries/CANDIDATES/54/evidence/2ba4906b271e148a956755df9ba9907457ef0bee726b7a24a13602df4e73fa3e.json)
- [B0-TIME::B0-TIME-P00](../../../assets/deliveries/CANDIDATES/54/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME::B0-TIME-P01](../../../assets/deliveries/CANDIDATES/54/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME::B0-TIME-P02](../../../assets/deliveries/CANDIDATES/54/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME::B0-TIME-P03](../../../assets/deliveries/CANDIDATES/54/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME::B0-TIME-P04](../../../assets/deliveries/CANDIDATES/54/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME::B0-TIME-P05](../../../assets/deliveries/CANDIDATES/54/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME::B0-TIME-P06](../../../assets/deliveries/CANDIDATES/54/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME::B0-TIME-P07](../../../assets/deliveries/CANDIDATES/54/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME::B0-TIME-P08](../../../assets/deliveries/CANDIDATES/54/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME::B0-TIME-P09](../../../assets/deliveries/CANDIDATES/54/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME::B0-TIME-P10](../../../assets/deliveries/CANDIDATES/54/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME::B0-TIME-P11](../../../assets/deliveries/CANDIDATES/54/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME::B0-TIME-P12](../../../assets/deliveries/CANDIDATES/54/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME::B0-TIME-P13](../../../assets/deliveries/CANDIDATES/54/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME::B0-TIME-P14](../../../assets/deliveries/CANDIDATES/54/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME::B0-TIME-P15](../../../assets/deliveries/CANDIDATES/54/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME::B0-TIME-P16](../../../assets/deliveries/CANDIDATES/54/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME::B0-TIME-P17](../../../assets/deliveries/CANDIDATES/54/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME::B0-TIME-P18](../../../assets/deliveries/CANDIDATES/54/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME::B0-TIME-P19](../../../assets/deliveries/CANDIDATES/54/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME::B0-TIME-P20](../../../assets/deliveries/CANDIDATES/54/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME::B0-TIME-P21](../../../assets/deliveries/CANDIDATES/54/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME::B0-TIME-P22](../../../assets/deliveries/CANDIDATES/54/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME::B0-TIME-P23](../../../assets/deliveries/CANDIDATES/54/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME::B0-TIME-P24](../../../assets/deliveries/CANDIDATES/54/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME::B0-TIME-P25](../../../assets/deliveries/CANDIDATES/54/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME::B0-TIME-P26](../../../assets/deliveries/CANDIDATES/54/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME::B0-TIME-P27](../../../assets/deliveries/CANDIDATES/54/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME::B0-TIME-P28](../../../assets/deliveries/CANDIDATES/54/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME::B0-TIME-P29](../../../assets/deliveries/CANDIDATES/54/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME::B0-TIME-P30](../../../assets/deliveries/CANDIDATES/54/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME::B0-TIME-P31](../../../assets/deliveries/CANDIDATES/54/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [B0-COUPLED::N0-P00](../../../assets/deliveries/CANDIDATES/54/evidence/8b52feb7089cffe70d9021197a45f309b8906fe343fd85120036a82cbf9c004c.json)
- [B0-COUPLED::N0-P01](../../../assets/deliveries/CANDIDATES/54/evidence/cdd7dccfa0da7ae03b743a21e48a8aba760b0341f00e73f4e825e4ceb4c77080.json)
- [B0-COUPLED::N0-P02](../../../assets/deliveries/CANDIDATES/54/evidence/9fad10754f615e5c41fb1a718fbe9a6c045ebd8ac463c0f23a72e10666e1fed2.json)
- [B0-COUPLED::N0-P03](../../../assets/deliveries/CANDIDATES/54/evidence/00d30ba9690c9b92d17a628a50de0da836a1d7d106cff956ad88e2141f80cb6e.json)
- [B0-COUPLED::N0-P04](../../../assets/deliveries/CANDIDATES/54/evidence/aa2e4c590c9cd82dfeadb1063273d6b15b45eef2c93c7d9f90134c6e85985bec.json)
- [B0-COUPLED::N0-P05](../../../assets/deliveries/CANDIDATES/54/evidence/0884ee746fd76a00b22b33967195a3a387b25da8922c8be6de894d62df687dfe.json)
- [B0-COUPLED::N0-P06](../../../assets/deliveries/CANDIDATES/54/evidence/ee9def90c73145e9d990a235ba4f7e94fa580d624125fb9ab34818cbe5d107b9.json)
- [B0-COUPLED::N0-P07](../../../assets/deliveries/CANDIDATES/54/evidence/5f3461d47fb7b4c9338b8a8b479a0a6f49412ed0f2c70226bbd204296478d83f.json)
- [B0-COUPLED::N0-P08](../../../assets/deliveries/CANDIDATES/54/evidence/cb3769d22cbd8170797367c194b389f6e2dd708278d55ff3c26d6f9cb9d62cbc.json)
- [B0-COUPLED::N0-P09](../../../assets/deliveries/CANDIDATES/54/evidence/c94030e112bdb6cab54d27dc15199db42e9d886db62dc9dcdf062647bab92f0c.json)
- [B0-COUPLED::N0-P10](../../../assets/deliveries/CANDIDATES/54/evidence/b031978651fe123213477dae03ac9def22348a1116babd87fc02b5d1f629a7c9.json)
- [B0-COUPLED::N0-P11](../../../assets/deliveries/CANDIDATES/54/evidence/5d7013e4c8d1903694786398e486a6ed9fd38b88151acb618259d9cd22927552.json)
- [B0-COUPLED::N0-P12](../../../assets/deliveries/CANDIDATES/54/evidence/1ef7f4e1189b56d6d713e23f5b2fdfc78dc7794b8d793573a3fffb426acc0e6e.json)
- [B0-COUPLED::N0-P13](../../../assets/deliveries/CANDIDATES/54/evidence/4208ec1da81fb5ad0325bbd20e69797d241c329fc4c2e8e5b54931329868a422.json)
- [B0-COUPLED::N0-P14](../../../assets/deliveries/CANDIDATES/54/evidence/3ebf6975f4f6e6ccea30553b56a359a9e9c4e0f834e8e9c62e182a5d7e501326.json)
- [B0-COUPLED::N0-P15](../../../assets/deliveries/CANDIDATES/54/evidence/0bfc404ce11e85f66410b0faf1d26874114010ba3b332145a8e74980aec06047.json)
- [B0-COUPLED::N0-P16](../../../assets/deliveries/CANDIDATES/54/evidence/f31f4de50a96b5e9355fb6f0dd1fbbd78b5cf8e5849a70b2f30d4a6ec20cc42f.json)
- [B0-COUPLED::N0-P17](../../../assets/deliveries/CANDIDATES/54/evidence/b376761b8720466b3664ab93e17dadf1d90e9db2ef9d3e1623706af9473c4683.json)
- [B0-COUPLED::N0-P18](../../../assets/deliveries/CANDIDATES/54/evidence/75d3678c81ddb4aa77dba987df31d56dccb16e4670660e472ec51472cc5824c2.json)
- [B0-COUPLED::N0-P19](../../../assets/deliveries/CANDIDATES/54/evidence/b9650c9f8689c9484347ad76f569eb8bb762e3371a503a8b2ef28816cb40e106.json)
- [B0-COUPLED::N0-P20](../../../assets/deliveries/CANDIDATES/54/evidence/849028292cef252249bbcd8f6d23c3ed000ea86291126c5a37843058a5f83226.json)
- [B0-COUPLED::N0-P21](../../../assets/deliveries/CANDIDATES/54/evidence/303a8a774752297d889d0d9a2a0939195c815ae56797360f9b6b0259e7d48b63.json)
- [B0-COUPLED::N0-P22](../../../assets/deliveries/CANDIDATES/54/evidence/b3bec19f81c0612e3e95f947e57a5e56c30cefa30a2ff4cffd6d7e9e714ef5aa.json)
- [B0-COUPLED::N0-P23](../../../assets/deliveries/CANDIDATES/54/evidence/6394a851b6663be50542325af7af773e11dab1adeeb5b997bd4b179e4b25cf4d.json)
- [B0-COUPLED::N0-P24](../../../assets/deliveries/CANDIDATES/54/evidence/706bb3a28910bf56bfb44151f68c11c32c0d57bcdccc3c499b71ed47a59f1479.json)
- [B0-COUPLED::N0-P25](../../../assets/deliveries/CANDIDATES/54/evidence/b857b34d928c03ba8c71d4dacebf9829193ff1f185c7092482eecb4d91b232d5.json)
- [B0-COUPLED::N0-P26](../../../assets/deliveries/CANDIDATES/54/evidence/6db1a6097ab4bb15730ac10db206f27f6ece191326ef0686f6a7330ba187bab0.json)
- [B0-COUPLED::N0-P27](../../../assets/deliveries/CANDIDATES/54/evidence/0587291034ca9c3a77730bc739f94856a9b948edef3eb9de52633a7841c1ee0c.json)
- [B0-COUPLED::N0-P28](../../../assets/deliveries/CANDIDATES/54/evidence/dc7c9f99b5cf5bebe6aca5e86508fd1a07e867331f1ce74476cb21be5c29f3b0.json)
- [B0-COUPLED::N0-P29](../../../assets/deliveries/CANDIDATES/54/evidence/6f47f434e289e61283f04846a71a00473ee57cbaff1098a0d01d788de304920d.json)
- [B0-COUPLED::N0-P30](../../../assets/deliveries/CANDIDATES/54/evidence/bab9b8ec7926165a1072b529ca510d44fe69e262583d6d05a57df99ff588111d.json)
- [B0-COUPLED::N0-P31](../../../assets/deliveries/CANDIDATES/54/evidence/7c4db143900693ed02b62741881f2859593aca138472a8367cda06019a212513.json)
- [N0::N0-P00](../../../assets/deliveries/CANDIDATES/54/evidence/cee623b26dcd6acfa525015d44499247fe7a6c66ab712923fdaa8a3601ff29bd.json)
- [N0::N0-P01](../../../assets/deliveries/CANDIDATES/54/evidence/b327425b049a0fe753e83a7b01091be2d890b04b0cfd0488462be5029d7bd768.json)
- [N0::N0-P02](../../../assets/deliveries/CANDIDATES/54/evidence/e5cfddd0149ca8ce280597e2abfaf0cca85f7c4620c31dae183813686f1ed932.json)
- [N0::N0-P03](../../../assets/deliveries/CANDIDATES/54/evidence/849fd521cb9b0130308c4b06a5911ee8e41736d7ee510d2531c108e8d886b8da.json)
- [N0::N0-P04](../../../assets/deliveries/CANDIDATES/54/evidence/82e4bae906ffa94ddf8fcbdf405aa00ab1cce7165687e8840c470419227a4a4e.json)
- [N0::N0-P05](../../../assets/deliveries/CANDIDATES/54/evidence/a8b4c60564326c4e0ea52f58f32d4ffe2105ce79ab2dfaa1309df92524415d60.json)
- [N0::N0-P06](../../../assets/deliveries/CANDIDATES/54/evidence/bf8ef610c86d3e90b0b096ae382c80546bf7a28e4038f6edd8af8478c7412f95.json)
- [N0::N0-P07](../../../assets/deliveries/CANDIDATES/54/evidence/2ad53d15d8df40d017bd970303d588fa637d362711852dab7afaa409af96a75f.json)
- [N0::N0-P08](../../../assets/deliveries/CANDIDATES/54/evidence/2b82f0c08ca2583c055f094faca1125cd5c65085403a5383245ea4f6aee2f094.json)
- [N0::N0-P09](../../../assets/deliveries/CANDIDATES/54/evidence/39290686de53f3ca99b6365e46c883553fa4f342d2cd9f379487dcc6900db8e2.json)
- [N0::N0-P10](../../../assets/deliveries/CANDIDATES/54/evidence/efb03e27d1ee59342366fa409f3e6fd55e721012e86e04ef61e4250e1368dfda.json)
- [N0::N0-P11](../../../assets/deliveries/CANDIDATES/54/evidence/be1fb154ec7b5bb0b3416ca4138a1eb4ed5e8481750f92aebcfd682255cc9f62.json)
- [N0::N0-P12](../../../assets/deliveries/CANDIDATES/54/evidence/3062e9603bcbeb307267149f63229ee4a788be3ea8aac2ac063503ed8b283f84.json)
- [N0::N0-P13](../../../assets/deliveries/CANDIDATES/54/evidence/64ef845c9baf70437fc2e1656fcc007ffbfe0f4603ed402ec32deec085205d7b.json)
- [N0::N0-P14](../../../assets/deliveries/CANDIDATES/54/evidence/c0b6a28a6594e881828b5fad44f5db3a78fb4f8e71ff71384173c7f9400f2dba.json)
- [N0::N0-P15](../../../assets/deliveries/CANDIDATES/54/evidence/43ee96d2936b18589f74b8751c2a4e10123971bc1ff0e48810d3c55b5fac546a.json)
- [N0::N0-P16](../../../assets/deliveries/CANDIDATES/54/evidence/cdd99fec32c78ccfce2e4f7a793cba9a93412e07ee4f99e1ad3985588632c990.json)
- [N0::N0-P17](../../../assets/deliveries/CANDIDATES/54/evidence/123d6ecc862096ad5e4bc2252f43de4cab4d2b7d6a475fd337ad2b7a658ccf32.json)
- [N0::N0-P18](../../../assets/deliveries/CANDIDATES/54/evidence/6d18284ef4d4cd335ceea9a9e2a22ccaaff90076c0a12fa1fa23e29f70511f59.json)
- [N0::N0-P19](../../../assets/deliveries/CANDIDATES/54/evidence/cad8e3ccab9bb725a004a7cfa756da93a07ec9edde5d2de02647d3aa8f1aa72b.json)
- [N0::N0-P20](../../../assets/deliveries/CANDIDATES/54/evidence/1fbb6a504e455186bd3a61b4b8faca88cc85dbf067ff04fc1cb2d1b2476d53fc.json)
- [N0::N0-P21](../../../assets/deliveries/CANDIDATES/54/evidence/0d271839516ab48ef9894be00ec8b8f827a6c39f8f9a258d3faa81899e0f05da.json)
- [N0::N0-P22](../../../assets/deliveries/CANDIDATES/54/evidence/ae13a43e9b6819c08f915de2fab0be1e4072b6f18e62e2914024f3dc831085fa.json)
- [N0::N0-P23](../../../assets/deliveries/CANDIDATES/54/evidence/2c0ce53b5b4338092777bf559b531d9c0fa104d53b656fd02705ce24099dca32.json)
- [N0::N0-P24](../../../assets/deliveries/CANDIDATES/54/evidence/a42a00697137b5af8c964e0fc50ab9a0549d1108879cc1c534ba777dabba68ad.json)
- [N0::N0-P25](../../../assets/deliveries/CANDIDATES/54/evidence/9305249660bf533e8d294df4b321a5196112f0445d6c386aab8c211f441c61d9.json)
- [N0::N0-P26](../../../assets/deliveries/CANDIDATES/54/evidence/b30ba1277764a4eb6752586c4ab1fa3fbcd2fccf05eab8c7c3c71b2cbe1c5a40.json)
- [N0::N0-P27](../../../assets/deliveries/CANDIDATES/54/evidence/9135515629cd9f9319a6111d4cde7565b41333809e9aba3c7ac6e13c6bffa8e5.json)
- [N0::N0-P28](../../../assets/deliveries/CANDIDATES/54/evidence/d6d48c97169d13bc605286d34804a2231b16e3dafd1af5f386cc18eecfaa6d45.json)
- [N0::N0-P29](../../../assets/deliveries/CANDIDATES/54/evidence/794facb34e0d733555d5f22422dc3a2f1520dff62b32bf734ff636a98b935dea.json)
- [N0::N0-P30](../../../assets/deliveries/CANDIDATES/54/evidence/93078f615c7e200ed64e5d141f96b88a8a1cf2ce13501f9a866123ea6abfbfff.json)
- [N0::N0-P31](../../../assets/deliveries/CANDIDATES/54/evidence/69539de24489f1bbcc4cf14f1a99e83ae6d309922248dff46937edaf22aa2cf1.json)
- [plan](../../../assets/deliveries/CANDIDATES/54/evidence/12d2301b33f896b46fb541cd1150b7211ae09cc0017938b1e025b07f4402cfa9.json)
- [raw-below-reentry-method](../../../assets/deliveries/CANDIDATES/54/evidence/843b40a139a813f1a4d6af57f68e328505e22246cfcd150d446d4b42184c56b0.json)
- [geometry](../../../assets/deliveries/CANDIDATES/54/evidence/bf86aa5e626b27385fca9fc8fc544c592202947a0cb0cccd53805aebe245b091.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/54/evidence/ad442a1d6252922d27d9b92d10b7dbbe0e6334d76e3bb8596572cd0d1b0c5a3c.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/54/evidence/1a777be0dfd53de4a130ce685b40c963ae2a6dbb44c7df1c434ab7c39373057d.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/54/evidence/211716fb7fa7b6bb44636c08f7f0610dea66354cca04ea628bba6ea1f2656096.json)
- [parameter-v1-history-pure-prototype](../../../assets/deliveries/CANDIDATES/54/evidence/6f37c6b94ccc645c5adee2f39b30225dc7b7a5ea72501b47f2e9b9ed3d869852.json)
- [crosscheck-pure-prototype](../../../assets/deliveries/CANDIDATES/54/evidence/adef7732da514034f01c355dfd39e4458c60f0dec1ef8ef7a5d18ba163bb5d28.json)
- [loss_diagnosis_method](../../../assets/deliveries/CANDIDATES/54/evidence/2f7985eec3d0b5132843538ed1c4b5385328a4a652e3d214b191a15d3eaea6dd.json)
- [loss_diagnosis](../../../assets/deliveries/CANDIDATES/54/evidence/fb65921eba7e1d0c47d39de3a745be9b0f674ae205577093e5b98525e4536ae6.json)
- [protocols-center-screen-method-reference](../../../assets/deliveries/CANDIDATES/54/evidence/9e8a53e3b4f80b852a6a746b5be56153e5a16d889c093674978fde45bce5c1b6.json)
- [protocols-center-screen-reference](../../../assets/deliveries/CANDIDATES/54/evidence/2cbb7dc0635985c13c2026a43e0b898ecc771d58b18780017e91b48a65190850.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/54/evidence/419ad0cfb1e0ede6fd35f66228694f7d2d23cce500b72a5fe317ccd64ee692e9.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/54/evidence/1e37dc823effe12975c7ccefa46526dff3f8ef9f609c42b61db8d4b3c330559c.json)
- [protocols-method-reference](../../../assets/deliveries/CANDIDATES/54/evidence/6a14f0f085bf68cba8a9af4d0a14cc05770cf8d029a502e86a4b2dcd2028a78b.json)
- [protocols-parameter-analysis-references](../../../assets/deliveries/CANDIDATES/54/evidence/d3f342f5af835b289b5447bcebe477e0dabc74c58dfbbd5f585d6c3f11446067.json)
- [protocols-parameter-method-scope-clarification](../../../assets/deliveries/CANDIDATES/54/evidence/d1dcc05a3bd11c3c4d7f1880ddf81f8ca1dcb9d9b8ddf2115917c73ce18d7105.json)
- [protocols-parameter-method-scope-clarification-reference](../../../assets/deliveries/CANDIDATES/54/evidence/a440837d318fcd9b6fbbd7c07ffc9ced61e20e655dd8fc7b94bbcd32b897be8c.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/54/evidence/3987de4adde0c84cafb86f7ea5113772888d5dc178e7d6b8fc45c58694619271.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/54/evidence/fcce00c217548b20886b8a620af1c3e0a7f997de393968d7c73182d48a419512.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/54/evidence/0cd9f3b18c423f434ebe52800215b2275c87c937bf6ee480b3b2b844844561b7.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/54/evidence/5ab1e900d60164803d6cc9fef17f81b85318a90d83908775838259ad5d80c2aa.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/54/evidence/306e77a9c2b07f6f3d71fe261ee11212ad30fa84ac6e02b683c527dfa94fc9ab.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/54/evidence/3c4ffdf3515cbed2262d97cf1923c20a5426ebf888aed2dda08193844a597ea6.json)
- [runs-parameter-matrix](../../../assets/deliveries/CANDIDATES/54/evidence/78050066f387082da06e4b488d80466eddb20a73b84fc2f1db1b679edcd51b4a.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/54/evidence/60270a8adb38d9182b58a24a8ef3ecba17fbcd054b09ef37f2947e519320a613.json)
- [runs-parameter-precheck](../../../assets/deliveries/CANDIDATES/54/evidence/19995360e70df5962b49968f1038a1069347e543718c4ca86d2fd9754b428f5d.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/54/evidence/359d2876bf4904b5aa3db8d14604503e254d521474461bcd2ada1121cdc3feeb.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/54/evidence/000b30f761f3bdd1781a318546721fc844ebd9c13bf298a9b6fec2a1881f417e.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/54/evidence/ea691b76c6f35882443edbcddc577bf9bd7b73f3402972f71022e563dd50de44.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/54/evidence/75abac286337c37fb7c4b3aa8a38017dc94504c38bf9d9248bb86770c2c11507.json)
