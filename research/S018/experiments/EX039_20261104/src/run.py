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

STRATEGY = "from decimal import Decimal, ROUND_FLOOR\nfrom strategy_runtime.account_strategy import AccountDecision, AccountStepResult\nfrom strategy_runtime.equity_replay import StateRecord\nfrom strategy_runtime.replay_contracts import ReplayOrder\nfrom strategy_runtime.contracts import OrderSide, OrderType\n\n\ndef step(ctx, state):\n    bars = ctx.history.to_frame()\n    price = float(bars['Close'].iloc[-1])\n    horizon = int(ctx.parameters['exit'])\n    phase = int(ctx.parameters['entry'].split('_')[1])\n    enter = (len(bars)-1) % (horizon+1) == phase\n    active = ctx.position.active\n    orders = ()\n    if active is None:\n        anchor, floor = price, float(bars['Low'].iloc[-1])\n        target = float(enter)\n        reason = 'entry' if enter else 'no opportunity'\n        if enter:\n            raw = Decimal(str(price))*Decimal(str(ctx.portfolio.reference_price_scale))\n            limit = (raw*Decimal('1.01')/Decimal('0.01')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('0.01')\n            orders = (ReplayOrder(OrderSide.BUY,1,OrderType.LIMIT,float(limit)),)\n    else:\n        anchor = state.cycle.values.get('anchor')\n        floor = state.cycle.values.get('floor')\n        held = sum(t >= active.entry_interval.start for t in bars['Date'])\n        target = float(held < horizon)\n        reason = 'hold' if target else 'complete'\n    return AccountStepResult(\n        AccountDecision.from_facts(target,reason,\n            facts={'observed_signal':enter,'anchor':anchor,'floor':floor},\n            next_watch='next complete daily bar',capital_mode='full_available_cash',orders=orders),\n        cycle_values=StateRecord((('anchor',anchor),('floor',floor))) if active is not None or target else None)\n"


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def metrics(run):
    m = run["metrics"]
    dd = m["bar_max_drawdown"]
    counts = m["rolling_60_closed_cycle_counts"]
    from collections import Counter
    reasons = Counter(item["explanation"]["explanation"] for item in run["decisions"] if item.get("side") == "SELL")
    signals = sum(any(fact["key"] == "observed_signal" and fact["text"] == "True"
                      for fact in item["explanation"]["basis"]) for item in run["decisions"])
    points = {p["session"]:p["equity"] for p in run["account_points"]}
    focus = [t for t in run["trades"] if t["status"] == "CLOSED" and "2026-10-02" <= t["exit_at"][:10] <= "2026-10-15"]
    return {"october_return": points["2026-10-15"]/points["2026-10-01"]-1,
            "october_closed": len(focus), "october_closed_pnl": sum(t["net_pnl"] for t in focus),
            "observed_signal_days": signals, "annual": m["annualized_return"], "dd": dd,
            "calmar": m["annualized_return"] / dd if dd else None,
            "closed": m["closed_cycles"], "median": m["rolling_60_closed_cycle_median"],
            "coverage": sum(n >= 3 for n in counts) / len(counts), "exit_orders": reasons}

def main():
    protocol = read(Path(sys.argv[1]))
    number, title, configurations = (protocol[k] for k in ("number","question","configurations"))
    baselines = protocol.get("reuse", [])
    assert 37 <= number <= 63 and 2 <= len(configurations) <= 16
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
        execution_spec=spec, resources=ExecutionResources(4, 1, 17))
    w = folder / "experiments" / e.experiment_id
    if not w.exists():
        assert create_experiment(ctx, ExperimentRequest("MU stage two", title, date(2026,11,4))) == e
    assert not (w / "report_ref.json").exists()
    src = w / "src"
    out = w / "others"
    out.mkdir(exist_ok=True)
    (src / "strategy.py").write_bytes(STRATEGY.encode())
    (src / "run.py").write_bytes(Path(__file__).read_bytes())
    protocol["source_sha256"] = equity_source_hash(src, ("strategy.py",))
    save(out / "protocol.json", protocol)
    refs = [publish_evidence(ctx, d.MaterialEvidenceWrite(e, "protocol", (out / "protocol.json").read_bytes(), "application/json", "json"))]
    for name, key in baselines:
        record = read(folder / "experiments" / name / "others/results.json")
        refs.append(d.EvidenceRef.from_dict((record["accounts"][key] if key else record)["account_ref"]))
    p = read(folder / "experiments/EX001_20261104/others/daily_preparation.json")["reference"]
    prepared = PreparedDataRef(UUID(p["space_id"]), UUID(p["preparation_id"]), p["manifest_sha256"])
    source = SourceRef("futu", "s018-mu-daily-20261104")
    sources = d.EquitySources(source, source, SourceRef("s018-mu-actions", "futu-spglobal-crosscheck-v1"),
        SourceRef("s018-mu-rules", "daily-research-assumptions-v1"))
    tz = ZoneInfo("America/New_York")
    window = TimeInterval(datetime(2023,1,3,9,30,tzinfo=tz), datetime(2026,10,30,16,tzinfo=tz))
    schema = StrategyStateSchema(cycle_fields=(StateField("anchor", StateValueType.FLOAT), StateField("floor", StateValueType.FLOAT)))
    candidates, requests = [], []
    for index, (entry, exit_mode, allocation) in enumerate(configurations):
        params = {"entry": entry, "exit": exit_mode, "allocation": allocation}
        definition = EquityStrategyDefinition(instrument, spec, 63, "strategy:step", ("strategy.py",),
            equity_source_hash(src, ("strategy.py",)), contract_version=4, feature_graph=FeatureGraph((), ()), state_schema=schema,
            computation=StrategyComputation.STATEFUL_STEP, parameters_json=json.dumps(params),
            parameter_schema_json=json.dumps({k: {"type": "number" if k == "allocation" else "string", "enum": [v]} for k,v in params.items()}))
        candidate = EquityStrategyCandidate("S018", f"C{7000+(number-39)*100+index}", definition, src)
        candidates.append(candidate)
        requests.append(d.EquityEvaluationRequest(e, candidate, window, date(2022,1,3), sources, 100000., .001,
            prepared=prepared, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)), window_id="MU_DEVELOPMENT",
            drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE"))
    accounts = {}
    event_records = []
    with d.ResearchExecutionSession(ctx, experiment=e) as session:
        handles = tuple(ctx.evaluation.prepare(r, execution=session) for r in requests)
        outcomes = ctx.evaluation.evaluate_many(handles, execution=session)
        assert all(x.status.value == "SUCCEEDED" for x in outcomes), [x.error for x in outcomes]
        receipts = publish_evidence_many(ctx, tuple(d.EvaluationEvidenceWrite(e, f"mu-{c.candidate_id}", h, o.result)
            for c,h,o in zip(candidates,handles,outcomes,strict=True)), execution=session)
        for c, config, outcome, receipt in zip(candidates, configurations, outcomes, receipts, strict=True):
            assert receipt.status.value == "PUBLISHED", receipt.error
            refs.append(receipt.reference)
            result = outcome.result
            artifacts = {item.sha256: item for item in result.artifacts}
            runs = {k: json.loads(artifacts[result.payload[k + "_ref"]["sha256"]].content)["run"] for k in ("candidate","benchmark")}
            x, y = metrics(runs["candidate"]), metrics(runs["benchmark"])
            buys = {f['cycle_id']: f for f in runs['candidate']['fills'] if f['side']=='BUY'}
            for trade in runs['candidate']['trades']:
                fill=buys[trade['cycle_id']]
                assert fill['quantity']==1
                event_records.append({'candidate':c.candidate_id,'horizon':int(config[1]),
                    'entry_interval':fill['interval_start'],'entry_price':fill['price'], **trade})
            daily = runs["candidate"]["account_daily"]
            prior, years = 100000., {}
            for year in (2023,2024,2025,2026):
                chunk = [z for z in daily if z["session"].startswith(str(year))]
                years[str(year)] = chunk[-1]["equity"] / prior - 1
                prior = chunk[-1]["equity"]
            x["year_returns"] = years
            values = {z["session"]: z["equity"] for z in daily}
            x["october_diagnostic"] = values["2026-10-15"]/values["2026-10-01"]-1
            x["invested_days"] = sum(z["quantity"] > 0 for z in daily)
            assert all(z["observed_through"] < z["execution_start"] for z in runs["candidate"]["decisions"])
            x["causal_clock_check"] = "PASS"
            gates = {"calmar": x["calmar"] is not None and x["calmar"] >= 1.5*y["calmar"],
                "dd_absolute": x["dd"] <= .25, "dd_relative": x["dd"] <= .8*y["dd"],
                "median": x["median"] >= 6, "coverage": x["coverage"] >= .9}
            accounts[c.candidate_id] = dict(config=config, candidate=x, gates=gates, account_ref=receipt.reference.to_dict(),
                definition=c.definition.to_dict())
        workload = asdict(session.equity_statistics)
    save(out / "analysis_events.json", event_records)
    save(out / "results.json", {"accounts": accounts, "benchmark": y, "workload": workload})
    refs.append(publish_evidence(ctx, d.MaterialEvidenceWrite(e, "results", (out / "results.json").read_bytes(), "application/json", "json")))
    save(out / "evidence_refs.json", [r.to_dict() for r in refs])
    lines = ["# MU 阶段二问题对照", "", title, "",
        f"新增 {len(accounts)} 个策略账户，引用 {len(baselines)} 个既有账户。沿用原开发池和标准费用。",
        "", "|配置|规则|净年化|回撤|净卡玛|闭合|中位|覆盖|通过|", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for key, record in accounts.items():
        x = record["candidate"]
        lines.append(f"|{key}|{record['config']}|{x['annual']:.2%}|{x['dd']:.2%}|{x['calmar']}|{x['closed']}|{x['median']:g}|{x['coverage']:.2%}|{all(record['gates'].values())}|")
    lines += ["", "[协议](others/protocol.json) · [账户与逐项验收](others/results.json)"]
    body = ("\n".join(lines)+"\n").encode()
    (w / "report.md").write_bytes(body)
    print(e.experiment_id, [(k,v["config"],round(v["candidate"]["calmar"] or 0,3),round(v["candidate"]["dd"],3),v["candidate"]["median"],round(v["candidate"]["coverage"],3)) for k,v in accounts.items()], flush=True)

if __name__ == "__main__":
    main()

