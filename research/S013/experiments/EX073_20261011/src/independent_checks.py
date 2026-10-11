"""Independent chronological fill, direct price arithmetic and rank/DF verification."""

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr


def verify_inputs(account, fills, decisions, entries, prices, features, labels, scope, old14, warm):
    count = 0
    position, records = 0, []
    d = decisions.copy()
    d.signal_date = pd.to_datetime(d.signal_date).dt.normalize()
    f = fills.copy()
    f["day"] = pd.to_datetime(f.fill_time).dt.normalize()
    for row in account.itertuples():
        day = pd.Timestamp(row.date).normalize()
        assert row.quantity_before == position
        for event in f.loc[f.day == day].itertuples():
            if event.side == "BUY":
                if position == 0:
                    t = pd.Timestamp(event.signal_date).normalize()
                    selected = d.loc[d.signal_date == t]
                    assert len(selected) == 1 and selected.iloc[0].action == "BUY"
                    assert pd.Timestamp(selected.iloc[0].valid_session).normalize() == day > t
                    records.append((t, day, selected.iloc[0].regime, str(event.fill_id)))
                position += event.quantity
            else:
                position -= event.quantity
            assert position >= 0
            count += 2
        assert row.quantity == position
        count += 2
    assert list(entries.index) == [r[0] for r in records]
    for t, day, regime, identity in records:
        assert entries.loc[t, "entry_session"] == day and entries.loc[t, "regime"] == regime
        assert entries.loc[t, "entry_fill_id"] == identity
        bought = f.loc[(f.day == day) & f.side.eq("BUY")]
        assert entries.loc[t, "entry_quantity"] == bought.quantity.sum()
        if regime == "bear":
            assert bool(scope.loc[t])
        count += 3
    expected_scope = features.index.isin([r[0] for r in records if r[2] == "bear"])
    np.testing.assert_array_equal(scope, expected_scope)
    pd.testing.assert_frame_equal(features.loc[:, list(old14.columns)], old14, check_exact=True)
    opens, closes = prices.Open.to_numpy(), prices.Close.to_numpy()
    for t in features.index:
        k = warm.index.get_loc(t)
        assert k >= 4
        overnight = sum(
            max(0, -np.log(warm.iloc[j].Open / warm.iloc[j - 1].Close)) for j in range(k - 3, k + 1)
        )
        intra = sum(
            max(0, -np.log(warm.iloc[j].Close / warm.iloc[j].Open)) for j in range(k - 3, k + 1)
        )
        assert features.loc[t, "pressure_flag"] == float(overnight > intra)
        i = prices.index.get_loc(t)
        if i + 3 < len(prices):
            np.testing.assert_allclose(
                labels.loc[t, "first2"], opens[i + 3] / opens[i + 1] - 1, rtol=0, atol=5e-15
            )
            assert pd.Timestamp(labels.loc[t, "label_end_first2"]) == prices.index[i + 3]
        else:
            assert pd.isna(labels.loc[t, "first2"]) and pd.isna(labels.loc[t, "label_end_first2"])
        if i + 5 >= len(prices):
            for name in ("late_return", "full4", "late_downside"):
                assert pd.isna(labels.loc[t, name]) and pd.isna(labels.loc[t, "label_end_" + name])
                count += 1
            continue
        expected = {
            "late_return": opens[i + 5] / opens[i + 3] - 1,
            "full4": opens[i + 5] / opens[i + 1] - 1,
            "late_downside": max(
                0,
                1
                - min(opens[i + 3], closes[i + 3], opens[i + 4], closes[i + 4], opens[i + 5])
                / opens[i + 3],
            ),
        }
        for name, value in expected.items():
            np.testing.assert_allclose(labels.loc[t, name], value, rtol=0, atol=5e-15)
            assert pd.Timestamp(labels.loc[t, "label_end_" + name]) == prices.index[i + 5]
            count += 2
        np.testing.assert_allclose(
            (1 + labels.loc[t, "first2"]) * (1 + labels.loc[t, "late_return"]) - 1,
            labels.loc[t, "full4"],
            rtol=0,
            atol=5e-15,
        )
        np.testing.assert_allclose(
            0.999 * opens[i + 5] / (0.999 * opens[i + 3]) - 1,
            labels.loc[t, "late_return"],
            rtol=0,
            atol=5e-15,
        )
        count += 5
    return {
        "status": "PASS",
        "checks": count,
        "fill_entry_identity": True,
        "no_exit_selection": True,
        "old14_exact": True,
        "price_label_algebra_maturity": True,
    }


def independent_ic(x, y, controls=None):
    good = np.isfinite(x) & np.isfinite(y)
    if controls is not None:
        good &= np.isfinite(controls).all(axis=1)
    x, y = x[good], y[good]
    n = len(x)
    value, reason, rank, df = None, None, None, None
    design = None
    if controls is not None:
        columns = [np.ones(n)] + [rankdata(v) for v in controls[good].T]
        design = np.asarray(columns).T
        rank = int(np.linalg.matrix_rank(design)) if n else 0
        df = n - rank
        if df < 10:
            reason = "INSUFFICIENT_RESIDUAL_DF"
    if reason is None and n < 20:
        reason = "INSUFFICIENT_SAMPLE"
    if reason is None and (np.ptp(x) == 0 or np.ptp(y) == 0):
        reason = "CONSTANT_COMPONENT_OR_LABEL"
    if reason is None:
        if controls is None:
            value = float(spearmanr(x, y).statistic)
        else:
            xr, yr = rankdata(x), rankdata(y)
            xn, yn = np.linalg.norm(xr - xr.mean()), np.linalg.norm(yr - yr.mean())
            projection = design @ np.linalg.pinv(design)
            xr, yr = xr - projection @ xr, yr - projection @ yr
            if np.linalg.norm(xr) <= 1e-10 * xn or np.linalg.norm(yr) <= 1e-10 * yn:
                reason = "CONSTANT_OR_EXPLAINED_RESIDUAL"
            else:
                value = float(np.corrcoef(xr, yr)[0, 1])
    return {
        "n": n,
        "flag_n": int((x == 1).sum()),
        "clear_n": int((x == 0).sum()),
        "design_rank": rank,
        "residual_df": df,
        "value": value,
        "reason": reason,
    }


def match(reported, expected):
    for key in ("n", "flag_n", "clear_n", "design_rank", "residual_df", "reason"):
        assert reported[key] == expected[key], (key, reported, expected)
    if expected["value"] is None:
        assert reported["value"] is None
    else:
        np.testing.assert_allclose(reported["value"], expected["value"], rtol=0, atol=2e-10)


def match_groups(reported, x, y):
    good = np.isfinite(x) & np.isfinite(y)
    for name, flag in (("flag", 1), ("clear", 0)):
        values = y[good & (x == flag)]
        r = reported[name]
        assert r["n"] == len(values)
        assert r["negative_n"] == int((values < 0).sum())
        assert r["zero_n"] == int((values == 0).sum())
        assert r["positive_n"] == int((values > 0).sum())
        assert r["reliable_group_evidence"] == (len(values) >= 20)
        assert r["descriptive_only"] is True
        if len(values):
            np.testing.assert_allclose(r["mean"], sum(values) / len(values), rtol=0, atol=5e-15)
        else:
            assert r["mean"] is None


def verify_statistics(features, labels, scope, outcome, control_names):
    count = 0
    x, c = features.pressure_flag.to_numpy(float), features.loc[:, control_names].to_numpy(float)
    mask = scope.to_numpy(bool)
    rng = np.random.default_rng(13)
    n = len(features)
    starts = rng.integers(0, n - 39, (500, (n + 39) // 40))
    samples = np.concatenate(
        [starts[:, j, None] + np.arange(40) for j in range(starts.shape[1])], axis=1
    )[:, :n]
    assert outcome["entry_n"] == int(mask.sum()) and outcome["models"] == 0
    for name, panel in outcome["labels"].items():
        y = labels[name].to_numpy(float)
        groups = [(panel, mask)]
        groups += [(v, mask & (features.index.year == int(k))) for k, v in panel["years"].items()]
        groups += [(v, mask & (np.arange(n) % 5 == int(k))) for k, v in panel["phases"].items()]
        for row, keep in groups:
            match(row["raw"], independent_ic(x[keep], y[keep]))
            match(row["partial"], independent_ic(x[keep], y[keep], c[keep]))
            match_groups(row["groups"], x[keep], y[keep])
            count += 3
        for kind in ("raw", "partial"):
            reported = panel["bootstrap"][kind]
            assert len(reported["replicates"]) == 500
            valid, failures = [], {}
            for i, raw in enumerate(samples):
                selected = raw[mask[raw]]
                expected = independent_ic(
                    x[selected], y[selected], c[selected] if kind == "partial" else None
                )
                match(reported["replicates"][i], expected)
                assert reported["replicates"][i]["replicate"] == i
                if expected["value"] is not None:
                    valid.append(expected["value"])
                else:
                    failures[expected["reason"]] = failures.get(expected["reason"], 0) + 1
                count += 1
            assert (
                reported["valid_replicates"] == len(valid)
                and reported["failure_reasons"] == failures
            )
            if len(valid) >= 400:
                np.testing.assert_allclose(
                    reported["ic95"],
                    np.quantile(valid, [0.025, 0.975], method="linear"),
                    rtol=0,
                    atol=2e-10,
                )
            else:
                assert (
                    reported["ic95"] is None
                    and reported["reason"] == "INSUFFICIENT_VALID_BOOTSTRAP_REPLICATES"
                )
    for name in ("first2", "full4"):
        match_groups(outcome["companions"][name], x[mask], labels[name].to_numpy(float)[mask])
        count += 1
    return {"status": "PASS", "checks": count, "all_replicates_and_failures_verified": True}
