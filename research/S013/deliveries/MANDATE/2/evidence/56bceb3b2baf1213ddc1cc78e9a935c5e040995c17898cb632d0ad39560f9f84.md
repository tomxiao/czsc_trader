# S013 研究交接

## 当前身份

- 策略族：`S013 / S013｜510500ETF策略研究`；
- 初始范围：`["510500.SH"]`；
- 研究状态：`RESEARCHING`；
- 当前没有候选、冻结版本或PTE账户。

## 研究意图

```json
{
  "symbol": "510500.SH",
  "asset_type": "etf",
  "stage": "MANDATE",
  "status": "REGISTERED",
  "development_pool": {
    "start": "2020-01-01",
    "end": "2026-09-30",
    "inclusive": true,
    "use": "开发池，可用于研究与参数搜索"
  },
  "performance_targets": {
    "annual_return": {
      "requirement": "策略年化收益 >= 1.5倍同期buyhold",
      "benchmark_multiplier": 1.5,
      "inclusive": true
    },
    "annual_maximum_drawdown": {
      "requirement": "策略年化最大回撤幅度严格 < 同期buyhold",
      "strict": true
    },
    "closed_trade_frequency": {
      "requirement": "开发池平均每60交易日闭合交易数量 >= 4",
      "window_trading_days": 60,
      "minimum": 4,
      "inclusive": true,
      "count": "已完成入场和退出的闭合交易"
    },
    "combination": "三项同时达标",
    "source": "research/RSCH_AGENT.md",
    "source_commit": "b3a0efd6"
  },
  "execution_defaults": {
    "long_only": true,
    "leverage": false,
    "decision_frequency": "daily",
    "decision_execution": "交易日T决策、T+1执行",
    "cost_per_side_bps": 10,
    "buy_order": "LIMIT",
    "sell_order": "MARKET"
  },
  "authorization": {
    "source": "当前用户明确指令",
    "record": "research/S013/materials/registration_authorization_20261007.json",
    "user_instruction": "s012 因无达标候选，请予以暂停。新开研究分支，注册 s013，标的为 510500，开发池窗口 2020-1-1 至 2026-9-30。"
  },
  "research_branch": "codex/s013-research",
  "pending": [
    "阶段一明确研究问题、策略职责及机制探索范围",
    "明确年化、最大回撤的统计周期与汇总方法及平均交易频率计算方式",
    "确认buyhold的执行参数、初始资金、既有数据权限及资源范围",
    "形成阶段一研究约定及交付，取得用户批准后进入阶段二"
  ],
  "next_action": "完成阶段一研究任务与评价约定，呈现用户审阅"
}
```

研究意图是可演化的人类语义。阶段目标和推进由用户确认；完成技术检验并取得用户对冻结计划的明确批准后，通过TDR公共冻结接口发布策略版本。
