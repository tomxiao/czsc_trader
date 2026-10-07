"""SRT platform adapter from validated runtime facts to frozen execution rules."""

from __future__ import annotations

from typing import Any, Mapping

from .execution_rules import ExecutionRuleInput, build_frozen_execution_plan
from .models import ExecutionPolicy


def build_execution_plan(
    *,
    deployment_settings: Mapping[str, object],
    available_cash: float,
    position_quantity: int,
    target_position: float,
    policy: ExecutionPolicy,
    signal_reference_price: float,
    execution_reference_price: float,
    price_scale: float = 1.0,
    unadjusted_reference_price: float | None = None,
) -> Mapping[str, Any]:
    """Build the concrete order plan carried by an SRT execution instruction."""

    return build_frozen_execution_plan(
        ExecutionRuleInput(
            policy_type=policy.policy_type,
            settings=policy.settings,
            deployment_settings=deployment_settings,
            available_cash=available_cash,
            position_quantity=position_quantity,
            target_position=target_position,
            signal_reference_price=signal_reference_price,
            execution_reference_price=execution_reference_price,
            price_scale=price_scale,
            unadjusted_reference_price=unadjusted_reference_price,
        )
    )
