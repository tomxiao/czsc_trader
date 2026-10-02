from __future__ import annotations

from pathlib import Path
import shutil

import pandas as pd
import pytest
from dataflows import Dataflows
from current_contract_support import candidate_payload as candidate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]


def _frame(root: Path, pattern: str, date_column: str) -> pd.DataFrame:
    parts = [pd.read_csv(path) for path in sorted(root.glob(pattern))]
    frame = pd.concat(parts, ignore_index=True)
    return frame.rename(
        columns={
            date_column: "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "amount": "Amount",
        }
    )


@pytest.fixture
def functional_repo(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    (root / "src" / "czsc_trader").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname='czsc-trader-functional-test'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    shutil.copytree(REPO_ROOT / "strategies", root / "strategies")
    raw_dir = root / "data" / "raw"
    raw_dir.mkdir(parents=True)
    for source in (REPO_ROOT / "data" / "raw").glob("588080*"):
        shutil.copy2(source, raw_dir / source.name)
    (root / "data" / "backtest").mkdir()
    frames = {
        ("etf.ohlcv", "588080.SH", "30m"): _frame(
            raw_dir, "588080_30m_*.csv", "datetime"
        ),
        ("etf.ohlcv", "588080.SH", "daily"): _frame(
            raw_dir, "588080_daily_*.csv", "date"
        ),
        ("etf.ohlcv", "588080.SH", "weekly"): _frame(
            raw_dir, "588080_weekly_*.csv", "date"
        ),
        ("etf.unadjusted_daily", "588080.SH", "daily"): _frame(
            raw_dir, "588080_execution_daily_*.csv", "date"
        ),
    }
    calendar_end = pd.Timestamp(frames[("etf.ohlcv", "588080.SH", "daily")]["Date"].max()) + pd.Timedelta(days=20)
    dates = pd.date_range(
        frames[("etf.ohlcv", "588080.SH", "daily")]["Date"].min(), calendar_end
    )
    observed_sessions = pd.DatetimeIndex(
        pd.to_datetime(frames[("etf.ohlcv", "588080.SH", "daily")]["Date"])
    ).normalize()
    is_open = dates.normalize().isin(observed_sessions)
    is_open |= (dates > observed_sessions.max()) & (dates.weekday < 5)
    frames[("calendar.trading_sessions", "SSE", "daily")] = pd.DataFrame(
        {"Date": dates, "IsOpen": is_open.astype(int)}
    )

    def fetch(request):
        key = (str(request.dataset), request.symbol, request.frequency)
        if key not in frames and str(request.dataset).startswith("etf."):
            key = (str(request.dataset), "588080.SH", request.frequency)
        frame = frames[key].copy()
        column = "Date"
        values = pd.to_datetime(frame[column])
        request_end = pd.Timestamp(request.end)
        if len(str(request.end)) == 10:
            request_end += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        frame = frame.loc[
            values.between(pd.Timestamp(request.start), request_end)
        ].reset_index(drop=True)
        metadata = {"vendor": "functional-fixture"}
        if str(request.dataset) == "etf.unadjusted_daily":
            metadata["adjustment"] = "none"
        return frame, metadata

    flows = Dataflows({key[0]: fetch for key in frames})
    monkeypatch.setattr("strategy_runtime.preparation.Dataflows", lambda: flows)
    monkeypatch.setattr("czsc_trader.backtesting.service.Dataflows", lambda **kwargs: flows)
    monkeypatch.setattr("czsc_trader.research_tools.evaluation.Dataflows", lambda **kwargs: flows)
    monkeypatch.setattr(
        "czsc_trader.backtesting.execution_data.Dataflows", lambda: flows
    )
    for relative in (
        Path("S001/0824_EX04/artifacts/frozen_challenger.json"),
        Path("S001/0901_EX20/artifacts/frozen_challenger.json"),
        Path("S001/0902_EX02/artifacts/frozen_execution_policy.json"),
        Path("S001/0903_EX06/artifacts/frozen_challenger.json"),
        Path("S007/20260915_S007_EX04/artifacts/causal_feature_panel.csv.gz"),
    ):
        source = REPO_ROOT / "experiments" / relative
        if source.is_file():
            destination = root / "experiments" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (root / "experiments").mkdir(exist_ok=True)
    (root / "outputs").mkdir()
    return root
