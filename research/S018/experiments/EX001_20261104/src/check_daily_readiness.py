"""Check MU daily data and dividend accounting with a fixed infrastructure probe."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys
from datetime import date, datetime, time
from dataclasses import asdict
from zoneinfo import ZoneInfo
import json
import types

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
OUT = WORK / "others"
os.environ["TMP"] = os.environ["TEMP"] = str(ROOT / ".tmp")
sys.pycache_prefix = str(ROOT / ".tmp/s018-pycache")

from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence_many
from dataflows import (AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparePolicy, ProviderBinding, ProviderConfig, ProviderKey, SourceRef,
    TimeInterval, UsEquityBarPolicy, futu_equity_bindings)
from strategy_runtime import ExecutionResources
from strategy_runtime.equity_definition import (EquityStrategyCandidate, EquityStrategyDefinition,
    equity_source_hash, execution_spec_from_dict)
from strategy_runtime.equity_features import FeatureGraph
from strategy_runtime.equity_replay import StrategyStateSchema
from strategy_runtime.equity_buy_hold_v4 import __file__ as probe_source
from strategy_runtime.replay_contracts import StrategyComputation
import pandas as pd

ZONE = ZoneInfo("America/New_York")
FIRST, LAST = date(2022, 1, 3), date(2026, 10, 30)
SOURCE = SourceRef("futu", "s018-mu-daily-20261104")
ACTIONS = SourceRef("s018-mu-actions", "futu-spglobal-crosscheck-v1")
RULES = SourceRef("s018-mu-rules", "daily-research-assumptions-v1")
INSTRUMENT = InstrumentId(MarketId.US, AssetClass.STOCK, "MU")
BATCH = d.ResearchBatchRef("S018")
EXPERIMENT = d.ExperimentRef("S018", "EX001_20261104")

# Ex-date and exact amount from Futu, payment date cross-checked against S&P
# Global's event table. Latest 2026 payment also verified in issuer filings.
PAYMENTS = {
    "2022-04-08": ("2022-04-26", .10), "2022-07-08": ("2022-07-26", .115),
    "2022-10-07": ("2022-10-26", .115), "2022-12-30": ("2023-01-19", .115),
    "2023-04-06": ("2023-04-25", .115), "2023-07-07": ("2023-07-25", .115),
    "2023-10-06": ("2023-10-25", .115), "2023-12-29": ("2024-01-18", .115),
    "2024-03-28": ("2024-04-16", .115), "2024-07-08": ("2024-07-23", .115),
    "2024-10-07": ("2024-10-23", .115), "2024-12-30": ("2025-01-15", .115),
    "2025-03-31": ("2025-04-15", .115), "2025-07-07": ("2025-07-22", .115),
    "2025-10-03": ("2025-10-21", .115), "2025-12-29": ("2026-01-14", .115),
    "2026-03-30": ("2026-04-15", .15), "2026-07-06": ("2026-07-21", .15),
    "2026-10-14": ("2026-10-29", .15),
}


def save(name, obj):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_bytes((json.dumps(obj, ensure_ascii=False, indent=2, default=str,
        allow_nan=False) + "\n").encode())


def stamp(day, hour, minute=0):
    return datetime.combine(date.fromisoformat(day), time(hour, minute), ZONE)


def prepare(quote, repo, spec):
    original = futu_equity_bindings(source=SOURCE, quote_context=quote, maximum_pages=3,
        research_policy=UsEquityBarPolicy(1, .01))
    bindings = {k: v for k, v in original.items() if k.product in (EquityProduct.BARS, EquityProduct.SESSIONS)}
    ret, events = quote.get_rehab("US.MU")
    if ret != 0:
        raise ValueError(str(events))
    actual = {str(x["ex_div_date"]): x for x in events.to_dict("records")
              if FIRST.isoformat() <= str(x["ex_div_date"]) <= LAST.isoformat()}
    if set(actual) != set(PAYMENTS):
        raise ValueError("Corporate action dates differ from payment source")
    for day, (_, amount) in PAYMENTS.items():
        event = actual[day]
        if event["per_cash_div"] != amount or any(pd.notna(event.get(field)) and event[field] != 0
                for field in ("split_ratio", "special_dividend", "per_share_div_ratio",
                              "per_share_trans_ratio", "allotment_ratio", "stk_spo_ratio", "spin_off_ratio")):
            raise ValueError(f"Unexpected corporate action at {day}")
    save("dividend_sources.json", {"events": [
        {"ex_date": day, "payment_date": pay, "cash_per_share": amount}
        for day, (pay, amount) in PAYMENTS.items()],
        "sources": ["Futu get_rehab US.MU", "https://stockanalysis.com/stocks/mu/dividend/",
            "https://dividendhistory.org/payout/MU/",
            "https://investors.micron.com/static-files/236af4a3-d99f-4287-b088-09721d0f6ace",
            "https://investors.micron.com/financials/quarterly-results/"],
        "availability": "Effective session open. Payment at 16:00 ET is a conservative daily assumption, not broker intraday evidence."})

    def enrich(request):
        p = request.parameters
        product = p.query.product
        base = EquityProduct.SESSIONS if product is EquityProduct.ACTIONS else EquityProduct.CONSTRAINTS
        source_req = EquityDataRequest(p.instrument, SOURCE,
            EquityQuery(base, p.query.start, p.query.end, p.query.frequency))
        frame, meta = original[ProviderKey(base, MarketId.US, SOURCE)].fetch(source_req)
        meta.update(vendor=p.source.provider, source_revision=p.source.revision)
        if product is EquityProduct.ACTIONS:
            rows = [{"Date": stamp(day, 9, 30), "AvailableDate": stamp(day, 9, 30),
                "EventId": f"MU-{day}-cash", "Kind": "CASH_DIVIDEND", "Ratio": 1.,
                "CashPerShare": amount, "PayAt": stamp(pay, 16)}
                for day, (pay, amount) in PAYMENTS.items()
                if p.query.start.isoformat() <= day <= p.query.end.isoformat()]
            return pd.DataFrame(rows), meta
        frame["PriceLimitPolicy"] = "EXPLICIT_UNBOUNDED"
        frame["PriceLimitLower"], frame["PriceLimitUpper"] = None, None
        frame["BuySellableAt"], frame["SettlementAt"] = frame.Date, frame.Date
        frame["SellRemainderPolicy"] = "STRICT_STEP"
        meta.update(constraint_contract="DATED_EQUITY_RULES_V1", rule_basis="RESEARCH_ASSUMPTIONS")
        return frame, meta

    for product, source in [(EquityProduct.ACTIONS, ACTIONS), (EquityProduct.CONSTRAINTS, RULES)]:
        bindings[ProviderKey(product, MarketId.US, source)] = ProviderBinding(source.provider, source.revision, enrich)
    sources = d.EquitySources(SOURCE, SOURCE, ACTIONS, RULES)
    requests = tuple(EquityDataRequest(INSTRUMENT, source,
        EquityQuery(product, FIRST, LAST, BarFrequency.DAILY))
        for product, source in zip(EquityProduct, (SOURCE, SOURCE, ACTIONS, RULES), strict=True))
    # Capture independent calendar rows and observed-bar coverage using the same
    # provider contract before handing these exact results to DFLS.
    captured = {}
    for request in requests:
        p = request.parameters
        key = ProviderKey(p.query.product, MarketId.US, p.source)
        captured[key] = bindings[key].fetch(request)
    bars, _ = captured[ProviderKey(EquityProduct.BARS, MarketId.US, SOURCE)]
    calendar, _ = captured[ProviderKey(EquityProduct.SESSIONS, MarketId.US, SOURCE)]
    if len(bars) != len(calendar) or not bars.BarStatus.eq("OBSERVED").all():
        raise ValueError("Missing or zero-volume daily sessions")
    if list(pd.to_datetime(bars.Date, utc=True).dt.tz_convert(ZONE).dt.date.astype(str)) != list(calendar.SessionDate):
        raise ValueError("Daily history differs from exchange calendar session dates")
    retained = {k: ProviderBinding(k.source.provider, k.source.revision, lambda request, pair=pair: pair)
                for k, pair in captured.items()}
    context = create_research_context(repo, BATCH, providers=ProviderConfig(bindings={}, equity_bindings=retained),
        execution_spec=spec, resources=ExecutionResources(1, 1, 17))
    ready = context.data.prepare(requests, policy=PreparePolicy.REUSE)
    save("daily_preparation.json", {"status": ready.status.value,
        "items": [{"product": x.request.parameters.query.product.value, "status": x.status.value,
                   "error": None if x.error is None else asdict(x.error),
                   "sha256": None if x.identity is None else x.identity.content_sha256} for x in ready.items],
        "reference": None if not ready.ready else asdict(ready.reference),
        "start": FIRST, "end": LAST, "sessions": len(calendar), "bars": len(bars),
        "observed_development_sessions": int((calendar.SessionDate >= "2023-01-03").sum()),
        "corporate_actions": len(PAYMENTS), "calendar_source": "Futu request_trading_days",
        "bars_source": "Futu request_history_kline raw daily"})
    if not ready.ready:
        raise ValueError("DFLS preparation incomplete")
    return context, sources, ready.reference


def probe(context, sources, prepared, spec):
    source_root = WORK / "src/probe"
    source_root.mkdir(exist_ok=True)
    (source_root / "strategy.py").write_bytes(Path(probe_source).read_bytes())
    definition = EquityStrategyDefinition(INSTRUMENT, spec, 1, "strategy:step", ("strategy.py",),
        equity_source_hash(source_root, ("strategy.py",)), contract_version=4,
        feature_graph=FeatureGraph((), ()), state_schema=StrategyStateSchema(),
        computation=StrategyComputation.STATEFUL_STEP)
    candidate = EquityStrategyCandidate("S018", "C9999", definition, source_root)
    req = d.EquityEvaluationRequest(EXPERIMENT, candidate,
        TimeInterval(stamp("2026-03-23", 9, 30), stamp(LAST.isoformat(), 16)), FIRST,
        sources, 100000., .001, prepared=prepared, benchmark=d.EvaluationBenchmark(d.EquityBuyHold(spec)),
        window_id="DAILY_INFRASTRUCTURE_PROBE", drawdown_basis="BAR_CLOSE", concentration_basis="MAX_SINGLE")
    with d.ResearchExecutionSession(context, experiment=EXPERIMENT) as session:
        handle = context.evaluation.prepare(req, execution=session)
        outcome, = context.evaluation.evaluate_many((handle,), execution=session)
        if outcome.status.value != "SUCCEEDED":
            raise ValueError(str(outcome.error))
        result = outcome.result
        artifacts = {item.sha256: item for item in result.artifacts}
        checks = {}
        for label in ("candidate", "benchmark"):
            run = json.loads(artifacts[result.payload[label + "_ref"]["sha256"]].content)["run"]
            accrual, payment = [row for row in run["actions"] if row["event_id"] == "MU-2026-03-30-cash"]
            assert accrual["kind"] == "CASH_DIVIDEND" and payment["kind"] == "DIVIDEND_PAYMENT"
            assert accrual["quantity_before"] > 0 and accrual["cash_delta"] == 0.
            assert abs(accrual["receivable_delta"] - .15 * accrual["quantity_before"]) < 1e-9
            assert abs(payment["cash_delta"] - accrual["receivable_delta"]) < 1e-9
            assert abs(payment["receivable_delta"] + accrual["receivable_delta"]) < 1e-9
            assert accrual["time"][:10] == "2026-03-30" and payment["time"][:10] == "2026-04-15"
            checks[label] = {"accrual": accrual, "payment": payment, "sessions": run["metrics"]["sessions"]}
        publication, = publish_evidence_many(context, (d.EvaluationEvidenceWrite(EXPERIMENT,
            "daily-readiness-dividend-probe", handle, result),), execution=session)
        if publication.status.value != "PUBLISHED":
            raise ValueError(str(publication.error))
        save("daily_account_probe.json", {"status": "PASS", "window": ["2026-03-23", LAST.isoformat()],
            "purpose": "execution and dividend accrual/payment only", "checks": checks,
            "evidence": publication.reference.to_dict(), "statistics": asdict(session.equity_statistics)})
        print("S018 DAILY ACCOUNT PASS", checks["candidate"])


def main():
    # Keep the SDK's import-time log output inside the research scratch space.
    module_name = "futu.common.ft_logger"
    logger_file = ROOT / ".venv/Lib/site-packages/futu/common/ft_logger.py"
    logger_code = logger_file.read_text(encoding="utf-8")
    marker = '__LogPathName__ = "com.futunn.FutuOpenD/Log"'
    if logger_code.count(marker) != 1:
        raise RuntimeError("Unexpected Futu SDK logger layout")
    logger_module = types.ModuleType(module_name)
    logger_module.__file__ = str(logger_file)
    logger_module.__package__ = "futu.common"
    sys.modules[module_name] = logger_module
    redirected = logger_code.replace(marker, "__LogPathName__ = " + repr(str(ROOT / ".tmp/s018-futu-logs")))
    exec(compile(redirected, str(logger_file), "exec"), logger_module.__dict__)
    import futu as ft
    ft.SysConfig.enable_console_log(False)
    ft.SysConfig.set_all_thread_daemon(True)
    spec = execution_spec_from_dict({
        "market": {"rule_version": "US_EQUITY_V1"}, "decision_clock": "daily",
        "account": {"currency": "USD", "cash_availability": "IMMEDIATE_RESEARCH",
                    "allow_short": False, "allow_negative_cash": False},
        "quantity_step": 1, "price_tick": .01, "buy_premium": .01, "slippage_bp": 0.,
        "execution": "BAR_RANGE_V1", "inclusive_touch": False, "data_latency_seconds": 0,
    })
    quote = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        context, sources, prepared = prepare(quote, RepositoryContext.discover(ROOT), spec)
    finally:
        quote.close()
    probe(context, sources, prepared, spec)


if __name__ == "__main__":
    main()
