"""Source-only synthetic cases; never open market data/native cache or experiment."""

import ast
from hashlib import sha256
from pathlib import Path
import json
import numpy as np
import pandas as pd
import entry_core as core
import entry_statistics as stats
from independent_checks import independent_ic, match, verify_statistics

HERE = Path(__file__).parent


def fixture():
    index = pd.bdate_range("2020-01-01", periods=12)
    fills = pd.DataFrame(
        [
            {
                "fill_time": index[1] + pd.Timedelta(hours=9, minutes=30),
                "fill_id": "a",
                "signal_date": index[0],
                "side": "BUY",
                "quantity": 10,
                "price": 100,
                "fees": 1,
            },
            {
                "fill_time": index[1] + pd.Timedelta(hours=9, minutes=31),
                "fill_id": "b",
                "signal_date": index[0],
                "side": "BUY",
                "quantity": 5,
                "price": 100,
                "fees": 0.5,
            },
            {
                "fill_time": index[5] + pd.Timedelta(hours=9, minutes=30),
                "fill_id": "c",
                "signal_date": index[4],
                "side": "SELL",
                "quantity": 15,
                "price": 100,
                "fees": 1.5,
            },
            {
                "fill_time": index[7] + pd.Timedelta(hours=9, minutes=30),
                "fill_id": "d",
                "signal_date": index[6],
                "side": "BUY",
                "quantity": 20,
                "price": 100,
                "fees": 2,
            },
            {
                "fill_time": index[9] + pd.Timedelta(hours=9, minutes=30),
                "fill_id": "e",
                "signal_date": index[8],
                "side": "SELL",
                "quantity": 20,
                "price": 100,
                "fees": 2,
            },
        ]
    )
    daily, position = [], 0
    for day in index:
        before = position
        for f in fills.loc[pd.to_datetime(fills.fill_time).dt.normalize() == day].itertuples():
            position += f.quantity if f.side == "BUY" else -f.quantity
        daily.append({"date": day, "quantity_before": before, "quantity": position})
    d = pd.DataFrame(
        {
            "signal_date": index[:-1],
            "valid_session": index[1:],
            "action": "WAIT",
            "signal_reason": "flat",
            "regime": "bear",
        }
    )
    for i, action in ((0, "BUY"), (4, "SELL"), (6, "BUY"), (8, "SELL")):
        d.loc[i, ["action", "signal_reason"]] = [action, "entry" if action == "BUY" else "time"]
    d.loc[6, "regime"] = "bull"
    return index, pd.DataFrame(daily), fills, d


def main():
    checks, refusals = [], []
    idx = pd.bdate_range("2020-01-01", periods=18)
    prices = pd.DataFrame(
        {"Open": np.arange(18) + 100.0, "Close": np.arange(18) + 100.5}, index=idx
    )
    observed = core.pressure(prices)
    assert observed.pressure_flag.iloc[:4].isna().all()
    assert observed.pressure_flag.iloc[4:].eq(0).all()
    checks.append("full4session availability and no-down false")
    bearish = prices.copy()
    bearish["Open"], bearish["Close"] = 100 * 0.99 ** np.arange(18), 100 * 0.99 ** np.arange(18)
    assert core.pressure(bearish).pressure_flag.iloc[4:].eq(1).all()
    checks.append("overnight-only down fixed true")
    intraday = prices.copy()
    intraday["Open"] = 100 * 0.99 ** np.arange(18)
    intraday["Close"] = intraday.Open * 0.99
    assert core.pressure(intraday).pressure_flag.iloc[4:].eq(0).all()
    checks.append("intraday-only down false")
    equal = pd.DataFrame({"Open": 100.0, "Close": 100.0}, index=idx)
    assert core.pressure(equal).pressure_flag.iloc[4:].eq(0).all()
    checks.append("zero denominator equality false")
    pd.testing.assert_frame_equal(core.pressure(prices.iloc[:11]), observed.iloc[:11])
    future = prices.copy()
    future.iloc[11:] *= 4
    pd.testing.assert_frame_equal(core.pressure(future).iloc[:11], observed.iloc[:11])
    checks.append("pressure prefix/future invariant")
    np.testing.assert_allclose(
        core.pressure(prices * 3).iloc[4:, :4], observed.iloc[4:, :4], rtol=0, atol=1e-13
    )
    checks.append("pressure scale invariant")
    labelled = core.labels(prices, idx)
    np.testing.assert_allclose(
        labelled.loc[idx[0], "late_return"], prices.Open.iloc[5] / prices.Open.iloc[3] - 1
    )
    np.testing.assert_allclose(labelled.loc[idx[0], "late_downside"], 0)
    np.testing.assert_allclose(
        (1 + labelled.first2) * (1 + labelled.late_return), 1 + labelled.full4, equal_nan=True
    )
    checks.append("fixed window endpoints plus multiplicative decomposition")
    assert labelled.first2.iloc[-3:].isna().all() and labelled.late_return.iloc[-5:].isna().all()
    assert (
        labelled.label_end_first2.iloc[-3:].isna().all()
        and labelled.label_end_late_return.iloc[-5:].isna().all()
    )
    checks.append("missing maturity no extension")
    changed = prices.copy()
    changed.loc[idx[1], "Open"] = 0.01
    changed.loc[idx[2], "Close"] = 0.01
    assert core.labels(changed, idx).late_downside.iloc[0] == labelled.late_downside.iloc[0]
    changed.loc[idx[4], "Close"] = 50
    np.testing.assert_allclose(
        core.labels(changed, idx).late_downside.iloc[0], 1 - 50 / prices.Open.iloc[3]
    )
    checks.append("late risk excludes initial overnight and uses only declared O/C")
    irrelevant = prices.assign(High=9999, Low=0.001)
    pd.testing.assert_frame_equal(core.labels(irrelevant, idx), labelled)
    np.testing.assert_allclose(
        core.labels(prices * 7, idx)[["first2", "late_return", "full4", "late_downside"]],
        labelled[["first2", "late_return", "full4", "late_downside"]],
        rtol=0,
        atol=5e-15,
    )
    checks.append("HL ignored labels scale invariant")
    prefix = core.labels(prices.iloc[:11], idx[:6])
    pd.testing.assert_frame_equal(prefix, labelled.iloc[:6])
    altered = prices.copy()
    altered.iloc[11:] *= 9
    pd.testing.assert_frame_equal(core.labels(altered, idx).iloc[:6], labelled.iloc[:6])
    checks.append("mature labels prefix and future invariant")
    i, ledger, fills, decisions = fixture()
    entries = core.actual_entries(ledger, fills, decisions)
    assert entries.index.tolist() == [i[0], i[6]] and entries.entry_quantity.tolist() == [15, 20]
    checks.append("first actual BUY from flat and partial fill aggregation")
    before = core.actual_entries(ledger.iloc[:5], fills.iloc[:2], decisions.iloc[:4])
    pd.testing.assert_frame_equal(before, entries.iloc[:1])
    modified = fills.copy()
    modified.loc[2, "price"] = 999
    modified.loc[2, "fees"] = 0
    altered_d = decisions.copy()
    altered_d.loc[8, "signal_reason"] = "range"
    pd.testing.assert_frame_equal(
        core.actual_entries(ledger, modified, altered_d).iloc[:1], entries.iloc[:1]
    )
    checks.append("entry prefix/future exit values do not select first entry")
    rng = np.random.default_rng(13)
    x = np.r_[np.ones(15), np.zeros(49)]
    y = rng.normal(size=64)
    c = rng.normal(size=(64, 14))
    match(stats.ic(x, y), independent_ic(x, y))
    match(stats.ic(x, y, c), independent_ic(x, y, c))
    assert stats.ic(x, y, c)["residual_df"] == 49
    assert not stats.describe(x, y)["flag"]["reliable_group_evidence"]
    checks.append("full rank/df and binary15 group explicitly unreliable")
    for n in (0, 3, 19):
        a = stats.ic(x[:n], y[:n], c[:n])
        assert a["value"] is None
        match(a, independent_ic(x[:n], y[:n], c[:n]))
    assert stats.ic(np.zeros(30), y[:30])["reason"] == "CONSTANT_COMPONENT_OR_LABEL"
    assert (
        stats.ic(x, y, np.column_stack([x, c[:, :13]]))["reason"]
        == "CONSTANT_OR_EXPLAINED_RESIDUAL"
    )
    checks.append("thin DF/sample and explained component null")
    samples = stats.sampled_indices(1635)
    assert samples.shape == (500, 1635) and samples.min() >= 0 and samples.max() < 1635
    np.testing.assert_array_equal(samples, stats.sampled_indices(1635))
    assert np.all(np.diff(samples[:, :40], axis=1) == 1)
    checks.append("fullaxis500x40 fixed seed and block geometry")
    synthetic_index = pd.bdate_range("2020-01-01", periods=200)
    synthetic_features = pd.DataFrame(
        rng.normal(size=(200, 14)), index=synthetic_index, columns=stats.CONTROLS
    )
    synthetic_features["pressure_flag"] = rng.integers(0, 2, 200).astype(float)
    synthetic_labels = pd.DataFrame(
        rng.normal(size=(200, 4)),
        index=synthetic_index,
        columns=["late_return", "late_downside", "first2", "full4"],
    )
    synthetic_scope = pd.Series(np.arange(200) % 3 == 0, index=synthetic_index)
    synthetic_outcome = stats.analyze(synthetic_features, synthetic_labels, synthetic_scope)
    independent = verify_statistics(
        synthetic_features, synthetic_labels, synthetic_scope, synthetic_outcome, stats.CONTROLS
    )
    assert independent["checks"] > 2000
    checks.append(
        "full synthetic statistic pipeline all500replicates null/status/group/year/phase independently verified"
    )
    for name, function in (
        ("nonpositive price", lambda: core.pressure(prices.assign(Open=0))),
        ("duplicate calendar", lambda: core.labels(pd.concat([prices, prices.iloc[-1:]]), idx)),
        ("nonfinite price", lambda: core.labels(prices.assign(Close=np.nan), idx)),
        (
            "future fill causality",
            lambda: core.actual_entries(
                ledger,
                fills.assign(signal_date=pd.to_datetime(fills.fill_time).dt.normalize()),
                decisions,
            ),
        ),
        (
            "ledger inconsistent",
            lambda: core.actual_entries(ledger.assign(quantity=0), fills, decisions),
        ),
        (
            "negative fill",
            lambda: core.actual_entries(ledger, fills.assign(quantity=-1), decisions),
        ),
    ):
        try:
            function()
        except (ValueError, KeyError):
            refusals.append(name)
        else:
            raise AssertionError("Failed refusal: " + name)
    sources = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))}
    for path in HERE.glob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        assert not any(
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"evaluate", "fetch", "get_data", "run_backtest"}
            for node in calls
        )
    out = {
        "status": "PASS",
        "synthetic_n": len(checks),
        "checks": checks,
        "refusal_n": len(refusals),
        "refusals": refusals,
        "source_hashes": sources,
        "ast": "PASS no fetch/evaluate/backtest calls",
        "market_reads": 0,
        "statistic_runs": 0,
        "accounts": 0,
        "allocations": 0,
    }
    path = HERE / "focused_checks.json"
    assert not path.exists()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8")
    print(
        {k: out[k] for k in ("status", "synthetic_n", "refusal_n", "market_reads", "allocations")}
    )


if __name__ == "__main__":
    main()
