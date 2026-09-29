"""S010 EX15: frozen basket breadth, leadership and dispersion survey."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S010_EX15"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
    "20260929_S010_EX07": "f39fc5db88c7ed9c7996a96fd4d7fee4ec1c73e275c6e553aee343f0e30cb8ba",
    "20260929_S010_EX08": "d48bba43ce2e25e1fd6c3f4a7613f57776331ff79190546986e9ffe4658bf6c9",
    "20260929_S010_EX09": "6c9dc8791d54a205f0356ce587ccb349ceb983757409edd0218b0561fac682d9",
    "20260929_S010_EX10": "f31c3df4cec34265cbe59902cbbb5987c1e2ec99e460f6f7aa7d5261886a86ca",
    "20260929_S010_EX11": "577edf88220d5cba3f16c857267ed608fe27d312e3da5f95bc57727a0131cf51",
    "20260929_S010_EX12": "6b0ab17d03232dc2d79afea75a306b11b2efef0d5aaf3775b00f4dd7c83a87c9",
    "20260929_S010_EX13": "ae3ff0deff311b496e5b22bd84b1b54a2aea83567e3f086f3a265709c8500619",
    "20260929_S010_EX14": "1bb95559a3c1653326320af64c81f7a0d8b8d8b453a9d687ab5e66fca00907e2",
}
ETF_SHA256 = "727085dab698e770ef1afd82eefbc460d4b68a2bb72820ba3d3ef86b4dab7212"
START, CUTOFF = "2024-09-09", "2026-09-28"
SEED = 2026092915
SNAPSHOT_DELAY_DAYS = 35
MAX_STALE_SESSIONS = 10
MIN_WEIGHT_COVERAGE = 0.95
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
B0 = ("etf_return_1", "etf_return_5", "etf_volatility_20",
      "tsfresh_range__median", "intra_afternoon_return", "tsfresh_return__maximum")
B_THEME = (*B0, "theme_return_1", "theme_return_5")
FACTORS = tuple(f"basket_{name}_{h}" for h in (1, 5)
                for name in ("breadth_equal", "breadth_weighted", "leader_spread", "dispersion"))
OUTCOMES = ("open_return_1", "open_return_5", "open_return_10", "adverse_5")
COMPARISONS = tuple((factor, outcome, baseline_name, baseline)
                    for factor in FACTORS for outcome in OUTCOMES
                    for baseline_name, baseline in (("B0", B0), ("B_THEME", B_THEME)))


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray):
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights, weights


def _folds(index: pd.DatetimeIndex, horizon: int):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 1 + horizon < test[0])
        yield start, train, test


def _factor_panel(weights: pd.DataFrame, closes: pd.DataFrame,
                  sessions: pd.DatetimeIndex) -> pd.DataFrame:
    snapshots = {date: frame.sort_values("Weight", ascending=False)
                 for date, frame in weights.groupby("Date")}
    dates = pd.DatetimeIndex(sorted(snapshots))
    wide = closes.pivot(index="Date", columns="Symbol", values="Close").sort_index()
    daily = wide.reindex(wide.index.union(sessions)).sort_index().ffill(limit=MAX_STALE_SESSIONS)
    daily = daily.reindex(sessions)
    returns = {h: daily.pct_change(h, fill_method=None) for h in (1, 5)}
    records = []
    for session in sessions:
        record = {"Date": session, **{name: np.nan for name in FACTORS}}
        eligible = dates[dates + pd.Timedelta(days=SNAPSHOT_DELAY_DAYS) <= session]
        if eligible.empty:
            records.append(record)
            continue
        basket = snapshots[eligible.max()]
        symbols = basket["ConstituentSymbol"].tolist()
        weights_pct = basket["Weight"].to_numpy(dtype=float)
        for horizon in (1, 5):
            values = returns[horizon].loc[session].reindex(symbols).to_numpy(dtype=float)
            valid = np.isfinite(values)
            if weights_pct[valid].sum() < MIN_WEIGHT_COVERAGE * weights_pct.sum():
                continue
            values = values[valid]
            w = weights_pct[valid]
            w = w / w.sum()
            top = np.flatnonzero(valid) < 10
            record[f"basket_breadth_equal_{horizon}"] = float(np.mean(values > 0))
            record[f"basket_breadth_weighted_{horizon}"] = float(w[values > 0].sum())
            if top.any() and (~top).any():
                record[f"basket_leader_spread_{horizon}"] = float(
                    np.average(values[top], weights=w[top])
                    - np.average(values[~top], weights=w[~top])
                )
            mean = np.average(values, weights=w)
            record[f"basket_dispersion_{horizon}"] = float(
                np.sqrt(np.average(np.square(values - mean), weights=w))
            )
        records.append(record)
    return pd.DataFrame(records).set_index("Date")


def _adverse(daily: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    if not daily.index.equals(sessions):
        raise ValueError("ETF daily dates differ from predecessor calendar")
    opens = daily["Open"].to_numpy(dtype=float)
    lows = daily["Low"].to_numpy(dtype=float)
    if not np.isfinite(opens).all() or not np.isfinite(lows).all():
        raise ValueError("ETF execution prices contain nonfinite value")
    if (opens <= 0).any() or (lows <= 0).any() or (lows > opens).any():
        raise ValueError("ETF execution low or open is invalid")
    out = np.full(len(sessions), np.nan)
    for position in range(len(sessions) - 5):
        out[position] = lows[position + 1:position + 6].min() / opens[position + 1] - 1
    return pd.Series(out, index=sessions, name="adverse_5")


def _evaluate(joined: pd.DataFrame):
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor, outcome, baseline_name, baseline in COMPARISONS:
        horizon = 5 if outcome == "adverse_5" else int(outcome.rsplit("_", 1)[-1])
        base_errors, extra_errors, positive = [], [], 0
        for start, train_positions, test_positions in _folds(dates, horizon):
            columns = [*baseline, factor, outcome]
            train = joined.iloc[train_positions][columns].dropna()
            test = joined.iloc[test_positions][columns].dropna()
            if len(train) < 80 or len(test) < 15:
                details.append({"factor": factor, "outcome": outcome,
                                "baseline": baseline_name, "test_start": start,
                                "status": "INSUFFICIENT", "train_rows": len(train),
                                "test_rows": len(test)})
                continue
            last = dates.get_loc(train.index[-1]) + 1 + horizon
            if last >= len(dates) or dates[last] >= test.index[0]:
                raise ValueError("training label crosses chronological test boundary")
            y_train = train[outcome].to_numpy(dtype=float)
            y_test = test[outcome].to_numpy(dtype=float)
            base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                             test[list(baseline)].to_numpy(dtype=float))
            extra, weights = _ridge(train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                                    test[[*baseline, factor]].to_numpy(dtype=float))
            b, e = np.square(y_test - base), np.square(y_test - extra)
            base_errors.extend(b)
            extra_errors.extend(e)
            positive += int(e.mean() < b.mean())
            details.append({"factor": factor, "outcome": outcome,
                            "baseline": baseline_name, "test_start": start,
                            "status": "EVALUATED", "train_rows": len(train),
                            "test_rows": len(test),
                            "train_label_end": dates[last].date().isoformat(),
                            "base_mse": float(b.mean()), "extra_mse": float(e.mean()),
                            "extra_standardized_coefficient": float(weights[-1])})
        totals.append({"factor": factor, "outcome": outcome,
                       "baseline": baseline_name, "oos_rows": len(base_errors),
                       "positive_folds": positive,
                       "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                       if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _states(joined: pd.DataFrame):
    dates = pd.DatetimeIndex(joined.index)
    frames, summaries = [], []
    for factor, outcome, horizon in (("basket_breadth_equal_5", "open_return_5", 5),
                                     ("basket_dispersion_5", "adverse_5", 5)):
        rows = []
        for start, train_positions, test_positions in _folds(dates, horizon):
            history = joined.iloc[train_positions][factor].dropna()
            if len(history) < 80:
                continue
            q25, q75 = history.quantile([0.25, 0.75])
            for position in test_positions:
                value = joined.iloc[position][factor]
                future = joined.iloc[position][outcome]
                if not np.isfinite(value) or not np.isfinite(future):
                    continue
                state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
                rows.append({"Date": dates[position], "Factor": factor,
                             "Outcome": outcome, "TestStart": start, "State": state,
                             "Value": value, "TrainingQ25": q25, "TrainingQ75": q75,
                             "Future": future})
        frame = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"no basket state observations: {factor}")
        rng = np.random.default_rng(SEED + (0 if factor.endswith("equal_5") else 1))
        length, width = len(frame), 10
        starts = np.arange(length - width + 1)
        differences = []
        for _ in range(2000):
            draw = rng.choice(starts, size=int(np.ceil(length / width)), replace=True)
            positions = (draw[:, None] + np.arange(width)).reshape(-1)[:length]
            sample = frame.iloc[positions]
            high = sample.loc[sample["State"].eq("HIGH"), "Future"]
            low = sample.loc[sample["State"].eq("LOW"), "Future"]
            if not high.empty and not low.empty:
                differences.append(float(high.mean() - low.mean()))
        high = frame.loc[frame["State"].eq("HIGH"), "Future"]
        low = frame.loc[frame["State"].eq("LOW"), "Future"]
        interval = list(np.quantile(differences, [0.025, 0.975])) if differences else [np.nan, np.nan]
        summaries.append({"Factor": factor, "Outcome": outcome,
                          "HighDays": len(high), "LowDays": len(low),
                          "HighMean": float(high.mean()) if len(high) else np.nan,
                          "LowMean": float(low.mean()) if len(low) else np.nan,
                          "HighMinusLowCi95Low": float(interval[0]),
                          "HighMinusLowCi95High": float(interval[1])})
        frames.append(frame)
    return pd.concat(frames, ignore_index=True), pd.DataFrame(summaries)


def _precheck() -> None:
    weights = pd.DataFrame({"Date": pd.to_datetime(["2024-09-30", "2024-09-30"]),
                            "ConstituentSymbol": ["A", "B"], "Weight": [60.0, 40.0]})
    dates = pd.bdate_range("2024-10-28", periods=10)
    closes = pd.DataFrame([{"Date": day, "Symbol": symbol,
                            "Close": 100.0 + position * (1 if symbol == "A" else -1)}
                           for position, day in enumerate(dates) for symbol in ("A", "B")])
    panel = _factor_panel(weights, closes, dates)
    if not panel.iloc[0].isna().all():
        raise ValueError("future snapshot entered synthetic factor panel")
    available = panel.loc[pd.Timestamp("2024-11-04")]
    if not np.isclose(available["basket_breadth_equal_1"], 0.5):
        raise ValueError("synthetic constituent breadth differs")
    first = next(_folds(pd.bdate_range("2024-01-01", periods=800), 5))
    if first[1][-1] + 6 >= first[2][0]:
        raise ValueError("synthetic purge boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does lagged basket breadth, leadership or dispersion add confirmation or downside information?",
            hypothesis="Participation and concentrated leadership can reveal internal theme diffusion beyond aggregate ETF and index prices.",
            falsification_conditions=("No stable increment beyond aggregate prices and existing components",
                                    "High-low state interpretation fails",
                                    "Source identity or historical time contract differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Internal stock participation can precede ETF-level price discovery",),
                information_paths=("Lagged index basket and T stock closes -> subsequent ETF prices",),
                stage_objectives=("Survey eight fixed basket factors against two aggregate-price baselines",
                                  "Audit breadth and dispersion state roles"),
                observation_metrics=("Purged MSE", "training coefficient direction",
                                     "state counts and moving-block intervals"),
                methodology=("Sixty-four fixed comparisons", "Training-only quartiles",
                             "Ten-session moving-block intervals"),
                predecessor_experiment_ids=tuple(RECEIPTS),
            ),
            subjects=("159326.SZ",),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
        )

    def synthetic_precheck(self) -> None:
        _precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        for name, receipt in RECEIPTS.items():
            if context.predecessors[name].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {name}")
            validate_experiment_archive(root.parent / name)
        first = root.parent / "20260929_S010_EX01" / "artifacts"
        third = root.parent / "20260929_S010_EX03" / "artifacts"
        fourth = root.parent / "20260929_S010_EX04" / "artifacts"
        fourteenth = root.parent / "20260929_S010_EX14" / "artifacts"
        gate = json.loads((fourteenth / "summary.json").read_text(encoding="utf-8"))
        if gate["decision"] != "BREADTH_SOURCE_AUDIT_COMPLETE" or gate["stock_failed_count"] != 0:
            raise ValueError("predecessor basket data gate is incomplete")
        factors = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        theme = pd.read_csv(fourth / "theme_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        weights = pd.read_csv(fourteenth / "weight_snapshots.csv.gz", parse_dates=["Date"])
        closes = pd.read_csv(fourteenth / "stock_closes.csv.gz", parse_dates=["Date"])
        sessions = pd.DatetimeIndex(factors.index)
        if not sessions.equals(pd.DatetimeIndex(labels.index)) or not sessions.equals(pd.DatetimeIndex(intraday.index)):
            raise ValueError("predecessor calendars differ")
        if not sessions.equals(pd.DatetimeIndex(theme.index)) or sessions.duplicated().any():
            raise ValueError("theme calendar differs or contains duplicates")
        basket = _factor_panel(weights, closes, sessions)
        result = context.data.fetch(DataRequest(
            Dataset.ETF_OHLCV, "159326.SZ", START, CUTOFF, CUTOFF, "daily",
            {"env_file": str(root.parents[2] / ".env")},
        ))
        if not result.ready or result.identity is None:
            error = result.error
            raise ValueError("ETF daily DFLS unavailable: " + result.status.value
                             + ("" if error is None else f" {error.code}: {error.message}"))
        if result.identity.content_sha256 != ETF_SHA256:
            raise ValueError("ETF daily source identity differs from prior experiments")
        daily = result.dataframe.copy()
        daily["Date"] = pd.to_datetime(daily["Date"], errors="raise")
        daily = daily.set_index("Date").sort_index()
        adverse = _adverse(daily, sessions)
        joined = factors[list(dict.fromkeys(name for name in B_THEME if name in factors.columns))]
        joined = joined.join(intraday[["intra_afternoon_return"]])
        joined = joined.join(theme[["theme_return_1", "theme_return_5"]])
        joined = joined.join(basket).join(labels[list(OUTCOMES[:3])]).join(adverse)
        joined = joined.replace([np.inf, -np.inf], np.nan)
        scores, folds = _evaluate(joined)
        states, state_summary = _states(joined)
        state_counts = states.groupby(["Factor", "TestStart", "State"]).size().unstack(fill_value=0).reset_index()
        quality = pd.DataFrame([{"Factor": name, "FiniteRows": int(basket[name].notna().sum()),
                                 "FirstDate": basket[name].first_valid_index()}
                                for name in FACTORS])
        relations = joined[[*FACTORS, "etf_return_1", "etf_return_5", "tsfresh_range__median",
                            "theme_return_1", "theme_return_5"]].corr().loc[list(FACTORS)]
        relations.index.name = "Factor"
        artifacts = []
        for name, frame in (("basket_factors.csv.gz", basket.reset_index()),
                            ("factor_quality.csv", quality),
                            ("factor_scores.csv", scores),
                            ("fold_scores.csv", folds),
                            ("state_days.csv", states),
                            ("state_counts.csv", state_counts),
                            ("state_summary.csv", state_summary),
                            ("factor_relations.csv", relations.reset_index())):
            frame.to_csv(context.workspace.path(name), index=False,
                         compression="gzip" if name.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX15-{name.split('.')[0]}"))
        summary = {"decision": "BASKET_BREADTH_SURVEY_COMPLETE",
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "basket_source_receipt_sha256": RECEIPTS["20260929_S010_EX14"],
                   "etf_sha256": result.identity.content_sha256,
                   "snapshot_delay_calendar_days": SNAPSHOT_DELAY_DAYS,
                   "source_publication_timestamp_verified": False,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX15-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "factor_count": len(FACTORS),
                   "comparison_count": len(scores), "sealed_date_rows_read": 0},
            diagnostics={"basket_factor_rows": int(basket.notna().all(axis=1).sum())},
            artifacts=tuple(artifacts),
        )
