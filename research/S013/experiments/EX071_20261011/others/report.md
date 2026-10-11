# EX071：尾盘弱势能否帮助判断继续持有

本轮固定检验一个既有线索：尾盘弱势=-log(C8/C6)，是否在真实持仓及已知持有天数、浮盈亏等控制后，对下一开盘继续持有4日/8日有收益与风险信息。原正收益、负风险方向不翻转；原经济硬门不变，0新账户、0参数优化。

科学判断：本固定持仓恢复表达判为INEFFECTIVE，不转成退出延迟或放宽退出。少数局部正面事实保留，但整体控制后区间全部跨零、2023方向反向，退出组预测退化，不足以证明可用的持仓管理优势。总体稳健策略目标未达成。

以account_daily.date=T的收盘实际quantity选择样本：506行持仓，其中过去20日下跌217行；T当前信号计划继续390行、计划退出116行。不能用账本signal_date(T−1)错位对齐。当前B0实际quantity与前一信号计划逐T完全一致，分歧0；本研究没有借此宣称B0存在未成交差异。

主标签是明早卖出与继续h日后卖出的同数量价格增量，两路径相同卖费抵消，不重新扣买费。它与旧虚拟新买收益是固定手续费仿射关系，不能靠移除买费制造新的预测排序。T收盘标记到未来清算另只扣一次卖费，仅用于分解；首个隔夜变动是两方案共同承担、明早决定已无法避免的部分。

风险采用未来固定OPEN/CLOSE观察最不利幅度，不用已知异常High/Low，不含初始隔夜于可控风险；这不是完整日内路径或实际账户最大回撤。未来旧策略卖出日不用于挑样本；假设固定当前数量继续跨越旧退出，仍是反事实标签而非可执行账户。

|范围与标签|控制后相关|500×40描述区间|可用样本/残差df|加late预测误差相对controls|加late误差相对训练均值|
|---|---:|---|---:|---:|---:|
|全部真实持仓 return_4|+0.0242|[-0.0785,+0.1215]|493/470|-0.0177%|+4.8524%|
|全部真实持仓 return_8|+0.0454|[-0.0342,+0.1134]|492/469|+0.0912%|+9.1944%|
|全部真实持仓 downside_4|-0.0126|[-0.1045,+0.0873]|493/470|+0.0619%|+7.7386%|
|全部真实持仓 downside_8|-0.0322|[-0.1178,+0.0617]|492/469|-0.0102%|+15.7592%|
|下跌真实持仓 return_4|+0.1263|[-0.0151,+0.2627]|213/191|-0.4759%|+3.3878%|
|下跌真实持仓 return_8|+0.0948|[-0.0111,+0.2219]|213/191|+0.0175%|+1.7514%|
|下跌真实持仓 downside_4|-0.1292|[-0.2565,+0.0046]|213/191|-0.3925%|-1.6763%|
|下跌真实持仓 downside_8|-0.1283|[-0.2481,+0.0032]|213/191|-0.5440%|-5.5111%|
|当前计划继续 return_4|+0.0269|[-0.0854,+0.1402]|379/356|-0.0102%|+3.7467%|
|当前计划继续 return_8|+0.0420|[-0.0580,+0.1195]|378/355|+0.2068%|+10.1264%|
|当前计划继续 downside_4|-0.0269|[-0.1414,+0.0955]|379/356|-0.1376%|+13.4238%|
|当前计划继续 downside_8|-0.0555|[-0.1634,+0.0671]|378/355|-0.0559%|+22.6395%|
|当前计划退出 return_4|+0.0524|[-0.1818,+0.2621]|114/91|+0.4918%|+2.5587%|
|当前计划退出 return_8|+0.0944|[-0.1552,+0.3271]|114/91|+0.4815%|+3.9358%|
|当前计划退出 downside_4|+0.0231|[-0.1893,+0.2416]|114/91|+0.1628%|-5.7528%|
|当前计划退出 downside_8|+0.0296|[-0.2058,+0.2334]|114/91|+0.1634%|-4.1900%|

正面事实完整保留：下跌持仓4日raw相关+0.1287，其raw区间[+0.00197,+0.28125]；但控制后+0.1263的区间[-0.01515,+0.26267]跨0。下跌持仓4日收益加late误差比controls降低0.4759%，仍比训练均值差3.3878%；对应风险误差比controls降低0.3925%，比均值好1.6763%。2022下跌持仓收益/风险控制后方向为+0.2385/−0.1556。不能把这些事实抹成“完全无信息”。

最强反证：2023真实全部持仓、下跌持仓、计划继续三组，收益4日控制后相关分别−0.1329、−0.3069、−0.1621，配对风险分别+0.1199、+0.3261、+0.1286，均与原冻结方向相反。这是该年描述性方向事实，不是已经过逐年置信区间确认的因果结论。所有scope的8日收益加late误差均更差；退出组4日收益误差增加0.4918%。

下跌持仓4日五个固定非重叠相位的控制后相关为[-0.2229,−0.0888,−0.0354,−0.0276,+0.4930]，整体正相关不在多数相位重复。退出组五相位全部残差df<10，不报partial；2022退出n26/df3、2023 n22/df0同样不可报，不能将raw高相关当控制后有力证据。2023下跌持仓低/高训练分位组只有4/7行，不报告分组均值。

22控制=原20去掉组件精确反向late_recovery，再加入真实持有天数、已知成本价浮盈亏和当时下跌状态。避免将自身反向放入控制造成机械消除。残差自由度按实际矩阵rank计算，低于10明确不可用；这只是统计可解释性诊断，未新增经济否决门。两模型使用共同有限样本，训练标签严格早于测试信号成熟，rank只由过去训练拟合，ridge固定10、500×40块区间seed13，无阈值或相位选择。

29合成检查/3非法输入拒绝、源码静态校验及33,159真实独立核验通过。其中输入32,628、统计504、控制/scope27；逐T实际成交重建、费用仿射恒等式、close分解、OPEN/CLOSE风险端点、所有年份/相位rank和df、成熟共享模型样本及预测MSE均核验。Bootstrap和ridge不重复拟合，未请求新数据。

下一步停止此尾盘恢复驱动的持仓改法。保留既有原确认、真实账户退出与下跌年严格正收益目标，转向已公开负面隔夜压力的风险职责最小对照。动态逐次半仓当前公开接口不可表达，平台角色边界保持；现有二元接口的风险过滤先做固定方案及中心反证，频率可能损失且后续路径会变，不承诺改善。

局限：重复已见S013 510500开发池及原warmup，无封存新样本、研究选择偏差未完整校正。后复权、资金费用及固定1%合同保持，不叠加分红；源前缀检验不证明历史数据实际发布时间和修订史。样本均值、相关、区间和预测误差不能替代整个账户的四门或32点抗扰动结论。

## 正式证据引用

- [continuation_core.py](../../../assets/deliveries/COMPONENTS/9/evidence/752ebc55ce9cd401645410d57508fc0a2633df3ac1a1f386ae9bcd0df50cc2cf.py)
- [driver.py](../../../assets/deliveries/COMPONENTS/9/evidence/6820cf33bf13c9670d5d059a3cd6c66cd5055f10fc7ad8c696b4d7d175d9feff.py)
- [focused_checks.py](../../../assets/deliveries/COMPONENTS/9/evidence/d460cca291a4945e1b45358e9a5cf9fcae73e1887744d796262f2e991a2e2714.py)
- [freeze_plan.py](../../../assets/deliveries/COMPONENTS/9/evidence/3a4adcd3f849734071008b668f7cbdb20841d555864458f7ca5400ba745e9233.py)
- [independent_inputs.py](../../../assets/deliveries/COMPONENTS/9/evidence/3ea0db23d360553e3abb8732d270da1c18999aed7106c320c8efa668f1f52997.py)
- [independent_statistics.py](../../../assets/deliveries/COMPONENTS/9/evidence/59eb424a2e8adf7739cbe444a64262fdcd267f09d8ff4b556dc8fbe4572d5218.py)
- [opportunity_statistics.py](../../../assets/deliveries/COMPONENTS/9/evidence/05f2d98f9245ac0a56009343b2e22ece5680f22312530bba3777b234af3b43a5.py)
- [prepare_statistics.py](../../../assets/deliveries/COMPONENTS/9/evidence/2feb277496dc70c3d676be9f412d50e60839d606f2933d182ce4df19e147c027.py)
- [prepare_verifier.py](../../../assets/deliveries/COMPONENTS/9/evidence/a288a872ba458f3fd365a6b30dfa91dcb67906110e98ec3caa2424458c0749f8.py)
- [focused_checks.json](../../../assets/deliveries/COMPONENTS/9/evidence/0b3892c98d5dc7187cedc042d1ccd05e75c601a8f49c0cedd10c4aa3c6d9cd2d.json)
- [method.json](../../../assets/deliveries/COMPONENTS/9/evidence/7e14048fe32ec0b45c0cc6ef8416efc26377a8a17d2d4051ef37fdaa2762a116.json)
- [prospective_plan.json](../../../assets/deliveries/COMPONENTS/9/evidence/30f5e89d720ba8dfa28ec5d92342a114b2e8ee1dd54e12e17e6c316244d72b19.json)
- [plan.json](../../../assets/deliveries/COMPONENTS/9/evidence/0ab0b925a3300cd870d92ccad7b3d5d3b581e8a4f51eefc5ff591e2966d177fe.json)
- [input_checks.json](../../../assets/deliveries/COMPONENTS/9/evidence/25e7ddaf1b1d27a7a6252f5a5fb3d47d3a937316c50aef81b6cea00b6e6874a7.json)
- [features.csv](../../../assets/deliveries/COMPONENTS/9/evidence/9b19b0219dcf886936584cb30a00e3cdb1616cb75f20bf110e971ba1d11ed890.csv)
- [state.csv](../../../assets/deliveries/COMPONENTS/9/evidence/b2f0d2a1436e14aeb39569f09e68d9bd6dfd02b6c0ecb205396d5aa0682220ba.csv)
- [labels.csv](../../../assets/deliveries/COMPONENTS/9/evidence/a0a83fab02406d6340e63393491e483cb889fa802cfdfc2d39a0105945137252.csv)
- [scopes.csv](../../../assets/deliveries/COMPONENTS/9/evidence/e96960f85a535224ae72834e559438a86024404b6e643f4ec0a4096d75039c1d.csv)
- [daily_prices.csv](../../../assets/deliveries/COMPONENTS/9/evidence/499377d8075acbed61555029809b7449dc5703e24ad04bbc6abf8e095c479a0e.csv)
- [statistics.json](../../../assets/deliveries/COMPONENTS/9/evidence/04f600fc246836bebd2d53c586eea704b0d4a44607d1d2dd4549d1f32942153b.json)
- [verification.json](../../../assets/deliveries/COMPONENTS/9/evidence/c79a52e2d156347676da78f7bdd69e87f53391c7b1470f8c8520cc26b8671f5c.json)
- [finish_v1.py](../../../assets/deliveries/COMPONENTS/9/evidence/bd876dd5aceadc1cd583e9936da86f0ec67f2666ecd45ad6b13dc9a201f5316e.py)
- [root_review.json](../../../assets/deliveries/COMPONENTS/9/evidence/9479b1e2e2200a05a3d2e36930b57a7ad9af26db72759b8aa920aa0fea243792.json)
- [compact_statistics.json](../../../assets/deliveries/COMPONENTS/9/evidence/602791f2f1bfd57258aa9e2ff86a677b73b2134bce003246bb9d790b3ce956cf.json)
- [conclusion.json](../../../assets/deliveries/COMPONENTS/9/evidence/300f70900e0620ed23bb6599d20d24aa01fb9a0a9df8483f11ecd7a339c09238.json)
- [report.md](../../../assets/deliveries/COMPONENTS/9/evidence/4f74c56fe8ed5a6dd23f440732458d72e0034768d566acd905335dca4122572a.md)
- [closeout_amendment.json](../../../assets/deliveries/COMPONENTS/9/evidence/0488e7c5fdf134b07384ff89dd4b5d36cf3fa02d17965e4c2e1de5b626ca3bd8.json)
- [finish.py](../../../assets/deliveries/COMPONENTS/9/evidence/35922486354bde321729576a1edc6e06d0580e22809a2091a78941297cc25c65.py)
