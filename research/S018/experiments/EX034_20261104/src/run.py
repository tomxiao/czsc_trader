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

STRATEGY = """from decimal import Decimal, ROUND_FLOOR
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.contracts import OrderSide, OrderType
from strategy_runtime.equity_replay import StateRecord
from strategy_runtime.replay_contracts import ReplayOrder


def step(ctx, state):
    bars = ctx.history.to_frame(tail=63)
    c = bars["Close"]
    o = bars["Open"]
    h = bars["High"]
    l = bars["Low"]
    price = float(c.iloc[-1])
    prev = float(c.iloc[-2])
    opening = float(o.iloc[-1])
    high = float(h.iloc[-1])
    low = float(l.iloc[-1])
    midpoint = (high + low) / 2
    prior_range = float((h-l).iloc[-11:-1].median())
    p = ctx.parameters
    down = price < prev
    recovered = price > midpoint
    oversold = down and prev - low >= prior_range
    trend = prev > float(c.iloc[-21:-1].median())
    direction = price > prev and recovered
    accelerating = direction and price > float(h.iloc[-2])
    gap_down = opening < prev
    gap_up = opening > prev
    lower_close = prev < float(c.iloc[-3]) and down
    signals = {
        "oversold": oversold, "absorb": oversold and recovered,
        "weak": oversold and not recovered, "two_down": lower_close,
        "trend_pullback": trend and lower_close,
        "strength": direction, "break": accelerating,
        "strength_no_break": direction and not accelerating,
        "gap_repair": gap_down and price > prev,
        "gap_fail": gap_up and price < opening and direction,
        "trend_strength": direction and trend,
        "pullback_or_strength": (trend and lower_close) or accelerating,
        "trend_absorb": oversold and recovered and trend,
    }
    background = c.iloc[:-2]
    advance10 = float(background.iloc[-1]) > float(background.iloc[-11])
    advance20 = float(background.iloc[-5:].median()) > float(background.iloc[-15:-5].median())
    slope = float(background.iloc[-5:].median()) > float(background.iloc[-10:-5].median())
    price_support = price >= float(background.iloc[-10:].median())
    no_break = price > float(l.iloc[-12:-2].min())
    contained = float(background.iloc[-1]) - price < prior_range
    recent_floor = price > float(c.iloc[-7:-2].min())
    medium_up = float(background.iloc[-1]) > float(background.iloc[-21])
    long_up = float(background.iloc[-1]) > float(background.iloc[-61])
    long_center_up = float(background.iloc[-20:].median()) > float(background.iloc[-60:-20].median())
    daily_range = (h-l) / c.shift()
    short_range = float(daily_range.iloc[-7:-2].median())
    longer_range = float(daily_range.iloc[-22:-7].median())
    expanding = short_range > longer_range
    current_range_shock = float(daily_range.iloc[-2:].max()) >= 2 * longer_range
    falling_majority = int((background.diff().iloc[-10:] < 0).sum()) >= 6
    early_peak = int(background.iloc[-10:].to_numpy().argmax()) < 5
    volume = bars["Volume"]
    vol_background = float(volume.iloc[-22:-2].median())
    quiet_both = float(volume.iloc[-2:].max()) < vol_background
    cooling = float(volume.iloc[-1]) < float(volume.iloc[-2])
    dominant_sell = float(volume.iloc[-1]) > vol_background and price <= midpoint
    previous_peak = float(c.iloc[-11:-1].max())
    stress = (1 - price / previous_peak) >= 2 * longer_range
    serial_weakness = int((c.diff().iloc[-5:] < 0).sum()) >= 4
    lower_peaks = float(h.iloc[-5:].max()) < float(h.iloc[-10:-5].max())
    downside_gap = opening < float(l.iloc[-2]) and price < float(l.iloc[-2])
    slowdown = price / prev > prev / float(c.iloc[-3])
    reject_lows = price > midpoint
    higher_low = low >= float(l.iloc[-2])
    overnight = opening < prev and price > opening
    signals.update({name: lower_close and flag for name, flag in {
        "medium_up": medium_up, "medium_down": not medium_up,
        "long_up": long_up, "long_down": not long_up,
        "long_center_up": long_center_up, "long_center_down": not long_center_up,
        "expanding": expanding, "not_expanding": not expanding,
        "range_shock": current_range_shock, "not_range_shock": not current_range_shock,
        "falling_majority": falling_majority, "not_falling_majority": not falling_majority,
        "early_peak": early_peak, "late_peak": not early_peak,
        "quiet_both": quiet_both, "not_quiet_both": not quiet_both,
        "cooling": cooling, "not_cooling": not cooling,
        "dominant_sell": dominant_sell, "not_dominant_sell": not dominant_sell,
        "stress": stress, "no_stress": not stress,
        "serial_weakness": serial_weakness, "no_serial_weakness": not serial_weakness,
        "lower_peaks": lower_peaks, "no_lower_peaks": not lower_peaks,
        "downside_gap": downside_gap, "no_downside_gap": not downside_gap,
        "shock_half": True, "calm_half": True,
        "slowdown": slowdown, "acceleration": not slowdown,
        "reject_lows": reject_lows, "accept_lows": not reject_lows,
        "higher_low": higher_low, "lower_low": not higher_low,
        "intraday_repair": overnight, "not_intraday_repair": not overnight,

        "up10": advance10, "not_up10": not advance10,
        "up_center": advance20, "not_up_center": not advance20,
        "up_recent_center": slope, "not_up_recent_center": not slope,
        "support": price_support, "not_support": not price_support,
        "no_break": no_break, "breakdown": not no_break,
        "contained": contained, "not_contained": not contained,
        "recent_floor": recent_floor, "not_recent_floor": not recent_floor,
        "up10_support": advance10 and price_support,
        "up10_no_break": advance10 and no_break,
        "up_center_no_break": advance20 and no_break,
    }.items()})
    delayed = prev < float(c.iloc[-3]) < float(c.iloc[-4])
    signals.update({
        "delay_all": delayed,
        "delay_up": delayed and price > prev,
        "delay_no_up": delayed and price <= prev,
        "delay_up_strong": delayed and price > prev and price > midpoint,
        "delay_up_weak": delayed and price > prev and price <= midpoint,
    })
    enter = signals[p["entry"]]
    active = ctx.position.active
    orders = ()
    allocation = p["allocation"]
    if (p["entry"] == "shock_half" and current_range_shock) or (p["entry"] == "calm_half" and not current_range_shock):
        allocation = 0.5
    if active is None:
        floor = low
        anchor = price if p["exit"] == "signal_line" else float(c.iloc[-3]) if p["exit"] == "predecline_line" else prev
        if p["entry"].startswith("delay_"):
            anchor = prev
        reason = "entry" if enter else "no opportunity"
        target = float(enter)
        if enter and allocation < 1:
            tick = Decimal("0.01")
            reference = Decimal(str(price)) * Decimal(str(ctx.portfolio.reference_price_scale))
            limit = (reference * Decimal("1.01") / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            cash = Decimal(str(ctx.account.available_cash)) * Decimal(str(allocation))
            quantity = int(cash / (limit * Decimal("1.001")))
            if quantity:
                orders = (ReplayOrder(OrderSide.BUY, quantity, OrderType.LIMIT, float(limit)),)
            else:
                target = 0.
    else:
        floor = state.cycle.values.get("floor")
        anchor = state.cycle.values.get("anchor")
        held = sum(stamp >= active.entry_interval.start for stamp in bars["Date"])
        mode = p["exit"]
        if mode == "repair":
            done = price >= anchor
            failed = price < floor
        elif mode == "trend":
            done = False
            failed = price < float(l.iloc[-3:-1].min())
        elif mode == "follow":
            done = False
            failed = price < prev and price < midpoint
        elif mode in ("signal_line", "predecline_line"):
            done = held >= 6 or (held >= 3 and price <= anchor)
            failed = False
        elif mode in ("winner", "cut", "winner_cut", "winner_trail"):
            profitable = price * active.quantity > active.buy_cost
            done = held >= 6 if mode != "cut" else held >= 3
            if mode != "cut":
                done = done or (held >= 3 and not profitable)
            failed = mode in ("cut", "winner_cut") and held == 2 and price <= prev and not profitable
            if mode == "winner_trail" and held >= 3:
                failed = price < float(l.iloc[-3:-1].min())
        else:
            done = held >= int(mode)
            failed = False
        reason = "failed" if failed else "complete" if done else "hold"
        target = float(reason == "hold")
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={"anchor": anchor, "floor": floor, "observed_signal": enter, "entry_allocation": allocation},
        next_watch="next complete daily bar", capital_mode="full_available_cash", orders=orders),
        cycle_values=StateRecord((("anchor", anchor), ("floor", floor))) if active is not None or target else None)
"""

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
    assert 34 <= number <= 63 and 2 <= len(configurations) <= 12
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
        candidate = EquityStrategyCandidate("S018", f"C{6000+number*12+index}", definition, src)
        candidates.append(candidate)
        requests.append(d.EquityEvaluationRequest(e, candidate, window, date(2022,1,3), sources, 100000., .001,
            prepared=prepared, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)), window_id="MU_DEVELOPMENT",
            drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE"))
    accounts = {}
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
            gates = {"calmar": x["calmar"] is not None and x["calmar"] >= 1.5*y["calmar"],
                "dd_absolute": x["dd"] <= .25, "dd_relative": x["dd"] <= .8*y["dd"],
                "median": x["median"] >= 6, "coverage": x["coverage"] >= .9}
            accounts[c.candidate_id] = dict(config=config, candidate=x, gates=gates, account_ref=receipt.reference.to_dict(),
                definition=c.definition.to_dict())
        workload = asdict(session.equity_statistics)
    save(out / "results.json", {"accounts": accounts, "benchmark": y, "workload": workload})
    refs.append(publish_evidence(ctx, d.MaterialEvidenceWrite(e, "results", (out / "results.json").read_bytes(), "application/json", "json")))
    lines = ["# MU 阶段二问题对照", "", title, "",
        f"新增 {len(accounts)} 个策略账户，引用 {len(baselines)} 个既有账户。沿用原开发池和标准费用。",
        "", "|配置|规则|净年化|回撤|净卡玛|闭合|中位|覆盖|通过|", "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for key, record in accounts.items():
        x = record["candidate"]
        lines.append(f"|{key}|{record['config']}|{x['annual']:.2%}|{x['dd']:.2%}|{x['calmar']}|{x['closed']}|{x['median']:g}|{x['coverage']:.2%}|{all(record['gates'].values())}|")
    lines += ["", "[协议](others/protocol.json) · [账户与逐项验收](others/results.json)"]
    body = ("\n".join(lines)+"\n").encode()
    (w / "report.md").write_bytes(body)
    publish_evidence(ctx, d.ExperimentReportWrite(e, sha256(body).hexdigest(), d.ExperimentOutcome.COMPLETED, tuple(refs)))
    assert validate_experiment(repo, d.ExperimentValidationRequest(e, d.ExperimentValidationScope.REPORT_PUBLICATION)).status is d.ValidationStatus.PASS
    print(e.experiment_id, [(k,v["config"],round(v["candidate"]["calmar"] or 0,3),round(v["candidate"]["dd"],3),v["candidate"]["median"],round(v["candidate"]["coverage"],3)) for k,v in accounts.items()], flush=True)

if __name__ == "__main__":
    main()

