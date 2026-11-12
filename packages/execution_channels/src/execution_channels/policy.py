"""Explicit execution model and account policies owned by EC."""
from dataclasses import dataclass, asdict
from enum import StrEnum
from functools import lru_cache
from typing import Any, Mapping
import math
from .daily_execution import ENTRY_CASH_FRACTION, TARGET_TRIGGERS
from .instruments import BarFrequency, MarketId, InstrumentId, AssetClass
from .identity import equity_hash, canonical_sha256, _text, _json_mapping
from .errors import RuntimeContractError

class CashAvailabilityPolicy(StrEnum):
    IMMEDIATE_RESEARCH = "IMMEDIATE_RESEARCH"
    SETTLED_ONLY = "SETTLED_ONLY"


class ExecutionModel(StrEnum):
    BAR_RANGE = "BAR_RANGE_V1"


def _positive(value, name):
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")


@dataclass(frozen=True, slots=True)
class CnEquitySpec:
    rule_version: str = "CN_EQUITY_V1"

    def __post_init__(self):
        if self.rule_version != 'CN_EQUITY_V1':
            raise ValueError('CN execution policy requires its declared market')


@dataclass(frozen=True, slots=True)
class UsEquitySpec:
    rule_version: str = "US_EQUITY_V1"

    def __post_init__(self):
        if self.rule_version != 'US_EQUITY_V1':
            raise ValueError('US execution policy requires its declared market')


@dataclass(frozen=True, slots=True)
class AccountPolicy:
    currency: str
    cash_availability: CashAvailabilityPolicy
    # Settled-only accounts apply the settlement time resolved for each execution interval.
    allow_short: bool = False
    allow_negative_cash: bool = False

    def __post_init__(self):
        if self.currency not in {"USD", "CNY"} or type(self.cash_availability) is not CashAvailabilityPolicy:
            raise TypeError("explicit currency and cash availability required")
        if self.allow_short is not False or self.allow_negative_cash is not False:
            raise ValueError("equity research supports long-only unlevered accounts")


@dataclass(frozen=True, slots=True)
class ResearchExecutionSpec:
    market: CnEquitySpec | UsEquitySpec
    decision_clock: BarFrequency
    account: AccountPolicy
    quantity_step: int
    price_tick: float
    buy_premium: float
    slippage_bp: float
    execution: ExecutionModel = ExecutionModel.BAR_RANGE
    inclusive_touch: bool = False
    data_latency_seconds: int = 0

    def __post_init__(self):
        if type(self.market) not in (CnEquitySpec, UsEquitySpec) or type(self.account) is not AccountPolicy:
            raise TypeError("explicit typed market and account required")
        if type(self.decision_clock) is not BarFrequency or type(self.execution) is not ExecutionModel:
            raise TypeError("explicit decision frequency and execution model required")
        if type(self.quantity_step) is not int or self.quantity_step <= 0:
            raise ValueError("quantity step must be a positive integer")
        _positive(self.price_tick, "price tick")
        for name in ("buy_premium", "slippage_bp"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {name}")
        if self.buy_premium >= 1 or self.slippage_bp >= 10000:
            raise ValueError("execution premium or slippage outside supported range")
        if type(self.inclusive_touch) is not bool or type(self.data_latency_seconds) is not int or self.data_latency_seconds < 0:
            raise TypeError("invalid touch or latency declaration")
        expected = "USD" if type(self.market) is UsEquitySpec else "CNY"
        if self.account.currency != expected:
            raise ValueError("MARKET_CONTRACT_MISMATCH: account currency")
        expected_rule = "US_EQUITY_V1" if type(self.market) is UsEquitySpec else "CN_EQUITY_V1"
        if self.market.rule_version != expected_rule:
            raise ValueError("unsupported equity market rules version")

    @property
    def market_id(self):
        return MarketId.US if type(self.market) is UsEquitySpec else MarketId.CN

    @property
    def fingerprint(self):
        # Dataclass equality merges 0 with 0.0 and 0.0 with -0.0, while the
        # established canonical JSON identity deliberately distinguishes them.
        representation = tuple(repr(getattr(self, name))
                               for name in ('price_tick', 'buy_premium', 'slippage_bp'))
        return _execution_spec_fingerprint(self, representation)

    def require_instrument(self, instrument: InstrumentId):
        if type(instrument) is not InstrumentId or instrument.market is not self.market_id:
            raise ValueError("MARKET_CONTRACT_MISMATCH: candidate instrument")
        if instrument.asset_class not in (AssetClass.STOCK, AssetClass.ETF):
            raise ValueError("unsupported asset class")


@lru_cache(maxsize=256)
def _execution_spec_fingerprint(specification, numeric_representation):
    """Cache frozen spec values without collapsing their JSON number spelling."""
    return equity_hash(asdict(specification))

@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """Execution semantics owned by the strategy.

    FROZEN_RULE capital mode ``target_equity_fraction`` uses decision scope and
    allocation_fraction=1. Each decision sizes the requested [0, 1] weight from
    cash plus actual holdings valued at the causal execution reference. Whole
    lots, cash including fees, and subsequent execution prices constrain the
    realized weight. It rebalances on every decision, unlike entry_cycle modes.
    """

    policy_type: str
    settings: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_type", _text(self.policy_type, "execution policy_type"))
        object.__setattr__(self, "settings", _json_mapping(self.settings, "execution settings"))
        canonical_sha256(self.settings)
        if "execution_trigger" in self.settings and (
                self.policy_type not in {"TARGET_POSITION", "FROZEN_RULE"}
                or self.settings["execution_trigger"] not in TARGET_TRIGGERS):
            raise RuntimeContractError("unsupported position execution trigger")
        if self.policy_type == "TARGET_POSITION":
            if set(self.settings) - {"capital_mode", "execution_trigger"}:
                raise RuntimeContractError("target-position policy contains unsupported fields")
            if self.settings.get("capital_mode", "target_equity_fraction") not in {
                    "target_equity_fraction", "full_available_cash", ENTRY_CASH_FRACTION}:
                raise RuntimeContractError("target-position policy requires a supported capital mode")
            if (self.settings.get("capital_mode") == ENTRY_CASH_FRACTION
                    and self.settings.get("execution_trigger") not in TARGET_TRIGGERS):
                raise RuntimeContractError("entry cash allocation requires target execution")
        if self.policy_type == "FROZEN_RULE":
            capital = self.settings.get("capital", {})
            if capital.get("mode") == "signal_cash_fraction":
                if capital.get("target_scope") != "entry_cycle" or "allocation_fraction" in capital:
                    raise RuntimeContractError(
                        "signal cash fraction requires entry_cycle scope and signal-owned fraction"
                    )
            if capital.get("mode") == "target_equity_fraction":
                if (capital.get("target_scope") != "decision"
                        or isinstance(capital.get("allocation_fraction"), bool)
                        or capital.get("allocation_fraction") != 1):
                    raise RuntimeContractError(
                        "equity target requires decision scope and allocation fraction one"
                    )

    def order_type_for(self, side: str) -> str:
        """Return the effective channel-neutral order type for one side."""

        if self.policy_type != "FROZEN_RULE":
            raise RuntimeContractError(
                "order_type_for is only defined for target-position policies"
            )
        normalized = side.upper()
        if normalized == "BUY":
            return str(dict(self.settings["entry"])["order_type"])
        if normalized != "SELL":
            raise RuntimeContractError(f"unsupported target order side: {side}")
        virtual_fill = dict(self.settings.get("virtual_fill", {}))
        if str(virtual_fill.get("sell", "")).lower() == "marketable_limit_at_open":
            return "MARKET"
        return str(dict(self.settings["exit"])["order_type"])
