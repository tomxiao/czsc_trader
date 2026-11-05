"""S011 explanation projects the trading history's reason; it never decides trades."""

import pandas as pd

from strategy_runtime import (
    ConstantGuide, ObservationDefinition, ObservationFact, ObservationFormat,
    ObservationSeries, ObservationValueType, SignalBasisDefinition,
    SignalExplanationCase, SignalExplanationDefinition, SignalGroup,
    SignalPanelDefinition, SignalSeriesDefinition, SignalStateDefinition,
    SignalStateOption, SignalText, SeriesValueRef, GuideValueRef,
)


REASONS = {
    "CASH": "cash", "PRESSURE_ENTRY": "entered", "HOLD": "hold",
    "PRESSURE_RELEASED": "released", "SIGNAL_EXPIRED": "expired",
}


def text(*parts):
    return SignalText(tuple(parts))


def observation_definition(p):
    score, age = SeriesValueRef("score"), SeriesValueRef("age")
    entry, exit_ = GuideValueRef("score", "entry"), GuideValueRef("score", "exit")
    expiry = GuideValueRef("age", "expiry")
    watch_exit = text("得分 ≤ ", exit_, "，或信号已持续达到 ", expiry, "时结束本轮信号。")
    detail = text("得分综合ETF尾盘、沪深300当日表现及此前可得的美股表现的历史相对排名，描述模型定义的短期反弹条件，不是收益率或上涨概率。排名观察期为 ", SeriesValueRef("lookback"), "。信号期限从模型激活后开始计数，与实际成交日无关；同日达到得分退出与期限时，优先记录压力释放。买入为限价委托，参考价上浮 ", SeriesValueRef("premium"), "，不保证成交；模型判断与账户成交分别查看。条件按未舍入的原值比较，显示值经过四舍五入。")
    cases = (
        SignalExplanationCase("cash", text("暂不满足入场条件"), (
            SignalBasisDefinition("score", text("压力反转得分 ", score, " ＜ 入场门槛 ", entry)),
        ), text("等待得分达到 ", entry, " 或以上。"), detail),
        SignalExplanationCase("entered", text("出现入场信号"), (
            SignalBasisDefinition("score", text("压力反转得分 ", score, " ≥ 入场门槛 ", entry)),
            SignalBasisDefinition("execution", text("模型激活本轮信号；实际买入以成交记录为准。")),
        ), watch_exit, detail),
        SignalExplanationCase("hold", text("本轮信号仍有效"), (
            SignalBasisDefinition("score", text("得分 ", score, " ＞ 退出门槛 ", exit_)),
            SignalBasisDefinition("age", text("信号已持续 ", age, "；期限 ", expiry)),
        ), watch_exit, detail),
        SignalExplanationCase("released", text("出现退出信号：压力已释放"), (
            SignalBasisDefinition("score", text("得分 ", score, " ≤ 退出门槛 ", exit_)),
        ), text("等待新的入场信号；实际卖出以成交记录为准。"), detail),
        SignalExplanationCase("expired", text("出现退出信号：信号已到期"), (
            SignalBasisDefinition("age", text("信号已持续 ", age, "，达到期限 ", expiry)),
            SignalBasisDefinition("score", text("当前得分 ", score, " 仍高于退出门槛 ", exit_)),
        ), text("等待新的入场信号；实际卖出以成交记录为准。"), detail),
    )
    return ObservationDefinition(
        (ObservationSeries("score", "压力反转得分", "score", (
            ConstantGuide("entry", "入场阈值", p["entry"]),
            ConstantGuide("exit", "退出阈值", p["exit"]),
        )),),
        (ObservationFact("reason", "决策原因", "reason", ObservationValueType.TEXT, ObservationFormat.TEXT),
         ObservationFact("intent_age", "信号已持续交易日", "intent_age", ObservationValueType.INTEGER, ObservationFormat.INTEGER)),
        SignalPanelDefinition(
            (SignalGroup("score_group", "压力反转", "分", "历史相对排名", ObservationFormat.NUMBER, 3),
             SignalGroup("sessions", "交易日计数", "个交易日", "模型信号时间", ObservationFormat.INTEGER, 0),
             SignalGroup("price_ratio", "买入限价", "%", "参考价上浮比例", ObservationFormat.PERCENT, 2)),
            (SignalSeriesDefinition("score", "压力反转得分", "score_group", "obs_score", guides=(
                ConstantGuide("entry", "入场门槛", p["entry"]), ConstantGuide("exit", "退出门槛", p["exit"]))),
             SignalSeriesDefinition("age", "信号已持续", "sessions", "obs_age", guides=(ConstantGuide("expiry", "信号期限", p["max_days"]),)),
             SignalSeriesDefinition("lookback", "排名观察期", "sessions", "obs_lookback"),
             SignalSeriesDefinition("premium", "买入限价上浮", "price_ratio", "obs_premium")),
            (SignalStateDefinition("decision", "模型判断", "obs_decision", tuple(
                SignalStateOption(case.key, label) for case, label in zip(cases,
                    ("等待", "入场", "继续有效", "压力释放退出", "期限退出"), strict=True))),),
            SignalExplanationDefinition("decision", cases),
        ),
    )


def observation_history(history, p):
    if not history.reason.isin(REASONS).all():
        raise ValueError("unknown S011 trading reason")
    result = pd.DataFrame(index=history.index)
    result["obs_score"] = history.score
    result["obs_age"] = history.intent_age
    result["obs_decision"] = history.reason.map(REASONS)
    result["obs_lookback"] = p["lookback"]
    result["obs_premium"] = p["premium"]
    return result
