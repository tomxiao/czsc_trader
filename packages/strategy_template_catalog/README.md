# 策略模板目录（Strategy Template Catalog，STC）

本文面向策略研究员（RSCH）和首席投资官（CIO）；安装、源码维护及验证见
[开发运维交接](../../docs/DEVELOPMENT_HANDOFF.md)。

STC 是项目级策略函数模板目录。FSC 回答“可使用哪些输入 `x`”，STC 回答“用哪种受控结构
`F` 组合输入”，Optuna 将模板参数实例化为具体函数 `f`。首版提供五类适合 OPC 团队的模板：

| 模板 | 适用结构 |
| --- | --- |
| `STC-T01-WEIGHTED-SCORE` | 多个弱信息的加权评分 |
| `STC-T02-GATED-SCORE` | 机会、确认和风险否决 |
| `STC-T03-REGIME-WEIGHTED-SCORE` | 按市场状态使用不同权重 |
| `STC-T04-EVENT-HOLD` | 事件触发后固定期限持有 |
| `STC-T05-CORE-OVERLAY` | 核心仓位加战术事件轮转 |

STC 是无运行时依赖的独立包，只管理模板定义、输入角色、参数边界和确定性实例身份。它不读取
行情、不引用 FSC、不执行回测、不搜索参数、不评价候选，也不管理策略版本和交易账户。TDR
负责交叉验证 FSC 引用、在具体研究实现中落实模板语义并编排实验；SE 负责评价；SM 负责冻结
后的策略版本。

RSCH可用模板核对输入角色和参数边界，或提出模板之外的新原型；CIO可据模板身份理解候选的
结构来源。模板定义位于仓库根目录`strategy_templates/templates.json`，TDR提供查询入口：

```powershell
.\.venv\Scripts\czsc-trader.exe template validate
.\.venv\Scripts\czsc-trader.exe template list --status READY
.\.venv\Scripts\czsc-trader.exe template show --id STC-T04-EVENT-HOLD
.\.venv\Scripts\czsc-trader.exe template instantiate --spec .\prototype.json
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
候选最终使用的具体参数、SRT实现和执行规则进入候选快照与SM治理链，不写回STC。

实例化结果只证明结构合同有效；是否有可交易机会、参数是否稳健及账户表现如何，仍须交由
研究实验和完整执行评价回答。
