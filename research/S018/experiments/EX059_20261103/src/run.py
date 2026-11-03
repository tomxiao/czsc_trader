from dataclasses import asdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import UUID
import json
import os
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "research/S018/batch.json").is_file())
os.environ["TMP"] = os.environ["TEMP"] = str(ROOT / ".tmp")
sys.pycache_prefix = str(ROOT / ".tmp/s018-pycache")

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context,
    create_experiment, ExperimentRequest, publish_evidence, publish_evidence_many, validate_experiment)
from dataflows import AssetClass, InstrumentId, MarketId, ProviderConfig, PreparedDataRef, SourceRef, TimeInterval
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import EquityStrategyCandidate, EquityStrategyDefinition, equity_source_hash
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema, StateField, StateValueType
from strategy_runtime.replay_contracts import StrategyComputation
from strategy_manager import CandidateKey
import pandas as pd

F = ROOT / "research/S018"
B = d.ResearchBatchRef("S018")
R = RepositoryContext.discover(ROOT)

STRATEGY = """from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.replay_contracts import ReplayOrder


def step(ctx, state):
    bars = ctx.history.to_frame(tail=66)
    close = bars["Close"]
    dates = [stamp.astimezone(ZoneInfo("America/New_York")) for stamp in bars["Date"]]
    active = ctx.position.active
    orders = ()
    if active is not None:
        held = sum(stamp >= active.entry_interval.start for stamp in dates)
        month_only = state.cycle.values.get("month_only")
        extended = state.cycle.values.get("extended")
        m007_only = state.cycle.values.get("m007_only")
        if held == 5:
            extended = bool(close.iloc[-1] * active.quantity > active.buy_cost)
        time_stop = bool(held == 2 and close.iloc[-1] <= close.iloc[-2] and close.iloc[-1] * active.quantity <= active.buy_cost)
        target = float(held < ((11 if m007_only else 10) if extended else 5) and not time_stop)
        facts = {"completed_holding_sessions": held, "month_only": month_only, "extended": extended, "time_stop": time_stop}
    else:
        ret = close.pct_change()
        r5 = close.pct_change(5)
        sigma5 = ret.shift().rolling(60).std() * 5 ** .5
        m007 = bool(ret.iloc[-3:].lt(0).all())
        m015 = bool(r5.iloc[-1] > sigma5.iloc[-1] and r5.iloc[-2] <= sigma5.iloc[-2]
                    and close.iloc[-1] > close.iloc[-20:].mean())
        m022 = bool(dates[-1].month != dates[-2].month)
        facts = {"m007": m007, "m015": m015, "m022": m022}
        target = float(m007 or m015 or m022)
        month_only = m022 and not (m007 or m015)
        extended = False
        m007_only = m007 and not (m015 or m022)
        fraction = Decimal("0.35") if m015 and not (m007 or m022) else Decimal(1) if m007 and not (m015 or m022) else Decimal(".8") if target else Decimal(1)
        if target and fraction < 1:
            tick = Decimal("0.01")
            reference = Decimal(str(float(close.iloc[-1]))) * Decimal(str(ctx.portfolio.reference_price_scale))
            limit = (reference * Decimal("1.01") / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            half_cash = Decimal(str(ctx.account.available_cash)) * fraction
            quantity = int(half_cash / (limit * Decimal("1.001")))
            if quantity:
                orders = (ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),)
            else:
                target = 0.0
    return AccountStepResult(AccountDecision.from_facts(target, "EX038 controlled policy variant",
        facts=facts, orders=orders, next_watch="next completed daily bar", capital_mode="full_available_cash"),
        cycle_values=StateRecord((("month_only", month_only), ("extended", extended), ("m007_only", m007_only))) if active is not None or target else None)
"""

def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def stats(run):
    m = run["metrics"]
    counts = m["rolling_60_closed_cycle_counts"]
    points = pd.DataFrame(run["account_points"])
    groups = []
    starting = 100000.
    for name, segment in points.groupby(points.session.ge("2025-01-01"), sort=True):
        values = pd.concat([pd.Series([starting]), segment.equity], ignore_index=True)
        groups.append({"group": "2025–2026" if name else "2023–2024",
            "net_return": float(values.iloc[-1] / starting - 1),
            "max_drawdown": float((1 - values / values.cummax()).max()),
            "exposed_sessions": int(segment.quantity.gt(0).sum()), "sessions": len(segment)})
        starting = values.iloc[-1]
    return {"net_return": m["total_return"], "annual": m["annualized_return"], "dd": m["bar_max_drawdown"],
        "calmar": m["annualized_return"] / m["bar_max_drawdown"] if m["bar_max_drawdown"] > 1e-12 else None,
        "frequency_median": m["rolling_60_closed_cycle_median"], "covered": sum(n >= 3 for n in counts),
        "windows": len(counts), "closed": m["closed_cycles"], "fees": m["fees"], "groups": groups}


def main():
    mandate = d.DeliveryContent.from_dict(read(F / "assets/deliveries/MANDATE/3/delivery.json")["content"])
    benchmark = next(x.requirement.benchmark for x in mandate.payload.items if x.item_id == "benchmark")
    spec = benchmark.execution.execution_spec
    ctx = create_research_context(R, B, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=spec, resources=ExecutionResources(1, 1, 17))
    e = d.ExperimentRef("S018", "EX059_20261103")
    if not (F / "experiments" / e.experiment_id / "experiment.json").exists():
        assert create_experiment(ctx, ExperimentRequest('衰竭足额建仓与盈利延续组合', '只有M007 连续下跌后的抛压衰竭独立触发的盈利仓位延至第十一日，其他仍至第十日', date(2026,11,3))) == e
    w = F / "experiments" / e.experiment_id
    out = w / "others"
    out.mkdir(exist_ok=True)
    src = w / "src"
    src.mkdir(exist_ok=True)
    (src / "strategy.py").write_bytes(STRATEGY.encode())
    (src / "run.py").write_bytes(Path(__file__).read_bytes())
    protocol = {'baseline': 'EX053_20261103', 'change': '只有M007 连续下跌后的抛压衰竭独立触发的盈利仓位延至第十一日，其他仍至第十日', 'window': ['2023-01-03', '2026-10-30'], 'fee_each_side': 0.001, 'parameter_grid': False}

    save(out / "protocol.json", protocol)
    def material(name, path):
        return publish_evidence(ctx, d.MaterialEvidenceWrite(e, name, path.read_bytes(),
            "application/json" if path.suffix == ".json" else "text/x-python", path.suffix[1:]))
    protocol_ref = material("prototype-protocol", out / "protocol.json")
    p = read(F / "experiments/EX001_20261103/others/daily_preparation.json")["reference"]
    ref = PreparedDataRef(UUID(p["space_id"]), UUID(p["preparation_id"]), p["manifest_sha256"])
    source = SourceRef("futu", "s018-mu-daily-20261103")
    sources = d.EquitySources(source, source, SourceRef("s018-mu-actions", "futu-spglobal-crosscheck-v1"),
        SourceRef("s018-mu-rules", "daily-research-assumptions-v1"))
    instrument = InstrumentId(MarketId.US, AssetClass.STOCK, "MU")
    window = TimeInterval(pd.Timestamp("2023-01-03 09:30", tz="America/New_York").to_pydatetime(),
        pd.Timestamp("2026-10-30 16:00", tz="America/New_York").to_pydatetime())
    candidates = []
    for key in ("C9054",):
        definition = EquityStrategyDefinition(instrument, spec, 66, "strategy:step", ("strategy.py",),
            equity_source_hash(src, ("strategy.py",)),
            contract_version=4, feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema(cycle_fields=(StateField("month_only", StateValueType.BOOL), StateField("extended", StateValueType.BOOL), StateField("m007_only", StateValueType.BOOL))),
            computation=StrategyComputation.STATEFUL_STEP)
        candidates.append(EquityStrategyCandidate(B.strategy_id, key, definition, src))
    with d.ResearchExecutionSession(ctx, experiment=e) as session:
        handles = tuple(ctx.evaluation.prepare(d.EquityEvaluationRequest(e, c, window, date(2022,1,3),
            sources, 100000., .001, prepared=ref, benchmark=benchmark,
            window_id="MU_DEVELOPMENT", drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE"),
            execution=session) for c in candidates)
        outcomes = ctx.evaluation.evaluate_many(handles, execution=session)
        assert all(x.status.value == "SUCCEEDED" for x in outcomes), [x.error for x in outcomes]
        published = publish_evidence_many(ctx, tuple(d.EvaluationEvidenceWrite(e, "mu-" + c.candidate_id,
            handle, outcome.result) for c, handle, outcome in zip(candidates, handles, outcomes, strict=True)),
            execution=session)
        assert all(x.status.value == "PUBLISHED" for x in published)
        workload = asdict(session.equity_statistics)
        summary = {}
        for c, outcome, receipt in zip(candidates, outcomes, published, strict=True):
            result = outcome.result
            artifacts = {item.sha256: item for item in result.artifacts}
            run = json.loads(artifacts[result.payload["candidate_ref"]["sha256"]].content)["run"]
            bh = json.loads(artifacts[result.payload["benchmark_ref"]["sha256"]].content)["run"]
            summary[c.candidate_id] = {"candidate": stats(run), "benchmark": stats(bh),
                "account_ref": receipt.reference.to_dict(), "candidate_key": CandidateKey("S018", c.candidate_id).to_dict(),
                "identity": asdict(c.content_identity), "definition": c.definition.to_dict()}
    save(out / "results.json", {"results": summary, "workload": workload})
    baseline = read(F / "experiments/EX053_20261103/others/results.json")["results"]["C9048"]["candidate"]
    report = ['# 衰竭足额建仓与盈利延续组合', "", '沿用 EX053，只作以下变动。只有M007 连续下跌后的抛压衰竭独立触发的盈利仓位延至第十一日，其他仍至第十日。', "",
        "|方案|净年化|最大回撤|Calmar|60日中位|覆盖|闭合交易|", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, values in [(k, row["candidate"]) for k, row in summary.items()] + [("C9048", baseline), ("买持", summary["C9054"]["benchmark"])]:
        report.append(f"|{name}|{values['annual']:.2%}|{values['dd']:.2%}|{values['calmar']:.3f}|{values['frequency_median']}|{values['covered']}/{values['windows']}|{values['closed']}|")
    report+=["", "连续账本分段净收益、回撤和持仓覆盖见 [账户汇总](others/results.json)。"]
    body = ("\n".join(report)+"\n").encode()
    (w/"report.md").write_bytes(body)
    results_ref = material("prototype-results",out/"results.json")
    report_ref = publish_evidence(ctx,d.ExperimentReportWrite(e,sha256(body).hexdigest(),d.ExperimentOutcome.COMPLETED,
        (protocol_ref,results_ref,d.EvidenceRef.from_dict(read(F / "experiments/EX053_20261103/others/results.json")["results"]["C9048"]["account_ref"]))+tuple(d.EvidenceRef.from_dict(x["account_ref"]) for x in summary.values())))
    assert validate_experiment(R,d.ExperimentValidationRequest(e,d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
    save(out/"publication.json",{"report":report_ref.to_dict(),"protocol":protocol_ref.to_dict(),"results":results_ref.to_dict()})
    print(e.experiment_id, json.dumps({k:{x:v[x] for x in ("candidate","benchmark")} for k,v in summary.items()}, ensure_ascii=False))

if __name__ == "__main__":
    main()
