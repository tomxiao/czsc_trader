# 策略模板目录（Strategy Template Catalog，STC）

本文面向策略研究员（RSCH）和平台开发者（DEV）；安装、源码维护及验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

STC 是项目级策略函数模板目录。FSC 回答“可使用哪些输入 `x`”，STC 回答“用哪种受控结构
`F` 组合输入”。研究员可独立使用Optuna搜索参数，再将模板实例化为具体函数 `f`。提供五类模板：

| 模板 | 适用结构 |
| --- | --- |
| `STC-T01-WEIGHTED-SCORE` | 多个弱信息的加权评分 |
| `STC-T02-GATED-SCORE` | 机会、确认和风险否决 |
| `STC-T03-REGIME-WEIGHTED-SCORE` | 按市场状态使用不同权重 |
| `STC-T04-EVENT-HOLD` | 事件触发后固定期限持有 |
| `STC-T05-CORE-OVERLAY` | 核心仓位加战术事件轮转 |

STC 是无运行时依赖的独立包，只管理模板定义、输入角色、参数边界和确定性实例身份。它不读取
行情、不引用 FSC、不执行回测、不搜索参数、不评价候选，也不管理策略版本和交易账户。TDR
负责交叉验证FSC引用并提供受管执行入口；研究员在SRT实现中落实模板语义、编排实验；
SE负责数值评价，SM保存候选身份、用户决定和冻结版本。

RSCH可用模板核对输入角色和参数边界，或提出模板之外的新原型；模板身份记录候选的结构来源。
模板定义位于仓库根目录`strategy_templates/templates.json`，TDR提供Python API：

```python
from pathlib import Path
from czsc_trader.application import (
    RepositoryContext, validate_templates, list_templates,
    show_template, instantiate_template,
)

context = RepositoryContext.discover(Path.cwd())
validation = validate_templates(context)
templates = list_templates(context, operator=None, status="READY", query=None)
template = show_template(context, "STC-T04-EVENT-HOLD")
# 将下方JSON保存为仓库内的 .tmp/prototype.json 后执行。
instance = instantiate_template(context, context.root / ".tmp/prototype.json")
```

`prototype.json`示例：

```json
{
  "schema_version": 1,
  "template_id": "STC-T04-EVENT-HOLD",
  "bindings": [
    {
      "slot": "entry_events",
      "source_id": "SIG-CZSC-cxt_bi_base_V230228",
      "source_kind": "SIGNAL",
      "state": "向上",
      "weight": null
    }
  ],
  "parameters": {"holding_sessions": 5}
}
```

实例化只验证结构和参数，并返回确定性的 `STI-*` 身份，不代表策略有效、候选通过或获准部署。

现有模板无法表达新机制时，RSCH可提出有实验依据的平台需求，不直接改写已引用的模板定义。
候选最终使用的具体参数、SRT实现和执行规则通过TDR `register_candidate`登记，进入内容身份
和冻结治理链，不写回STC。STC不提供搜索预算管理或Optuna运行时适配器。

实例化结果只证明结构合同有效；是否有可交易机会、参数是否稳健及账户表现如何，仍须交由
研究实验和完整执行评价回答。
