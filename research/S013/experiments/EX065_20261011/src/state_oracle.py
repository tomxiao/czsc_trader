"""Independent signal-state oracle; no runtime, orders, accounts or market readers."""
from dataclasses import dataclass
from enum import Enum
from math import isfinite


class Policy(Enum):
    ORIGINAL = "original"
    LOCK = "entry_route_no_regime_exit"
    CURRENT = "current_route_no_regime_exit"
    GAP = "original_plus_lowest_priority_gap_repair_exit"


@dataclass(frozen=True, slots=True)
class Rule:
    entry: float
    exit: float
    hold: int
    acf_min: float | None
    momentum_min: float | None = None
    loss: float | None = None
    trailing: float | None = None

    def __post_init__(self):
        if not (isfinite(self.entry) and isfinite(self.exit) and 0 <= self.entry < self.exit <= 1):
            raise ValueError("ordered range thresholds required")
        if type(self.hold) is not int or not 1 <= self.hold <= 60:
            raise ValueError("integer holding limit1..60 required")
        for value in (self.acf_min, self.momentum_min, self.loss, self.trailing):
            if value is not None and not isfinite(value):
                raise ValueError("finite optional rule values required")
        for value in (self.loss, self.trailing):
            if value is not None and not 0 < value < 0.5:
                raise ValueError("stop fractions must be0..0.5 strict")


@dataclass(frozen=True, slots=True)
class State:
    entry_route: str | None = None
    age: int = 0
    anchor: float = 0.0
    peak: float = 0.0
    last_reason: str | None = None
    last_route: str | None = None
    category: str | None = None

    def __post_init__(self):
        if self.entry_route not in (None, "bull", "bear"):
            raise ValueError("entry route invalid")
        if type(self.age) is not int or self.age < 0 or (self.entry_route is None and self.age != 0):
            raise ValueError("held age nonnegative; flat age canonical zero")
        if not (isfinite(self.anchor) and isfinite(self.peak) and 0 <= self.anchor <= self.peak):
            raise ValueError("finite nonnegative signal anchor/peak required")
        if self.entry_route is not None and self.anchor <= 0:
            raise ValueError("held anchor must be positive")
        if self.last_reason not in (None, "loss", "trailing", "range", "time", "regime", "gap_repair_exit"):
            raise ValueError("final exit reason invalid")
        if self.last_route not in (None, "bull", "bear") or ((self.last_reason is None) != (self.last_route is None)):
            raise ValueError("exit reason and origin route must coexist")
        if self.last_reason == "time" and self.last_route == "bear":
            if self.category not in ("BELOW", "EQUAL", "ABOVE"):
                raise ValueError("bear TIME requires strict anchor category")
        elif self.category is not None:
            raise ValueError("category only belongs to bear-origin final TIME")
        if self.entry_route is not None and self.last_reason is not None:
            raise ValueError("signal entry consumes prior exit context")


@dataclass(frozen=True, slots=True)
class Feature:
    raw: str
    previous_raw: str
    close: float
    open: float
    bull_position: float
    bear_position: float
    acf: float
    momentum: float
    score: float
    previous_close: float

    def __post_init__(self):
        if self.raw not in ("bull", "bear") or self.previous_raw not in ("bull", "bear"):
            raise ValueError("complete current and previous raw routes required")
        values = (self.close, self.open, self.bull_position, self.bear_position,
                  self.acf, self.momentum, self.score, self.previous_close)
        if not all(isfinite(value) for value in values) or self.close <= 0 or self.open <= 0 or self.previous_close <= 0:
            raise ValueError("finite features and positive signal prices required")


@dataclass(frozen=True, slots=True)
class Decision:
    target: int
    reason: str
    next_state: State
    management_route: str
    opportunity: bool
    score_pass: bool
    recovered: bool


def step(policy: Policy, state: State, feature: Feature, bull: Rule, bear: Rule,
         score_threshold: float) -> Decision:
    if type(policy) is not Policy or not isfinite(score_threshold):
        raise ValueError("explicit policy and finite score threshold required")
    held = state.entry_route is not None
    manager = feature.raw if policy is Policy.CURRENT or not held else state.entry_route
    rule = bull if manager == "bull" else bear
    position = feature.bull_position if manager == "bull" else feature.bear_position
    body_up = feature.close > feature.open
    acf_ok = rule.acf_min is None or feature.acf >= rule.acf_min
    range_ok = position <= rule.entry
    momentum_ok = rule.momentum_min is None or feature.momentum >= rule.momentum_min
    recovery = (not held and feature.raw == "bear" and state.last_reason == "time"
                and state.last_route == "bear" and state.category == "BELOW" and body_up)
    eligible = range_ok and momentum_ok and (acf_ok or recovery)
    opportunity = not held and eligible
    passed = feature.score >= score_threshold
    recovered = range_ok and momentum_ok and not acf_ok and recovery
    if held:
        elapsed, peak = state.age + 1, max(state.peak, feature.close)
        predicates = (
            ("loss", rule.loss is not None and feature.close / state.anchor - 1 <= -rule.loss),
            ("trailing", rule.trailing is not None and feature.close / peak - 1 <= -rule.trailing),
            ("range", position >= rule.exit),
            ("time", elapsed >= rule.hold),
            ("regime", policy in (Policy.ORIGINAL, Policy.GAP) and feature.raw != state.entry_route),
        )
        reason = next((name for name, condition in predicates if condition), "hold")
        if reason == "hold" and policy is Policy.GAP and feature.open < feature.previous_close and feature.close > feature.open:
            reason = "gap_repair_exit"
        if reason == "hold":
            after = State(state.entry_route, elapsed, state.anchor, peak)
        else:
            category = None
            if reason == "time" and state.entry_route == "bear":
                category = ("BELOW" if feature.close < state.anchor else
                            "ABOVE" if feature.close > state.anchor else "EQUAL")
            after = State(None, 0, state.anchor, peak, reason, state.entry_route, category)
    elif not eligible:
        reason, after = "flat", state
    elif feature.raw == "bull" and feature.previous_raw == "bear" and not body_up:
        reason, after = "entry_direction_rejected", state
    elif not passed:
        reason, after = "confirmation_rejected", state
    else:
        reason = "entry"
        after = State(feature.raw, 0, feature.close, feature.close)
    return Decision(int(after.entry_route is not None), reason, after, manager,
                    opportunity, passed, recovered)
