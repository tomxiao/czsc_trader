"""Prospectively declared S013 intraday-order study; zero new accounts."""

from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
import pressure_component
import opportunity_statistics as stats
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = Path(__file__).parent
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
import common  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def write(path, value):
    path = Path(path)
    if path.exists():
        raise ValueError("Immutable output already exists: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8"
    )


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013 only")
    return ref.resolve(ROOT)


def put(ctx, exp, path):
    path = Path(path)
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp,
            path.stem.replace("_", "-"),
            path.read_bytes(),
            {".py": "text/x-python", ".csv": "text/csv"}.get(path.suffix, "application/json"),
            path.suffix[1:],
        ),
    ).to_dict()


def frame(path):
    f = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    f.index = pd.to_datetime(f.index).as_unit("ns")
    return f


def numerical(df):
    rename = {
        "Date": "dt",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "vol",
        "Amount": "amount",
    }
    value = df.rename(columns=rename).loc[:, list(rename.values())].copy()
    value.dt = pd.to_datetime(value.dt)
    value.attrs = {}
    return value


def declare():
    assert read(WORK / "focused_checks.json")["status"] == "PASS"
    assert read(WORK / "statistics_checks.json")["status"] == "PASS"
    old68 = read(
        ROOT / "research/S013/experiments/EX068_20261011/protocols/verification_references.json"
    )
    assert read(public(old68["verification.json"]))["status"] == "PASS"
    old66 = read(
        ROOT / "research/S013/experiments/EX066_20261011/protocols/final_evidence_references.json"
    )
    inputs = {
        n: old68[n]
        for n in ("features.csv", "scopes.csv", "input_checks.json", "verification.json")
    }
    inputs["labels.csv"] = old66["labels.csv"]
    for ref in inputs.values():
        public(ref)
    sources = (
        "pressure_component.py",
        "focused_checks.py",
        "prepare_statistics.py",
        "prepare_driver.py",
        "opportunity_statistics.py",
        "statistics_checks.py",
        "driver.py",
    )
    ctx = common.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "跨日压力构成与短期伸展的增量检验",
            "固定四日波动标准化伸展及隔夜下跌占比，能否超出已有20项信息预测下一开盘后的扣费收益？",
            date(2026, 10, 11),
        ),
    )
    write(WORK / "experiment.json", exp.to_dict())
    plan = {
        "experiment": exp.to_dict(),
        "role": "RSCH",
        "stage": 2,
        "authorization": "认同你的观点。请你重新设定研究目标，并自主研究",
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
        "objective": "寻找扣费后做多盈利信息，为原四门与抗扰动目标提供组件证据，不把统计显著性或样本量变成经济硬门",
        "selection_history": "已见EX066-068机会供给、状态和顺序组件结果后的固定新假说；仍是反复研究开发池，不是封存验证",
        "feature_method": pressure_component.METHOD,
        "statistics": stats.METHOD,
        "hypothesis_signs": {
            "short_stretch4": "negative return4",
            "overnight_down_share4": "positive return4",
        },
        "primary": ["return_4", "downside_4"],
        "auxiliary": ["return_8", "downside_8"],
        "controls": list(stats.CONTROLS),
        "fixed_scopes": ["all", "past20_declining", "flat_eligible", "declining_flat"],
        "scope_definition": "EX068 exact scopes; original confirmation_opportunity=eligible AND NOT previous target_position, not actual filled quantity; declining=causal original20daymomentum<0",
        "labels": "EX0664/8 net-open labels .999/1.001 and paired downside unchanged byte reuse, not native limit/lot/account returns",
        "partial_residual_df": "OLS rank-control design includes intercept; compute actual design rank; n-rank(design)>=10 and original n>=20 required, otherwise explicit unavailable with rank/df; no +/-1 thin-phase claims; bootstrap500x40seed13 unchanged",
        "inputs": "EX06820 exact old observations, EX066labels, originalEX058native priced daily plus originalbound.input_bindings.full daily HFQ request2019-04-10..2026-09-29 including original warmup, only existing public assets",
        "price_units": "original public HFQ daily units, constant divide by original anchor.2803 only for overlap authentication; feature ratios and originalvol20 recomputed without rounding",
        "input_references": inputs,
        "native_ref": read(common.RUNS / "account_references.json")["N0"],
        "source_files": {n: digest(WORK / n) for n in sources},
        "common_sha256": digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py"),
        "ex068_plan_sha256": digest(
            ROOT / "research/S013/experiments/EX068_20261011/protocols/plan.json"
        ),
        "predecessors": [
            read(ROOT / f"research/S013/deliveries/{s}/{r}/receipt.json")["reference"]
            for s, r in (("MANDATE", 6), ("COMPONENTS", 5), ("CANDIDATES", 57))
        ],
        "stop": "无稳定增量则停止固定方向，不扫期限/窗口/方向/阈值；保留局部正反事实及样本不足",
        "boundaries": "仅S013现有数据至2026-09-30及原warmup，不新provider/外部/跨族/封存/DEV/PTE/生产/账户/参数搜索/32点",
        "limitations": "首19日旧控制缺失保留，零vol不可用；时间顺序非独立封存；市场价标签代理不含限价/整手；真实发布时间修订未验证",
    }
    write(WORK / "plan.json", plan)
    refs = {}
    for n in (
        *sources,
        "focused_checks.json",
        "statistics_checks.json",
        "method.json",
        "plan.json",
    ):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src").mkdir(exist_ok=True)
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    write(exp.resolve(ROOT) / "protocols/method_references.json", refs)
    print({"declared": exp.experiment_id, "accounts": 0}, flush=True)


def study():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    assert not (WORK / "input_checks.json").exists(), "No automatic rerun"
    for n, sha in plan["source_files"].items():
        assert digest(WORK / n) == sha, n
    assert (
        digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py")
        == plan["common_sha256"]
    )
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    assert read(public(refs["plan.json"])) == plan
    ctx = common.context(1)
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    assert serialize_evaluation_evidence(bound, result) == read(public(plan["native_ref"]))
    assert bound.strategy.candidate_id == "C8880"
    old = frame(public(plan["input_references"]["features.csv"]))
    features = old.loc[:, list(stats.CONTROLS)].copy()
    labels = frame(public(plan["input_references"]["labels.csv"]))
    for name in labels:
        if name.startswith("label_end_"):
            labels[name] = pd.to_datetime(labels[name])
    assert len(old) == 1635 and old.index.equals(labels.index)
    ed = bound.execution_data
    identity = {}
    got = ctx.data.fetch(
        bound.input_bindings["full"].plan.requests["daily"],
        prepared=bound.input_bindings["full"].prepared,
    )
    assert got.ready
    identity["srt_daily_hfq"] = {
        "content_sha256": got.identity.content_sha256,
        "request": str(bound.input_bindings["full"].plan.requests["daily"]),
    }
    daily = got.dataframe.set_index("Date")[["Open", "Close"]].copy()
    daily.index = pd.to_datetime(daily.index).as_unit("ns")
    assert daily.index[0] == pd.Timestamp("2019-04-10") and daily.index[-1] == old.index[-1]
    expected = ed.execution_daily.set_index("dt")
    expected.index = pd.to_datetime(expected.index).as_unit("ns")
    common_dates = daily.index.intersection(expected.index)
    anchor = ed.pricing.to_dict()["anchor_factor"]
    np.testing.assert_allclose(
        daily.loc[common_dates, ["Open", "Close"]].to_numpy() / anchor,
        expected.loc[common_dates, ["open", "close"]].to_numpy(),
        rtol=1e-13,
        atol=1e-13,
    )
    for key in ("adjusted_daily", "execution_daily"):
        current = ctx.data.fetch(ed.requests[key], prepared=ed.prepared)
        assert current.ready
        identity[key] = {
            "content_sha256": current.identity.content_sha256,
            "request": str(ed.requests[key]),
        }
        identity[key]["data"] = numerical(current.dataframe)
    priced = ed.pricing.apply(
        identity["execution_daily"].pop("data"),
        raw_daily=numerical(
            ctx.data.fetch(ed.requests["execution_daily"], prepared=ed.prepared).dataframe
        ),
        adjusted_daily=identity["adjusted_daily"].pop("data"),
    )
    a, b = priced.reset_index(drop=True).copy(), ed.execution_daily.reset_index(drop=True).copy()
    a.attrs, b.attrs = {}, {}
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    observations = pressure_component.build_features(daily).reindex(old.index)
    pd.testing.assert_series_equal(
        observations.volatility20, old.volatility20, check_names=False, check_exact=True
    )
    features = features.join(observations[list(pressure_component.FEATURES)]).loc[
        :, [*stats.CONTROLS, *stats.COMPONENTS]
    ]
    decisions = result.runs[0].execution.decisions.copy()
    decisions.index = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).as_unit("ns")
    flat = decisions.confirmation_opportunity.astype(bool).reindex(old.index)
    eligible = decisions.entry_eligible.astype(bool).reindex(old.index)
    before = decisions.target_position.shift(1, fill_value=0).astype(bool).reindex(old.index)
    np.testing.assert_array_equal(flat, eligible & ~before)
    scopes = pd.DataFrame(
        {
            "all": True,
            "past20_declining": old.momentum20.lt(0),
            "flat_eligible": flat,
            "declining_flat": flat & old.momentum20.lt(0),
        },
        index=old.index,
    )
    pd.testing.assert_frame_equal(
        scopes, frame(public(plan["input_references"]["scopes.csv"])), check_exact=True
    )
    assert not common.SOURCE_CALLS
    write(
        WORK / "input_checks.json",
        {
            "status": "PASS",
            "native_exact": True,
            "priced_daily_exact": True,
            "warmup_hfq_overlap_anchor_allclose": True,
            "original_volatility20_exact": True,
            "original20controls_exact": True,
            "ex066labels_byte_reuse": True,
            "identity": identity,
            "signal_n": len(features),
            "warmup_price_rows": len(daily),
            "scope_counts": {c: int(scopes[c].sum()) for c in scopes},
            "unavailable_stretch": observations.short_stretch_reason.value_counts().to_dict(),
            "feature_missing": features.isna().sum().to_dict(),
            "provider_calls": common.SOURCE_CALLS,
            "accounts": 0,
        },
    )
    features.to_csv(WORK / "features.csv", index_label="signal_date", float_format="%.17g")
    observations.to_csv(WORK / "observations.csv", index_label="signal_date", float_format="%.17g")
    daily.to_csv(WORK / "daily_prices.csv", index_label="signal_date", float_format="%.17g")
    scopes.to_csv(WORK / "scopes.csv", index_label="signal_date")
    (WORK / "labels.csv").write_bytes(public(plan["input_references"]["labels.csv"]).read_bytes())
    for n in (
        "input_checks.json",
        "features.csv",
        "observations.csv",
        "daily_prices.csv",
        "scopes.csv",
        "labels.csv",
    ):
        refs[n] = put(ctx, exp, WORK / n)
    write(exp.resolve(ROOT) / "protocols/input_references.json", refs)
    print(
        {
            "inputs_authenticated": True,
            "scopes": {c: int(scopes[c].sum()) for c in scopes},
            "warmup": len(daily),
        },
        flush=True,
    )
    outcome = stats.analyze(features, labels, scopes)
    write(WORK / "statistics.json", outcome)
    refs["statistics.json"] = put(ctx, exp, WORK / "statistics.json")
    write(exp.resolve(ROOT) / "protocols/result_references.json", refs)
    print({"statistics_complete": exp.experiment_id, "accounts": 0}, flush=True)


def verify():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    features, labels, scopes = (
        frame(public(refs[n])) for n in ("features.csv", "labels.csv", "scopes.csv")
    )
    result = read(public(refs["statistics.json"]))
    checks = 0
    for scope, panel in result["scopes"].items():
        mask = scopes[scope].to_numpy(bool)
        assert panel["eligible_n"] == int(mask.sum())
        for label, block in panel["labels"].items():
            ends = pd.to_datetime(labels["label_end_" + label])
            for component, reported in block["components"].items():
                good = mask & np.isfinite(features[component]) & np.isfinite(labels[label])
                x, y = features.loc[good, component].to_numpy(), labels.loc[good, label].to_numpy()
                assert reported["spearman"]["n"] == len(x)
                if len(x) >= 20 and np.ptp(x) > 0 and np.ptp(y) > 0:
                    np.testing.assert_allclose(
                        reported["spearman"]["value"], spearmanr(x, y).statistic, rtol=0, atol=1e-13
                    )
                checks += 1
                controls = features.loc[:, stats.CONTROLS]
                partial_good = good & np.isfinite(controls).all(axis=1)
                x, y = (
                    features.loc[partial_good, component].to_numpy(),
                    labels.loc[partial_good, label].to_numpy(),
                )
                assert reported["partial_rank_ic"]["n"] == len(x)
                partial = reported["partial_rank_ic"]
                design_check = np.column_stack(
                    [
                        np.ones(len(x)),
                        *(rankdata(v) for v in controls.loc[partial_good].to_numpy().T),
                    ]
                )
                rank = int(np.linalg.matrix_rank(design_check)) if len(x) else 0
                assert partial["design_rank"] == rank and partial["residual_df"] == len(x) - rank
                if len(x) - rank < 10:
                    assert (
                        partial["value"] is None and partial["reason"] == "INSUFFICIENT_RESIDUAL_DF"
                    )
                if len(x) >= 20 and np.ptp(x) > 0 and np.ptp(y) > 0:
                    xr, yr = rankdata(x), rankdata(y)
                    design = np.column_stack(
                        [
                            np.ones(len(x)),
                            *(rankdata(v) for v in controls.loc[partial_good].to_numpy().T),
                        ]
                    )
                    xr -= design @ np.linalg.lstsq(design, xr, rcond=None)[0]
                    yr -= design @ np.linalg.lstsq(design, yr, rcond=None)[0]
                    if reported["partial_rank_ic"]["value"] is not None:
                        np.testing.assert_allclose(
                            reported["partial_rank_ic"]["value"],
                            np.corrcoef(xr, yr)[0, 1],
                            rtol=0,
                            atol=1e-12,
                        )
                checks += 1
            finite = (
                np.isfinite(features).all(axis=1).to_numpy() & np.isfinite(labels[label]).to_numpy()
            )
            for year, row in block["walk_forward"]["yearly"].items():
                first = features.index[features.index.year == int(year)][0]
                train = (
                    mask
                    & finite
                    & (features.index.year >= 2020)
                    & (features.index.year < int(year))
                    & (ends < first).to_numpy()
                )
                test = mask & finite & (features.index.year == int(year))
                assert row["common_train_n"] == int(train.sum()) and row["common_test_n"] == int(
                    test.sum()
                )
                if row["latest_train_label_end"] is not None:
                    assert pd.Timestamp(row["latest_train_label_end"]) == ends[train].max() < first
                checks += 1
            for model, records in block["walk_forward"]["prediction_records"].items():
                dates = pd.DatetimeIndex(pd.to_datetime([v["signaldate"] for v in records]))
                truth = np.array([v["target"] for v in records])
                predicted = np.array([v["prediction"] for v in records])
                np.testing.assert_array_equal(truth, labels.loc[dates, label].to_numpy())
                aggregate = block["walk_forward"]["aggregate_models"][model]
                assert aggregate["n"] == len(records)
                if len(records) >= 20:
                    np.testing.assert_allclose(
                        aggregate["mse"], np.mean((truth - predicted) ** 2), rtol=0, atol=1e-15
                    )
                checks += 1
    # Independently verify DF metadata for every year and every nonoverlapping phase.
    for scope, panel in result["scopes"].items():
        scope_mask = scopes[scope].to_numpy(bool)
        for label, block in panel["labels"].items():
            for component, reported in block["components"].items():
                for category in ("yearly", "nonoverlap_phases"):
                    for key, row in reported[category].items():
                        submask = scope_mask & (
                            (features.index.year == int(key))
                            if category == "yearly"
                            else (
                                np.arange(len(features)) % (stats.HORIZONS[label] + 1) == int(key)
                            )
                        )
                        valid = (
                            submask
                            & np.isfinite(features[component])
                            & np.isfinite(labels[label])
                            & np.isfinite(features.loc[:, stats.CONTROLS]).all(axis=1)
                        )
                        values = features.loc[valid, stats.CONTROLS].to_numpy()
                        design = np.column_stack(
                            [np.ones(len(values)), *(rankdata(v) for v in values.T)]
                        )
                        rank = int(np.linalg.matrix_rank(design)) if len(values) else 0
                        observed = row["partial_rank_ic"]
                        assert (
                            observed["n"] == len(values)
                            and observed["design_rank"] == rank
                            and observed["residual_df"] == len(values) - rank
                        )
                        if len(values) - rank < 10:
                            assert (
                                observed["value"] is None
                                and observed["reason"] == "INSUFFICIENT_RESIDUAL_DF"
                            )
                        checks += 1
    prices = frame(public(refs["daily_prices.csv"]))
    observations = frame(public(refs["observations.csv"]))
    for dt in features.index:
        i = prices.index.get_loc(dt)
        assert i >= 20
        close = prices.Close.to_numpy()
        opening = prices.Open.to_numpy()
        vol = np.std(close[i - 19 : i + 1] / close[i - 20 : i] - 1.0, ddof=1)
        expected = np.log(close[i] / close[i - 4]) / (2.0 * vol) if vol > 0.0 else np.nan
        np.testing.assert_allclose(
            features.loc[dt, "short_stretch4"], expected, rtol=1e-11, atol=1e-11
        )
        overnight = sum(max(-np.log(opening[j] / close[j - 1]), 0.0) for j in range(i - 3, i + 1))
        intraday = sum(max(-np.log(close[j] / opening[j]), 0.0) for j in range(i - 3, i + 1))
        expected_share = overnight / (overnight + intraday) if overnight + intraday > 0.0 else 0.0
        np.testing.assert_allclose(
            features.loc[dt, "overnight_down_share4"], expected_share, rtol=1e-10, atol=1e-10
        )
        assert observations.loc[dt, "short_stretch_reason"] == (
            "AVAILABLE" if vol > 0.0 else "ZERO_VOLATILITY"
        )
        checks += 2
    plan = read(WORK / "plan.json")
    assert (WORK / "labels.csv").read_bytes() == public(
        plan["input_references"]["labels.csv"]
    ).read_bytes()
    assert scopes.declining_flat.equals(scopes.past20_declining & scopes.flat_eligible)
    write(
        WORK / "verification.json",
        {
            "status": "PASS",
            "checks": checks,
            "scope": "independent raw/partial ranks and DF including phases/years, mature model rows, truth/MSE, four-session endpoint formulas, unchanged fee-label bytes; no bootstrap/refit repeats",
            "new_accounts": 0,
            "scientific_judgment": "not made",
        },
    )
    refs["verification.json"] = put(common.context(1), exp, WORK / "verification.json")
    write(exp.resolve(ROOT) / "protocols/verification_references.json", refs)
    print({"verification": "PASS", "checks": checks}, flush=True)


if __name__ == "__main__":
    {"declare": declare, "study": study, "verify": verify}[sys.argv[1]]()
