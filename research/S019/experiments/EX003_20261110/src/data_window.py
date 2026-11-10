"""Prepare the approved 2021 warmup and unified 2022-2026 window."""
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID

import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import (
    BarFrequency, EquityDataRequest, EquityProduct, EquityQuery, MarketId,
    PreparedDataRef, PreparePolicy, PriceAdjustment, ProviderBinding, ProviderConfig,
    ProviderKey, SourceRef, futu_equity_bindings,
)
from dataflows.equity_data import equity_metadata, session_record, sessions_from_metadata
from strategy_runtime import ExecutionResources

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SHARED = ROOT / "research/S019/experiments/EX001_20261110/src"
sys.path.insert(0, str(SHARED))
from prepare_data import INSTRUMENTS, open_quotes  # noqa: E402
from load_data import load as load_previous  # noqa: E402

HISTORY_START, FIRST, LAST = date(2021, 1, 1), date(2022, 1, 3), date(2026, 10, 30)
SOURCE = SourceRef("futu", "s019-unified-window-20261110-v2")


def save(name, value):
    (WORK / "others" / name).write_bytes((json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n").encode())


def queries():
    return tuple(EquityDataRequest(instrument, SOURCE, EquityQuery(product, HISTORY_START, LAST, frequency,
        PriceAdjustment.BACKWARD if product is EquityProduct.BARS else PriceAdjustment.NONE))
        for frequency in (BarFrequency.DAILY, BarFrequency.M30)
        for instrument in INSTRUMENTS
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS))


def reference():
    row = json.loads((WORK / "others/preparation.json").read_text(encoding="utf-8"))["reference"]
    return PreparedDataRef(UUID(row["space_id"]), UUID(row["preparation_id"]), row["manifest_sha256"])


def load():
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S019"),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    prepared = reference()
    frames, metadata = {}, {}
    for query in queries():
        got = context.data.fetch(query, prepared=prepared)
        if not got.ready:
            raise RuntimeError(got.error)
        key = (query.parameters.instrument, query.parameters.query.frequency, query.parameters.query.product)
        frames[key], metadata[key] = got.dataframe, dict(got.identity.metadata)
    return frames, metadata


def prepare():
    quote = open_quotes()
    try:
        context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S019"),
            providers=ProviderConfig(bindings={}, equity_bindings=futu_equity_bindings(source=SOURCE, quote_context=quote)),
            resources=ExecutionResources(4, 1, 19))
        ready = context.data.prepare(queries(), policy=PreparePolicy.REUSE)
        summary = {"status": ready.status.value, "source": asdict(SOURCE),
            "history_start": str(HISTORY_START), "evaluation_start": str(FIRST), "evaluation_end": str(LAST),
            "reference": asdict(ready.reference) if ready.ready else None,
            "items": [{"symbol": x.request.parameters.instrument.symbol, "frequency": x.request.parameters.query.frequency.value,
                "product": x.request.parameters.query.product.value, "status": x.status.value,
                "error": str(x.error) if x.error else None} for x in ready.items]}
        save("preparation.json", summary)
        if not ready.ready:
            raise RuntimeError("Approved-window preparation failed; see preparation.json")
        print("PREPARED", flush=True)
    finally:
        quote.close()
    audit()


def audit():
    frames, metadata = load()
    previous = load_previous()
    rows, cross = [], []
    for (instrument, frequency, product), frame in frames.items():
        if product is not EquityProduct.BARS:
            continue
        days = frame.Date.dt.tz_convert(instrument.timezone).dt.date
        old = previous["daily" if frequency is BarFrequency.DAILY else "m30", instrument.symbol]
        overlap = frame.loc[days >= FIRST].reset_index(drop=True)
        columns = ["Date", "BarStart", "AvailableDate", "Open", "High", "Low", "Close", "Volume", "Amount"]
        assert overlap.Date.equals(old.Date)
        delta = (overlap[["Open", "High", "Low", "Close"]] / old[["Open", "High", "Low", "Close"]] - 1).abs().max().to_dict()
        changed = {column: int((~(overlap[column].eq(old[column]) | (overlap[column].isna() & old[column].isna()))).sum()) for column in columns}
        rows.append({"symbol": instrument.symbol, "frequency": frequency.value, "rows": len(frame),
            "warmup_rows": int((days < FIRST).sum()), "evaluation_rows": int((days >= FIRST).sum()),
            "first": str(days.iloc[0]), "last": str(days.iloc[-1]), "overlap_all_columns_equal": overlap[columns].equals(old[columns]),
            "overlap_max_relative_price_change": delta,
            "overlap_changed_value_counts": changed,
            "overlap_max_absolute_volume_amount_change": (overlap[["Volume", "Amount"]] - old[["Volume", "Amount"]]).abs().max().to_dict(),
            "metadata": {key: metadata[instrument, frequency, product].get(key) for key in
                ("acquisition_method", "price_basis_id", "publication_time_verified", "available_at", "download_receipts")}})
    for instrument in INSTRUMENTS:
        daily = frames[instrument, BarFrequency.DAILY, EquityProduct.BARS].copy()
        fine = frames[instrument, BarFrequency.M30, EquityProduct.BARS].copy()
        for frame in (daily, fine):
            frame["session"] = frame.Date.dt.tz_convert(instrument.timezone).dt.date
        aggregate = fine.groupby("session").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        daily = daily.set_index("session")
        assert daily.index.equals(aggregate.index)
        differences = (aggregate / daily[["Open", "High", "Low", "Close"]] - 1).abs()
        cross.append({"symbol": instrument.symbol, "sessions": len(daily),
            "warmup_sessions": sum(day < FIRST for day in daily.index),
            "evaluation_sessions": sum(day >= FIRST for day in daily.index),
            "cross_frequency_max_relative_difference": differences.max().to_dict()})
    version_path = ROOT / "strategies/S018/versions/v1.json"
    frozen = json.loads(version_path.read_text(encoding="utf-8"))
    definition = frozen["strategy_payload"]["equity_definition"]
    needed = max(definition["warmup_bars"], *(x["warmup_bars"] for x in definition["auxiliary_inputs"]), 64)
    assert all(x["warmup_sessions"] >= needed for x in cross)
    result = {"inputs": rows, "cross_frequency": cross, "required_daily_warmup_current": needed,
        "reference_definition_sha256": sha256(version_path.read_bytes()).hexdigest(),
        "warmup_policy": "Recheck each future candidate against its actual maximum lookback before evaluation; extend earlier input if needed without moving evaluation start."}
    save("sample_audit.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def replay_context(repository, execution_spec):
    frames, metadata = load()
    calendars = {}
    for instrument in INSTRUMENTS:
        calendars[instrument] = sessions_from_metadata(metadata[instrument, BarFrequency.DAILY, EquityProduct.SESSIONS])

    def fetch(request):
        p, q = request.parameters, request.parameters.query
        if p.source != SOURCE or p.instrument not in calendars or q.start < HISTORY_START or q.end > LAST:
            raise ValueError("Request outside the approved prepared source")
        sessions = tuple(s for s in calendars[p.instrument] if q.start <= s.session_date <= q.end)
        if q.product is EquityProduct.TRADING_FACTS:
            stamps = [bar.start for session in sessions for bar in session.bars(q.frequency)]
            frame = pd.DataFrame({"Date": stamps, "AvailableDate": stamps, "Tradable": True,
                "PriceLimitLower": None, "PriceLimitUpper": None})
            meta = equity_metadata(request, sessions, availability_basis="SESSION_ELIGIBILITY_RESEARCH_ASSUMPTION")
            meta.update(rule_basis="RESEARCH_ASSUMPTIONS", historical_halt_coverage_verified=False,
                assumption="Same declared S018-v1 research eligibility and unbounded-price assumptions; no historical intraday halt claim.")
            following = next((s for s in calendars[p.instrument] if s.session_date > q.end), None)
            if following:
                meta["following_session"] = session_record(following)
            return frame, meta
        original = frames[p.instrument, q.frequency, q.product]
        dates = original.Date.dt.tz_convert(p.instrument.timezone).dt.date
        selected = original.loc[(dates >= q.start) & (dates <= q.end)].copy().reset_index(drop=True)
        meta = dict(metadata[p.instrument, q.frequency, q.product])
        if q.start != HISTORY_START or q.end != LAST:
            raise ValueError("Bar and calendar replay requests must use the full prepared history")
        return selected, meta

    bindings = {ProviderKey(product, MarketId.US, SOURCE): ProviderBinding(SOURCE.provider, SOURCE.revision, fetch)
        for product in EquityProduct}
    return create_research_context(repository, ResearchBatchRef("S019"),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings), execution_spec=execution_spec,
        resources=ExecutionResources(4, 1, 19))


if __name__ == "__main__":
    {"prepare": prepare, "audit": audit}[sys.argv[1]]()
