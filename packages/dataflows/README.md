# 金融数据流（Dataflows，DFLS）

本文面向策略研究员（RSCH）和首席投资官（CIO）。DFLS发布经过校验、带来源与时间身份的行情
及支持数据；策略特征、因果滞后和决策由SRT负责。安装、凭据配置、供应商适配及补丁维护见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

## RSCH：取得可用数据

在研究数据门中，先从`dataflows`顶层公开的`Dataset`确认数据集标识，再通过`Dataflows.fetch`
请求指定标的、窗口和截止日。例如：

```python
from dataflows import Dataflows, DataRequest, DataStatus, Dataset

result = Dataflows().fetch(
    DataRequest(
        dataset=Dataset.ETF_OHLCV,
        symbol="588080.SH",
        start="2026-01-01",
        end="2026-09-15",
        required_cutoff="2026-09-15",
        frequency="daily",
        options={"env_file": ".env"},
    )
)
if result.status is DataStatus.READY:
    bars, identity = result.dataframe, result.identity
else:
    raise RuntimeError(result.error or result.status)
```

`READY`表示这一次请求满足自身数据合同；`WAITING_SOURCE`、`EMPTY`、`INCOMPLETE`和`FAILED`
均不能作为完整数据使用。研究应保留`DataIdentity`、实际覆盖范围和修复记录，不能截短窗口或
自行补齐后宣称数据门通过。`required_cutoff=None`只适用于明确接受快照语义的请求。

每个`READY`结果保留原始源时间列，并在身份元数据中声明`source_time_field`、
`source_calendar`和`available_at`。跨市场、跨频率输入由SRT按策略声明做因果对齐；不要先
重索引到境内交易日历再对收益做位移。多输入策略还须由`StrategyInstance.prepare_data()`逐项
核对历史深度与截止规则；单项DFLS成功不代表整套策略已准备完成。

股票、ETF研究需区分后复权的长期经济表现与不复权的实际执行价格。Tushare是默认优先来源，
其他外部数据源须先取得用户授权；凭据不写入实验、候选包或Git。原始数据的完整性、权限和
时间语义不确定时，停止收益分析并报告阻断原因。

## CIO：核对数据证据

CIO通过`candidate review`和`candidate evaluate`使用平台封存的数据及身份，核对候选所需
数据是否完整、当时可得且与SRT运行身份一致。CIO不以手工重新抓取或修补行情替代平台体检。
供应商数据确有已登记异常时，DFLS按“校验→匹配补丁→重新校验”处理；执行过的修复会进入
`DataIdentity.metadata.repair_records`。未知异常或修复后仍不合格时明确失败，不降级发布。

数据门、源权限与策略实例的完整准备规则分别见[研究员 Agent](../../research/RSCH_AGENT.md)
和[SRT 使用说明](../strategy_runtime/README.md)。
