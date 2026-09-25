"""Synthetic SRT/TXE implementation gate for the four S009 opportunity prototypes."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from czsc_trader.temp_workspace import create_temporary_directory
from dataflows import Dataflows, Dataset
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
from strategy_runtime import (
    StrategyCandidate,
    StrategyInit,
    StrategyRuntime,
    TradableWindow,
    implementation_sha256,
)
from trading_execution_engine import HistoricalExecutor


EXPERIMENT_ID = "20260926_S009_EX12"
PREDECESSOR = "20260926_S009_EX11"
PREDECESSOR_RECEIPT = "450a242f5f60ea1a0040aba0b27a9831df3b840db6ba82a24c021cf8a1eb01bb"
PROTOTYPES = ("P01", "P02", "P03", "P04")
SOURCE_FILES = ("strategies/s009_ex12.py",)
EVALUATION_START = date(2019, 2, 1)
EVALUATION_END = date(2019, 4, 30)


def _frames() -> dict[tuple[str, str | None], pd.DataFrame]:
    sessions = pd.bdate_range("2018-01-01", EVALUATION_END)
    elapsed = np.arange(len(sessions), dtype=float)
    close = 6.0 + 0.004 * elapsed + 0.3 * np.sin(elapsed / 23.0)
    # Keep synthetic next opens below the known prior close so a full-cash
    # MARKET plan can exercise its fill/exit path without a financing artifact.
    open_price = np.r_[close[0], close[:-1]] * 0.99
    market = pd.DataFrame({
        "Date": sessions, "Open": open_price,
        "High": np.maximum(open_price, close) + 0.06,
        "Low": np.minimum(open_price, close) - 0.06,
        "Close": close, "Volume": 100000.0,
        "Amount": close * 100000.0,
    })
    frames = {
        (Dataset.ETF_OHLCV.value, "518880.SH"): market,
        (Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH"): market,
    }
    for offset, symbol in enumerate(("510050.SH", "510300.SH", "159915.SZ")):
        shares = 1e9 * np.exp(0.00004 * elapsed + 0.025 * np.sin(elapsed / 13 + offset * 0.4))
        frames[(Dataset.ETF_SHARE_SIZE.value, symbol)] = pd.DataFrame({
            "Date": sessions, "TotalShare": shares,
        })
    frames[(Dataset.US_POLICY_UNCERTAINTY_DAILY.value, None)] = pd.DataFrame({
        "Date": sessions,
        "AvailableDate": sessions + pd.Timedelta(days=1),
        "PolicyUncertaintyIndex": 120 + 25 * np.sin(elapsed / 18 + 0.6),
    })
    days = pd.date_range(sessions[0], sessions[-1] + pd.Timedelta(days=20))
    frames[(Dataset.TRADING_CALENDAR.value, "SSE")] = pd.DataFrame({
        "Date": days, "IsOpen": (days.weekday < 5).astype(int),
    })
    return frames


def _flows(frames: dict[tuple[str, str | None], pd.DataFrame]) -> Dataflows:
    def fetch(request):
        dataset = str(request.dataset)
        frame = frames[(dataset, request.symbol)].copy()
        dates = pd.to_datetime(frame["Date"])
        frame = frame.loc[dates.between(request.start, request.end)].reset_index(drop=True)
        metadata = {"vendor": "S009_EX12_SYNTHETIC", "synthetic": True}
        if dataset == Dataset.ETF_OHLCV.value:
            metadata["adjustment"] = "hfq"
        elif dataset == Dataset.ETF_UNADJUSTED_DAILY.value:
            metadata["adjustment"] = "none"
        elif dataset == Dataset.US_POLICY_UNCERTAINTY_DAILY.value:
            metadata.update({
                "vendor": "FRED", "series_id": "USEPUINDXD",
                "vintage_mode": "INITIAL_RELEASE_ONLY", "fred_output_type": 4,
                "source_time_field": "Date", "availability_time_field": "AvailableDate",
                "source_calendar": "FRED_CALENDAR_DAY",
                "available_at": "initial release date reported by ALFRED",
            })
        return frame, metadata

    return Dataflows({key[0]: fetch for key in frames})


def _candidate(source_root: Path, prototype_id: str, source_hash: str) -> StrategyCandidate:
    return StrategyCandidate(
        "S009", f"EX12{prototype_id}",
        {
            "runtime": {
                "module": "strategy_runtime.strategies.s009_ex12",
                "qualname": "S009Prototype",
                "contract_version": 1,
                "source_files": list(SOURCE_FILES),
                "source_sha256": source_hash,
            },
            "parameters": {"prototype_id": prototype_id},
        },
        source_root,
    )


def _executor(instance, market: pd.DataFrame, fee: float) -> HistoricalExecutor:
    daily = market.rename(columns={
        "Date": "dt", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "vol", "Amount": "amount",
    }).copy()
    daily["symbol"] = "518880.SH"
    return HistoricalExecutor(
        strategy_reference=instance.identity.reference_id,
        symbol="518880.SH",
        execution_daily=daily,
        execution_intraday=pd.DataFrame(columns=["dt", "open", "high", "low", "close"]),
        evaluation_start=pd.Timestamp(EVALUATION_START),
        evaluation_end=pd.Timestamp(EVALUATION_END),
        initial_cash=1_000_000.0,
        execution_policy=instance.definition.execution,
        order_types=instance.definition.capabilities.order_types,
        fee_rate_override=fee,
    )


def _synthetic_gate() -> list[dict[str, object]]:
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    source_root = experiment / "runtime" / "strategy_runtime"
    source_hash = implementation_sha256(SOURCE_FILES, source_root=source_root)
    frames = _frames()
    flows = _flows(frames)
    rows: list[dict[str, object]] = []
    temp = create_temporary_directory(repository, "research-experiments", prefix="s009-ex12-")
    try:
        with patch("strategy_runtime.preparation.Dataflows", return_value=flows):
            for prototype_id in PROTOTYPES:
                candidate = _candidate(source_root, prototype_id, source_hash)
                runtime = StrategyRuntime()
                definition = runtime.describe(candidate)
                instance = runtime.create(StrategyInit(
                    candidate,
                    TradableWindow(EVALUATION_START, EVALUATION_END),
                    temp / prototype_id,
                ))
                prepared = instance.prepare_data()
                history = instance.inspect_signals()
                targets = set(history["target_position"].unique())
                transitions = int(history["target_position"].diff().abs().fillna(0).gt(0).sum())
                if targets != {0.0, 1.0} or transitions < 2:
                    raise ValueError(f"synthetic states are incomplete: {prototype_id}")
                results = [
                    instance.run_window(executor=_executor(
                        instance, frames[(Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH")], fee
                    ))
                    for fee in (0.001, 0.003)
                ]
                expected_days = len(pd.bdate_range(EVALUATION_START, EVALUATION_END))
                if any(len(result.decisions) != expected_days for result in results):
                    raise ValueError(f"TXE decision coverage is incomplete: {prototype_id}")
                if any(result.orders.empty or result.fills.empty for result in results):
                    raise ValueError(f"TXE did not create orders and fills: {prototype_id}")
                for result in results:
                    if result.orders["status"].ne("FILLED").any() or not {"BUY", "SELL"}.issubset(
                        set(result.fills["side"])
                    ) or result.trades.empty or not result.trades["status"].eq("CLOSED").any():
                        raise ValueError(
                            f"TXE order/trade closure failed: {prototype_id}; "
                            f"orders={result.orders[['side', 'quantity', 'status']].to_dict('records')}; "
                            f"trades={result.trades.to_dict('records')}"
                        )
                if not results[0].decisions["target_position"].equals(
                    results[1].decisions["target_position"]
                ):
                    raise ValueError(f"cost scenarios changed decisions: {prototype_id}")
                rows.append({
                    "prototype_id": prototype_id,
                    "runtime_sha256": definition.runtime_sha256,
                    "prepared_through": prepared.available_through.isoformat(),
                    "target_states": "0|1",
                    "target_transitions": transitions,
                    "primary_decisions": len(results[0].decisions),
                    "primary_orders": len(results[0].orders),
                    "primary_fills": len(results[0].fills),
                    "primary_closed_trades": int(results[0].trades["status"].eq("CLOSED").sum()),
                    "stress_decisions": len(results[1].decisions),
                    "stress_orders": len(results[1].orders),
                    "stress_fills": len(results[1].fills),
                    "stress_closed_trades": int(results[1].trades["status"].eq("CLOSED").sum()),
                })
    finally:
        shutil.rmtree(temp)
    return rows


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Can four frozen S009 opportunity rules close through one SRT implementation and TXE?",
            hypothesis="Strictly prior liquidity and policy inputs yield distinct binary decisions and executable market orders.",
            falsification_conditions=(
                "Any component reads same-day unavailable data or misses a calculation session",
                "Any prototype fails to exercise both positions and TXE order/fill closure",
                "Primary and stress costs change the strategy decision sequence",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026091201,
            allowed_datasets=(
                Dataset.ETF_OHLCV.value,
                Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.ETF_SHARE_SIZE.value,
                Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
                Dataset.TRADING_CALENDAR.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.PROTOTYPE,
                first_principles=(
                    "Every return-seeking prototype must map observable states to an executable next-open position",
                    "Synthetic implementation results test technical contracts only",
                ),
                information_paths=(
                    "T-1 broad ETF creations -> domestic liquidity -> gold participation",
                    "FRED initial-release policy uncertainty -> global safe-haven allocation -> gold participation",
                ),
                stage_objectives=(
                    "Verify one reusable SRT implementation for four EX11 prototype identities",
                    "Verify SRT preparation and TXE account closure under two fixed cost scenarios",
                ),
                observation_metrics=("binary target transitions, prepared cutoff, decisions, orders, fills",),
                methodology=(
                    "Use the median of three strictly lagged 20/60-day ETF share log changes as BroadLiquidity20/60",
                    "Use strictly prior ALFRED initial-release values for the 20/120-day policy mean ratio",
                    "Apply EX11 zero-threshold rules without learning weights or using real returns",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        _synthetic_gate()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX11 predecessor receipt differs")
        repository = Path(__file__).resolve().parents[3]
        validate_experiment_archive(repository / "experiments" / "S009" / PREDECESSOR)
        catalog = pd.read_csv(
            repository / "experiments" / "S009" / PREDECESSOR / "artifacts/prototype_catalog.csv"
        )
        contract = json.loads((
            repository / "experiments" / "S009" / PREDECESSOR
            / "artifacts/execution_contract.json"
        ).read_text(encoding="utf-8"))
        if set(catalog["PrototypeId"].str.extract(r"S009-(P\d\d)-")[0]) != set(PROTOTYPES):
            raise ValueError("EX11 prototype catalog differs")
        if contract["position_set"] != [0.0, 1.0] or contract["primary_one_way_cost"] != 0.001:
            raise ValueError("EX11 execution contract differs")
        rows = _synthetic_gate()
        pd.DataFrame(rows).to_csv(
            context.workspace.path("implementation_gate.csv"), index=False, lineterminator="\n"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": "PROCEED_TO_DEVELOPMENT_ACCOUNT_EVALUATION",
                "prototype_count": len(rows),
                "synthetic_technical_gate_passed": True,
                "real_returns_read": False,
            },
            diagnostics={
                "component_aggregation": "median of three strictly lagged share log changes",
                "evaluation_scope": "SYNTHETIC_ONLY",
                "winner_selected": False,
                "candidate_created": False,
            },
            artifacts=(context.workspace.register_artifact(
                "implementation_gate.csv", "S009-synthetic-implementation-gate"
            ),),
        )
