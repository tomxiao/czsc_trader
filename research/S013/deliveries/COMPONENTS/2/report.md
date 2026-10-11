# EX060：按扰动绝对收益与回撤重新审视C2132，并回到阶段二检验风险组件

本轮证据审计与组件验证已完成；“达标且稳健”的策略目标仍未达成。原四项经济要求保持不变。优先提高收益Q10、降低全区间回撤Q90，不再要求相对中心的退化量同步改善，也未新增硬门。

## 1. 已有研究取得了实际改善，但还不够

原S013开发池2020-01-02至2026-09-30，共1636个交易日，100万元，每侧费用0.1%，固定1% LimitBuyHold基准，HFQ_RESEARCH后复权及2019-12-31锚点。以下不是EX059共同区间比较，不能与该比较的数值混用。
Q10和Q90由原13维完整参数域上的同32组5%标准化总L2扰动计算，seed13，linear分位数。它们表示这些固定扰动样本较差一端的表现，并不是未来发生概率或收益保证。

| 指标 | C2132 | C8880（EX058） |
|---|---:|---:|
| 中心净年化收益 | 16.1572% | 17.1346% |
| 中心全区间最大回撤 | 14.1599% | 13.6187% |
| 扰动净年化收益Q10，越高越好 | 5.8974% | 6.3981% |
| 扰动全区间回撤Q90，越低越好 | 30.5044% | 28.3508% |

C8880收益Q10提高0.5007个百分点，回撤Q90降低2.1537个百分点；32组同坐标对照中，30组收益更高，30组回撤更低。六个历史中心达标方案中，C8880是此绝对尾部口径下唯一未被其他方案同时压过的方案。此前相对中心收益退化略变差，使其未通过旧的联合改善判断；历史判断保留不变，新的用户偏好另行记录。

| 原四项目标 | C2132达标数/32 | C8880达标数/32 |
|---|---:|---:|
| 净年化收益达到基准的1.5倍，即10.8290% | 2（6.25%） | 7（21.875%） |
| 每一年度回撤严格低于基准 | 32（100%） | 32（100%） |
| 每60个交易日至少4次闭合交易 | 23（71.875%） | 27（84.375%） |
| 基准亏损年份策略均盈利 | 0（0%） | 2（6.25%） |
| 同时满足四项 | 0（0%） | 0（0%） |

主要缺口是收益和弱年份盈利的兼容性。C8880在2022年14/32组盈利、2023年仅5/32；2023年扰动收益平均−3.3915%，Q10为−7.8918%。两组同时在2022/2023盈利的方案，其净年化10.1780%和10.4484%仍低于10.8290%门槛。年度回撤目标通过，并不意味着全区间回撤Q90已令人满意。

完整64行逐点指标与四门布尔值见正式证据baseline-32-point-gates；复用旧账户，不重新运行或重复计数。

## 2. 为什么回到阶段二

原范围位置负责寻找回落后的机会，ACF和买入确认影响是否进场，持有时限负责退出。小改参数会改变第一次进出场、持仓状态及后续路径，难以只靠局部微调稳定收益。既有删除ACF、删除定时退出、简单平滑/投票、波动时钟和振幅止损等研究已经有反证，见历史审计及组件设计证据。
本次检验新的信息，而不把过去失败的波动时钟重新包装：①20日30分钟下行能量占比，衡量日内路径的下行能量分布；②20日隔夜负跳空RMS，衡量近期隔夜下跌幅度。它们不是账户收益指标。

## 3. 新组件检验结果

事前固定2组件、3/5日收益和不利波动及次日负跳空共5标签、9项原信息控制、4个固定模型。2020用于初始训练，2021—2026逐年预测；训练标签必须在首个测试信号日前成熟，阈值及排名只使用训练历史。全池为主，原C8880 entry_eligible机会池为辅助，机会池受旧策略状态路径影响，不按盈利样本筛选。

| 风险标签，全池 | 日内下行能量：控制后秩相关 | 隔夜负跳空RMS：控制后秩相关 |
|---|---:|---:|
| 未来3日不利波动 | −0.0402 | −0.0026 |
| 未来5日不利波动 | −0.0359 | −0.0056 |

隔夜组件与3/5日不利波动的原始秩相关分别0.1274/0.1139；控制价格方向、波动、当前日内/隔夜变化、日内总能量及原买入确认后接近零。这支持“主要重复已有波动信息”的解释，尚不足证明完全冗余或任何非线性表达都无效。
更直接的反证是：全池及机会池、3日及5日风险的四模型对照中，加入日内、加入隔夜、同时加入两者，共12个增广比较，合并年度预测误差全部比原九项信息更大。各年度和不重叠相位方向也不稳定。两范围×五标签×两组件共20个控制后相关区间均跨零，仅用于描述不确定性，不作为新增验收硬门。

正面证据同样保留：隔夜指标高组的后续不利波动确实较大，全池3/5日高减低为0.8107/1.0458个百分点，机会池为0.8054/0.5110个百分点；日内组件略改善机会池次日负跳空方向预测误差，约0.7934%。但“有风险分层”尚未证明提供额外信息，次日开盘跳空标签也不是能用次日开盘成交避免的持仓当夜损失。局部年份改善不能代替跨年增量。

2023机会池日内低组仅15例、隔夜高组0例，不能声称该年保护有效；2022最小相关组21例，标签重叠，不能当作21个独立样本；2026机会池5日标签仅19例，明确记为样本不足。分位分组可因并列阈值重叠，完整输出保留组数和原因。

判断：停止本次两个固定组件的策略化和门槛搜索。这是基于缺乏稳定增量及预测退化的研究判断，不是新经济硬门，也不证明所有重设计都不可能。

## 4. 验证范围与局限

公开DFLS重取固定资产；30m共13088根，1636日每天8根，完整日历一致；首Open/末Close与日线一致；公开ExecutionPricing转换与原账户数据完全一致；C8880原账户缓存与已发表原生证据序列化完全相同，原确认分未改写。没有新provider调用。
组件信号日期2020-01-02至2026-09-29共1635日，9/30仅用于标签；原账户验收仍为1636执行日。30m缺少开发池之前的历史，因此首19日相关组件保持缺失，不补造；3/5日标签尾部保持缺失。旧5个30m High/Low偏差原样保留，组件只用Open/Close，风险标签采用日线Low。
17项纯组件检查、24项纯统计检查及8项非法输入拒绝用例通过；真实CSV独立相关复算、实际训练成熟日期和保留预测误差共120项检查通过。当前纯组件、纯统计、修正版执行器及交付器Ruff通过；早期执行器的输入适配失败保留，均发生在真实统计前，统计方法未修改。
已见开发池被反复研究；年度时间顺序预测仍不是独立封存验证。T17可用为现有数据政策，历史真实发布时间及修订未独立验证。价格标签未扣费用、未模拟限价成交或复投，不能宣称新收益改善。阶段二未启动新账户、参数32点或五项策略自检。

## 5. 保留什么，停止什么

保留C2132作为原机制基线、C8880作为目前绝对尾部最优的研究基线，保留旧ACF、确认及定时退出的可核查作用证据；不把任何基线认定为已稳健达标。停止继续围绕失败的两个组件扫阈值，以及缺乏新依据的简单平滑、投票和波动时钟重复试验。
若继续，应重新提出独立盈利机会或收益与风险的共同表达假说，再检验其增量；仅增加“少买一点”的过滤条件，容易同时损失收益和交易频率。现阶段没有足够证据支持具体新策略。平台当前FROZEN_RULE仅表达0/1仓位，动态分层仓位或部分退出需要单独DEV能力授权，本轮未修改平台。

本轮收口：证据审计与两条组件实验完成，稳健达标目标未完成。下一步建议更换信息假说和策略表达，避免继续加补丁；不自动把本轮负面结果当作已完成整个策略目标。

## 正式证据引用

- [plan.json](../../../assets/deliveries/COMPONENTS/2/evidence/95f1b98012e56bc40cbc09cc15864b8554b0140c7856651ac4db7bd702cce57a.json)
- [absolute_audit.json](../../../assets/deliveries/COMPONENTS/2/evidence/06f7bdcf06728fe9cd1c8b6738e1401a25159b4252d8c327f9b77a6d4f80018a.json)
- [component_method.json](../../../assets/deliveries/COMPONENTS/2/evidence/7a0c1e01f93656634932761b9baffeec6e1aa065320732aeec900c427a192448.json)
- [component_statistics_method.json](../../../assets/deliveries/COMPONENTS/2/evidence/fbb7716cd84d1dfbe6581d922b0b9abbfa387ea4505fdb8cbe802c53cc2542c8.json)
- [component_review.json](../../../assets/deliveries/COMPONENTS/2/evidence/c90da2af3a148ed619aebdaae675313b1e1468ccac65953ca6a3e4883de1eae5.json)
- [component_checks.json](../../../assets/deliveries/COMPONENTS/2/evidence/6a7e7f0ff46a5e8db23ac6c5d26caf6a4539d517699a456eafe844611589039c.json)
- [component_statistics_focused.json](../../../assets/deliveries/COMPONENTS/2/evidence/af7bbabc1bfac7617938b4b4fb23c53f17161eb6ebf510c41fd0b77480e1f17a.json)
- [component_definitions.py](../../../assets/deliveries/COMPONENTS/2/evidence/573f3be2a9ac71f76a09d7687ae926906895b472e435ce855a78fd5634bff9f7.py)
- [component_statistics.py](../../../assets/deliveries/COMPONENTS/2/evidence/e5f7126d2bd8ae92086742840ed72d8c0e5f33bce4b8ef96d887d63112f2b83f.py)
- [component_checks.py](../../../assets/deliveries/COMPONENTS/2/evidence/ade8ed4f45e8529503d8e6a1e4279d0456d92f9c0e7bd30fa3bf8c16a58f243a.py)
- [component_statistics_focused.py](../../../assets/deliveries/COMPONENTS/2/evidence/28d93806d5f142d75bbe645f351998ae3a5cb75b46cf479dd2fdadf468e6f0d1.py)
- [run_study.py](../../../assets/deliveries/COMPONENTS/2/evidence/48793ee427ce34f2a6c54b1d9d3478c7f05fc795901beb380285a019f2880a2c.py)
- [run_study_v2.py](../../../assets/deliveries/COMPONENTS/2/evidence/9635f41cc24bf3130d7aba00be01c02f6368991cda41da69d8d867d168a10381.py)
- [technical_correction_v2.json](../../../assets/deliveries/COMPONENTS/2/evidence/a55ccf0d07804e8ea1b36b83170854049b51570962c7e861d01e8efa3df5c2c7.json)
- [run_study_v3.py](../../../assets/deliveries/COMPONENTS/2/evidence/a3446835a1b3b0b7dbb81aab084fe02d206906c14570ba1deb88c44b03dec265.py)
- [technical_correction_v3.json](../../../assets/deliveries/COMPONENTS/2/evidence/192fbd405d2e39af99c99ff859893a28b82336ced699bc3bd7fff7af0ae3a6e6.json)
- [run_study_v4.py](../../../assets/deliveries/COMPONENTS/2/evidence/291d1c2b24908fa9d4e0554aed007119d3995604ecd64b097317767f8a85af90.py)
- [technical_correction_v4.json](../../../assets/deliveries/COMPONENTS/2/evidence/d62154a35d657888ca1c0e98a9085955bada9db814ec9c2e29660f0a0ad7ea5e.json)
- [input_checks.json](../../../assets/deliveries/COMPONENTS/2/evidence/13fccedfa17a28e135bba66b334aa30a4cf885eb59f9e71dba34b57ce58e0aa2.json)
- [features.csv](../../../assets/deliveries/COMPONENTS/2/evidence/fa38cb7d8e169913f8c87fa50ba0bc370b307921604298a7c1ab4fb590d86f60.csv)
- [labels.csv](../../../assets/deliveries/COMPONENTS/2/evidence/5b323f06165446b7b53b4984ebe36faed5e5a42022668a86bf33f655968caddf.csv)
- [opportunity.csv](../../../assets/deliveries/COMPONENTS/2/evidence/090742cf2ffbbc15d382569717debb45898ee5eb877d0310fab48899047133d1.csv)
- [statistics.json](../../../assets/deliveries/COMPONENTS/2/evidence/835a560ea37687b57649a03d53bbaf3e33c521fad90121c686564e520d711190.json)
- [C2132-old-parameter-analysis](../../../assets/deliveries/COMPONENTS/2/evidence/ad07b35eb3df6065900055feb6cdf3c7a56f72e336e586464cab819fda1f3ad6.json)
- [C8880-old-parameter-analysis](../../../assets/deliveries/COMPONENTS/2/evidence/3c4ffdf3515cbed2262d97cf1923c20a5426ebf888aed2dda08193844a597ea6.json)
- [baseline_32_point_gates.csv](../../../assets/deliveries/COMPONENTS/2/evidence/10f77550ae3c33feed72622d7996bcc9e55f92fd47dd34310168ec83baa9f27e.csv)
- [compact_statistics.json](../../../assets/deliveries/COMPONENTS/2/evidence/b603e298471e55d27a4683518b733ad18f25b72c21b4ab9e1e9c8d8d333be0e5.json)
- [component_judgment.json](../../../assets/deliveries/COMPONENTS/2/evidence/e5b36d3f6a43beaa2fd3ba50a7bca689e01d9d522089223fefa3eecdc9c66150.json)
- [verification.json](../../../assets/deliveries/COMPONENTS/2/evidence/807105b3137edaf663a4b0bd6673d97548dc2f2000d5b9642729121096817227.json)
- [conclusion.json](../../../assets/deliveries/COMPONENTS/2/evidence/64f5abffccb9b8c79e8febdb6fe39a6b99d91954b484b2ca8fc14aeae554d795.json)
- [legacy_components_v1_exact_bytes](../../../assets/deliveries/COMPONENTS/2/evidence/7b998719b65e4164e82f8c14f7af7f4ee8a729077b36ab10d386f4ca9944083d.json)
- [delivery_technical_correction.json](../../../assets/deliveries/COMPONENTS/2/evidence/ce7d57128ce5dea72052bbe4d57c0c527623d9aed7d52ccb1844c3783b13280f.json)
- [verify_results.py](../../../assets/deliveries/COMPONENTS/2/evidence/fe97f638a52692e84202b9269679695b4e4354e59884b18b0698e96c52a39fda.py)
- [deliver_study.py](../../../assets/deliveries/COMPONENTS/2/evidence/8c2d14b62afed504cfee4797978e3984be364429737afc3b825b0e08b9590d5e.py)
- [deliver_study_v2.py](../../../assets/deliveries/COMPONENTS/2/evidence/763ae666d0d981303769751710be55116a00ca7ddb05087392df74675707fab7.py)

旧COMPONENTS/1为schema6，不能作为当前schema7机器前驱。精确字节已关联，不改旧交付；历史引用：{"type": "DeliveryReference", "batch": {"type": "ResearchBatchRef", "strategy_id": "S013"}, "stage": "COMPONENTS", "revision": 1, "content_sha256": "9ebad9782dd0dfa30de41fd2ee3cf501290d551e42657e014a106f9ac0f0c26e"}。正式前驱使用当前获批MANDATE/6，其原四门及1%执行合同保持。
