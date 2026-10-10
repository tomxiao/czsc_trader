# S013：下跌持仓逆向波幅退出最小机制对照

RSCH阶段三，用户授权自主完成目标，无需逐轮评审。沿用原S013数据与四项经济要求，本轮完成只表示已交付证据。

EX036完整既有账户诊断：原中心下跌路线57次买入机会全部通过确认；33账户2021次下跌机会仅7次被拒绝。共同满足原资格的配对日，确认判断不同21次。机会依已有持仓状态，不是删除确认后的收益。均值居中自相关C8701仅差2024年度回撤要求，其峰谷损失全部位于实际下跌持仓。该路径归因是描述，不是新增风险规则的利润预测。

本轮两新机制分别在EX028均值居中自相关及EX029同类BODY背景上增加同一风险退出：已持仓下跌路线，从HFQ信号入场Close锚点到当前Close的逆向位移达到严格过去20日真实波幅均值的一个单位时，T发出退出，T+1按原规则执行。TR=max(High-Low,abs(High-previousClose),abs(Low-previousClose))；参考均值shift(1)，当日冲击不进入单位。单位随T的过去历史变化，不冻结在入场日；包含等号、不在入场当日退出。优先级loss>trailing>bear_risk>range>time>regime。退出后按原资格可以再次入场，无新增等待。bull路线和原确认保持。

固定一个单位及20日是新机制选择，未对它们做参数稳定性检验。信号锚点不同于实际成交价和费用，日频退出不保证成交止损价。原H8/H4信号持仓日、全部13数值中心及完整域保持，不按年份/盈利交易例外。最强反证是提前退出可恢复反弹、增加重复买卖费用并损害2022/2023收益。

510500.SH、2020-01-02至2026-09-30共1636交易日、100万元、HFQ信号、整手100、T决策/T+1执行、单边0.1%费用，策略及LimitBuyHold统一1%限买溢价。四项要求：年化达到正基准1.5倍；每自然年最大回撤严格小于基准；每60日平均至少4闭合交易（至少110笔）；基准亏损年2022/2023实际连续账户年度收益为正。全窗回撤与邻点诊断不新增经济门。

两新业务配置、三实际完整评价（N0串行/spawn重复一致；N1一次），三旧原生完整账户精确复用。完整信号及现金/数量/费用账本独立核对，原生绑定HFQ重算ACF、因果量额秩/确认分、范围位置、路由、TR单位及全持仓状态。仅各自通过原四门的新中心接受32完整13维扰动点；原EX01532精确复用，不扩展未达标中心。

|账户|候选|年化|全窗回撤|闭合交易|2022收益|2023收益|原四门|
|---|---|---:|---:|---:|---:|---:|---|
|B0-TIME|C2132|16.1572%|14.1599%|112|+12.1687%|+0.2841%|通过|
|B0-MEAN|C8701|13.5405%|23.9087%|123|+11.4638%|+0.5481%|annual_drawdown|
|B0-BODY|C8481|13.9218%|22.2369%|121|+12.8492%|+1.4978%|annual_drawdown|
|N0|C5900|12.8494%|21.7798%|131|+9.0633%|-3.8531%|negative_buyhold_year_profit|
|N1|C5901|12.9879%|21.0400%|130|+8.9218%|-2.9442%|negative_buyhold_year_profit|

|账户|自然年|收益|回撤|基准回撤|年度回撤门|
|---|---:|---:|---:|---:|---|
|B0-TIME|2020|+16.7355%|6.1272%|14.9712%|通过|
|B0-TIME|2021|+9.9101%|2.7008%|9.7035%|通过|
|B0-TIME|2022|+12.1687%|9.7680%|28.4105%|通过|
|B0-TIME|2023|+0.2841%|5.6722%|17.2665%|通过|
|B0-TIME|2024|+64.9989%|10.0213%|18.5736%|通过|
|B0-TIME|2025|+11.0774%|3.5332%|13.7975%|通过|
|B0-TIME|2026|-0.0384%|4.5425%|18.7646%|通过|
|B0-MEAN|2020|+17.3786%|6.1272%|14.9712%|通过|
|B0-MEAN|2021|+12.0902%|2.2401%|9.7035%|通过|
|B0-MEAN|2022|+11.4638%|12.9741%|28.4105%|通过|
|B0-MEAN|2023|+0.5481%|6.7438%|17.2665%|通过|
|B0-MEAN|2024|+50.4429%|19.7899%|18.5736%|未通过|
|B0-MEAN|2025|+10.7206%|3.5336%|13.7975%|通过|
|B0-MEAN|2026|-7.1506%|10.1152%|18.7646%|通过|
|B0-BODY|2020|+17.3786%|6.1272%|14.9712%|通过|
|B0-BODY|2021|+12.0902%|2.2401%|9.7035%|通过|
|B0-BODY|2022|+12.8492%|13.0875%|28.4105%|通过|
|B0-BODY|2023|+1.4978%|5.8626%|17.2665%|通过|
|B0-BODY|2024|+50.4465%|19.7916%|18.5736%|未通过|
|B0-BODY|2025|+10.7211%|3.5330%|13.7975%|通过|
|B0-BODY|2026|-7.1525%|10.1165%|18.7646%|通过|
|N0|2020|+17.7275%|6.1272%|14.9712%|通过|
|N0|2021|+9.1809%|3.3426%|9.7035%|通过|
|N0|2022|+9.0633%|11.1375%|28.4105%|通过|
|N0|2023|-3.8531%|9.4420%|17.2665%|通过|
|N0|2024|+61.0069%|16.0218%|18.5736%|通过|
|N0|2025|+5.8681%|4.1948%|13.7975%|通过|
|N0|2026|-4.5927%|7.6384%|18.7646%|通过|
|N1|2020|+17.7275%|6.1272%|14.9712%|通过|
|N1|2021|+9.1809%|3.3426%|9.7035%|通过|
|N1|2022|+8.9218%|11.2527%|28.4105%|通过|
|N1|2023|-2.9442%|8.5853%|17.2665%|通过|
|N1|2024|+60.9824%|16.0218%|18.5736%|通过|
|N1|2025|+5.8673%|4.1946%|13.7975%|通过|
|N1|2026|-4.5920%|7.6391%|18.7646%|通过|

N0独立全路径风险退出20次；该计数不是增加的盈利交易数。完整路径变化及所有闭合/未闭合交易保留。

N1独立全路径风险退出20次；该计数不是增加的盈利交易数。完整路径变化及所有闭合/未闭合交易保留。

两个新中心均未通过原四门，因此按事前计划不运行新增参数账户。这不是参数稳定性改善证明。

全部已见年份和完整失败账户保留。反复使用开发池产生选择偏差，无独立验证、未来保证或对新常量稳定性的证明。FULL只核验声明证据完整性。未推进正式阶段四、冻结、PTE或生产。

本轮目标判断：总改善目标仍未达成；本轮机制的接受或否定依据为完整账户与原经济要求。

## 正式证据引用

- [B0-TIME](../../../assets/deliveries/CANDIDATES/33/evidence/bcc9e99b4a0e2d0854e63570a8b6846ddca26debddac364c74246264ac288b86.json)
- [B0-MEAN](../../../assets/deliveries/CANDIDATES/33/evidence/f47132856172896f6ecd570c266d73d154e182019ebe5340055427b455e0ee32.json)
- [B0-BODY](../../../assets/deliveries/CANDIDATES/33/evidence/976de84cea65318f55203724ee8a7b2c5b4fa0805be1bfb9587b85927773db30.json)
- [N0](../../../assets/deliveries/CANDIDATES/33/evidence/b5159b7d969d3c86382724408dadaebb049b6d310c27524551f4c8cf62156b3f.json)
- [N1](../../../assets/deliveries/CANDIDATES/33/evidence/d9746b6919fa7537740479ffe784ae762fa645ffdab5f288d3872c6174d081dd.json)
- [plan](../../../assets/deliveries/CANDIDATES/33/evidence/c666eefdfff833556c4acbb5bca09884d66b2908c2fb25c4b34b05712b9ae177.json)
- [authorization](../../../assets/deliveries/CANDIDATES/33/evidence/4075bdb831064fa3bd7b1d964816858bd60ee8c7c47d0636c293b2e73d0612f5.json)
- [research-decision](../../../assets/deliveries/CANDIDATES/33/evidence/0ec60e01d7137bfb86e3e33b3e54bda540cbc258575b43b8be807842447b24e3.json)
- [native-confirmation-diagnosis-v2](../../../assets/deliveries/CANDIDATES/33/evidence/0b916fde7b2c5d24b337b0e59a5952f33020d6e8a54fdfe97ddb2e0ca24c23e9.json)
- [native-drawdown-diagnosis-v2](../../../assets/deliveries/CANDIDATES/33/evidence/9c18d0e3415b9b6c97561f372e8ff4e109c5023fe19f89cd64c4c703dc461ed1.json)
- [geometry](../../../assets/deliveries/CANDIDATES/33/evidence/3fe2635961b87dee68575741225d69cfbc067a8b0117aa462ec0f3bcda2fde22.json)
- [protocols-geometry-reference](../../../assets/deliveries/CANDIDATES/33/evidence/3c865aa6dde3421f003ae818ff9f59f7a316ad9be34b6c45f95709e351082966.json)
- [protocols-parameter-plans](../../../assets/deliveries/CANDIDATES/33/evidence/5a6a5d4d77b38656207391b4875673992429533c54285145c6c3ff3c987642ed.json)
- [protocols-plan-references](../../../assets/deliveries/CANDIDATES/33/evidence/9de35197ce3b8348fc6d84083d0951eba7ae9ee8b6699cbb824c45f3c8299df5.json)
- [runs-account-references](../../../assets/deliveries/CANDIDATES/33/evidence/791ba19189b2af93e37c1d01f5e5f28119d6d383201265a98d8906ea535b44fd.json)
- [runs-analysis](../../../assets/deliveries/CANDIDATES/33/evidence/3cde770bc419545f414ded73d56c52260611d2d45c5aee9fc87f628f49f83777.json)
- [runs-conclusion](../../../assets/deliveries/CANDIDATES/33/evidence/89d5b4726974d6c846d9a1312638904c9773fb57fdb2e2045e99afa346aacffa.json)
- [runs-matrix](../../../assets/deliveries/CANDIDATES/33/evidence/40073572f73ab29e78392b47275af44e9b641254833651d37a2ed9b7c2b3f5fb.json)
- [runs-parameter-analysis](../../../assets/deliveries/CANDIDATES/33/evidence/470b6d5430cc24581fee92b322001c3a1798e9eba52257498d78811ff1dd6cb1.json)
- [runs-parameter-pairs](../../../assets/deliveries/CANDIDATES/33/evidence/d2507df3887b688c5297b1cfdf3decea4f8c6ba081b6772fa5c9df6ea0d4193f.json)
- [runs-precheck](../../../assets/deliveries/CANDIDATES/33/evidence/540436364ebb2ed9dbf8437a641f3773e0eade63441ea99d6c08cf9182d92d2e.json)
- [runs-registration](../../../assets/deliveries/CANDIDATES/33/evidence/ec70d3521c3e9c65ae4052f70ddbae580b2b482f822a13a1ac6ddb73d4523b61.json)
- [runs-reproduction](../../../assets/deliveries/CANDIDATES/33/evidence/064b9b3b524f27860d834ef0bed76743909e0b3f7c25ef6707608a994b814cd6.json)
- [runs-synthetic-check](../../../assets/deliveries/CANDIDATES/33/evidence/53fb2330dba5fd82f1b15c80fe252e18b9f8830bfb33d4a228aa918fc1592a6c.json)
