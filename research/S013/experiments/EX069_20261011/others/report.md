# EX069：此前四天的价格伸展与下跌构成

在S013既有开发池及原预热期研究两个固定假说：4日净价格变化除以原20日波动及sqrt4，越低随后4日收益越好；4日负变动中隔夜占比越高随后恢复越好。原20controls=原14、EX061两原观察、EX068两顺序及总涨跌量。主4日净收益及配对不利变动，8日辅助。原四经济硬门保持，统计诊断不新增经济门。

## 价格回落只有条件性入场线索

|范围、4日|short_stretch控制后相关|描述性500x40块区间|
|---|---:|---|
|全池|-0.0244|[-0.0926,+0.0415]|
|过去20日下跌|-0.0644|[-0.1701,+0.0394]|
|原信号真正空仓资格|-0.2735|[-0.4440,-0.1077]|
|下跌且原空仓|-0.3138|[-0.5760,+0.0803]|

原空仓资格池4日符合事前负向假说，残差自由度124；训练分位低/高组扣费代理均值+0.9100% n23/+0.7929% n26。该子集年份可报raw相关2020—2024均负，其中2022有效控制后相关-0.2677、残差自由度11。其余年份多因控制后的自由度不足不能报告partial；2023低/高组7/9行，不能估计该年分组盈利。五个非重叠相位只有phase1控制后自由度足够，相关-0.4073，另外四相位不报partial，不择相位交易。

最强反证：原空仓4日三种增广MSE全部更差，单加stretch由0.002083594升至0.002087259；配对风险未改善。全池4/8收益和4日风险三增广均退化。广义下跌低stretch组4日2022-0.79782% n45、2023-0.15939% n40、2024+1.84937% n34；跨年平均正收益不能证明两个亏损年均正，不能一般化“越跌越买”。

研究员判断：保留有限的空仓条件性入场线索，允许一个固定完整账户反证来解决统计相关与预测误差的冲突，不把它当作新策略已合格。

## 隔夜下跌更易恢复的正向假说失败

过去20日下跌池，隔夜负变动占比4日控制后收益相关-0.10853、区间[-0.23717,-0.01240]，对应不利变动相关+0.09907、区间[+0.02194,+0.21423]，与原预设正向恢复相反。单加该观察收益MSE略降约0.134%，风险MSE变差，收益仍不如训练均值基准。低占比2022-0.25160% n37、2023+0.17371% n74，高组分别-0.91036% n40/-0.56434% n22。

停止此正向买入表达；负面风险事实完整保留，但不翻号宣布原假说成功。任何持仓风险用途都须另作职责与完整账户验证。

## 下一最小账户反证

原C8880买入确认与所有退出规则保留，仅在自身当前空仓且原entry_eligible时，允许“原确认通过 OR 完整4日历史、原波动为正且4日价格回落”入场。4日和零阈值不优化，正常成交、资金、费用、后复权和固定1%执行合同保持。OR路径会改变后续持仓轨迹，不保证原基线每笔交易仍发生；原信号资格不等于实际成交。

先比较原账户与单个新中心的四项经济门。如果中心不达标，停止此固定表达并完整报告；如果达标，再事前声明包含新增lookback有效参数的标准32点和最新五项自检。不能只扰原13参数，也不能把新增14维几何与旧13维直接称为逐点相同。原四门合格与抗扰动目标分别报告，不增加新的经济否决门。

## 验证与局限

原EX058原生序列化与公开已计价日价、原1815行后复权warmup重叠区间、原volatility20、20controls均精确核验；1635开发信号保持，原费用标签按字节复用；没有新provider。纯组件16合成/18非法拒绝、统计9合成、3942真实独立核验通过。方法/合成/计划/最终格式化源码哈希一致；Bootstrap与ridge未重新拟合复算。

本轮事前声明n-rank(design)为残差自由度，低于10时partial明确不可用，共108个薄相位如此；是可解释性诊断而非策略经济门。全部原结果保留，不改EX066—068原件。

标签仍是T+1开盘至T+1+h理想分数份额成交、两侧10bp净收益代理，后复权且不叠加分红。风险Low保留原数据局限，不能代替真实账户回撤。反复已见开发池、自适应假说与未校正选择偏差不构成封存验证。本轮账户、32点、自检、候选登记均0，稳健达标总目标尚未达成。

## 正式证据引用

- [pressure_component.py](../../../assets/deliveries/COMPONENTS/8/evidence/c0b3d87baf51cca6c145e51d91ecaf995190931be8895afee70a42a4e5008a5c.py)
- [focused_checks.py](../../../assets/deliveries/COMPONENTS/8/evidence/d03b9e13111da801778c4da25e8c678cf601064fd4d4903bff9fab37f84b17b9.py)
- [prepare_statistics.py](../../../assets/deliveries/COMPONENTS/8/evidence/29e3c38fe602e2f8478a87b3f7cf3d814b87a1ed1cc662c2e5d5d9f322fc78ca.py)
- [prepare_driver.py](../../../assets/deliveries/COMPONENTS/8/evidence/af00ba6438cfe720a6693f0b705939b3ec287bcfe68b712bc80698f67fcd96fc.py)
- [opportunity_statistics.py](../../../assets/deliveries/COMPONENTS/8/evidence/676e5fc24f9bf08caa50a09b47887c30e834bfbf2afadbb12fad2ea05fc316e1.py)
- [statistics_checks.py](../../../assets/deliveries/COMPONENTS/8/evidence/1a0c8cb8ec93bf7da1070044627fe4acda88981300b4758823b2cb2554990e2c.py)
- [driver.py](../../../assets/deliveries/COMPONENTS/8/evidence/7d43ebe235b018bc4a0485d9a8fd984f5dfc59368db6d8032b2659a4e1b166e6.py)
- [focused_checks.json](../../../assets/deliveries/COMPONENTS/8/evidence/55d3be7596438b35743f027fdeaf1fbc4eb8c96e772e1707e5b5a5e2702f6005.json)
- [statistics_checks.json](../../../assets/deliveries/COMPONENTS/8/evidence/a8396ddd341ba8484552da210337d1f6017e5b51189c6b9e99afd76d9c82120e.json)
- [method.json](../../../assets/deliveries/COMPONENTS/8/evidence/6f740e5d9524a19b6e286f88a615c99a1e939490758ef5c3eee06cde18c31f3f.json)
- [plan.json](../../../assets/deliveries/COMPONENTS/8/evidence/f172299fcde74ee5e10af20b6eb86c003868decaacf7da43a79a1a0870a9aa64.json)
- [input_checks.json](../../../assets/deliveries/COMPONENTS/8/evidence/978ef1195fa94cffbfea3f9375433936b49a85d3080c31e2563b25a124e479b1.json)
- [features.csv](../../../assets/deliveries/COMPONENTS/8/evidence/e1e2dc88675e953364369833d1e8731e8c39061e723498e50d46ddefaace764c.csv)
- [observations.csv](../../../assets/deliveries/COMPONENTS/8/evidence/813fb9d6d19becbd99f6fd931f1830472e8721f636891ba9e140de6307234f3e.csv)
- [daily_prices.csv](../../../assets/deliveries/COMPONENTS/8/evidence/71319e1c9ea6543849f809a0996bd6978636d76848cbb3c8aaf962f302c27263.csv)
- [scopes.csv](../../../assets/deliveries/COMPONENTS/8/evidence/123bfd64696b97d2d0c0806527d6003e8d3471c8999a8f4e257a73f245c4e855.csv)
- [labels.csv](../../../assets/deliveries/COMPONENTS/8/evidence/ade6c0b45a0de547ac941b0585a6e24a381bee87a8ac56b95f44b20c4be6af50.csv)
- [statistics.json](../../../assets/deliveries/COMPONENTS/8/evidence/064197fc69cc4571fdbe66b82db4e3ea001d832b35131698bd1a1a578517a149.json)
- [verification.json](../../../assets/deliveries/COMPONENTS/8/evidence/9d007a8bcfea18d85255180b06a60cb88e41d4b80367a54d869600ce5ca25f81.json)
- [judgment.json](../../../assets/deliveries/COMPONENTS/8/evidence/b6f1a6b631b488e6b987127fa900029c224726dbce2e1bd1370b5ccf9d98bd64.json)
- [compact_statistics.json](../../../assets/deliveries/COMPONENTS/8/evidence/e3124986f11f56e2aa9647bd65cfb8290e704d4d49921ca58e7069abc2d93a94.json)
- [conclusion.json](../../../assets/deliveries/COMPONENTS/8/evidence/a4f08fde6a9333f78aa6645519921be322c54851406d9a68e28675ff8206c184.json)
- [report.md](../../../assets/deliveries/COMPONENTS/8/evidence/6c9855f07e0f3978ceaa94006f651d5bd199ccf258efc7dc8e872b42eefdf615.md)
- [finish.py](../../../assets/deliveries/COMPONENTS/8/evidence/10650e8051b71df63ae1625dc67734fa77951fcae32fc369ee8d76653d67e50b.py)
