"""Independent PTE expectations for the unit-price binary fixture strategy."""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from paper_trading_engine.inspection import (
    CoverageRequirement, InspectionOrderStatus, PteCheckpointExpectation,
    PteCoverageRequirement, PteDecisionInput, PteEnvironmentRequirement,
    PteFailureCase, PteFault, PteInspectionCapability, PteInspectionProtocol,
    PteInspectionScenario, PteOrderKey, PteOrderUpdate, PteRepeatedOrderReport,
    PteSubmissionResult, SubmissionOutcome,
)
from paper_trading_engine.lifecycle import AccountHealth
from strategy_runtime import PlannedOrder, OrderSide, OrderType


def unit_price_protocol(environment, bindings):
    """100000 cash, price 1, 0.1% fee: 99900 shares and 99800.2 exit cash.

    Expected values are specified before execution, never copied from observed
    strategy/PTE output. ``bindings`` are real prepared one-session SRT inputs.
    """
    zone = timezone(timedelta(hours=8))

    def at(day, hour, minute):
        return datetime(2026, 9, day, hour, minute, tzinfo=zone)

    buy = (PlannedOrder(OrderSide.BUY, 99900, OrderType.LIMIT, Decimal("1")),)
    sell = (PlannedOrder(OrderSide.SELL, 99900, OrderType.MARKET, Decimal("1")),)
    decisions = tuple(PteDecisionInput(name, bindings[name], at(day - 1, 20, 31),
                                      date(2026, 9, day), at(day, 10, 0), name == "enter")
                      for name, day in (("enter", 16), ("hold", 17), ("exit", 18)))
    enter, exit = PteOrderKey("enter", 0), PteOrderKey("exit", 0)
    events = (
        PteSubmissionResult("entry_accepted", at(16, 10, 0), enter, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate("entry_partial", at(16, 10, 1), enter, InspectionOrderStatus.PARTIAL,
                       50000, Decimal("1"), Decimal("50")),
        PteRepeatedOrderReport("entry_repeated", at(16, 10, 2), "entry_partial"),
        PteOrderUpdate("entry_filled", at(16, 10, 3), enter, InspectionOrderStatus.FILLED,
                       99900, Decimal("1"), Decimal("99.9")),
        PteSubmissionResult("exit_accepted", at(18, 10, 0), exit, SubmissionOutcome.ACCEPTED),
        PteOrderUpdate("exit_filled", at(18, 10, 0), exit, InspectionOrderStatus.FILLED,
                       99900, Decimal("1"), Decimal("99.9")),
    )

    def expected(event, orders, quantity, cash, frozen, target, count):
        return PteCheckpointExpectation(event.replace(":", "_") + "_check", event, orders,
                                        quantity, Decimal(cash), Decimal(frozen), target,
                                        AccountHealth.OK, count)

    checkpoints = (
        expected("LOAD", (), 0, "100000", "0", None, 0),
        expected("enter:decision", buy, 0, "0.1", "99999.9", 99900, 0),
        expected("enter:repeat", buy, 0, "0.1", "99999.9", 99900, 0),
        expected("enter:submit", buy, 0, "0.1", "99999.9", 99900, 1),
        expected("entry_partial", buy, 50000, "0.1", "49949.9", 99900, 1),
        expected("entry_repeated", buy, 50000, "0.1", "49949.9", 99900, 1),
        expected("entry_filled", buy, 99900, "0.1", "0", 99900, 1),
        expected("hold:decision", (), 99900, "0.1", "0", 99900, 1),
        expected("hold:submit", (), 99900, "0.1", "0", 99900, 1),
        expected("exit:decision", sell, 99900, "0.1", "0", 99900, 1),
        expected("exit:submit", sell, 0, "99800.2", "0", 99900, 2),
        expected("exit_filled", sell, 0, "99800.2", "0", 99900, 2),
    )
    scenario = PteInspectionScenario("unit_price_cycle", Decimal("100000"), decisions, events,
                                     checkpoints, restart_after=("entry_partial",))
    coverage = tuple(PteCoverageRequirement(
        capability,
        CoverageRequirement.NOT_APPLICABLE if capability is PteInspectionCapability.POSITION_CHANGE
        else CoverageRequirement.REQUIRED,
        () if capability is PteInspectionCapability.POSITION_CHANGE else (scenario.scenario_id,),
        "Binary entry-cycle strategy has no fractional exposure levels."
        if capability is PteInspectionCapability.POSITION_CHANGE else "Assert the declared economic trajectory.",
    ) for capability in PteInspectionCapability)
    failures = (
        PteFailureCase("damaged_package", scenario.scenario_id, PteFault.PACKAGE_CONTENT_CHANGED, "LOAD"),
        PteFailureCase("missing_input", scenario.scenario_id, PteFault.INPUT_UNAVAILABLE, "enter:decision"),
        PteFailureCase("future_input", scenario.scenario_id, PteFault.INPUT_AFTER_DECISION, "enter:decision"),
    )
    return PteInspectionProtocol(PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version), (scenario,), coverage, failures)
