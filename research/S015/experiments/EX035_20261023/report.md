# S015 价格行为六维信号普查

Status: COMPLETED

已冻结研究计划和24个连续价格表达，再完成434日覆盖与逐日前缀核验。此实验没有查看新信号的收益效果，没有新增有效组件或候选。用户授权阶段二不限轮数，接续组件验证，不进入阶段三。

所有数据来自既有认证快照，日线75日预热、开发434日，30分钟每天8根。没有新增源或日期。零分母按字典定义中性值；不补缺行。高低点在同根内部的先后未知，不能解释成逐笔交易行为。

## 信号字典与数据普查

| 家族/信号 | 定义 | 唯一值数 | 零值数 |
| --- | --- | ---: | ---: |
| direction_efficiency/drift5_scaled | sum(r[-5:])/(abs(sum(r[-5:]))+sqrt(5)*population_std(r[-20:])); r=log adjusted close returns | 432 | 3 |
| direction_efficiency/efficiency5 | sum(r[-5:])/sum(abs(r[-5:])) | 407 | 3 |
| direction_efficiency/intraday_efficiency | sum(u)/sum(abs(u)); u[0]=log(Cbar[0]/day_open), u[j]=log(Cbar[j]/Cbar[j-1]) | 416 | 9 |
| direction_efficiency/step_persistence | mean(sign(u[:-1])*sign(u[1:])); zero moves have sign zero | 14 | 21 |
| up_down_asymmetry/semivariance_balance | (sum(max(u,0)^2)-sum(min(u,0)^2))/sum(u^2) | 424 | 0 |
| up_down_asymmetry/largest_step_balance | (max(max(u,0))-max(max(-u,0)))/(max(max(u,0))+max(max(-u,0))) | 418 | 6 |
| up_down_asymmetry/post_drop_recovery | After the earliest negative u within absolute 1e-12 log-return of min(u), sum(remaining u)/sum(abs(remaining u)); 0 if no negative step or no remaining movement | 289 | 49 |
| up_down_asymmetry/run_length_balance | (longest strictly positive u run-longest strictly negative u run)/8; zeros break runs | 15 | 94 |
| location_response/prior_range_position | (2*C-H20prev-L20prev)/(abs(2*C-H20prev-L20prev)+(H20prev-L20prev)); H/L exclude current day | 421 | 0 |
| location_response/close_location | (2*C-H-L)/(H-L) on adjusted current daily OHLC | 335 | 6 |
| location_response/open_side_occupation | mean(sign(eight bar closes-first bar Open)) | 17 | 18 |
| location_response/wick_rejection | sum(min(O,C)-L-(H-max(O,C)))/sum(H-L) over eight bars | 426 | 8 |
| volatility_transition/range_expansion | (TRtoday-mean(TR[-21:-1]))/(TRtoday+mean(TR[-21:-1])); TR=max(H-L,abs(H-prevC),abs(L-prevC)) | 433 | 0 |
| volatility_transition/prior_range_compression | (mean(TR previous5)-mean(TR previous20))/(mean(TR previous5)+mean(TR previous20)); excludes current day | 433 | 0 |
| volatility_transition/shock_concentration | max(u^2)/sum(u^2); 0 when every observed step is zero | 434 | 0 |
| volatility_transition/gap_energy_share | g^2/(g^2+sum(u^2)); g=log(adjusted day Open/previous adjusted Close) | 364 | 71 |
| temporal_order/return_time_balance | dot(linspace(-1,1,8),u)/sum(abs(u)) | 434 | 0 |
| temporal_order/extrema_order | (earliest argmax(bar High)-earliest argmin(bar Low))/7; 0 when same bar | 15 | 43 |
| temporal_order/excursion_balance | (maximum subsequent rise-maximum subsequent fall)/sum(abs(u)) on log path [day Open,eight closes] | 413 | 12 |
| temporal_order/halfday_balance | (sum(u[4:])-sum(u[:4]))/sum(abs(u)) | 431 | 0 |
| scale_relationship/direction_alignment | efficiency5*intraday_efficiency | 423 | 12 |
| scale_relationship/drift_acceleration | (mean(r last5)-mean(r preceding15))/(abs(mean(r last5)-mean(r preceding15))+population_std(r last20)) | 434 | 0 |
| scale_relationship/intraday_daily_energy | (sum(u^2)-mean(r last20 squared))/(sum(u^2)+mean(r last20 squared)) | 434 | 0 |
| scale_relationship/nested_range_ratio | (current H-L)/(current H-L+max(H previous5)-min(L previous5)) | 412 | 0 |

## 重复信息与边界

全部24列有434条有限值；434个逐日截断重算与完整数据特征一致。相关性仅揭示表达重叠，不证明有效性或独立信息。最大的10组绝对秩相关如下：

| 表达A | 表达B | Spearman |
| --- | --- | ---: |
| intraday_efficiency | excursion_balance | 0.9786 |
| semivariance_balance | largest_step_balance | 0.9707 |
| drift5_scaled | efficiency5 | 0.9638 |
| intraday_efficiency | semivariance_balance | 0.9583 |
| semivariance_balance | excursion_balance | 0.9474 |
| return_time_balance | halfday_balance | 0.8976 |
| semivariance_balance | open_side_occupation | 0.8758 |
| intraday_efficiency | largest_step_balance | 0.8746 |
| largest_step_balance | excursion_balance | 0.8721 |
| intraday_efficiency | close_location | 0.8665 |

日OHLC和30分钟OHLC只提供价格路径的粗观测，不证明主动资金、订单簿深度或投资者身份；历史发布时点与HFQ版本可得性仍是既有局限。

## 后续验证设计

按[研究计划](protocols/research_plan.md)和[信号字典](protocols/signal_dictionary.json)开展入场收益、入场风险、未来持仓浮亏、同仓位持有价值和成交概率的分职责验证。先以纯价格基线检验家族增量，同时保留历史量价参考；逐信号训练内三分位提供可解释性，前推训练严格清除尚未知标签。

此处只完成定义与可计算性，不将24个表达称为24个有效或独立组件。历史实验资格不变。原双窗口收益、回撤、频率和稳健性目标不变，合格策略0。已有434日已反复观察，任何重切均非独立验证。

证据：[普查结果](others/census.json)、[特征表](others/features.csv)、[输入认证](others/input_refs.json)、[定义源码](src/features.py)。
