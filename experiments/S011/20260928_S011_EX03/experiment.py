"""S011 EX03: broad factor and later executable-price association census."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
import pyarrow
from research_experiment import (
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)


EXPERIMENT_ID = "20260928_S011_EX03"
PREDECESSORS = {
    "20260928_S011_EX01": "b086702fda537d0129a437d9013e75dd2b5e942ea7aef1d9d5fb4be1013da4e8",
    "20260928_S011_EX02": "5c820f80a763596a80b8faa8340f986372fb252c2684a7c6aed600e0e124c931",
}
START = "2024-09-09"
CUTOFF = "2026-09-24"
SYMBOL = "159326.SZ"
HORIZONS = (1, 5, 10, 20)
SPLIT = 248
MIN_HALF = 100
EXPECTED_ETF_SHA256 = "a197ebc57a54591c0c4a226ec1f7c64cf67bc0ca698968f6cfd582d656608ca3"
EXPECTED_MARKET_SHA256 = "e1983f68713e3808c0b23ef1531e94f36c5332249f6b65336ffc05602d36dccd"
PANELS = (
    ("20260928_S011_EX01", "daily", 10, "tsfresh_daily_w10.parquet"),
    ("20260928_S011_EX01", "daily", 20, "tsfresh_daily_w20.parquet"),
    ("20260928_S011_EX01", "daily", 60, "tsfresh_daily_w60.parquet"),
    ("20260928_S011_EX01", "30m", 16, "tsfresh_30m_w16.parquet"),
    ("20260928_S011_EX01", "30m", 40, "tsfresh_30m_w40.parquet"),
    ("20260928_S011_EX01", "30m", 80, "tsfresh_30m_w80.parquet"),
    ("20260928_S011_EX02", "manual", 0, "manual_factor_panel.parquet"),
    ("20260928_S011_EX02", "peripheral", 10, "tsfresh_peripheral_w10.parquet"),
    ("20260928_S011_EX02", "peripheral", 20, "tsfresh_peripheral_w20.parquet"),
    ("20260928_S011_EX02", "peripheral", 60, "tsfresh_peripheral_w60.parquet"),
)
BASELINE_FEATURES = (
    "p_momentum_w5", "p_momentum_w20", "p_momentum_w60", "x_market_momentum_w20",
)


def _forward_return(opened: np.ndarray, closed: np.ndarray, horizon: int) -> np.ndarray:
    length = len(opened)
    target = np.full(length, np.nan)
    if len(closed) != length or horizon <= 0 or horizon >= length:
        raise ValueError("invalid forward-return input")
    with np.errstate(divide="ignore", invalid="ignore"):
        target[: length - horizon] = np.log(closed[horizon:] / opened[1 : length - horizon + 1])
    target[~np.isfinite(target)] = np.nan
    return target


def _ranked_correlations(ranked_x: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ranked_y = pd.Series(target).rank(method="average", pct=True).to_numpy(dtype=float)
    valid = np.isfinite(ranked_x) & np.isfinite(ranked_y)[:, None]
    count = valid.sum(axis=0)
    x = np.where(valid, ranked_x, 0.0)
    y = np.where(valid, ranked_y[:, None], 0.0)
    count_safe = np.maximum(count, 1)
    sum_x = x.sum(axis=0)
    sum_y = y.sum(axis=0)
    cross = (x * y).sum(axis=0) - sum_x * sum_y / count_safe
    var_x = (x * x).sum(axis=0) - sum_x * sum_x / count_safe
    var_y = (y * y).sum(axis=0) - sum_y * sum_y / count_safe
    denominator = np.sqrt(np.maximum(var_x * var_y, 0.0))
    correlation = np.divide(
        cross, denominator, out=np.full(len(count), np.nan), where=(count >= 3) & (denominator > 0)
    )
    return correlation, count


def _load_panel(
    archive: Path, panel: str, window: int, filename: str, calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, int, int]:
    quality = pd.read_csv(archive / "artifacts" / "factor_quality.csv.gz")
    subset = quality.loc[quality["Panel"].eq(panel) & quality["Window"].eq(window)]
    selected = subset.loc[subset["Coverage"].ge(0.95) & subset["UniqueFinite"].gt(1)]
    selected = selected.drop_duplicates("ExactColumnSha256")
    frame = pd.read_parquet(archive / "artifacts" / filename)
    if panel == "manual":
        if not pd.DatetimeIndex(frame.index).equals(calendar):
            raise ValueError("manual panel calendar differs from governed ETF data")
        frame.index = pd.Index(range(len(calendar)))
    else:
        if not frame.index.is_unique or not pd.Index(frame.index).isin(range(len(calendar))).all():
            raise ValueError("tsfresh panel has invalid decision-day indexes")
        frame = frame.reindex(range(len(calendar)))
    names = selected["Feature"].tolist()
    if not set(names).issubset(frame.columns):
        raise ValueError("quality ledger and factor panel columns differ")
    return frame[names].replace([np.inf, -np.inf], np.nan), len(subset), len(names)


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Which precomputed causal factors associate with later ETF returns beyond broad-market movement?",
            hypothesis="Some price-volume or peripheral states may have persistent forward associations worth mechanism review.",
            falsification_conditions=(
                "Either predecessor receipt or archive identity differs",
                "Governed ETF or market prices differ from the frozen data identities",
                "Any panel/target alignment or archive validation fails",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=20260903,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.DOMESTIC_INDEX_DAILY.value),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("A useful state must precede the return and add more than a common market move",),
                information_paths=("T-close observable factor -> next-open through future-close ETF return",),
                stage_objectives=("Census broad factor-return relations without selecting a strategy",),
                observation_metrics=("Full-period rank association, market-difference association and chronological halves",),
                methodology=("Quality-filter before reading returns, test every remaining factor at four horizons",),
                predecessor_experiment_ids=tuple(PREDECESSORS),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("pyarrow", pyarrow.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self) -> None:
        opened = np.array([10.0, 20.0, 30.0, 40.0])
        closed = np.array([11.0, 22.0, 33.0, 44.0])
        if not np.isclose(_forward_return(opened, closed, 1)[0], np.log(22 / 20)):
            raise ValueError("one-session outcome does not begin at next open")
        if not np.isclose(_forward_return(opened, closed, 2)[0], np.log(33 / 20)):
            raise ValueError("multi-session outcome has an off-by-one boundary")
        test = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]}).rank(pct=True).to_numpy()
        correlation, count = _ranked_correlations(test, np.array([4.0, 3.0, 2.0, 1.0]))
        if count[0] != 4 or not np.isclose(correlation[0], -1.0):
            raise ValueError("synthetic rank-association calculation differs")

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        for predecessor_id, receipt in PREDECESSORS.items():
            if context.predecessors[predecessor_id].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {predecessor_id}")
            validate_experiment_archive(root.parent / predecessor_id)
        input_rows: list[dict[str, object]] = []
        frames: dict[str, pd.DataFrame] = {}
        for label, dataset, symbol, expected_hash in (
            ("etf", Dataset.ETF_OHLCV, SYMBOL, EXPECTED_ETF_SHA256),
            ("market", Dataset.DOMESTIC_INDEX_DAILY, "000300.SH", EXPECTED_MARKET_SHA256),
        ):
            result = context.data.fetch(DataRequest(
                dataset=dataset, symbol=symbol, start=START, end=CUTOFF,
                required_cutoff=CUTOFF, frequency="daily", options={"env_file": ".env"},
            ))
            if result.status is not DataStatus.READY or result.identity is None:
                raise RuntimeError(f"governed {label} prices not READY: {result.error}")
            identity = result.identity
            if identity.content_sha256 != expected_hash:
                raise ValueError(f"frozen {label} price content changed")
            frames[label] = result.dataframe.sort_values("Date").reset_index(drop=True)
            input_rows.append({
                "Input": label, "Dataset": identity.dataset, "Source": identity.source,
                "Symbol": identity.symbol, "Rows": len(result.dataframe),
                "Sha256": identity.content_sha256,
                "AvailableAt": identity.temporal_contract.available_at,
            })
        calendar = pd.DatetimeIndex(pd.to_datetime(frames["etf"]["Date"]).dt.normalize())
        market_calendar = pd.DatetimeIndex(pd.to_datetime(frames["market"]["Date"]).dt.normalize())
        if len(calendar) != 496 or not calendar.equals(market_calendar) or calendar.has_duplicates:
            raise ValueError("ETF and market calendars differ from the fixed complete window")

        targets: dict[int, dict[str, np.ndarray]] = {}
        target_table = pd.DataFrame({"Date": calendar})
        for horizon in HORIZONS:
            etf = _forward_return(
                frames["etf"]["Open"].to_numpy(dtype=float),
                frames["etf"]["Close"].to_numpy(dtype=float), horizon,
            )
            market = _forward_return(
                frames["market"]["Open"].to_numpy(dtype=float),
                frames["market"]["Close"].to_numpy(dtype=float), horizon,
            )
            targets[horizon] = {"etf": etf, "market_difference": etf - market}
            target_table[f"ETF_h{horizon}"] = etf
            target_table[f"ETF_minus_market_h{horizon}"] = etf - market

        ledger_rows: list[dict[str, object]] = []
        panel_rows: list[dict[str, object]] = []
        baseline_rows: list[dict[str, object]] = []
        for predecessor_id, panel, window, filename in PANELS:
            archive = root.parent / predecessor_id
            factor_frame, total_count, eligible_count = _load_panel(archive, panel, window, filename, calendar)
            panel_rows.append({
                "experiment": predecessor_id, "panel": panel, "window": window,
                "all_columns": total_count, "quality_filtered_columns": eligible_count,
            })
            if factor_frame.empty:
                continue
            portions = {
                "all": factor_frame,
                "first": factor_frame.iloc[:SPLIT],
                "second": factor_frame.iloc[SPLIT:],
            }
            ranked = {name: portion.rank(axis=0, method="average", pct=True).to_numpy(dtype=float)
                      for name, portion in portions.items()}
            for horizon in HORIZONS:
                raw = targets[horizon]["etf"]
                difference = targets[horizon]["market_difference"]
                all_ic, n_all = _ranked_correlations(ranked["all"], raw)
                market_ic, _ = _ranked_correlations(ranked["all"], difference)
                first_ic, n_first = _ranked_correlations(ranked["first"], raw[:SPLIT])
                second_ic, n_second = _ranked_correlations(ranked["second"], raw[SPLIT:])
                for number, feature in enumerate(factor_frame.columns):
                    row = {
                        "Experiment": predecessor_id, "Panel": panel, "Window": window,
                        "Feature": feature, "Horizon": horizon,
                        "N": int(n_all[number]), "FirstN": int(n_first[number]),
                        "SecondN": int(n_second[number]),
                        "RankIC": float(all_ic[number]), "MarketDifferenceRankIC": float(market_ic[number]),
                        "FirstRankIC": float(first_ic[number]), "SecondRankIC": float(second_ic[number]),
                    }
                    ledger_rows.append(row)
                    if panel == "manual" and feature in BASELINE_FEATURES:
                        baseline_rows.append(row)
        ledger = pd.DataFrame(ledger_rows)
        if ledger.empty:
            raise ValueError("quality filter yielded no factor-return observations")
        valid = ledger["N"].ge(250) & ledger["FirstN"].ge(MIN_HALF) & ledger["SecondN"].ge(MIN_HALF)
        consistent = valid & ledger["FirstRankIC"].notna() & ledger["SecondRankIC"].notna() & (
            np.sign(ledger["FirstRankIC"]) == np.sign(ledger["SecondRankIC"])
        )
        ledger.to_csv(
            context.workspace.path("full_association_ledger.csv.gz"), index=False,
            compression={"method": "gzip", "compresslevel": 9, "mtime": 0}, lineterminator="\n",
        )
        pd.DataFrame(baseline_rows).to_csv(
            context.workspace.path("price_baselines.csv"), index=False, lineterminator="\n",
        )
        pd.DataFrame(panel_rows).to_csv(
            context.workspace.path("panel_scope.csv"), index=False, lineterminator="\n",
        )
        target_table.to_parquet(context.workspace.path("forward_targets.parquet"), compression="zstd", index=False)
        pd.DataFrame(input_rows).to_csv(
            context.workspace.path("input_identities.csv"), index=False, lineterminator="\n",
        )
        summary = {
            "decision": "FORWARD_RELATION_CENSUS_COMPLETE",
            "panels": panel_rows,
            "quality_filtered_factor_columns": int(sum(row["quality_filtered_columns"] for row in panel_rows)),
            "factor_horizon_tests": len(ledger),
            "valid_test_rows": int(valid.sum()),
            "split_half_same_sign_rows": int(consistent.sum()),
            "target_horizons": list(HORIZONS),
            "trading_strategy_tested": False,
            "market_difference_is_broad_index_proxy": True,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        artifacts = tuple(context.workspace.register_artifact(name, role) for name, role in (
            ("full_association_ledger.csv.gz", "complete-factor-return-ledger"),
            ("price_baselines.csv", "simple-price-baselines"),
            ("panel_scope.csv", "screening-scope"),
            ("forward_targets.parquet", "forward-price-outcomes"),
            ("input_identities.csv", "governed-input-identities"),
            ("summary.json", "census-summary"),
        ))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": summary["decision"],
                "quality_filtered_factor_columns": summary["quality_filtered_factor_columns"],
                "factor_horizon_tests": summary["factor_horizon_tests"],
                "valid_test_rows": summary["valid_test_rows"],
                "split_half_same_sign_rows": summary["split_half_same_sign_rows"],
            },
            diagnostics={"trading_strategy_tested": False, "hypothesis_selected": False},
            artifacts=artifacts,
        )
