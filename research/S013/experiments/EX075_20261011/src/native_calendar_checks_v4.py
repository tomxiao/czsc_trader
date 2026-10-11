"""Artificial anchor/evaluation calendar fixtures only; no data/provider I/O."""

import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

import component_draft as component
import input_adapter_draft_v2 as adapter
import statistics_draft_v2 as statistics


def check():
    here = Path(__file__).resolve().parent
    oldfreeze = json.loads((here / "source_freeze_v3.json").read_text(encoding="utf-8"))
    assert len(oldfreeze["source_files"]) == 38
    assert all(
        sha256((here / n).read_bytes()).hexdigest() == h
        for n, h in oldfreeze["source_files"].items()
    )
    assert (
        sha256((here / "source_freeze_v3.json").read_bytes()).hexdigest()
        == "65559cb920a0cec408cb3dd7e4804a50b84259b1a1cc26fbb5f8f6d18557066d"
    )
    checks = ["prior38_and_freeze_unchanged"]
    rng = np.random.default_rng(7504)
    available = pd.bdate_range("2020-01-02", "2026-09-30").as_unit("ns")
    chosen = np.linspace(0, len(available) - 3, 1634).astype(int)
    sessions = available[chosen].append(available[-2:])
    signals = sessions[:-1].rename("signal_date")
    fullcalendar = pd.DatetimeIndex([pd.Timestamp("2019-12-31")]).append(sessions)
    prices = pd.DataFrame(
        {"Open": 100 + np.arange(1637) * 0.01, "Close": 100 + np.arange(1637) * 0.005},
        index=fullcalendar,
    )
    warmcalendar = pd.bdate_range("2019-04-10", "2026-09-30").as_unit("ns")
    warm = pd.DataFrame({"Open": 28.03, "Close": 28.03}, index=warmcalendar)
    warm.loc[fullcalendar] = prices * 0.2803
    times = pd.DatetimeIndex(
        np.repeat(sessions.to_numpy(), 8)
        + np.tile(pd.to_timedelta([t + ":00" for t in component.CLOCKS]).to_numpy(), 1636)
    )
    bars = pd.DataFrame(
        {
            "Open": 100.0,
            "Close": 100 * np.exp(rng.normal(0, 0.001, len(times))),
            "Volume": rng.integers(100, 1000, len(times)).astype(float),
        },
        index=times,
    )
    tail = adapter.original_tail(bars).reindex(signals)
    old14 = pd.DataFrame(
        rng.normal(size=(1635, 14)), index=signals, columns=statistics.CONTROLS[:14]
    )
    old66 = old14.join(
        pd.DataFrame(
            {
                "late_weakness": -tail.late_recovery,
                "early_reclaim_weakness": -tail.early_volume_reclaim,
            },
            index=signals,
        )
    )
    old69 = old14.join(tail)
    arguments = [
        old66,
        old69,
        prices.copy(),
        warm,
        bars,
        prices,
        sessions,
        {"basis": "HFQ_RESEARCH", "anchor_factor": 0.2803},
        "C8880",
        "510500.SH",
    ]
    features, labels, observations, profile, result = adapter.construct(*arguments)
    assert result["full_native_price_n"] == 1637 and result["price_calendar_n"] == 1636
    assert (
        result["independent_checks"] == 1635 and result["anchor_removal_all_labels_maturity_exact"]
    )
    analysis_prices = prices.loc[sessions]
    pd.testing.assert_frame_equal(labels, component.fee_labels4(prices, signals), check_exact=True)
    pd.testing.assert_frame_equal(
        labels, component.fee_labels4(analysis_prices, signals), check_exact=True
    )
    assert labels.return4_net.notna().sum() == 1631
    assert labels.label_end4.iloc[1630] == sessions[-1] and sessions[-1] not in features.index
    assert labels.label_end4.iloc[0] == sessions[5]
    expected = (
        0.999 * prices.loc[sessions[5], "Open"] / (1.001 * prices.loc[sessions[1], "Open"]) - 1
    )
    assert labels.return4_net.iloc[0] == expected
    statistics.validate(features, labels, analysis_prices.index)
    assert statistics.block_indices(len(features)).shape == (500, 1635)
    assert (
        observations.profile_available.iloc[:20].eq(False).all()
        and observations.profile_available.iloc[20:].all()
    )
    assert profile.iloc[:20].isna().all().all()
    independently, independent_q = component.features(bars)
    pd.testing.assert_frame_equal(observations, independently, check_exact=True)
    pd.testing.assert_frame_equal(profile, independent_q, check_exact=True)
    assert pd.Timestamp("2019-12-31") not in bars.index.normalize()
    checks.append(
        "full1637_anchor_evaluation1636_Taxis1635_h4Tplus5_finite1631_anchor_removal_labels_exact"
    )
    checks.append(
        "label_direct_positions_same_analysis_calendar_profile_first20_no_anchor_bar_bootstrap_signalaxis_only"
    )

    fixtures = []
    bad = list(arguments)
    bad[2], bad[5] = prices.iloc[1:].copy(), prices.iloc[1:].copy()
    fixtures.append(("missing_anchor", bad))
    bad = list(arguments)
    bad[6] = sessions.delete(3)
    fixtures.append(("missing_evaluation_session", bad))
    bad = list(arguments)
    extra = pd.DataFrame({"Open": [120.0], "Close": [119.0]}, index=[pd.Timestamp("2026-10-01")])
    bad[2], bad[5] = pd.concat([prices, extra]), pd.concat([prices, extra])
    fixtures.append(("extra_native_endpoint", bad))
    bad = list(arguments)
    mismatch = prices.copy()
    mismatch.iloc[12, 0] += 0.01
    bad[2] = mismatch
    fixtures.append(("public_native_price_mismatch", bad))
    bad = list(arguments)
    clock = bars.copy()
    changed = clock.index.to_numpy().copy()
    changed[3] += np.timedelta64(1, "m")
    clock.index = pd.DatetimeIndex(changed)
    bad[4] = clock
    fixtures.append(("wrong_bar_clock", bad))
    bad = list(arguments)
    bad[4] = bars.loc[bars.index.normalize() != sessions[10]]
    fixtures.append(("missing_complete_bar_session", bad))
    bad = list(arguments)
    illegal = prices.copy()
    illegal.iloc[0, 0] = 0.0
    bad[2], bad[5] = illegal.copy(), illegal
    fixtures.append(("illegal_anchor_price", bad))
    refusals = []
    for name, changed in fixtures:
        try:
            adapter.construct(*changed)
        except (ValueError, AssertionError):
            refusals.append(name)
        else:
            raise AssertionError("missing refusal: " + name)

    source = here / "authorized_driver_draft_v4.py"
    old = (here / "authorized_driver_draft_v3.py").read_text(encoding="utf-8")
    expected_source = (
        old.replace("source_freeze_v3.json", "source_freeze_v4.json")
        .replace("_authorization_v3.json", "_authorization_v4.json")
        .replace(
            "import input_adapter_draft as adapter", "import input_adapter_draft_v2 as adapter"
        )
        .replace(
            '        ("prices.csv", prices),',
            '        ("full_native_prices.csv", prices),\n        ("prices.csv", prices.loc[sessions]),',
        )
    )
    assert ast.dump(ast.parse(source.read_text(encoding="utf-8"))) == ast.dump(
        ast.parse(expected_source)
    )
    checks.append("driver_only_adapter_v2_full_analysis_artifacts_v4_authority_changes")
    text_method, bytes_method = Path.read_text, Path.read_bytes

    def forbidden(*args, **kwargs):
        raise AssertionError("no real input/platform calls permitted")

    Path.read_text, Path.read_bytes = forbidden, forbidden
    try:
        spec = importlib.util.spec_from_file_location("standby_volume_driver_v4_artificial", source)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
    finally:
        Path.read_text, Path.read_bytes = text_method, bytes_method
    original_authority = driver.authority

    def isolated(phase):
        return original_authority(phase, here=here / "synthetic_no_authority_driver_v4")

    driver.authority, driver.original_common = isolated, forbidden
    for phase in ("declare", "preflight", "statistics"):
        try:
            getattr(driver, phase)()
        except FileNotFoundError as error:
            assert "root_" + phase + "_authorization_v4.json" in str(error)
        else:
            raise AssertionError("missing v4 phase denial")
    checks.append("pure_driver_import_three_new_v4_authority_guards_stop_before_platform")
    return {
        "status": "PASS_ARTIFICIAL_CALENDARS_ONLY_NO_REAL_PHASE",
        "checks": checks,
        "refusals": refusals,
        "source_sha256": {
            n: sha256((here / n).read_bytes()).hexdigest()
            for n in (
                "input_adapter_draft_v2.py",
                "authorized_driver_draft_v4.py",
                "native_calendar_checks_v4.py",
            )
        },
        "real_input_reads": 0,
        "new_statistics": 0,
        "signals": 0,
        "accounts": 0,
        "allocate": 0,
        "publish": 0,
        "DEV": 0,
    }


if __name__ == "__main__":
    proof = check()
    with Path(__file__).with_suffix(".json").open("x", encoding="utf-8") as f:
        json.dump(proof, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(proof, ensure_ascii=False))
