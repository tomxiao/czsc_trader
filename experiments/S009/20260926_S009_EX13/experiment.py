"""Successor execution gate for S009 limit buys and market sells."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_FLOOR
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
    ExecutionPolicy,
    StrategyCandidate,
    StrategyInit,
    StrategyRuntime,
    TradableWindow,
    implementation_sha256,
)
from trading_execution_engine import HistoricalExecutor, OrderSpec, resolve_fill


EXPERIMENT_ID = "20260926_S009_EX13"
PREDECESSOR = "20260926_S009_EX12"
PREDECESSOR_RECEIPT = "e6da86da816065d34e01d35e253456e8fe5ff79eae88146cce7961b52af0ab09"
PROTOTYPES = ("P01", "P02", "P03", "P04")
SOURCE_FILES = ("strategies/s009_ex13.py",)
EVALUATION_START = date(2019, 2, 1)
EVALUATION_END = date(2019, 4, 30)


def _frames() -> dict[tuple[str, str | None], pd.DataFrame]:
    sessions = pd.bdate_range("2018-01-01", EVALUATION_END)
    elapsed = np.arange(len(sessions), dtype=float)
    close = 6.0 + 0.004 * elapsed + 0.3 * np.sin(elapsed / 23.0)
    # A 5% synthetic overnight rise exercises a marketable limit buy while
    # remaining below the exchange-derived 10% ceiling.
    open_price = np.r_[close[0], close[:-1]] * 1.05
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
        metadata = {"vendor": "S009_EX13_SYNTHETIC", "synthetic": True}
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
        "S009", f"EX13{prototype_id}",
        {
            "runtime": {
                "module": "strategy_runtime.strategies.s009_ex13",
                "qualname": "S009Prototype",
                "contract_version": 1,
                "source_files": list(SOURCE_FILES),
                "source_sha256": source_hash,
            },
            "parameters": {"prototype_id": prototype_id},
        },
        source_root,
    )


def _executor(instance, market: pd.DataFrame, policy: ExecutionPolicy) -> HistoricalExecutor:
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
        execution_policy=policy,
        order_types=instance.definition.capabilities.order_types,
    )


def _synthetic_gate() -> list[dict[str, object]]:
    signal_close = 10.0
    buy_limit = 10.999
    under_limit = resolve_fill(
        OrderSpec("BUY", "LIMIT", 100, buy_limit),
        session_open=10.5,
        session_time=pd.Timestamp("2019-02-01").to_pydatetime(),
        intraday_touches=(),
    )
    at_limit_up = resolve_fill(
        OrderSpec("BUY", "LIMIT", 100, buy_limit),
        session_open=signal_close * 1.1,
        session_time=pd.Timestamp("2019-02-01").to_pydatetime(),
        intraday_touches=(),
    )
    strict_touch = resolve_fill(
        OrderSpec("BUY", "LIMIT", 100, buy_limit),
        session_open=11.0,
        session_time=pd.Timestamp("2019-02-01").to_pydatetime(),
        intraday_touches=((pd.Timestamp("2019-02-01 10:00").to_pydatetime(), 10.998),),
    )
    equal_touch = resolve_fill(
        OrderSpec("BUY", "LIMIT", 100, buy_limit),
        session_open=11.0,
        session_time=pd.Timestamp("2019-02-01").to_pydatetime(),
        intraday_touches=((pd.Timestamp("2019-02-01 10:00").to_pydatetime(), 10.999),),
    )
    if (not under_limit.filled or under_limit.price != 10.5 or at_limit_up.filled
            or not strict_touch.filled or equal_touch.filled):
        raise ValueError("limit-buy opening and limit-up nonfill semantics differ")
    experiment = Path(__file__).resolve().parent
    repository = experiment.parents[2]
    source_root = experiment / "runtime" / "strategy_runtime"
    source_hash = implementation_sha256(SOURCE_FILES, source_root=source_root)
    frames = _frames()
    flows = _flows(frames)
    rows: list[dict[str, object]] = []
    temp = create_temporary_directory(repository, "research-experiments", prefix="s009-ex13-")
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
                settings = dict(definition.execution.settings)
                settings["capital"] = {**settings["capital"], "fee_rate": 0.003}
                stress_policy = ExecutionPolicy(definition.execution.policy_type, settings)
                stress_instance = runtime.create(StrategyInit(
                    candidate,
                    TradableWindow(EVALUATION_START, EVALUATION_END),
                    temp / prototype_id / "stress",
                    execution_policy=stress_policy,
                ))
                stress_instance.prepare_data()
                market = frames[(Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH")]
                results = [
                    instance.run_window(executor=_executor(instance, market, definition.execution)),
                    stress_instance.run_window(executor=_executor(stress_instance, market, stress_policy)),
                ]
                expected_days = len(pd.bdate_range(EVALUATION_START, EVALUATION_END))
                if any(len(result.decisions) != expected_days for result in results):
                    raise ValueError(f"TXE decision coverage is incomplete: {prototype_id}")
                if any(result.orders.empty or result.fills.empty for result in results):
                    raise ValueError(f"TXE did not create orders and fills: {prototype_id}")
                for fee, result in zip((0.001, 0.003), results, strict=True):
                    if result.orders["status"].ne("FILLED").any() or not {"BUY", "SELL"}.issubset(
                        set(result.fills["side"])
                    ) or result.trades.empty or not result.trades["status"].eq("CLOSED").any():
                        raise ValueError(
                            f"TXE order/trade closure failed: {prototype_id}; "
                            f"orders={result.orders[['side', 'quantity', 'status']].to_dict('records')}; "
                            f"trades={result.trades.to_dict('records')}"
                        )
                    buys = result.orders.loc[result.orders["side"].eq("BUY")]
                    sells = result.orders.loc[result.orders["side"].eq("SELL")]
                    if not buys["order_type"].eq("LIMIT").all() or not sells["order_type"].eq("MARKET").all():
                        raise ValueError(f"S009 order types differ: {prototype_id}")
                    if not result.fills.loc[result.fills["side"].eq("BUY"), "trigger"].eq("OPEN").all():
                        raise ValueError(f"S009 limit buys did not fill at the open: {prototype_id}")
                    market_close = frames[(Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH")].set_index("Date")["Close"]
                    cash_before = result.account_daily.set_index("date")["cash_before"]
                    for order in buys.itertuples(index=False):
                        previous_close = Decimal(str(market_close.loc[order.signal_date]))
                        upper_tick = (previous_close * Decimal("1.1") / Decimal("0.001")).to_integral_value(
                            rounding=ROUND_FLOOR
                        ) * Decimal("0.001")
                        expected_limit = upper_tick - Decimal("0.001")
                        if abs(Decimal(str(order.limit_price)) - expected_limit) > Decimal("0.0000001"):
                            raise ValueError(f"S009 buy limit differs from upper band: {prototype_id}")
                        reserve = Decimal(str(order.quantity)) * expected_limit * (1 + Decimal(str(fee)))
                        if reserve > Decimal(str(cash_before.loc[order.execution_date])) + Decimal("0.000001"):
                            raise ValueError(
                                f"S009 limit buy is not cash-funded: {prototype_id}; "
                                f"fee={fee}, reserve={reserve}, cash={cash_before.loc[order.execution_date]}, "
                                f"quantity={order.quantity}, limit={expected_limit}"
                            )
                    if result.account_daily["cash"].lt(-1e-8).any():
                        raise ValueError(f"S009 account cash became negative: {prototype_id}")
                    expected_fees = result.fills["quantity"] * result.fills["price"] * fee
                    if not np.allclose(result.fills["fees"], expected_fees, rtol=0, atol=1e-6):
                        raise ValueError(f"S009 actual fill fees differ from scenario: {prototype_id}")
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
                    "primary_buy_orders": int(results[0].orders["side"].eq("BUY").sum()),
                    "primary_limit_buy_fills_at_open": int(
                        results[0].fills["side"].eq("BUY").mul(results[0].fills["trigger"].eq("OPEN")).sum()
                    ),
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
            research_question="Can the four S009 prototypes execute S007-style bounded limit buys and market sells without changing signals?",
            hypothesis="A limit one tick below the 518880 10% upper band permits causal order sizing and marketable next-open buys without overspending.",
            falsification_conditions=(
                "Any component reads same-day unavailable data or misses a calculation session",
                "Any prototype fails to exercise both positions and TXE order/fill closure",
                "Order types, price cap, limit-up nonfill, or cash safety differs from the approved rule",
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
                    "Preserve the four EX11 signal rules and EX12 causal inputs",
                    "Verify bounded LIMIT buys and MARKET sells under two fixed cost scenarios",
                ),
                observation_metrics=("binary target transitions, prepared cutoff, decisions, order types, fills, cash",),
                methodology=(
                    "Use the median of three strictly lagged 20/60-day ETF share log changes as BroadLiquidity20/60",
                    "Use strictly prior ALFRED initial-release values for the 20/120-day policy mean ratio",
                    "Apply EX11 zero-threshold rules without learning weights or using real returns",
                    "Set buy limit to one 0.001 tick below the rounded 10% upper band; size whole lots using limit and fee",
                    "Require next-open marketable buys, next-open market sells, and no fill at limit-up without a quote",
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
            raise ValueError("EX12 predecessor receipt differs")
        repository = Path(__file__).resolve().parents[3]
        validate_experiment_archive(repository / "experiments" / "S009" / PREDECESSOR)
        gate = pd.read_csv(
            repository / "experiments" / "S009" / PREDECESSOR / "artifacts/implementation_gate.csv"
        )
        contract = json.loads((
            repository / "experiments" / "S009" / "20260926_S009_EX11"
            / "artifacts/execution_contract.json"
        ).read_text(encoding="utf-8"))
        if set(gate["prototype_id"]) != set(PROTOTYPES):
            raise ValueError("EX12 prototype gate differs")
        if (contract["entry_order_type"], contract["exit_order_type"]) != ("MARKET", "MARKET"):
            raise ValueError("EX11 execution contract differs")
        rows = _synthetic_gate()
        pd.DataFrame(rows).to_csv(
            context.workspace.path("implementation_gate.csv"), index=False, lineterminator="\n"
        )
        revised = {
            **contract,
            "schema_version": 2,
            "entry_order_type": "LIMIT",
            "exit_order_type": "MARKET",
            "order_submission_time": "T_PLUS_1_OPEN",
            "execution_time": "T_PLUS_1_OPEN_OR_SAME_DAY_LIMIT_TOUCH",
            "buy_limit_family": "previous_close_ratio_exchange_upper_minus_one_tick",
            "buy_limit_parameter": 0.1,
            "price_limit_ratio": 0.1,
            "price_tick": 0.001,
            "buy_open_fill": "open_at_or_below_limit",
            "buy_intraday_fill": "low_strictly_below_limit",
            "buy_at_limit_up_without_quote": "UNFILLED",
            "buy_sizing_reference": "limit_price_including_fee",
            "source_experiment_id": "20260926_S009_EX11",
            "source_receipt_sha256": "450a242f5f60ea1a0040aba0b27a9831df3b840db6ba82a24c021cf8a1eb01bb",
        }
        context.workspace.path("revised_execution_contract.json").write_text(
            json.dumps(revised, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": "PROCEED_TO_LIMIT_ORDER_DEVELOPMENT_EVALUATION",
                "prototype_count": len(rows),
                "synthetic_technical_gate_passed": True,
                "real_returns_read": False,
            },
            diagnostics={
                "component_aggregation": "median of three strictly lagged share log changes",
                "execution_change": "LIMIT_BUY_MARKET_SELL",
                "evaluation_scope": "SYNTHETIC_ONLY",
                "winner_selected": False,
                "candidate_created": False,
            },
            artifacts=(context.workspace.register_artifact(
                "implementation_gate.csv", "S009-synthetic-implementation-gate"
            ), context.workspace.register_artifact(
                "revised_execution_contract.json", "S009-revised-execution-contract"
            )),
        )
