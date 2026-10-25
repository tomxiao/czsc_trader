"""S015 observation semantics, isolated from every trading calculation."""

import numpy as np
import pandas as pd

from strategy_runtime import (
    ConstantGuide, ObservationDefinition, ObservationFormat, ObservationSeries,
    SignalGroup, SignalPanelDefinition, SignalRender, SignalSeriesDefinition,
    SignalStateDefinition, SignalStateOption,
)


def observation_definition(parameters):
    return ObservationDefinition(
        (
            ObservationSeries("repair_space", "当前中心相对收盘修复空间", "repair_space"),
            ObservationSeries("center_gain", "跨日价格中心变化", "center_gain"),
            ObservationSeries("repair_target", "机会激活时固定的修复目标", "repair_target"),
            ObservationSeries("invalidation_origin", "机会激活时固定的中心失效起点", "invalidation_origin"),
        ),
        (),
        signal_panel=SignalPanelDefinition(
            groups=(
                SignalGroup("entry_conditions", "入场条件", "%", "相对变化", ObservationFormat.PERCENT, 2,
                            "修复空间与中心上移幅度分别满足门槛，才具备入场条件。"),
                SignalGroup("opportunity_bounds", "机会边界", "元", "后复权参考价格", ObservationFormat.NUMBER, 3,
                            "目标与失效线按机会激活时的价格中心固定；失效线用于比较中心，不是成交止损价。"),
            ),
            series=(
                SignalSeriesDefinition("repair_space", "修复空间", "entry_conditions", "obs_repair_space",
                    status_field="obs_price_status", reason_field="obs_price_reason",
                    guides=(ConstantGuide("minimum", "最低修复空间", float(parameters["minimum_repair_space"])),),
                    description="当前收盘价距离参考价格中心还有多远；负值表示已经高于中心。"),
                SignalSeriesDefinition("center_change", "中心上移幅度", "entry_conditions", "obs_center_change",
                    status_field="obs_condition_status", reason_field="obs_condition_reason",
                    guides=(ConstantGuide("zero", "上移分界", 0.0),),
                    description="价格中心相对观察期之前中心的变化；大于零才满足上移条件。"),
                SignalSeriesDefinition("center_price", "当前价格中心", "opportunity_bounds", "obs_center_price",
                    status_field="obs_price_status", reason_field="obs_price_reason",
                    description="策略计算的当前价格中心，使用后复权参考价格口径。"),
                SignalSeriesDefinition("repair_target", "固定修复目标", "opportunity_bounds", "obs_repair_target",
                    render=SignalRender.STEP, status_field="obs_opportunity_status", segment_field="obs_opportunity_id",
                    description="机会激活时固定的修复目标；达到该目标会触发模型退出。"),
                SignalSeriesDefinition("invalidation_origin", "中心失效线", "opportunity_bounds", "obs_invalidation_origin",
                    render=SignalRender.STEP, status_field="obs_opportunity_status", segment_field="obs_opportunity_id",
                    description="当前价格中心降至此线时，上移前提失效；由策略结束该机会。"),
            ),
            states=(
                SignalStateDefinition("center_condition", "中心上移条件", "obs_center_condition",
                    (SignalStateOption("pass", "满足"), SignalStateOption("fail", "未满足")),
                    status_field="obs_condition_status", reason_field="obs_condition_reason"),
                SignalStateDefinition("space_condition", "修复空间条件", "obs_space_condition",
                    (SignalStateOption("pass", "满足"), SignalStateOption("fail", "未满足")),
                    status_field="obs_price_status", reason_field="obs_price_reason"),
                SignalStateDefinition("entry_condition", "完整入场条件", "obs_entry_condition",
                    (SignalStateOption("pass", "满足"), SignalStateOption("fail", "未满足")),
                    status_field="obs_condition_status", reason_field="obs_condition_reason"),
                SignalStateDefinition("opportunity", "模型机会", "obs_opportunity_state",
                    (SignalStateOption("active", "有效"), SignalStateOption("inactive", "无有效机会"),
                     SignalStateOption("entered", "当日激活"), SignalStateOption("exited", "当日结束")),
                    description="模型机会状态独立于账户是否成交、是否持仓。"),
            ),
        ),
    )


def observation_history(inputs, context, history, parameters):
    from .price_process import causal_features, intentions

    requested_index = history.index
    features = causal_features(inputs["market"], inputs["execution"], inputs["intraday"],
                               parameters["lookback"], parameters["center_kind"])
    history = intentions(features, parameters)
    result = pd.DataFrame(index=history.index)
    active = history.target_position.astype(bool)
    entered = history.entry_signal.astype(bool)
    exited = history.exit_signal.astype(bool)
    activation_dates = pd.Series(
        [day.date().isoformat() if flag else None for day, flag in zip(history.index, entered, strict=True)],
        index=history.index,
        dtype=object,
    ).ffill()
    if activation_dates[active].isna().any():
        raise ValueError("observation requires the original opportunity activation history")
    result["obs_repair_space"] = history.repair_space
    ready = history.feature_ready.astype(bool)
    price_ready = history.index >= pd.Timestamp("2025-01-02")
    result["obs_condition_status"] = np.where(ready, "AVAILABLE", "UNAVAILABLE")
    result["obs_condition_reason"] = np.where(ready, "", "尚未形成完整观察期")
    result["obs_price_status"] = np.where(price_ready, "AVAILABLE", "UNAVAILABLE")
    result["obs_price_reason"] = np.where(price_ready, "", "起始种子日无模型价格中心")
    result["obs_center_change"] = np.expm1(history.center_gain)
    result["obs_center_price"] = np.exp(history.m)
    result["obs_repair_target"] = np.exp(history.repair_target).where(active)
    result["obs_invalidation_origin"] = np.exp(history.invalidation_origin).where(active)
    result["obs_opportunity_status"] = np.where(active, "AVAILABLE", "INACTIVE")
    result["obs_opportunity_id"] = activation_dates.where(active, "")
    result["obs_center_condition"] = np.where(history.center_gain > 0, "pass", "fail")
    result["obs_space_condition"] = np.where(
        (history.p < history.m) & (history.repair_space >= parameters["minimum_repair_space"]), "pass", "fail")
    result["obs_entry_condition"] = np.where(history.permission.astype(bool), "pass", "fail")
    result["obs_opportunity_state"] = np.select(
        (entered, exited, active), ("entered", "exited", "active"), default="inactive")
    return result.reindex(requested_index)
