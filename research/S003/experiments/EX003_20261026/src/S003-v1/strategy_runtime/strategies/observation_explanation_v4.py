"""Observation-only explanation; trading results are authoritative."""

import numpy as np
import pandas as pd
from strategy_runtime import (
    EvidenceGuide,
    ObservationDefinition,
    ObservationFormat,
    SignalGroup,
    SignalPanelDefinition,
    SignalSeriesDefinition,
    SignalStateDefinition,
    SignalStateOption,
    SignalText,
    SignalBasisDefinition,
    SignalExplanationDefinition,
    SignalExplanationCase,
    SeriesValueRef,
    GuideValueRef,
)


LEGACY = {
    "contract_version": "strategy_observation.v2",
    "series": [
        {
            "guides": [
                {
                    "key": "dynamic_threshold",
                    "label": "动态阈值",
                    "value_field": "threshold",
                    "kind": "EVIDENCE",
                }
            ],
            "key": "moneyflow_breadth",
            "label": "资金流宽度",
            "value_field": "moneyflow_breadth",
        }
    ],
    "facts": [],
}


def observation_definition(feature):
    def text(*parts):
        return SignalText(parts)

    detail = text(
        "资金流宽度是有资金流记录的中证500成分股中，净流入股票所占的权重比例，"
        "不是流入金额或上涨概率。策略将当日宽度与按冻结历史窗口计算的动态分位门槛比较。"
        "信号满足时计划在下一交易日做早盘增强，并按既定上午检查点退出增强部分；"
        "底仓与可卖份额轮换遵守账户执行规则。无增强信号不代表清空底仓，模型信号不代表已经成交。"
    )
    common = (
        SignalBasisDefinition(
            "breadth",
            text(
                "资金流宽度 ",
                SeriesValueRef("breadth"),
                "；动态门槛 ",
                GuideValueRef("breadth", "threshold"),
            ),
        ),
        SignalBasisDefinition(
            "coverage",
            text(
                "已观测成分权重比例 ",
                SeriesValueRef("coverage"),
                "；最低覆盖要求 ",
                GuideValueRef("coverage", "minimum"),
            ),
        ),
    )
    panel = SignalPanelDefinition(
        groups=(SignalGroup("ratio", "成分资金流", "%", "权重占比", ObservationFormat.PERCENT, 2),),
        series=(
            SignalSeriesDefinition(
                "breadth",
                "资金流宽度",
                "ratio",
                "obs_breadth",
                status_field="obs_breadth_status",
                reason_field="obs_breadth_reason",
                guides=(EvidenceGuide("threshold", "动态门槛", "obs_threshold"),),
            ),
            SignalSeriesDefinition(
                "coverage",
                "已观测权重比例",
                "ratio",
                "obs_coverage",
                status_field="obs_coverage_status",
                reason_field="obs_coverage_reason",
                guides=(EvidenceGuide("minimum", "最低覆盖要求", "obs_minimum_coverage"),),
            ),
        ),
        states=(
            SignalStateDefinition(
                "decision",
                "增强信号",
                "obs_decision",
                (SignalStateOption("active", "满足"), SignalStateOption("inactive", "未满足")),
                status_field="obs_decision_status",
                reason_field="obs_decision_reason",
            ),
        ),
        explanation=SignalExplanationDefinition(
            "decision",
            (
                SignalExplanationCase(
                    "active",
                    text("出现早盘增强信号"),
                    common,
                    text("关注下一交易日增强委托及上午退出的实际成交；不是长期加仓信号。"),
                    detail,
                ),
                SignalExplanationCase(
                    "inactive",
                    text("暂不触发早盘增强"),
                    common,
                    text(
                        "等待资金流宽度达到动态门槛 ",
                        GuideValueRef("breadth", "threshold"),
                        "；底仓按既定规则维护。",
                    ),
                    detail,
                ),
            ),
        ),
    )
    legacy = ObservationDefinition.from_dict(LEGACY)
    return ObservationDefinition(legacy.series, legacy.facts, signal_panel=panel)


def observation_history(history, feature):
    result = pd.DataFrame(index=history.index)
    result["obs_breadth"] = history["moneyflow_breadth"]
    result["obs_threshold"] = history["threshold"]
    result["obs_coverage"] = history["observed_weight_ratio"]
    result["obs_minimum_coverage"] = float(feature["minimum_observed_weight_ratio"])
    breadth_ready = np.isfinite(history["moneyflow_breadth"]) & np.isfinite(history["threshold"])
    coverage_ready = np.isfinite(history["observed_weight_ratio"])
    result["obs_breadth_status"] = np.where(breadth_ready, "AVAILABLE", "UNAVAILABLE")
    result["obs_breadth_reason"] = np.where(breadth_ready, "", "资金流宽度或历史动态门槛不可用")
    result["obs_coverage_status"] = np.where(coverage_ready, "AVAILABLE", "UNAVAILABLE")
    result["obs_coverage_reason"] = np.where(coverage_ready, "", "已观测成分权重比例不可用")
    ready = breadth_ready & coverage_ready & history["signal_active"].notna()
    result["obs_decision_status"] = np.where(ready, "AVAILABLE", "UNAVAILABLE")
    result["obs_decision_reason"] = np.where(ready, "", "增强信号的比较依据尚不完整")
    # Map the trading calculation's decision; do not independently rerun its comparison.
    result["obs_decision"] = history["signal_active"].map({True: "active", False: "inactive"})
    return result
