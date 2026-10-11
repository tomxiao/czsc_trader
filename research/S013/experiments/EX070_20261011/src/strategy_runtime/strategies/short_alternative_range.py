"""Fixed original C8880 with causal four-session alternative buy confirmation."""

import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from .reentry_confirmed_range import ReentryConfirmedRange
from .confirmed_range import PROFILES, confirmation_features
from .range_reversion import components



def short_confirmation(close, lookback):
    """No epsilon: unavailable/zero volatility cannot offer an alternative."""
    if type(lookback) is not int or not 1 <= lookback <= 20:
        raise ValueError("short confirmation integer lookback1..20 required")
    volatility = close.pct_change(fill_method=None).rolling(20,min_periods=20).std(ddof=1)
    prior = close.shift(lookback)
    defined = prior.notna() & volatility.notna() & volatility.gt(0)
    value = pd.Series(np.nan,index=close.index,dtype=float)
    value.loc[defined] = (np.log(close.loc[defined])-np.log(prior.loc[defined])) / (volatility.loc[defined]*np.sqrt(lookback))
    passed = defined & value.le(0)
    reason = pd.Series("COMPLETE",index=close.index,dtype=object)
    reason.loc[volatility.eq(0)]="ZERO_VOLATILITY"
    reason.loc[prior.isna() | volatility.isna()]="INCOMPLETE_HISTORY"
    return value,passed.astype(bool),reason

class ShortAlternativeRange(ReentryConfirmedRange):
    def __init__(self, parameters):
        p = parameters.values
        if p.get("mechanism") != "RAW_BULL_BOUNDARY_BODY_BEAR_BELOW_BODY_ACF_RECOVERY_SHORT_ALT":
            raise ValueError(
                "explicit bull boundary body and bear BELOW body ACF recovery mechanism required"
            )
        if p.get("confirmation", {}).get("enabled") is not True:
            raise ValueError("original buy confirmation must remain enabled")
        lookback = p.get("short_confirmation_lookback4")
        if type(lookback) is not int or not 1 <= lookback <= 20:
            raise ValueError("short confirmation lookback integer1..20 required")
        super().__init__(
            ParameterSet({key: value for key, value in p.items() if key not in ("mechanism", "short_confirmation_lookback4")})
        )
        self._parameters = parameters
        self._warmup = max(self._warmup, p["regime_window"] + 2, 21, lookback + 1)

    def calculate_history(self, inputs, sessions):
        p = self._parameters.values
        c, settings = p["confirmation"], p["context"]
        daily = inputs["daily"]
        if not {"Date", "Open", "Close"}.issubset(daily.columns):
            raise ValueError("complete signal Date/Open/Close required")
        prices = daily.loc[:, ["Open", "Close"]].to_numpy(dtype=float)
        if not np.isfinite(prices).all() or (prices <= 0).any():
            raise ValueError("signal Open/Close must be finite and positive")
        all_features = {
            key: components(inputs["daily"], p[key]["range_window"]) for key in ("bull", "bear")
        }
        raw_bear_acf = all_features["bear"].acf1
        features = {key: frame.reindex(sessions) for key, frame in all_features.items()}
        if not all(np.isfinite(frame.to_numpy()).all() for frame in features.values()):
            raise ValueError("required causal route features missing")
        score_bars = inputs["daily"].copy()
        if settings["volume_basis"] == "RAW":
            raw = inputs["execution"].copy()
            raw.index = pd.DatetimeIndex(pd.to_datetime(raw.Date)).normalize()
            score_bars.index = pd.DatetimeIndex(pd.to_datetime(score_bars.Date)).normalize()
            if (
                not raw.index.is_unique
                or not raw.index.is_monotonic_increasing
                or not raw.index.isin(score_bars.index).all()
            ):
                raise ValueError(
                    "raw volume dates must be unique, ordered and share the adjusted calendar"
                )
            adjusted = score_bars.loc[raw.index]
            reconstructed = adjusted.Volume * adjusted.Close / raw.Close
            if not np.allclose(
                reconstructed.to_numpy(), raw.Volume.to_numpy(), rtol=1e-12, atol=1e-6
            ):
                raise ValueError("per-date raw/HFQ volume conversion differs")
            if not np.allclose(
                adjusted.Amount.to_numpy(), raw.Amount.to_numpy(), rtol=1e-12, atol=1e-6
            ):
                raise ValueError("amount must be invariant across price-unit conversion")
            score_bars = adjusted.assign(Volume=raw.Volume)
        _, normalized = confirmation_features(score_bars, all_features["bull"].acf1, c["lookback"])
        normalized = normalized.reindex(sessions)
        if not np.isfinite(normalized.to_numpy()).all():
            raise ValueError("complete causal confirmation history missing")
        score = (
            0.5 * normalized.acf + 0.25 * normalized.turnover + 0.25 * normalized.volume
            if settings["weighting"] == "EQUAL_BLOCKS"
            else normalized.loc[:, list(PROFILES[c["profile"]])].mean(axis=1)
        ) * c["orientation"]
        bars = inputs["daily"].copy()
        bars.index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        close = bars.Close.astype(float)
        signal_close = close.reindex(sessions)
        signal_open = bars.Open.astype(float).reindex(sessions)
        previous_close = close.shift(1).reindex(sessions)
        if not np.isfinite(np.column_stack((signal_close, signal_open, previous_close))).all():
            raise ValueError("complete current and previous signal prices required")
        short_value, short_pass, short_reason = short_confirmation(close, p["short_confirmation_lookback4"])
        short_value = short_value.reindex(sessions)
        short_pass = short_pass.reindex(sessions)
        short_reason = short_reason.reindex(sessions)
        direction = (signal_close > signal_open).to_numpy()
        all_momentum = close / close.shift(p["regime_window"]) - 1
        momentum = all_momentum.reindex(sessions)
        previous_momentum = all_momentum.shift(1).reindex(sessions)
        if not (
            np.isfinite(momentum.to_numpy()).all()
            and np.isfinite(previous_momentum.to_numpy()).all()
        ):
            raise ValueError("required current and previous causal regime features missing")
        regimes = np.where(momentum.to_numpy() >= p["regime_threshold"], "bull", "bear")
        previous_regimes = np.where(
            previous_momentum.to_numpy() >= p["regime_threshold"], "bull", "bear"
        )
        holding = False
        active_route = None
        last_exit_reason = None
        last_exit_route = None
        last_exit_category = None
        age = 0
        anchor = peak = 0.0
        targets, reasons, positions, opportunities, passes, contexts = [], [], [], [], [], []
        entry_acf_values, entry_acf_passes, direction_gate_applies = [], [], []
        recovery_flags, eligibility_flags = [], []
        alternative_opportunities, alternative_entries, entry_origins = [], [], []
        previous_exit_reasons, previous_exit_routes, previous_exit_categories = [], [], []
        for i, regime in enumerate(regimes):
            previous_exit_reasons.append(last_exit_reason)
            previous_exit_routes.append(last_exit_route)
            previous_exit_categories.append(last_exit_category)
            route = active_route if holding else regime
            rp = p[route]
            row = features[route].iloc[i]
            positions.append(row.range_position)
            entry_acf = row.acf1
            acf_pass = rp["acf_min"] is None or entry_acf >= rp["acf_min"]
            entry_acf_values.append(entry_acf)
            entry_acf_passes.append(acf_pass)
            range_pass = row.range_position <= rp["entry"]
            momentum_pass = rp["momentum_min"] is None or row.momentum20 >= rp["momentum_min"]
            recovery_context = (
                not holding
                and regime == "bear"
                and last_exit_reason == "time"
                and last_exit_route == "bear"
                and last_exit_category == "BELOW"
                and direction[i]
            )
            recovered = range_pass and momentum_pass and not acf_pass and recovery_context
            eligible = range_pass and momentum_pass and (acf_pass or recovery_context)
            recovery_flags.append(bool(recovered))
            eligibility_flags.append(bool(eligible))
            applies = c["scope"] in ("both", regime) and (
                settings["entry_gate"] == "all" or last_exit_reason == "regime"
            )
            opportunity = not holding and eligible
            # Original bear eligibility recovery is unchanged; only new raw-bull entry is gated.
            boundary_gate = regime == "bull" and previous_regimes[i] == "bear"
            direction_gate_applies.append(bool(boundary_gate))
            passed = not applies or score.iloc[i] >= c["threshold"]
            opportunities.append(opportunity)
            passes.append(passed)
            contexts.append(last_exit_reason or "initial")
            alternative = bool(short_pass.iloc[i])
            alt_only = opportunity and not passed and alternative
            alternative_opportunities.append(alt_only)
            entered_by_alt = False
            entry_origin = "NONE"
            reason = "flat"
            if holding:
                age += 1
                peak = max(peak, row.close)
                loss = rp["stop_loss"] is not None and row.close / anchor - 1 <= -rp["stop_loss"]
                trail = (
                    rp["trailing_stop"] is not None and row.close / peak - 1 <= -rp["trailing_stop"]
                )
                changed = p["exit_on_regime_change"] and regime != active_route
                if (
                    loss
                    or trail
                    or row.range_position >= rp["exit"]
                    or age >= rp["max_hold"]
                    or changed
                ):
                    holding = False
                    reason = (
                        "loss"
                        if loss
                        else "trailing"
                        if trail
                        else "range"
                        if row.range_position >= rp["exit"]
                        else "time"
                        if age >= rp["max_hold"]
                        else "regime"
                    )
                    last_exit_reason = reason
                    last_exit_route = active_route
                    # Classify only the final bear TIME exit against this signal episode's anchor.
                    last_exit_category = (
                        (
                            "BELOW"
                            if row.close < anchor
                            else "ABOVE"
                            if row.close > anchor
                            else "EQUAL"
                        )
                        if reason == "time" and active_route == "bear"
                        else None
                    )
                    active_route = None
                else:
                    reason = "hold"
            elif eligible:
                if boundary_gate and not direction[i]:
                    reason = "entry_direction_rejected"
                elif passed or alternative:
                    holding = True
                    active_route = regime
                    age = 0
                    anchor = peak = row.close
                    last_exit_reason = None
                    last_exit_route = None
                    last_exit_category = None
                    reason = "entry"
                    entered_by_alt = not passed
                    entry_origin = "ORIGINAL_CONFIRMATION" if passed else "SHORT_ALTERNATIVE"
                else:
                    reason = "confirmation_rejected"
            targets.append(float(holding))
            reasons.append(reason)
            alternative_entries.append(entered_by_alt)
            entry_origins.append(entry_origin)
        history = features["bull"].assign(
            range_position=positions,
            target_position=targets,
            signal_reason=reasons,
            regime=regimes,
            regime_momentum=momentum,
            previous_regime=previous_regimes,
            previous_regime_momentum=previous_momentum,
            entry_direction_gate_applies=direction_gate_applies,
            entry_direction_up=direction,
            previous_signal_close=previous_close,
            entry_signal_close=signal_close,
            entry_signal_open=signal_open,
            bull_range_position=features["bull"].range_position,
            bear_range_position=features["bear"].range_position,
            confirmation_score=score,
            confirmation_acf=normalized.acf,
            confirmation_turnover=normalized.turnover,
            confirmation_volume=normalized.volume,
            confirmation_opportunity=opportunities,
            confirmation_pass=passes,
            confirmation_exit_context=contexts,
            last_exit_reason=pd.Series(previous_exit_reasons, index=sessions, dtype=object),
            last_exit_route=pd.Series(previous_exit_routes, index=sessions, dtype=object),
            last_exit_category=pd.Series(previous_exit_categories, index=sessions, dtype=object),
            bear_acf_raw=raw_bear_acf.reindex(sessions),
            entry_acf_value=entry_acf_values,
            entry_acf_pass=entry_acf_passes,
            entry_acf_recovery_applies=recovery_flags,
            entry_eligible=eligibility_flags,
            original_pass=passes,
            short_alt_pass=short_pass,
            short_stretch4=short_value,
            short_stretch_reason=short_reason,
            alt_only_opportunity=alternative_opportunities,
            alt_only_entry=alternative_entries,
            entry_confirmation_origin=entry_origins,
        )
        return history
