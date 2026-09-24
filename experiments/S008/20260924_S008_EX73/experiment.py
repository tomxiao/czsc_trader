from __future__ import annotations

from datetime import date
from hashlib import sha256
import json

from dataflows import DataRequest, DataStatus, Dataset
from dotenv import dotenv_values
import pandas as pd
import requests
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


EX72 = "20260924_S008_EX72"
EX72_RECEIPT = "c3e57d8b354c93bfc9c4c26456344cb2d8ac41bfc4be2219fa663469d50034ee"
FIRST_RELEASE = "2013-08-15"
LAST_RELEASE = "2024-12-11"
EXPECTED_RELEASES = 137
MAX_DIFFERENCE_PP = 0.05


def _fred_json(path: str, key: str, **params: str) -> dict[str, object]:
    try:
        response = requests.get(
            "https://api.stlouisfed.org/fred/" + path,
            params={"api_key": key, "file_type": "json", "series_id": "CPIAUCNS", **params},
            timeout=120,
        )
    except requests.RequestException:
        raise RuntimeError("ALFRED request failed") from None
    if response.status_code != 200:
        raise RuntimeError(f"ALFRED returned status {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("ALFRED returned invalid JSON") from None
    if not isinstance(data, dict):
        raise RuntimeError("ALFRED response is not an object")
    return data


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX73",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Can a managed US CPI release series be used at a causal decision time "
                "throughout the S008 development window?"
            ),
            hypothesis=(
                "Tushare release events retain the US CPI first-release information "
                "needed to investigate inflation and gold upside participation."
            ),
            falsification_conditions=(
                "DFLS cannot publish complete and uniquely identified CPI release events",
                "Source clock does not align with the BLS Eastern release clock",
                "ALFRED historical vintages disagree on date or rounded CPI YoY value",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097301,
            allowed_datasets=(Dataset.US_CPI_RELEASE.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.DATA_GATE,
                first_principles=(
                    "US inflation can alter real-rate expectations and gold holding demand",
                    "The impact can reverse when rate tightening or dollar strength dominates",
                ),
                information_paths=(
                    "CPI release -> real-rate and dollar expectations -> gold demand -> ETF participation",
                    "CPI release -> tighter policy expectations -> weaker gold demand",
                ),
                stage_objectives=(
                    "Validate source identity, historical coverage and causal availability only",
                ),
                observation_metrics=(
                    "release count and boundary, vintage-date matches, point-in-time YoY difference",
                ),
                methodology=(
                    "Fetch Tushare through the stable DFLS US CPI release contract",
                    "Compare each release to the corresponding ALFRED as-of CPI index snapshot",
                    "Do not read ETF returns or use Tushare forecast values",
                ),
                predecessor_experiment_ids=(EX72,),
            ),
            dependencies=(
                ExperimentDependency("pandas", "3.0.5"),
                ExperimentDependency("requests", "2.34.2"),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX72]
        if predecessor.receipt_sha256 != EX72_RECEIPT:
            raise ValueError("EX72 receipt identity differs")
        if predecessor.facts.get("decision") != "HOLD_INTRADAY_DISCOVERY_ONLY":
            raise ValueError("EX72 did not close the prior intraday route")
        publication = context.data.fetch(
            DataRequest(
                dataset=Dataset.US_CPI_RELEASE,
                symbol=None,
                start="2013-07-29",
                end="2024-12-31",
                required_cutoff=LAST_RELEASE,
                options={"env_file": ".env"},
            )
        )
        if publication.status is not DataStatus.READY:
            return ExperimentResult(
                outcome=ExperimentOutcome.FAIL,
                facts={
                    "decision": "STOP_US_CPI_DATA_GATE",
                    "dfls_status": publication.status.value,
                    "dfls_error_code": publication.error.code if publication.error else None,
                },
                diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            )
        frame = publication.dataframe
        identity = publication.identity
        if identity is None:
            raise RuntimeError("READY DFLS result has no identity")
        dates = frame["Date"].dt.date.astype(str).tolist()
        key = str(dotenv_values(".env").get("FRED_KEY") or "").strip()
        if not key:
            raise RuntimeError("FRED_KEY is absent")
        vintage_response = _fred_json(
            "series/vintagedates",
            key,
            realtime_start="2013-07-29",
            realtime_end="2024-12-31",
            limit="10000",
        )
        vintage_dates = list(vintage_response.get("vintage_dates", []))
        boundary_pass = (
            len(frame) == EXPECTED_RELEASES
            and dates[0] == FIRST_RELEASE
            and dates[-1] == LAST_RELEASE
        )
        dates_pass = len(vintage_dates) == EXPECTED_RELEASES and vintage_dates == dates
        if not boundary_pass or not dates_pass:
            return ExperimentResult(
                outcome=ExperimentOutcome.FAIL,
                facts={
                    "decision": "STOP_US_CPI_DATA_GATE",
                    "dfls_status": publication.status.value,
                    "dfls_rows": len(frame),
                    "alfred_vintage_count": len(vintage_dates),
                    "boundary_pass": boundary_pass,
                    "release_dates_match": dates_pass,
                    "dfls_content_sha256": identity.content_sha256,
                },
                diagnostics={"reads_real_returns": False, "reads_sealed_validation": False},
            )

        by_release = frame.set_index(frame["Date"].dt.date.astype(str))
        reference_months = pd.period_range("2013-07", "2024-11", freq="M")
        if len(reference_months) != EXPECTED_RELEASES:
            raise RuntimeError("reference-month grid differs from the frozen contract")
        audit = []
        source_digest = sha256()
        for offset in range(0, EXPECTED_RELEASES, 35):
            batch_dates = vintage_dates[offset : offset + 35]
            response = _fred_json(
                "series/observations",
                key,
                output_type="2",
                vintage_dates=",".join(batch_dates),
                observation_start="2012-07-01",
                observation_end="2024-11-01",
                limit="100000",
            )
            observations = response.get("observations", [])
            if not isinstance(observations, list):
                raise RuntimeError("ALFRED vintage observations are missing")
            by_month = {str(item["date"]): item for item in observations}
            for index in range(offset, min(offset + 35, EXPECTED_RELEASES)):
                release_date = vintage_dates[index]
                reference = reference_months[index]
                current_month = reference.strftime("%Y-%m-01")
                prior_month = (reference - 12).strftime("%Y-%m-01")
                field = "CPIAUCNS_" + release_date.replace("-", "")
                current = by_month.get(current_month, {}).get(field)
                prior = by_month.get(prior_month, {}).get(field)
                if current in {None, "."} or prior in {None, "."}:
                    raise RuntimeError("ALFRED as-of CPI denominator or numerator is missing")
                computed = (float(current) / float(prior) - 1.0) * 100.0
                actual = float(by_release.loc[release_date, "YoYPercent"])
                difference = abs(computed - actual)
                source_digest.update(
                    json.dumps(
                        [release_date, current_month, current, prior],
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                audit.append(
                    {
                        "ReferenceMonth": str(reference),
                        "ReleaseDate": release_date,
                        "AvailableDate": by_release.loc[release_date, "AvailableDate"].date().isoformat(),
                        "AbsoluteDifferencePP": difference,
                    }
                )
        ledger = pd.DataFrame(audit)
        ledger_path = context.workspace.path("cpi_release_calibration.csv")
        ledger.to_csv(ledger_path, index=False, float_format="%.12f", lineterminator="\n")
        artifact = context.workspace.register_artifact(
            "cpi_release_calibration.csv", "point-in-time-source-calibration"
        )
        differences_pass = len(ledger) == EXPECTED_RELEASES and ledger[
            "AbsoluteDifferencePP"
        ].le(MAX_DIFFERENCE_PP + 1e-9).all()
        decision = (
            "PROCEED_US_CPI_INFORMATION_VALUE_AUDIT"
            if differences_pass
            else "STOP_US_CPI_DATA_GATE"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if differences_pass else ExperimentOutcome.FAIL,
            facts={
                "decision": decision,
                "dfls_status": publication.status.value,
                "dfls_rows": len(frame),
                "first_release": dates[0],
                "last_release": dates[-1],
                "alfred_vintage_count": len(vintage_dates),
                "boundary_pass": boundary_pass,
                "release_dates_match": dates_pass,
                "point_in_time_yoy_within_0_05pp": int(
                    ledger["AbsoluteDifferencePP"].le(MAX_DIFFERENCE_PP + 1e-9).sum()
                ),
                "maximum_absolute_difference_pp": float(ledger["AbsoluteDifferencePP"].max()),
                "dfls_content_sha256": identity.content_sha256,
                "alfred_calibration_sha256": source_digest.hexdigest(),
            },
            diagnostics={
                "reads_real_returns": False,
                "reads_sealed_validation": False,
                "uses_forecast_values": False,
                "preliminary_exploration_already_seen": True,
                "prototype_created": False,
                "candidate_created": False,
            },
            artifacts=(artifact,),
        )
