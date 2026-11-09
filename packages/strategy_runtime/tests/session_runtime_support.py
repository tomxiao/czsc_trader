"""Small real source/data fixtures shared by SRT and host integration tests."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import pandas as pd
from dataflows import Dataflows, Dataset, DataSpace, ProviderConfig, ProviderBinding
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence, verify_daily_sessions
from strategy_runtime import StrategyCandidate, implementation_sha256


def make_runtime_candidate(tmp_path):
    source = tmp_path / "source/strategy_runtime"
    target = source / "strategies/current_fixture.py"
    target.parent.mkdir(parents=True)
    root = Path(__file__).resolve().parents[3]
    shutil.copyfile(root / "tests/fixtures/candidate_runtime.py", target)
    files = ("strategies/current_fixture.py",)
    return StrategyCandidate("S900","C0001",{
        "runtime":{"module":"strategy_runtime.strategies.current_fixture","qualname":"CandidateFixture",
                   "contract_version":1,"source_files":list(files),
                   "source_sha256":implementation_sha256(files,source_root=source)},
        "parameters":{"threshold":.5}}, source)


def _flows(tmp_path, *, flow_value=0.8) -> Dataflows:
    # The fixture strategy needs one prior session; five dates also cover the
    # latest-available cutoff scenario without unrelated multi-year history.
    dates = pd.bdate_range(end="2026-09-02", periods=5)
    bars = pd.DataFrame(
        {
            "Date": dates,
            "Flow": flow_value,
            "TotalShare": 100000.0,
            "Open": pd.array([9.4] * len(dates), dtype="Float64"),
            "High": pd.array([9.5] * len(dates), dtype="Float64"),
            "Low": pd.array([9.3] * len(dates), dtype="Float64"),
            "Close": pd.array(
                [9.417734788764953] * len(dates), dtype="Float64"
            ),
            "Volume": pd.array([1000] * len(dates), dtype="Int64"),
            "Amount": pd.array([9400.0] * len(dates), dtype="Float64"),
        }
    )

    def market(request):
        frame = bars.loc[pd.to_datetime(bars["Date"]).between(request.start, request.end)].copy()
        metadata = {
            "vendor": "test",
            "adjustment": "none" if "unadjusted" in request.dataset else "hfq",
            "primary_key": ["Date"],
        }
        if request.dataset in {Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY}:
            pro = SimpleNamespace(
                fund_basic=lambda **kwargs: pd.DataFrame({
                    "ts_code": [request.symbol], "list_date": [dates[0].strftime("%Y%m%d")],
                }),
                trade_cal=lambda **kwargs: pd.DataFrame({
                    "cal_date": pd.date_range(kwargs["start_date"], kwargs["end_date"]).strftime("%Y%m%d"),
                    "is_open": (pd.date_range(kwargs["start_date"], kwargs["end_date"]).dayofweek < 5).astype(int),
                }),
            )
            coverage = verify_daily_sessions(pro, request.symbol, frame,
                start=request.start, end=request.end)
            quality = build_quality_evidence(frame, expected_dates=coverage["expected_dates"])
            metadata.update(daily_session_coverage=coverage,
                ohlcv_quality_evidence=bind_quality_frame(quality, frame,
                    adjustment=metadata["adjustment"]))
            frame.attrs = {name: metadata[name] for name in
                           ("daily_session_coverage", "ohlcv_quality_evidence")}
        return frame, metadata

    def calendar(request):
        days = pd.date_range(request.start, request.end)
        return pd.DataFrame({"Date": days, "IsOpen": (days.dayofweek < 5).astype(int)}), {
            "vendor": "test",
            "primary_key": ["Date"],
        }

    return Dataflows(base_dir=tmp_path, space=DataSpace(Path("assets")), providers=ProviderConfig({
        dataset: ProviderBinding("test", "1", provider) for dataset, provider in {
            Dataset.ETF_SHARE_SIZE: market, Dataset.ETF_OHLCV: market,
            Dataset.ETF_UNADJUSTED_DAILY: market, Dataset.TRADING_CALENDAR: calendar,
        }.items()
    }))
