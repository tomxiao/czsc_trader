from __future__ import annotations

from datetime import date
from hashlib import sha256
from math import ceil
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import Dataset
import numpy as np
import pandas as pd
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260925_S008_EX90"
PREDECESSOR = "20260925_S008_EX89"
PREDECESSOR_RECEIPT = "6c4f9b604f9095039c88f5706f7b070f07203c9b11300c5cc845deadf71197c6"
BASIS_SHA256 = "a5b37907825e114b39877867bf130ccb4298fc2a3d8f01346b3694a01f6504b5"
PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
PRICE = ("price_return_5d", "price_return_20d", "price_return_60d", "price_return_120d", "price_volatility_20")
SPOT = ("gold_sge_return_5d", "gold_sge_return_20d", "gold_sge_trend_distance_60")
EXISTING = PRICE + SPOT + ("CurveSlope", "DaysToMaturity")
EXTENDED = EXISTING + ("SpotFuturesBasis",)
STATES = ("START", "PERSIST", "PULLBACK", "WEAK")
HORIZONS = (20, 60)
YEARS = tuple(range(2019, 2025))
REPETITIONS = 2000
SEED = 20260990


def _states(frame: pd.DataFrame) -> pd.Series:
    short = frame["price_return_20d"].gt(0)
    medium = frame["price_return_60d"].gt(0)
    return pd.Series(np.select(
        (~medium & short, medium & short, medium & ~short, ~medium & ~short),
        STATES, default="",
    ), index=frame.index, name="State")


def _future_open_return(opens: pd.Series, horizon: int) -> pd.Series:
    return opens.shift(-(horizon + 1)).div(opens.shift(-1)).sub(1)


def _predict(train: pd.DataFrame, test: pd.DataFrame, fields: tuple[str, ...]) -> tuple[np.ndarray | None, int]:
    x = train.loc[:, fields].to_numpy(dtype=float)
    z = test.loc[:, fields].to_numpy(dtype=float)
    if len(x) <= len(fields) + 1:
        return None, 0
    center, scale = x.mean(axis=0), x.std(axis=0)
    if not np.isfinite(scale).all() or np.any(scale == 0):
        return None, 0
    design = np.column_stack((np.ones(len(x)), (x - center) / scale))
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        return None, rank
    coefficients = np.linalg.lstsq(design, train["Outcome"].to_numpy(dtype=float), rcond=None)[0]
    future = np.column_stack((np.ones(len(z)), (z - center) / scale))
    return future @ coefficients, rank


def _bh(values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().sort_values()
    if valid.empty:
        return result
    ranks = np.arange(1, len(valid) + 1)
    adjusted = np.minimum.accumulate((valid.to_numpy() * len(valid) / ranks)[::-1])[::-1]
    result.loc[valid.index] = np.minimum(adjusted, 1.0)
    return result


def _bootstrap(calendar: pd.DatetimeIndex, pair: pd.DataFrame, horizon: int, seed: int,
               repetitions: int) -> tuple[float | None, float | None, float | None, int]:
    series = pair.set_index("Date")["LossImprovement"].reindex(calendar)
    observed = series.dropna()
    present = series.notna().to_numpy()
    runs = int(np.sum(present & ~np.r_[False, present[:-1]]))
    if len(observed) < 2 or runs < 2 or len(calendar) < horizon:
        return None, None, None, runs
    values = series.to_numpy(dtype=float)
    blocks = ceil(len(values) / horizon)
    starts = np.random.default_rng(seed).integers(
        0, len(values) - horizon + 1, size=(repetitions, blocks)
    )
    sampled_indices = (starts[:, :, None] + np.arange(horizon)).reshape(repetitions, -1)[:, :len(values)]
    samples = values[sampled_indices]
    counts = np.isfinite(samples).sum(axis=1)
    means = np.divide(np.nansum(samples, axis=1), counts,
                      out=np.full(repetitions, np.nan), where=counts > 0)
    if not np.isfinite(means).all():
        return None, None, None, runs
    mean = float(observed.mean())
    lower, upper = np.quantile(means, (0.025, 0.975))
    p = (1 + int(np.sum(means - mean >= mean))) / (repetitions + 1)
    return float(lower), float(upper), float(p), runs


def _rank_metrics(outcome: np.ndarray, prediction: np.ndarray) -> dict[str, float | None]:
    if len(outcome) < 5 or np.unique(prediction).size < 5:
        return {"RankIC": None, "QuintileSpread": None, "UpsideCapture": None, "DownsideAvoidance": None}
    rank_ic = pd.Series(outcome).corr(pd.Series(prediction), method="spearman")
    order = np.argsort(prediction, kind="stable")
    size = max(1, len(order) // 5)
    upside = np.maximum(outcome, 0)
    downside = np.maximum(-outcome, 0)
    return {
        "RankIC": float(rank_ic) if pd.notna(rank_ic) else None,
        "QuintileSpread": float(outcome[order[-size:]].mean() - outcome[order[:size]].mean()),
        "UpsideCapture": float(upside[prediction > 0].sum() / upside.sum()) if upside.sum() > 0 else None,
        "DownsideAvoidance": float(downside[prediction <= 0].sum() / downside.sum()) if downside.sum() > 0 else None,
    }


def audit(frame: pd.DataFrame, repetitions: int = REPETITIONS) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("ETF decision dates must be unique and ordered")
    if frame.index.max() > pd.Timestamp("2024-12-31") or not frame["Open"].gt(0).all():
        raise ValueError("execution opens or development cutoff differ")
    if not set(EXTENDED).issubset(frame.columns):
        raise ValueError("frozen comparison feature is absent")
    source = frame.copy()
    source["State"] = _states(source)
    dates = pd.Series(source.index, index=source.index)
    predictions: list[dict[str, object]] = []
    fits: list[dict[str, object]] = []
    for horizon in HORIZONS:
        eligible = source.copy()
        eligible["Outcome"] = _future_open_return(source["Open"], horizon)
        eligible["OutcomeEnd"] = dates.shift(-(horizon + 1))
        eligible = eligible.dropna(subset=list(EXTENDED) + ["Outcome", "OutcomeEnd"])
        for year in YEARS:
            first = pd.Timestamp(year=year, month=1, day=1)
            training = eligible.loc[eligible["OutcomeEnd"].lt(first)]
            evaluation = eligible.loc[eligible.index.year == year]
            for state in STATES:
                train = training.loc[training["State"].eq(state)]
                test = evaluation.loc[evaluation["State"].eq(state)]
                if test.empty:
                    continue
                base, base_rank = _predict(train, test, EXISTING)
                extended, extended_rank = _predict(train, test, EXTENDED)
                fits.append({"Horizon": horizon, "Year": year, "State": state,
                             "TrainingN": len(train), "EvaluationN": len(test),
                             "BaselineRank": base_rank, "ExtendedRank": extended_rank,
                             "Identifiable": base is not None and extended is not None})
                for offset, (dt, item) in enumerate(test.iterrows()):
                    predictions.append({
                        "Date": dt, "Year": year, "State": state, "Horizon": horizon,
                        "Outcome": float(item["Outcome"]),
                        "Baseline": float(base[offset]) if base is not None else np.nan,
                        "Extended": float(extended[offset]) if extended is not None else np.nan,
                    })
    prediction_frame = pd.DataFrame(predictions).sort_values(["Horizon", "Date"]).reset_index(drop=True)
    fit_frame = pd.DataFrame(fits)
    rows: list[dict[str, object]] = []
    for horizon in HORIZONS:
        calendar = pd.DatetimeIndex(
            prediction_frame.loc[prediction_frame["Horizon"].eq(horizon), "Date"].sort_values().unique()
        )
        for state in STATES:
            pair = prediction_frame.loc[
                prediction_frame["Horizon"].eq(horizon) & prediction_frame["State"].eq(state)
            ].dropna(subset=["Baseline", "Extended"]).copy()
            if pair.empty:
                rows.append({"Horizon": horizon, "State": state, "EvaluationN": 0,
                             "Status": "UNIDENTIFIABLE"})
                continue
            outcome, base, extended = (pair[name].to_numpy(dtype=float)
                                       for name in ("Outcome", "Baseline", "Extended"))
            pair["LossImprovement"] = (outcome - base) ** 2 - (outcome - extended) ** 2
            lower, upper, p, runs = _bootstrap(
                calendar, pair[["Date", "LossImprovement"]], horizon,
                SEED + horizon * 100 + STATES.index(state), repetitions,
            )
            annual = pair.groupby("Year")["LossImprovement"].mean()
            base_metrics = _rank_metrics(outcome, base)
            extended_metrics = _rank_metrics(outcome, extended)
            rows.append({
                "Horizon": horizon, "State": state, "EvaluationN": len(pair), "StateRuns": runs,
                "BaselineMSE": float(np.mean((outcome - base) ** 2)),
                "ExtendedMSE": float(np.mean((outcome - extended) ** 2)),
                "DeltaMSE": float(pair["LossImprovement"].mean()),
                "CI95Lower": lower, "CI95Upper": upper, "PValue": p,
                "PositiveYears": int(annual.gt(0).sum()), "EvaluableYears": len(annual),
                **{"Baseline" + key: value for key, value in base_metrics.items()},
                **{"Extended" + key: value for key, value in extended_metrics.items()},
                "Status": "ESTIMATED" if p is not None else "INSUFFICIENT_BLOCKS",
            })
    ledger = pd.DataFrame(rows)
    if len(ledger) != 8:
        raise ValueError("frozen comparison count differs")
    ledger["QValue"] = _bh(pd.to_numeric(ledger["PValue"], errors="coerce"))
    ledger["ExploratoryClue"] = (
        ledger["DeltaMSE"].gt(0) & ledger["QValue"].le(0.10) & ledger["PositiveYears"].ge(4)
    )
    return prediction_frame, fit_frame, ledger


def synthetic_precheck() -> None:
    opens = pd.Series([10.0, 11.0, 12.0, 15.0], index=pd.bdate_range("2014-01-01", periods=4))
    if not np.isclose(_future_open_return(opens, 2).iloc[0], 15 / 11 - 1):
        raise ValueError("T+1 open outcome alignment differs")
    test = pd.DataFrame({"price_return_20d": [-1, 1, -1, 1],
                         "price_return_60d": [-1, -1, 1, 1]})
    if tuple(_states(test)) != ("WEAK", "START", "PULLBACK", "PERSIST"):
        raise ValueError("fixed price-state classification differs")
    rng = np.random.default_rng(90)
    dates = pd.bdate_range("2013-07-29", "2024-12-31")
    fake = pd.DataFrame(rng.normal(size=(len(dates), len(EXTENDED))), index=dates,
                        columns=EXTENDED)
    fake["Open"] = 100 * np.exp(np.cumsum(rng.normal(scale=0.01, size=len(dates))))
    prediction, fits, ledger = audit(fake, repetitions=10)
    if len(ledger) != 8 or prediction.empty or fits.empty:
        raise ValueError("full synthetic comparison shape differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does spot-futures basis improve conditional upside prediction beyond price, spot trend, curve and maturity?",
            hypothesis="A causal domestic spot-futures premium contains incremental gold-demand information.",
            falsification_conditions=(
                "The source identity or calendar differs from the passed data gate",
                "No paired improvement remains after the eight-comparison correction",
                "Any gain is limited to fewer than four of six evaluation years",
            ),
            development_cutoff=date(2024, 12, 31), random_seed=SEED,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Domestic spot-futures basis can reflect physical demand or financing carry",
                    "ETF and spot trends plus futures curve may explain away any apparent premium",
                ),
                information_paths=("Prior-session domestic basis -> later ETF upside conditional on known state",),
                stage_objectives=("Identify or reject incremental information without a trading rule",),
                observation_metrics=("Paired annual-forward MSE, annual stability, calendar-block uncertainty and BH q",),
                methodology=("Compare eight frozen state-horizon paths on identical evaluation dates",),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX89 data-gate receipt differs")
        root = Path(__file__).resolve().parents[3]
        basis_path = root / "experiments/S008/20260925_S008_EX89/artifacts/basis_causal_panel.csv.gz"
        panel_path = root / "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz"
        execution_path = root / "data/raw/518880_execution_manifest.json"
        for path, expected in ((basis_path, BASIS_SHA256), (panel_path, PANEL_SHA256),
                               (execution_path, EXECUTION_SHA256)):
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"frozen input identity differs: {path.name}")
        basis = pd.read_csv(basis_path, parse_dates=["Date", "SourceDate"]).set_index("Date")
        panel = pd.read_csv(panel_path, compression="gzip", parse_dates=["Date"]).set_index("Date")
        if not basis.index.equals(panel.index):
            raise ValueError("basis and existing causal panel dates differ")
        if basis["SourceDate"].ge(pd.Series(basis.index, index=basis.index)).fillna(False).any():
            raise ValueError("same-day basis source leaked into decision")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        prices = load_execution_prices(
            root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff="2024-12-31"
        )
        opens = prices.set_index("dt")["open"].sort_index().astype(float)
        if not panel.index.isin(opens.index).all():
            raise ValueError("execution opens do not cover the causal panel")
        frame = panel[list(PRICE + SPOT)].join(basis[["CurveSlope", "DaysToMaturity", "SpotFuturesBasis"]])
        frame["Open"] = opens.reindex(frame.index)
        predictions, fits, ledger = audit(frame)
        predictions.to_csv(context.workspace.path("annual_predictions.csv"), index=False, lineterminator="\n")
        fits.to_csv(context.workspace.path("model_fits.csv"), index=False, lineterminator="\n")
        ledger.to_csv(context.workspace.path("basis_incremental_ledger.csv"), index=False, lineterminator="\n")
        clues = ledger.loc[ledger["ExploratoryClue"], ["State", "Horizon"]].to_dict("records")
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={"decision": "REVIEW_BASIS_INCREMENTAL_INFORMATION", "comparisons": len(ledger),
                   "estimable": int(ledger["PValue"].notna().sum()), "exploratory_clues": clues,
                   "evaluation_rows": len(predictions), "development_cutoff": "2024-12-31"},
            diagnostics={"discovery_only": True, "independent_out_of_sample": False,
                         "reads_sealed_validation": False, "candidate_created": False},
            artifacts=tuple(context.workspace.register_artifact(name, kind) for name, kind in (
                ("annual_predictions.csv", "annual-forward-predictions"),
                ("model_fits.csv", "identifiability-ledger"),
                ("basis_incremental_ledger.csv", "multiplicity-adjusted-basis-tests"),
            )),
        )
