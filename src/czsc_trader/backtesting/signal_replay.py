from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .models import StrategySnapshot


@dataclass(frozen=True)
class SignalReplay:
    snapshot: StrategySnapshot
    strategy_source: object
    decisions: pd.DataFrame
    calculation_start: pd.Timestamp
    calculation_end: pd.Timestamp
    evaluation_start: pd.Timestamp
    evaluation_end: pd.Timestamp
    data_dir: Path
    data_identity: str
    support_data: dict[str, object] | None = None
