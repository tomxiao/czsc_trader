from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
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


EXPERIMENT_ID = "20260925_S008_EX89"
START = "2013-07-29"
CUTOFF = "2024-12-31"
PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
FEATURES = ("SpotFuturesBasis", "CurveSlope", "DaysToMaturity")


def build_basis_panel(
    daily: pd.DataFrame, mapping: pd.DataFrame, spot: pd.DataFrame, etf_dates: pd.DatetimeIndex
) -> pd.DataFrame:
    main = mapping.merge(daily, on=["Date", "Contract"], how="left", validate="one_to_one")
    if main["Settle"].isna().any():
        raise ValueError("main mapping has missing settlement bars")
    main = main.merge(
        spot[["Date", "Close"]].rename(columns={"Close": "SpotClose"}),
        on="Date", how="left", validate="one_to_one",
    )
    # A missing SGE session remains missing on the matching source date. The
    # preregistered coverage gate below decides whether the history is usable.
    maturity_days = (main["MaturityDate"] - main["Date"]).dt.days
    if maturity_days.le(0).any() or main["Settle"].le(0).any() or main["SpotClose"].le(0).any():
        raise ValueError("basis has invalid price or maturity")
    main["SpotFuturesBasis"] = np.log(main["Settle"] / main["SpotClose"])
    main["DaysToMaturity"] = maturity_days.astype(float)
    far_candidates = daily.merge(
        main[["Date", "MaturityDate"]].rename(columns={"MaturityDate": "MainMaturityDate"}),
        on="Date", validate="many_to_one",
    )
    far_candidates = far_candidates.loc[
        far_candidates["MaturityDate"].ge(far_candidates["MainMaturityDate"] + pd.Timedelta(days=60))
        & far_candidates["Volume"].gt(0)
    ]
    far = far_candidates.sort_values(["Date", "MaturityDate", "Contract"]).drop_duplicates("Date")
    curve = main[["Date", "Settle", "MaturityDate"]].merge(
        far[["Date", "Settle", "MaturityDate"]], on="Date", how="left",
        suffixes=("Main", "Far"), validate="one_to_one",
    )
    tenor = (curve["MaturityDateFar"] - curve["MaturityDateMain"]).dt.days
    main["CurveSlope"] = (
        (curve["SettleFar"].to_numpy() / curve["SettleMain"].to_numpy() - 1)
        * 365 / tenor.to_numpy()
    )
    source = main[["Date", *FEATURES]].rename(columns={"Date": "SourceDate"}).sort_values("SourceDate")
    decisions = pd.DataFrame({"Date": etf_dates}).sort_values("Date")
    aligned = pd.merge_asof(
        decisions, source, left_on="Date", right_on="SourceDate",
        direction="backward", allow_exact_matches=False,
    )
    age = (aligned["Date"] - aligned["SourceDate"]).dt.days
    aligned.loc[age.gt(10), list(FEATURES)] = np.nan
    if aligned["SourceDate"].ge(aligned["Date"]).fillna(False).any():
        raise ValueError("same-day or future source leaked into ETF decision")
    return aligned


def synthetic_precheck() -> None:
    dates = pd.to_datetime(["2024-06-03", "2024-06-04"])
    daily = pd.DataFrame({
        "Date": [dates[0], dates[0], dates[1], dates[1]],
        "Contract": ["AU2406.SHF", "AU2408.SHF"] * 2,
        "MaturityDate": pd.to_datetime(["2024-06-17", "2024-08-16"] * 2),
        "Settle": [550.0, 552.0, 551.0, 553.0],
        "Volume": [100.0] * 4,
    })
    mapping = pd.DataFrame({"Date": dates, "Contract": ["AU2406.SHF", "AU2406.SHF"]})
    spot = pd.DataFrame({"Date": dates, "Close": [549.0, 550.0]})
    decisions = pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05"])
    panel = build_basis_panel(daily, mapping, spot, decisions)
    if not pd.isna(panel.loc[0, "SpotFuturesBasis"]):
        raise ValueError("synthetic same-day source was used")
    if not np.isclose(panel.loc[1, "SpotFuturesBasis"], np.log(550.0 / 549.0)):
        raise ValueError("synthetic prior-session basis differs")
    if panel.loc[2, "SourceDate"] != dates[1] or not np.isfinite(panel.loc[2, "CurveSlope"]):
        raise ValueError("synthetic source alignment or curve differs")
    missing_spot = build_basis_panel(daily, mapping, spot.iloc[:1], decisions)
    if not pd.isna(missing_spot.loc[2, "SpotFuturesBasis"]):
        raise ValueError("missing same-date spot was filled from an older session")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Is an auditable causal SHFE-main versus SGE-spot basis available?",
            hypothesis="The spot-futures premium may encode financing or physical demand beyond the inter-futures curve.",
            falsification_conditions=(
                "A governed source or identity fails",
                "Same-date pairing or causal alignment fails",
                "Basis or curve coverage is below the frozen 95 percent gate",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=20260989,
            allowed_datasets=(
                Dataset.FUTURES_SHFE_GOLD_DAILY.value,
                Dataset.FUTURES_SHFE_GOLD_MAPPING.value,
                Dataset.SGE_GOLD_DAILY.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=("Spot-futures premium mixes carrying cost and physical demand",),
                information_paths=("Prior-session SHFE main versus SGE spot -> potential later ETF upside",),
                stage_objectives=("Establish a causal basis input without observing future ETF returns",),
                observation_metrics=("Governed data identities, basis and curve coverage, source age",),
                methodology=("Pair source-date prices, keep all rolls, align strictly to later ETF decisions",),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        root = Path(__file__).resolve().parents[3]
        panel_path = root / "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz"
        if sha256(panel_path.read_bytes()).hexdigest() != PANEL_SHA256:
            raise ValueError("EX16 causal-calendar identity differs")
        etf_dates = pd.DatetimeIndex(
            pd.read_csv(panel_path, compression="gzip", usecols=["Date"], parse_dates=["Date"])["Date"]
        )
        if len(etf_dates) != 2781 or etf_dates.min() != pd.Timestamp(START) or etf_dates.max() != pd.Timestamp(CUTOFF):
            raise ValueError("fixed ETF development calendar differs")
        requests = (
            (Dataset.FUTURES_SHFE_GOLD_DAILY, "AU.SHFE"),
            (Dataset.FUTURES_SHFE_GOLD_MAPPING, "AU.SHFE"),
            (Dataset.SGE_GOLD_DAILY, "Au99.99"),
        )
        frames: dict[Dataset, pd.DataFrame] = {}
        identity_rows: list[dict[str, object]] = []
        for dataset, symbol in requests:
            result = context.data.fetch(
                DataRequest(dataset, symbol, START, CUTOFF, CUTOFF, options={"env_file": ".env"})
            )
            if result.status is not DataStatus.READY or result.identity is None:
                raise RuntimeError(f"governed source is not READY: {dataset}: {result.error}")
            if not result.identity.metadata["available_at"]:
                raise ValueError(f"source-time metadata is missing: {dataset}")
            frames[dataset] = result.dataframe.copy()
            identity_rows.append({
                "Dataset": dataset.value, "Symbol": symbol, "Rows": len(result.dataframe),
                "Start": result.identity.data_start, "Cutoff": result.identity.data_cutoff,
                "Sha256": result.identity.content_sha256,
                "AvailableAt": result.identity.metadata["available_at"],
            })
        panel = build_basis_panel(
            frames[Dataset.FUTURES_SHFE_GOLD_DAILY],
            frames[Dataset.FUTURES_SHFE_GOLD_MAPPING],
            frames[Dataset.SGE_GOLD_DAILY],
            etf_dates,
        )
        coverage = {field: float(panel[field].notna().mean()) for field in FEATURES}
        if min(coverage["SpotFuturesBasis"], coverage["CurveSlope"]) < 0.95:
            raise ValueError(f"basis data gate coverage failed: {coverage}")
        if not panel["Date"].equals(pd.Series(etf_dates, name="Date")):
            raise ValueError("basis panel calendar differs")
        panel.to_csv(context.workspace.path("basis_causal_panel.csv.gz"), index=False,
                     compression={"method": "gzip", "compresslevel": 9, "mtime": 0}, lineterminator="\n")
        pd.DataFrame(identity_rows).to_csv(
            context.workspace.path("source_identities.csv"), index=False, lineterminator="\n"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "PROCEED_TO_BASIS_INFORMATION_AUDIT", "coverage": coverage,
                   "etf_dates": len(panel), "source_rows": {row["Dataset"]: row["Rows"] for row in identity_rows},
                   "development_cutoff": CUTOFF},
            diagnostics={"reads_real_returns": False, "reads_sealed_validation": False,
                         "creates_candidate": False},
            artifacts=(
                context.workspace.register_artifact("basis_causal_panel.csv.gz", "causal-basis-panel"),
                context.workspace.register_artifact("source_identities.csv", "governed-source-identities"),
            ),
        )
