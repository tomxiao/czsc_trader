"""S013 prospective fee-aware opportunity capacity and reversal study."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from core import COST, HORIZONS, labels, supply
from verify_statistics import verify_statistics
from czsc_trader.application import create_experiment, ExperimentRequest, publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "research/S013/experiments/EX058_20261011/src"))
import common  # noqa: E402

spec = importlib.util.spec_from_file_location("s013_fee_stats", WORK / "opportunity_statistics.py")
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    if path.exists():
        raise ValueError("Immutable output exists: " + str(path))
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
    media = {".py": "text/x-python", ".csv": "text/csv", ".md": "text/markdown"}.get(
        path.suffix, "application/json"
    )
    return publish_evidence(
        ctx,
        MaterialEvidenceWrite(
            exp, path.stem.replace("_", "-"), path.read_bytes(), media, path.suffix[1:]
        ),
    ).to_dict()


def experiment():
    return ExperimentRef.from_dict(read(WORK / "experiment.json"))


def declare():
    if (WORK / "experiment.json").exists():
        raise ValueError("Already declared")
    assert read(WORK / "checks.json")["status"] == "PASS"
    assert read(WORK / "statistics_checks.json")["status"] == "PASS"
    assert (
        read(ROOT / "research/S013/experiments/EX065_20261011/protocols/delivery_validation.json")[
            "status"
        ]
        == "PASS"
    )
    assert (
        read(ROOT / "research/S013/experiments/EX064_20261011/protocols/delivery_validation.json")[
            "status"
        ]
        == "PASS"
    )
    oldrefs = read(
        ROOT / "research/S013/experiments/EX061_20261011/protocols/result_references.json"
    )
    input_refs = {n: oldrefs[n] for n in ("features.csv", "opportunity.csv", "input_checks.json")}
    for ref in input_refs.values():
        public(ref)
    predecessors = [
        read(ROOT / f"research/S013/deliveries/{stage}/{rev}/receipt.json")["reference"]
        for stage, rev in [("MANDATE", 6), ("COMPONENTS", 4), ("CANDIDATES", 57)]
    ]
    ctx = common.context(1)
    exp = create_experiment(
        ctx,
        ExperimentRequest(
            "扣费后做多机会供给与实际持有期限",
            "在原开发池中，固定期限的正净收益机会是否足够；短期卖压回归是否超出原14项信息，在匹配4/8日持有期后仍有增量？",
            date(2026, 10, 11),
        ),
    )
    sources = (
        "core.py",
        "checks.py",
        "opportunity_statistics.py",
        "statistics_checks.py",
        "stats_test_module.py",
        "verify_statistics.py",
        "driver.py",
        "prepare_statistics.py",
    )
    plan = {
        "experiment": exp.to_dict(),
        "role": "RSCH",
        "stage": 2,
        "authorization": "认同你的观点。请你重新设定研究目标，并自主研究",
        "objective": "检验只做多条件下扣费后机会数量、盈利余量与可识别性；有依据才构建原硬门达标且标准扰动能力更强的完整策略。",
        "economic_targets_unchanged": True,
        "new_hard_gates": False,
        "scope": "仅S013既有510500.SH，2020-01-02至2026-09-30和原预热；1m资本，HFQ原锚点，固定1%LimitBuyHold，每侧10bp，不跨族/外部/封存/DEV/PTE/生产。",
        "frequency": "全池平均每60session>=4，1636session至少110闭合；不要求每个下跌年份单独达标。",
        "negative_buyhold_years": "实际基准亏损年份净收益严格>0；未改为>=0。",
        "label": "nextOpen to nextOpen+h, fee proxy=(exit/entry)*.999/1.001-1; actual native limit/lot/fill model not simulated",
        "fixed_horizons": {
            "capacity": [1, 4, 8, 10],
            "predictive_primary": [4, 8],
            "predictive_auxiliary": [1],
        },
        "horizon_reason": "bear.TIME4/bull.TIME8 matches actual age-zero entry; h10 links original stage2; h1 tests only short-lived EX061 reverse clue. No horizon optimization.",
        "components": {
            "late_weakness": "negative of EX061 log(C8/C6)",
            "early_reclaim_weakness": "negative of EX061 volume-weighted early-close reclaim",
        },
        "hypothesis": "暂时卖压后的回归在下一开盘之后提供旧BODY、位置、量能、ACF和确认之外的扣费后收益；正值方向预声明，风险不预设改善。",
        "selection_history": "反方向来自已见EX061，期限来自已见C8880，均非独立新样本。符号反转不会创造新信息；重复h1仅检查扣费水平，不称独立确认。",
        "controls": list(stats.CONTROLS),
        "statistics": stats.METHOD,
        "scope_masks": ["all", "opportunity", "past20_declining", "declining_opportunity"],
        "declining_definition": "信号当日过去20日momentum<0，因果固定分层，不等同全年buyhold亏损或原raw路线；年份仅事后诊断。",
        "capacity": "Future-aware interval-DP over fixed1/4/8/10 horizons, fractional full-capital open fills with10bp each side, one-session turnaround; fullpool best growth constrained>=110. Yearly capacity not yearly hardgate. Not tradable; no limit/tick/lot restrictions.",
        "oracle_non_claims": "Cannot prove live strategy feasibility or universal impossibility. No oracle prices used in predictors. Native-account original frequency/annual continuous equity unchanged.",
        "stop_policy": "若无稳定控制后增量，停止两条固定反向表达的策略化；不扫阈值或再翻方向；正负结果及薄组全保留。下一新信息假说须另行事前留证。",
        "accounts": {"preparations": 0, "evaluations": 0, "new32": 0},
        "input_references": input_refs,
        "predecessors": predecessors,
        "source_files": {n: digest(WORK / n) for n in sources},
        "trusted_common_sha256": digest(
            ROOT / "research/S013/experiments/EX058_20261011/src/common.py"
        ),
        "limits": "已反复研究开发池，时间顺序测试非封存；成本代理非账户收益，重叠标签非组合，未知历史发布时间、供应商修订未独立验证。",
    }
    write(WORK / "plan.json", plan)
    refs = {}
    for n in (*sources, "checks.json", "statistics_checks.json", "plan.json"):
        refs[n] = put(ctx, exp, WORK / n)
        if n.endswith(".py"):
            (exp.resolve(ROOT) / "src").mkdir(exist_ok=True)
            (exp.resolve(ROOT) / "src" / n).write_bytes((WORK / n).read_bytes())
    write(exp.resolve(ROOT) / "protocols/plan.json", plan)
    write(exp.resolve(ROOT) / "protocols/method_references.json", refs)
    write(WORK / "experiment.json", exp.to_dict())
    print({"declared": exp.experiment_id, "stage": 2, "new_accounts": 0}, flush=True)


def check_sources():
    plan = read(WORK / "plan.json")
    for n, sha in plan["source_files"].items():
        assert digest(WORK / n) == sha, n
    assert (
        digest(ROOT / "research/S013/experiments/EX058_20261011/src/common.py")
        == plan["trusted_common_sha256"]
    )
    refs = read(experiment().resolve(ROOT) / "protocols/method_references.json")
    assert read(public(refs["plan.json"])) == plan
    return plan


def frame(path):
    f = pd.read_csv(path, index_col="signal_date", float_precision="round_trip")
    f.index = pd.to_datetime(f.index).as_unit("ns")
    return f


def study():
    plan = check_sources()
    if (WORK / "input_checks.json").exists():
        raise ValueError("No automatic rerun")
    exp = experiment()
    ctx = common.context(1)
    refs = read(exp.resolve(ROOT) / "protocols/method_references.json")
    bound, result = common.cache_read(common.CACHE / "N0.pkl.gz")
    native_ref = common.read(common.RUNS / "account_references.json")["N0"]
    assert serialize_evaluation_evidence(bound, result) == read(public(native_ref))
    old = frame(public(plan["input_references"]["features.csv"]))
    opportunity = frame(public(plan["input_references"]["opportunity.csv"])).iloc[:, 0]
    assert opportunity.dtype == bool and len(old) == 1635 and old.index.equals(opportunity.index)
    features = old.loc[:, list(stats.CONTROLS)].copy()
    features["late_weakness"] = -old.late_recovery
    features["early_reclaim_weakness"] = -old.early_volume_reclaim
    ed = bound.execution_data
    adjusted = ctx.data.fetch(ed.requests["adjusted_daily"], prepared=ed.prepared)
    raw = ctx.data.fetch(ed.requests["execution_daily"], prepared=ed.prepared)
    assert adjusted.ready and raw.ready
    from run_opportunity_study import numerical

    prices = ed.pricing.apply(
        numerical(raw.dataframe),
        raw_daily=numerical(raw.dataframe),
        adjusted_daily=numerical(adjusted.dataframe),
    )
    expected = ed.execution_daily.copy()
    a = prices.copy()
    expected.attrs = {}
    a.attrs = {}
    pd.testing.assert_frame_equal(a, expected, check_exact=True)
    prices = prices.set_index("dt")
    prices.index = prices.index.as_unit("ns")
    assert (
        len(prices) == 1637
        and prices.index[0] == pd.Timestamp("2019-12-31")
        and prices.index[-1] == pd.Timestamp("2026-09-30")
    )
    target = labels(prices, features.index)
    assert not common.SOURCE_CALLS
    write(
        WORK / "input_checks.json",
        {
            "status": "PASS",
            "native_account_exact": True,
            "native_ref": native_ref,
            "pricing": ed.pricing.to_dict(),
            "adjusted_identity": adjusted.identity.content_sha256,
            "raw_identity": raw.identity.content_sha256,
            "signal_n": len(features),
            "execution_sessions": len(prices) - 1,
            "execution_prices_exact": True,
            "provider_calls": common.SOURCE_CALLS,
            "fee_proxy_only": True,
            "latest_price_date": str(prices.index[-1]),
            "old_input_references": plan["input_references"],
        },
    )
    for n, f in [
        ("features.csv", features),
        ("labels.csv", target),
        ("opportunity.csv", opportunity),
        ("prices.csv", prices),
    ]:
        f.to_csv(WORK / n, index_label="signal_date", float_format="%.17g")
        refs[n] = put(ctx, exp, WORK / n)
    refs["input_checks.json"] = put(ctx, exp, WORK / "input_checks.json")
    capacity = supply(prices, target, features, opportunity)
    write(WORK / "supply.json", capacity)
    refs["supply.json"] = put(ctx, exp, WORK / "supply.json")
    write(exp.resolve(ROOT) / "protocols/input_references.json", refs)
    print(
        {"inputs_authenticated": True, "supply_computed": True, "scopes": 4, "new_accounts": 0},
        flush=True,
    )
    write(WORK / "statistics.json", stats.analyze(features, target, opportunity))
    refs["statistics.json"] = put(ctx, exp, WORK / "statistics.json")
    write(exp.resolve(ROOT) / "protocols/result_references.json", refs)
    print({"statistics_complete": True, "new_accounts": 0}, flush=True)


def verify():
    check_sources()
    exp = experiment()
    refs = read(exp.resolve(ROOT) / "protocols/result_references.json")
    frames = {
        n: frame(public(refs[n]))
        for n in ("features.csv", "labels.csv", "opportunity.csv", "prices.csv")
    }
    features, target, opp, prices = (
        frames[n] for n in ("features.csv", "labels.csv", "opportunity.csv", "prices.csv")
    )
    opp = opp.iloc[:, 0]
    checks = verify_statistics(
        features, target, opp, read(public(refs["statistics.json"])), pd.Timestamp("2026-09-30")
    )
    for h in HORIZONS:
        for t, row in target.iterrows():
            p = prices.index.get_loc(t)
            if p + h + 1 >= len(prices):
                assert pd.isna(row[f"return_{h}"])
            else:
                expected = (prices.open.iloc[p + h + 1] * (1 - COST)) / (
                    prices.open.iloc[p + 1] * (1 + COST)
                ) - 1
                np.testing.assert_allclose(row[f"return_{h}"], expected, atol=5e-16, rtol=0)
    old = frame(public(read(WORK / "plan.json")["input_references"]["features.csv"]))
    np.testing.assert_array_equal(features.late_weakness, -old.late_recovery)
    np.testing.assert_array_equal(features.early_reclaim_weakness, -old.early_volume_reclaim)
    pd.testing.assert_frame_equal(
        features.loc[:, list(stats.CONTROLS)], old.loc[:, list(stats.CONTROLS)], check_exact=True
    )
    cap = read(public(refs["supply.json"]))
    # Independent earliest-finish greedy verifies maximal positive interval count.
    for year in range(2020, 2027):
        year_prices = prices.loc[prices.index.year == year]
        mixture = []
        for h in HORIZONS:
            edges = []
            for start in range(len(year_prices) - h):
                if year_prices.index[start] < pd.Timestamp("2020-01-02"):
                    continue
                end = start + h
                net = (
                    year_prices.open.iloc[end] * 0.999 / (year_prices.open.iloc[start] * 1.001) - 1
                )
                if net > 0:
                    edges.append((start, end))
            mixture.extend(edges)
            count = 0
            last = -2
            for start, end in sorted(edges, key=lambda x: (x[1], x[0])):
                if start >= last + 1:
                    count += 1
                    last = end
            assert (
                cap["foresight_capacity"][f"{year}/h{h}"]["positive_nonoverlap_max_count"] == count
            )
        count = 0
        last = -2
        for start, end in sorted(mixture, key=lambda x: (x[1], x[0])):
            if start >= last + 1:
                count += 1
                last = end
        assert cap["four_horizon_mixture"][str(year)]["positive_nonoverlap_max_count"] == count
    checks["independent_fee_formula_rows"] = len(target) * len(HORIZONS)
    checks["independent_greedy_capacity_checks"] = 35
    checks["original_control_and_reverse_component_exact"] = True
    checks["synthetic_proof"] = read(WORK / "checks.json")
    write(WORK / "verification.json", checks)
    print(
        {
            "verification": "PASS",
            "statistical_checks": checks["check_count"],
            "label_rows": checks["independent_fee_formula_rows"],
            "capacity_checks": 35,
        },
        flush=True,
    )


if __name__ == "__main__":
    if sys.argv[1] == "study":
        sys.path.insert(0, str(ROOT / "research/S013/experiments/EX061_20261011/src"))
    {"declare": declare, "study": study, "verify": verify}[sys.argv[1]]()
