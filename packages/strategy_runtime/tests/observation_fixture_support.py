from dataclasses import replace


from datetime import date, datetime, timezone


from decimal import Decimal






from strategy_runtime import (
    ConstantGuide,
    EvidenceGuide,
    ObservationDefinition,
    ObservationFact,
    ObservationSeries,
    ObservationValueType as ValueType,
    ObservationFormat as Format,
    ExecutionPlan,
    StrategyIdentity,
    PriceReference,
    ExecutionCapabilities,
    SignalRender,
    SignalGroup,
    SignalSeriesDefinition,
    SignalStateOption,
    SignalStateDefinition,
    SignalPanelDefinition,
)


from strategy_runtime.contracts import signal_identity_for, plan_identity_for


from packages.strategy_runtime.tests.authoring_fixture_support import _definition


def observed_plan(evidence=None, signal_panel=None):
    declaration = ObservationDefinition(
        (
            ObservationSeries(
                "score",
                "Score",
                "score",
                (ConstantGuide("entry", "Entry", 0.2), EvidenceGuide("exit", "Exit", "exit")),
            ),
        ),
        (
            ObservationFact("reason", "Reason", "reason", ValueType.TEXT, Format.TEXT),
            ObservationFact("active", "Active", "active", ValueType.BOOLEAN, Format.BOOLEAN),
            ObservationFact("count", "Count", "count", ValueType.INTEGER, Format.INTEGER),
        ),
        signal_panel,
    )
    definition = replace(_definition(), observation=declaration)
    strategy = StrategyIdentity(
        definition.strategy_family_id,
        definition.release_id,
        definition.release_hash,
        definition.runtime_sha256,
        definition.tradable_symbol,
    )
    signal = dict(
        strategy=strategy,
        signal_date=date(2026, 9, 1),
        target_position=0.0,
        input_identities={"input": "a" * 64},
        price_identities={"price": "b" * 64},
    )
    execution = dict(
        signal_identity=signal_identity_for(**signal),
        actual_quantity=0,
        target_quantity=0,
        cycle_target_quantity=0,
        plan_mode="NONE",
        capital_mode="full_available_cash",
        allocation_fraction=Decimal(1),
        orders=(),
        legs=(),
    )
    plan = ExecutionPlan(
        **signal,
        **execution,
        plan_identity=plan_identity_for(**execution),
        symbol=definition.tradable_symbol,
        trading_date=date(2026, 9, 2),
        generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        expected_portfolio_revision=0,
        expected_state_revision=0,
        action="WAIT",
        available_cash=Decimal(1000),
        fee_rate=Decimal(".001"),
        estimated_order_cost=Decimal(0),
        unallocated_cash=Decimal(1000),
        references=PriceReference(Decimal(1), Decimal(1), "hfq", "raw"),
        required_capabilities=ExecutionCapabilities(()),
        evidence=evidence
        or {
            "score": 0.31,
            "exit": 0.08,
            "reason": "完整理由" * 100,
            "active": False,
            "count": 2,
            "private": "hidden",
        },
    )
    return definition, plan


def signal_panel_plan(**evidence):
    panel = SignalPanelDefinition(
        (SignalGroup("conditions", "入场条件", "比例", "price_ratio", Format.PERCENT, 2),
         SignalGroup("boundaries", "机会边界", "元", "hfq", Format.NUMBER, 3)),
        (SignalSeriesDefinition("space", "修复空间", "conditions", "obs_space",
                                guides=(ConstantGuide("minimum", "最低门槛", .002),)),
         SignalSeriesDefinition("target", "固定目标", "boundaries", "obs_target", SignalRender.STEP,
                                "obs_target_status", "obs_segment", "obs_reason",
                                (EvidenceGuide("center", "当前中心", "obs_center"),))),
        (SignalStateDefinition("opportunity", "机会状态", "obs_state",
                               (SignalStateOption("active", "有效"), SignalStateOption("ended", "结束"))),),
    )
    original = dict(observed_plan()[1].evidence)
    original.update(obs_space=.03, obs_target=1.5, obs_target_status="AVAILABLE",
                    obs_segment="2026-09-01", obs_center=1.45, obs_state="active")
    original.update(evidence)
    return observed_plan(original, signal_panel=panel)
