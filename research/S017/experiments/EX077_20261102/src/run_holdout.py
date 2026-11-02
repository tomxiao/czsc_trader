"""Run the five prespecified test candidates once through public TDR execution."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUT = WORK / "others"
SCRATCH = ROOT / ".tmp/s017-holdout-20261102"
SCRATCH.mkdir(parents=True, exist_ok=True)
sys.pycache_prefix = str(SCRATCH / "pycache")
os.environ["TMP"] = os.environ["TEMP"] = str(SCRATCH)
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import math
from time import perf_counter
from zoneinfo import ZoneInfo

import psutil
from dataflows import (BarFrequency, EquityDataRequest, EquityProduct, EquityQuery, MarketId,
    PreparePolicy, ProviderBinding, ProviderConfig, ProviderKey, SourceRef, TimeInterval)
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, load_candidate,
    publish_evidence, publish_evidence_many, update_research_intent, ResearchIntentUpdate,
    validate_experiment)
from strategy_manager import CandidateKey
from strategy_runtime import ExecutionResources
from strategy_evaluator import assess_candidates
from strategy_evaluator import research_models as m
from strategy_evaluator.research_acceptance import check_target, acceptance_status
from cache_slice import load_authorized_slice

E = d.ExperimentRef("S017", WORK.name)
SOURCE = SourceRef("futu", "lite-full-gap-known-interruptions-v1-20261028")
RULES = SourceRef("s017-research-rules", "same-approved-us-assumptions-v4-ex032-v1")


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False,
                              default=str) + "\n", encoding="utf-8", newline="\n")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def ratio(annual, drawdown):
    result = None if drawdown <= 1e-12 else annual / drawdown
    return result if result is not None and math.isfinite(result) else None


def metric_values(run):
    values = run["metrics"]
    result = {"NET_ANNUAL_RETURN": values["annualized_return"],
              "DRAWDOWN_MAGNITUDE": values["bar_max_drawdown"],
              "NET_CALMAR": ratio(values["annualized_return"], values["bar_max_drawdown"]),
              "FREQUENCY_MEDIAN": values["rolling_60_closed_cycle_median"]}
    counts = values["rolling_60_closed_cycle_counts"]
    return result, {"windows": len(counts), "covered": sum(n >= 3 for n in counts),
        "coverage": sum(n >= 3 for n in counts) / len(counts) if counts else None,
        "closed_cycles": values["closed_cycles"], "sessions": values["sessions"],
        "observations": values["observations"], "total_return": values["total_return"],
        "fees": values["fees"], "ending": run["account_points"][-1]}


def independent_target(target, values, benchmark, frequency):
    """RSCH scalar/count verification, without replaying or re-auditing accounts."""
    if isinstance(target, m.FrequencyCoverageTarget):
        return ("INDETERMINATE" if not frequency["windows"] else
            "PASSED" if frequency["covered"] * target.minimum_denominator
            >= frequency["windows"] * target.minimum_numerator else "FAILED")
    if target.when is not None:
        observed = benchmark[target.when.metric.value]
        if observed is None:
            return "INDETERMINATE"
        compare = {"EQ": lambda a, b: a == b, "LT": lambda a, b: a < b,
                   "LE": lambda a, b: a <= b, "GT": lambda a, b: a > b,
                   "GE": lambda a, b: a >= b}[target.when.operator.value]
        if not compare(observed, target.when.value):
            return "NOT_APPLICABLE"
    value = values.get(target.metric.value)
    if value is None:
        return "INDETERMINATE"
    for bound, lower in ((target.lower, True), (target.upper, False)):
        if bound is None:
            continue
        if isinstance(bound, m.BenchmarkBound):
            base = benchmark.get(target.metric.value)
            if base is None:
                return "INDETERMINATE"
            threshold = Decimal(str(base)) * Decimal(str(bound.multiplier))
        else:
            threshold = Decimal(str(bound.value))
        current = Decimal(str(value))
        good = ((current >= threshold if bound.inclusive else current > threshold) if lower else
                (current <= threshold if bound.inclusive else current < threshold))
        if not good:
            return "FAILED"
    return "PASSED"


def context(repository, candidate, bindings=None):
    return create_research_context(repository, d.ResearchBatchRef("S017"),
        providers=ProviderConfig(bindings={}, equity_bindings={} if bindings is None else bindings),
        execution_spec=candidate.definition.execution_spec, resources=ExecutionResources(12, 1, 17))


def prepare_data(repository, candidate):
    frames, metadata, provenance = load_authorized_slice()
    rules = frames["CONSTRAINTS"].copy(deep=True)
    rules["PriceLimitPolicy"] = "EXPLICIT_UNBOUNDED"
    rules["PriceLimitLower"], rules["PriceLimitUpper"] = None, None
    rules["BuySellableAt"] = rules.Date
    rules["SellRemainderPolicy"] = "STRICT_STEP"
    rules["SettlementAt"] = rules.Date
    frames["CONSTRAINTS"] = rules
    metadata["CONSTRAINTS"].update(vendor=RULES.provider, source_revision=RULES.revision,
        constraint_contract="DATED_EQUITY_RULES_V1",
        rule_basis="EXPLICIT_EXISTING_RESEARCH_ASSUMPTIONS_NOT_HISTORICAL_BROKER_FACTS",
        immediate_time_basis="INTERVAL_START_RESEARCH_ASSUMPTION_NOT_REAL_SETTLEMENT",
        parent_source=asdict(SOURCE), derivation_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())

    def fetch(request):
        p = request.parameters
        require(p.instrument == candidate.instrument and p.query.start == date(2025, 11, 1)
            and p.query.end == date(2026, 9, 30) and p.query.frequency is BarFrequency.M30,
            "Only the fixed authorized data window is served")
        require(p.source == (RULES if p.query.product is EquityProduct.CONSTRAINTS else SOURCE),
                "Fixed data source differs")
        return frames[p.query.product.name].copy(deep=True), deepcopy(metadata[p.query.product.name])

    bindings = {ProviderKey(product, MarketId.US, RULES if product is EquityProduct.CONSTRAINTS else SOURCE):
        ProviderBinding((RULES if product is EquityProduct.CONSTRAINTS else SOURCE).provider,
                        (RULES if product is EquityProduct.CONSTRAINTS else SOURCE).revision, fetch)
        for product in EquityProduct}
    research = context(repository, candidate, bindings)
    requests = tuple(EquityDataRequest(candidate.instrument,
        RULES if product is EquityProduct.CONSTRAINTS else SOURCE,
        EquityQuery(product, date(2025, 11, 1), date(2026, 9, 30), BarFrequency.M30))
        for product in EquityProduct)
    prepared = research.data.prepare(requests, policy=PreparePolicy.REUSE)
    status = {"status": prepared.status.value, "items": [{"product": x.request.parameters.query.product.value,
        "status": x.status.value, "error": None if x.error is None else asdict(x.error),
        "content_sha256": None if x.identity is None else x.identity.content_sha256} for x in prepared.items]}
    save(OUT / "data_preparation_status.json", status)
    require(prepared.ready, "Data preparation failed; see data_preparation_status.json")
    warmup = frames["BARS"].Date.dt.tz_convert("America/New_York").dt.date < date(2026, 1, 2)
    require(int(warmup.sum()) >= 261, "Fixed warmup has insufficient observed bars")
    save(OUT / "data_preparation.json", {"reference": asdict(prepared.reference), "parent": provenance,
        "status": status, "warmup_observations": int(warmup.sum()), "fixed_window_only": True,
        "October_prices_in_research_inputs": False, "external_downloads": 0})
    return research, prepared.reference


def execute(research, candidates, protocol, prepared):
    zone = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2026, 1, 2, 9, 30, tzinfo=zone),
                          datetime(2026, 9, 30, 16, tzinfo=zone))
    facts, records, baseline = {}, {}, {}

    def progress(item):
        save(OUT / "progress.json", item.to_dict() if hasattr(item, "to_dict") else asdict(item))
        print("HOLDOUT", item.phase.value, item.completed, item.total, flush=True)

    with d.ResearchExecutionSession(research, experiment=E, on_progress=progress) as execution:
        jobs, handles = [], []
        for scenario in protocol["scenarios"]:
            for key in protocol["candidate_order_fixed_from_training"]:
                candidate = candidates[key]
                request = d.EquityEvaluationRequest(E, candidate, window, date(2025, 11, 1),
                    d.EquitySources(SOURCE, SOURCE, SOURCE, RULES), 100000., scenario["one_way_fee"],
                    prepared=prepared, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
                    window_id="TEST_2026_01_09", scenario_id=scenario["scenario_id"],
                    measurement_tier="FORMAL" if scenario["scenario_id"] == "STANDARD" else "STRESS",
                    drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE", frequency_window_days=60)
                handles.append(research.evaluation.prepare(request, execution=execution))
                jobs.append((key, scenario["scenario_id"]))
        outcomes = research.evaluation.evaluate_many(tuple(handles), execution=execution)
        statuses = [{"candidate": key, "scenario": scene, "status": outcome.status.value,
                     "error": None if outcome.error is None else asdict(outcome.error)}
                    for (key, scene), outcome in zip(jobs, outcomes, strict=True)]
        save(OUT / "execution_statuses.json", statuses)
        require(all(o.status.value == "SUCCEEDED" and o.result is not None for o in outcomes),
                "Account execution incomplete; no automatic retry")
        publications = publish_evidence_many(research, tuple(d.EvaluationEvidenceWrite(E,
            f"test-{key}-{scene.lower()}", handle, outcome.result)
            for (key, scene), handle, outcome in zip(jobs, handles, outcomes, strict=True)), execution=execution)
        require(all(p.status.value == "PUBLISHED" for p in publications), "Account publication incomplete")
        for (key, scene), handle, outcome, publication in zip(jobs, handles, outcomes, publications, strict=True):
            result = outcome.result
            header = result.payload
            artifacts = {item.sha256: item for item in result.artifacts}
            run = json.loads(artifacts[header["candidate_ref"]["sha256"]].content)["run"]
            bh_sha = header["benchmark_ref"]["sha256"]
            if bh_sha not in baseline:
                bh = json.loads(artifacts[bh_sha].content)["run"]
                baseline[bh_sha] = dict(zip(("metrics", "detail"), metric_values(bh), strict=True))
            values, detail = metric_values(run)
            fact, = d.build_assessment_evidence(handle, result, execution=execution)
            facts[key, scene] = fact
            records[key + ":" + scene] = {"candidate": key, "scenario": scene, "metrics": values,
                "detail": detail, "benchmark": baseline[bh_sha], "benchmark_sha256": bh_sha,
                "evidence": publication.reference.to_dict(), "request_sha256": result.request_hash,
                "candidate_identity": asdict(handle.candidate.content_identity)}
        stats = {"execution": asdict(execution.stats), "accounts": asdict(execution.equity_statistics)}
    require(stats["accounts"]["candidate_runs"] == 10 and stats["accounts"]["benchmark_runs"] == 2,
            "Actual account workload differs from frozen protocol")
    save(OUT / "accounts.json", records)
    save(OUT / "assessment_evidence.json", [fact.to_dict() for fact in facts.values()])
    save(OUT / "execution_statistics.json", stats)
    return facts, records


def analyze(facts, records, protocol):
    source = read(ROOT / "research/S017/experiments/EX076_20261102/protocols/confirmed_bounded_stage4_v3.json")
    rules = replace(m.CalmarSelfCheckProtocol.from_dict(source["protocol"]), baseline_window="TEST_2026_01_09")
    keys = protocol["candidate_order_fixed_from_training"]
    request = m.CandidateAssessmentRequest(tuple(facts[key, "STANDARD"].candidate for key in keys), rules, (), tuple(facts.values()))
    panel = assess_candidates(request)
    save(OUT / "assessment_panel.json", panel.to_dict())
    targets = m.ResearchTargets.from_dict(protocol["targets"])
    rows = {row.candidate.candidate_id.split("-", 1)[1]: row for row in panel.rows}
    result = {}
    for key in keys:
        row = rows[key]
        checks = tuple(check_target(t, row, 60) for t in targets.requirements)
        for target, check in zip(targets.requirements, checks, strict=True):
            scene = "PRESSURE" if getattr(target, "scope", None) is m.TargetScope.STRESS else "STANDARD"
            record = records[key + ":" + scene]
            independent = independent_target(target, record["metrics"], record["benchmark"]["metrics"], record["detail"])
            require(check.status.value == independent, f"RSCH and SE hard gate disagree: {key}/{target.target_id}")
        standard = tuple(c for t, c in zip(targets.requirements, checks, strict=True)
                         if getattr(t, "scope", None) is not m.TargetScope.STRESS)
        pressure = tuple(c for t, c in zip(targets.requirements, checks, strict=True)
                         if getattr(t, "scope", None) is m.TargetScope.STRESS)
        result[key] = {"standard": records[key + ":STANDARD"], "pressure": records[key + ":PRESSURE"],
            "checks": [item.to_dict() for item in checks], "standard_status": acceptance_status(standard).value,
            "pressure_status": acceptance_status(pressure).value, "combined_status": acceptance_status(checks).value,
            "uncertainty": row.uncertainty.to_dict(), "diagnostics": [v.to_dict() for v in row.diagnostics],
            "rolling_calmar": row.rolling_calmar_excess_q10.to_dict()}
    passed = [key for key in keys if result[key]["combined_status"] == "PASSED"]
    summary = {"status": "COMPLETED_FIXED_FIVE_CANDIDATE_HOLDOUT", "candidate_order": keys,
        "passed_all_declared_test_conditions": passed, "recommended_by_prespecified_rule": passed[0] if passed else None,
        "results": result, "family_diagnostics": [x.to_dict() for x in panel.family_diagnostics],
        "rsch_scalar_and_frequency_checks_equal_SE": True, "new_parameter_searches": 0,
        "test_parameter_neighborhoods_executed": False, "October_prices_in_research_inputs": False}
    save(OUT / "results.json", summary)
    return summary


def report(summary, elapsed):
    rows = []
    for key in summary["candidate_order"]:
        item = summary["results"][key]
        v, details = item["standard"]["metrics"], item["standard"]["detail"]
        calmar = "不可用" if v["NET_CALMAR"] is None else f"{v['NET_CALMAR']:.4f}"
        rows.append(f"|{key}|{details['total_return']:.2%}|{v['NET_ANNUAL_RETURN']:.2%}|{v['DRAWDOWN_MAGNITUDE']:.2%}|{calmar}|"
                    f"{v['FREQUENCY_MEDIAN']}|{details['covered']}/{details['windows']}|{item['standard_status']}|{item['pressure_status']}|")
    failures = [f"- {key}：" + "；".join(c["target"]["target_id"] + "=" + c["status"]
        for c in item["checks"] if c["status"] in ("FAILED", "INDETERMINATE"))
        for key, item in summary["results"].items() if item["combined_status"] != "PASSED"]
    first = summary["results"][summary["candidate_order"][0]]["standard"]["benchmark"]
    text = f"""# EX077：五个固定配置的2026联合样本外测试

本轮已完成用户授权的五候选联合验证。全部标准及压力账户、同成本买持和SE数值计算已完成，RSCH逐项核验硬门与频率。
测试窗口为美东2026-01-02至2026-09-30，{first['detail']['sessions']}个交易日；每账户100000美元、空仓与初始策略状态。
实际10个策略账户、2个共享买持，12进程上限，每进程1线程。准备、执行、分析耗时{elapsed:.2f}秒，独立账户审计与额外FULL复算均未执行。

## 做了哪些尝试

在读测试价格前固定C0342、C0352、C0338、C0341、C0340及其源码参数、窗口和标准；沿用标准每侧0.1%、压力每侧0.2%。
复用既有本地Futu缓存，先按2025-11-01至2026-09-30裁剪，再准备特征和账户；2025仅预热，不继承训练末状态。零外部下载，十月价格不进入研究输入。
测试不新增参数扰动或调参，训练参数自检保持原结论，不宣称已取得样本外参数稳健性证据。

## 有哪些收获

|配置|测试区间净收益|净年化|最大回撤|净Calmar|60日闭合中位|≥3笔窗口|标准五门|费用压力门|
|---|---:|---:|---:|---:|---:|---:|---|---|
{chr(10).join(rows)}

同窗标准买持：区间净收益{first['detail']['total_return']:.2%}、净年化{first['metrics']['NET_ANNUAL_RETURN']:.2%}、最大回撤{first['metrics']['DRAWDOWN_MAGNITUDE']:.2%}、Calmar {first['metrics']['NET_CALMAR']}。
净Calmar严格大于同窗买持1.5倍、回撤不高于买持0.8倍且不高于25%、60交易日闭合中位至少6且至少90%完整窗口≥3；压力按其自身买持检验既定Calmar及回撤条件。没有独立净年化收益门。

{chr(10).join(failures) if failures else '五配置均通过本轮全部声明条件。'}

账户末仓以最后BAR_CLOSE估值，不强制平仓、不制造闭合交易；末仓数量、现金、净值、费用及全部逐项门结果见[完整结果](others/results.json)。
九个月不足252交易日，年度滚动项如实不可用，不借训练或未来补齐；它不新增否决门。配对年化差区间、集中度及研究族诊断保留在[SE面板](others/assessment_panel.json)。

## 下一步建议

按事前规则，通过标准和压力条件的集合为{summary['passed_all_declared_test_conditions']}，沿用训练排序的首位为{summary['recommended_by_prespecified_rule']}。
这是五个相关候选共用一段样本的联合测试，按通过与否筛选仍属于已声明的多候选选择；不表示五份独立证据或经全研究族选择校正的显著性。
不根据结果追加参数、候选或改变门槛。用户决定后续选型、技术检验或停止；本轮未授权阶段五、冻结、PTE或生产。

原NONE公司行动声明、缺口及立即可用现金等研究假设沿用，不升级为独立历史券商或事件事实核验；测试结果在这些数据和执行前提下解释。

## 依据

[事前方案](protocols/fixed_holdout.md)、[机器方案](protocols/fixed_holdout.json)、[方案发布](others/protocol_publication.json)、[数据准备](others/data_preparation.json)、[实际运行](others/execution_statistics.json)、[正式账户引用](others/accounts.json)、[逐项结果](others/results.json)。
"""
    (WORK / "report.md").write_text(text, encoding="utf-8", newline="\n")


def publish(research, summary):
    references = [d.EvidenceRef.from_dict(x["evidence"]) for x in read(OUT / "accounts.json").values()]
    references.append(d.EvidenceRef.from_dict(read(OUT / "protocol_publication.json")["reference"]))
    for path in (OUT / "results.json", OUT / "assessment_panel.json", OUT / "data_preparation.json",
                 OUT / "execution_statistics.json", Path(__file__), WORK / "src/cache_slice.py"):
        references.append(publish_evidence(research, d.MaterialEvidenceWrite(E, "holdout-" + path.stem,
            path.read_bytes(), "application/json" if path.suffix == ".json" else "text/x-python", path.suffix[1:])))
    root_report = (WORK / "report.md").read_bytes()
    reference = publish_evidence(research, d.ExperimentReportWrite(E, sha256(root_report).hexdigest(),
        d.ExperimentOutcome.COMPLETED, tuple(references)))
    checked = validate_experiment(research.repository, d.ExperimentValidationRequest(E, d.ExperimentValidationScope.REPORT_PUBLICATION))
    require(checked.status is d.ValidationStatus.PASS, "Report publication validation did not pass")
    save(OUT / "publication.json", {"status": "COMPLETED_REPORT_PUBLICATION_PASS", "report": reference.to_dict(),
        "validation": checked.to_dict(), "new_account_replays_by_report": 0, "independent_account_audit": False})
    intent = read(ROOT / "research/registrations/S017/family.json")["research_intent"]
    intent["active_final_test_20261102"].update(status="COMPLETED", prices_accessed=True,
        report=reference.to_dict(), results="research/S017/experiments/EX077_20261102/others/results.json",
        passed=summary["passed_all_declared_test_conditions"], recommended=summary["recommended_by_prespecified_rule"],
        stage_five_or_freeze_authorized=False)
    intent["next_action"] = "五候选联合测试完成，报告全部结果及选择限制；等待用户确定后续候选技术检验或研究安排。"
    update_research_intent(research.repository, d.ResearchBatchRef("S017"), ResearchIntentUpdate(research_intent=intent),
        actor="RSCH", reason="用户授权的固定五配置测试已完成，RSCH硬门核验及正式报告发布通过；不自动推进技术检验或冻结")


def main():
    started = perf_counter()
    require(not (OUT / "accounts.json").exists(), "Completed accounts exist; finalize explicitly without replay")
    protocol = read(WORK / "protocols/fixed_holdout.json")
    expected = read(OUT / "protocol_publication.json")
    require(sha256((WORK / "protocols/fixed_holdout.json").read_bytes()).hexdigest() == expected["sha256"], "Prespecified protocol changed")
    require(psutil.virtual_memory().available >= 16 * 2**30, "Memory requires resource review")
    repository = RepositoryContext.discover(ROOT)
    keys = protocol["candidate_order_fixed_from_training"]
    candidates = {key: load_candidate(repository, CandidateKey("S017", key)) for key in keys}
    for key, candidate in candidates.items():
        require(asdict(candidate.content_identity) == protocol["candidate_locks"][key]["content_identity"], "Candidate content changed")
    research, prepared = prepare_data(repository, candidates[keys[0]])
    intent = read(ROOT / "research/registrations/S017/family.json")["research_intent"]
    intent["active_final_test_20261102"].update(status="RUNNING", prices_accessed=True)
    update_research_intent(repository, d.ResearchBatchRef("S017"), ResearchIntentUpdate(research_intent=intent),
        actor="RSCH", reason="固定方案已发布，授权窗口数据已按日期裁剪并准备；开始十个固定策略场景及共享买持")
    facts, records = execute(research, candidates, protocol, prepared)
    summary = analyze(facts, records, protocol)
    report(summary, perf_counter() - started)
    publish(research, summary)
    print("HOLDOUT_COMPLETED", summary["passed_all_declared_test_conditions"],
          "recommended", summary["recommended_by_prespecified_rule"], "seconds", perf_counter() - started, flush=True)


if __name__ == "__main__":
    main()
