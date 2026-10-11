"""Synthetic-only standby checks; no source-data/statistical/financial I/O."""

from hashlib import sha256
from pathlib import Path
import json
import numpy as np
import pandas as pd
from component_draft import features, fee_labels4, CLOCKS

HERE = Path(__file__).parent


def bars_fixture():
    days = pd.bdate_range("2020-01-01", periods=24)
    offsets = pd.to_timedelta([s + ":00" for s in CLOCKS])
    index = pd.DatetimeIndex(np.repeat(days.to_numpy(), 8) + np.tile(offsets.to_numpy(), len(days)))
    c = np.array([99.0, 101.0, 100.0, 102.0, 101.0, 103.0, 104.0, 105.0])
    o = np.r_[100.0, c[:-1]]
    return pd.DataFrame(
        {"Open": np.tile(o, 24), "Close": np.tile(c, 24), "Volume": 10.0}, index=index
    )


def old_pair(day):
    return np.log(day.Close.iloc[7]) - np.log(day.Close.iloc[5]), float(
        (day.Volume.iloc[:6] * np.sign(day.Close.iloc[7] - day.Close.iloc[:6])).sum()
        / day.Volume.iloc[:6].sum()
    )


def main():
    b = bars_fixture()
    f, q = features(b)
    checks = []
    np.testing.assert_allclose(f.down_volume_cov, 0, rtol=0, atol=1e-15)
    assert not f.profile_available.iloc[:20].any() and f.profile_available.iloc[20:].all()
    assert f.past_volume_shape_projection.iloc[:20].isna().all()
    assert q.iloc[:20].isna().all(axis=None)
    checks.append("equal volume covariance zero; first20 explicit unavailable")
    changed = b.copy()
    # Preserve total volume and all prices, while keeping final close above early6.
    changed.iloc[20 * 8, changed.columns.get_loc("Volume")] = 15.0
    changed.iloc[20 * 8 + 1, changed.columns.get_loc("Volume")] = 5.0
    g, qg = features(changed)
    np.testing.assert_array_equal(q.iloc[20].to_numpy(), qg.iloc[20].to_numpy())
    assert f.mean_negative_body.iloc[20] == g.mean_negative_body.iloc[20]
    assert f.past_volume_shape_projection.iloc[20] == g.past_volume_shape_projection.iloc[20]
    assert g.down_volume_cov.iloc[20] > f.down_volume_cov.iloc[20]
    np.testing.assert_array_equal(old_pair(b.iloc[160:168]), old_pair(changed.iloc[160:168]))
    assert b.Volume.iloc[160:168].sum() == changed.Volume.iloc[160:168].sum()
    checks.append(
        "not exact EX061 pair copy; q strict shift1 unaffected current V; dailyVolume same"
    )
    # The change must enter NEXT day's historical profile at exactly 1/20 weight.
    np.testing.assert_allclose(
        qg.iloc[21].to_numpy() - q.iloc[21].to_numpy(),
        np.r_[5.0, -5.0, np.zeros(6)] / 80 / 20,
        rtol=0,
        atol=1e-15,
    )
    checks.append("past20 endpoint and exact clock mapping")
    for days in (20, 21, 23):
        h, qh = features(changed.iloc[: days * 8])
        pd.testing.assert_frame_equal(h, g.iloc[:days])
        pd.testing.assert_frame_equal(qh, qg.iloc[:days])
    future = changed.copy()
    future.iloc[21 * 8 :] *= 11
    hf, qf = features(future)
    pd.testing.assert_frame_equal(hf.iloc[:21], g.iloc[:21])
    pd.testing.assert_frame_equal(qf.iloc[:21], qg.iloc[:21])
    checks.append("prefix and future mutation invariance")
    scaled = changed.copy()
    scaled[["Open", "Close"]] *= 3
    scaled.Volume *= 7
    hs, qs = features(scaled)
    np.testing.assert_allclose(hs.iloc[:, :3], g.iloc[:, :3], rtol=0, atol=5e-15, equal_nan=True)
    np.testing.assert_allclose(qs, qg, rtol=0, atol=1e-15, equal_nan=True)
    checks.append("price/volume scale invariance")
    up = b.copy()
    up.Close = up.Open * 1.01
    zero, _ = features(up)
    assert zero.down_volume_cov.eq(0).all() and zero.mean_negative_body.eq(0).all()
    assert zero.past_volume_shape_projection.iloc[20:].eq(0).all()
    checks.append("no-negative-body semantic zero, no absorption claim")
    d = pd.bdate_range("2020-01-01", periods=12)
    prices = pd.DataFrame({"Open": np.arange(12) + 100.0, "Close": np.arange(12) + 99.0}, index=d)
    labels = fee_labels4(prices, d)
    np.testing.assert_allclose(labels.return4_net.iloc[0], 0.999 * 105 / (1.001 * 101) - 1)
    np.testing.assert_allclose(labels.downside4_oc.iloc[0], 1 - 100 / 101)
    assert labels.label_end4.iloc[0] == d[5] and labels.iloc[-5:].isna().all(axis=None)
    np.testing.assert_allclose(
        fee_labels4(prices * 9, d).iloc[:, :2],
        labels.iloc[:, :2],
        rtol=0,
        atol=5e-15,
        equal_nan=True,
    )
    checks.append("independent4day cost label/O-C risk/maturity/tail/scale")
    refusals = []
    for name, operation in (
        ("zero volume", lambda: features(b.assign(Volume=0))),
        ("nonfinite", lambda: features(b.assign(Open=np.nan))),
        ("missing bar", lambda: features(b.drop(b.index[0]))),
        ("duplicate clock", lambda: features(pd.concat([b, b.iloc[-1:]]))),
        ("bad label price", lambda: fee_labels4(prices.assign(Close=0), d)),
    ):
        try:
            operation()
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError(name)
    out = {
        "status": "PASS",
        "checks": checks,
        "synthetic_n": len(checks),
        "refusals": refusals,
        "source_hashes": {
            n: sha256((HERE / n).read_bytes()).hexdigest()
            for n in ("component_draft.py", "synthetic_draft.py")
        },
        "real_data_reads": 0,
        "real_statistics": 0,
        "signals": 0,
        "accounts": 0,
        "allocations": 0,
        "publications": 0,
    }
    path = HERE / "synthetic_draft.json"
    assert not path.exists()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print({k: out[k] for k in ("status", "synthetic_n", "refusals", "source_hashes")})


if __name__ == "__main__":
    main()
