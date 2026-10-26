"""Frozen S001-v2 runtime with an explicit observation-capable declaration."""

from __future__ import annotations

from strategy_runtime import ParameterSet, RuntimeContractError

from .s001_common import S001Base


class S001V2(S001Base):
    def __init__(self, parameters: ParameterSet, deployment_symbol: str | None = None) -> None:
        from .s001_common import (
            _object, re, effective_target_order_type, Dataset, StrategyDefinition,
            ParameterSet, InputContract, InputRequirement, CutoffRule, DecisionContract,
            ExecutionPolicy, MonitoringPolicy, RequiredCapabilities, HistoryPolicy,
            _INTRADAY, _DAILY, _WEEKLY, _EXECUTION, _CALENDAR, _HISTORY_START,
        )
        payload = _object(parameters.values, "strategy parameters")
        rule = _object(payload.get("rule"), "S001 rule")
        execution = _object(rule.get("execution"), "S001 execution")
        instrument = _object(execution.get("instrument"), "S001 instrument")
        frozen_symbol = str(instrument.get("symbol", "")).upper()
        if frozen_symbol != "588080.SH":
            raise RuntimeContractError("S001 frozen symbol must be 588080.SH")
        symbol = (deployment_symbol or frozen_symbol).upper()
        if not re.fullmatch("\\d{6}\\.(?:SH|SZ)", symbol):
            raise RuntimeContractError("S001 deployment symbol must be an A-share instrument")
        self._rule = rule
        self._symbol = symbol
        order_types = tuple(
            sorted(
                {
                    effective_target_order_type(execution, "BUY"),
                    effective_target_order_type(execution, "SELL"),
                }
            )
        )
        datasets = (
            Dataset.ETF_OHLCV.value,
            Dataset.ETF_UNADJUSTED_DAILY.value,
            Dataset.TRADING_CALENDAR.value,
        )
        self._definition = StrategyDefinition(
            ParameterSet(payload),
            InputContract(
                (
                    InputRequirement(
                        _INTRADAY,
                        Dataset.ETF_OHLCV.value,
                        symbol,
                        "30m",
                        500,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        _DAILY,
                        Dataset.ETF_OHLCV.value,
                        symbol,
                        "daily",
                        60,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        _WEEKLY,
                        Dataset.ETF_OHLCV.value,
                        symbol,
                        "weekly",
                        10,
                        CutoffRule.LATEST_AVAILABLE,
                        7,
                    ),
                    InputRequirement(
                        _EXECUTION,
                        Dataset.ETF_UNADJUSTED_DAILY.value,
                        symbol,
                        "daily",
                        1,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                    InputRequirement(
                        _CALENDAR,
                        Dataset.TRADING_CALENDAR.value,
                        "SSE",
                        "daily",
                        0,
                        CutoffRule.LATEST_AVAILABLE,
                    ),
                )
            ),
            DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION_OPEN"),
            ExecutionPolicy("FROZEN_RULE", execution),
            MonitoringPolicy("FORWARD_OBSERVATION", {"frozen": True}),
            RequiredCapabilities(datasets, order_types),
            tradable_symbol=symbol,
            history=HistoryPolicy(
                "CANONICAL_REPLAY", _HISTORY_START.isoformat(), _HISTORY_START.isoformat()
            ),
            observation=self.observation_definition(),
        )


    def observation_definition(self):
        from strategy_runtime import ObservationDefinition
        from .observation_s001_v4 import observation_definition
        legacy = ObservationDefinition.from_dict(
                {
                    "contract_version": "strategy_observation.v2",
                    "series": [
                        {
                            "guides": [
                                {
                                    "key": "entry_threshold",
                                    "label": "买入阈值",
                                    "value": 0.175,
                                    "kind": "CONSTANT",
                                },
                                {
                                    "key": "exit_threshold",
                                    "label": "卖出阈值",
                                    "value": 0.025,
                                    "kind": "CONSTANT",
                                },
                            ],
                            "key": "factor_score",
                            "label": "策略得分",
                            "value_field": "factor_score",
                        }
                    ],
                    "facts": [],
                }
            )
        return observation_definition(legacy, self._rule)


    def observation_history(self, inputs, context, history):
        from .observation_s001_v4 import observation_history
        return observation_history(history, self._rule)

