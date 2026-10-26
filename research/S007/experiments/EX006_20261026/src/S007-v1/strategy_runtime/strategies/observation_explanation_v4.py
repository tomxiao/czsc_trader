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
                    "key": "entry_threshold",
                    "label": "入场阈值",
                    "value": 0.10449974411727908,
                    "kind": "CONSTANT",
                },
                {
                    "key": "exit_threshold",
                    "label": "退出阈值",
                    "value": 0.047857421473087296,
                    "kind": "CONSTANT",
                },
            ],
            "key": "base_score",
            "label": "基础分",
            "value_field": "base_score",
        },
        {
            "guides": [
                {
                    "key": "confirmation_threshold",
                    "label": "确认门",
                    "value": -0.012073272333918687,
                    "kind": "CONSTANT",
                }
            ],
            "key": "confirmation_score",
            "label": "确认分",
            "value_field": "confirmation_score",
        },
    ],
    "facts": [],
}


def observation_definition(score):
    def text(*parts):
        return SignalText(parts)

    base = SignalBasisDefinition(
        "base",
        text(
            "基础分 ",
            SeriesValueRef("base"),
            "；入场门槛 ",
            GuideValueRef("base", "entry"),
            "；退出门槛 ",
            GuideValueRef("base", "exit"),
        ),
    )
    confirmation = SignalBasisDefinition(
        "confirmation",
        text(
            "确认分 ",
            SeriesValueRef("confirmation"),
            "；确认门槛 ",
            GuideValueRef("confirmation", "entry"),
        ),
    )
    detail = text(
        "基础分将价格相对成交均价的偏离、振幅、创业板换手、此前美股表现及隔夜资金利率变化，"
        "按历史分位和固定权重汇总；确认分来自滞后一日的ETF份额五日变化，以及截至当日的近20个交易日对数成交量变化均值。"
        "分数不是收益率或上涨概率。空仓模型须基础分和确认分同时达标才激活；"
        "激活后仅基础分降至退出门槛或以下才结束，确认分回落本身不触发退出。"
        "这里展示模型状态；账户持仓和实际成交另看账户、事件记录。"
    )
    enter_watch = text(
        "关注基础分是否降至退出门槛 ",
        GuideValueRef("base", "exit"),
        " 或以下；实际入场以委托和成交记录为准。",
    )
    wait_watch = text(
        "等待基础分达到 ",
        GuideValueRef("base", "entry"),
        " 且确认分达到 ",
        GuideValueRef("confirmation", "entry"),
        "。",
    )
    panel = SignalPanelDefinition(
        groups=(
            SignalGroup(
                "score", "模型得分", "分", "居中历史分位加权分", ObservationFormat.NUMBER, 4
            ),
        ),
        series=(
            SignalSeriesDefinition(
                "base",
                "基础分",
                "score",
                "obs_base",
                status_field="obs_base_status",
                reason_field="obs_base_reason",
                guides=(
                    EvidenceGuide("entry", "入场门槛", "obs_entry"),
                    EvidenceGuide("exit", "退出门槛", "obs_exit"),
                ),
            ),
            SignalSeriesDefinition(
                "confirmation",
                "确认分",
                "score",
                "obs_confirmation",
                status_field="obs_confirmation_status",
                reason_field="obs_confirmation_reason",
                guides=(EvidenceGuide("entry", "确认门槛", "obs_confirmation_entry"),),
            ),
        ),
        states=(
            SignalStateDefinition(
                "decision",
                "模型决策",
                "obs_decision",
                tuple(
                    SignalStateOption(k, label)
                    for k, label in (
                        ("enter", "激活入场"),
                        ("hold_position", "继续有效"),
                        ("exit", "结束退出"),
                        ("hold_cash", "空仓等待"),
                    )
                ),
            ),
        ),
        explanation=SignalExplanationDefinition(
            "decision",
            (
                SignalExplanationCase(
                    "enter", text("出现入场信号"), (base, confirmation), enter_watch, detail
                ),
                SignalExplanationCase(
                    "hold_position",
                    text("本轮信号继续有效"),
                    (
                        base,
                        SignalBasisDefinition(
                            "exit_rule", text("模型保持激活；确认分回落本身不触发退出。")
                        ),
                    ),
                    text("关注基础分是否降至 ", GuideValueRef("base", "exit"), " 或以下。"),
                    detail,
                ),
                SignalExplanationCase(
                    "exit",
                    text("出现退出信号"),
                    (
                        base,
                        SignalBasisDefinition(
                            "exit_rule", text("基础分触及退出条件，本轮模型机会结束。")
                        ),
                    ),
                    wait_watch,
                    detail,
                ),
                SignalExplanationCase(
                    "hold_cash",
                    text("暂不满足完整入场条件"),
                    (base, confirmation),
                    wait_watch,
                    detail,
                ),
            ),
        ),
    )
    legacy = ObservationDefinition.from_dict(LEGACY)
    return ObservationDefinition(legacy.series, legacy.facts, signal_panel=panel)


def observation_history(history, score):
    result = pd.DataFrame(index=history.index)
    result["obs_base"] = history["base_score"]
    result["obs_confirmation"] = history["confirmation_score"]
    result["obs_entry"] = float(score["entry_threshold"])
    result["obs_exit"] = float(score["exit_threshold"])
    result["obs_confirmation_entry"] = float(score["confirmation_threshold"])
    for key, field in (("base", "base_score"), ("confirmation", "confirmation_score")):
        ready = np.isfinite(history[field])
        result[f"obs_{key}_status"] = np.where(ready, "AVAILABLE", "UNAVAILABLE")
        result[f"obs_{key}_reason"] = np.where(ready, "", "历史分位计算的有效数据尚不完整")
    # Actual trading action selects explanation; no parallel state machine.
    result["obs_decision"] = history["action"].map(
        {
            "ENTER": "enter",
            "HOLD_POSITION": "hold_position",
            "EXIT": "exit",
            "HOLD_CASH": "hold_cash",
        }
    )
    return result
