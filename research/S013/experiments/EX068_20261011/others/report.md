# EX068：日内下跌顺序与连续段对照

本轮从原尾盘入场路线转向新增顺序信息。固定两个观察：前4根30分钟负收益占全天负收益的比例；最大连续严格负收益段的累计跌幅占全天负收益的比例。零/正变动中断连续段，没有负变动时比例0仅代表无下跌。控制原14项、EX061两原观察和总上涨/下跌量，共18项；不是重排旧评分或搜索阈值。主4日净收益和途中不利变动，8日辅助。

## 入场增量不足

|范围、4日|早段下跌占比控制后相关|最大连续段占比控制后相关|收益预测|
|---|---:|---:|---|
|全开发池|-0.0261|-0.0086|三种增广均更差|
|过去20日下跌|-0.0112|-0.0464|仅连续段略改善|
|原信号真正空仓资格|+0.0294|-0.0123|三种增广均更差|
|下跌且原空仓|-0.0338|-0.0697|成熟训练及分年测试样本不足|

上述控制后描述性块区间均跨零。全池4日三种增广模型及8日三种均退化；空仓4/8同样如此。早盘先跌后稳的正向固定假说未得到支持，不将负向结果翻号后宣布成功。

## 连续卖压有局部线索，但不能解决两个亏损年份

过去20日下跌池，按此前成熟训练Q25/Q75，连续段低组4日扣费代理均值+0.17119%，n184；高组-0.33359%，n159。单加连续段MSE由0.00089735249降到0.00089541904，改善约0.215%，仍不如过去训练均值基准0.00089291259。配对4日风险MSE却由0.00044605532升到0.00044668757。

|年份|低连续段组4日扣费均值|样本|高组均值|样本|
|---|---:|---:|---:|---:|
|2022|-0.82148%|48|-1.44547%|35|
|2023|+0.30906%|42|-0.41629%|30|
|2024|+0.37390%|36|+0.25520%|29|
|2025|+0.97621%|22|-0.42836%|23|

不能把跨年份平均正收益当作每个buyhold亏损年份均盈利。2022低组仍大幅负，8日预测退化，原空仓增量未成立。结论是保留局部正面事实，停止本组直接策略化；未运行账户验证，不宣称账户或参数扰动已改善。

## 薄相位及价格代理限制

18项controls加截距，当薄相位仅20行时残差空间可能只剩一个维度，相关±1不构成强证据。本轮原统计完整保留；判断不依赖这些薄相位。后继将事前声明残差自由度口径，避免解释自由度不足的partial相关，不新增策略经济门。下跌且原空仓69行、有效约67，逐年模型/分组样本不足；不能称作零收益或2023已经验证。

原EX058原生序列化、既有公开30分钟计价、EX061两原观察的源码重算/公开列/EX066负号列、原14controls均精确核对。纯组件20项合成检查、25项非法输入拒绝，统计7项合成检查及224项独立真实核验通过；没有新增provider或账户。Bootstrap与ridge未重复拟合复算。全池1635行，过去20日下跌757行，原空仓资格147行、其中下跌69行；该空仓是原策略信号状态，非实际账户数量。

固定净收益标签使用下一开盘至下一开盘+h、两侧10bp、分数份额理想成交，原后复权且不叠加分红。风险标签的Low保留已有数据问题，不能代替真实最大回撤。开发池已反复见过，区间未校正开发选择，非独立封存验证。原四项硬门和最新五项自检定义保持，新账户、新32点、自检及候选登记均0，稳健达标总目标尚未达成。

下一路线研究此前四天的价格伸展，以及负变动主要来自隔夜还是盘中；固定少量假说，控制旧信息与本轮顺序信息后检验增量。


首次交付发布遇同S013批次EX067的发布锁占用；原统计与判断保持，保留失败记录后顺序恢复同一COMPONENTS7，没有删除锁、改平台或另建实验。
## 正式证据引用

- [order_component.py](../../../assets/deliveries/COMPONENTS/7/evidence/ebef150b9e19920484a003915ca73d79ffb5799444b30db511c7668eef3063bf.py)
- [focused_checks.py](../../../assets/deliveries/COMPONENTS/7/evidence/19a52307f1cb79f99b6d6acbc6e3875b73970deb3cc4e9387bf08f304139363b.py)
- [prepare_statistics.py](../../../assets/deliveries/COMPONENTS/7/evidence/c49e2a38bb75a1ed1bcccb3c7916906cf7ba2b90ad66cc54a108ce297c0e5a47.py)
- [late_recovery_component.py](../../../assets/deliveries/COMPONENTS/7/evidence/3cd87ec20d4bd8f043aaf5448fc85ba8f486350d65cf0828249cf8650c9ea54e.py)
- [opportunity_statistics.py](../../../assets/deliveries/COMPONENTS/7/evidence/49a69940c4e4ff272c88813b9b8f4e70ec97847d45099da82d6c520ce5270b36.py)
- [statistics_checks.py](../../../assets/deliveries/COMPONENTS/7/evidence/1db2543219ea52e4f4a2b8489152dee0c3ee17d2041eacb82afd8d2c672f7213.py)
- [driver.py](../../../assets/deliveries/COMPONENTS/7/evidence/8149b28ee0670915ad17a1339f745b92d4f51e1ceb8d2d1061d275a268dce788.py)
- [focused_checks.json](../../../assets/deliveries/COMPONENTS/7/evidence/861336a9ba2647cd7b03fb33e9ab581d8860bb175820d50fc1255c238c6dc793.json)
- [statistics_checks.json](../../../assets/deliveries/COMPONENTS/7/evidence/fb745b85e835cc0bb9119698948c0ba984cd9f82e66fff43d6413a1d5db5322d.json)
- [method.json](../../../assets/deliveries/COMPONENTS/7/evidence/35b1b4ae66187743e09c63cc9a4f40d8a797411eb37822172597c662b39f0d29.json)
- [plan.json](../../../assets/deliveries/COMPONENTS/7/evidence/053ccd1ade20b79a6f0c2ce4a4586838c8a4fae59331e5791f8d56d4fbc40842.json)
- [input_checks.json](../../../assets/deliveries/COMPONENTS/7/evidence/a6bc0cb63574ba62e39ec56be6b8121593404a7f93d808dae4c1c1a18b794825.json)
- [features.csv](../../../assets/deliveries/COMPONENTS/7/evidence/303943c0042045db2e45a2319fc548f6931d977576febf8a81e67f90797f01fb.csv)
- [scopes.csv](../../../assets/deliveries/COMPONENTS/7/evidence/123bfd64696b97d2d0c0806527d6003e8d3471c8999a8f4e257a73f245c4e855.csv)
- [labels.csv](../../../assets/deliveries/COMPONENTS/7/evidence/ade6c0b45a0de547ac941b0585a6e24a381bee87a8ac56b95f44b20c4be6af50.csv)
- [statistics.json](../../../assets/deliveries/COMPONENTS/7/evidence/9912d5b749f60efb87f77532a9e3b386ba053ef2ec376726bbe88016a0638af4.json)
- [verification.json](../../../assets/deliveries/COMPONENTS/7/evidence/1f0d0a4b8ebfdf96dc7d407c3a023fee450baa797256cff6b68119e64397bbfb.json)
- [compact_statistics.json](../../../assets/deliveries/COMPONENTS/7/evidence/4cd50a381848027f095c07057be28cd9caadc0c51c32da378be0442419414225.json)
- [judgment.json](../../../assets/deliveries/COMPONENTS/7/evidence/337fdf11695f4fe0863b67345cb2758a14604fd7d7d8c47e82bbc154b8eec348.json)
- [conclusion.json](../../../assets/deliveries/COMPONENTS/7/evidence/f894f68698a5af3f1f1c7ef956ccfcb70943994f9d8b9b325f08dd0c01201504.json)
- [report.md](../../../assets/deliveries/COMPONENTS/7/evidence/44cfa12c0b8c909fc4ebff183b8bac4e42d33fe1540ceb8e5b3fbdb318617d0f.md)
- [finish.py](../../../assets/deliveries/COMPONENTS/7/evidence/4ac49b9e421a0537223ec2432ddd34d311c06afcc9c8d308847bed7f6b268866.py)
- [failed_closeout.json](../../../assets/deliveries/COMPONENTS/7/evidence/acb71c62376b064fbe7ca9e78d4e586e3db7efd6b9f69d5ec0d8a8c0c477b138.json)
- [recover_closeout.py](../../../assets/deliveries/COMPONENTS/7/evidence/ef84f70a98a8663b2cd4df4c4022a5650f337486890a27e9f1b9de630fae32c1.py)
