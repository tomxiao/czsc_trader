# EX045 下跌过滤与买入确认历史窗口拆分

本轮完整对照完成，改善参数敏感性的总目标尚未达成。

只改变一个结构：下跌自相关历史均值固定使用中心120天；买入确认继续使用原可扰动窗口。原13项参数全部参与计算，H、退出优先级、再入场价格条件、执行费用与数据口径均保留。固定120天在13项数值参数之外，没有搜索窗口或选年份。

## 中心完整账户

| 中心 | 年化收益 | 全期回撤 | 闭合交易 | 四项目标 |
|---|---:|---:|---:|---|
| 原策略 | 16.1572% | 14.1599% | 112 | 通过 |
| 共用窗口 | 10.8889% | 21.2540% | 119 | 通过 |
| 固定均值窗口120天 | 10.8889% | 21.2540% | 119 | 通过 |

中心的买入确认窗口本来为120天，新旧共用/拆分中心的因果信号字段、完整每日账户及九项经济指标精确相同；新中心使用自己独立的原生完整账户身份，串行与spawn预检精确一致。

## 完整32点共同坐标

| 指标 | 原策略 | 共用窗口 | 拆分窗口 |
|---|---:|---:|---:|
| 较差一端年化收益Q10（%） | 5.8974 | 1.7843 | 1.5207 |
| 较差一端全期回撤Q90（%） | 30.5044 | 34.6163 | 34.7178 |
| 相对中心收益下降（百分点） | 10.2598 | 9.1046 | 9.3682 |
| 相对中心回撤增加（百分点） | 16.3446 | 13.3624 | 13.4638 |

完整13域、域宽标准化联合L2=5%、seed13、HALF_EVEN整数、LINEAR分位数以及原32坐标全部保留。原策略与共用窗口64点以原身份、原计划与血缘、完整原账户精确复用；新策略32点完整原生执行，零替换或删除。

共同坐标的原账户对照摘要：

- N0：32完整配对，收益改善1、下降31、相同0；回撤改善8、恶化24、相同0。
- N0-vs-B0-COUPLED：32完整配对，收益改善7、下降7、相同18；回撤改善7、恶化7、相同18。
- B0-COUPLED：32完整配对，收益改善1、下降31、相同0；回撤改善9、恶化23、相同0。

逐点四项经济判断、所有年度账户、现金/成交独立复核、完整信号与日历审计均在正式材料中。参数诊断不新增经济否决条件；“全部32点都达标”不作为新硬门。

## 结论与证据边界

完成判断：{'center_four_gates': True, 'absolute_q10_return_better': False, 'absolute_q90_drawdown_better': False, 'relative_return_degradation_better': True, 'relative_drawdown_degradation_better': True}

Fixed baseline split does not satisfy joint absolute/relative original-tail improvement. Preserve full negative panel; follow actual coupled-vs-fixed matched account/path evidence to choose next mechanism, without further baseline-window search or narrowed domain.

拆分窗口相对共用窗口，收益Q10下降0.2635个百分点，回撤Q90增加0.1015个百分点。相对原中心的退化虽小一些，但新中心本身收益较低、回撤较大，不能把这种相对数字当作参数稳健性改善。

原生账户互补核对覆盖全部32配对和中心：18个参数配对的目标持仓与完整逐日账户精确相同，14对改变；14对真实目标的首个分歧日与EX044一步探针的首个下一状态分歧日完全相同。中心经济字段及每日账户精确相同，原生decision_id因策略身份不同单列记录。五套基准账本在66个账户间精确相同。该诊断没有新增评价或现金重放。

互补诊断的初版曾错误访问请求对象的身份字段，中心初版曾把独立原生decision_id也要求相同；两次失败源码与显式修正版均正式保留。成功修正未改动冻结策略、参数几何或任何经济账户。

EX044一步探针在33条路径上出现36个下一状态差异，不能预测收益；本轮用真实完整账户检验。共用窗口拆分与原策略比较还包含既有均值过滤、BELOW再入场条件的结构差异；不据此声称单个参数的收益因果。

新增机制业务账户1、实际评估2；新增参数业务账户32、实际评估33；复用机制对照2、参数对照64。重复评估只用于串行/spawn一致性，不增加独立样本数。

数据已反复用于开发，未进行独立市场验证。技术FULL通过只代表引用、身份、来源和证据完整性；没有替代经济目标。RSCH S013阶段三。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/41/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/41/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0](../../../assets/deliveries/CANDIDATES/41/evidence/75d4e9840f332d7003e1c516120907aede97dc502a687c1a9194acdc890c2edc.json)
- [B0-TIME::B0-TIME-P00](../../../assets/deliveries/CANDIDATES/41/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME::B0-TIME-P01](../../../assets/deliveries/CANDIDATES/41/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME::B0-TIME-P02](../../../assets/deliveries/CANDIDATES/41/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME::B0-TIME-P03](../../../assets/deliveries/CANDIDATES/41/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME::B0-TIME-P04](../../../assets/deliveries/CANDIDATES/41/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME::B0-TIME-P05](../../../assets/deliveries/CANDIDATES/41/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME::B0-TIME-P06](../../../assets/deliveries/CANDIDATES/41/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME::B0-TIME-P07](../../../assets/deliveries/CANDIDATES/41/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME::B0-TIME-P08](../../../assets/deliveries/CANDIDATES/41/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME::B0-TIME-P09](../../../assets/deliveries/CANDIDATES/41/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME::B0-TIME-P10](../../../assets/deliveries/CANDIDATES/41/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME::B0-TIME-P11](../../../assets/deliveries/CANDIDATES/41/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME::B0-TIME-P12](../../../assets/deliveries/CANDIDATES/41/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME::B0-TIME-P13](../../../assets/deliveries/CANDIDATES/41/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME::B0-TIME-P14](../../../assets/deliveries/CANDIDATES/41/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME::B0-TIME-P15](../../../assets/deliveries/CANDIDATES/41/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME::B0-TIME-P16](../../../assets/deliveries/CANDIDATES/41/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME::B0-TIME-P17](../../../assets/deliveries/CANDIDATES/41/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME::B0-TIME-P18](../../../assets/deliveries/CANDIDATES/41/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME::B0-TIME-P19](../../../assets/deliveries/CANDIDATES/41/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME::B0-TIME-P20](../../../assets/deliveries/CANDIDATES/41/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME::B0-TIME-P21](../../../assets/deliveries/CANDIDATES/41/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME::B0-TIME-P22](../../../assets/deliveries/CANDIDATES/41/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME::B0-TIME-P23](../../../assets/deliveries/CANDIDATES/41/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME::B0-TIME-P24](../../../assets/deliveries/CANDIDATES/41/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME::B0-TIME-P25](../../../assets/deliveries/CANDIDATES/41/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME::B0-TIME-P26](../../../assets/deliveries/CANDIDATES/41/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME::B0-TIME-P27](../../../assets/deliveries/CANDIDATES/41/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME::B0-TIME-P28](../../../assets/deliveries/CANDIDATES/41/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME::B0-TIME-P29](../../../assets/deliveries/CANDIDATES/41/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME::B0-TIME-P30](../../../assets/deliveries/CANDIDATES/41/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME::B0-TIME-P31](../../../assets/deliveries/CANDIDATES/41/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [B0-COUPLED::N0-P00](../../../assets/deliveries/CANDIDATES/41/evidence/8b52feb7089cffe70d9021197a45f309b8906fe343fd85120036a82cbf9c004c.json)
- [B0-COUPLED::N0-P01](../../../assets/deliveries/CANDIDATES/41/evidence/cdd7dccfa0da7ae03b743a21e48a8aba760b0341f00e73f4e825e4ceb4c77080.json)
- [B0-COUPLED::N0-P02](../../../assets/deliveries/CANDIDATES/41/evidence/9fad10754f615e5c41fb1a718fbe9a6c045ebd8ac463c0f23a72e10666e1fed2.json)
- [B0-COUPLED::N0-P03](../../../assets/deliveries/CANDIDATES/41/evidence/00d30ba9690c9b92d17a628a50de0da836a1d7d106cff956ad88e2141f80cb6e.json)
- [B0-COUPLED::N0-P04](../../../assets/deliveries/CANDIDATES/41/evidence/aa2e4c590c9cd82dfeadb1063273d6b15b45eef2c93c7d9f90134c6e85985bec.json)
- [B0-COUPLED::N0-P05](../../../assets/deliveries/CANDIDATES/41/evidence/0884ee746fd76a00b22b33967195a3a387b25da8922c8be6de894d62df687dfe.json)
- [B0-COUPLED::N0-P06](../../../assets/deliveries/CANDIDATES/41/evidence/ee9def90c73145e9d990a235ba4f7e94fa580d624125fb9ab34818cbe5d107b9.json)
- [B0-COUPLED::N0-P07](../../../assets/deliveries/CANDIDATES/41/evidence/5f3461d47fb7b4c9338b8a8b479a0a6f49412ed0f2c70226bbd204296478d83f.json)
- [B0-COUPLED::N0-P08](../../../assets/deliveries/CANDIDATES/41/evidence/cb3769d22cbd8170797367c194b389f6e2dd708278d55ff3c26d6f9cb9d62cbc.json)
- [B0-COUPLED::N0-P09](../../../assets/deliveries/CANDIDATES/41/evidence/c94030e112bdb6cab54d27dc15199db42e9d886db62dc9dcdf062647bab92f0c.json)
- [B0-COUPLED::N0-P10](../../../assets/deliveries/CANDIDATES/41/evidence/b031978651fe123213477dae03ac9def22348a1116babd87fc02b5d1f629a7c9.json)
- [B0-COUPLED::N0-P11](../../../assets/deliveries/CANDIDATES/41/evidence/5d7013e4c8d1903694786398e486a6ed9fd38b88151acb618259d9cd22927552.json)
- [B0-COUPLED::N0-P12](../../../assets/deliveries/CANDIDATES/41/evidence/1ef7f4e1189b56d6d713e23f5b2fdfc78dc7794b8d793573a3fffb426acc0e6e.json)
- [B0-COUPLED::N0-P13](../../../assets/deliveries/CANDIDATES/41/evidence/4208ec1da81fb5ad0325bbd20e69797d241c329fc4c2e8e5b54931329868a422.json)
- [B0-COUPLED::N0-P14](../../../assets/deliveries/CANDIDATES/41/evidence/3ebf6975f4f6e6ccea30553b56a359a9e9c4e0f834e8e9c62e182a5d7e501326.json)
- [B0-COUPLED::N0-P15](../../../assets/deliveries/CANDIDATES/41/evidence/0bfc404ce11e85f66410b0faf1d26874114010ba3b332145a8e74980aec06047.json)
- [B0-COUPLED::N0-P16](../../../assets/deliveries/CANDIDATES/41/evidence/f31f4de50a96b5e9355fb6f0dd1fbbd78b5cf8e5849a70b2f30d4a6ec20cc42f.json)
- [B0-COUPLED::N0-P17](../../../assets/deliveries/CANDIDATES/41/evidence/b376761b8720466b3664ab93e17dadf1d90e9db2ef9d3e1623706af9473c4683.json)
- [B0-COUPLED::N0-P18](../../../assets/deliveries/CANDIDATES/41/evidence/75d3678c81ddb4aa77dba987df31d56dccb16e4670660e472ec51472cc5824c2.json)
- [B0-COUPLED::N0-P19](../../../assets/deliveries/CANDIDATES/41/evidence/b9650c9f8689c9484347ad76f569eb8bb762e3371a503a8b2ef28816cb40e106.json)
- [B0-COUPLED::N0-P20](../../../assets/deliveries/CANDIDATES/41/evidence/849028292cef252249bbcd8f6d23c3ed000ea86291126c5a37843058a5f83226.json)
- [B0-COUPLED::N0-P21](../../../assets/deliveries/CANDIDATES/41/evidence/303a8a774752297d889d0d9a2a0939195c815ae56797360f9b6b0259e7d48b63.json)
- [B0-COUPLED::N0-P22](../../../assets/deliveries/CANDIDATES/41/evidence/b3bec19f81c0612e3e95f947e57a5e56c30cefa30a2ff4cffd6d7e9e714ef5aa.json)
- [B0-COUPLED::N0-P23](../../../assets/deliveries/CANDIDATES/41/evidence/6394a851b6663be50542325af7af773e11dab1adeeb5b997bd4b179e4b25cf4d.json)
- [B0-COUPLED::N0-P24](../../../assets/deliveries/CANDIDATES/41/evidence/706bb3a28910bf56bfb44151f68c11c32c0d57bcdccc3c499b71ed47a59f1479.json)
- [B0-COUPLED::N0-P25](../../../assets/deliveries/CANDIDATES/41/evidence/b857b34d928c03ba8c71d4dacebf9829193ff1f185c7092482eecb4d91b232d5.json)
- [B0-COUPLED::N0-P26](../../../assets/deliveries/CANDIDATES/41/evidence/6db1a6097ab4bb15730ac10db206f27f6ece191326ef0686f6a7330ba187bab0.json)
- [B0-COUPLED::N0-P27](../../../assets/deliveries/CANDIDATES/41/evidence/0587291034ca9c3a77730bc739f94856a9b948edef3eb9de52633a7841c1ee0c.json)
- [B0-COUPLED::N0-P28](../../../assets/deliveries/CANDIDATES/41/evidence/dc7c9f99b5cf5bebe6aca5e86508fd1a07e867331f1ce74476cb21be5c29f3b0.json)
- [B0-COUPLED::N0-P29](../../../assets/deliveries/CANDIDATES/41/evidence/6f47f434e289e61283f04846a71a00473ee57cbaff1098a0d01d788de304920d.json)
- [B0-COUPLED::N0-P30](../../../assets/deliveries/CANDIDATES/41/evidence/bab9b8ec7926165a1072b529ca510d44fe69e262583d6d05a57df99ff588111d.json)
- [B0-COUPLED::N0-P31](../../../assets/deliveries/CANDIDATES/41/evidence/7c4db143900693ed02b62741881f2859593aca138472a8367cda06019a212513.json)
- [N0::N0-P00](../../../assets/deliveries/CANDIDATES/41/evidence/e3206a580b6d2976c34b5920932a528c21be43a9ec607a2604dd9b18615822a5.json)
- [N0::N0-P01](../../../assets/deliveries/CANDIDATES/41/evidence/e2b2e9574fd4d4fb8c3692aa76746ce94520043ec31f66897ed1c2435e9bcfee.json)
- [N0::N0-P02](../../../assets/deliveries/CANDIDATES/41/evidence/8bb00950771bf72ef8f14d0254d57f442d1699c1741f696b5f7d31203158e59f.json)
- [N0::N0-P03](../../../assets/deliveries/CANDIDATES/41/evidence/342d85547e43f4128f3600c8fe1823c30b581c75ad254145b0b4c723e67b82c6.json)
- [N0::N0-P04](../../../assets/deliveries/CANDIDATES/41/evidence/7c480d7d13d348e59b8ec014fd2d482959d209407acc37684c01f50e8c46e3d2.json)
- [N0::N0-P05](../../../assets/deliveries/CANDIDATES/41/evidence/dca2d6b0d535b4f750314d8d04006a0c49232786acbbf8400969be8ee8713dbb.json)
- [N0::N0-P06](../../../assets/deliveries/CANDIDATES/41/evidence/c1cce011ba90aa55ef1f0cd4e73d6a1113be60c3fba4cb8372dee96500bff973.json)
- [N0::N0-P07](../../../assets/deliveries/CANDIDATES/41/evidence/9c12499479460c16930e39bca7b3701fc62de7b6c4b8fd52440eb623f7bb950d.json)
- [N0::N0-P08](../../../assets/deliveries/CANDIDATES/41/evidence/8805f1ae108d2e4b1bdfdde64072ffa27a040755ff55c773e61941cb4aff8ea4.json)
- [N0::N0-P09](../../../assets/deliveries/CANDIDATES/41/evidence/ba0fe50e7b4e4d013ed9d8a078b1a35c899222e7c5ffa1048b2d09e2e027da0e.json)
- [N0::N0-P10](../../../assets/deliveries/CANDIDATES/41/evidence/4b301fb6b7d44b0e79abacf977e707b3cde8dfd43f0174c0104f5b883a03c46a.json)
- [N0::N0-P11](../../../assets/deliveries/CANDIDATES/41/evidence/c93025d1a10bc56881707941288167d296cc013197332ea76f2acf875309860c.json)
- [N0::N0-P12](../../../assets/deliveries/CANDIDATES/41/evidence/8f7b60ec3c0f82574d8713523d4012e8857f98b010ec662b5bb5b408c59e23ab.json)
- [N0::N0-P13](../../../assets/deliveries/CANDIDATES/41/evidence/1c05dbe629d0d2926de9c2dad22f602b7a9280971480269436c5036f178646bd.json)
- [N0::N0-P14](../../../assets/deliveries/CANDIDATES/41/evidence/360457822626b1bb4896f5f064d3426fb58a8521bd0aba98310a724a4c037e78.json)
- [N0::N0-P15](../../../assets/deliveries/CANDIDATES/41/evidence/d1825f20c5a9cf07cc927200ab2092178216de44adff60ca08513e45f1c9ecfb.json)
- [N0::N0-P16](../../../assets/deliveries/CANDIDATES/41/evidence/6370328b211680322b2b571d50f4daed155cdd523aa6975b03202184cad12426.json)
- [N0::N0-P17](../../../assets/deliveries/CANDIDATES/41/evidence/f40561df508e086d58893b60d51cdb1faf0aa82f914e93bbfd51f7740c0dc4b6.json)
- [N0::N0-P18](../../../assets/deliveries/CANDIDATES/41/evidence/d54f331cd85edb8c8f448b590f1fe2caecc0170e77a5c94065cafe70a2197eb1.json)
- [N0::N0-P19](../../../assets/deliveries/CANDIDATES/41/evidence/3455538cc7ffe4320abfe2f30c74a91424fd4c7a02c824b8292a7030cbdb3dcd.json)
- [N0::N0-P20](../../../assets/deliveries/CANDIDATES/41/evidence/a5ae379efe590a0b4e9e602a6e199e7ab9e107d79c0ab556a70f17f70b002bc0.json)
- [N0::N0-P21](../../../assets/deliveries/CANDIDATES/41/evidence/73e91189f43a3b80b2f527f93f1ce317a6d146c03a4d6e5e0b71ec6e2f5bad22.json)
- [N0::N0-P22](../../../assets/deliveries/CANDIDATES/41/evidence/f0339e745a493c8ab1856e2267f4a653a605d32a208d50a93ce09eecaa255fa0.json)
- [N0::N0-P23](../../../assets/deliveries/CANDIDATES/41/evidence/20bb389c447b4fe0d262cb37772960246e7856a2cc255218e0535d45d499b6dd.json)
- [N0::N0-P24](../../../assets/deliveries/CANDIDATES/41/evidence/453f3c3503e7005ff36d6a633c99e9cd586a9228b81c56c59b1c52298fc0d154.json)
- [N0::N0-P25](../../../assets/deliveries/CANDIDATES/41/evidence/ffd5fcc9ff532f48c62c45bb927d6d31df5c95e8ee952682fa18977165d6c2e7.json)
- [N0::N0-P26](../../../assets/deliveries/CANDIDATES/41/evidence/26d348f9194208e893ed17f20c48b449c7d40beeaf24e8b5f60509eb31c8f64f.json)
- [N0::N0-P27](../../../assets/deliveries/CANDIDATES/41/evidence/5e8b07fa16d93c3ebf3e77d6b30c646690a7cf37d873495801575fddeed80ebd.json)
- [N0::N0-P28](../../../assets/deliveries/CANDIDATES/41/evidence/c3bd840aa1fb5af454db4519da0baace496bfcc49cb9d1881e46f9250331fd52.json)
- [N0::N0-P29](../../../assets/deliveries/CANDIDATES/41/evidence/4c4d198f0afc166f305997dd03ccbeaaafdf1d06655341b7232e395995327f5f.json)
- [N0::N0-P30](../../../assets/deliveries/CANDIDATES/41/evidence/2c131d39e09be666dd4ec32c63054708407e3f4e0097134e322a850e4b2eadcd.json)
- [N0::N0-P31](../../../assets/deliveries/CANDIDATES/41/evidence/35713b73c61f67fb4ff363ce426139b42c1aac04b6e4a30736adcdc048d5fd4c.json)
- [plan](../../../assets/deliveries/CANDIDATES/41/evidence/b4afd910800c80ccf30563a9f2fb6fad22ad9dc3ba89cf06d52c1bf3e21e334e.json)
- [previous44-native-diagnosis](../../../assets/deliveries/CANDIDATES/41/evidence/28965bd4fdceef53981e5410315ba9dec6573ceb79b168273614dbba87323127.json)
- [geometry](../../../assets/deliveries/CANDIDATES/41/evidence/bc78e054f7819621c9e5786bc7dae9615e48a6fbd81e17e51e0d92e59d07d243.json)
- [native-pair-complete](../../../assets/deliveries/CANDIDATES/41/evidence/2fb7d89c55d09e9a2096fe86bdd57892a5ed9283782d6ead44be3a60d76a3982.json)
- [native-pair-source-history](../../../assets/deliveries/CANDIDATES/41/evidence/e9e2457198bb89e30ac3e8f9488c9827101f01cc165039d2c71b7d03d4921881.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/41/evidence/b1a25e95c5e6f4ea1db93ac90d10319f2d7c1c3f013b2a4db3f550d3b7251eed.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/41/evidence/e0b5e977149f49d9142133b2095cea2ac4995c48871e6ae75714bd241b8b6d7c.json)
- [protocols-native-pair-references](../../../assets/deliveries/CANDIDATES/41/evidence/3199b8649de7a08719b1bc965a37be768077173a19767da4415da26adde07ad0.json)
- [protocols-parameter-analysis-references](../../../assets/deliveries/CANDIDATES/41/evidence/cfcd3cbaf056d5fa7dac7c33629f27fa96953fdfb57623af819788edc8994136.json)
- [protocols-parameter-helper-checks](../../../assets/deliveries/CANDIDATES/41/evidence/b103d0a8f533011e91a4da2b99329dbd68934c5686e23a14556e86849d7b3102.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/41/evidence/6346f625b18936f1527d57123bc91577f4bfb53bcef7a47dd0430a35fa5e81d6.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/41/evidence/d4a7d00373cb69c549bb5520f2cdb1453974feaac152c0a7a4f173bd91281533.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/41/evidence/28963916a78f0aa5f700d175067c9fa74b6b2624b8c1d4328be968a300f26f37.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/41/evidence/730027c2c065ad8ef0af6b0e2270412aa8eba82d94f7aa9341653d213f408039.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/41/evidence/5e89caacc5a610e2b4c68f5081bfe40e1fa5f7c5378cae25fe69f28d7f447272.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/41/evidence/11276aa067200869ec49c0ab027386f0b5f1c41f8ab86d4bda751b73ec897125.json)
- [runs-parameter-matrix](../../../assets/deliveries/CANDIDATES/41/evidence/4901d3259a9a3fffe7b6a9d95e0d38724d3e05023d3eaf19cb0fac40089faff5.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/41/evidence/b342fd9686ee193131fbc9adb6c77f73726de9a0ae8f2e0e400d06c22aaa7621.json)
- [runs-parameter-precheck](../../../assets/deliveries/CANDIDATES/41/evidence/1c6f11c658c4326f0796c31420fcd29f53ee3169f0d8eaff3b3859ba232cc979.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/41/evidence/c06db43512e3f802a091e28362c4d9ade3a8f69129b079c4bdd153dec2482438.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/41/evidence/b0a9012d8c5cd6b3174de3ba5b8b8dd6ff85658a072d912ae3220bd6bef70a2a.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/41/evidence/53dbe649a48bd0adcf86d099295b6223817343a67cd951abd663f16c4809364e.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/41/evidence/09e8a4ce1f8a87f643aad1465c33ed4e9781a1273581ec315e7b1faee867a2ab.json)
