"""Independent price-event state and general S013 native-account audit."""

import numpy as np
import pandas as pd
from czsc_trader.research_tools import build_assessment_evidence
from czsc_trader.research_tools.evaluation import (
    serialize_evaluation_evidence,
    validate_evaluation_evidence,
)
from strategy_runtime import canonical_sha256


def independent_history(daily, sessions, lookback=20, distance=1.0):
    axis = pd.DatetimeIndex(pd.to_datetime(daily.Date)).normalize()
    if not axis.is_unique or not axis.is_monotonic_increasing:
        raise ValueError("ordered unique daily dates required")
    price = daily.Close.to_numpy(float)
    if not np.isfinite(price).all() or not (price > 0).all():
        raise ValueError("positive finite Close required")
    locs = axis.get_indexer(sessions)
    if (locs < 0).any() or not np.array_equal(locs, np.arange(locs[0], locs[-1] + 1)):
        raise ValueError("complete signal prefix required")
    state, peak, trough, sigma0 = "FLAT", float(price[locs[0]]), None, None
    rows = []
    for pos in locs:
        current = float(price[pos])
        returns = (
            [
                float(np.log(price[j]) - np.log(price[j - 1]))
                for j in range(pos - lookback + 1, pos + 1)
            ]
            if pos >= lookback
            else []
        )
        sigma = float(np.std(returns, ddof=0)) if returns else np.nan
        available = bool(np.isfinite(sigma) and sigma > 0)
        before = state
        if state == "FLAT":
            peak = max(peak, current)
            if not available:
                reason = "FLAT_VOL_UNAVAILABLE"
            elif np.log(peak) - np.log(current) >= 2 * distance * sigma:
                state, trough, sigma0, reason = "ARMED", current, sigma, "ARM_PRICE_EXCURSION"
            else:
                reason = "TRACK_FLAT_PEAK"
        elif state == "ARMED":
            trough = min(trough, current)
            if np.log(current) - np.log(trough) >= distance * sigma0:
                state, peak, trough, reason = "HELD", current, None, "BUY_PRICE_REVERSAL"
            else:
                reason = "WAIT_PRICE_REVERSAL"
        else:
            peak = max(peak, current)
            if np.log(peak) - np.log(current) >= distance * sigma0:
                state, peak, trough, sigma0, reason = (
                    "FLAT",
                    current,
                    None,
                    None,
                    "SELL_PRICE_RETRACE",
                )
            else:
                reason = "CONTINUE_PRICE_CYCLE"
        rows.append(
            {
                "state_before": before,
                "state_after": state,
                "signal_reason": reason,
                "target_position": int(state == "HELD"),
                "close": current,
                "sigma_current": sigma,
                "sigma_available": available,
                "sigma_locked": sigma0 if sigma0 is not None else np.nan,
                "known_peak": peak,
                "known_trough": trough if trough is not None else np.nan,
            }
        )
    return pd.DataFrame(rows, index=sessions)


def compare_history(native, expected):
    for name in (
        "state_before",
        "state_after",
        "signal_reason",
        "target_position",
        "sigma_available",
    ):
        if not np.array_equal(native[name].to_numpy(), expected[name].to_numpy()):
            raise ValueError("independent state mismatch: " + name)
    for name in ("close", "sigma_current", "sigma_locked", "known_peak", "known_trough"):
        # SRT omits NaN evidence. An entirely unavailable optional diagnostic may
        # therefore have no native column, which must match all-NaN expectation.
        if name not in native:
            if not expected[name].isna().all():
                raise ValueError("required native causal feature absent: " + name)
            actual = np.full(len(native), np.nan)
        else:
            actual = pd.to_numeric(native[name], errors="raise").to_numpy(float)
        if not np.allclose(
            actual, expected[name].to_numpy(float), rtol=1e-11, atol=1e-12, equal_nan=True
        ):
            raise ValueError("independent causal feature mismatch: " + name)


def audit(ctx, bound, result, formal, daily, helpers):
    validate_evaluation_evidence(formal)
    if serialize_evaluation_evidence(bound, result) != formal:
        raise ValueError("serialized public native pair mismatch")
    if len(result.runs) != 1 or bound.execution_mode != "FULL" or bound.workers != 1:
        raise ValueError("one full centre required")
    if (
        bound.initial_cash != 1_000_000
        or bound.price_basis.value != "HFQ_RESEARCH"
        or len(bound.costs) != 1
        or bound.costs[0].one_way_cost != 0.001
        or bound.benchmark.execution.premium != 0.01
    ):
        raise ValueError("original economics/execution contract required")
    identity = ctx.runtime.identify(bound.strategy, dependencies=bound.dependencies)
    if (
        identity.content_sha256 != result.runs[0].identity.content_sha256
        or result.data_identity != bound.execution_data.fingerprint
        or result.runtime_binding_hash != canonical_sha256(bound.runtime_binding)
    ):
        raise ValueError("native identity mismatch")
    decisions = result.runs[0].execution.decisions
    signals = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).normalize()
    execution = pd.DatetimeIndex(pd.to_datetime(decisions.valid_session)).normalize()
    if (
        len(signals) != 1636
        or signals[0] != pd.Timestamp("2019-12-31")
        or signals[-1] != pd.Timestamp("2026-09-29")
        or execution[0] != pd.Timestamp("2020-01-02")
        or execution[-1] != pd.Timestamp("2026-09-30")
    ):
        raise ValueError("original native decision/execution endpoints required")
    binding = bound.input_bindings["full"]
    expected_signal = pd.DatetimeIndex(
        pd.to_datetime([binding.plan.signal_dates[x.date()] for x in execution])
    ).normalize()
    pd.testing.assert_index_equal(signals, expected_signal, check_names=False, exact=False)
    expected = independent_history(daily, signals, **bound.strategy.payload["parameters"])
    compare_history(decisions.set_index(signals), expected)
    facts = build_assessment_evidence(bound, result)
    economics = helpers["economics_reference"].economics(facts[0])
    account = helpers["account_reference"].verify_account(bound, result)
    links = helpers["execution_links"].verify(bound, result)
    for year, row in account["annual"].items():
        if abs(row["net_return"] - economics["annual"][year]["return"]) > 1e-12:
            raise ValueError("independent annual accounting mismatch")
    account_daily = result.runs[0].execution.account_daily
    if (
        not np.isfinite(account_daily.equity).all()
        or (account_daily.quantity < 0).any()
        or (account_daily.cash < -1e-6).any()
    ):
        raise ValueError("finite long-only unlevered account required")
    return {
        "status": "PASS",
        "independent_signal_state": "EXACT",
        "signal_days": 1636,
        "effective_parameters": 2,
        "economics": economics,
        "cash_account": account,
        "orders_first_touch": links,
        "qualified": economics["qualified"],
        "stop": "CENTRE_FAIL_STOP_32_FEE"
        if not economics["qualified"]
        else "CENTRE_PASS_WAIT_ROOT_32_FEE_AUTHORITY",
        "new_accounts": 1,
        "technical_financial_repeats": 0,
        "signal_vs_actual": "Binary policy intent is not filled holdings or actual closed-trade frequency",
        "limitations": "Reuse original anomalous OHLC input unchanged; native intraday first touch audited, no repair. SRT serializes pd.Timestamp history evidence as date, so T17 is policy/source availability metadata, not that serialized field's clock.",
    }
