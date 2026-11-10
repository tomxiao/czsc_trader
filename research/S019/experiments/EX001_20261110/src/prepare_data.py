"""Prepare retained daily and fresh M30 observations through public DFLS."""
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
import types
from uuid import UUID

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import (
    AssetClass, BarFrequency, EquityDataRequest, EquityProduct, EquityQuery,
    InstrumentId, MarketId, PreparedDataRef, PreparePolicy, PriceAdjustment,
    ProviderBinding, ProviderConfig, ProviderKey, SourceRef, futu_equity_bindings,
)
from strategy_runtime import ExecutionResources

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
FIRST, LAST = date(2022, 1, 3), date(2026, 10, 30)
DAILY_SOURCE = SourceRef("futu", "s018-hfq-target-repack-20261108-v1")
M30_SOURCE = SourceRef("futu", "s019-mu-soxx-m30-20261110-v1")
INSTRUMENTS = (
    InstrumentId(MarketId.US, AssetClass.STOCK, "MU"),
    InstrumentId(MarketId.US, AssetClass.ETF, "SOXX"),
)


def save(name, value):
    (WORK / "others" / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def requests(source, frequency):
    return tuple(
        EquityDataRequest(instrument, source, EquityQuery(
            product, FIRST, LAST, frequency,
            PriceAdjustment.BACKWARD if product is EquityProduct.BARS else PriceAdjustment.NONE,
        ))
        for instrument in INSTRUMENTS
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS)
    )


def prepare(context, queries, name):
    ready = context.data.prepare(queries, policy=PreparePolicy.REUSE)
    summary = {
        "status": ready.status.value,
        "reference": asdict(ready.reference) if ready.ready else None,
        "items": [{"symbol": item.request.parameters.instrument.symbol,
                   "product": item.request.parameters.query.product.value,
                   "status": item.status.value,
                   "error": str(item.error) if item.error else None}
                  for item in ready.items],
    }
    if ready.ready:
        summary["inputs"] = []
        for query in queries:
            result = context.data.fetch(query, prepared=ready.reference)
            if not result.ready:
                raise RuntimeError(result.error)
            frame = result.dataframe
            summary["inputs"].append({
                "request": query.to_dict() if hasattr(query, "to_dict") else asdict(query),
                "content_sha256": result.identity.content_sha256,
                "rows": len(frame), "first": str(frame.Date.min()), "last": str(frame.Date.max()),
                "metadata": dict(result.identity.metadata),
            })
    save(name, summary)
    print(name, summary["status"], flush=True)
    return summary


def daily(repository):
    source_path = ROOT / "research/S018/experiments/EX069_20261108/others/data_inputs.json"
    source_bytes = source_path.read_bytes()
    ref = json.loads(source_bytes)["prepared"]
    reference = PreparedDataRef(UUID(ref["space_id"]), UUID(ref["preparation_id"]), ref["manifest_sha256"])
    old = create_research_context(repository, ResearchBatchRef("S018"),
        providers=ProviderConfig(bindings={}, equity_bindings={}), resources=ExecutionResources(1, 1, 19))
    captured = {}
    queries = requests(DAILY_SOURCE, BarFrequency.DAILY)
    for query in queries:
        result = old.data.fetch(query, prepared=reference)
        if not result.ready:
            raise RuntimeError(result.error)
        captured[query.parameters] = (result.dataframe.copy(), dict(result.identity.metadata))

    def fetch(request):
        return captured[request.parameters]

    bindings = {ProviderKey(product, MarketId.US, DAILY_SOURCE):
        ProviderBinding(DAILY_SOURCE.provider, DAILY_SOURCE.revision, fetch)
        for product in (EquityProduct.BARS, EquityProduct.SESSIONS)}
    context = create_research_context(repository, ResearchBatchRef("S019"),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings), resources=ExecutionResources(4, 1, 19))
    summary = prepare(context, queries, "daily_preparation.json")
    summary["reuse"] = {"source_record": source_path.relative_to(ROOT).as_posix(),
        "source_record_sha256": sha256(source_bytes).hexdigest(), "prepared": ref,
        "operation": "PUBLIC_DFLS_FETCH_AND_NEW_BATCH_PREPARE_UNCHANGED_VALUES"}
    save("daily_preparation.json", summary)
    if summary["status"] != "READY":
        raise RuntimeError("Daily data preparation failed")


def open_quotes():
    # Match the established research-only logger relocation; keep SDK files intact.
    name = "futu.common.ft_logger"
    path = ROOT / ".venv/Lib/site-packages/futu/common/ft_logger.py"
    code = path.read_text(encoding="utf-8")
    marker = '__LogPathName__ = "com.futunn.FutuOpenD/Log"'
    if code.count(marker) != 1:
        raise RuntimeError("Futu log-path declaration changed")
    module = types.ModuleType(name)
    module.__file__, module.__package__ = str(path), "futu.common"
    sys.modules[name] = module
    code = code.replace(marker, "__LogPathName__ = " + repr(str(ROOT / ".tmp/s019-futu-logs")))
    exec(compile(code, str(path), "exec"), module.__dict__)
    import futu
    futu.SysConfig.enable_console_log(False)
    futu.SysConfig.set_all_thread_daemon(True)
    quote = futu.OpenQuoteContext(host="127.0.0.1", port=11111, is_async_connect=True)
    quote.set_sync_query_connect_timeout(15)
    return quote


def m30(repository):
    quote = open_quotes()
    try:
        bindings = futu_equity_bindings(source=M30_SOURCE, quote_context=quote)
        context = create_research_context(repository, ResearchBatchRef("S019"),
            providers=ProviderConfig(bindings={}, equity_bindings=bindings), resources=ExecutionResources(4, 1, 19))
        prepare(context, requests(M30_SOURCE, BarFrequency.M30), "m30_preparation.json")
    finally:
        quote.close()


if __name__ == "__main__":
    repository = RepositoryContext.discover(ROOT)
    {"daily": daily, "m30": m30}[sys.argv[1]](repository)
