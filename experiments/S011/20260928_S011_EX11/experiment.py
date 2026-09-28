"""S011 EX11: return-blind census of currently accessible trading factors."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dataflows import DataRequest, DataStatus, Dataset
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


EXPERIMENT_ID = "20260928_S011_EX11"
PREDECESSOR = "20260928_S011_EX10"
PREDECESSOR_RECEIPT = "7ac889c77b4a76dd934979a8f102ea1e8db82e664868813598d10701aa743f6f"
START = "2024-09-09"
THEME_START = "2024-10-24"
END = "2026-09-24"
SEED = 2026092811
EX06_LEDGER_SHA256 = "e78f2e91b7f15067d4150268846880beac1c9be13d387e718dfdb1f02ae33aed"
EX09_LEDGER_SHA256 = "0980ad37b53c5de87e1c6bd2999c0cd77f8bb31f59c6fbfe56bc22a1b8eae934"
EX02_SNAPSHOT_SHA256 = "35b9eb90192b44a0adc6c10b0b9208e65fa408727a5fc3973aacf6a8902eab57"
EX02_REPORT_SHA256 = "12966da51cb5c439ff9f933f6e18a12803640dcba93a912d0ba2e1af9de9aaa1"
EXISTING_DAILY = (
    "TrendReturn20",
    "TrendEfficiency20",
    "VolatilityRatio5To20",
    "VolumeShock20",
    "SignedVolumePressure20",
    "LogAmihud20",
    "ThemeRelativeReturn20",
    "ShareChange5",
)
EXISTING_INTRADAY = (
    "OpeningHourReturn",
    "AfternoonReturn",
    "TailAcceleration",
    "OpeningHourVolumeShare",
    "TailVolumeShare",
    "DownVolumeShare",
    "RealizedVolatilityRatio20",
    "CloseLocation",
)
REQUESTS = (
    ("etf_daily", Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ", START, "daily", True),
    ("etf_30m", Dataset.ETF_OHLCV, "159326.SZ", START, "30m", True),
    ("theme_daily", Dataset.DOMESTIC_INDEX_DAILY, "931994.CSI", THEME_START, "daily", True),
    ("market_daily", Dataset.DOMESTIC_INDEX_DAILY, "000300.SH", START, "daily", True),
    ("etf_shares", Dataset.ETF_SHARE_SIZE, "159326.SZ", START, "daily", True),
    ("theme_turnover", Dataset.INDEX_DAILY_BASIC, "931994.CSI", START, "daily", False),
    ("market_turnover", Dataset.INDEX_DAILY_BASIC, "000300.SH", START, "daily", False),
    ("stock_moneyflow_sample", Dataset.STOCK_MONEYFLOW, "600487.SH", START, "daily", False),
)
PRIOR_SOURCE_HASHES = {
    "etf_daily": "a197ebc57a54591c0c4a226ec1f7c64cf67bc0ca698968f6cfd582d656608ca3",
    "etf_30m": "8926257d0b2bb6c378f27c2555373b056416e1008b3880fe4bbd4ce987901131",
    "theme_daily": "720f251694ef27558a984e0988b33aca29af8a25aeee859f3352ac252cb6ceb7",
    "etf_shares": "c786ffc7c0b790016c379dfaad43fbbf7b1dea9136fffe93e6307a25e64655ba",
}


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _daily(frame: pd.DataFrame) -> pd.DataFrame:
    value = frame.copy()
    value["Date"] = pd.to_datetime(value["Date"], errors="raise").dt.normalize()
    if value["Date"].duplicated().any():
        raise ValueError("daily source has duplicate dates")
    return value.set_index("Date").sort_index()


def _build_factors(
    etf: pd.DataFrame,
    theme: pd.DataFrame,
    market: pd.DataFrame,
    daily_ledger: pd.DataFrame,
    intraday_ledger: pd.DataFrame,
    market_turnover: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    etf = _daily(etf)
    theme = _daily(theme)
    market = _daily(market)
    factors = pd.DataFrame(index=etf.index)
    roles: dict[str, str] = {}
    for ledger, names, role in (
        (daily_ledger, EXISTING_DAILY, "EX06_REUSE"),
        (intraday_ledger, EXISTING_INTRADAY, "EX09_REUSE"),
    ):
        indexed = _daily(ledger)
        missing = sorted(set(names).difference(indexed.columns))
        if missing:
            raise ValueError(f"frozen feature ledger is missing fields: {missing}")
        for name in names:
            factors[name] = pd.to_numeric(indexed[name].reindex(factors.index), errors="raise")
            roles[name] = role

    close = pd.to_numeric(etf["Close"], errors="raise")
    volume = pd.to_numeric(etf["Volume"], errors="raise")
    amount = pd.to_numeric(etf["Amount"], errors="raise")
    theme_close = pd.to_numeric(theme["Close"], errors="raise").reindex(factors.index)
    market_close = pd.to_numeric(market["Close"], errors="raise").reindex(factors.index)
    log_close = np.log(close)
    log_volume = np.log(volume)
    log_amount = np.log(amount)
    new = {
        "ETFReturn1": log_close.diff(),
        "ETFReturn5": log_close.diff(5),
        "ETFRange": (etf["High"] - etf["Low"]) / close,
        "ETFCloseLocation": (close - etf["Low"]) / (etf["High"] - etf["Low"]),
        "ETFGappedOpen": np.log(etf["Open"] / close.shift(1)),
        "ETFDrawdown20": close / close.rolling(20, min_periods=20).max() - 1.0,
        "ETFRealizedVol20": log_close.diff().rolling(20, min_periods=20).std(ddof=0),
        "ETFVolumeChange1": log_volume.diff(),
        "ETFAmountChange1": log_amount.diff(),
        "ThemeReturn5": np.log(theme_close).diff(5),
        "ThemeReturn20": np.log(theme_close).diff(20),
        "MarketReturn20": np.log(market_close).diff(20),
        "ETFMarketRelativeReturn20": log_close.diff(20) - np.log(market_close).diff(20),
        "ETFThemeRelativeReturn5": log_close.diff(5) - np.log(theme_close).diff(5),
    }
    for name, values in new.items():
        factors[name] = values
        roles[name] = "NEW_CLOSE_KNOWN"
    if market_turnover is not None:
        turnover = _daily(market_turnover)["TurnoverRateFreeFloat"]
        factors["MarketTurnoverRate"] = pd.to_numeric(
            turnover.reindex(factors.index), errors="raise"
        )
        roles["MarketTurnoverRate"] = "AVAILABILITY_UNVERIFIED"
    factors = factors.replace([np.inf, -np.inf], np.nan)
    return factors, roles


def _census(factors: pd.DataFrame, roles: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    correlation = factors.corr(method="spearman", min_periods=100)
    rows: list[dict[str, object]] = []
    for name in factors.columns:
        series = pd.to_numeric(factors[name], errors="raise")
        valid = series.dropna()
        peer = correlation[name].drop(index=name).abs().dropna()
        closest = None if peer.empty else str(peer.idxmax())
        closest_value = None if peer.empty else float(peer.max())
        rolling = series.shift(1).rolling(120, min_periods=60)
        low, high = rolling.quantile(0.20), rolling.quantile(0.80)
        ready = low.notna() & high.notna() & series.notna()
        extreme = (series.le(low) | series.ge(high)) & ready
        changes = series.diff().abs().dropna()
        rows.append(
            {
                "Factor": name,
                "SourceClass": roles[name],
                "CalendarRows": len(series),
                "AvailableRows": len(valid),
                "Coverage": float(len(valid) / len(series)),
                "FirstDate": None if valid.empty else valid.index.min().date(),
                "LastDate": None if valid.empty else valid.index.max().date(),
                "UniqueValues": int(valid.nunique()),
                "P10": None if valid.empty else float(valid.quantile(0.10)),
                "Median": None if valid.empty else float(valid.median()),
                "P90": None if valid.empty else float(valid.quantile(0.90)),
                "Lag1Autocorrelation": None if len(valid) < 3 else float(series.autocorr()),
                "MedianAbsoluteDailyChange": None if changes.empty else float(changes.median()),
                "ExtremeReferenceRows": int(ready.sum()),
                "ExtremeStates": int(extreme.sum()),
                "ClosestFactor": closest,
                "AbsoluteSpearmanWithClosest": closest_value,
                "RedundantAt085": bool(closest_value is not None and closest_value >= 0.85),
            }
        )
    return pd.DataFrame(rows), correlation


def synthetic_precheck() -> None:
    dates = pd.bdate_range("2024-01-02", periods=180)
    phase = np.arange(len(dates), dtype=float)
    close = 1.0 + phase * 0.001 + 0.02 * np.sin(phase / 7)
    etf = pd.DataFrame(
        {
            "Date": dates,
            "Open": close * 0.999,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000 + phase * 1000,
            "Amount": (1_000_000 + phase * 1000) * close,
        }
    )
    ledger = pd.DataFrame({"Date": dates})
    for name in EXISTING_DAILY + EXISTING_INTRADAY:
        ledger[name] = np.sin(phase / 9) + phase / 1000
    theme = pd.DataFrame({"Date": dates, "Close": 100 + phase * 0.1})
    panel, roles = _build_factors(etf, theme, theme, ledger, ledger, None)
    census, _ = _census(panel, roles)
    if len(panel) != 180 or len(census) != 30:
        raise ValueError("synthetic factor census dimensions changed")
    if not np.isclose(panel["ETFReturn5"].iloc[5], np.log(close[5] / close[0])):
        raise ValueError("backward ETF return alignment changed")
    edited = etf.copy()
    edited.loc[179, "Close"] *= 2
    earlier, _ = _build_factors(edited, theme, theme, ledger, ledger, None)
    if not panel.iloc[:-1].equals(earlier.iloc[:-1]):
        raise ValueError("later input changed earlier factor values")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Which currently accessible S011 trading and peripheral datasets can form "
                "causal, sufficiently covered and nonduplicate factors without reading outcomes?"
            ),
            hypothesis=(
                "A source and factor census can locate observable trading states and the "
                "data gaps that need resolution before proposing another alpha hypothesis."
            ),
            falsification_conditions=(
                "Mandatory DFLS sources are unavailable",
                "Frozen predecessor ledgers differ",
                "Factor calculations use data beyond their decision date",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=tuple(sorted({spec[1].value for spec in REQUESTS})),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "A factor must be observable at the intended decision time",
                    "Coverage and distinctness precede any return association test",
                ),
                information_paths=(
                    "Trading path and peripheral supply-demand observations -> candidate states for later testing",
                ),
                stage_objectives=(
                    "Inventory current DFLS sources relevant to the 159326 trading path",
                    "Census frozen and additional backward-looking factors without future outcomes",
                ),
                observation_metrics=(
                    "source status, rows and availability contract",
                    "factor coverage, distribution, changes, extreme-state density and redundancy",
                ),
                methodology=(
                    "Reuse EX06 and EX09 frozen factor ledgers with verified file identities",
                    "Fetch eight fixed DFLS source requests; record optional EMPTY or FAILED sources explicitly",
                    "Do not calculate future returns, information coefficients or trading performance",
                    "Report availability-uncertain fields without promoting them to causal factors",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(),
            subjects=("159326.SZ",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        if context.predecessors[PREDECESSOR].receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX10 predecessor receipt differs")
        root = Path(__file__).resolve().parents[3]
        sources = {
            "EX06": (
                root / "experiments/S011/20260928_S011_EX06/artifacts/feature_ledger.csv.gz",
                EX06_LEDGER_SHA256,
            ),
            "EX09": (
                root
                / "experiments/S011/20260928_S011_EX09/artifacts/intraday_feature_ledger.csv.gz",
                EX09_LEDGER_SHA256,
            ),
            "EX02_snapshots": (
                root / "experiments/S011/20260928_S011_EX02/artifacts/index_snapshots.csv.gz",
                EX02_SNAPSHOT_SHA256,
            ),
            "EX02_reports": (
                root / "experiments/S011/20260928_S011_EX02/artifacts/sell_side_reports.csv.gz",
                EX02_REPORT_SHA256,
            ),
        }
        for name, (path, expected) in sources.items():
            if _sha256(path) != expected:
                raise ValueError(f"{name} frozen artifact differs")

        frames: dict[str, pd.DataFrame] = {}
        catalog: list[dict[str, object]] = []
        for key, dataset, symbol, start, frequency, mandatory in REQUESTS:
            result = context.data.fetch(
                DataRequest(
                    dataset,
                    symbol,
                    start,
                    END,
                    END if mandatory else None,
                    frequency,
                    {"env_file": ".env"},
                )
            )
            identity = result.identity
            prior_hash = PRIOR_SOURCE_HASHES.get(key)
            catalog.append(
                {
                    "Input": key,
                    "Dataset": dataset.value,
                    "Symbol": symbol,
                    "Status": result.status.value,
                    "Rows": len(result.dataframe),
                    "FirstDate": None if identity is None else identity.data_start,
                    "LastDate": None if identity is None else identity.data_cutoff,
                    "ContentSha256": None if identity is None else identity.content_sha256,
                    "PriorContentSha256": prior_hash,
                    "MatchesPrior": None
                    if prior_hash is None or identity is None
                    else identity.content_sha256 == prior_hash,
                    "AvailableAt": None
                    if identity is None
                    else identity.temporal_contract.available_at,
                    "DecisionAvailability": (
                        "NEXT_SESSION"
                        if key == "etf_shares"
                        else "UNVERIFIED"
                        if key in {"theme_turnover", "market_turnover", "stock_moneyflow_sample"}
                        else "SAME_SESSION_CLOSE"
                    ),
                    "ErrorCode": None if result.error is None else result.error.code,
                    "Mandatory": mandatory,
                }
            )
            if result.status is DataStatus.READY:
                frames[key] = result.dataframe.copy()
            elif mandatory:
                raise ValueError(f"mandatory source {key} is {result.status.value}")
        for key, (path, expected) in sources.items():
            catalog.append(
                {
                    "Input": key,
                    "Dataset": "frozen_experiment_artifact",
                    "Symbol": "159326.SZ",
                    "Status": "READY",
                    "Rows": len(pd.read_csv(path)),
                    "FirstDate": None,
                    "LastDate": None,
                    "ContentSha256": expected,
                    "PriorContentSha256": None,
                    "MatchesPrior": None,
                    "AvailableAt": "SEE_PREDECESSOR_CONTRACT",
                    "DecisionAvailability": "SEE_PREDECESSOR_CONTRACT",
                    "ErrorCode": None,
                    "Mandatory": True,
                }
            )
        daily_ledger = pd.read_csv(sources["EX06"][0])
        intraday_ledger = pd.read_csv(sources["EX09"][0])
        factors, roles = _build_factors(
            frames["etf_daily"],
            frames["theme_daily"],
            frames["market_daily"],
            daily_ledger,
            intraday_ledger,
            frames.get("market_turnover"),
        )
        census, correlation = _census(factors, roles)
        source_catalog = pd.DataFrame(catalog)
        status = (
            "CENSUS_COMPLETE_WITH_GAPS"
            if source_catalog["Status"].ne("READY").any()
            else "CENSUS_COMPLETE"
        )
        summary = {
            "decision": status,
            "calendar_sessions": len(factors),
            "factor_count": len(census),
            "causal_ready_factor_count": int(
                census["SourceClass"].ne("AVAILABILITY_UNVERIFIED").sum()
            ),
            "factors_with_95pct_coverage": int(census["Coverage"].ge(0.95).sum()),
            "redundant_at_085_count": int(census["RedundantAt085"].sum()),
            "source_ready": int(source_catalog["Status"].eq("READY").sum()),
            "source_not_ready": int(source_catalog["Status"].ne("READY").sum()),
            "changed_prior_sources": source_catalog.loc[
                source_catalog["MatchesPrior"].eq(False), "Input"
            ].tolist(),
            "reads_future_returns": False,
            "reads_sealed_validation": False,
            "candidate_created": False,
            "alpha_claimed": False,
        }
        source_catalog.to_csv(context.workspace.path("source_catalog.csv"), index=False)
        census.to_csv(context.workspace.path("factor_census.csv"), index=False)
        correlation.to_csv(context.workspace.path("factor_spearman.csv"))
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        artifacts = tuple(
            context.workspace.register_artifact(name, kind)
            for name, kind in (
                ("source_catalog.csv", "dfls-source-catalog"),
                ("factor_census.csv", "return-blind-factor-census"),
                ("factor_spearman.csv", "return-blind-factor-redundancy"),
                ("summary.json", "return-blind-census-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts=summary,
            diagnostics={
                "optional_nonready_sources": source_catalog.loc[
                    source_catalog["Status"].ne("READY"), "Input"
                ].tolist()
            },
            artifacts=artifacts,
        )
