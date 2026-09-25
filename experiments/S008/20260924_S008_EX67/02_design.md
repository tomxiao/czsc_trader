# S008 EX67 设计

## 固定输入

| 实验 | 文件 | SHA-256 |
| --- | --- | --- |
| EX42 | `04_conclusion.md` | `67546014dfa6e64e33cf6d928a6c151633a8f8376592d556176840ad117be4a9` |
| EX48 | `artifacts/oracle_gap_attribution.json` | `1e7fb83f05f445b8867f8fd75a36607081eeb0a88465e137acc7930bc4c43cb4` |
| EX48 | `artifacts/representative_selection.csv` | `1d985ae13704017cbf4028d2053eeea4f2f91df8a2f5d88e5b976fbfe0172136` |
| EX66 | `artifacts/search_evidence.json` | `affa05e4bec344e164efe024448c07506df49e5ed093976adf43d53bca35425c` |
| EX66 | `artifacts/search_trial_ledger.csv.gz` | `870c0fd7655aa45e45a90c82357017e7ee28ddfc6ee3c765e411605bc49c6ae8` |

## 固定计算

1. 以EX66 BuyHold年化收益乘1.5形成收益硬门，以BuyHold最大回撤形成回撤硬门。
2. 对EX66全部`COMPLETE`且具备主成本指标的trial统计两个硬门通过数量、最高年化收益、最低回撤和
   回撤合格区域内最高年化收益。
3. 读取EX48七个既有因果代表和Oracle差距，不重新筛选代表。
4. 输出确定性缺口复核及下一阶段竞争假设。

## 决策规则

同时满足以下条件时，裁决`PROCEED_TO_UPSIDE_PARTICIPATION_INFORMATION_AUDIT`：

- EX66收益门通过数量为0；
- EX66至少80%的有效trial通过回撤门；
- EX66最高年化收益低于BuyHold；
- EX48主诊断为`UPSIDE_CAPTURE_DEFICIT`；
- EX42确认目标在完美事后信息下数学可达。

否则裁决`STOP_FOR_STAGE_OBJECTIVE_REVIEW`。本实验不会因接近门槛而放宽目标。

## 竞争假设

- H1：入场与重新入场确认滞后，错过黄金趋势启动阶段，是上涨捕获不足的主要原因。
- H2：宏观、金银偏好和风险门控主要是同步或滞后过滤器，降低暴露但没有提供领先收益信息。
- H3：在0/100%、T+1和现有授权信息下，硬目标虽Oracle可达，但可能不存在可学习的稳定规则。
- H0：开发池中少数上涨阶段导致Oracle优势，所谓领先信息无法跨时期稳定复现。

下一阶段如获准，只审计能够区分H1、H2、H3和H0的领先信息；不得直接创建新原型或启动搜索。
