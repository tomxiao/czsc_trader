"""Artificial-only EX080 checks. Never fetch/prepare/evaluate/read market files."""

import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet, StrategyCandidate, StrategyRuntime, implementation_sha256

BASE = Path(__file__).resolve().parent
ROOT = next(p for p in BASE.parents if (p / "pyproject.toml").exists())


def load():
    p = types.ModuleType("confirm_fixture")
    p.__path__ = [str(BASE)]
    sys.modules[p.__name__] = p
    for name in ("confirm_kernel", "confirm_net"):
        spec = importlib.util.spec_from_file_location(
            "confirm_fixture." + name, BASE / (name + ".py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules["confirm_fixture.confirm_kernel"], module


def fixture():
    signals = pd.bdate_range("2019-12-31", periods=350)
    warm = pd.bdate_range(end=signals[0], periods=180)[:-1]
    full = warm.append(signals)
    z = np.arange(len(full))
    c = np.exp(np.cumsum(0.012 * np.sin(z * 0.83) + 0.004 * np.cos(z * 0.17))) * 10
    o = c * np.exp(-0.006 * np.cos(z * 0.61))
    d = pd.DataFrame(
        {
            "Date": full,
            "Open": o,
            "Close": c,
            "High": np.maximum(o, c) * 1.01,
            "Low": np.minimum(o, c) * 0.99,
            "Volume": 10000 + z * 13 + 2000 * np.sin(z * 0.7),
            "Amount": 200000 + z * 29 + 10000 * np.cos(z * 0.33),
        }
    )
    n = d.loc[d.Date.isin(signals)].copy()
    rows = []
    for day in signals[1:]:
        row = d.loc[d.Date.eq(day)].iloc[0]
        closes = np.exp(
            np.linspace(np.log(row.Open), np.log(row.Close), 8)
            + np.array([0.001, -0.002, 0.003, -0.002, 0.001, -0.001, 0.002, 0])
        )
        for i, time in enumerate(
            ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
        ):
            op = row.Open if i == 0 else closes[i - 1]
            rows.append(
                [
                    pd.Timestamp(str(day.date()) + " " + time),
                    op,
                    max(op, closes[i]) * 1.001,
                    min(op, closes[i]) * 0.999,
                    closes[i],
                    1000 + i * 10,
                    10000 + i * 100,
                ]
            )
    bars = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume", "Amount"])
    return d, n, bars, signals


def run():
    k, a = load()
    d, n, bars, axis = fixture()
    f = k.rebuild(d, n, bars, axis)
    checks = []
    assert (
        f.iloc[1:20].intraday_energy20.isna().all() and f.iloc[20:].intraday_energy20.notna().all()
    )
    assert f.confirmation_score.notna().all()
    raw = k.frame(d)
    acf = raw.Close.pct_change(fill_method=None).rolling(20).apply(k.acf, raw=True)
    rawscore = pd.DataFrame(
        {
            "acf": acf,
            "turnover": raw.Amount / raw.Amount.rolling(20).mean(),
            "volume": np.log(raw.Volume).diff().rolling(20).mean(),
        }
    )
    norm = rawscore.apply(lambda v: k.causal_rank(v, 120))
    np.testing.assert_array_equal(
        f.confirmation_score,
        (0.5 * norm.acf + 0.25 * norm.turnover + 0.25 * norm.volume).reindex(axis),
    )
    checks.append("original ADJUSTED120 confirmation and20-session original missingness")
    prices = k.frame(n)
    scores, proof = k.annual_forecasts(f, prices, axis)
    first2021 = axis[axis.year == 2021][0]
    cut = axis.get_loc(first2021) + 2
    shortf = k.rebuild(d, n, bars, axis[:cut])
    shortscores, _ = k.annual_forecasts(shortf, prices, axis[:cut])
    pd.testing.assert_series_equal(scores.iloc[:cut], shortscores, check_exact=True)
    assert proof["2021"]["max_maturity"] < first2021.isoformat()
    assert scores.loc[scores.index.year <= 2020].isna().all()
    assert scores.iloc[-4:].notna().all()
    checks.append("no future test-count gate/prefix/year maturity/2020cash/feature-only tail")
    md = d.copy()
    mn = n.copy()
    mb = bars.copy()
    future = axis[cut]
    for frame in (md, mn, mb):
        mask = frame.Date >= future
        for col in ("Open", "High", "Low", "Close", "Volume", "Amount"):
            frame[col] = frame[col].astype(float)
            frame.loc[mask, col] *= 1.37
    mf = k.rebuild(md, mn, mb, axis)
    ms, _ = k.annual_forecasts(mf, k.frame(mn), axis)
    pd.testing.assert_frame_equal(f.iloc[:cut], mf.iloc[:cut], check_exact=True)
    pd.testing.assert_series_equal(scores.iloc[:cut], ms.iloc[:cut], check_exact=True)
    checks.append("futureOHLCVA cannot change prior features/forecasts")
    pa = pd.bdate_range("2020-12-29", periods=15)
    pred = pd.Series(1.0, index=pa)
    h = k.episode_history(pred, pa)
    assert h.iloc[:3].target_position.eq(0).all()
    assert list(h.iloc[3:9].target_position) == [1, 1, 1, 1, 0, 1]
    assert list(h.iloc[3:8].signal_reason) == ["entry", "hold", "hold", "hold", "expiry"]
    assert list(h.iloc[3:8].policy_age) == [0, 1, 2, 3, 4]
    negative = pred.copy()
    negative.iloc[4:8] = -1
    nh = k.episode_history(negative, pa)
    pd.testing.assert_series_equal(
        h.iloc[3:8].target_position, nh.iloc[3:8].target_position, check_exact=True
    )
    assert k.episode_history(pd.Series(0.0, index=pa), pa).target_position.eq(0).all()
    assert k.episode_history(pd.Series(np.nan, index=pa), pa).target_position.eq(0).all()
    checks.append(
        "age0/4 expirypriority/no sameexitentry/negative whileheld/fill-independent/yearcross"
    )
    # Source/math authentication only, no old data/results.
    old = ROOT / k.NUMERIC_SOURCE
    assert sha256(old.read_bytes()).hexdigest() == k.NUMERIC_SHA
    oldast = ast.parse(old.read_text(encoding="utf-8"))
    newast = ast.parse((BASE / "confirm_kernel.py").read_text(encoding="utf-8"))
    for name in ("_cdf_apply", "_ridge_predict"):

        def get(tree):
            return ast.dump(
                next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name),
                include_attributes=False,
            )

        assert get(oldast) == get(newast)
    assert list(k._cdf_apply(np.array([0.0, 0.0, 1.0]), np.array([-1.0, 0.0, 1.0, 2.0]))) == [
        0.0,
        1 / 3,
        5 / 6,
        1.0,
    ]
    checks.append("originalEX066 sourcehash/numericAST exact/ties")
    params = ParameterSet(
        {"confirmation_lookback": 120, "holding_sessions": 4, "ridge_alpha": 10.0}
    )
    runtime = a.ConfirmNet(params)
    raw = n.copy()
    rawbars = bars.copy()
    for col in ("Open", "High", "Low", "Close"):
        raw[col] /= 0.2803
        rawbars[col] /= 0.2803
    inputs = {"daily": d, "native_daily": raw, "intraday": rawbars, "execution": raw.iloc[:1]}
    actual = runtime.calculate_history(inputs, axis)
    pd.testing.assert_series_equal(
        actual.target_position, k.episode_history(scores, axis).target_position, check_exact=True
    )
    np.testing.assert_allclose(actual.net_forecast, scores, rtol=0, atol=1e-15, equal_nan=True)
    # Original fullnative request contains last execution day without daily signal-HFQ tail.
    tailday = axis[-1] + pd.offsets.BDay(1)
    tail = raw.iloc[[-1]].copy()
    tail.Date = tailday
    tailbars = rawbars.iloc[-8:].copy()
    tailbars.Date = tailbars.Date + pd.Timedelta(days=(tailday - axis[-1]).days)
    withtail = dict(
        inputs,
        native_daily=pd.concat([raw, tail], ignore_index=True),
        intraday=pd.concat([rawbars, tailbars], ignore_index=True),
    )
    tailactual = runtime.calculate_history(withtail, axis)
    pd.testing.assert_frame_equal(actual, tailactual, check_exact=True)
    assert actual.index.unit == "ns"
    # Metadata-only artificial scope verifies promoted native request identities.
    from datetime import date
    from strategy_runtime import TradableWindow

    window = TradableWindow(date(2020, 1, 2), date(2026, 9, 30))
    calendar = tuple(t.date() for t in pd.bdate_range("2019-01-07", "2026-09-30"))
    scope = runtime.derive_calculation_scope(window, calendar)
    assert (
        scope.inputs["native_daily"].start == "2020-01-01"
    )  # artificial weekday calendar prior, not market calendar
    assert (
        scope.inputs["native_daily"].end == "2026-09-30"
        and scope.inputs["native_daily"].coverage is None
    )
    assert (
        scope.inputs["intraday"].start == "2020-01-02"
        and scope.inputs["intraday"].frequency == "30m"
        and scope.inputs["intraday"].coverage is None
    )
    assert runtime.calendar_request(window).start == "2019-01-07"
    checks.append("adapter fullhistory and legal five input exact-request promotion metadata")
    packing = BASE / "artificial_packing" / "strategy_runtime"
    (packing / "strategies").mkdir(parents=True, exist_ok=True)
    for name in ("confirm_kernel.py", "confirm_net.py"):
        (packing / "strategies" / name).write_bytes((BASE / name).read_bytes())
    files = ["strategies/confirm_kernel.py", "strategies/confirm_net.py"]
    payload = {
        "parameters": dict(params.values),
        "runtime": {
            "module": "strategy_runtime.strategies.confirm_net",
            "qualname": "ConfirmNet",
            "contract_version": 1,
            "source_files": files,
            "source_sha256": implementation_sha256(files, source_root=packing),
        },
    }
    candidate = StrategyCandidate("S013", "C9990", payload, packing)
    definition = StrategyRuntime(ROOT / "strategies").describe(candidate)
    assert len(definition.inputs.requirements) == 5
    from importlib.metadata import version
    from strategy_runtime import ImplementationDependency

    identity = StrategyRuntime(ROOT / "strategies").identify(
        candidate,
        dependencies=tuple(
            ImplementationDependency(name, version(name))
            for name in ("numpy", "pandas", "czsc-strategy-runtime")
        ),
    )
    assert len(identity.content_sha256) == 64
    # Allowed request/calendar metadata only, never any actual price/asset input.
    meta = json.loads((BASE / "original_binding_metadata.json").read_text(encoding="utf-8"))
    from datetime import date
    from dataflows import DataRequest, DataCoverageRequirement

    def request(obj):
        return DataRequest(
            obj["dataset"],
            obj["symbol"],
            obj["start"],
            obj["end"],
            obj["required_cutoff"],
            obj["frequency"],
            coverage=None
            if obj["coverage"] is None
            else DataCoverageRequirement(**obj["coverage"]),
        )

    nativeplan = meta["input_bindings"]["full"]["plan"]
    dates_actual = tuple(date.fromisoformat(x) for x in nativeplan["calendar_dates"])
    exactscope = runtime.derive_calculation_scope(window, dates_actual)
    for name in ("daily", "execution"):
        assert exactscope.inputs[name] == request(nativeplan["requests"][name])
    assert runtime.calendar_request(window) == request(nativeplan["requests"]["calendar"])
    assert exactscope.inputs["native_daily"] == request(
        meta["execution_requests"]["execution_daily"]
    )
    assert exactscope.inputs["intraday"] == request(meta["execution_requests"]["execution_30m"])
    assert dict(exactscope.signal_dates) == {
        date.fromisoformat(k): date.fromisoformat(v) for k, v in nativeplan["signal_dates"].items()
    }
    checks.append("public SRT authenticated namespace loader twofiles packing")
    refusals = 0
    for p in ((39, 4, 10.0), (120, 0, 10.0), (120, 4, 0.0), (120, 4, 10)):
        try:
            k.parameters(*p)
        except ValueError:
            refusals += 1
        else:
            raise AssertionError("invalidparameter")
    wrong = bars.copy()
    wrong.loc[0, "Date"] += pd.Timedelta(minutes=1)
    try:
        k.rebuild(d, n, wrong, axis)
    except ValueError:
        refusals += 1
    else:
        raise AssertionError("wrongclock")
    checks.append("full parameter domains/clock refusal withoutfallback")
    return {
        "status": "PASS",
        "checks": checks,
        "check_count": len(checks),
        "refusals": refusals,
        "source_sha256": {
            n: sha256((BASE / n).read_bytes()).hexdigest()
            for n in ("confirm_kernel.py", "confirm_net.py", "focused_checks.py")
        },
        "real_data_reads": 0,
        "real_statistics": 0,
        "prepare": 0,
        "evaluate": 0,
        "allocation": 0,
        "publication": 0,
        "provider": 0,
    }


if __name__ == "__main__":
    result = run()
    (BASE / "focused_checks.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
