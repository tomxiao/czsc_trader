"""S011 EX02: causal base and peripheral factor census without future returns."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json

from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
import pyarrow
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
import tsfresh
from tsfresh import extract_features
from tsfresh.feature_extraction import ComprehensiveFCParameters


EXPERIMENT_ID = "20260928_S011_EX02"
PREDECESSOR_ID = "20260928_S011_EX01"
PREDECESSOR_RECEIPT = "b086702fda537d0129a437d9013e75dd2b5e942ea7aef1d9d5fb4be1013da4e8"
SYMBOL = "159326.SZ"
START = "2024-09-09"
CUTOFF = "2026-09-24"
WINDOWS = (3, 5, 10, 20, 40, 60)
TSFRESH_WINDOWS = (10, 20, 60)
EXPECTED_SHA256 = {
    "etf_daily": "a197ebc57a54591c0c4a226ec1f7c64cf67bc0ca698968f6cfd582d656608ca3",
    "etf_30m": "8926257d0b2bb6c378f27c2555373b056416e1008b3880fe4bbd4ce987901131",
    "shares": "c786ffc7c0b790016c379dfaad43fbbf7b1dea9136fffe93e6307a25e64655ba",
    "market": "e1983f68713e3808c0b23ef1531e94f36c5332249f6b65336ffc05602d36dccd",
    "shibor": "bcaaf0ea3d63dd0cb0d4401230a2216f672ebbcc0bcde9f09a830e79ca696d44",
    "usdcnh": "c7a330eaa2d525a174f7ecbf9969332d1a8595d823df609e3146869f97125583",
}
REQUESTS = (
    ("etf_daily", Dataset.ETF_OHLCV, SYMBOL, "daily"),
    ("etf_30m", Dataset.ETF_OHLCV, SYMBOL, "30m"),
    ("shares", Dataset.ETF_SHARE_SIZE, SYMBOL, "daily"),
    ("market", Dataset.DOMESTIC_INDEX_DAILY, "000300.SH", "daily"),
    ("shibor", Dataset.SHIBOR_DAILY, None, "daily"),
    ("usdcnh", Dataset.USDCNH_DAILY, None, "daily"),
)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    value = numerator.astype(float) / denominator.astype(float)
    return value.where(np.isfinite(value))


def _lagged_source(frame: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    source = frame.copy()
    source["Date"] = pd.to_datetime(source["Date"]).dt.normalize()
    if source["Date"].duplicated().any():
        raise ValueError("peripheral source has duplicate dates")
    source = source.set_index("Date").sort_index()
    if source.index.max() > calendar.max():
        raise ValueError("peripheral source exceeds frozen ETF cutoff")
    return source.reindex(calendar, method="ffill").shift(1)


def _daily_intraday(frame: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, pd.Series]:
    bars = frame.copy().sort_values("Date").reset_index(drop=True)
    bars["Date"] = pd.to_datetime(bars["Date"])
    days = bars["Date"].dt.normalize()
    counts = days.value_counts().sort_index()
    if len(bars) != len(calendar) * 8 or not counts.index.equals(calendar) or not counts.eq(8).all():
        raise ValueError("30-minute calendar differs from eight bars per ETF session")
    opened = bars["Open"].to_numpy(dtype=float).reshape(-1, 8)
    high = bars["High"].to_numpy(dtype=float).reshape(-1, 8)
    low = bars["Low"].to_numpy(dtype=float).reshape(-1, 8)
    closed = bars["Close"].to_numpy(dtype=float).reshape(-1, 8)
    amount = bars["Amount"].to_numpy(dtype=float).reshape(-1, 8)
    bar_ret = np.log(closed / opened)
    total_amount = amount.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = {
            "i_first_bar_return": bar_ret[:, 0],
            "i_last_bar_return": bar_ret[:, -1],
            "i_morning_return": np.log(closed[:, 3] / opened[:, 0]),
            "i_afternoon_return": np.log(closed[:, -1] / opened[:, 4]),
            "i_first_amount_share": amount[:, 0] / total_amount,
            "i_last_amount_share": amount[:, -1] / total_amount,
            "i_amount_concentration": ((amount / total_amount[:, None]) ** 2).sum(axis=1),
            "i_realized_volatility": np.sqrt((bar_ret ** 2).sum(axis=1)),
            "i_daily_range": (high.max(axis=1) - low.min(axis=1)) / opened[:, 0],
            "i_close_location": (closed[:, -1] - low.min(axis=1)) / (high.max(axis=1) - low.min(axis=1)),
        }
    return {name: pd.Series(value, index=calendar).replace([np.inf, -np.inf], np.nan) for name, value in raw.items()}


def _manual_panel(
    daily: pd.DataFrame,
    intraday: pd.DataFrame,
    market: pd.DataFrame,
    shares: pd.DataFrame,
    shibor: pd.DataFrame,
    usdcnh: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    etf = daily.copy().sort_values("Date").reset_index(drop=True)
    etf["Date"] = pd.to_datetime(etf["Date"]).dt.normalize()
    calendar = pd.DatetimeIndex(etf["Date"])
    if len(calendar) != 496 or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("frozen ETF daily calendar changed")
    mkt = market.copy().sort_values("Date").reset_index(drop=True)
    mkt["Date"] = pd.to_datetime(mkt["Date"]).dt.normalize()
    if not pd.DatetimeIndex(mkt["Date"]).equals(calendar):
        raise ValueError("market and ETF trading calendars differ")
    share_lag = _lagged_source(shares, calendar)
    rate_lag = _lagged_source(shibor, calendar)
    fx_lag = _lagged_source(usdcnh, calendar)

    close = pd.Series(etf["Close"].to_numpy(dtype=float), index=calendar)
    opened = pd.Series(etf["Open"].to_numpy(dtype=float), index=calendar)
    high = pd.Series(etf["High"].to_numpy(dtype=float), index=calendar)
    low = pd.Series(etf["Low"].to_numpy(dtype=float), index=calendar)
    amount = pd.Series(etf["Amount"].to_numpy(dtype=float), index=calendar)
    volume = pd.Series(etf["Volume"].to_numpy(dtype=float), index=calendar)
    market_close = pd.Series(mkt["Close"].to_numpy(dtype=float), index=calendar)
    market_ret = np.log(market_close).diff()
    etf_ret = np.log(close).diff()
    share_level = np.log(share_lag["TotalShare"].astype(float))
    share_change = share_level.diff()
    rate_level = rate_lag["OvernightRate"].astype(float)
    rate_change = rate_level.diff()
    fx_mid = (fx_lag["BidClose"].astype(float) + fx_lag["AskClose"].astype(float)) / 2.0
    fx_return = np.log(fx_mid).diff()
    amihud = _safe_ratio(etf_ret.abs(), amount)

    panel = pd.DataFrame(index=calendar)
    panel["p_return_1"] = etf_ret
    panel["p_overnight_gap"] = np.log(opened / close.shift(1))
    panel["p_session_return"] = np.log(close / opened)
    panel["p_range"] = _safe_ratio(high - low, close.shift(1))
    panel["p_close_location"] = _safe_ratio(close - low, high - low)
    panel["l_log_amount"] = np.log1p(amount)
    panel["l_log_volume"] = np.log1p(volume)
    panel["l_amihud_1"] = amihud
    panel["x_market_return_1"] = market_ret
    panel["x_relative_return_1"] = etf_ret - market_ret
    panel["e_log_share_level"] = share_level
    panel["e_share_change_1"] = share_change
    panel["x_shibor_level"] = rate_level
    panel["x_shibor_change_1"] = rate_change
    panel["x_fx_mid_log_level"] = np.log(fx_mid)
    panel["x_fx_return_1"] = fx_return
    panel["c_weekday"] = calendar.dayofweek.astype(float)
    panel["c_month"] = calendar.month.astype(float)
    period = calendar.to_period("M")
    panel["c_last_trading_day_of_month"] = np.r_[period[:-1] != period[1:], True].astype(float)
    for name, value in _daily_intraday(intraday, calendar).items():
        panel[name] = value

    signed_amount = amount.where(etf_ret > 0, -amount)
    for window in WINDOWS:
        suffix = f"w{window}"
        panel[f"p_momentum_{suffix}"] = np.log(close / close.shift(window))
        panel[f"p_realized_volatility_{suffix}"] = etf_ret.rolling(window).std()
        panel[f"p_downside_volatility_{suffix}"] = etf_ret.clip(upper=0).rolling(window).std()
        panel[f"p_high_position_{suffix}"] = _safe_ratio(close, high.rolling(window).max()) - 1
        panel[f"p_low_position_{suffix}"] = _safe_ratio(close, low.rolling(window).min()) - 1
        panel[f"l_amount_change_{suffix}"] = np.log(amount / amount.shift(window))
        panel[f"l_amount_zscore_{suffix}"] = _safe_ratio(
            amount - amount.rolling(window).mean(), amount.rolling(window).std()
        )
        panel[f"l_volume_zscore_{suffix}"] = _safe_ratio(
            volume - volume.rolling(window).mean(), volume.rolling(window).std()
        )
        panel[f"l_signed_amount_balance_{suffix}"] = _safe_ratio(
            signed_amount.rolling(window).sum(), amount.rolling(window).sum()
        )
        panel[f"l_amihud_mean_{suffix}"] = amihud.rolling(window).mean()
        panel[f"x_market_momentum_{suffix}"] = np.log(market_close / market_close.shift(window))
        panel[f"x_market_volatility_{suffix}"] = market_ret.rolling(window).std()
        panel[f"x_relative_momentum_{suffix}"] = panel[f"p_momentum_{suffix}"] - panel[f"x_market_momentum_{suffix}"]
        panel[f"x_market_correlation_{suffix}"] = etf_ret.rolling(window).corr(market_ret)
        panel[f"e_share_change_{suffix}"] = share_level - share_level.shift(window)
        panel[f"x_shibor_change_{suffix}"] = rate_level - rate_level.shift(window)
        panel[f"x_fx_momentum_{suffix}"] = np.log(fx_mid / fx_mid.shift(window))
        panel[f"x_fx_volatility_{suffix}"] = fx_return.rolling(window).std()
    panel = panel.replace([np.inf, -np.inf], np.nan)
    if panel.isna().all().any():
        raise ValueError("a manual factor is undefined for the entire ETF window")
    raw = {
        "market_return": market_ret,
        "share_change": share_change,
        "shibor_change": rate_change,
        "fx_return": fx_return,
    }
    return panel, raw


def _window_rows(raw: dict[str, pd.Series], window: int, length: int) -> pd.DataFrame:
    rows: list[tuple[int, int, str, float]] = []
    for end in range(window, length):
        for kind, series in raw.items():
            values = series.iloc[end - window + 1 : end + 1].to_numpy(dtype=float)
            if not np.isfinite(values).all():
                continue
            rows.extend((end, position, kind, float(value)) for position, value in enumerate(values))
    return pd.DataFrame(rows, columns=("id", "time", "kind", "value"))


def _quality(frame: pd.DataFrame, panel: str, window: int) -> list[dict[str, object]]:
    values = frame.to_numpy(dtype=np.float64)
    rows: list[dict[str, object]] = []
    for number, name in enumerate(frame.columns):
        series = values[:, number]
        finite = np.isfinite(series)
        valid = series[finite]
        digest = sha256(finite.tobytes() + np.where(finite, series, 0.0).tobytes()).hexdigest()
        rows.append({
            "Panel": panel,
            "Window": window,
            "Feature": name,
            "Samples": len(series),
            "Finite": int(finite.sum()),
            "Coverage": float(finite.mean()),
            "Std": float(np.std(valid)) if len(valid) else np.nan,
            "UniqueFinite": int(np.unique(valid).size),
            "ExactColumnSha256": digest,
        })
    return rows


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Which causal ETF base and peripheral factors are calculable across the fixed window?",
            hypothesis="Market, ETF creation flow, rates and FX may provide nonredundant state descriptions.",
            falsification_conditions=(
                "EX01 predecessor receipt differs",
                "Any frozen governed input is unavailable or changes identity",
                "Source timing, calendars, full feature extraction or archive contract fails",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=20260902,
            allowed_datasets=tuple(sorted({item[1].value for item in REQUESTS})),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Decision-time peripheral state may add information beyond the ETF's own prices",),
                information_paths=("Observed external state -> later ETF price behavior, not tested here",),
                stage_objectives=("Census available handcrafted and full tsfresh peripheral factors",),
                observation_metrics=("Factor coverage, variance, undefined values and exact redundancy",),
                methodology=("Use governed fixed-window data, conservative lags and trailing-only windows",),
                predecessor_experiment_ids=(PREDECESSOR_ID,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("pyarrow", pyarrow.__version__),
                ExperimentDependency("tsfresh", tsfresh.__version__),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def synthetic_precheck(self) -> None:
        dates = pd.date_range("2024-01-02", periods=4, freq="D")
        source = pd.DataFrame({"Date": dates[:3], "Value": [10.0, 20.0, 30.0]})
        lagged = _lagged_source(source, dates)
        if not pd.isna(lagged.iloc[0, 0]) or lagged["Value"].iloc[1:].tolist() != [10.0, 20.0, 30.0]:
            raise ValueError("peripheral lag may include a current or future observation")
        raw = {"x": pd.Series(np.arange(12, dtype=float))}
        sample = _window_rows(raw, 4, 12)
        if sample.loc[sample["id"].eq(4), "value"].tolist() != [1.0, 2.0, 3.0, 4.0]:
            raise ValueError("tsfresh trailing window includes future input")
        settings = ComprehensiveFCParameters()
        if len(settings) != 75 or sum(1 if item is None else len(item) for item in settings.values()) != 788:
            raise ValueError("installed tsfresh comprehensive scope changed")
        test = extract_features(sample, column_id="id", column_sort="time", column_kind="kind",
                                column_value="value", default_fc_parameters={"mean": None},
                                n_jobs=1, disable_progressbar=True)
        if not np.isclose(test.loc[4, "x__mean"], 2.5):
            raise ValueError("synthetic tsfresh extraction differs")

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR_ID]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX01 receipt differs from frozen predecessor")
        frames: dict[str, pd.DataFrame] = {}
        identities: list[dict[str, object]] = []
        for label, dataset, symbol, frequency in REQUESTS:
            result = context.data.fetch(DataRequest(
                dataset=dataset, symbol=symbol, start=START, end=CUTOFF,
                required_cutoff=CUTOFF, frequency=frequency, options={"env_file": ".env"},
            ))
            if result.status is not DataStatus.READY or result.identity is None:
                raise RuntimeError(f"governed {label} input not READY: {result.error}")
            identity = result.identity
            if identity.content_sha256 != EXPECTED_SHA256[label]:
                raise ValueError(f"frozen {label} input content changed")
            frames[label] = result.dataframe
            identities.append({
                "Input": label, "Dataset": identity.dataset, "Source": identity.source,
                "Symbol": identity.symbol, "Rows": len(result.dataframe),
                "Start": identity.data_start, "Cutoff": identity.data_cutoff,
                "Sha256": identity.content_sha256,
                "AvailableAt": identity.temporal_contract.available_at,
            })
        manual, raw = _manual_panel(
            frames["etf_daily"], frames["etf_30m"], frames["market"],
            frames["shares"], frames["shibor"], frames["usdcnh"],
        )
        artifacts = []
        manual.to_parquet(context.workspace.path("manual_factor_panel.parquet"), compression="zstd", index=True)
        artifacts.append(context.workspace.register_artifact("manual_factor_panel.parquet", "manual-factor-panel"))
        quality_rows = _quality(manual, "manual", 0)
        settings = ComprehensiveFCParameters()
        panels: list[dict[str, object]] = [{"panel": "manual", "window": 0, "samples": len(manual), "features": len(manual.columns)}]
        for window in TSFRESH_WINDOWS:
            samples = _window_rows(raw, window, len(manual))
            if samples.empty:
                raise ValueError(f"no valid peripheral samples for window {window}")
            features = extract_features(
                samples, column_id="id", column_sort="time", column_kind="kind", column_value="value",
                default_fc_parameters=settings, n_jobs=1, disable_progressbar=True, impute_function=None,
            ).sort_index(axis=0).sort_index(axis=1)
            if features.empty:
                raise ValueError(f"tsfresh returned no columns for window {window}")
            name = f"tsfresh_peripheral_w{window}.parquet"
            features.to_parquet(context.workspace.path(name), compression="zstd", index=True)
            artifacts.append(context.workspace.register_artifact(name, "tsfresh-peripheral-panel"))
            quality_rows.extend(_quality(features, "peripheral", window))
            panels.append({"panel": "peripheral", "window": window, "samples": len(features), "features": len(features.columns)})
        quality = pd.DataFrame(quality_rows)
        quality.to_csv(context.workspace.path("factor_quality.csv.gz"), index=False,
                       compression={"method": "gzip", "compresslevel": 9, "mtime": 0}, lineterminator="\n")
        artifacts.append(context.workspace.register_artifact("factor_quality.csv.gz", "factor-quality-ledger"))
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        artifacts.append(context.workspace.register_artifact("input_identities.csv", "governed-input-identities"))
        summary = {
            "decision": "PERIPHERAL_FACTOR_CENSUS_COMPLETE",
            "panels": panels,
            "factor_columns": len(quality),
            "coverage_95": int(quality["Coverage"].ge(0.95).sum()),
            "undefined": int(quality["Finite"].eq(0).sum()),
            "constant": int(quality["UniqueFinite"].le(1).sum()),
            "exact_duplicate_columns": int(quality.duplicated(["Panel", "Window", "ExactColumnSha256"]).sum()),
            "reads_real_returns": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "census-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": summary["decision"], "factor_columns": summary["factor_columns"],
                "coverage_95": summary["coverage_95"], "undefined": summary["undefined"],
                "exact_duplicate_columns": summary["exact_duplicate_columns"],
            },
            diagnostics={"reads_real_returns": False, "creates_candidate": False},
            artifacts=tuple(artifacts),
        )
