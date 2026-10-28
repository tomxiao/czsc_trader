"""Explicit equity research contracts and causal bar decision planning."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from enum import StrEnum
from hashlib import sha256
import json
import math
import inspect
import marshal
from pathlib import Path
from typing import Callable

import pandas as pd
import numpy as np
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TimeInterval
from dataflows.equity_contracts import utc


class CashAvailabilityPolicy(StrEnum):
    IMMEDIATE_RESEARCH = "IMMEDIATE_RESEARCH"
    SETTLED_ONLY = "SETTLED_ONLY"


class ExecutionModel(StrEnum):
    BAR_RANGE = "BAR_RANGE_V1"


def _positive(value, name):
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")


def equity_hash(value):
    def default(item):
        if isinstance(item, (datetime, pd.Timestamp)):
            return utc(item.to_pydatetime() if isinstance(item, pd.Timestamp) else item).isoformat()
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, np.generic):
            return item.item()
        raise TypeError(f"unserializable equity identity {type(item)}")
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False, default=default).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CnEquitySpec:
    rule_version: str = "CN_EQUITY_V1"


@dataclass(frozen=True, slots=True)
class UsEquitySpec:
    rule_version: str = "US_EQUITY_V1"


@dataclass(frozen=True, slots=True)
class AccountPolicy:
    currency: str
    cash_availability: CashAvailabilityPolicy
    # Settled-only accounts require provider-declared settlement times per bar.
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
        return equity_hash(asdict(self))

    def require_instrument(self, instrument: InstrumentId):
        if type(instrument) is not InstrumentId or instrument.market is not self.market_id:
            raise ValueError("MARKET_CONTRACT_MISMATCH: candidate instrument")
        if instrument.asset_class not in (AssetClass.STOCK, AssetClass.ETF):
            raise ValueError("unsupported asset class")


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    observed_through: datetime
    decision_at: datetime
    execution_interval: TimeInterval

    def __post_init__(self):
        object.__setattr__(self, "observed_through", utc(self.observed_through))
        object.__setattr__(self, "decision_at", utc(self.decision_at))
        if type(self.execution_interval) is not TimeInterval:
            raise TypeError("decision requires an execution interval")
        if self.observed_through > self.decision_at or self.decision_at > self.execution_interval.start:
            raise ValueError("CAUSAL_TIME_VIOLATION")


@dataclass(frozen=True, slots=True)
class EquityPortfolio:
    cash: float
    quantity: int
    receivable: float
    revision: int
    cycle_entry: datetime | None = None
    cycle_cost: float = 0.
    feedback_source: str = "BAR_INTERVAL"
    reference_price_scale: float = 1.

    def __post_init__(self):
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < -1e-8 for v in (self.cash, self.receivable)):
            raise ValueError("invalid cash or receivable")
        if any(type(v) is not int or v < 0 for v in (self.quantity, self.revision)):
            raise ValueError("invalid quantity or portfolio revision")
        if type(self.cycle_cost) not in (float, int) or not math.isfinite(self.cycle_cost) or self.cycle_cost < 0:
            raise ValueError("invalid cycle cost")
        if self.cycle_entry is not None:
            object.__setattr__(self, "cycle_entry", utc(self.cycle_entry))
        _positive(self.reference_price_scale, "reference price scale")


def equity_implementation_hash(decide):
    """Bind the loaded function and its containing source file for research replay.

    Dependencies remain the research environment's responsibility; this identity
    is not a frozen release or an attestation of third-party libraries.
    """
    if not inspect.isfunction(decide) or decide.__closure__:
        raise TypeError("equity decisions require a module-level function without closure state")
    source = inspect.getsourcefile(decide)
    if source is None or not Path(source).is_file():
        raise ValueError("decision implementation requires a source file")
    return equity_hash({"source": sha256(Path(source).read_bytes()).hexdigest(),
                        "loaded_code": sha256(marshal.dumps(decide.__code__)).hexdigest(),
                        "defaults": decide.__defaults__, "keyword_defaults": decide.__kwdefaults__})


@dataclass(frozen=True, slots=True)
class EquityCandidate:
    """Content-bound research implementation. It is not a frozen/PTE release."""
    strategy_id: str
    candidate_id: str
    instrument: InstrumentId
    execution_spec_hash: str
    implementation_hash: str
    warmup_bars: int
    decide: Callable[[pd.DataFrame, EquityPortfolio], float]

    def __post_init__(self):
        import re
        if not re.fullmatch(r"S\d{3}", self.strategy_id) or not self.candidate_id.strip():
            raise ValueError("candidate identity is invalid")
        for value in (self.execution_spec_hash, self.implementation_hash):
            if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("candidate requires content and execution SHA-256 identities")
        if type(self.instrument) is not InstrumentId or type(self.warmup_bars) is not int or self.warmup_bars < 1 or not callable(self.decide):
            raise TypeError("candidate requires typed instrument, positive warmup and decision implementation")
        if self.implementation_hash != equity_implementation_hash(self.decide):
            raise ValueError("candidate implementation identity differs from loaded source")


@dataclass(frozen=True, slots=True)
class EquityPlan:
    plan_id: str
    point: DecisionPoint
    target: float
    quantity: int
    side: str
    limit_price: float | None
    portfolio_revision: int
    reference_price: float
    specification_hash: str
    explanation: dict | None = None

    def __post_init__(self):
        if type(self.point) is not DecisionPoint or self.target not in (0., 1.):
            raise ValueError("invalid decision point or target")
        if type(self.quantity) is not int or self.quantity < 0 or type(self.portfolio_revision) is not int or self.portfolio_revision < 0:
            raise ValueError("invalid plan quantity or revision")
        if self.side not in {"BUY", "SELL", "HOLD", "WAIT"} or ((self.side in {"BUY", "SELL"}) != (self.quantity > 0)):
            raise ValueError("plan side differs from quantity")
        if self.side == "BUY":
            _positive(self.limit_price, "buy limit")
        elif self.side == "SELL" and self.limit_price is not None:
            raise ValueError("sell must be a market order")
        _positive(self.reference_price, "reference price")


class EquityStrategyInstance:
    def __init__(self, candidate: EquityCandidate, specification: ResearchExecutionSpec):
        from .equity_definition import EquityStrategyCandidate
        if type(candidate) not in (EquityCandidate, EquityStrategyCandidate) or type(specification) is not ResearchExecutionSpec:
            raise TypeError("equity instance requires candidate and specification")
        specification.require_instrument(candidate.instrument)
        if candidate.execution_spec_hash != specification.fingerprint:
            raise ValueError("MARKET_CONTRACT_MISMATCH: candidate execution identity")
        self.candidate, self.specification = candidate, specification

    def run_window(self, bars, constraints, executor, *, start, end, fee_rate):
        """Plan at bar boundaries with only completed, published observations."""
        from .equity_definition import EquityStrategyCandidate
        if type(self.candidate) is EquityStrategyCandidate:
            self.candidate.verify()
        elif self.candidate.implementation_hash != equity_implementation_hash(self.candidate.decide):
            raise ValueError("candidate source changed since registration")
        starts = pd.to_datetime(bars.BarStart)
        ends = pd.to_datetime(bars.Date)
        available = pd.to_datetime(bars.AvailableDate) + pd.Timedelta(seconds=self.specification.data_latency_seconds)
        dated_constraints = {pd.Timestamp(row.Date): row for _, row in constraints.iterrows()}
        if not ends.is_monotonic_increasing or ends.duplicated().any():
            raise ValueError("bars must be unique and ordered")
        for index in range(len(bars)):
            bar = bars.iloc[index]
            if starts.iloc[index] < start or ends.iloc[index] > end:
                continue
            history = bars.loc[(ends <= starts.iloc[index]) & (available <= starts.iloc[index])]
            if len(history) < self.candidate.warmup_bars:
                raise ValueError("insufficient causal warmup at window start")
            constraint = dated_constraints.get(starts.iloc[index])
            if constraint is None or pd.Timestamp(constraint.AvailableDate) > starts.iloc[index]:
                raise ValueError("no dated trading constraints available at execution start")
            portfolio = (executor.snapshot_at(history.Date.iloc[-1], starts.iloc[index])
                         if type(self.candidate) is EquityStrategyCandidate else executor.snapshot())
            plan = self.plan(history, TimeInterval(starts.iloc[index].to_pydatetime(), ends.iloc[index].to_pydatetime()),
                             portfolio, fee_rate=fee_rate)
            executor.execute(plan, bar, constraint=constraint)
        return executor.finish()

    def plan(self, history: pd.DataFrame, interval: TimeInterval, portfolio: EquityPortfolio,
             *, fee_rate: float) -> EquityPlan:
        if len(history) < self.candidate.warmup_bars:
            raise ValueError("insufficient candidate warmup")
        available = pd.to_datetime(history.AvailableDate)
        last = history.iloc[-1]
        observed = pd.Timestamp(last.Date).to_pydatetime()
        decision = max(pd.Timestamp(available.max()).to_pydatetime(), observed) + timedelta(seconds=self.specification.data_latency_seconds)
        point = DecisionPoint(observed, decision, interval)
        if type(fee_rate) not in (int, float) or not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise ValueError("invalid fee rate")
        from .equity_definition import EquityStrategyCandidate, EquityDecisionContext
        explanation = None
        if type(self.candidate) is EquityStrategyCandidate:
            point = DecisionPoint(observed, interval.start, interval)
            feedback = portfolio if self.candidate.definition.feedback_mode == 'CONFIRMED_EXECUTION' else None
            result = self.candidate.decide(EquityDecisionContext(history.copy(deep=True), feedback, point,
                                                                self.candidate.definition.parameters))
            target, explanation = result.target, result.explanation.to_dict()
        else:
            target = self.candidate.decide(history.copy(deep=True), portfolio)
        if type(target) not in (float, int) or target not in (0, 1):
            raise ValueError("equity candidate must return a finite binary long-only target")
        reference = float(last.Close) * portfolio.reference_price_scale
        _positive(reference, "reference")
        side, quantity, limit = "HOLD", 0, None
        if target == 1 and portfolio.quantity == 0:
            tick = Decimal(str(self.specification.price_tick))
            limit = float((Decimal(str(reference)) * (1 + Decimal(str(self.specification.buy_premium)))
                           / tick).to_integral_value(rounding=ROUND_FLOOR) * tick)
            _positive(limit, "limit")
            step = self.specification.quantity_step
            quantity = int(Decimal(str(portfolio.cash)) / (Decimal(str(limit)) * (1 + Decimal(str(fee_rate))) * step)) * step
            side = "BUY" if quantity else "WAIT"
        elif target == 0 and portfolio.quantity:
            side, quantity = "SELL", portfolio.quantity
        payload = {"candidate": self.candidate.candidate_id,
                   "implementation": self.candidate.implementation_hash,
                   "specification": self.specification.fingerprint,
                   "point": asdict(point), "target": target, "quantity": quantity,
                   "side": side, "limit": limit, "revision": portfolio.revision,
                   "reference": reference, "fee_rate": fee_rate}
        if explanation is not None:
            payload["explanation"] = explanation
        return EquityPlan(equity_hash(payload), point, float(target), quantity, side, limit,
                          portfolio.revision, reference, self.specification.fingerprint, explanation)
