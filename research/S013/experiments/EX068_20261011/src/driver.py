"""Prospectively declared S013 intraday-order study; zero new accounts."""
from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
import order_component
import late_recovery_component
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "utf-8")


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def public(value):
    ref = EvidenceRef.from_dict(value)
    if ref.experiment.strategy_id != "S013":
        raise ValueError("S013 only")
    return ref.resolve(ROOT)


def put(ctx, exp, path):
    path = Path(path)
    return publish_evidence(ctx, MaterialEvidenceWrite(exp, path.stem.replace("_", "-"), path.read_bytes(),
        {".py": "text/x-python", ".csv": "text/csv"}.get(path.suffix, "application/json"), path.suffix[1:])).to_dict()


def frame(path):
    f = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    f.index = pd.to_datetime(f.index).as_unit("ns")
    return f


def numerical(df):
    rename = {"Date": "dt", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "vol", "Amount": "amount"}
    value = df.rename(columns=rename).loc[:, list(rename.values())].copy()
    value.dt = pd.to_datetime(value.dt)
    value.attrs = {}
    return value


def declare():
    assert read(WORK / "focused_checks.json")["status"] == "PASS"
    assert read(WORK / "statistics_checks.json")["status"] == "PASS"
    prior = ROOT / "research/S013/experiments/EX066_20261011"
    assert read(prior / "protocols/delivery_validation.json")["status"] == "PASS"
    refs = read(prior / "protocols/final_evidence_references.json")
    inputs = {n: refs[n] for n in ("features.csv", "labels.csv", "opportunity.csv", "input_checks.json", "verification.json")}
    old61 = read(ROOT / "research/S013/experiments/EX061_20261011/protocols/result_references.json")
    inputs["ex061_features"] = old61["features.csv"]
    for ref in inputs.values():
        public(ref)
    sources = ("order_component.py", "focused_checks.py", "prepare_statistics.py", "late_recovery_component.py", "opportunity_statistics.py", "statistics_checks.py", "driver.py")
    ctx = common.context(1)
    exp = create_experiment(ctx, ExperimentRequest("日内下跌顺序与持续性的增量检验", "同样旧量价信息、尾盘状态及全天涨跌总量下，早段下跌占比与连续下跌段占比能否预测下一开盘后的扣费收益？", date(2026, 10, 11)))
    write(WORK / "experiment.json", exp.to_dict())
    plan = {
        "experiment": exp.to_dict(), "role": "RSCH", "stage": 2,
        "authorization": "认同你的观点。请你重新设定研究目标，并自主研究",
        "economic_targets_unchanged": True, "new_hard_gates": False,
        "objective": "研究新路径顺序观察的增量；有依据才支持原四门达标与抗扰动策略，组件统计不代表账户收益",
        "selection_history": "已见EX060/061/064失败与EX066/067条件拆分结果后提出；非独立封存验证，不逆转方向或扫阈值挽救结果",
        "feature_method": order_component.METHOD, "statistics": stats.METHOD,
        "hypothesis_signs": {"early_down_share": "positive return4", "max_down_run_share": "negative return4"},
        "primary": ["return_4", "downside_4"], "auxiliary": ["return_8", "downside_8"],
        "controls": list(stats.CONTROLS),
        "fixed_scopes": ["all", "past20_declining", "flat_eligible", "declining_flat"],
        "scope_definition": "past20_declining=original momentum20<0; flat_eligible=original confirmation_opportunity, verified eligible AND NOT previous original target_position; signal state is not actual account quantity",
        "labels": "EX066 fixed4/8 net-nextOpen proxy and paired downside exact reuse; .999/1.001 fee adjustment, no native limit/lot fills",
        "input_references": inputs,
        "native_ref": read(common.RUNS / "account_references.json")["N0"],
        "source_files": {n: digest(WORK / n) for n in sources},
        "common_sha256": digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py"),
        "ex061_component_sha256": digest(ROOT / "research/S013/experiments/EX061_20261011/src/late_recovery_component.py"),
        "ex067_plan_sha256": digest(ROOT / "research/S013/experiments/EX067_20261011/protocols/plan.json"),
        "predecessors": [read(ROOT / f"research/S013/deliveries/{s}/{r}/receipt.json")["reference"] for s, r in (("MANDATE", 6), ("COMPONENTS", 5), ("CANDIDATES", 57))],
        "stop": "缺乏一致控制后增量或跨年模型退化则停止两条固定表达；保留全部薄组及失败；不据事后结果反向或挑期限",
        "boundaries": "S013既有510500.SH至2026-09-30及原预热，既有公开数据请求只读，无外部provider/封存/跨族/DEV/PTE/生产/账户/参数搜索/32点",
        "limitations": "首19日原控制缺失保留；零值/并列分位可能重叠，须披露；已见开发池；历史发布修订未验证；纯价格路径不能称资金流",
    }
    write(WORK / "plan.json", plan)
    published = {}
    for n in (*sources, "focused_checks.json", "statistics_checks.json", "method.json", "plan.json"):
        published[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src").mkdir(exist_ok=True)
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    write(exp.resolve(ROOT) / "protocols/method_references.json", published)
    print({"declared": exp.experiment_id, "accounts": 0}, flush=True)


def study():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    plan = read(WORK / "plan.json")
    assert not (WORK / "input_checks.json").exists(), "No automatic rerun"
    for n, sha in plan["source_files"].items():
        assert digest(WORK / n) == sha, n
    assert digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py") == plan["common_sha256"]
    assert digest(WORK / "late_recovery_component.py") == plan["ex061_component_sha256"]
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    assert read(public(refs["plan.json"])) == plan
    ctx = common.context(1)
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    assert serialize_evaluation_evidence(bound, result) == read(public(plan["native_ref"]))
    assert bound.strategy.candidate_id == "C8880"
    ed = bound.execution_data
    fetched, identities = {}, {}
    for key in ("adjusted_daily", "execution_daily", "execution_30m"):
        got = ctx.data.fetch(ed.requests[key], prepared=ed.prepared)
        assert got.ready, key
        fetched[key] = numerical(got.dataframe)
        identities[key] = {"content_sha256": got.identity.content_sha256, "request": str(ed.requests[key])}
    intra = ed.pricing.apply(fetched["execution_30m"], raw_daily=fetched["execution_daily"], adjusted_daily=fetched["adjusted_daily"])
    a, b = intra.reset_index(drop=True).copy(), ed.execution_intraday.reset_index(drop=True).copy()
    a.attrs, b.attrs = {}, {}
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    bars = intra.rename(columns={"open": "Open", "close": "Close", "vol": "Volume"}).set_index("dt")[["Open", "Close", "Volume"]]
    bars.index = bars.index.as_unit("ns")
    sessions = pd.DatetimeIndex(pd.to_datetime(ed.evaluation_sessions)).normalize().as_unit("ns")
    observation = order_component.build_features(bars)
    pd.testing.assert_index_equal(observation.index, sessions, check_names=False)
    old61 = frame(public(plan["input_references"]["ex061_features"]))
    old66 = frame(public(plan["input_references"]["features.csv"]))
    old_tail = late_recovery_component.build_features(bars).reindex(old61.index)
    for name in late_recovery_component.FEATURES:
        pd.testing.assert_series_equal(old_tail[name], old61[name], check_names=False, check_exact=True)
    pd.testing.assert_series_equal(-old66.late_weakness, old61.late_recovery, check_names=False, check_exact=True)
    pd.testing.assert_series_equal(-old66.early_reclaim_weakness, old61.early_volume_reclaim, check_names=False, check_exact=True)
    for name in stats.CONTROLS[:14]:
        pd.testing.assert_series_equal(old66[name], old61[name], check_exact=True)
    features = old66.loc[:, list(stats.CONTROLS[:14])].join(old61[list(late_recovery_component.FEATURES)]).join(observation)
    features = features.loc[:, [*stats.CONTROLS, *stats.COMPONENTS]]
    labels = frame(public(plan["input_references"]["labels.csv"]))
    for name in labels:
        if name.startswith("label_end_"):
            labels[name] = pd.to_datetime(labels[name])
    assert len(features) == 1635 and features.index.equals(labels.index)
    decisions = result.runs[0].execution.decisions.copy()
    decisions.index = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).as_unit("ns")
    eligible = decisions.entry_eligible.astype(bool).reindex(features.index)
    flat = decisions.confirmation_opportunity.astype(bool).reindex(features.index)
    prior_holding = decisions.target_position.shift(1, fill_value=0).astype(bool).reindex(features.index)
    np.testing.assert_array_equal(flat, eligible & ~prior_holding)
    old_eligible = frame(public(plan["input_references"]["opportunity.csv"])).iloc[:, 0]
    pd.testing.assert_series_equal(eligible, old_eligible, check_names=False)
    scopes = pd.DataFrame({"all": True, "past20_declining": features.momentum20.lt(0), "flat_eligible": flat,
                           "declining_flat": flat & features.momentum20.lt(0)}, index=features.index)
    assert not common.SOURCE_CALLS
    write(WORK / "input_checks.json", {"status": "PASS", "native_exact": True, "priced_intraday_exact": True,
        "ex061_recomputed_exact": True, "ex066_old_controls_exact": True, "ex066_labels_exact_reuse": True,
        "identity": identities, "signal_n": len(features), "session_n": len(sessions),
        "scope_counts": {k: int(scopes[k].sum()) for k in scopes}, "provider_calls": common.SOURCE_CALLS,
        "no_down_n": int(features.total_down.eq(0).sum()), "zero_counts": {k: int(features[k].eq(0).sum()) for k in order_component.FEATURES},
        "feature_missing": features.isna().sum().to_dict(), "accounts": 0})
    features.to_csv(WORK / "features.csv", index_label="signal_date", float_format="%.17g")
    scopes.to_csv(WORK / "scopes.csv", index_label="signal_date")
    (WORK / "labels.csv").write_bytes(public(plan["input_references"]["labels.csv"]).read_bytes())
    for n in ("input_checks.json", "features.csv", "scopes.csv", "labels.csv"):
        refs[n] = put(ctx, exp, WORK / n)
    write(exp.resolve(ROOT) / "protocols/input_references.json", refs)
    print({"inputs_authenticated": True, "scopes": {c: int(scopes[c].sum()) for c in scopes}}, flush=True)
    outcome = stats.analyze(features, labels, scopes)
    write(WORK / "statistics.json", outcome)
    refs["statistics.json"] = put(ctx, exp, WORK / "statistics.json")
    write(exp.resolve(ROOT) / "protocols/result_references.json", refs)
    print({"statistics_complete": exp.experiment_id, "accounts": 0}, flush=True)


def verify():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    features, labels, scopes = (frame(public(refs[n])) for n in ("features.csv", "labels.csv", "scopes.csv"))
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
                    np.testing.assert_allclose(reported["spearman"]["value"], spearmanr(x, y).statistic, rtol=0, atol=1e-13)
                checks += 1
                controls = features.loc[:, stats.CONTROLS]
                partial_good = good & np.isfinite(controls).all(axis=1)
                x, y = features.loc[partial_good, component].to_numpy(), labels.loc[partial_good, label].to_numpy()
                assert reported["partial_rank_ic"]["n"] == len(x)
                if len(x) >= 20 and np.ptp(x) > 0 and np.ptp(y) > 0:
                    xr, yr = rankdata(x), rankdata(y)
                    design = np.column_stack([np.ones(len(x)), *(rankdata(v) for v in controls.loc[partial_good].to_numpy().T)])
                    xr -= design @ np.linalg.lstsq(design, xr, rcond=None)[0]
                    yr -= design @ np.linalg.lstsq(design, yr, rcond=None)[0]
                    if reported["partial_rank_ic"]["value"] is not None:
                        np.testing.assert_allclose(reported["partial_rank_ic"]["value"], np.corrcoef(xr, yr)[0, 1], rtol=0, atol=1e-12)
                checks += 1
            finite = np.isfinite(features).all(axis=1).to_numpy() & np.isfinite(labels[label]).to_numpy()
            for year, row in block["walk_forward"]["yearly"].items():
                first = features.index[features.index.year == int(year)][0]
                train = mask & finite & (features.index.year >= 2020) & (features.index.year < int(year)) & (ends < first).to_numpy()
                test = mask & finite & (features.index.year == int(year))
                assert row["common_train_n"] == int(train.sum()) and row["common_test_n"] == int(test.sum())
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
                    np.testing.assert_allclose(aggregate["mse"], np.mean((truth - predicted) ** 2), rtol=0, atol=1e-15)
                checks += 1
    assert scopes.declining_flat.equals(scopes.past20_declining & scopes.flat_eligible)
    write(WORK / "verification.json", {"status": "PASS", "checks": checks,
        "scope": "independent raw/partial ranks, mature common model rows, retained truth and MSE, causal scope membership; no bootstrap/model refit repetition",
        "new_accounts": 0, "scientific_judgment": "not made"})
    refs["verification.json"] = put(common.context(1), exp, WORK / "verification.json")
    write(exp.resolve(ROOT) / "protocols/verification_references.json", refs)
    print({"verification": "PASS", "checks": checks}, flush=True)


if __name__ == "__main__":
    {"declare": declare, "study": study, "verify": verify}[sys.argv[1]]()
