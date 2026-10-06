# 金融数据流（Dataflows，DFLS）研究员使用手册

DFLS负责获取、规范化、校验和保存研究所需的数据。研究员声明标的、窗口、频率和数据用途，
通过`prepare`准备数据，再持准备引用调用`fetch`读取。研究输入范围、决策时点、策略预热和
实验结论由研究员负责；`prepare`返回`READY`表示数据满足本次准备请求的契约。

正式研究通过TDR的`ResearchContext`共用批次数据空间`research/<批次>/data/`。
`research_context.data`用于准备和读取；研究评价、回测及候选技术检验使用同一批次空间。
直接调用DFLS时，由调用方显式配置空间并保存准备引用。历史数据空间保留原位。
以下示例使用`.tmp/`下的独立空间，适合试用和验证。

## 1. 先选择数据用途

研究信号和成交、估值所用的价格口径应在输入清单中分别声明。
后复权行情调整了历史价格和成交量，用于研究收益表现；不复权行情保留实际市场成交价格，
用于执行和估值。DFLS处理单位换算及复权，返回标准字段`Date`、`Open`、`High`、`Low`、
`Close`、`Volume`、`Amount`，必要时附带`AvailableDate`。

| 数据集 | 市场与频率 | 研究用途 |
| --- | --- | --- |
| `Dataset.ETF_OHLCV` | A股ETF；`daily`、`weekly`、`1m`、`5m`、`15m`、`30m` | 后复权研究行情 |
| `Dataset.STOCK_OHLCV` | A股股票；`daily`、`weekly`、`1m`、`5m`、`15m`、`30m` | 后复权研究行情 |
| `Dataset.STOCK_OHLCV` | 港股，如`00700.HK`；`daily`、`weekly`、`30m` | 当前接入原始行情，周线由日线聚合 |
| `Dataset.STOCK_OHLCV` | 美股，如`AAPL`；`daily`、`weekly` | 当前接入原始行情，周线由日线聚合 |
| `Dataset.ETF_UNADJUSTED_DAILY` / `Dataset.STOCK_UNADJUSTED_DAILY` | 对应A股资产；`daily` | 不复权成交价格和估值价格 |
| `Dataset.ETF_UNADJUSTED_INTRADAY` / `Dataset.STOCK_UNADJUSTED_INTRADAY` | 对应A股资产；`1m`、`5m`、`15m`、`30m` | 不复权日内成交价格和估值价格 |

以上为内置Tushare适配器的范围。实际可获取的窗口取决于账户权限、历史深度和供应商数据。
港股分钟线目前按常规完整交易时段检查，半日市尚未自动识别。跨市场数据接入与该市场的
策略回测、交易链路就绪情况应分别确认。

宏观、资金流、指数、期货、申赎篮子等输入也使用同一套准备和读取接口。
完整数据集及请求参数见公开[契约定义](src/dataflows/contract.py)，公共类型统一从
[dataflows](src/dataflows/__init__.py)导入。

## 2. 准备数据并读取

在项目根目录运行下面的示例。凭据文件由运行环境提供，Tushare优先读取环境变量
`TUSHARE_TOKEN`，其次读取显式指定的凭据文件。凭据应保留在运行环境中。

```python
from pathlib import Path
from dataflows import Dataflows, DataRequest, DataSpace, Dataset, PreparePolicy, ProviderConfig

root = Path.cwd()
flows = Dataflows(
    base_dir=root,
    space=DataSpace(Path(".tmp/dataflows-example")),
    providers=ProviderConfig(env_file=root / ".env"),
)
requests = tuple(
    DataRequest(
        dataset=Dataset.ETF_OHLCV,
        symbol="588080.SH",
        start="2026-09-14",
        end="2026-09-15",
        required_cutoff="2026-09-15",
        frequency=frequency,
    )
    for frequency in ("daily", "30m")
)
prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
if not prepared.ready:
    for item in prepared.items:
        print(item.request.symbol, item.request.frequency, item.status, item.error)
    raise RuntimeError("数据准备未通过，请按逐项错误处理")

reference = prepared.reference
results = {}
for request in requests:
    result = flows.fetch(request, prepared=reference)
    if not result.ready:
        raise RuntimeError(result.error)
    results[request.frequency] = result

daily_bars = results["daily"].dataframe
minute_bars = results["30m"].dataframe
```

`prepare`接收非空`tuple[DataRequest, ...]`。同批所有请求通过且重叠数据一致时，
才返回可供读取的`PreparedDataRef`。仅请求日线时，DFLS按日线要求验收，无需获取分钟线。
请求分钟线时，DFLS另外获取独立日线锚，并同时验收两者。
需要单独读取日线时，将日线请求也纳入准备批次，如上例所示。

| 调用方式 | 何时使用 | 行为 |
| --- | --- | --- |
| `prepare(..., policy=PreparePolicy.REUSE)` | 重复研究、恢复工作 | 复用满足当前请求的资产；缺失、覆盖不足或实现版本变化时重新取源 |
| `prepare(..., policy=PreparePolicy.REFRESH)` | 明确获取供应商当前版本 | 重新取源、校验，成功后保存取得的数据版本和新的准备引用 |
| `fetch(request, prepared=reference)` | 读取已准备的研究输入 | 校验准备引用、当前实现修订和资产完整性，裁取已准备范围内的数据；不重做子窗口质量验收，不访问供应商 |

`DataSpace.path`必须相对`base_dir`。空间位置属于调用方配置，准备引用必须与对应空间配套。
只读的`flows.binding`返回`DataSpaceBinding(base_dir, space, space_id)`，可用于确认宿主配置的
绝对基准目录、相对空间和空间UUID；调用方无需访问DFLS内部存储对象。

## 3. 声明窗口与额外覆盖要求

`start`和`end`使用ISO日期或时间戳。日期形式的`end`包含当天；时间戳形式包含指定时刻。
`required_cutoff`表示实际数据必须达到的截止日期或时刻；允许为`None`。
OHLCV仍须满足整个请求窗口的交易日完备率要求。

OHLCV的交易日分母由请求窗口、对应交易所日历和标的上市日期确定。
上市前日期不适用；上市后的应有开市日全部纳入。缺失日期不会自动按停牌解释。

需要最少记录数、最少交易日数或限制实际起点偏移时，增加`DataCoverageRequirement`：

```python
from dataflows import DataCoverageRequirement

long_request = DataRequest(
    dataset=Dataset.ETF_OHLCV,
    symbol="588080.SH",
    start="2020-01-01",
    end="2026-09-30",
    required_cutoff="2026-09-30",
    frequency="daily",
    coverage=DataCoverageRequirement(
        maximum_start_lag_days=None,
        minimum_sessions=252,
    ),
)
```

`minimum_observations`统计记录数，`minimum_sessions`统计不同来源日期数。
`maximum_start_lag_days`限制实际起点比请求起点晚多少个自然日。
该字段在`DataCoverageRequirement`中的默认值为`0`；如只需数量要求，并允许请求窗口包含
上市前日期或非交易日，应像上例一样显式设置为`None`，继承来源的起点约束。
数量要求与OHLCV逐交易日完备性分别验收。

## 4. OHLCV通过规则

一次准备先执行现有结构、时间、身份及数值校验，按已登记且适用的可信补丁修复，
再对修复后的序列统计完备率和准确率。

| 请求 | 完备率要求 | 准确率要求 |
| --- | --- | --- |
| 日线 | 应有交易日全部有日线，即100% | 准确交易日数 / 应有交易日数 ≥99% |
| 分钟线的日线锚 | 应有交易日全部有日线，即100% | 日线准确率 ≥99% |
| 分钟线 | 应有交易日及对应频率的应有柱全部齐全，即100% | 准确交易日数 / 应有交易日数 ≥95% |

分钟请求须同时满足日线锚和分钟线两项要求。周线由底层日线验收并核对聚合结果，
其质量统计分母仍为交易日。

日线准确性检查成交均价`Amount / Volume`是否处于当日`Low`至`High`范围内，
使用现有价格容差；非正成交量的日线判为不准确。
分钟线按日聚合：首柱开盘、最高价、最低价、末柱收盘、成交量及成交额汇总与独立日线锚核对。
任一字段超出容差，该交易日判为不准确；一天多个字段异常只计一个不准确交易日。

现有容差为：价格绝对差不超过`0.005`；成交量、成交额相对差不超过`1e-5`（0.001%），
相对差分母为`max(abs(日线值), 1)`，另忽略浮点运算误差。
容差适用于实际校验使用的价格和单位口径。

达到准确率门槛时，数据可以包含少量不准确交易日，这些日期及异常字段会保留在质量证据中。
可信补丁没有覆盖的自洽偏差计入准确率；缺日、缺柱、结构非法、身份或证据不一致等问题仍会阻断。
研究员可查看异常对自身组件的影响，研究结论按已确认的目标和约束作出。

## 5. 查看结果与处理失败

批次状态`READY`表示全部请求通过；`PARTIAL`表示部分通过；`FAILED`表示全部未通过。
`PARTIAL`和`FAILED`均没有准备引用。部分成功的资产可供下一次`REUSE`复用。
具体原因应查看`prepared.items`中每个请求的状态及`error`。

| 逐项状态 | 含义 | 建议处理 |
| --- | --- | --- |
| `READY` | 本次请求满足数据契约 | 保存引用，读取数据及质量证据 |
| `WAITING_SOURCE` | 来源尚未达到可用时点 | 核对来源更新时间，再重新准备 |
| `EMPTY` | 来源或读取范围没有记录 | 核对标的、上市日期、窗口及账号权限 |
| `INCOMPLETE` | 缺日、缺柱或其他覆盖要求未满足 | 查看缺失明细，核实数据缺口；调整研究窗口须符合研究授权 |
| `FAILED` | 准确率不足、结构非法、身份或证据不一致、来源调用失败等 | 查看错误代码和上下文，必要时交DEV定位 |

失败结果不提供可用数据。`error`包含`code`、`message`、`context`和`retryable`；
仅更换调用方式或反复刷新不能保证消除数据问题。

成功读取后，可直接查看质量统计、逐日证据和修复记录：

```python
metadata = results["30m"].identity.metadata
quality = metadata["ohlcv_quality"]
print("交易日数：", quality["total_sessions"])
for kind in ("daily", "minute"):
    detail = quality[kind]
    print(kind, "完备率：", detail["completeness"], "准确率：", detail["accuracy"])
    print("缺失日期：", detail["incomplete_dates"])
    print("不准确日期：", detail["inaccurate_dates"])

sessions = metadata["ohlcv_quality_evidence"]["sessions"]
for day in quality["minute"]["inaccurate_dates"]:
    print(day, sessions[day]["minute_fields"], sessions[day]["minute_differences"])
print("可信修复记录：", metadata.get("repair_records", []))
```

完备率和准确率字段取值为0至1；例如`0.9831`约为98.31%。
`prepared.items`的身份及质量结果用于确认本次`prepare`请求的验收范围。
`fetch`继承已保存资产的质量证据；读取子窗口时不会重统计该子窗口的准确率，
返回数据的`data_start`、`data_cutoff`和内容哈希会按实际切片更新。
`daily_session_coverage`记录交易日分母和上市依据；`repair_records`记录适用补丁及修复日期。
若准备失败，质量统计可能位于`item.error.context["quality"]`；其他硬错误应按具体上下文判读。

## 6. 保存引用、恢复工作与读取子窗口

实验应保存准备引用及使用的数据请求。准备引用包含空间UUID、准备UUID和清单哈希，
可序列化保存，并在进程重启后恢复。以下接续前面的示例：

```python
import json
from uuid import UUID
from dataflows import PreparedDataRef

reference_file = root / ".tmp/dataflows-example/prepared-reference.json"
reference_file.write_text(json.dumps({
    "space_id": str(reference.space_id),
    "preparation_id": str(reference.preparation_id),
    "manifest_sha256": reference.manifest_sha256,
}, indent=2), encoding="utf-8")

saved = json.loads(reference_file.read_text(encoding="utf-8"))
restored_reference = PreparedDataRef(
    space_id=UUID(saved["space_id"]),
    preparation_id=UUID(saved["preparation_id"]),
    manifest_sha256=saved["manifest_sha256"],
)
restored = flows.fetch(requests[0], prepared=restored_reference)
if not restored.ready:
    raise RuntimeError(restored.error)
```

正式研究应在结果证据中保存使用的准备引用及请求，并保留对应批次数据空间。
复制或迁移空间时应保留完整空间身份和资产；单独保存引用不能恢复丢失的数据。
批次数据默认不由Git跟踪，Git clone不能保证恢复本地数据；跨机器继续计算须另行保存或迁移空间。

同一引用支持已准备范围内、选择条件一致的子请求。`fetch`验证空间UUID、准备清单哈希、
当前DFLS实现修订及资产内容和身份；读取超出准备范围、空数据或相互冲突的资产会明确失败。
完成这些检查后，直接裁取数据，不再对该子窗口重新执行OHLCV、覆盖或准确率验收。
因此已验收大窗口中的少量异常日不会仅因子窗口准确率降低而触发新的拒绝；
研究员继续按已保存的逐日证据判断其对研究结论的影响。多个准备区间不会自动拼接为一个更大的请求。

`REFRESH`成功后产生新引用，旧引用仍指向原资产，不会随刷新改指新版本。
旧引用读取须与当前DFLS实现修订一致；修订不一致时返回`PREPARATION_VALIDATION_REQUIRED`，
应重新`prepare`取得当前验收的引用。历史研究记录继续保留其原引用及结果，
新准备不改写历史引用和结论。

## 7. 其他研究输入与时间边界

非OHLCV数据按各自的字段、覆盖、时间和证据契约验收，上述99%／95%规则仅适用于OHLCV。

- 宏观序列按数据集指定标的参数；例如SHIBOR、美国国债收益率等固定序列要求`symbol=None`。
- 申赎篮子、资金流及本地特征证据使用`PcfParameters`、`MoneyflowParameters`、
  `EvidenceParameters`等公开类型，参数须与数据集匹配。
- 本地特征证据准备时核对源文件及哈希，读取时使用已准备版本。源文件变化后，
  获取新版本需要新的证据参数及准备引用。
- 决策时点应结合`DataIdentity.temporal_contract`及可用时间字段检查。
  历史K线完成时间、供应商发布时间和研究决策可用时间应分别确认。
- 跨市场、跨频率对齐和策略预热由研究流程声明；DFLS的`READY`不自动证明历史可得性、
  策略有效性或交易资格。

新增数据来源或修改来源语义时，由DEV提供明确的`ProviderBinding`和版本，研究员使用其
已约定的契约。自定义OHLCV来源也须提供可核验的日历、日线锚和质量证据。
