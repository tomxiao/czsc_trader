"""S007 engineering reproduction from independently owned, hash-pinned inputs.

This entry reproduces the existing 101-feature panel without selecting a model,
reading future-return labels, or changing any sealed experiment or release.
Historical provenance is retained in materialization_inputs.json; it is never
used as a runtime input path. Run from the repository with --output under .tmp.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from dataflows import (
    Dataflows, DataRequest, DataSpace, Dataset, EvidenceParameters,
    PreparePolicy, ProviderBinding, ProviderConfig,
)
from tsfresh import extract_features
from tsfresh.feature_extraction import MinimalFCParameters


def load_inputs(repo: Path, data_space: DataSpace) -> dict[str, pd.DataFrame]:
    manifest = json.loads((Path(__file__).parent / "materialization_inputs.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1 or manifest["owner"] != "S007":
        raise ValueError("input manifest identity differs")
    owned = (repo / "data/research/S007/materialization_inputs").resolve()
    entries = manifest["inputs"]
    frames = {}
    requests = []
    for name, item in entries.items():
        source = (repo / item["path"]).resolve()
        if source.parent != owned or source.is_symlink():
            raise ValueError("input must be an S007-owned regular asset")
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"input hash differs: {name}")
        frame = pd.read_csv(source)
        if len(frame) != item["rows"]:
            raise ValueError(f"input row count differs: {name}")
        frame["Date"] = pd.to_datetime(frame[item["date_column"]].astype(str), errors="raise")
        frame["__row"] = np.arange(len(frame))
        frames[name] = frame.sort_values(["Date", "__row"]).reset_index(drop=True)
        requests.append(DataRequest(
            Dataset.STRATEGY_FEATURE_EVIDENCE, name, item["start"], item["end"], None,
            parameters=EvidenceParameters(repo, item["path"], item["sha256"]),
        ))

    def publish(request: DataRequest):
        item = entries[request.symbol]
        return frames[request.symbol].copy(), {
            "vendor": "repository", "primary_key": ["Date", "__row"],
            "source_path": item["path"], "source_sha256": item["sha256"],
            "source_time_field": "Date", "availability_time_field": "Date",
            "source_calendar": "S007 historical input mapping",
            "available_at": "Historical mapping preserved; not independently revalidated",
            "request_range_policy": "EXACT",
        }

    flows = Dataflows(base_dir=repo, space=data_space, providers=ProviderConfig(bindings={
        Dataset.STRATEGY_FEATURE_EVIDENCE: ProviderBinding("s007-owned-inputs", "1", publish),
    }))
    prepared = flows.prepare(tuple(requests), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        raise ValueError(f"input preparation failed: {prepared.items}")
    result = {}
    for request in requests:
        fetched = flows.fetch(request, prepared=prepared.reference)
        if not fetched.ready:
            raise ValueError(f"input fetch failed: {fetched.error}")
        result[request.symbol] = fetched.dataframe.sort_values("__row").drop(columns=["Date", "__row"]).reset_index(drop=True)
    return result


def extract_rolling_features(frame: pd.DataFrame, lookback: int) -> pd.DataFrame:
    windows = []
    for end in range(lookback - 1, len(frame)):
        window = frame.iloc[end - lookback + 1:end + 1].copy()
        window["window_id"] = end
        windows.append(window)
    expanded = pd.concat(windows, ignore_index=True)
    features = extract_features(
        expanded, column_id="window_id", column_sort="date",
        default_fc_parameters=MinimalFCParameters(), n_jobs=1,
        disable_progressbar=True,
    ).sort_index(axis=1)
    features.index = pd.DatetimeIndex(frame.iloc[features.index]["date"], name="date")
    return features.rename(columns=lambda name: f"tsfresh__{name}__lb{lookback}")


def _feature_meta(name: str, hypothesis: str, family: str, availability: str, provider: str) -> dict[str, str]:
    return {
        "feature": name,
        "hypothesis_id": hypothesis,
        "information_family": family,
        "availability": availability,
        "provider": provider,
    }


def _weighted_std(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & weights.gt(0)
    if not mask.any():
        return float("nan")
    value = values.loc[mask].astype(float)
    weight = weights.loc[mask].astype(float)
    mean = np.average(value, weights=weight)
    return float(np.sqrt(np.average((value - mean) ** 2, weights=weight)))


def materialize(repo: Path, data_space: DataSpace) -> tuple[pd.DataFrame, pd.DataFrame]:
    inputs = load_inputs(repo, data_space)
    daily = inputs["etf_daily"]
    daily["date"] = pd.to_datetime(daily["date"])
    sessions = pd.DatetimeIndex(daily["date"], name="date")
    panel = pd.DataFrame(index=sessions)
    metadata: list[dict[str, str]] = []

    # H01: domestic and overseas risk appetite, all known by the 20:30 decision time.
    shibor = inputs["shibor"].copy()
    shibor["date"] = pd.to_datetime(shibor["date"].astype(str), format="%Y%m%d", errors="raise")
    rates = shibor.set_index("date").sort_index().reindex(sessions).ffill(limit=4)
    for tenor in ("on", "1w", "3m"):
        panel[f"risk_shibor_{tenor}_change_1d"] = pd.to_numeric(rates[tenor]).diff()
        panel[f"risk_shibor_{tenor}_change_5d"] = pd.to_numeric(rates[tenor]).diff(5)
        metadata.extend(
            [
                _feature_meta(f"risk_shibor_{tenor}_change_1d", "H01-RISK-APPETITE", "INTEREST_RATE", "T 12:00", "tushare.shibor"),
                _feature_meta(f"risk_shibor_{tenor}_change_5d", "H01-RISK-APPETITE", "INTEREST_RATE", "T 12:00", "tushare.shibor"),
            ]
        )
    panel["risk_shibor_slope_3m_on"] = pd.to_numeric(rates["3m"]) - pd.to_numeric(rates["on"])
    metadata.append(_feature_meta("risk_shibor_slope_3m_on", "H01-RISK-APPETITE", "INTEREST_RATE", "T 12:00", "tushare.shibor"))

    indices = inputs["broad_risk_indices"].copy()
    indices["trade_date"] = pd.to_datetime(
        indices["trade_date"].astype(str), format="%Y%m%d", errors="raise"
    )
    aliases = {"000001.SH": "sse", "000905.SH": "csi500", "399006.SZ": "chinext"}
    for code, alias in aliases.items():
        frame = indices.loc[indices["ts_code"].eq(code)].set_index("trade_date").sort_index().reindex(sessions)
        close = pd.to_numeric(frame["close"])
        turnover = pd.to_numeric(frame["turnover_rate_f"])
        for horizon in (1, 5):
            name = f"risk_{alias}_return_{horizon}d"
            panel[name] = close.pct_change(horizon, fill_method=None)
            metadata.append(_feature_meta(name, "H01-RISK-APPETITE", "MARKET_RISK_APPETITE", "T close+", "tushare.index_daily"))
        name = f"risk_{alias}_turnover_z20"
        panel[name] = (turnover - turnover.rolling(20).mean()) / turnover.rolling(20).std(ddof=0)
        metadata.append(_feature_meta(name, "H01-RISK-APPETITE", "MARKET_RISK_APPETITE", "T close+", "tushare.index_dailybasic"))

    global_tech = inputs["global_technology_panel"].copy()
    global_tech["a_share_session"] = pd.to_datetime(global_tech["a_share_session"])
    piv = global_tech.pivot(index="a_share_session", columns="source_code", values="return_pct").reindex(sessions) / 100.0
    panel["risk_global_ixic_return"] = piv["IXIC"]
    panel["risk_global_spx_return"] = piv["SPX"]
    semis = piv[["AMD", "AVGO", "NVDA", "QCOM", "TSM"]]
    panel["risk_global_semis_mean_return"] = semis.mean(axis=1)
    panel["risk_global_semis_positive_breadth"] = semis.gt(0).mean(axis=1)
    for name in ("risk_global_ixic_return", "risk_global_spx_return", "risk_global_semis_mean_return", "risk_global_semis_positive_breadth"):
        metadata.append(_feature_meta(name, "H01-RISK-APPETITE", "GLOBAL_RISK_APPETITE", "before T open", "tushare.global/us_daily"))

    # H02: point-in-time sell-side revisions, mapped to the declared available session.
    forecasts = inputs["active_constituent_forecasts"].copy()
    forecasts["available_session"] = pd.to_datetime(forecasts["available_session"])
    forecasts["report_date"] = pd.to_datetime(forecasts["report_date"])
    forecasts = forecasts.sort_values(["ts_code", "org_name", "quarter", "report_date", "available_session"])
    forecasts["estimate"] = pd.to_numeric(forecasts["np"]).where(pd.to_numeric(forecasts["np"]).notna(), pd.to_numeric(forecasts["eps"]))
    forecasts["prior_estimate"] = forecasts.groupby(["ts_code", "org_name", "quarter"], dropna=False)["estimate"].shift()
    valid_prior = forecasts["prior_estimate"].abs().gt(1e-12)
    forecasts["revision"] = ((forecasts["estimate"] - forecasts["prior_estimate"]) / forecasts["prior_estimate"].abs()).where(valid_prior)
    revisions = forecasts.loc[forecasts["revision"].notna()].copy()
    revisions["signed_weight"] = np.sign(revisions["revision"]) * pd.to_numeric(revisions["weight"]).clip(lower=0)
    grouped = revisions.groupby("available_session").agg(
        revision_signed_weight=("signed_weight", "sum"),
        revision_total_weight=("weight", "sum"),
        revision_count=("revision", "size"),
        revision_magnitude=("revision", lambda value: float(value.abs().median())),
    )
    daily_revision = grouped.reindex(sessions).fillna(0.0)
    panel["expectation_revision_breadth_20"] = daily_revision["revision_signed_weight"].rolling(20).sum() / daily_revision["revision_total_weight"].rolling(20).sum().replace(0, np.nan)
    panel["expectation_revision_count_20"] = daily_revision["revision_count"].rolling(20).sum()
    panel["expectation_revision_magnitude_20"] = daily_revision["revision_magnitude"].rolling(20).mean()
    for name in ("expectation_revision_breadth_20", "expectation_revision_count_20", "expectation_revision_magnitude_20"):
        metadata.append(_feature_meta(name, "H02-EARNINGS-EXPECTATION", "FUNDAMENTAL_EXPECTATION", "available_session close", "tushare.report_rc"))

    # H03: point-in-time constituent breadth, dispersion and ordinary money flow.
    constituents = inputs["constituent_panel"].copy()
    constituents["dt"] = pd.to_datetime(constituents["dt"])
    constituent_rows = []
    for date, frame in constituents.groupby("dt", sort=True):
        weight = pd.to_numeric(frame["weight"]).clip(lower=0)
        normalized = weight / weight.sum()
        returns = pd.to_numeric(frame["pct_chg"])
        amount = pd.to_numeric(frame["amount"]).clip(lower=0)
        flow = pd.to_numeric(frame["net_mf_amount"])
        constituent_rows.append(
            {
                "date": date,
                "breadth_weighted_sign": float((normalized * np.sign(returns)).sum()),
                "breadth_weighted_return": float((normalized * returns).sum() / 100.0),
                "breadth_dispersion": _weighted_std(returns / 100.0, normalized),
                "breadth_concentration_hhi": float((normalized**2).sum()),
                "breadth_moneyflow_positive": float(normalized.loc[flow.gt(0)].sum()),
                "breadth_moneyflow_intensity": float(flow.sum() / amount.sum()) if amount.sum() > 0 else np.nan,
            }
        )
    breadth = pd.DataFrame(constituent_rows).set_index("date").reindex(sessions)
    for name in breadth.columns:
        panel[name] = breadth[name]
        family = "FUND_FLOW" if "moneyflow" in name else "MARKET_BREADTH"
        metadata.append(_feature_meta(name, "H03-BREADTH-DISPERSION", family, "T close+", "tushare constituents/moneyflow"))

    # H04: share and NAV values are shifted one A-share session; options are available after T close.
    share = inputs["etf_share_size"].copy()
    share["trade_date"] = pd.to_datetime(share["trade_date"])
    share = share.set_index("trade_date").sort_index().reindex(sessions)
    total_share = pd.to_numeric(share["total_share"])
    total_size = pd.to_numeric(share["total_size"])
    nav = pd.to_numeric(share["nav"])
    close = pd.to_numeric(share["close"])
    panel["micro_share_change_1d_lag1"] = total_share.pct_change(fill_method=None).shift(1)
    panel["micro_share_change_5d_lag1"] = total_share.pct_change(5, fill_method=None).shift(1)
    panel["micro_size_change_1d_lag1"] = total_size.pct_change(fill_method=None).shift(1)
    panel["micro_nav_premium_lag1"] = (close / nav - 1.0).shift(1)
    for name in ("micro_share_change_1d_lag1", "micro_share_change_5d_lag1", "micro_size_change_1d_lag1", "micro_nav_premium_lag1"):
        metadata.append(_feature_meta(name, "H04-ETF-DERIVATIVE-MICROSTRUCTURE", "ETF_PRIMARY_MARKET", "T uses T-1 publication", "tushare.etf_share_size"))

    options = inputs["option_daily"].copy()
    options["trade_date"] = pd.to_datetime(options["trade_date"])
    options = options.loc[options["standard_contract"].astype(bool) & options["valid_quote"].astype(bool)]
    option_group = options.groupby(["trade_date", "call_put"]).agg(vol=("vol", "sum"), oi=("oi", "sum")).unstack("call_put")
    option_features = pd.DataFrame(index=option_group.index)
    option_features["micro_option_put_call_volume"] = option_group[("vol", "P")] / option_group[("vol", "C")].replace(0, np.nan)
    option_features["micro_option_put_call_oi"] = option_group[("oi", "P")] / option_group[("oi", "C")].replace(0, np.nan)
    option_features = option_features.reindex(sessions)
    for name in option_features.columns:
        panel[name] = option_features[name]
        metadata.append(_feature_meta(name, "H04-ETF-DERIVATIVE-MICROSTRUCTURE", "DERIVATIVE_POSITIONING", "T 17:00", "tushare.opt_daily"))

    # H05: transparent OHLCV features plus causal tsfresh proposals.
    close = pd.to_numeric(daily["close"])
    high = pd.to_numeric(daily["high"])
    low = pd.to_numeric(daily["low"])
    volume = pd.to_numeric(daily["volume"])
    amount = pd.to_numeric(daily["amount"])
    panel["price_return_1d"] = close.pct_change(fill_method=None).to_numpy()
    panel["price_return_5d"] = close.pct_change(5, fill_method=None).to_numpy()
    panel["price_intraday_range"] = ((high - low) / close).to_numpy()
    panel["price_close_vwap_deviation"] = (close / (amount / volume).replace([np.inf, -np.inf], np.nan) - 1.0).to_numpy()
    panel["liquidity_volume_ratio_20"] = (volume / volume.rolling(20).mean()).to_numpy()
    panel["volatility_realized_20"] = close.pct_change(fill_method=None).rolling(20).std(ddof=0).to_numpy()
    for name, family in (
        ("price_return_1d", "TREND_MOMENTUM"),
        ("price_return_5d", "TREND_MOMENTUM"),
        ("price_intraday_range", "VOLATILITY_RISK"),
        ("price_close_vwap_deviation", "POSITION_VALUATION"),
        ("liquidity_volume_ratio_20", "VOLUME_LIQUIDITY"),
        ("volatility_realized_20", "VOLATILITY_RISK"),
    ):
        metadata.append(_feature_meta(name, "H05-PRICE-LIQUIDITY-STATE", family, "T close", "588080 OHLCV"))

    ts_input = pd.DataFrame(
        {
            "date": sessions[1:],
            "return_1d": close.pct_change(fill_method=None).iloc[1:].to_numpy(),
            "intraday_range": ((high - low) / close).iloc[1:].to_numpy(),
            "log_volume_change": np.log(volume).diff().iloc[1:].to_numpy(),
        }
    )
    for lookback in (20, 60):
        renamed = extract_rolling_features(ts_input, lookback)
        panel = panel.join(renamed, how="left")
        for name in renamed.columns:
            metadata.append(_feature_meta(name, "H05-PRICE-LIQUIDITY-STATE", "TSFRESH_PROPOSAL", "T close", "tsfresh"))

    if panel.columns.duplicated().any() or not panel.index.is_unique:
        raise ValueError("feature panel identities must be unique")
    numeric = panel.to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise ValueError("feature panel contains infinite values")
    meta = pd.DataFrame(metadata)
    if set(meta["feature"]) != set(panel.columns) or meta["feature"].duplicated().any():
        raise ValueError("feature metadata does not exactly cover panel columns")

    return panel.reset_index(), meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    output = (repo / args.output).resolve()
    if not output.is_relative_to((repo / ".tmp").resolve()):
        raise ValueError("engineering output must be under .tmp")
    output.mkdir(parents=True, exist_ok=True)
    panel, metadata = materialize(repo, DataSpace(Path("data/research/S007/materialization_store")))
    panel.to_csv(output / "causal_feature_panel.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    metadata.to_csv(output / "feature_catalog.csv", index=False)
    print(json.dumps({"status": "COMPLETE", "sessions": len(panel), "features": len(panel.columns) - 1}))


if __name__ == "__main__":
    main()
