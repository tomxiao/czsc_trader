# 金融数据流（Dataflows，DFLS）

本文面向策略研究员（RSCH）和平台开发者（DEV）。DFLS发布经过校验、带来源与时间身份的行情
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

## DEV：配置本地缓存

缓存通过现有`Dataflows.fetch(DataRequest)`使用，由宿主显式配置；默认不启用。

```python
from datetime import timedelta
from pathlib import Path
from dataflows import CachePolicy, Dataflows, LocalCacheConfig

cache = LocalCacheConfig(
    root=Path(".tmp/dataflows-cache"),
    namespace="research-provider-v1",
    max_age=timedelta(hours=24),
    policy=CachePolicy.READ_THROUGH,
)
flows = Dataflows(env_file=Path(".env"), cache=cache)
# 继续调用 flows.fetch(DataRequest(...))，请求契约不变。
```

`root`必须是`Path`，`namespace`不能为空，`max_age`必须是正的`timedelta`，
`policy`必须使用`CachePolicy`枚举。请求中的`options.env_file`优先于宿主配置，
宿主配置不修改进程环境变量。`env_file`不参与缓存键；供应商、权限或数据语义变化时，
调用方必须更换命名空间，防止复用另一来源的数据。

| 策略 | 行为 |
| --- | --- |
| `READ_THROUGH` | 有效命中直接读取；缺失或过期时访问数据源并缓存成功结果 |
| `REFRESH` | 显式访问数据源，成功后原子替换缓存 |
| `CACHE_ONLY` | 只读取有效缓存；缺失或过期时明确失败 |

只有`READY`结果写入缓存。命中保留`DataIdentity`、DataFrame类型及索引，并返回独立数据对象；
读取时核验内容哈希、请求身份和覆盖要求。请求窗口、截止日及覆盖条件均参与缓存键。
`STRATEGY_FEATURE_EVIDENCE`直接走原有证据校验流程，避免缓存绕过本地文件身份检查。

缓存使用每键SQLite事务协调跨进程访问，锁等待上限为60秒。内部序列化使用pickle，
缓存目录只允许可信本地进程写入，不导入外部缓存文件作为研究证据。
缓存错误返回`DataStatus.FAILED`，错误码包括`CACHE_KEY_INVALID`、`CACHE_MISS`、
`CACHE_EXPIRED`、`CACHE_CORRUPT`、`CACHE_IO_ERROR`和`CACHE_LOCK_TIMEOUT`。
损坏缓存直接失败；源请求失败时保留源状态，不返回陈旧数据。刷新失败不会覆盖原缓存。

同一个`Dataflows`可注入`StrategyRuntime(dataflows=flows)`、TDR回测或探索上下文。
正式实验通过`create_formal_experiment_context(..., cache=cache)`配置平台拥有的数据入口，
详见[REX说明](../research_experiment/README.md)。DFLS缓存与SRT实例准备结果分别管理；
刷新DFLS缓存不会重写已认证的SRT实例数据。

## 核对数据证据

研究员通过公开数据API和受管实验端口核对来源、身份、覆盖及历史可得性。不以手工抓取或修补行情绕过合同。
供应商数据确有已登记异常时，DFLS按“校验→匹配补丁→重新校验”处理；执行过的修复会进入
`DataIdentity.metadata.repair_records`。未知异常或修复后仍不合格时明确失败，不降级发布。

数据门、源权限与策略实例的完整准备规则分别见[研究员 Agent](../../research/RSCH_AGENT.md)
和[SRT 使用说明](../strategy_runtime/README.md)。

## 研究输入契约与口径

以下是调用方的研究合同要求；现有类型与能力先查[公共导出](src/dataflows/__init__.py)。DFLS成功状态不自动证明历史可得性或研究合同成立。

| 项目 | 记录或核验要求 |
| --- | --- |
| 正式来源 | 正式实验通过REX上下文访问DFLS受管数据与身份 |
| 来源说明 | 来源、覆盖、单位、价格口径、可用时点、缺失及历史修订风险 |
| 因果可得性 | 核验数据及复权调整信息在实际决策时点是否可得 |
| 跨市场对齐 | 由SRT按决策时点对齐 |
| 跨市场来源身份 | 保留来源日期、时区及陈旧程度 |
| 信号价格 | 连续收益、趋势及量价信号默认使用后复权价格 |
| 窗口 | 分别声明输入预热、信号计算、成交评价及数据截止窗口 |
| 口径不符 | 保留失败证据，由后继实验承接修订 |

交易和账户价格要求见[TXE说明](../trading_execution_engine/README.md)。研究员仍须判断输入是否适用于当前机制，不能以工具校验代替因果判断。
