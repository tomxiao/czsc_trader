# 因子与信号目录（Factor & Signal Catalog，FSC）

本文面向策略研究员（RSCH）和平台开发者（DEV）。平台安装、源码维护和验证见
[DEV Agent](../../docs/DEV_AGENT.md)。

FSC管理信息族、因子和信号的稳定定义，并提供项目因子的纯计算实现，让TDR和各策略研究线
能够查询、引用和复用同一份语义与计算契约。

FSC不取数、不读取研究或实验产物，也不保存计算值、缓存、收益、实验结论或策略运行状态。
目录校验拒绝包含`research`或`experiments`路径段的实现入口；项目因子计算内聚于
[`factor_signal_catalog.calculations`](src/factor_signal_catalog/calculations.py)。CZSC注册表暴露
的是信号函数；其内部因子无法独立复现时，目录使用`embedded_factor=true`明确记录这一边界。

每条定义包含稳定ID、信息族、因果可用时间、实现入口、参数及状态。FSC负责结构、唯一性、
定义摘要及所提供计算函数的输入输出契约；研究者负责提供符合时点约束的数据，在具体标的和
窗口中物化、去冗余及验证机制。SE和FSC均不据此宣称Alpha有效。

RSCH在构建信息路径前先查询已有定义，核对因果可用时间、实现入口和参数，并在组件交付中
绑定定义身份与实验事实。目录数据位于仓库根目录`catalog/`，通过TDR Python API只读查询：

```python
from pathlib import Path
from czsc_trader.application import (
    RepositoryContext, validate_catalog, list_catalog, show_catalog,
)

context = RepositoryContext.discover(Path.cwd())
validation = validate_catalog(context)
signals = list_catalog(
    context, kind="signal", family="MARKET_STRUCTURE", status=None, query=None,
)
factor = show_catalog(context, "F-PROJECT-ER60")
```

项目因子计算从`factor_signal_catalog.calculations`显式导入，按目录定义的`implementation`核对
具体函数及输入列。公共函数接收调用方提供的DataFrame及必要的交易日历，返回独立计算结果；
不会通过TDR注册、取数或读取其他研究批次。函数的输入、日期、缺失值及输出口径以
[计算模块](src/factor_signal_catalog/calculations.py)的签名与说明为准。

```python
from factor_signal_catalog.calculations import calculate_etf_share_change

# shares及calendar由调用方按已确认的数据范围准备。
features = calculate_etf_share_change(shares, calendar)
```

定义摘要不包含计算源码，也不证明具体数据的历史可得性；实验仍须绑定实际计算依赖身份和输入证据。

`FactorDefinition.definition_sha256`和`SignalDefinition.definition_sha256`覆盖完整规范定义，
参数必须满足有限JSON值契约。阶段二使用`CatalogDefinitionRef`绑定定义类型、ID和哈希，
TDR发布／验证交付时核验定义一致性。定义哈希与实验收益证据分别保存。

状态含义：`DISCOVERED`表示已发现但语义或契约尚未完整整理；`READY`表示定义、实现和因果
可用时间已经可复用；`DEPRECATED`表示只为历史引用保留。状态不表达Alpha有效性。

`READY`只表示目录定义可复用。具体标的上的信息价值、冗余和收益贡献仍由RSCH通过实验验证；
目录状态不能替代研究员解释或用户选型决定。
