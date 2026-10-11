"""Pure fixed original-input assembly; no provider, account execution or I/O."""

import numpy as np
import pandas as pd

import component
import curvature_statistics as statistics
import labels as label_formula

PRICE_COLUMNS = ("open", "high", "low", "close", "vol", "amount")


def exact_datetime(values):
    """Only lossless datetime-unit normalization; never normalize time-of-day."""
    index = pd.DatetimeIndex(values)
    if index.tz is not None or index.hasnans:
        raise ValueError("finite timezone-naive datetime values required")
    unit = index.unit
    result = index.as_unit("ns")
    pd.testing.assert_index_equal(result.as_unit(unit), index, exact=True)
    if result.tolist() != index.tolist():
        raise ValueError("datetime values changed")
    if result.has_duplicates or not result.is_monotonic_increasing or not result.equals(result.normalize()):
        raise ValueError("unique ordered full-session midnight axis required")
    return result


def construct(old66, old61, old69, warm69, public_prices, old_labels, native_daily,
              sessions, decisions, pricing):
    """Fixed S013 schema. Caller authenticates all immutable file/native identities."""
    if pricing != {"basis": "HFQ_RESEARCH", "quantity_unit": "RESEARCH_UNIT",
                   "anchor_date": "2019-12-31", "anchor_factor": 0.2803}:
        raise ValueError("original complete HFQ pricing identity required")
    sessions = exact_datetime(sessions)
    grid = exact_datetime(old66.index)
    if (len(sessions) != 1636 or sessions[0] != pd.Timestamp("2020-01-02")
            or sessions[-1] != pd.Timestamp("2026-09-30") or len(grid) != 1635
            or not grid.equals(sessions[:-1])):
        raise ValueError("exact original1636 sessions/1635 signal grid required")
    for frame in (old61, old69, old_labels):
        pd.testing.assert_index_equal(exact_datetime(frame.index), grid, check_names=False)
    for name in statistics.CONTROLS[:14]:
        for frame in (old61, old69):
            pd.testing.assert_series_equal(old66[name], frame[name], check_exact=True, check_names=False)
    for name in statistics.CONTROLS[14:16]:
        pd.testing.assert_series_equal(old61[name], old69[name], check_exact=True, check_names=False)
    pd.testing.assert_series_equal(-old66.late_weakness, old61.late_recovery,
                                   check_exact=True, check_names=False)
    pd.testing.assert_series_equal(-old66.early_reclaim_weakness, old61.early_volume_reclaim,
                                   check_exact=True, check_names=False)
    if list(native_daily.columns) != ["dt", *PRICE_COLUMNS]:
        raise ValueError("exact complete original native daily schema required")
    native = native_daily.copy()
    native.index = exact_datetime(native.pop("dt"))
    native.index.name = "signal_date"
    native.attrs = {}
    full_axis = pd.DatetimeIndex([pd.Timestamp("2019-12-31")]).append(sessions)
    if not native.index.equals(full_axis):
        raise ValueError("native anchor plus full1636 execution calendar required")
    if list(public_prices.columns) != list(PRICE_COLUMNS):
        raise ValueError("all original price/volume/amount columns must be retained")
    pd.testing.assert_frame_equal(public_prices, native, check_exact=True)
    if not np.isfinite(native.to_numpy()).all() or not (native[["open", "high", "low", "close"]] > 0).all().all():
        raise ValueError("finite complete native observations and positive prices required")
    if (list(warm69.columns) != ["Open", "Close"] or warm69.index[0] != pd.Timestamp("2019-04-10")
            or warm69.index[-1] != grid[-1]):
        raise ValueError("original2019 HFQ warmup through original last signal required")
    exact_datetime(warm69.index)
    overlap = native.index.intersection(warm69.index)
    # Same authenticated original anchor arithmetic as EX069; never change source units.
    np.testing.assert_allclose(warm69.loc[overlap].to_numpy() / 0.2803,
                               native.loc[overlap, ["open", "close"]].to_numpy(),
                               rtol=1e-13, atol=1e-13)
    observations = component.build_features(warm69).reindex(grid)
    pd.testing.assert_series_equal(observations.volatility20, old66.volatility20,
                                   check_exact=True, check_names=False)
    pd.testing.assert_series_equal(observations.short_stretch4, old69.short_stretch4,
                                   check_exact=True, check_names=False)
    features = old66[list(statistics.CONTROLS[:14])].join(old61[list(statistics.CONTROLS[14:16])])
    features = features.join(old69[["short_stretch4"]]).join(observations[["curvature4"]])
    prices = native.rename(columns={"open": "Open", "close": "Close"})[["Open", "Close"]]
    labels = label_formula.fee_labels4(prices, grid)
    np.testing.assert_allclose(labels.return4_net, old_labels.return_4,
                               rtol=0, atol=5e-15, equal_nan=True)
    pd.testing.assert_series_equal(labels.label_end4, old_labels.label_end_return_4,
                                   check_exact=True, check_names=False)
    decision_axis = exact_datetime(decisions.signal_date)
    if not decision_axis.equals(full_axis[:-1]):
        raise ValueError("full original1636 N0 decision prefix required")
    if decisions.entry_eligible.dtype != np.dtype(bool) or decisions.confirmation_opportunity.dtype != np.dtype(bool):
        raise ValueError("original native Boolean policy predicates required")
    eligible = decisions.entry_eligible.copy()
    target = decisions.target_position.copy()
    eligible.index, target.index = decision_axis, decision_axis
    complete_scope = component.causal_flat_eligible(eligible, target, initial_target_position=0)
    np.testing.assert_array_equal(complete_scope, decisions.confirmation_opportunity)
    flat = complete_scope.reindex(grid)
    statistics.validate(features, labels, sessions)
    return features, labels, flat, sessions, {
        "status": "PASS", "signal_n": len(grid), "decision_prefix_n": len(decisions),
        "native_price_n": len(native), "warmup_price_n": len(warm69),
        "all_native_prices_volume_amount_exact": True, "old17_controls_exact": True,
        "datetime_unit_normalization": "lossless exact roundtrip only; no timestamp normalization",
        "warmup_anchor_overlap": "same originalEX069 rtol=1e-13/atol=1e-13 arithmetic; full CSV SHA exact",
        "return4_old_formula_agreement": "atol5e-15 machine arithmetic only; old label CSV SHA exact",
        "labels": "exact frozen h4 OPEN-fee/OC-risk formulas on original authenticated prices",
        "auxiliary": "original policy-flat confirmation_opportunity; not actual filled account-flat",
        "flat_eligible_n": int(flat.sum()), "provider_calls": 0, "new_accounts": 0,
        "missing_features": features.isna().sum().to_dict(),
    }
