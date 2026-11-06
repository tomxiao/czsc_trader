"""Bounded owner-supplied economic facts through the public DFLS path."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from dataflows import (
    AssetClass,
    BarFrequency,
    Dataflows,
    DataSpace,
    EquityDataRequest,
    EquityProduct,
    EquityQuery,
    InstrumentId,
    MarketId,
    PreparePolicy,
    ProviderBinding,
    ProviderConfig,
    SourceRef,
    TimeInterval,
    TradingSession,
    equity_evidence_bindings,
)
from dataflows.equity_data import equity_metadata
from dataflows.errors import DataContractError, IncompleteDataError


def fixture(tmp_path, market, frequency, *, no_events=False):
    source = SourceRef("explicit-economic-fixture", "v1")
    instrument = InstrumentId(
        market, AssetClass.STOCK, "600000.SH" if market is MarketId.CN else "MU"
    )
    zone = ZoneInfo(instrument.timezone)
    days = (date(2026, 11, 5), date(2026, 11, 6))
    hours = ((9, 30, 11, 30), (13, 0, 15, 0)) if market is MarketId.CN else ((9, 30, 16, 0),)
    sessions = tuple(
        TradingSession(
            day,
            str(zone),
            tuple(
                TimeInterval(
                    datetime(day.year, day.month, day.day, a, b, tzinfo=zone),
                    datetime(day.year, day.month, day.day, c, d, tzinfo=zone),
                )
                for a, b, c, d in hours
            ),
        )
        for day in days
    )

    def calendar(request):
        chosen = tuple(
            s
            for s in sessions
            if request.parameters.query.start <= s.session_date <= request.parameters.query.end
        )
        return pd.DataFrame(
            {
                "Date": [s.segments[0].start for s in chosen],
                "AvailableDate": [s.segments[0].start for s in chosen],
                "SessionDate": [s.session_date.isoformat() for s in chosen],
            }
        ), equity_metadata(request, chosen, availability_basis="FIXTURE")

    rules = []
    for session in sessions:
        for bar in session.bars(frequency):
            rules.append(
                dict(
                    Date=bar.start.isoformat(),
                    AvailableDate=bar.start.isoformat(),
                    QuantityStep=100 if market is MarketId.CN else 1,
                    PriceTick=0.01,
                    Tradable=True,
                    PriceLimitPolicy="DATED_LIMITS"
                    if market is MarketId.CN
                    else "EXPLICIT_UNBOUNDED",
                    PriceLimitLower=5.0 if market is MarketId.CN else None,
                    PriceLimitUpper=15.0 if market is MarketId.CN else None,
                    SellRemainderPolicy="FULL_LIQUIDATION",
                    BuySellableAt=(
                        bar.start + timedelta(days=1) if market is MarketId.CN else bar.start
                    ).isoformat(),
                    SettlementAt=(bar.start + timedelta(days=1)).isoformat(),
                )
            )
    stamp = sessions[1].segments[0].start.isoformat()
    events = (
        []
        if no_events
        else [
            dict(
                Date=stamp,
                AvailableDate=sessions[0].segments[0].start.isoformat(),
                EventId="cash-1",
                Kind="CASH_DIVIDEND",
                CashPerShare=0.5,
                Ratio=1.0,
                PayAt=stamp,
            )
        ]
    )

    def asset(name, value):
        data = json.dumps(value).encode()
        (tmp_path / name).write_bytes(data)
        return dict(path=name, sha256=sha256(data).hexdigest())

    evidence = asset(
        "receipt.json", {"scope": "Synthetic input/output contract test; not verified market facts"}
    )
    bounds = {"start": days[0].isoformat(), "end": days[1].isoformat(), "evidence": evidence}
    manifest = {
        "schema_version": 1,
        "source": asdict(source),
        "market": market.value,
        "instruments": [
            {
                "instrument": asdict(instrument),
                "actions": bounds | {"complete": True, "data": asset("actions.json", events)},
                "constraints": {frequency.value: bounds | {"data": asset("rules.json", rules)}},
            }
        ],
    }
    path = tmp_path / "manifest.json"

    def save():
        path.write_text(json.dumps(manifest), encoding="utf-8")

    save()
    bindings = equity_evidence_bindings(
        source=source,
        market=market,
        manifest_path=path,
        session_binding=ProviderBinding("calendar", "v1", calendar),
    )

    def request(product, start=days[0], end=days[1]):
        return EquityDataRequest(instrument, source, EquityQuery(product, start, end, frequency))

    return manifest, bindings, request, asset, save


@pytest.mark.parametrize("market", list(MarketId))
@pytest.mark.parametrize("frequency", list(BarFrequency))
def test_public_preparation_pins_dated_rules_and_cash_payment(tmp_path, market, frequency):
    _, bindings, request, _, _ = fixture(tmp_path, market, frequency)
    flows = Dataflows(
        base_dir=tmp_path,
        space=DataSpace(Path("assets")),
        providers=ProviderConfig(bindings={}, equity_bindings=bindings),
    )
    requests = tuple(request(p) for p in (EquityProduct.ACTIONS, EquityProduct.CONSTRAINTS))
    prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert prepared.ready, [item.error for item in prepared.items]
    actions = flows.fetch(requests[0], prepared=prepared.reference)
    assert actions.dataframe.CashPerShare.tolist() == [0.5]
    assert actions.identity.metadata["action_history_complete"] is True
    rules = flows.fetch(requests[1], prepared=prepared.reference)
    assert len(rules.dataframe) == (
        2 if frequency is BarFrequency.DAILY else 16 if market is MarketId.CN else 26
    )
    assert set(rules.dataframe.PriceLimitPolicy) == (
        {"DATED_LIMITS"} if market is MarketId.CN else {"EXPLICIT_UNBOUNDED"}
    )
    # A published preparation reads its immutable asset, not the mutable source file.
    (tmp_path / "actions.json").write_text("corrupted", encoding="utf-8")
    assert flows.fetch(requests[0], prepared=prepared.reference).ready
    assert not flows.prepare((requests[0],), policy=PreparePolicy.REFRESH).ready


@pytest.mark.parametrize("market", list(MarketId))
def test_only_complete_explicit_history_can_assert_empty_subrange(tmp_path, market):
    manifest, bindings, request, _, save = fixture(tmp_path, market, BarFrequency.DAILY)
    req = request(EquityProduct.ACTIONS, end=date(2026, 11, 5))
    fetch = bindings[req.parameters.provider_key].fetch
    frame, meta = fetch(req)
    assert frame.Kind.tolist() == ["NONE"] and meta["no_actions_verified"] is True
    manifest["instruments"][0]["actions"]["complete"] = False
    save()
    with pytest.raises(IncompleteDataError, match="complete economic-event"):
        fetch(req)


@pytest.mark.parametrize(
    "defect",
    [
        "hash",
        "traversal",
        "empty_receipt",
        "missing_payment",
        "naive_time",
        "rule_gap",
        "late_rule",
        "outside_coverage",
        "duplicate_instrument",
        "unknown_symbol",
    ],
)
def test_invalid_or_uncovered_facts_fail_explicitly(tmp_path, defect):
    manifest, bindings, request, asset, save = fixture(tmp_path, MarketId.US, BarFrequency.DAILY)
    item = manifest["instruments"][0]
    product = (
        EquityProduct.CONSTRAINTS if defect in ("rule_gap", "late_rule") else EquityProduct.ACTIONS
    )
    req = request(product)
    if defect == "hash":
        item["actions"]["data"]["sha256"] = "0" * 64
    elif defect == "traversal":
        item["actions"]["data"]["path"] = "../untrusted.json"
    elif defect == "empty_receipt":
        item["actions"]["evidence"] = asset("empty.json", "")
    elif defect in ("missing_payment", "naive_time"):
        rows = json.loads((tmp_path / "actions.json").read_text())
        rows[0]["PayAt" if defect == "missing_payment" else "AvailableDate"] = (
            None if defect == "missing_payment" else "2026-11-05"
        )
        item["actions"]["data"] = asset("actions.json", rows)
    elif defect in ("rule_gap", "late_rule"):
        rows = json.loads((tmp_path / "rules.json").read_text())
        if defect == "rule_gap":
            rows = rows[:-1]
        else:
            rows[0]["AvailableDate"] = "2026-11-05T23:00:00+00:00"
        item["constraints"]["daily"]["data"] = asset("rules.json", rows)
    elif defect == "outside_coverage":
        req = request(product, end=date(2026, 11, 9))
    elif defect == "duplicate_instrument":
        manifest["instruments"].append(item.copy())
    else:
        item["instrument"]["symbol"] = "MSFT"
    if defect == "empty_receipt":
        (tmp_path / "empty.json").write_bytes(b"")
        item["actions"]["evidence"]["sha256"] = sha256(b"").hexdigest()
    save()
    with pytest.raises((DataContractError, IncompleteDataError)):
        bindings[req.parameters.provider_key].fetch(req)


def test_verified_empty_events_and_market_source_boundaries(tmp_path):
    _, bindings, request, _, _ = fixture(tmp_path, MarketId.CN, BarFrequency.DAILY, no_events=True)
    req = request(EquityProduct.ACTIONS)
    fetch = bindings[req.parameters.provider_key].fetch
    assert fetch(req)[0].Kind.tolist() == ["NONE"]
    wrong = EquityDataRequest(
        req.parameters.instrument, SourceRef("other", "v1"), req.parameters.query
    )
    with pytest.raises(DataContractError, match="MISMATCH"):
        fetch(wrong)
