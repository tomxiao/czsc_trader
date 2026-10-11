"""Independent full-state audit consuming independently certified OHLC features."""
from __future__ import annotations
from dataclasses import dataclass
import math
import re
from typing import Mapping
import pandas as pd
from state_oracle import Feature, Policy, Rule, State, step
ORIGINAL = "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY"
GAP = ORIGINAL + "_GAP_REPAIR_EXIT"
def plain(value):
    import json
    return json.loads(json.dumps(value, default=dict, allow_nan=False))
@dataclass(frozen=True, slots=True)
class FeatureCertificate:
    independent_source_sha256: str
    formal_input_sha256: str
    source_and_all_13_formulas_verified: bool
    calendar_and_execution_mapping_verified: bool

    def __post_init__(self):
        for digest in (self.independent_source_sha256, self.formal_input_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("exact source/input hashes required")
        if self.source_and_all_13_formulas_verified is not True or self.calendar_and_execution_mapping_verified is not True:
            raise ValueError("independent feature/calendar adapter must finish before native acceptance")


def nullable(value, allowed):
    """Storage-null canonicalization only for validated exit/context strings."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("invalid non-null context metadata")
    return value


def policy_for(parameters):
    flag, mechanism = parameters["exit_on_regime_change"], parameters["mechanism"]
    if type(flag) is not bool:
        raise ValueError("explicit boolean independent regime exit contract")
    if mechanism == GAP and flag is True:
        return Policy.GAP
    if mechanism == ORIGINAL and flag is True:
        return Policy.ORIGINAL
    raise ValueError("unknown fixed policy or stale true current regime flag")


def rules(parameters):
    c, context = parameters["confirmation"], parameters["context"]
    if (c["enabled"] is not True or c["scope"] != "both" or c["orientation"] != 1
            or context != {"entry_gate": "all", "volume_basis": "ADJUSTED", "weighting": "EQUAL_BLOCKS"}
            or any(parameters[key]["cooldown"] != 0 for key in ("bull", "bear"))):
        raise ValueError("oracle supports only the fixed original C8880 contract")
    def one(p):
        return Rule(p["entry"], p["exit"], p["max_hold"], p["acf_min"], p["momentum_min"],
                    p["stop_loss"], p["trailing_stop"])
    return one(parameters["bull"]), one(parameters["bear"]), c["threshold"]


def audit_signal_rows(parameters, rows: tuple[Mapping, ...], features: tuple[Feature, ...],
                      certificate: FeatureCertificate):
    """Independent state oracle on independently certified feature values, not old exit assertions."""
    if type(certificate) is not FeatureCertificate or len(rows) != len(features) or not rows:
        raise ValueError("complete independently certified native rows/features required")
    p = plain(parameters)
    policy = policy_for(p)
    bull, bear, threshold = rules(p)
    state = State()
    previous_signal, previous_execution = None, None
    for row, feature in zip(rows, features, strict=True):
        if type(feature) is not Feature:
            raise TypeError("independent strongly typed feature required")
        signal_date, execution_date = pd.Timestamp(row["signal_date"]), pd.Timestamp(row["execution_date"])
        if (pd.isna(signal_date) or pd.isna(execution_date) or execution_date <= signal_date
                or (previous_signal is not None and signal_date <= previous_signal)
                or (previous_execution is not None and execution_date <= previous_execution)):
            raise ValueError("exact ordered actual calendar mapping required, never fabricate T+1")
        previous_signal, previous_execution = signal_date, execution_date
        decision = step(policy, state, feature, bull, bear, threshold)
        expected = {"target_position": float(decision.target), "signal_reason": decision.reason,
                    "confirmation_opportunity": decision.opportunity, "confirmation_pass": decision.score_pass,
                    "entry_acf_recovery_applies": decision.recovered}
        if policy is Policy.GAP:
            expected["gap_repair_exit_trigger"] = decision.reason == "gap_repair_exit"
        for key, value in expected.items():
            if row[key] != value:
                raise ValueError("independent full-policy transition mismatch: " + key)
        for key, allowed, value in (
            ("last_exit_reason", {"loss", "trailing", "range", "time", "regime", "gap_repair_exit"}, state.last_reason),
            ("last_exit_route", {"bull", "bear"}, state.last_route),
            ("last_exit_category", {"BELOW", "EQUAL", "ABOVE"}, state.category),
        ):
            if nullable(row[key], allowed) != value:
                raise ValueError("before-decision memory mismatch: " + key)
        if policy is Policy.CURRENT:
            before, after = state, decision.next_state
            expected_extra = {"entry_route_before": before.entry_route, "entry_route_after": after.entry_route,
                "management_route": decision.management_route, "holding_age_before": before.age,
                "holding_age_after": after.age, "entry_anchor_signal_close": after.anchor,
                "holding_peak_signal_close": after.peak}
            for key, value in expected_extra.items():
                actual = nullable(row[key], {"bull", "bear"}) if key.startswith("entry_route_") else row[key]
                if actual != value or (isinstance(actual, (float, int)) and not math.isfinite(actual)):
                    raise ValueError("current management/origin/clock mismatch: " + key)
        state = decision.next_state
    return {"status": "PASS", "policy": policy.value, "signal_days": len(rows),
            "scope": "complete before/after signal state given separately authenticated features",
            "new_account_evaluations": 0}


