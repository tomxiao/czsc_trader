"""Predeclared scope audit and conditional component responsibility study."""

from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import opportunity_statistics as stats
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
import common  # noqa:E402


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    if path.exists():
        raise ValueError("Immutable output exists " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
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
            {".py": "text/x-python", ".csv": "text/csv", ".md": "text/markdown"}.get(
                path.suffix, "application/json"
            ),
            path.suffix[1:],
        ),
    ).to_dict()


def frame(path):
    f = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    f.index = pd.to_datetime(f.index).as_unit("ns")
    return f


def scope_frame(eligible, flat, bear):
    if not eligible.index.equals(flat.index) or not eligible.index.equals(bear.index):
        raise ValueError("Aligned flags")
    for series in (eligible, flat, bear):
        if series.dtype != bool or series.isna().any():
            raise ValueError("Strict bool flags")
    if (flat & ~eligible).any():
        raise ValueError("Actual flat opportunity must be eligible")
    held = eligible & ~flat
    out = pd.DataFrame(
        {
            "flat_eligible": flat,
            "held_eligible": held,
            "declining_flat": flat & bear,
            "declining_held": held & bear,
        }
    )
    assert not (out.flat_eligible & out.held_eligible).any()
    np.testing.assert_array_equal(out.flat_eligible | out.held_eligible, eligible)
    return out


def synthetic():
    index = pd.bdate_range("2020-01-01", periods=120).append(
        pd.bdate_range("2021-01-01", periods=35)
    )

    def flags(a):
        return pd.Series(a, index=index, dtype=bool)

    eligible = flags(np.arange(len(index)) % 3 != 0)
    flat = eligible & flags(np.arange(len(index)) % 2 == 0)
    bear = flags(np.arange(len(index)) % 5 < 3)
    split = scope_frame(eligible, flat, bear)
    assert split.flat_eligible.sum() + split.held_eligible.sum() == eligible.sum()
    rng = np.random.default_rng(13)
    features = pd.DataFrame(
        rng.normal(size=(len(index), 15)), index=index, columns=[*stats.CONTROLS, *stats.COMPONENTS]
    )
    y = features.late_weakness.to_numpy() * 0.01
    ends = pd.Series(index + pd.Timedelta(days=10), index=index)
    out = stats._walk_forward(index, features, y, ends, np.ones(len(index), bool))
    assert tuple(out["aggregate_models"]) == ("controls", "controls+late")
    assert out["yearly"]["2021"]["latest_train_label_end"] < index[120].isoformat()
    assert tuple(stats.HORIZONS) == ("return_4", "return_8", "downside_4", "downside_8")
    write(
        WORK / "checks.json",
        {
            "status": "PASS",
            "scope": "boolean partition, one-component same-row two-model mature training, fixed4/8 labels",
            "checks": 6,
            "market_data_read": False,
        },
    )


def declare():
    assert read(WORK / "checks.json")["status"] == "PASS"
    prior = ROOT / "research/S013/experiments/EX066_20261011"
    assert read(prior / "protocols/delivery_validation.json")["status"] == "PASS"
    refs = read(prior / "protocols/final_evidence_references.json")
    inputs = {
        n: refs[n]
        for n in (
            "features.csv",
            "labels.csv",
            "opportunity.csv",
            "input_checks.json",
            "judgment.json",
            "statistics.json",
        )
    }
    for ref in inputs.values():
        public(ref)
    ctx = common.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "空仓入场机会与持仓恢复的条件拆分",
            "EX066下跌资格子集的尾盘弱势增量，是否在真正空仓可以买入的样本中仍成立，或主要来自持仓恢复？",
            date(2026, 10, 11),
        ),
    )
    write(WORK / "experiment.json", exp.to_dict())
    source_names = ("prepare.py", "opportunity_statistics.py", "driver.py")
    plan = {
        "experiment": exp.to_dict(),
        "role": "RSCH",
        "stage": 2,
        "authorization": "认同你的观点。请你重新设定研究目标，并自主研究",
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
        "objective": "辨明条件性盈利信息的职责；有真实空仓增量才考虑入场机制；持仓恢复线索不能直接作为入场过滤或卖出信号。",
        "inputs": inputs,
        "source_files": {n: digest(WORK / n) for n in source_names},
        "common_sha256": digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py"),
        "state_definition": "原entry_eligible=range/momentum/(ACF or recovery) evenwhile holding; 原confirmation_opportunity=not holding AND eligible. Independent check uses previous original target_position to verify not holding; not actual account quantity.",
        "fixed_scopes": ["flat_eligible", "held_eligible", "declining_flat", "declining_held"],
        "declining": "原信号过去20日momentum<0，不等同全年亏损；所有年份保留。",
        "component": "only late_weakness=-EX061 last60min logreturn; earlyreclaim stopped, not re-tested",
        "statistics": stats.METHOD,
        "common_predictor_transfer": "并行复用EX066机会池/下跌资格池controls与controls+late的已留存逐年预测及同一训练Q25/Q75，在真实空仓/持仓两组分别评价；不重新拟合，不以组结果重选阈值。独立小组拟合与共用模型分组结论分别呈现。",
        "controls": list(stats.CONTROLS),
        "labels": "精确复用EX0664/8日净开盘收益代理和downside；已持仓组仍用同一假想fresh-entry标签，不称实际继续持有收益。",
        "selection_history": "已见EX066条件子集正面结果后提出；范围拆分是自适应开发研究，非独立验证；不扫阈值、期限或方向。",
        "stop": "若正证仅持仓组成立或空仓薄组不可验证，不能授予入场策略资格。持仓线索仅保留，实际退出须独立账户验证。",
        "boundaries": "仅S013既有数据及原合同；无新账户、32点、外部数据、封存、平台DEV/PTE/生产；原硬门保持。",
        "predecessors": [
            read(ROOT / f"research/S013/deliveries/{s}/{r}/receipt.json")["reference"]
            for s, r in [("MANDATE", 6), ("COMPONENTS", 5), ("CANDIDATES", 57)]
        ],
    }
    write(WORK / "plan.json", plan)
    published = {}
    for n in (*source_names, "checks.json", "plan.json"):
        published[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src").mkdir(exist_ok=True)
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    write(exp.resolve(ROOT) / "protocols/method_references.json", published)
    print({"declared": exp.experiment_id, "accounts": 0}, flush=True)


def study():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    ctx = common.context(1)
    plan = read(WORK / "plan.json")
    for n, sha in plan["source_files"].items():
        assert digest(WORK / n) == sha
    assert (
        digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py")
        == plan["common_sha256"]
    )
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    assert read(public(refs["plan.json"])) == plan
    features = frame(public(plan["inputs"]["features.csv"])).loc[
        :, [*stats.CONTROLS, *stats.COMPONENTS]
    ]
    target = frame(public(plan["inputs"]["labels.csv"]))
    for c in target.columns:
        if c.startswith("label_end_"):
            target[c] = pd.to_datetime(target[c])
    oldeligible = frame(public(plan["inputs"]["opportunity.csv"])).iloc[:, 0]
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    native = read(public(read(public(plan["inputs"]["input_checks.json"]))["native_ref"]))
    assert serialize_evaluation_evidence(bound, result) == native
    decisions = result.runs[0].execution.decisions.copy()
    decisions.index = pd.DatetimeIndex(pd.to_datetime(decisions.signal_date)).as_unit("ns")
    eligible = decisions.entry_eligible.astype(bool).reindex(features.index)
    flat = decisions.confirmation_opportunity.astype(bool).reindex(features.index)
    pd.testing.assert_series_equal(eligible, oldeligible, check_names=False)
    before = decisions.target_position.shift(1, fill_value=0).astype(bool).reindex(features.index)
    np.testing.assert_array_equal(flat, eligible & ~before)
    split = scope_frame(eligible, flat, features.momentum20.lt(0))
    certificate = {
        "status": "PASS",
        "native_serialization_exact": True,
        "original_eligible_exact": True,
        "not_holding_check": "confirmation_opportunity == eligible AND NOT previous target_position on all1635 rows",
        "counts": {c: int(split[c].sum()) for c in split},
        "native_signals_are_not_actual_quantity": True,
        "provider_calls": common.SOURCE_CALLS,
        "accounts": 0,
    }
    write(WORK / "input_checks.json", certificate)
    split.to_csv(WORK / "scopes.csv", index_label="signal_date")
    # Whole same-row feature/label snapshots copied from authenticated public refs.
    for n in ("features.csv", "labels.csv"):
        (WORK / n).write_bytes(public(plan["inputs"][n]).read_bytes())
    for n in ("input_checks.json", "scopes.csv", "features.csv", "labels.csv"):
        refs[n] = put(ctx, exp, WORK / n)
    write(exp.resolve(ROOT) / "protocols/input_references.json", refs)
    print({"state_partition": certificate["counts"], "native_exact": True}, flush=True)
    outcome = stats.analyze(features, target, split)
    write(WORK / "statistics.json", outcome)
    refs["statistics.json"] = put(ctx, exp, WORK / "statistics.json")
    pooled = read(public(plan["inputs"]["statistics.json"]))
    transfer = {}
    for pool, split_names in [
        ("opportunity", ("flat_eligible", "held_eligible")),
        ("declining_opportunity", ("declining_flat", "declining_held")),
    ]:
        for label in ("return_4", "return_8"):
            wf = pooled["scopes"][pool]["labels"][label]["walk_forward"]
            for scope in split_names:
                row = {"models": {}, "groups": {}}
                for model in ("controls", "controls+late"):
                    records = [
                        r
                        for r in wf["prediction_records"][model]
                        if bool(split.loc[pd.Timestamp(r["signaldate"]), scope])
                    ]
                    truth = np.array([r["target"] for r in records])
                    prediction = np.array([r["prediction"] for r in records])
                    np.testing.assert_array_equal(
                        truth,
                        target.loc[
                            pd.DatetimeIndex(pd.to_datetime([r["signaldate"] for r in records])),
                            label,
                        ].to_numpy(),
                    )
                    row["models"][model] = {
                        "n": len(records),
                        "mse": float(np.mean((truth - prediction) ** 2))
                        if len(records) >= 20
                        else None,
                        "records": records,
                    }
                for year, yblock in wf["yearly"].items():
                    group = yblock["groups"]["late_weakness"]
                    masks = (
                        split[scope] & (features.index.year == int(year)) & target[label].notna()
                    )
                    annual = {}
                    for key, comparison in [("low", "q25"), ("high", "q75")]:
                        threshold = group[comparison]
                        selected = (
                            masks
                            & (
                                (features.late_weakness <= threshold)
                                if key == "low"
                                else (features.late_weakness >= threshold)
                            )
                            if threshold is not None
                            else masks & False
                        )
                        n = int(selected.sum())
                        annual[key] = {
                            "n": n,
                            "mean": float(target.loc[selected, label].mean()) if n >= 20 else None,
                            "threshold": threshold,
                            "reason": None if n >= 20 else "INSUFFICIENT_GROUP_SAMPLE",
                        }
                    row["groups"][year] = annual
                transfer[f"{pool}/{label}/{scope}"] = row
    write(
        WORK / "common_transfer.json",
        {
            "method": "Original EX066 pooled matured-model forecasts and group thresholds split by actual original signal state, no refit",
            "results": transfer,
            "account_returns": False,
        },
    )
    refs["common_transfer.json"] = put(ctx, exp, WORK / "common_transfer.json")
    write(exp.resolve(ROOT) / "protocols/result_references.json", refs)
    print({"statistics_complete": True, "accounts": 0}, flush=True)


def verify():
    exp = ExperimentRef.from_dict(read(WORK / "experiment.json"))
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    features = frame(public(refs["features.csv"]))
    target = frame(public(refs["labels.csv"]))
    split = frame(public(refs["scopes.csv"]))
    result = read(public(refs["statistics.json"]))
    checks = 0
    for scope, panel in result["scopes"].items():
        mask = split[scope].to_numpy(bool)
        assert panel["eligible_n"] == int(mask.sum())
        for label, block in panel["labels"].items():
            good = mask & np.isfinite(target[label])
            x = features.loc[good, "late_weakness"].to_numpy()
            y = target.loc[good, label].to_numpy()
            observed = block["components"]["late_weakness"]["spearman"]
            assert observed["n"] == len(x)
            if len(x) >= 20:
                np.testing.assert_allclose(
                    observed["value"], spearmanr(x, y).statistic, atol=1e-13, rtol=0
                )
            checks += 1
            ends = pd.to_datetime(target["label_end_" + label])
            for year, row in block["walk_forward"]["yearly"].items():
                first = features.index[features.index.year == int(year)][0]
                finite = (
                    np.isfinite(features.loc[:, [*stats.CONTROLS, *stats.COMPONENTS]])
                    .all(axis=1)
                    .to_numpy()
                    & np.isfinite(target[label]).to_numpy()
                )
                train = (
                    mask
                    & finite
                    & (features.index.year >= 2020)
                    & (features.index.year < int(year))
                    & (ends < first).to_numpy()
                )
                test = mask & finite & (features.index.year == int(year))
                assert row["common_train_n"] == int(train.sum())
                assert row["common_test_n"] == int(test.sum())
                if row["latest_train_label_end"] is not None:
                    assert pd.Timestamp(row["latest_train_label_end"]) < first
                    assert pd.Timestamp(row["latest_train_label_end"]) == ends[train].max()
                checks += 1
            for model, records in block["walk_forward"]["prediction_records"].items():
                dates = pd.DatetimeIndex(pd.to_datetime([r["signaldate"] for r in records]))
                actual = np.array([r["target"] for r in records])
                pred = np.array([r["prediction"] for r in records])
                np.testing.assert_array_equal(actual, target.loc[dates, label].to_numpy())
                v = block["walk_forward"]["aggregate_models"][model]
                assert v["n"] == len(records)
                if len(records) >= 20:
                    np.testing.assert_allclose(
                        v["mse"], np.mean((actual - pred) ** 2), atol=1e-15, rtol=0
                    )
                checks += 1
    transfer = read(public(refs["common_transfer.json"]))
    prior = read(public(read(WORK / "plan.json")["inputs"]["statistics.json"]))
    for key, row in transfer["results"].items():
        pool, label, scope = key.split("/")
        wf = prior["scopes"][pool]["labels"][label]["walk_forward"]
        for model, observed in row["models"].items():
            expected = [
                r
                for r in wf["prediction_records"][model]
                if bool(split.loc[pd.Timestamp(r["signaldate"]), scope])
            ]
            assert observed["records"] == expected
            assert observed["n"] == len(expected)
            if len(expected) >= 20:
                np.testing.assert_allclose(
                    observed["mse"],
                    np.mean([(r["target"] - r["prediction"]) ** 2 for r in expected]),
                    atol=1e-15,
                    rtol=0,
                )
            else:
                assert observed["mse"] is None
            checks += 1
        for year, groups in row["groups"].items():
            old = wf["yearly"][year]["groups"]["late_weakness"]
            for group, q in [("low", "q25"), ("high", "q75")]:
                threshold = old[q]
                assert groups[group]["threshold"] == threshold
                mask = split[scope] & (features.index.year == int(year)) & target[label].notna()
                if threshold is None:
                    mask = mask & False
                else:
                    mask &= (
                        (features.late_weakness <= threshold)
                        if group == "low"
                        else (features.late_weakness >= threshold)
                    )
                n = int(mask.sum())
                assert groups[group]["n"] == n
                if n >= 20:
                    np.testing.assert_allclose(
                        groups[group]["mean"], target.loc[mask, label].mean(), atol=1e-15, rtol=0
                    )
                else:
                    assert groups[group]["mean"] is None
                checks += 1
    assert not (split.flat_eligible & split.held_eligible).any()
    write(
        WORK / "verification.json",
        {
            "status": "PASS",
            "checks": checks,
            "scope": "independent Spearman, retained truth/MSE, maturity bounds and partitions; inherited EX066labels already independently verified; no bootstrap/refit repeats",
            "new_accounts": 0,
        },
    )
    print({"verification": "PASS", "checks": checks}, flush=True)


if __name__ == "__main__":
    {"synthetic": synthetic, "declare": declare, "study": study, "verify": verify}[sys.argv[1]]()
