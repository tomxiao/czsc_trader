"""Pure authenticated-input construction. No imports of platform/data loaders."""

import numpy as np
import pandas as pd

import component_draft as component
import statistics_draft_v2 as statistics


def original_tail(bars):
    days, a = component.arrays(bars)
    close, volume = a[:, :, 1], a[:, :, 2]
    relative = volume[:, :6] / volume[:, :6].max(axis=1, keepdims=True)
    return pd.DataFrame(
        {
            "late_recovery": np.log(close[:, 7]) - np.log(close[:, 5]),
            "early_volume_reclaim": (relative * np.sign(close[:, 7, None] - close[:, :6])).sum(
                axis=1
            )
            / relative.sum(axis=1),
        },
        index=days,
    )


def construct(
    old66,
    old69,
    public_native_prices,
    warm_prices,
    native_bars,
    native_prices,
    complete_sessions,
    pricing,
    candidate_id,
    symbol,
):
    if candidate_id != "C8880" or symbol != "510500.SH":
        raise ValueError("only original S013 C8880/510500 authorized")
    if (
        pricing.get("basis") != "HFQ_RESEARCH"
        or type(pricing.get("anchor_factor")) is not float
        or pricing["anchor_factor"] != 0.2803
    ):
        raise ValueError("exact original native HFQ anchor contract required")
    if not isinstance(complete_sessions, pd.DatetimeIndex) or not complete_sessions.equals(
        native_prices.index
    ):
        raise ValueError("native full-session calendar and execution daily must align exactly")
    if not old66.index.equals(old69.index) or not old66.index.isin(complete_sessions).all():
        raise ValueError("shared original signal axis required, no fill/extension")
    if (
        len(old66) != 1635
        or old66.index[-1] > pd.Timestamp("2026-09-30")
        or old66.index[0] < pd.Timestamp("2020-01-01")
    ):
        raise ValueError("original1635 development signal grid required")
    if native_prices.index[-1] != pd.Timestamp("2026-09-30"):
        raise ValueError("fixed native original development endpoint required")
    pd.testing.assert_frame_equal(
        old66[list(statistics.CONTROLS[:14])],
        old69[list(statistics.CONTROLS[:14])],
        check_exact=True,
    )
    days, _ = component.arrays(native_bars)
    pd.testing.assert_index_equal(days, complete_sessions, check_names=False)
    tail = original_tail(native_bars).reindex(old66.index)
    for name in ("late_recovery", "early_volume_reclaim"):
        pd.testing.assert_series_equal(tail[name], old69[name], check_exact=True, check_names=False)
    pd.testing.assert_series_equal(
        -old66["late_weakness"], tail["late_recovery"], check_exact=True, check_names=False
    )
    pd.testing.assert_series_equal(
        -old66["early_reclaim_weakness"],
        tail["early_volume_reclaim"],
        check_exact=True,
        check_names=False,
    )
    pd.testing.assert_frame_equal(
        native_prices[["Open", "Close"]],
        public_native_prices[["Open", "Close"]],
        check_exact=True,
        check_names=False,
    )
    common = native_prices.index.intersection(warm_prices.index)
    if common.empty or warm_prices.index[0] > pd.Timestamp("2019-04-10"):
        raise ValueError("existing original daily HFQ warmup/overlap required")
    np.testing.assert_allclose(
        native_prices.loc[common, ["Open", "Close"]].to_numpy() * 0.2803,
        warm_prices.loc[common, ["Open", "Close"]].to_numpy(),
        rtol=0,
        atol=5e-15,
    )
    observation, profile = component.features(native_bars)
    features = (
        old66[list(statistics.CONTROLS[:14])]
        .join(tail)
        .join(
            observation[["mean_negative_body", "past_volume_shape_projection", "down_volume_cov"]]
        )
    )
    labels = component.fee_labels4(native_prices, old66.index)
    scaled = component.fee_labels4(native_prices * 0.2803, old66.index)
    np.testing.assert_allclose(
        labels[list(statistics.LABELS)],
        scaled[list(statistics.LABELS)],
        rtol=0,
        atol=5e-15,
        equal_nan=True,
    )
    pd.testing.assert_series_equal(labels.label_end4, scaled.label_end4, check_exact=True)
    statistics.validate(features, labels, complete_sessions)
    checks = independent_check(
        native_bars, native_prices, features, labels, complete_sessions, profile
    )
    return (
        features,
        labels,
        observation,
        profile,
        {
            "status": "PASS",
            "native_identity": "caller serialized cache exact public native EvidenceRef",
            "old14_exact": True,
            "old_EX061_pair_exact": True,
            "EX066_inverse_exact": True,
            "native_price_units_exact": True,
            "warm_price_overlap_n": len(common),
            "anchor": 0.2803,
            "profile20": "strictly20 completed prior sessions, original full8clock calendar, first20 unavailable",
            "signal_axis_n": len(features),
            "price_calendar_n": len(complete_sessions),
            "missing_features": features.isna().sum().to_dict(),
            "independent_checks": checks,
            "labels": "new independent samefee h4 O/C labels, not native trades or old HL risk",
            "provider_calls": 0,
            "accounts": 0,
        },
    )


def independent_check(bars, prices, features, labels, calendar, profile):
    """Direct per-session formula checks, independent of vectorized builder."""
    check_n = 0
    blocks = {t: block for t, block in bars.groupby(bars.index.normalize())}
    for t in features.index:
        block = blocks[t]
        d = np.array([max(np.log(o) - np.log(c), 0.0) for o, c in zip(block.Open, block.Close)])
        volumes = block.Volume.to_numpy(float)
        expected = np.dot(volumes / volumes.sum(), d) - d.mean()
        np.testing.assert_allclose(features.loc[t, "down_volume_cov"], expected, rtol=0, atol=1e-13)
        np.testing.assert_allclose(
            features.loc[t, "mean_negative_body"], d.mean(), rtol=0, atol=1e-13
        )
        i = calendar.get_loc(t)
        if i < 20:
            assert pd.isna(features.loc[t, "past_volume_shape_projection"])
            assert profile.loc[t].isna().all()
        else:
            past = []
            for s in calendar[i - 20 : i]:
                volume = blocks[s].Volume.to_numpy(float)
                if len(volume) != 8:
                    raise ValueError("missing previouslycomplete8bar session")
                past.append(volume / volume.sum())
            q = np.mean(past, axis=0)
            np.testing.assert_allclose(profile.loc[t], q, rtol=0, atol=1e-13)
            np.testing.assert_allclose(
                features.loc[t, "past_volume_shape_projection"],
                np.dot(q, d) - d.mean(),
                rtol=0,
                atol=1e-13,
            )
        if i + 5 < len(calendar):
            entry, final = prices.Open.iloc[i + 1], prices.Open.iloc[i + 5]
            expected_return = (final / entry) * (0.999 / 1.001) - 1.0
            observations = (
                [prices.Open.iloc[j] for j in range(i + 1, i + 5)]
                + [prices.Close.iloc[j] for j in range(i + 1, i + 5)]
                + [final]
            )
            expected_risk = max(0.0, 1.0 - min(observations) / entry)
            np.testing.assert_allclose(
                labels.loc[t, ["return4_net", "downside4_oc"]].to_numpy(float),
                [expected_return, expected_risk],
                rtol=0,
                atol=5e-15,
            )
            assert labels.loc[t, "label_end4"] == calendar[i + 5]
        else:
            assert labels.loc[t].isna().all()
        check_n += 1
    return check_n
