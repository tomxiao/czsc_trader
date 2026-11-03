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
import optuna
from itertools import product

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
        if held == ctx.parameters["standard_days"]:
            extended = bool(close.iloc[-1] * active.quantity > active.buy_cost)
        time_stop = bool(held == 2 and close.iloc[-1] <= close.iloc[-2] and close.iloc[-1] * active.quantity <= active.buy_cost)
        target = float(held < ((ctx.parameters["m007_extension_days"] if m007_only else ctx.parameters["other_extension_days"]) if extended else ctx.parameters["standard_days"]) and not time_stop)
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
        fraction = Decimal(str(ctx.parameters["m015_fraction"])) if m015 and not (m007 or m022) else Decimal(1) if m007 and not (m015 or m022) else Decimal(str(ctx.parameters["other_fraction"])) if target else Decimal(1)
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

DEFAULTS = {"standard_days": 5, "m007_extension_days": 11, "other_extension_days": 10,
            "m015_fraction": .35, "other_fraction": .8}
SCHEMA = {"standard_days": {"type": "integer", "enum": [5]},
          "m007_extension_days": {"type": "integer", "minimum": 6, "maximum": 20},
          "other_extension_days": {"type": "integer", "minimum": 6, "maximum": 20},
          "m015_fraction": {"type": "number", "minimum": .1, "maximum": 1.0},
          "other_fraction": {"type": "number", "minimum": .1, "maximum": 1.0}}


def normalized(run):
    ids = {}
    for section, field in (("decisions", "decision_id"), ("orders", "order_id"),
                           ("fills", "fill_id"), ("fills", "cycle_id")):
        for item in run[section]:
            key = item[field]
            ids.setdefault(key, f"{field}/{len(ids)}")

    def visit(value):
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items() if k not in ("owner", "implementation")}
        if isinstance(value, list):
            return [visit(v) for v in value]
        return ids.get(value, value) if isinstance(value, str) else value

    return visit(run)


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
    expanded = '--expand' in sys.argv
    mandate = d.DeliveryContent.from_dict(read(F / "assets/deliveries/MANDATE/3/delivery.json")["content"])
    benchmark = next(x.requirement.benchmark for x in mandate.payload.items if x.item_id == "benchmark")
    spec = benchmark.execution.execution_spec
    ctx = create_research_context(R, B, providers=ProviderConfig(bindings={}, equity_bindings={}),
        execution_spec=spec, resources=ExecutionResources(3, 1, 17))
    e = d.ExperimentRef("S018", "EX062_20261103" if expanded else "EX061_20261103")
    if not (F / "experiments" / e.experiment_id / "experiment.json").exists():
        assert create_experiment(ctx, ExperimentRequest("MU仓位搜索扩边" if expanded else "MU仓位有限域搜索", "固定退出规则，Optuna依次记录预声明参数点", date(2026,11,3))) == e
    w = F / "experiments" / e.experiment_id
    out = w / "others"
    out.mkdir(exist_ok=True)
    src = w / "src"
    src.mkdir(exist_ok=True)
    (src / "strategy.py").write_bytes(STRATEGY.encode())
    (src / "run.py").write_bytes(Path(__file__).read_bytes())
    strengths = [.20, .25, .30, .35, .40, .45, .50] if expanded else [.30, .35, .40]
    others = [.70, .75, .80, .85, .90] if expanded else [.75, .80, .85]
    previous = set(product([.30, .35, .40], [.75, .80, .85])) if expanded else {(.35, .80)}
    points = [(a,b) for a,b in product(strengths,others) if (a,b) not in previous]
    protocol = {"baseline":"EX060_20261103","method":"Optuna 固定点入队，批量账户计算",
        "seed":17,"optuna":optuna.__version__,"domains":{"m015_fraction":strengths,"other_fraction":others},
        "points":points,"fixed":DEFAULTS,"window":["2023-01-03","2026-10-30"],"fee_each_side":.001,
        "max_workers":3,"selection":"保留同时通过所有既定硬门的配置；其余作为前沿诊断"}
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
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.RandomSampler(seed=17))
    trials = []
    for index, (strength, other) in enumerate(points, start=9100 if expanded else 9060):
        study.enqueue_trial({"m015_fraction":strength,"other_fraction":other})
        trial = study.ask()
        params = dict(DEFAULTS, m015_fraction=trial.suggest_categorical("m015_fraction",strengths),
                      other_fraction=trial.suggest_categorical("other_fraction",others))
        key = f"C{index}"
        trials.append(trial)
        definition = EquityStrategyDefinition(instrument, spec, 66, "strategy:step", ("strategy.py",),
            equity_source_hash(src, ("strategy.py",)),
            contract_version=4, feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema(cycle_fields=(StateField("month_only", StateValueType.BOOL), StateField("extended", StateValueType.BOOL), StateField("m007_only", StateValueType.BOOL))),
            computation=StrategyComputation.STATEFUL_STEP, parameters_json=json.dumps(params), parameter_schema_json=json.dumps(SCHEMA))
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
    for trial, (key, record) in zip(trials, summary.items(), strict=True):
        x,b = record["candidate"],record["benchmark"]
        gates = {"calmar":x["calmar"]>=1.5*b["calmar"],"absolute_dd":x["dd"]<=.25,
                 "relative_dd":x["dd"]<=.8*b["dd"],"frequency_median":x["frequency_median"]>=6,
                 "frequency_coverage":10*x["covered"]>=9*x["windows"]}
        record["gates"] = gates
        trial.set_user_attr("candidate",key)
        trial.set_user_attr("gates",gates)
        study.tell(trial,x["calmar"])
    save(out/"results.json",{"results":summary,"workload":workload,
         "trials":[{"number":t.number,"params":t.params,"value":t.value,"state":t.state.name,
                    "user_attrs":t.user_attrs} for t in study.trials]})
    report = ["# MU仓位搜索扩边" if expanded else "# MU仓位有限域搜索","",
              f"Optuna {optuna.__version__} 固定入队，{len(points)} 个新增点。退出规则、开发窗口、费用及基准沿用 EX060。","",
              "|配置|净年化|最大回撤|净 Calmar|60日中位|覆盖|硬门|","|---|---:|---:|---:|---:|---:|---|"]
    for key,record in summary.items():
        x=record["candidate"]
        report.append(f"|{key}|{x['annual']:.2%}|{x['dd']:.2%}|{x['calmar']:.6f}|{x['frequency_median']:g}|{x['covered']}/{x['windows']}|{'通过' if all(record['gates'].values()) else '未通过'}|")
    report += ["","[参数、试验轨迹与账户](others/results.json)。"]
    body = ("\n".join(report)+"\n").encode()
    (w/"report.md").write_bytes(body)
    results_ref = material("prototype-results",out/"results.json")
    report_ref = publish_evidence(ctx,d.ExperimentReportWrite(e,sha256(body).hexdigest(),d.ExperimentOutcome.COMPLETED,
        (protocol_ref,results_ref,d.EvidenceRef.from_dict(read(F / "experiments/EX060_20261103/others/results.json")["results"]["C9055"]["account_ref"]))+tuple(d.EvidenceRef.from_dict(x["account_ref"]) for x in summary.values())))
    assert validate_experiment(R,d.ExperimentValidationRequest(e,d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
    save(out/"publication.json",{"report":report_ref.to_dict(),"protocol":protocol_ref.to_dict(),"results":results_ref.to_dict()})
    print(e.experiment_id, [(k, round(v["candidate"]["calmar"],5), round(v["candidate"]["dd"],5), all(v["gates"].values())) for k,v in summary.items()])

if __name__ == "__main__":
    main()
