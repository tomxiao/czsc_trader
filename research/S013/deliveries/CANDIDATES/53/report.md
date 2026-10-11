# EX057 局部中性以上确认支持恢复相关资格

本轮对照完成，改善参数敏感性的总目标尚未达成。

仅在空仓、当前下跌路线、上次最终下跌到期退出信号价低于其入场信号价时，允许原相关性不达标机会恢复资格；恢复要求收盘高于开盘，且原综合确认分数达到固定数学中性点0。之后仍须原区间、动量和买入确认全部通过。原相关性通过的机会不增加方向或零分限制；持仓日没有例外。

本轮只比EX055增加原确认分数>=0条件。0是原加权经验排名分数的数学中性点，不是预测收益或费用覆盖线；为原相关性失格的额外机会要求支持性确认，原相关合格机会仍沿用原阈值。分数等于0允许例外，原阈值更高时仍须通过原确认。该假设是在看到旧结果后提出，选择偏差明确披露，不能预称修复2023。

上下文跨空仓失败、确认拒绝和原路线变化保留，任意路线成功发出入场信号清空。退出分类使用信号价格，不能当作实际亏损；实际成交重试不重置持仓年龄或信号锚点。全部持仓退出、优先级、原13数值中心和全域、同32坐标、暖启动、费用和数据保持。

## 完整账户对照

| 对照 | 候选 | 年化收益 | 全期回撤 | 闭合交易 | 2022收益 | 2023收益 | 四项目标 |
|---|---|---:|---:|---:|---:|---:|---|
| 原策略 | C2132 | 16.1572% | 14.1599% | 112 | +12.1687% | +0.2841% | 通过 |
| 历史均值相关+CLOSE门 | C4900 | 10.8889% | 21.2540% | 119 | +9.4200% | +0.5491% | 通过 |
| 旧局部BODY恢复 | C7980 | 16.8663% | 14.4246% | 118 | +18.9454% | -0.0252% | 未通过 |
| 新局部确认支持恢复 | C8580 | 16.4369% | 15.3601% | 115 | +18.9463% | -1.1162% | 未通过 |

新中心：年化收益通过；各自然年回撤通过；闭合交易频率通过；基准亏损年份仍盈利未通过。

三个旧账户按完整身份、实际请求、载荷、依赖、血缘和原生序列化逐字认证后复用，不新增评价。C7980未达标，仍作为旧中心机制诊断，不能成为新参数面板或新增否决条件。串行与spawn信号及策略、基准双方五账本精确一致；全部成交、费用、现金、状态、锚点和独立公式核对通过。技术PASS只表示这些证据核对通过。

相对原中心，目标仓位不同19天，原因不同27天；首个仓位分歧2021-02-02 00:00:00。

固定相同决策前状态时，原资格包含于新资格、新资格包含于旧BODY恢复资格；该逻辑包含关系不能推广为完整交易或资金路径的包含关系，因为早一次入场就会改变后续占仓、上下文和资金。未运行本轮原路径真实机会投影；旧EX055 BODY-only投影不能当作本轮实际交易数或利润。恢复分支入场要求分数>=max(0,原阈值)，负阈值在此分支被条件性屏蔽；原相关合格分支保留原阈值的完整作用。原13仍全局有效，但不能宣称各分支的有效自由度不变。

新中心未达原四项经济目标，32点参数实验不适用；新增及复用参数账户均为零。

## 最强反证与限制

EX055局部BODY恢复虽年化16.8663%、118笔、2022盈利18.9454%，2023仍亏损0.0252%，必须原样认定未达标。全取消下跌相关限制曾有217笔，却2022亏损3.2809%、2023亏损9.1143%、全期回撤29.5711%。局部资格恢复同样可能增加坏交易；确认评分达到中性也不保证持续反转。旧7个恢复成交只有2个分数非负（一亏一赢），2023两笔均负，是已见结果影响选择的最强反证，不能删去它们旧盈亏预测新收益。旧双价格方向对照已在完整中心证明业务信号等价，未追加金融账户。

原相关CLOSE和BODY局部门均只剩108笔，未达到最低110笔；本轮不是抑制全部原合格买点。原策略2023只有+0.2841%，低价到期后重入来源贡献+2.3049个百分点，不能把这类信号统称亏损交易或删除旧盈利预测新收益。历史均值+CLOSE中心虽达标，其参数较差一端收益和回撤均劣于原C2132；中心改善不能替代完整参数检验。

机制在实际账户前声明，纯runtime、独立oracle、原13域辅助和33合成路径核验完整保留，包括失败源和修正。反复使用已见S013开发池，未作独立市场验证；FULL只检验证据完整性。RSCH阶段三，不推进其他阶段。

完成判断：{'center_four_gates': False}

本机制未满足原联合目标；留存反证，依据完整实际路径继续研究，保持原目标和原参数域。

新增机制业务账户1、实际评价2、旧中心复用3；新参数业务账户0、实际评价0、旧参数复用0。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/53/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-COUPLED](../../../assets/deliveries/CANDIDATES/53/evidence/3aa193c1e7a1ae35f96dec4a7dbf88167fd2ecfd8b9aad14b4e662bd4483ddb7.json)
- [B0-RAW-RECOVERY](../../../assets/deliveries/CANDIDATES/53/evidence/90462cbc1be6b86ac691bee3f2f921d6c3db33e6e6b1d9ca12fd26b8e008707b.json)
- [N0](../../../assets/deliveries/CANDIDATES/53/evidence/8d2f89d207c3e72108e9cc68e43a7abc5a839ef9a9ab5f6201630e848bcdd99e.json)
- [plan](../../../assets/deliveries/CANDIDATES/53/evidence/95cb18e522ce5cb326649a097fc607fa5a2fdf0530b11d43a8c4893f4209f1ea.json)
- [raw-below-reentry-method](../../../assets/deliveries/CANDIDATES/53/evidence/50de04a99146eeed741857a91616e6988cd97fc17801d979e9f39b80990387b6.json)
- [geometry](../../../assets/deliveries/CANDIDATES/53/evidence/235a1df6b236c0687f8cf36f93f851975338e72e69002e964b1912c8ed3d4bc5.json)
- [runtime-pure-prototype](../../../assets/deliveries/CANDIDATES/53/evidence/acd7203fb1d6a550df4f6232ef4bed8e851751b495026eefd5ea3e53431ac52d.json)
- [oracle-pure-prototype](../../../assets/deliveries/CANDIDATES/53/evidence/6d45a76991a375722cc2c749c558c1551529e08110e62c93768d93e11d0d9d12.json)
- [parameter-checks-pure-prototype](../../../assets/deliveries/CANDIDATES/53/evidence/0e673b193a8919a265b6bdc2e052a533a562d3470b846e3bcefe67f29f6286b9.json)
- [crosscheck-pure-prototype](../../../assets/deliveries/CANDIDATES/53/evidence/970cfcccf9b2c3d7e71cb022a1d921db57355586858a1b9dc070a251b8052c24.json)
- [protocols-decision](../../../assets/deliveries/CANDIDATES/53/evidence/1dfa0ed7bc4180c3bf933c79ab6664e80e1ca0fbf3f6c9b25a15725c5b4c1eb8.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/53/evidence/967bbba357dbe507e3ce11ec66e076f8da8469f7a5083a9fb6336e3e674d9e4b.json)
- [protocols-method-reference](../../../assets/deliveries/CANDIDATES/53/evidence/672e05f2d1ec3bdf8485a3fcc81083318acf4a1dcdd2743d53a4c1fd8158aa96.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/53/evidence/7dd80f92d407e2c91185006f3978bcb2d27686232a05e6f3b138a1c62eb09271.json)
- [protocols-plan-reference](../../../assets/deliveries/CANDIDATES/53/evidence/b9f4895f19ca14d8e3fcd442def8c9fd5a79c6cff963f4ee3918778110404e50.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/53/evidence/a6366344f61f745dfd7541ab8c9cd7564a4845440cfa9d587a2143d4ace1d094.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/53/evidence/8b007a08c505ff547d0d6f34fb34ca3fcbf6daa0538426489b82d44d8b079a54.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/53/evidence/ec1614da755df0938be8cabac3a9464798e1a8243102884e99b58a086bbea369.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/53/evidence/0f7ab72ce33e8e729952c353ee687f813c842418e75d98ad75e7c1cad48ce95b.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/53/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/53/evidence/296519891f23c8f1dd5527f5ff1bd9c7f496fa469f4aae1bcf62ed319c12dc88.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/53/evidence/e80bc9799034285a17136a2d967c5cc0e83c7371466cad1cc47d6fafd4066396.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/53/evidence/d89652b37c0aa770b106d16199797f6b156eb70c90ba09214fec392d127fa3cd.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/53/evidence/b835fc4bcc97773a6acfee96bb6fdc37b218dfa660418b92ac381744a2cd2f0c.json)
