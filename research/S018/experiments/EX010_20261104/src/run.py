from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID
from zoneinfo import ZoneInfo
from datetime import datetime

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, ExperimentRequest, create_experiment,
    create_research_context, publish_evidence, publish_evidence_many, validate_experiment)
from dataflows import AssetClass, InstrumentId, MarketId, PreparedDataRef, ProviderConfig, SourceRef, TimeInterval
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash, execution_spec_from_dict
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema, StateField, StateValueType
from strategy_runtime.replay_contracts import StrategyComputation

STRATEGY = """from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    bars = ctx.history.to_frame(tail=21)
    close = bars["Close"]
    price = float(close.iloc[-1])
    anchor = float(close.iloc[-11:-1].median())
    floor = float(close.iloc[-21:-11].median())
    p = ctx.parameters
    mode = p["exit"]
    active = ctx.position.active
    if active is None:
        if p["entry"] == "repair":
            enter = anchor > floor and floor < price and anchor / price > 1.01 * 1.001 / .999
        elif p["entry"] == "range_repair":
            floor = float(close.iloc[-11:-1].min())
            enter = floor < price and anchor / price > 1.01 * 1.001 / .999
        elif p["entry"] == "discount":
            enter = anchor / price > 1.01 * 1.001 / .999
        else:
            enter = price > float(close.iloc[-11:-1].max())
        target = float(enter)
        reason = "entry" if enter else "no opportunity"
    else:
        anchor = state.cycle.values.get("anchor")
        floor = state.cycle.values.get("floor")
        held = int(sum(stamp >= active.entry_interval.start for stamp in bars["Date"]))
        current_center = float(close.iloc[-10:].median())
        reached = price >= anchor
        failed = (current_center <= floor if mode != "price_fail" else price <= floor)
        if mode == "fixed":
            reason = "time limit" if held >= 5 else "hold"
        elif mode == "failure_only":
            reason = "invalidated" if failed else "hold"
        elif mode == "trend":
            reason = "trend failed" if price < float(close.iloc[-11:-1].median()) else "hold"
        else:
            reason = "target reached" if reached else "invalidated" if failed and mode != "target_only" else "hold"
        target = float(reason == "hold")
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={"anchor": anchor, "floor": floor, "reason": reason},
        next_watch="next complete daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord((("anchor", anchor), ("floor", floor))) if active is not None or target else None)
"""

def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())

def read(path):
    return json.loads(path.read_bytes())

def metrics(run):
    m = run["metrics"]
    dd = m["bar_max_drawdown"]
    counts = m["rolling_60_closed_cycle_counts"]
    from collections import Counter
    reasons = Counter(item["explanation"]["explanation"] for item in run["decisions"] if item.get("side") == "SELL")
    return {"annual": m["annualized_return"], "dd": dd,
            "calmar": m["annualized_return"] / dd if dd else None,
            "closed": m["closed_cycles"], "median": m["rolling_60_closed_cycle_median"],
            "coverage": sum(n >= 3 for n in counts) / len(counts), "exit_orders": reasons}

def main():
    number, entry, exit_mode, title, *baselines = sys.argv[1:]
    root = Path.cwd()
    folder = root / "research/S018"
    repo = RepositoryContext.discover(root)
    b = d.ResearchBatchRef("S018")
    e = d.ExperimentRef("S018", f"EX{int(number):03d}_20261104")
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "MU")
    spec = execution_spec_from_dict({
        "market": {"rule_version": "US_EQUITY_V1"}, "decision_clock": "daily",
        "account": {"currency": "USD", "cash_availability": "IMMEDIATE_RESEARCH",
                    "allow_short": False, "allow_negative_cash": False},
        "quantity_step": 1, "price_tick": .01, "buy_premium": .01, "slippage_bp": 0.,
        "execution": "BAR_RANGE_V1", "inclusive_touch": False, "data_latency_seconds": 0,
    })
    ctx = create_research_context(repo, b, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=spec, resources=ExecutionResources(1, 1, 17))
    w = folder / "experiments" / e.experiment_id
    if not w.exists():
        assert create_experiment(ctx, ExperimentRequest("MU stage two", title, date(2026,11,4))) == e
    assert not (w / "report_ref.json").exists()
    src = w / "src"
    out = w / "others"
    out.mkdir(exist_ok=True)
    (src / "strategy.py").write_bytes(STRATEGY.encode())
    (src / "run.py").write_bytes(Path(__file__).read_bytes())
    params = {"entry": entry, "exit": exit_mode}
    save(out / "protocol.json", {"question": title, "configuration": params, "comparison_experiments": baselines,
        "window": ["2023-01-03", "2026-10-30"], "fee_each_side": .001, "parameter_search": False})
    refs = [publish_evidence(ctx, d.MaterialEvidenceWrite(e, "protocol", (out / "protocol.json").read_bytes(), "application/json", "json"))]
    for name in baselines:
        refs.append(d.EvidenceRef.from_dict(read(folder / "experiments" / name / "others/results.json")["account_ref"]))
    p = read(folder / "experiments/EX001_20261104/others/daily_preparation.json")["reference"]
    prepared = PreparedDataRef(UUID(p["space_id"]), UUID(p["preparation_id"]), p["manifest_sha256"])
    source = SourceRef("futu", "s018-mu-daily-20261104")
    sources = d.EquitySources(source, source, SourceRef("s018-mu-actions", "futu-spglobal-crosscheck-v1"),
        SourceRef("s018-mu-rules", "daily-research-assumptions-v1"))
    tz = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2023,1,3,9,30,tzinfo=tz), datetime(2026,10,30,16,tzinfo=tz))
    schema = StrategyStateSchema(cycle_fields=(StateField("anchor", StateValueType.FLOAT), StateField("floor", StateValueType.FLOAT)))
    definition = EquityStrategyDefinition(instrument, spec, 21, "strategy:step", ("strategy.py",),
        equity_source_hash(src, ("strategy.py",)), contract_version=4, feature_graph=FeatureGraph((), ()), state_schema=schema,
        computation=StrategyComputation.STATEFUL_STEP, parameters_json=json.dumps(params),
        parameter_schema_json=json.dumps({k: {"type": "string", "enum": [v]} for k,v in params.items()}))
    candidate = EquityStrategyCandidate("S018", f"C{8000+int(number)}", definition, src)
    request = d.EquityEvaluationRequest(e, candidate, window, date(2022,1,3), sources, 100000., .001,
        prepared=prepared, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)), window_id="MU_DEVELOPMENT",
        drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE")
    with d.ResearchExecutionSession(ctx, experiment=e) as session:
        handle = ctx.evaluation.prepare(request, execution=session)
        outcome, = ctx.evaluation.evaluate_many((handle,), execution=session)
        assert outcome.status.value == "SUCCEEDED", outcome.error
        result = outcome.result
        receipt, = publish_evidence_many(ctx, (d.EvaluationEvidenceWrite(e, "mu-account", handle, result),), execution=session)
        assert receipt.status.value == "PUBLISHED", receipt.error
        refs.append(receipt.reference)
        artifacts = {item.sha256: item for item in result.artifacts}
        runs = {key: json.loads(artifacts[result.payload[key + "_ref"]["sha256"]].content)["run"] for key in ("candidate","benchmark")}
        x, y = metrics(runs["candidate"]), metrics(runs["benchmark"])
        workload = asdict(session.equity_statistics)
    gates = {"calmar": x["calmar"] is not None and x["calmar"] >= 1.5*y["calmar"], "dd_absolute": x["dd"] <= .25,
        "dd_relative": x["dd"] <= .8*y["dd"], "median": x["median"] >= 6, "coverage": x["coverage"] >= .9}
    save(out / "results.json", {"candidate": x, "benchmark": y, "gates": gates, "workload": workload,
        "account_ref": receipt.reference.to_dict(), "definition": definition.to_dict()})
    refs.append(publish_evidence(ctx, d.MaterialEvidenceWrite(e, "results", (out / "results.json").read_bytes(), "application/json", "json")))
    body = (f"# MU 阶段二机制对照\n\n{title}\n\n"
        f"入场 {entry}，退出 {exit_mode}。开发池固定、每侧 0.1% 费用，无参数搜索。\n\n"
        f"净年化 {x['annual']:.2%}，最大回撤 {x['dd']:.2%}，净卡玛 {x['calmar']:.4f}，"
        f"闭合 {x['closed']} 笔，60 日中位数 {x['median']:g}，覆盖 {x['coverage']:.2%}。\n\n"
        "[预先记录的协议](others/protocol.json) · [账户与逐项验收](others/results.json)\n").encode()
    (w / "report.md").write_bytes(body)
    publish_evidence(ctx, d.ExperimentReportWrite(e, sha256(body).hexdigest(), d.ExperimentOutcome.COMPLETED, tuple(refs)))
    assert validate_experiment(repo, d.ExperimentValidationRequest(e, d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
    print(e.experiment_id, x, gates, flush=True)

if __name__ == "__main__":
    main()
