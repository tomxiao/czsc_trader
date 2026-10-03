# 因子与信号目录（Factor & Signal Catalog，FSC）

本文面向策略研究员（RSCH）和平台开发者（DEV）。平台安装、源码维护和验证见
[DEV Agent](../../docs/DEV_AGENT.md)。

FSC是项目级“弹药目录”。它记录信息族、因子和信号的稳定定义，让TDR和各策略研究线能够
查询、引用和复用同一份语义契约。

FSC只管理定义，不保存标的计算值、缓存、收益、实验结论或策略运行状态。CZSC注册表暴露
的是信号函数；其内部因子无法独立复现时，目录使用`embedded_factor=true`明确记录这一边界，
不会把信号伪装成因子。

每条定义包含稳定ID、信息族、因果可用时间、实现入口、参数及状态。FSC负责结构校验、唯一性
校验和确定性摘要；研究者负责在具体标的和窗口中物化、去冗余及验证机制，SE和FSC均不据此
宣称Alpha有效。

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

`FactorDefinition.definition_sha256`和`SignalDefinition.definition_sha256`覆盖完整规范定义，
参数必须满足有限JSON值契约。阶段二使用`CatalogDefinitionRef`绑定定义类型、ID和哈希，
TDR发布／验证交付时核验定义一致性。定义哈希与实验收益证据分别保存。

状态含义：`DISCOVERED`表示已发现但语义或契约尚未完整整理；`READY`表示定义、实现和因果
可用时间已经可复用；`DEPRECATED`表示只为历史引用保留。状态不表达Alpha有效性。

`READY`只表示目录定义可复用。具体标的上的信息价值、冗余和收益贡献仍由RSCH通过实验验证；
目录状态不能替代研究员解释或用户选型决定。
