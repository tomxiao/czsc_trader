"""Read-only execution explanations from this release's confirmed facts."""
from strategy_runtime.execution_explanation import ExecutionExplanation, ExecutionPlanContext


def explain_execution(context):
    if isinstance(context, ExecutionPlanContext):
        return explain_plan(context)
    return explain_result(context)


def explain_plan(plan):
    if plan.planning_status == "SUPPRESSED":
        return ExecutionExplanation("本轮未形成可执行信号。", "执行计划在信号观察阶段被抑制，本轮无委托。")
    if not plan.orders:
        if plan.planning_status == "BLOCKED":
            why = constraints_text(plan)
            return ExecutionExplanation("执行条件受限，本轮无委托。", f"策略目标为 {plan.target:.2%}。{why}")
        if plan.target == 0 and plan.position_at_decision == 0:
            text = "目标为空仓，账户当时已空仓，无需下单。"
        else:
            text = "按本轮目标与账户持仓，计划无需新增委托。"
        return ExecutionExplanation(text, text)
    previous = plan.previous
    if plan.trigger == "PREVIOUS_ZERO_FILL" and previous:
        if previous.intents and all(i.status == "EXPIRED" and i.channel_order_id is None for i in previous.intents):
            reason = "上轮委托过期未提交，按本轮目标重新生成计划。"
        elif previous.reason == "NORMAL_UNFILLED":
            reason = "上轮委托已提交，结束时未成交，按本轮目标重新生成计划。"
        else:
            reason = "上轮计划结束时无确认成交，按本轮目标重新生成计划。"
    elif plan.trigger == "PREVIOUS_ZERO_FILL":
        reason = "按本轮目标重新生成计划，上一轮的提交状态未记录。"
    elif plan.trigger == "TARGET_CHANGED":
        reason = "目标仓位变化，按当时账户持仓生成计划。"
    else:
        reason = "按本轮目标仓位和当时账户持仓生成计划。"
    orders = "、".join(f"{'买入' if item.side == 'BUY' else '卖出'} {item.quantity:,} 股" for item in plan.orders)
    return ExecutionExplanation(reason, f"{reason} 计划{orders}。{constraints_text(plan)}")


def constraints_text(plan):
    labels = {
        "INSUFFICIENT_CASH": "可用资金限制",
        "BELOW_MINIMUM_UNIT": "不足最小交易单位",
        "BELOW_PRICE_TICK": "低于最小报价单位",
        "INSUFFICIENT_SELLABLE_QUANTITY": "可卖股数受限",
        "ORDER_QUANTITY_LIMIT": "委托股数受限",
        "DEPENDENCY_UNAVAILABLE": "前序执行条件未满足",
    }
    if not plan.constraints:
        return ""
    limits = "、".join(labels[code] for code in plan.constraints)
    return f"本轮受{limits}影响，初拟目标 {plan.desired_quantity:,} 股，计划目标 {plan.planned_quantity:,} 股。"


def explain_result(result):
    confirmed = "、".join(f"{label} {quantity:,} 股" for side, label in (("BUY", "买入"), ("SELL", "卖出"))
        if (quantity := sum(fill.quantity for fill in result.fills if fill.side == side)))
    if confirmed:
        title = "计划全部成交" if result.reason == "PLAN_FILLED" else "已有确认成交"
        if result.reason == "NORMAL_PARTIAL":
            title = "委托结束，部分成交"
        text = f"{title}，{confirmed}。"
        return ExecutionExplanation(text, f"{text} 成交股数以渠道确认记录为准。")
    if result.reason == "NO_ORDER":
        text = "本轮无需下单，无成交。"
    elif result.reason == "EXECUTION_EXPIRED" and result.intents and all(
            i.status == "EXPIRED" and i.channel_order_id is None for i in result.intents):
        text = "委托超过提交时限，未提交、未成交。"
    elif result.reason == "NORMAL_UNFILLED":
        text = "委托已提交，结束时未成交。"
    elif result.reason in ("ORDER_REJECTED", "SUBMISSION_FAILED"):
        text = "委托被拒绝或提交失败，暂无确认成交。"
    elif result.reason in ("CHANNEL_RESULT_UNCERTAIN", "AWAITING_FILL_RECONCILIATION"):
        text = "渠道结果待确认，暂无确认成交。"
    elif result.status == "SUPERSEDED":
        text = "本轮计划已由新决策替代。"
    elif result.status in ("PENDING", "EXECUTING"):
        text = "等待执行结果，暂无确认成交。"
    else:
        text = "暂无确认成交，结果以账户执行记录为准。"
    return ExecutionExplanation(text, text)
