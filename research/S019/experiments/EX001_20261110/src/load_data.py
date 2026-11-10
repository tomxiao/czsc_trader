"""Read this batch's prepared observations through public DFLS."""
import json
from uuid import UUID

from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import BarFrequency, EquityProduct, PreparedDataRef, ProviderConfig
from prepare_data import ROOT, WORK, DAILY_SOURCE, M30_SOURCE, requests, save


def load():
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S019"),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    frames = {}
    for name, source, frequency in (("daily", DAILY_SOURCE, BarFrequency.DAILY), ("m30", M30_SOURCE, BarFrequency.M30)):
        receipt = json.loads((WORK / "others" / f"{name}_preparation.json").read_text(encoding="utf-8"))
        ref = receipt["reference"]
        prepared = PreparedDataRef(UUID(ref["space_id"]), UUID(ref["preparation_id"]), ref["manifest_sha256"])
        for request in requests(source, frequency):
            if request.parameters.query.product is EquityProduct.SESSIONS:
                continue
            result = context.data.fetch(request, prepared=prepared)
            if not result.ready:
                raise RuntimeError(result.error)
            frame = result.dataframe.copy()
            frame["session"] = frame.Date.dt.tz_convert("America/New_York").dt.date
            frames[name, request.parameters.instrument.symbol] = frame
    return frames


def audit():
    frames = load()
    checks = {}
    for symbol in ("MU", "SOXX"):
        daily = frames["daily", symbol].set_index("session")
        fine = frames["m30", symbol].groupby("session").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
        assert daily.index.equals(fine.index)
        assert (daily.Open == fine.Open).all() and (daily.Close == fine.Close).all()
        diff = (fine / daily[["Open", "High", "Low", "Close"]] - 1).abs()
        checks[symbol] = {"daily_rows": len(daily), "m30_rows": len(frames["m30", symbol]),
            "open_close_exact_match": True, "maximum_relative_difference": diff.max().to_dict(),
            "largest_high_difference_date": str(diff.High.idxmax()),
            "high_difference_days": int((diff.High > 1e-12).sum()),
            "low_difference_days": int((diff.Low > 1e-12).sum())}
    save("cross_frequency_audit.json", {"checks": checks,
        "usage": "Use retained daily close observations for daily signals; explicitly use M30 prices for intraday event execution. Retain original daily extremes and report frequency-dependent touch differences.",
        "dynamic_trading_facts": "Require explicit preparation before formal account evaluation."})
    print(json.dumps(checks))


if __name__ == "__main__":
    audit()
