# EX044 完整参数路径的触发与状态传播诊断

本轮诊断完成；改善参数敏感性的总目标尚未达成。66个不同已有原生账户全部精确复用，零新增账户、零资金重放。

## 已有经济反证

| 完整32点指标 | 原策略 | EX043新策略 |
|---|---:|---:|
| 较差一端年化收益（Q10） | 5.8974% | 1.7843% |
| 较差一端全期回撤（Q90） | 30.5044% | 34.6163% |
| 相对中心收益下降 | 10.2598% | 9.1046% |
| 相对中心回撤增加 | 16.3446% | 13.3624% |

新中心虽然四项目标达标，绝对尾部更差；相对中心下降较少不能代替尾部改善。既有收益未重跑。

## 当天触发与此前状态

把当天条件与决策前状态各自换一次，观察能否复现参数扰动账户当天决定。A为中心条件/中心状态；B为扰动条件/中心状态；C为中心条件/扰动状态；D为真实扰动条件/扰动状态。只算一步，B/C不向下一天传播。

| 目标仓位分类 | 原策略32点天数 | 新策略32点天数 |
|---|---:|---:|
| 四种决定都相同 | 45269 | 44589 |
| 换当日条件足以复现D | 2291 | 2240 |
| 换已有状态足以复现D | 2778 | 3307 |
| 任选一种替换都足以复现D | 542 | 592 |
| 两种合用才复现D或多值残差 | 489 | 514 |
| 实际A=D但单次替换有差异 | 983 | 1110 |

每日完整target及target/reason分类、信号年2019—2026、执行年2020—2026、空类别、连续区间、首分歧和尾状态都在正式诊断材料中保留。原32点和新32点是同一路市场的依赖路径，不是64个独立样本。

持仓/路线/持有天数相同、决策所需完整状态不同的天数：原策略0，新策略9397。新策略自带入场价格锚与退出类别记忆，不能从物理持仓相同直接推断后续决定相同。这个计数描述记忆状态，不证明其造成盈利或亏损。

“当日条件足以复现D”并不表示状态完全无影响；target/reason有多个取值。13项参数一起扰动，本轮不能确定某一个参数的单独收益因果。

## 共用历史窗口检查

33条新策略路径共53988天，只把下跌自相关历史均值窗口固定为中心120天。目标仓位改变36天；仓位或最终原因改变38天；完整下一状态改变36天；19条账户完整下一状态始终不变。

买入确认窗口仍是原13维中的有效参数；固定120天为结构选择，不删除参数维度。未搜索窗口、未延长数据、未计算修改后的账户利润。每条路径全部下一状态相同才可用归纳法排除该面板上的目标仓位/状态路径改变；最终原因还须独立核对。存在变化只能作为后续对照线索。

## 结论与下一步

Fixed120 decoupling changes observed steps; this is a mechanism lead only. Next controlled successor should preserve13domain/coordinates, activate confirmationL only in original score, keep baseline120 fixed structurally; first full center4gates then all32matched points if qualified. No profit claim from probe.

仍沿用四项经济目标、完整13维参数域及原32点共同坐标，不新增经济否决条件。总目标继续；技术PASS仅表示材料/身份/完整路径核验通过。RSCH S013阶段三，不涉及生产、PTE、冻结、推送或阶段推进。

发布v1因同一内容不同名称的引用比较失败；v2只修正内容去重，完整失败和纠正证据保留，零账户重跑。

## 正式证据引用

- [B0-TIME-center](../../../assets/deliveries/CANDIDATES/40/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-TIME-P00](../../../assets/deliveries/CANDIDATES/40/evidence/2a17b21d364d6e36cba15fefa9020c1504d9c0e20419ccd9d0affd38ccf11476.json)
- [B0-TIME-P01](../../../assets/deliveries/CANDIDATES/40/evidence/798fbb3f120942c151d779903d84d6de0e219800fa62dfe7230a3a85bf18b688.json)
- [B0-TIME-P02](../../../assets/deliveries/CANDIDATES/40/evidence/426b7382f2d8cd4f2a420d3817c5862f6628c678bc62b103d49bff715e9c3e37.json)
- [B0-TIME-P03](../../../assets/deliveries/CANDIDATES/40/evidence/ae32c030a2b7c61dd86c050ec22d178724dd3adaef19c47122a8cbf78352b47f.json)
- [B0-TIME-P04](../../../assets/deliveries/CANDIDATES/40/evidence/e7e50e6c122a2101bd6ac86f8a6a1d3b52e95064a2c3e36660137908bf818130.json)
- [B0-TIME-P05](../../../assets/deliveries/CANDIDATES/40/evidence/f29488548e9bf49436ed2b1f6da3db9fa81fcbfe4e7af54097d3eab656d3bf2c.json)
- [B0-TIME-P06](../../../assets/deliveries/CANDIDATES/40/evidence/9b25ea2e58dfece70898bdc3fc1caf2da7c76c9d627bb6be461dac7e87ee7bc1.json)
- [B0-TIME-P07](../../../assets/deliveries/CANDIDATES/40/evidence/0c2e0127bc6688e3d756f34448c91aed6af605ebf83d2d32da85c977bbd8f26f.json)
- [B0-TIME-P08](../../../assets/deliveries/CANDIDATES/40/evidence/7629cd0d00d12d660dad69bc2f99f485aa792d48b1bbefaff63273962ea7e147.json)
- [B0-TIME-P09](../../../assets/deliveries/CANDIDATES/40/evidence/561d5fbe5b13905942229136063aeedaf9e3bd1b0335d390dd45099827563822.json)
- [B0-TIME-P10](../../../assets/deliveries/CANDIDATES/40/evidence/792091e15396969a0fe616bc9712b1fd0f3aa1413498df8b5b1eaafc3b633cd1.json)
- [B0-TIME-P11](../../../assets/deliveries/CANDIDATES/40/evidence/e4ed01f394116dbed5b6cae89365ca9f2c245fc5f744286bbfa6c470a95d1309.json)
- [B0-TIME-P12](../../../assets/deliveries/CANDIDATES/40/evidence/1823fc2fcc62e4f0ec96703495ee2ed78c19593e9c276af539fce6c825e1e76b.json)
- [B0-TIME-P13](../../../assets/deliveries/CANDIDATES/40/evidence/df6026c13464264190b7d85bcf57c54a3c20c1b29787c5eb2a998073fd8c62ce.json)
- [B0-TIME-P14](../../../assets/deliveries/CANDIDATES/40/evidence/980fb6ccc1ae7fa1c28e071747b6a2db526a4541e7f07f5ad82129eaf9dbb76e.json)
- [B0-TIME-P15](../../../assets/deliveries/CANDIDATES/40/evidence/f6e3b4db7397729d6b25e4f448d67a5c829a20bdc796e5bc94f8f3225a519e2a.json)
- [B0-TIME-P16](../../../assets/deliveries/CANDIDATES/40/evidence/eeaa368ef2091d7b0a37158c56f1b463cbfa70e0b950daf79153764dc1a48cb9.json)
- [B0-TIME-P17](../../../assets/deliveries/CANDIDATES/40/evidence/d7d0a6d212269efa36028175454b984fa7a5218b9814069f987185c47e6b7495.json)
- [B0-TIME-P18](../../../assets/deliveries/CANDIDATES/40/evidence/6f566a31016b9f8f5e5c39bbeec80da94391910af15aa8fed00095135a5ca14d.json)
- [B0-TIME-P19](../../../assets/deliveries/CANDIDATES/40/evidence/40934ec002aad435489d4f2359f30897d3f3901b47f72224b3b75b8c571a4962.json)
- [B0-TIME-P20](../../../assets/deliveries/CANDIDATES/40/evidence/aaa3dceda2655956b3439e90a76c448d3d76446a7b0841724d192729bd4be898.json)
- [B0-TIME-P21](../../../assets/deliveries/CANDIDATES/40/evidence/a3feaa09bcc24f43a2ee4fca9da21519b9e53a0bda8dbb2df3ff76a8808f6680.json)
- [B0-TIME-P22](../../../assets/deliveries/CANDIDATES/40/evidence/34c50144cd8cc83be92ad028741b47ab958ce2853b677af683c1b834e8076ca6.json)
- [B0-TIME-P23](../../../assets/deliveries/CANDIDATES/40/evidence/78234b5f2d2a90052f09e6cd0512ac15da1b57a34abf9404cdbda434328592da.json)
- [B0-TIME-P24](../../../assets/deliveries/CANDIDATES/40/evidence/81830f8d1c5e411a0daa7984ba298e490706d5d113f99e408e18af1b930c56b4.json)
- [B0-TIME-P25](../../../assets/deliveries/CANDIDATES/40/evidence/4131f5fa795b8e9c148bbeb34b4e92743cc392469f73fd28c8a677f8fae5f585.json)
- [B0-TIME-P26](../../../assets/deliveries/CANDIDATES/40/evidence/cc91a3ef429b37c3e24103de959c0e12a6fb8d9ea7e0733e997a5b68a0a059a6.json)
- [B0-TIME-P27](../../../assets/deliveries/CANDIDATES/40/evidence/f7560a75c6e197752ab29fe313c037a5d99485f12bfb52eb0ec91be9a117c663.json)
- [B0-TIME-P28](../../../assets/deliveries/CANDIDATES/40/evidence/231c844524e94a90aa42c37fcfe4cc4d79bc97e33e012415fef56355fc929051.json)
- [B0-TIME-P29](../../../assets/deliveries/CANDIDATES/40/evidence/137cadf7c3a8bdc94f65b8a62d804d3083ab415ddb50114dac120653ba2cad9d.json)
- [B0-TIME-P30](../../../assets/deliveries/CANDIDATES/40/evidence/892e6c3a65a2d591cc72ed82d8dfb985d956c2f0cee0cde2aa54058204cd7b21.json)
- [B0-TIME-P31](../../../assets/deliveries/CANDIDATES/40/evidence/9b09a6ef303d404e7a1c780a55cd075dbb4c08d7cda4ca8ab0962c2fb31c3c86.json)
- [N0-center](../../../assets/deliveries/CANDIDATES/40/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [N0-P00](../../../assets/deliveries/CANDIDATES/40/evidence/8b52feb7089cffe70d9021197a45f309b8906fe343fd85120036a82cbf9c004c.json)
- [N0-P01](../../../assets/deliveries/CANDIDATES/40/evidence/cdd7dccfa0da7ae03b743a21e48a8aba760b0341f00e73f4e825e4ceb4c77080.json)
- [N0-P02](../../../assets/deliveries/CANDIDATES/40/evidence/9fad10754f615e5c41fb1a718fbe9a6c045ebd8ac463c0f23a72e10666e1fed2.json)
- [N0-P03](../../../assets/deliveries/CANDIDATES/40/evidence/00d30ba9690c9b92d17a628a50de0da836a1d7d106cff956ad88e2141f80cb6e.json)
- [N0-P04](../../../assets/deliveries/CANDIDATES/40/evidence/aa2e4c590c9cd82dfeadb1063273d6b15b45eef2c93c7d9f90134c6e85985bec.json)
- [N0-P05](../../../assets/deliveries/CANDIDATES/40/evidence/0884ee746fd76a00b22b33967195a3a387b25da8922c8be6de894d62df687dfe.json)
- [N0-P06](../../../assets/deliveries/CANDIDATES/40/evidence/ee9def90c73145e9d990a235ba4f7e94fa580d624125fb9ab34818cbe5d107b9.json)
- [N0-P07](../../../assets/deliveries/CANDIDATES/40/evidence/5f3461d47fb7b4c9338b8a8b479a0a6f49412ed0f2c70226bbd204296478d83f.json)
- [N0-P08](../../../assets/deliveries/CANDIDATES/40/evidence/cb3769d22cbd8170797367c194b389f6e2dd708278d55ff3c26d6f9cb9d62cbc.json)
- [N0-P09](../../../assets/deliveries/CANDIDATES/40/evidence/c94030e112bdb6cab54d27dc15199db42e9d886db62dc9dcdf062647bab92f0c.json)
- [N0-P10](../../../assets/deliveries/CANDIDATES/40/evidence/b031978651fe123213477dae03ac9def22348a1116babd87fc02b5d1f629a7c9.json)
- [N0-P11](../../../assets/deliveries/CANDIDATES/40/evidence/5d7013e4c8d1903694786398e486a6ed9fd38b88151acb618259d9cd22927552.json)
- [N0-P12](../../../assets/deliveries/CANDIDATES/40/evidence/1ef7f4e1189b56d6d713e23f5b2fdfc78dc7794b8d793573a3fffb426acc0e6e.json)
- [N0-P13](../../../assets/deliveries/CANDIDATES/40/evidence/4208ec1da81fb5ad0325bbd20e69797d241c329fc4c2e8e5b54931329868a422.json)
- [N0-P14](../../../assets/deliveries/CANDIDATES/40/evidence/3ebf6975f4f6e6ccea30553b56a359a9e9c4e0f834e8e9c62e182a5d7e501326.json)
- [N0-P15](../../../assets/deliveries/CANDIDATES/40/evidence/0bfc404ce11e85f66410b0faf1d26874114010ba3b332145a8e74980aec06047.json)
- [N0-P16](../../../assets/deliveries/CANDIDATES/40/evidence/f31f4de50a96b5e9355fb6f0dd1fbbd78b5cf8e5849a70b2f30d4a6ec20cc42f.json)
- [N0-P17](../../../assets/deliveries/CANDIDATES/40/evidence/b376761b8720466b3664ab93e17dadf1d90e9db2ef9d3e1623706af9473c4683.json)
- [N0-P18](../../../assets/deliveries/CANDIDATES/40/evidence/75d3678c81ddb4aa77dba987df31d56dccb16e4670660e472ec51472cc5824c2.json)
- [N0-P19](../../../assets/deliveries/CANDIDATES/40/evidence/b9650c9f8689c9484347ad76f569eb8bb762e3371a503a8b2ef28816cb40e106.json)
- [N0-P20](../../../assets/deliveries/CANDIDATES/40/evidence/849028292cef252249bbcd8f6d23c3ed000ea86291126c5a37843058a5f83226.json)
- [N0-P21](../../../assets/deliveries/CANDIDATES/40/evidence/303a8a774752297d889d0d9a2a0939195c815ae56797360f9b6b0259e7d48b63.json)
- [N0-P22](../../../assets/deliveries/CANDIDATES/40/evidence/b3bec19f81c0612e3e95f947e57a5e56c30cefa30a2ff4cffd6d7e9e714ef5aa.json)
- [N0-P23](../../../assets/deliveries/CANDIDATES/40/evidence/6394a851b6663be50542325af7af773e11dab1adeeb5b997bd4b179e4b25cf4d.json)
- [N0-P24](../../../assets/deliveries/CANDIDATES/40/evidence/706bb3a28910bf56bfb44151f68c11c32c0d57bcdccc3c499b71ed47a59f1479.json)
- [N0-P25](../../../assets/deliveries/CANDIDATES/40/evidence/b857b34d928c03ba8c71d4dacebf9829193ff1f185c7092482eecb4d91b232d5.json)
- [N0-P26](../../../assets/deliveries/CANDIDATES/40/evidence/6db1a6097ab4bb15730ac10db206f27f6ece191326ef0686f6a7330ba187bab0.json)
- [N0-P27](../../../assets/deliveries/CANDIDATES/40/evidence/0587291034ca9c3a77730bc739f94856a9b948edef3eb9de52633a7841c1ee0c.json)
- [N0-P28](../../../assets/deliveries/CANDIDATES/40/evidence/dc7c9f99b5cf5bebe6aca5e86508fd1a07e867331f1ce74476cb21be5c29f3b0.json)
- [N0-P29](../../../assets/deliveries/CANDIDATES/40/evidence/6f47f434e289e61283f04846a71a00473ee57cbaff1098a0d01d788de304920d.json)
- [N0-P30](../../../assets/deliveries/CANDIDATES/40/evidence/bab9b8ec7926165a1072b529ca510d44fe69e262583d6d05a57df99ff588111d.json)
- [N0-P31](../../../assets/deliveries/CANDIDATES/40/evidence/7c4db143900693ed02b62741881f2859593aca138472a8367cda06019a212513.json)
- [plan](../../../assets/deliveries/CANDIDATES/40/evidence/e91aa12a9a8b2d9c02128af431c73dfefc76e59dbc103574e5fbc51fde50a892.json)
- [method](../../../assets/deliveries/CANDIDATES/40/evidence/2c82b71ae1be55d8d2e1b42a534c15a2e5f04c8a9351929d9f205e577a3a07f9.json)
- [publication-failure](../../../assets/deliveries/CANDIDATES/40/evidence/82e296a6bda2586ef780abbbe394f345865abfe59d83b7c56b4074ecbf05538d.json)
- [publication-focused-checks](../../../assets/deliveries/CANDIDATES/40/evidence/f69131c523474228eadc9f70e5a469b8bbd2d2c75ef4454a9da536bbe319036f.json)
- [publication-correction](../../../assets/deliveries/CANDIDATES/40/evidence/8b340bcbd26c4482aed569a994dfb38f41b67ee8f5bf7c40966d38ad6df25bdc.json)
- [original-publication-reproduction](../../../assets/deliveries/CANDIDATES/40/evidence/5a4e6c61c1d770832aacd7c7489c6caeec0fe4c670e71dd338f38ff38ce36bc0.json)
- [existing-economic-analysis](../../../assets/deliveries/CANDIDATES/40/evidence/e11c0a57bf7624f459b05a81eff6b1383b0a261f6b719841323b9da21922f786.json)
- [complete-native-input-state](../../../assets/deliveries/CANDIDATES/40/evidence/28965bd4fdceef53981e5410315ba9dec6573ceb79b168273614dbba87323127.json)
- [focused-checks](../../../assets/deliveries/CANDIDATES/40/evidence/234c177cfd149e9f58a399d39addadd61446435d6dcebc2307e096bd1462114d.json)
- [research-decision](../../../assets/deliveries/CANDIDATES/40/evidence/39e933d292a279ed323ef4d9067ba9187d7d9689c6a88811358cb2453749c6e4.json)
- [research-conclusion](../../../assets/deliveries/CANDIDATES/40/evidence/39e933d292a279ed323ef4d9067ba9187d7d9689c6a88811358cb2453749c6e4.json)
- [reproduction](../../../assets/deliveries/CANDIDATES/40/evidence/3482ae927d149d67fd5aeb65f27f92489b14ef83ef86c58829c8fbbd52467fc8.json)
