"""Explain the already-computed S015 opportunity; do not replay its state machine."""

import numpy as np
import pandas as pd

from strategy_runtime import (
    ConstantGuide, ObservationDefinition, ObservationFormat, ObservationSeries,
    SignalBasisDefinition, SignalExplanationCase, SignalExplanationDefinition,
    SignalGroup, SignalPanelDefinition, SignalSeriesDefinition,
    SignalStateDefinition, SignalStateOption, SignalText, SeriesValueRef, GuideValueRef,
)


def text(*parts):
    return SignalText(tuple(parts))


def observation_definition(p):
    space = SeriesValueRef("repair_space")
    minimum = GuideValueRef("repair_space", "minimum")
    center, close = SeriesValueRef("center"), SeriesValueRef("close")
    gain = SeriesValueRef("center_change")
    target, origin = SeriesValueRef("repair_target"), SeriesValueRef("invalidation_origin")
    kind = {"median": "对数价格中位数", "mean": "对数价格均值"}[p["center_kind"]]
    detail = text("策略用当日八个半小时收盘价的", kind,
        "构造价格中心，并比较 ", SeriesValueRef("lookback"),
        " 前的中心。中心上移、收盘低于中心且修复空间达到门槛时，激活一次修复机会。激活时固定目标与原中心；以后收盘达到目标，或当前中心回落至原中心，就结束机会。观察期用于比较中心，不是固定持有期限；中心失效线比较的是中心，不是成交止损价。展示价格均为后复权参考价格。入场按信号时可用现金的 ",
        SeriesValueRef("allocation"), " 形成资金周期，限价买入不保证成交。模型机会与实际持仓分别查看。条件按未舍入的原值比较，显示值经过四舍五入。")
    entry_basis = (
        SignalBasisDefinition("space", text("修复空间 ", space, "；最低门槛 ", minimum)),
        SignalBasisDefinition("center", text("中心相对观察期之前上移 ", gain, "；要求大于零。")),
    )
    watch = text("关注收盘是否达到固定目标 ", target, "，或当前中心是否降至 ", origin, "。")
    cases = (
        SignalExplanationCase("warmup", text("观察数据尚未完整"), (
            SignalBasisDefinition("warmup", text("尚未形成完整中心比较，模型未激活修复机会。")),
        ), text("等待完成 ", SeriesValueRef("lookback"), " 的中心比较。"), detail),
        SignalExplanationCase("inactive", text("暂不满足入场条件"), entry_basis,
            text("等待中心上移、收盘低于中心，且修复空间达到 ", minimum, "。"), detail),
        SignalExplanationCase("entered", text("出现入场信号：修复机会激活"), entry_basis,
            watch, detail),
        SignalExplanationCase("active", text("本轮修复机会仍有效"), (
            SignalBasisDefinition("target", text("收盘 ", close, " ＜ 固定目标 ", target)),
            SignalBasisDefinition("origin", text("当前中心 ", center, " ＞ 中心失效线 ", origin)),
        ), watch, detail),
        SignalExplanationCase("exit_target", text("出现退出信号：修复目标达到"), (
            SignalBasisDefinition("target", text("收盘 ", close, " ≥ 固定目标 ", target)),
        ), text("本轮机会结束，等待新的入场条件；实际卖出以成交记录为准。"), detail),
        SignalExplanationCase("exit_center", text("出现退出信号：中心上移失效"), (
            SignalBasisDefinition("origin", text("当前中心 ", center, " ≤ 中心失效线 ", origin)),
        ), text("本轮机会结束，等待新的入场条件；实际卖出以成交记录为准。"), detail),
        SignalExplanationCase("exit_both", text("出现退出信号：两项退出条件均满足"), (
            SignalBasisDefinition("target", text("收盘 ", close, " ≥ 固定目标 ", target)),
            SignalBasisDefinition("origin", text("当前中心 ", center, " ≤ 中心失效线 ", origin)),
        ), text("本轮机会结束，等待新的入场条件；实际卖出以成交记录为准。"), detail),
    )
    series = (
        SignalSeriesDefinition("repair_space", "修复空间", "ratios", "obs_repair_space",
            status_field="obs_feature_status", reason_field="obs_feature_reason",
            guides=(ConstantGuide("minimum", "最低修复空间", p["minimum_repair_space"]),)),
        SignalSeriesDefinition("center_change", "中心上移幅度", "ratios", "obs_center_change",
            status_field="obs_feature_status", reason_field="obs_feature_reason"),
        SignalSeriesDefinition("allocation", "入场资金比例", "capital", "obs_allocation"),
        SignalSeriesDefinition("lookback", "中心观察期", "sessions", "obs_lookback"),
        SignalSeriesDefinition("center", "当前价格中心", "prices", "obs_center",
            status_field="obs_feature_status", reason_field="obs_feature_reason"),
        SignalSeriesDefinition("close", "当前收盘价", "prices", "obs_close",
            status_field="obs_feature_status", reason_field="obs_feature_reason"),
        SignalSeriesDefinition("repair_target", "固定修复目标", "prices", "obs_repair_target",
            status_field="obs_anchor_status"),
        SignalSeriesDefinition("invalidation_origin", "中心失效线", "prices", "obs_invalidation_origin",
            status_field="obs_anchor_status"),
    )
    return ObservationDefinition(
        (ObservationSeries("repair_space", "当前中心相对收盘修复空间", "repair_space"),
         ObservationSeries("center_gain", "跨日价格中心变化", "center_gain"),
         ObservationSeries("repair_target", "机会激活时固定的修复目标", "repair_target"),
         ObservationSeries("invalidation_origin", "机会激活时固定的中心失效起点", "invalidation_origin")),
        (),
        SignalPanelDefinition(
            (SignalGroup("ratios", "相对比例", "%", "相对价格变化", ObservationFormat.PERCENT, 2),
             SignalGroup("capital", "资金比例", "%", "信号时可用现金比例", ObservationFormat.PERCENT, 2),
             SignalGroup("sessions", "观察期", "个交易日", "中心比较跨度", ObservationFormat.INTEGER, 0),
             SignalGroup("prices", "参考价格", "元", "后复权参考价格", ObservationFormat.NUMBER, 3)),
            series,
            (SignalStateDefinition("decision", "模型机会判断", "obs_decision", tuple(
                SignalStateOption(case.key, label) for case, label in zip(cases,
                    ("数据不足", "等待", "当日激活", "继续有效", "目标达到退出", "中心失效退出", "两项退出条件均满足"), strict=True))),),
            SignalExplanationDefinition("decision", cases),
        ),
    )


def observation_history(history, p):
    result = pd.DataFrame(index=history.index)
    ready = history.feature_ready.astype(bool)
    entered = history.entry_signal.astype(bool)
    exited = history.exit_signal.astype(bool)
    active = history.target_position.astype(bool)
    # Exit subtypes describe predicates of an actual recorded exit; they do not
    # trigger exits or reconstruct the opportunity state machine.
    hit_target = history.p >= history.repair_target
    lost_center = history.m <= history.invalidation_origin
    if (exited & ~(hit_target | lost_center)).any():
        raise ValueError("S015 exit has no recorded financial cause")
    result["obs_decision"] = np.select(
        (exited & hit_target & lost_center, exited & hit_target, exited & lost_center,
         entered, active, ~ready),
        ("exit_both", "exit_target", "exit_center", "entered", "active", "warmup"),
        default="inactive",
    )
    result["obs_repair_space"] = history.repair_space
    result["obs_center_change"] = np.expm1(history.center_gain)
    result["obs_center"] = np.exp(history.m)
    result["obs_close"] = np.exp(history.p)
    result["obs_feature_status"] = np.where(ready, "AVAILABLE", "UNAVAILABLE")
    result["obs_feature_reason"] = np.where(ready, "", "尚未形成完整中心比较；内部种子值不作为实际价格展示")
    anchors = active | exited
    result["obs_repair_target"] = np.exp(history.repair_target).where(anchors)
    result["obs_invalidation_origin"] = np.exp(history.invalidation_origin).where(anchors)
    result["obs_anchor_status"] = np.where(anchors, "AVAILABLE", "INACTIVE")
    result["obs_allocation"] = p["allocation"]
    result["obs_lookback"] = p["lookback"]
    return result
