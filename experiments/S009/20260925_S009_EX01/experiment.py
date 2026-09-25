from __future__ import annotations

from datetime import date

from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
import tushare
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


EXPERIMENT_ID = "20260925_S009_EX01"
START = "2013-07-29"
END = "2024-12-31"
WINDOWS = (5, 20, 60)
CONTROL_FEATURES = (
    "PriceReturn5",
    "PriceReturn20",
    "PriceReturn60",
    "PriceReturn120",
    "PriceVolatility20",
)


def _log_return(series: pd.Series, window: int) -> pd.Series:
    values = pd.to_numeric(series, errors="raise").astype(float)
    if not values.gt(0).all():
        raise ValueError("log-return input must be positive")
    return np.log(values).diff(window)


def _strict_prior(
    calendar: pd.DatetimeIndex,
    source: pd.DataFrame,
    value_columns: tuple[str, ...],
    prefix: str,
) -> pd.DataFrame:
    left = pd.DataFrame({"Date": calendar}).sort_values("Date")
    right = source.loc[:, ["Date", *value_columns]].copy().sort_values("Date")
    right = right.rename(columns={
        "Date": f"{prefix}SourceDate",
        **{name: f"{prefix}{name}" for name in value_columns},
    })
    result = pd.merge_asof(
        left,
        right,
        left_on="Date",
        right_on=f"{prefix}SourceDate",
        direction="backward",
        allow_exact_matches=False,
    ).set_index("Date")
    source_dates = result[f"{prefix}SourceDate"]
    if source_dates.notna().any() and source_dates.dropna().ge(source_dates.dropna().index).any():
        raise ValueError(f"{prefix} source date is not strictly prior")
    return result


def build_panel(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    target = frames["target"].copy().sort_values("Date").set_index("Date")
    peer = frames["peer"].copy().sort_values("Date").set_index("Date")
    if not target.index.equals(peer.index):
        raise ValueError("target and peer ETF calendars differ")
    calendar = pd.DatetimeIndex(target.index)
    panel = pd.DataFrame(index=calendar)
    panel["TargetClose"] = pd.to_numeric(target["Close"], errors="raise")
    panel["PeerClose"] = pd.to_numeric(peer["Close"], errors="raise")

    for key, fields, prefix in (
        ("xau", ("BidClose", "AskClose"), "Xau"),
        ("fx", ("BidClose", "AskClose"), "Fx"),
        ("sge", ("Close",), "Sge"),
        ("target_share", ("TotalShare",), "TargetShare"),
        ("peer_share", ("TotalShare",), "PeerShare"),
    ):
        aligned = _strict_prior(calendar, frames[key], fields, prefix)
        panel = panel.join(aligned)

    panel["XauMid"] = (panel["XauBidClose"] + panel["XauAskClose"]) / 2
    panel["FxMid"] = (panel["FxBidClose"] + panel["FxAskClose"]) / 2
    panel["GlobalCnyGold"] = panel["XauMid"] * panel["FxMid"]
    required = (
        "TargetClose",
        "PeerClose",
        "GlobalCnyGold",
        "SgeClose",
        "TargetShareTotalShare",
        "PeerShareTotalShare",
    )
    if not panel.loc[:, required].dropna().gt(0).all().all():
        raise ValueError("positive aligned price/share contract failed")

    panel["PriceReturn5"] = _log_return(panel["TargetClose"], 5)
    panel["PriceReturn20"] = _log_return(panel["TargetClose"], 20)
    panel["PriceReturn60"] = _log_return(panel["TargetClose"], 60)
    panel["PriceReturn120"] = _log_return(panel["TargetClose"], 120)
    panel["PriceVolatility20"] = np.log(panel["TargetClose"]).diff().rolling(20).std(ddof=0)

    catalog: list[dict[str, object]] = []
    for window in WINDOWS:
        target_return = _log_return(panel["TargetClose"], window)
        peer_return = _log_return(panel["PeerClose"], window)
        global_return = _log_return(panel["GlobalCnyGold"], window)
        sge_return = _log_return(panel["SgeClose"], window)
        target_flow = _log_return(panel["TargetShareTotalShare"], window)
        peer_flow = _log_return(panel["PeerShareTotalShare"], window)
        common_flow = (target_flow + peer_flow) / 2

        features = {
            f"GlobalTransmissionGap{window}": global_return - target_return,
            f"DomesticTransmissionGap{window}": sge_return - target_return,
            f"PeerTransmissionGap{window}": peer_return - target_return,
            f"CommonShareFlow{window}": common_flow,
            f"PeerDemandLead{window}": peer_flow - target_flow,
            f"FlowConfirmedGlobalGap{window}": (global_return - target_return) * common_flow.clip(lower=0),
            f"UnconfirmedTargetOvershoot{window}": (global_return - target_return) * (-common_flow).clip(lower=0),
        }
        roles = {
            f"GlobalTransmissionGap{window}": ("GLOBAL_PARITY", "OPPORTUNITY"),
            f"DomesticTransmissionGap{window}": ("DOMESTIC_PARITY", "OPPORTUNITY"),
            f"PeerTransmissionGap{window}": ("PEER_PARITY", "ENTRY_TIMING"),
            f"CommonShareFlow{window}": ("COMMON_FLOW", "CONFIRMATION"),
            f"PeerDemandLead{window}": ("FLOW_DIVERGENCE", "ENTRY_TIMING"),
            f"FlowConfirmedGlobalGap{window}": ("FLOW_CONFIRMED_PARITY", "OPPORTUNITY"),
            f"UnconfirmedTargetOvershoot{window}": ("UNCONFIRMED_OVERSHOOT", "RISK_CONTEXT"),
        }
        for name, values in features.items():
            panel[name] = values
            family, role = roles[name]
            catalog.append({
                "Feature": name,
                "Window": window,
                "Family": family,
                "Role": role,
                "ExpectedAssociation": "POSITIVE",
            })

    candidate_columns = [row["Feature"] for row in catalog]
    panel = panel.loc[:, [
        "XauSourceDate", "FxSourceDate", "SgeSourceDate",
        "TargetShareSourceDate", "PeerShareSourceDate",
        *CONTROL_FEATURES, *candidate_columns,
    ]]
    return panel, pd.DataFrame(catalog)


def synthetic_precheck() -> None:
    calendar = pd.bdate_range("2020-01-02", periods=150)
    source = pd.DataFrame({
        "Date": calendar - pd.Timedelta(days=1),
        "BidClose": np.linspace(100, 130, len(calendar)),
        "AskClose": np.linspace(100.1, 130.1, len(calendar)),
    })
    aligned = _strict_prior(calendar, source, ("BidClose", "AskClose"), "Test")
    if aligned["TestSourceDate"].ge(aligned.index).any():
        raise ValueError("strict-prior synthetic check failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can cross-market gold transmission and ETF flow facts form a causal panel distinct from S008 inputs?",
            hypothesis="Delayed cross-market pass-through and flow confirmation are observable before later ETF returns.",
            falsification_conditions=(
                "Any source is unavailable, incomplete or lacks content identity",
                "Strict-prior source dates or T+1 share availability cannot be enforced",
                "The complete frozen feature panel contains fewer than 2500 sessions",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=20260901,
            allowed_datasets=(
                Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.FXCM_DAILY.value,
                Dataset.SGE_GOLD_DAILY.value,
                Dataset.ETF_SHARE_SIZE.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "International gold, currency and domestic spot changes transmit into RMB gold ETF prices",
                    "ETF creations and redemptions can distinguish broad allocation demand from product crowding",
                ),
                information_paths=(
                    "Strict-prior global/domestic gold facts plus T+1 share facts -> China close decision -> later ETF return",
                ),
                stage_objectives=("Materialize the frozen causal panel without reading future returns",),
                observation_metrics=("source identity, causal dates, coverage, feature completeness",),
                methodology=("Fetch only through DFLS and stop on any identity or causality mismatch",),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", tushare.__version__),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        specifications = (
            ("target", Dataset.ETF_UNADJUSTED_DAILY, "518880.SH"),
            ("peer", Dataset.ETF_UNADJUSTED_DAILY, "518800.SH"),
            ("xau", Dataset.FXCM_DAILY, "XAUUSD.FXCM"),
            ("fx", Dataset.FXCM_DAILY, "USDCNH.FXCM"),
            ("sge", Dataset.SGE_GOLD_DAILY, "Au99.99"),
            ("target_share", Dataset.ETF_SHARE_SIZE, "518880.SH"),
            ("peer_share", Dataset.ETF_SHARE_SIZE, "518800.SH"),
        )
        frames: dict[str, pd.DataFrame] = {}
        identities: list[dict[str, object]] = []
        issues: list[str] = []
        for key, dataset, symbol in specifications:
            result = context.data.fetch(DataRequest(
                dataset=dataset,
                symbol=symbol,
                start=START,
                end=END,
                required_cutoff=END,
                options={"env_file": ".env"},
            ))
            if result.status is not DataStatus.READY or result.identity is None:
                issues.append(f"{key}:{result.status.value}")
                continue
            frame = result.dataframe.copy()
            frame["Date"] = pd.to_datetime(frame["Date"]).dt.normalize()
            frames[key] = frame
            identities.append({
                "Key": key,
                "Dataset": dataset.value,
                "Symbol": symbol,
                "Rows": len(frame),
                "FirstDate": frame["Date"].min().date().isoformat(),
                "LastDate": frame["Date"].max().date().isoformat(),
                "ContentSha256": result.identity.content_sha256,
                "AvailabilityRule": result.identity.metadata.get("availability_rule"),
            })
        if issues or len(frames) != len(specifications):
            raise ValueError(f"S009 source gate failed: {issues}")
        panel, catalog = build_panel(frames)
        complete = panel.dropna(subset=[*CONTROL_FEATURES, *catalog["Feature"].tolist()])
        if len(complete) < 2500:
            raise ValueError(f"complete feature rows {len(complete)} < 2500")
        panel.reset_index().to_csv(
            context.workspace.path("parity_causal_panel.csv.gz"),
            index=False,
            compression="gzip",
            lineterminator="\n",
        )
        catalog.to_csv(context.workspace.path("feature_catalog.csv"), index=False, lineterminator="\n")
        pd.DataFrame(identities).to_csv(
            context.workspace.path("source_identities.csv"), index=False, lineterminator="\n"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": "PROCEED_TO_PARITY_INFORMATION_AUDIT",
                "panel_rows": len(panel),
                "complete_rows": len(complete),
                "candidate_features": len(catalog),
                "source_identities": {row["Key"]: row["ContentSha256"] for row in identities},
            },
            diagnostics={
                "reads_real_returns": False,
                "reads_sealed_validation": False,
                "candidate_created": False,
            },
            artifacts=tuple(context.workspace.register_artifact(name, kind) for name, kind in (
                ("parity_causal_panel.csv.gz", "causal-cross-market-parity-panel"),
                ("feature_catalog.csv", "frozen-feature-catalog"),
                ("source_identities.csv", "dfls-source-identities"),
            )),
        )
