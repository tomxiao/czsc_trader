# 策略评估器（SE）

SE提供确定性的指标、协议校验、比较、帕累托分层、PBO、DSR、Bootstrap、参数邻域、压力及账本审计计算。先阅读[公共导出](src/strategy_evaluator/__init__.py)，再沿导入核对契约与测试。

研究员通过TDR受管评价API取得SRT/TXE账户事实，再组合SE公共函数。SE不获取行情、不加载策略、不写治理状态。旧资格裁定、冻结健康政策、自动冻结建议及对应报告入口已删除。

`validate_protocol`、`screen_candidates`、`rank_candidates`保留已有协议驱动的比较计算；它们不等同于RSCH阶段四的完整排序政策。阶段四按已批准协议调用`pareto_layers`及所需诊断，不自行新增经济硬门。统计风险标签不等于冻结决定或未来成功概率。

平台只校验结构、计算和证据一致性，研究员解释结果，用户决定选型。新冻结工具仍待实现，见[RSCH契约](../../research/RSCH_AGENT.md)。

## `compare_ledgers`：保留原始身份的账本比较

调用方传入两份`ReplayEvidence`和强类型请求，SE只在内部副本上做比较，不改写原证据。

```python
from strategy_evaluator import (
    LedgerComparisonMode, LedgerComparisonRequest, compare_ledgers,
)

# left、right 是两份完整的 ReplayEvidence。
result = compare_ledgers(LedgerComparisonRequest(
    left=left,
    right=right,
    mode=LedgerComparisonMode.ECONOMIC,
    tolerance=0.0,
))
```

| 模式 | 比较规则 |
| --- | --- |
| `STRICT`（默认） | 保留策略哈希及全部决策、订单、成交、周期身份进行比较 |
| `ECONOMIC` | 忽略`strategy_hash`，对五张账本中的顶层`decision_id/order_id/fill_id/cycle_id`作一一对应重命名；保留业务字段、附加列、行顺序及引用关系 |

比较前核验证据JSON可序列化且数值有限、已填写的内容哈希、账户日期覆盖、身份唯一性和关联引用。
`data_hash`、初始资金、评价日期、执行规则及日内／日线执行数据必须精确一致；
`tolerance`仅用于其他数值字段的绝对误差比较，必须有限且非负。

`LedgerComparisonResult`包含`status`、`mode`、两侧原始证据哈希及最多20条
`LedgerDifference(path, reason)`。无法计算有效哈希时对应哈希为`None`。

| 状态 | 含义 |
| --- | --- |
| `EQUIVALENT` | 在指定模式和容差下等价 |
| `DIFFERENT` | 上下文可比，账本内容存在差异 |
| `INCOMPARABLE` | 数据、资金、窗口或执行上下文存在差异 |
| `INVALID` | 证据序列化、内容哈希、日期覆盖或引用关系不合格 |

经济等价模式仍比较诊断等附加字段；相同成交并不自动得到`EQUIVALENT`。
账本比较用于定位两次运行的差异，执行正确性仍由`audit_replay`独立审计。

## 基准整手审计

`BenchmarkEvidence`必须显式填写正整数`lot_size`，拒绝布尔值及浮点数；该字段进入序列化结果
和证据哈希。基准审计独立复算整手取整、现金、持仓、费用及净值，不调用TXE重放作为审计答案。
BuyHold及MA5/MA20的基准证据必须携带实际现金与持仓数量，不能只提供仓位比例收益。
历史证据保持原样；新证据按当前合同生成，不补写旧档案。

## `pareto_layers`：输入适配

先阅读[公共导出](src/strategy_evaluator/__init__.py)，核对`CandidateProfile`和[分层实现](src/strategy_evaluator/pareto.py)。函数按`worst_scores`执行各指标越大越好的帕累托分层，返回带`pareto_layer`的配置；不自带研究目标核验、层内排序或缺失值政策。

| 检查 | 调用方要求 |
| --- | --- |
| 指标集合 | 每个配置的指标键必须一致；当前实现按双方键的交集比较 |
| 数值 | 参与分层的数值必须有限 |
| 方向 | 越大越好；收益／回撤双指标分层传入净年化及负的最大回撤幅度 |
| 缺失 | 影响比较的缺失值标记不可比，不填零或静默丢弃指标 |
| 政策 | 研究目标核验及层内排序由调用方按已冻结协议执行 |

最小适配测试应覆盖指标键不一致、非有限值、完全并列及已知支配关系。工具分层结果不替代研究员解释或用户选型。
