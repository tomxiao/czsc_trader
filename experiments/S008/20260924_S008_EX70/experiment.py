from __future__ import annotations

from datetime import date
import gzip
from io import StringIO
import json

from dataflows import DataRequest, DataStatus
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


PREDECESSOR_ID = "20260924_S008_EX68"
PREDECESSOR_RECEIPT = "a9c683cb0d64e94fa8930c753e2bfd9626949d1e864b00b8152b9953b0aceb01"
EXPECTED_TIMES = (
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "13:30",
    "14:00",
    "14:30",
    "15:00",
)


def _build_intraday_panel(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy()
    bars["Date"] = pd.to_datetime(bars["Date"], errors="raise")
    bars["Session"] = bars["Date"].dt.normalize()
    bars["Time"] = bars["Date"].dt.strftime("%H:%M")
    rows: list[dict[str, object]] = []
    previous_close: float | None = None
    for session, group in bars.groupby("Session", sort=True):
        group = group.sort_values("Date").reset_index(drop=True)
        first = group.iloc[0]
        morning_close = group.loc[group["Time"] == "11:30"].iloc[0]
        afternoon_open = group.loc[group["Time"] == "13:30"].iloc[0]
        tail_open = group.loc[group["Time"] == "14:00"].iloc[0]
        last = group.iloc[-1]
        high = float(group["High"].max())
        low = float(group["Low"].min())
        day_range = high - low
        volume = float(group["Volume"].sum())
        amount = float(group["Amount"].sum())
        rows.append(
            {
                "Date": pd.Timestamp(session),
                "CloseLocation": 0.5
                if day_range == 0
                else (float(last["Close"]) - low) / day_range,
                "MorningReturn": float(morning_close["Close"]) / float(first["Open"]) - 1.0,
                "AfternoonReturn": float(last["Close"]) / float(afternoon_open["Open"]) - 1.0,
                "LastHourReturn": float(last["Close"]) / float(tail_open["Open"]) - 1.0,
                "LastHourVolumeShare": float(group.iloc[-2:]["Volume"].sum()) / volume,
                "LastHourAmountShare": float(group.iloc[-2:]["Amount"].sum()) / amount,
                "OvernightGap": None
                if previous_close is None
                else float(first["Open"]) / previous_close - 1.0,
                "IntradayReturn": float(last["Close"]) / float(first["Open"]) - 1.0,
                "AvailableAt": f"{pd.Timestamp(session).date().isoformat()} 15:00:00+08:00",
            }
        )
        previous_close = float(last["Close"])
    return pd.DataFrame(rows)


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX70",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Do managed intraday participation facts and SHFE gold futures facts provide "
                "causal inputs for the upside-capture information audit?"
            ),
            hypothesis=(
                "Intraday participation and leveraged futures positioning can reveal upside "
                "participation earlier than daily trend-state filters."
            ),
            falsification_conditions=(
                "Managed 30-minute bars are incomplete or cannot produce the frozen descriptors",
                "SHFE gold futures core interfaces lack development-boundary observations",
                "The project cannot govern source availability through DFLS",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097001,
            allowed_datasets=(
                "etf.ohlcv.managed",
                "futures.shfe_gold.capability",
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "Persistent domestic buying may appear inside the trading day before it is visible in daily state filters",
                    "Gold futures positioning and inventories encode leveraged risk preference and physical constraints",
                ),
                information_paths=(
                    "ETF intraday participation -> closing strength -> next-session opportunity participation",
                    "SHFE gold term structure and positioning -> trader risk preference -> ETF opportunity participation",
                ),
                stage_objectives=(
                    "Establish causal and complete inputs without measuring future-return information value",
                ),
                observation_metrics=(
                    "intraday session and descriptor completeness",
                    "vendor endpoint boundary coverage",
                    "project DFLS registration state",
                ),
                methodology=(
                    "Build a deterministic same-session descriptor panel from manifest-bound 30-minute bars",
                    "Probe only Tushare endpoint metadata and preserve no raw futures records",
                ),
                predecessor_experiment_ids=(PREDECESSOR_ID,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR_ID]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX68 receipt identity differs")
        if predecessor.facts.get("decision") != "PROCEED_TO_UPSIDE_PARTICIPATION_INFORMATION_AUDIT":
            raise ValueError("EX68 did not authorize the information-capability audit")

        intraday_result = context.data.fetch(
            DataRequest(
                dataset="etf.ohlcv.managed",
                symbol="518880.SH",
                start="2013-07-29",
                end="2024-12-31",
                required_cutoff="2024-12-31",
                frequency="30m",
            )
        )
        futures_result = context.data.fetch(
            DataRequest(
                dataset="futures.shfe_gold.capability",
                symbol="AU.SHFE",
                start="2013-07-29",
                end="2024-12-31",
                required_cutoff="2024-12-31",
                frequency="daily",
            )
        )
        if intraday_result.status is not DataStatus.READY:
            raise RuntimeError(f"managed intraday data is not ready: {intraday_result.status}")
        if futures_result.status is not DataStatus.READY:
            raise RuntimeError(
                f"futures capability publication is not ready: {futures_result.status}"
            )

        intraday = intraday_result.dataframe.copy()
        intraday["Date"] = pd.to_datetime(intraday["Date"], errors="raise")
        sessions = intraday["Date"].dt.normalize()
        counts = sessions.value_counts()
        actual_times = tuple(sorted(intraday["Date"].dt.strftime("%H:%M").unique()))
        session_contract_pass = (
            int(sessions.nunique()) == 2781
            and bool((counts == 8).all())
            and actual_times == tuple(sorted(EXPECTED_TIMES))
        )
        panel = _build_intraday_panel(intraday)
        numeric_columns = [
            "CloseLocation",
            "MorningReturn",
            "AfternoonReturn",
            "LastHourReturn",
            "LastHourVolumeShare",
            "LastHourAmountShare",
            "OvernightGap",
            "IntradayReturn",
        ]
        finite = np.isfinite(panel[numeric_columns].to_numpy(dtype=float))
        expected_missing = int(panel["OvernightGap"].isna().sum()) == 1
        finite_count = int(finite.sum())
        expected_finite = int(panel.shape[0] * len(numeric_columns) - 1)
        descriptor_completeness = finite_count / expected_finite
        intraday_pass = bool(
            session_contract_pass
            and expected_missing
            and descriptor_completeness >= 0.999
            and finite_count == expected_finite
        )

        csv_buffer = StringIO()
        panel.to_csv(csv_buffer, index=False, lineterminator="\n", float_format="%.12g")
        panel_path = context.workspace.path("intraday_causal_panel.csv.gz")
        panel_path.write_bytes(gzip.compress(csv_buffer.getvalue().encode("utf-8"), mtime=0))
        panel_artifact = context.workspace.register_artifact(
            "intraday_causal_panel.csv.gz", "causal-intraday-descriptor-panel"
        )

        capability = futures_result.dataframe.copy()
        core_names = {
            "fut_basic_au",
            "fut_daily_start",
            "fut_daily_end",
            "fut_mapping_start",
            "fut_mapping_end",
            "fut_holding_start",
            "fut_holding_end",
        }
        core = capability.loc[capability["Capability"].isin(core_names)]
        futures_core_pass = bool(
            len(core) == len(core_names)
            and (core["Status"] == "PASS").all()
            and (pd.to_numeric(core["Rows"], errors="coerce") > 0).all()
        )
        warehouse = capability.loc[capability["Capability"].isin({"fut_wsr_start", "fut_wsr_end"})]
        warehouse_full_coverage = bool(
            len(warehouse) == 2
            and (warehouse["Status"] == "PASS").all()
            and (pd.to_numeric(warehouse["Rows"], errors="coerce") > 0).all()
        )
        project_dfls_ready = bool(capability["ProjectDflsRegistered"].all())

        capability_records = capability.copy()
        capability_records["Date"] = pd.to_datetime(
            capability_records["Date"], errors="raise"
        ).dt.strftime("%Y-%m-%d")
        audit_payload = {
            "schema_version": 1,
            "experiment_id": self.definition.experiment_id,
            "intraday": {
                "rows": int(len(intraday)),
                "sessions": int(sessions.nunique()),
                "bars_per_session_min": int(counts.min()),
                "bars_per_session_max": int(counts.max()),
                "timestamps": list(actual_times),
                "descriptor_rows": int(len(panel)),
                "descriptor_completeness": descriptor_completeness,
                "causality_rule": "T descriptors available after the completed 15:00 bar; earliest action T+1 open",
                "pass": intraday_pass,
            },
            "futures": {
                "capabilities": capability_records.to_dict(orient="records"),
                "core_vendor_pass": futures_core_pass,
                "warehouse_full_coverage": warehouse_full_coverage,
                "project_dfls_ready": project_dfls_ready,
                "causality_rule": "T publication conservatively usable from the next China trading session until available_at is governed",
                "stores_raw_vendor_data": False,
            },
            "reads_future_return_labels": False,
            "reads_sealed_validation": False,
        }
        audit_bytes = (
            json.dumps(audit_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        audit_path = context.workspace.path("capability_audit.json.gz")
        audit_path.write_bytes(gzip.compress(audit_bytes, mtime=0))
        audit_artifact = context.workspace.register_artifact(
            "capability_audit.json.gz", "data-and-causality-capability-audit"
        )

        if not intraday_pass:
            decision = "STOP_UPSIDE_INFORMATION_ROUTE"
            outcome = ExperimentOutcome.FAIL
        elif not futures_core_pass:
            decision = "PROCEED_INTRADAY_INFORMATION_AUDIT_ONLY"
            outcome = ExperimentOutcome.PASS
        elif not project_dfls_ready:
            decision = "PROCEED_INTRADAY_INFORMATION_AUDIT_AND_REQUEST_FUTURES_DFLS_ADAPTATION"
            outcome = ExperimentOutcome.PASS
        else:
            decision = "PROCEED_DUAL_INFORMATION_AUDIT"
            outcome = ExperimentOutcome.PASS

        return ExperimentResult(
            outcome=outcome,
            facts={
                "decision": decision,
                "intraday_pass": intraday_pass,
                "intraday_rows": int(len(intraday)),
                "intraday_sessions": int(sessions.nunique()),
                "descriptor_completeness": descriptor_completeness,
                "futures_core_vendor_pass": futures_core_pass,
                "warehouse_full_coverage": warehouse_full_coverage,
                "futures_project_dfls_ready": project_dfls_ready,
            },
            diagnostics={
                "reads_future_return_labels": False,
                "reads_sealed_validation": False,
                "selects_inputs": False,
                "prototype_created": False,
                "search_started": False,
                "candidate_created": False,
                "platform_mutated": False,
            },
            artifacts=(panel_artifact, audit_artifact),
        )
