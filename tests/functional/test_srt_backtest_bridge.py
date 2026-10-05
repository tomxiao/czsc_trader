"""TDR validates the historical decisions returned by SRT."""
import pandas as pd
import pytest
from strategy_runtime import RuntimeContractError
from czsc_trader.backtesting.srt_bridge import _validate_historical_decisions


def test_srt_history_allows_unavailable_diagnostics_during_warmup() -> None:
    sessions = pd.DatetimeIndex(pd.to_datetime(["2026-09-16", "2026-09-17"]), name="dt")
    history = pd.DataFrame(
        {
            "base_score": [0.2, float("nan")],
            "confirmation_score": [0.1, 0.1],
            "target_position": [0.0, 0.0],
        },
        index=sessions,
    )

    _validate_historical_decisions(history, sessions)


def test_srt_history_rejects_unavailable_target_position() -> None:
    sessions = pd.DatetimeIndex(pd.to_datetime(["2026-09-16", "2026-09-17"]), name="dt")
    history = pd.DataFrame(
        {
            "base_score": [0.2, 0.3],
            "target_position": [0.0, float("nan")],
        },
        index=sessions,
    )

    with pytest.raises(RuntimeContractError, match="target_position"):
        _validate_historical_decisions(history, sessions)
