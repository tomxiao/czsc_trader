"""Build S007 observation-upgrade PTE protocol from authenticated old-package facts."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import json
from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from enum import Enum
import cloudpickle
import pandas as pd
from czsc_trader.application import (
    RepositoryContext,
    create_research_context,
    describe_inspection_environment,
)
from czsc_trader.research_tools import ResearchBatchRef, ExecutionResources
from dataflows import (
    Dataflows,
    DataSpace,
    ProviderBinding,
    ProviderConfig,
    PreparePolicy,
    canonical_frame_sha256,
)
from strategy_runtime import (
    StrategyCandidate,
    StrategyRelease,
    StrategyRuntime,
    StrategyInit,
    TradableWindow,
    TradingPoint,
    PortfolioSnapshot,
    ExecutionState,
    implementation_sha256,
    SignalHistoryMode,
)
from paper_trading_engine.inspection import (
    CoverageRequirement,
    InspectionOrderStatus,
    PteCheckpointExpectation,
    PteCoverageRequirement,
    PteDecisionInput,
    PteEnvironmentRequirement,
    PteFailureCase,
    PteFault,
    PteInspectionCapability,
    PteInspectionProtocol,
    PteInspectionScenario,
    PteOrderKey,
    PteOrderUpdate,
    PteRepeatedOrderReport,
    PteSubmissionResult,
    SubmissionOutcome,
)
from paper_trading_engine.lifecycle import AccountHealth

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp/observation-v4-upgrade/s007-pte"
ZONE = timezone(timedelta(hours=8))


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, Path)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    repo = RepositoryContext.discover(ROOT)
    ctx = create_research_context(
        repo, ResearchBatchRef("S007"), resources=ExecutionResources(2, 1, 42)
    )
    request = cloudpickle.loads(
        (ROOT / ".tmp/observation-v4-upgrade/S007-v1-baseline.pkl").read_bytes()
    )
    binding = request.input_bindings["full"]
    data = request.execution_data
    original = json.loads((ROOT / "strategies/S007/versions/v1.json").read_text(encoding="utf-8"))
    old = StrategyRelease.from_mapping(original)
    assert (
        request.strategy.payload["runtime"]["source_sha256"]
        == original["strategy_payload"]["runtime"]["source_sha256"]
    )
    originals = {}
    provenance = {}
    for role, req in binding.plan.requests.items():
        fetched = ctx.data.fetch(req, prepared=binding.prepared)
        if (
            not fetched.ready
            or canonical_frame_sha256(fetched.dataframe) != fetched.identity.content_sha256
        ):
            raise ValueError("unauthenticated parent input")
        key = (req.dataset, req.symbol, req.frequency)
        if key in originals:
            raise ValueError("ambiguous parent dataset")
        originals[key] = (req, fetched)
        provenance[role] = {"sha256": fetched.identity.content_sha256, "request": str(req)}

    def provider(req):
        before, fetched = originals[(req.dataset, req.symbol, req.frequency)]
        same_parameters = req.parameters == before.parameters
        if str(req.dataset) == "strategy.feature_evidence":
            same_parameters = (
                req.parameters.source_sha256 == before.parameters.source_sha256
                and req.parameters.source_path == before.parameters.source_path
            )
        if (
            not same_parameters
            or pd.Timestamp(req.start) < pd.Timestamp(before.start)
            or pd.Timestamp(req.end) > pd.Timestamp(before.end)
        ):
            raise ValueError("single-day input outside authenticated window")
        dates = pd.to_datetime(fetched.dataframe.Date)
        frame = (
            fetched.dataframe.loc[
                (dates >= pd.Timestamp(req.start))
                & (dates < pd.Timestamp(req.end) + pd.Timedelta(days=1))
            ]
            .copy()
            .reset_index(drop=True)
        )
        return frame, dict(fetched.identity.metadata)

    flows = Dataflows(
        base_dir=ROOT,
        space=DataSpace(Path("research/S007/assets/data")),
        providers=ProviderConfig(
            bindings={
                ds: ProviderBinding("s007-v4-authenticated-slice", "1", provider)
                for ds, _, _ in originals
            }
        ),
    )
    old_instance = StrategyRuntime(repo.strategy_root, dataflows=flows).create(
        StrategyInit(old, binding.plan.tradable_window, TMP / "old-full", pricing=data.pricing)
    )
    old_instance.prepare_data(policy=PreparePolicy.REUSE)
    old_plan = old_instance.input_binding.plan
    history = old_instance.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    eligible = [(day, signal) for day, signal in old_plan.signal_dates.items()]
    selected = None
    for i, (day, signal) in enumerate(eligible):
        if history.loc[pd.Timestamp(signal), "action"] != "ENTER":
            continue
        held = None
        for next_day, next_signal in eligible[i + 1 :]:
            action = history.loc[pd.Timestamp(next_signal), "action"]
            if action == "HOLD_POSITION" and held is None:
                held = (next_day, next_signal)
            if action == "EXIT":
                if held is not None:
                    selected = ((day, signal), held, (next_day, next_signal))
                break
        if selected:
            break
    if not selected:
        raise ValueError("No original-package ENTER/HOLD/EXIT cycle in authenticated window")
    payload = json.loads(json.dumps(original["strategy_payload"]))
    install = json.loads(
        (ROOT / "strategies/S007/releases/v1/runtime_binding.json").read_text(encoding="utf-8")
    )["install_files"]
    payload["runtime"]["source_files"] = list(
        dict.fromkeys(
            [
                *payload["runtime"]["source_files"],
                *install,
                "strategies/observation_explanation_v4.py",
            ]
        )
    )
    source = HOME / "src/S007-v1/strategy_runtime"
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=source
    )
    candidate = StrategyCandidate("S007", "C9950", payload, source)
    single = {}
    single_evidence = {}
    for name, (day, signal) in zip(("enter", "hold", "exit"), selected, strict=True):
        runtime = StrategyRuntime(repo.strategy_root, dataflows=flows).create(
            StrategyInit(candidate, TradableWindow(day, day), TMP / name, pricing=data.pricing)
        )
        runtime.prepare_data(policy=PreparePolicy.REUSE)
        bound = runtime.input_binding
        assert bound.plan.available_through == signal
        for role, req in bound.plan.requests.items():
            actual = flows.fetch(req, prepared=bound.prepared)
            expected, _ = provider(req)
            assert actual.ready and actual.identity.content_sha256 == canonical_frame_sha256(
                expected
            )
        single[name] = bound
        single_evidence[name] = bound.to_dict()

    def at(day, hour=10, minute=0):
        return datetime.combine(day, time(hour, minute), ZONE)

    cash = Decimal("100000")
    zero = Decimal("0")
    fee = Decimal(str(payload["parameters"]["rule"]["execution"]["capital"]["fee_rate"]))

    def old_order(name, position, available, cycle):
        i = ("enter", "hold", "exit").index(name)
        day, signal = selected[i]
        moment = at(signal, 20, 31)
        portfolio = PortfolioSnapshot(
            "old-package-probe",
            "588080.SH",
            available,
            cash,
            position,
            i,
            moment,
            pricing=data.pricing,
        )
        state = ExecutionState(i, moment, cycle)
        return old_instance.plan_at(
            point=TradingPoint(day, moment),
            portfolio=portfolio,
            state=state,
            history_mode=SignalHistoryMode.CONTINUOUS,
        )

    enter_plan = old_order("enter", 0, cash, None)
    buy = enter_plan.orders
    assert len(buy) == 1 and buy[0].side.value == "BUY"
    shares = buy[0].quantity
    price = buy[0].limit_price
    reserve = (shares * price * (1 + fee)).quantize(Decimal(".0001"))
    expected_shares = (
        int((cash / (price * (1 + fee) * 100)).to_integral_value(rounding=ROUND_FLOOR)) * 100
    )
    assert shares == expected_shares
    partial = shares // 200 * 100
    assert 0 < partial < shares
    full_fee = (shares * price * fee).quantize(Decimal(".0001"))
    held_cash = cash - shares * price - full_fee
    hold_plan = old_order("hold", shares, held_cash, shares)
    assert not hold_plan.orders
    exit_plan = old_order("exit", shares, held_cash, shares)
    sell = exit_plan.orders
    assert len(sell) == 1 and sell[0].side.value == "SELL" and sell[0].quantity == shares
    # Prescribed synthetic fills at legal original-package limits, not candidate results.
    sell_price = sell[0].limit_price
    sell_fee = (shares * sell_price * fee).quantize(Decimal(".0001"))
    final_cash = held_cash + shares * sell_price - sell_fee
    partial_fee = (partial * price * fee).quantize(Decimal(".0001"))
    partial_frozen = ((shares - partial) * price * (1 + fee)).quantize(Decimal(".0001"))
    partial_cash = cash - reserve + partial * price * (1 + fee) - partial * price - partial_fee
    decisions = tuple(
        PteDecisionInput(name, single[name], at(signal, 20, 31), day, at(day), name == "enter")
        for name, (day, signal) in zip(("enter", "hold", "exit"), selected, strict=True)
    )
    ek, xk = PteOrderKey("enter", 0), PteOrderKey("exit", 0)
    events = (
        PteSubmissionResult("entry_accepted", at(selected[0][0]), ek, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate(
            "entry_partial",
            at(selected[0][0], 10, 1),
            ek,
            InspectionOrderStatus.PARTIAL,
            partial,
            price,
            partial_fee,
        ),
        PteRepeatedOrderReport("entry_repeat", at(selected[0][0], 10, 2), "entry_partial"),
        PteOrderUpdate(
            "entry_filled",
            at(selected[0][0], 10, 3),
            ek,
            InspectionOrderStatus.FILLED,
            shares,
            price,
            full_fee,
        ),
        PteSubmissionResult("exit_accepted", at(selected[2][0]), xk, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate(
            "exit_filled",
            at(selected[2][0], 10, 1),
            xk,
            InspectionOrderStatus.FILLED,
            shares,
            sell_price,
            sell_fee,
        ),
    )

    def cp(event, orders, qty, available, frozen, target, count):
        return PteCheckpointExpectation(
            event.replace(":", "_") + "_check",
            event,
            orders,
            qty,
            available,
            frozen,
            target,
            AccountHealth.OK,
            count,
        )

    checks = [cp("LOAD", (), 0, cash, zero, None, 0)]
    for event, count in (("enter:decision", 0), ("enter:repeat", 0), ("enter:submit", 1)):
        checks.append(cp(event, buy, 0, cash - reserve, reserve, shares, count))
    for event in ("entry_partial", "entry_repeat"):
        checks.append(cp(event, buy, partial, partial_cash, partial_frozen, shares, 1))
    checks.append(cp("entry_filled", buy, shares, held_cash, zero, shares, 1))
    for event in ("hold:decision", "hold:submit"):
        checks.append(cp(event, (), shares, held_cash, zero, shares, 1))
    for event, count in (("exit:decision", 1), ("exit:submit", 2)):
        checks.append(cp(event, sell, shares, held_cash, zero, shares, count))
    checks.append(cp("exit_filled", sell, 0, final_cash, zero, shares, 2))
    cycle = PteInspectionScenario(
        "s007_old_package_cycle",
        cash,
        decisions,
        events,
        tuple(checks),
        restart_after=("entry_partial",),
    )
    coverage = tuple(
        PteCoverageRequirement(
            cap,
            CoverageRequirement.NOT_APPLICABLE
            if cap is PteInspectionCapability.POSITION_CHANGE
            else CoverageRequirement.REQUIRED,
            () if cap is PteInspectionCapability.POSITION_CHANGE else (cycle.scenario_id,),
            "Binary entry-cycle strategy; fractional target-equity rebalancing does not apply."
            if cap is PteInspectionCapability.POSITION_CHANGE
            else "Original-package orders and independent decimal cash arithmetic, prescribed synthetic fills.",
        )
        for cap in PteInspectionCapability
    )
    failures = (
        PteFailureCase(
            "package_changed", cycle.scenario_id, PteFault.PACKAGE_CONTENT_CHANGED, "LOAD"
        ),
        PteFailureCase(
            "input_missing", cycle.scenario_id, PteFault.INPUT_UNAVAILABLE, "enter:decision"
        ),
        PteFailureCase(
            "input_future", cycle.scenario_id, PteFault.INPUT_AFTER_DECISION, "enter:decision"
        ),
    )
    env = describe_inspection_environment(repo)
    protocol = PteInspectionProtocol(
        PteEnvironmentRequirement(
            env.platform_build_sha256, env.pte_contract_version, env.srt_contract_version
        ),
        (cycle,),
        coverage,
        failures,
    )
    (HOME / "others/pte_protocol.json").write_text(
        json.dumps(protocol.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    design = {
        "status": "PREPARED_NOT_EXECUTED",
        "reference": "S007-v1",
        "old_release_hash": old.release_hash,
        "candidate_source_sha256": payload["runtime"]["source_sha256"],
        "expectation_source": "Current original frozen package through public SRT plan_at; quantities checked independently; all account cash checkpoints calculated with Decimal. Candidate output is not an expectation source.",
        "purpose": "Observation upgrade execution equivalence, not independent economic-mechanism validation. Synthetic broker fills do not establish real liquidity.",
        "selected_dates": [
            {
                "trading_date": d.isoformat(),
                "signal_date": s.isoformat(),
                "old_action": history.loc[pd.Timestamp(s), "action"],
            }
            for d, s in selected
        ],
        "parent_binding": binding.to_dict(),
        "source_inputs": provenance,
        "single_day_bindings": single_evidence,
        "old_plans": {
            name: plain(plan)
            for name, plan in [("enter", enter_plan), ("hold", hold_plan), ("exit", exit_plan)]
        },
        "arithmetic": {
            k: str(v)
            for k, v in {
                "cash": cash,
                "shares": shares,
                "price": price,
                "reserve": reserve,
                "partial_shares": partial,
                "partial_fee": partial_fee,
                "partial_frozen": partial_frozen,
                "partial_cash": partial_cash,
                "held_cash": held_cash,
                "sell_price": sell_price,
                "sell_fee": sell_fee,
                "final_cash": final_cash,
            }.items()
        },
        "production_writes": 0,
    }
    (HOME / "others/pte_design.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("S007-v1 PTE_PROTOCOL_PREPARED", selected, flush=True)


if __name__ == "__main__":
    main()
