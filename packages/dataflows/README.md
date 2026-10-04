# 金融数据流（Dataflows，DFLS）

DFLS负责取数、规范化、校验与管理数据空间中的数据资产。业务方拥有输入清单，决定空间位置、
准备时机和引用保存位置；研究封存、候选资格、冻结及生产生效由业务方管理。

## 公共接口

```python
from pathlib import Path
from dataflows import (
    DataCoverageRequirement, Dataflows, DataRequest, DataSpace,
    Dataset, PreparePolicy, ProviderConfig,
)

flows = Dataflows(
    base_dir=Path.cwd(),
    space=DataSpace(Path(".tmp/dataflows-example")),
    providers=ProviderConfig(env_file=Path(".env")),
)
request = DataRequest(
    dataset=Dataset.ETF_OHLCV,
    symbol="588080.SH",
    start="2026-09-14",
    end="2026-09-15",
    required_cutoff="2026-09-15",
    frequency="daily",
    coverage=DataCoverageRequirement(minimum_observations=2, minimum_sessions=2),
)
prepared = flows.prepare((request,), policy=PreparePolicy.REUSE)
if not prepared.ready:
    raise RuntimeError(prepared.items)
result = flows.fetch(request, prepared=prepared.reference)
if not result.ready:
    raise RuntimeError(result.error)
bars, identity = result.dataframe, result.identity
```

示例使用临时空间；正式空间由业务方配置。PTE、研究和候选/冻结回测的主调方接入尚待独立评审。
本次接口替换不提供旧`Dataflows()`、隐式取数`fetch(request)`、`LocalCacheConfig`或`options`兼容层。

| 接口 | 契约 |
| --- | --- |
| `Dataflows(base_dir, space, providers)` | 三项均为必填关键字参数；初始化并核验数据空间 |
| `prepare(requests, policy=...)` | 非空`tuple[DataRequest, ...]`；取数或复用、校验、持久化，返回逐项结果和批次状态 |
| `fetch(request, prepared=...)` | 强制绑定`PreparedDataRef`；只读本地资产，重新核验并返回请求范围的数据 |

`PrepareStatus.READY`要求所有输入满足各自契约且重叠数据一致，才返回`PreparedDataRef`。
`PARTIAL`表示仅部分输入成功；`FAILED`表示整批失败或无成功项。未完整准备的批次没有引用；
部分成功资产可供下一次`REUSE`复用。逐项状态保留`WAITING_SOURCE`、`EMPTY`、`INCOMPLETE`、`FAILED`
及结构化错误，失败结果不暴露可用数据。

同批相同取数选择只访问一次供应商，分别检查各项验收要求。`REUSE`复用满足本批要求的资产，
缺失或覆盖不足时取源；`REFRESH`显式访问数据源。源失败、损坏资产和冲突内容均明确失败。
`fetch`不会补数、访问网络或切换来源。

## 强类型契约

公共类型从[dataflows](src/dataflows/__init__.py)导入，字段定义见[contract.py](src/dataflows/contract.py)。

- `DataSpace(path: Path)`：相对`base_dir`的非空路径，拒绝绝对路径、`..`及越界符号链接。
- `DataRequest`：有限`Dataset`、标的、ISO起止日期/时间、截止要求、合法频率和数据集专用参数。
  日期形式的`end`包含当天；时间戳包含该精确时刻。日期形式的截止要求按日检查。
- `DataCoverageRequirement`：`minimum_observations`为记录数，`minimum_sessions`为不同来源日期数，
  `maximum_start_lag_days`为起点最大自然日偏移。交易日历、应有交易日及停牌判断仍由数据集校验负责。
- `NoParameters`、`PcfParameters`、`MoneyflowParameters`、`EvidenceParameters`替代任意`options`字典。
  参数类型与数据集不匹配时，在构造请求时拒绝。
- `ProviderConfig`：宿主凭据文件及可选的`Dataset → ProviderBinding`映射；默认使用内置适配器。
  显式映射仅注册列出的数据集，不自动补默认来源。
- `ProviderBinding(name, revision, fetch)`：来源实现及语义版本；适配器返回规范化DataFrame和来源元数据。
  自定义适配器或来源语义改变时必须修改`revision`。凭据文件路径不进入数据请求和资产身份。
- `PreparedDataRef`：空间UUID、准备UUID及清单哈希，可由业务方序列化保存、进程重启后恢复使用。
  构造时UUID字段使用`UUID`对象；没有路径、封存标志或生命周期审批状态。

`DataIdentity`记录来源、内容哈希、实际覆盖及时间口径；`DataResult.prepared`记录读取绑定。
返回切片的内容哈希对应实际返回的数据。同一准备引用支持已准备范围内的子集；多项区间不会自动
拼接为更大的请求。资金流显式日期参数可读取已准备日期集合的子集。

## 数据空间与资产管理

每个空间使用`assets.sqlite3`管理数据资产、请求索引和准备清单。空间UUID独立于机器绝对路径，
完整复制空间后仍可用原引用读取。内部表与文件布局属于DFLS实现，调用方通过公开接口访问。

复用依据包括数据集、标的、频率、取数参数、范围、供应商标识/版本及DFLS实现版本。
截止日和覆盖阈值属于验收要求，每次单独检查。DFLS代码或适配器版本变化会阻止新准备复用旧实现的索引。
旧引用继续读取原资产，并经过当前校验逻辑；校验规则改变后可能明确失败。

数据内容身份包含字段、类型、分类域、索引和值。相同资产去重；刷新写入新资产与新准备记录，
保留旧引用对应的版本。首次入库时间与准备时间分别记录UTC事实，不参与内容去重。
数据资产同时承担复用功能；没有另一套缓存目录、TTL或自动删除策略。本版本不提供资产清理API，
业务方须保留有效引用所依赖的完整空间。

SQLite事务串行化同空间写入，锁等待上限60秒；首次创建使用完整数据库的原子发布。
损坏文件不自动重建，事务失败不发布引用。读取核验空间身份、清单哈希、资产字节及内容身份，
每次返回独立DataFrame。`SPACE_*`、`ASSET_*`、`PREPARATION_*`错误通过结构化状态返回；
初始化阶段的路径、空间损坏或版本问题直接抛出异常，阻止创建不可用对象。

存储使用pickle保留pandas类型、时区和精度，因此空间必须只允许可信本地进程写入；
外部数据库文件不能直接作为可信数据空间导入。读取失败不会回退到供应商或其他资产版本。

## 数据校验与研究证据边界

多频行情通过`validate_a_share_intraday_bars`与`validate_intraday_against_daily`检查；
分钟准备检查完整交易日，读取已准备资产允许显式盘中切片。已登记供应商异常按
“校验→匹配补丁→重新校验”处理，修复记录进入`DataIdentity.metadata.repair_records`。
未知异常或修复后不合格时明确失败。

每项数据保留来源时间、来源日历、可用时点和价格口径。股票、ETF信号用后复权经济表现时，
须与实际执行使用的不复权价格区分。跨市场、跨频率因果对齐、策略预热和完整输入清单由业务方负责；
`READY`不自动证明历史可得性、研究有效性或交易资格。凭据不能写入数据请求、实验包或Git。

本地特征证据在`prepare`时核对路径和文件哈希，随后保存为数据资产；`fetch`读取已准备版本，
原外部文件的后续变化不会改写旧引用。获取新版本须提交新的证据参数并重新准备。

模块测试使用离线夹具，不访问真实供应商或生产环境：

```powershell
.\.venv\Scripts\python.exe -m pytest packages/dataflows/tests/functional -q
```
