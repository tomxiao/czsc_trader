# S011 · MANDATE · 1

研究员声明状态：COMPLETE
归属：研究任务治理

技术校验验证结构、身份与证据引用；阶段推进和研究结论由研究员与用户决定。

[完整机器契约](delivery.json)

## 阶段内容


| 项目 | 类别 | 内容 | 确认状态 | 强类型约束 |
| --- | --- | --- | --- | --- |
| symbol | TRADABLE_SYMBOL | 159326.SZ；000300.SH和SPX为输入，不扩大交易标的。 | CONFIRMED | — |
| benchmark | BENCHMARK | 同标的、窗口、资金和成本；原限价基准的显式整手、溢价、价位和拆单契约。 | CONFIRMED | {'benchmark_id': 'BuyHold', 'kind': 'BUYHOLD', 'execution_version': 'buyhold-execution-v1', 'execution': {'type': 'LimitBuyHold', 'lot_size': 100, 'premium': 0.003, 'price_tick': 0.001, 'price_limit_ratio': 0.1, 'maximum_order_quantity': 1000000}} |
| horizon | HORIZON | 完整开发池2025-02-06至2026-09-28；403交易日。 | CONFIRMED | — |
| return | OBJECTIVE | CAGR≥1.5×基准；基准非正时还须策略为正且高于基准。 | CONFIRMED | (ResearchTarget(target_id='return_multiple', metric=&lt;ResearchMetric.NET_ANNUAL_RETURN: 'NET_ANNUAL_RETURN'&gt;, lower=BenchmarkBound(multiplier=1.5, inclusive=True), upper=None, when=None), ResearchTarget(target_id='positive_if_nonpositive_benchmark', metric=&lt;ResearchMetric.NET_ANNUAL_RETURN: 'NET_ANNUAL_RETURN'&gt;, lower=ConstantBound(value=0.0, inclusive=False), upper=None, when=BenchmarkCondition(metric=&lt;ResearchMetric.NET_ANNUAL_RETURN: 'NET_ANNUAL_RETURN'&gt;, operator=&lt;ComparisonOperator.LE: 'LE'&gt;, value=0.0)), ResearchTarget(target_id='excess_if_nonpositive_benchmark', metric=&lt;ResearchMetric.NET_ANNUAL_RETURN: 'NET_ANNUAL_RETURN'&gt;, lower=BenchmarkBound(multiplier=1.0, inclusive=False), upper=None, when=BenchmarkCondition(metric=&lt;ResearchMetric.NET_ANNUAL_RETURN: 'NET_ANNUAL_RETURN'&gt;, operator=&lt;ComparisonOperator.LE: 'LE'&gt;, value=0.0))) |
| drawdown | CONSTRAINT | 最大回撤幅度严格小于同口径基准。 | CONFIRMED | (ResearchTarget(target_id='strict_drawdown', metric=&lt;ResearchMetric.DRAWDOWN_MAGNITUDE: 'DRAWDOWN_MAGNITUDE'&gt;, lower=None, upper=BenchmarkBound(multiplier=1.0, inclusive=False), when=None),) |
| frequency | CONSTRAINT | 60×全部闭合交易笔数÷完整样本交易日数在[4,6]内。 | CONFIRMED | (ResearchTarget(target_id='full_frequency', metric=&lt;ResearchMetric.FULL_SAMPLE_FREQUENCY: 'FULL_SAMPLE_FREQUENCY'&gt;, lower=ConstantBound(value=4.0, inclusive=True), upper=ConstantBound(value=6.0, inclusive=True), when=None),) |
| frequency_window | EXECUTION | 全样本交易频率折算为60交易日。 | CONFIRMED | frequency_window_days: [60.0, 60.0] sessions |
| execution | EXECUTION | 初始100万元；lot_size=100；只多不杠杆；LIMIT买、MARKET卖；标准每侧10bp，压力20bp为诊断。 | CONFIRMED | — |
| permission | DATA_PERMISSION | 现有S011数据权限；所有复算均为已见开发池；阶段五、冻结及部署另行推进。 | CONFIRMED | — |

symbol 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

benchmark 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

horizon 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

return 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

drawdown 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

frequency 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

frequency_window 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

execution 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

permission 确认来源：[attachments/confirmed_mandate_source.json](<attachments/confirmed_mandate_source.json>)

## 事实

| ID | 值 | 单位 | 状态 | 缺失原因 |
| --- | --- | --- | --- | --- |

## 解释


## 未完成事项


## 复算

用公共validate_delivery验证；新实验复算，不覆盖封存原件。组装源码见附件build_deliveries.py。

数据访问：原S011权限范围；当前复算经DFLS；历史原件仅按显式原字节哈希引用，不承诺旧回执机器复验。

确定性及容差：原输入逐字节封存；身份和浮点公式版本显式记录。所有研究结果属于已见开发池。

