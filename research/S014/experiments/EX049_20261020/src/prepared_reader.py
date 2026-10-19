"""Authenticated prepared-only reader. No prepare, catalog, provider or exports."""
from datetime import datetime, time
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys
from uuid import UUID

from czsc_trader.application import create_research_context, RepositoryContext
from czsc_trader.research_tools import EvidenceRef, ResearchBatchRef
from dataflows import DataRequest, Dataset, PreparedDataRef, ProviderConfig
import pandas as pd
import requests
from strategy_runtime.pricing import ExecutionPricing
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

from local_cycle import CycleSeed, PreparedInputs

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "research/S014/experiments/EX046_20261020/src/strategy_runtime/strategies/completed_pause_review.py"
SOURCE_SHA = "5e775c5b27bfd7b1ac5bec9c2839ce24ae62f32f1829c21a13091868a174b846"


def deny_network(*args, **kwargs):
    raise RuntimeError("EX049 only authenticated prepared data, network forbidden")


def context():
    requests.sessions.Session.request = deny_network
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef("S014"),
                                   providers=ProviderConfig(bindings={}))


def read(path):
    return json.loads(path.read_bytes())


def published(identity):
    ref = EvidenceRef.from_dict(identity)
    data = ref.resolve(ROOT).read_bytes()
    if ref.experiment.strategy_id != "S014" or sha256(data).hexdigest() != ref.sha256:
        raise ValueError("Original immutable S014 identity required")
    return json.loads(data)


def original_source():
    if sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError("Original C9461 source changed")
    spec = importlib.util.spec_from_file_location("ex049_original_c9461", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def identities():
    receipt = read(ROOT / "research/S014/experiments/EX046_20261020/others/accounts/run-001.json")
    if receipt["evidence"]["sha256"] != "935b74f311a04b11e494d7adea80c7c9d1badb7776706e0761a77679dc8751e0":
        raise ValueError("Only original C9461 account")
    account = published(receipt["evidence"])
    if account["result_hash"] != "a3c398bd3f3259bbf8e46a6339a36a8bd83b2ccd924526240b0ca604b0f21bcb":
        raise ValueError("Original C9461 result mismatch")
    binding = published(receipt["binding_ref"])
    population_path = ROOT / "research/S014/materials/20261020_shock_state_diagnosis/accounting/original_shock_population_review.json"
    if sha256(population_path.read_bytes()).hexdigest() != "5ba29d8c5ca37324926c25d4c4b1eb7fbf6325219298719f4e3e84ab564a716a":
        raise ValueError("Original independently authenticated population changed")
    population = read(population_path)
    if receipt["binding_ref"] != population["binding_ref"] or receipt["evidence"] != population["source_account_ref"]:
        raise ValueError("Original independently authenticated binding differs")
    if binding["execution_fingerprint"] != account["request_identity"]["data_identity"]:
        raise ValueError("Original prepared execution identity mismatch")
    return receipt, account, binding


def prepared_ref(value):
    return PreparedDataRef(UUID(value["space_id"]), UUID(value["preparation_id"]), value["manifest_sha256"])


def fetch_one(ctx, query, prepared, expected=None):
    if "parameters" in query and query["parameters"]:
        raise ValueError("Unexpected parameterized original request")
    request = DataRequest(Dataset(query["dataset"]), query["symbol"], query["start"], query["end"],
                          query["required_cutoff"], query["frequency"])
    result = ctx.data.fetch(request, prepared=prepared)
    if not result.ready or (expected is not None and result.identity.content_sha256 != expected):
        raise ValueError("Original prepared request not ready or content identity mismatch")
    frame = result.dataframe.copy(deep=True)
    frame = frame.set_index(pd.DatetimeIndex(pd.to_datetime(frame.Date))).sort_index()
    if frame.index.has_duplicates:
        raise ValueError("Original unique session data required")
    return frame, result.identity.content_sha256


def fetch_inputs(account, binding):
    ctx = context()
    source_binding = binding["input_bindings"]["full"]
    source_prepared = prepared_ref(source_binding["prepared"])
    market, market_sha = fetch_one(ctx, source_binding["plan"]["requests"]["market"], source_prepared)
    source_frames = {}
    source_manifest = {"source_market": market_sha}
    for key in ("raw", "limits", "status"):
        source_frames[key], source_manifest["source_" + key] = fetch_one(
            ctx, source_binding["plan"]["requests"][key], source_prepared)
    execution_prepared = prepared_ref(binding["execution_prepared"])
    frames, manifest = {}, source_manifest
    for key in ("execution_daily", "adjusted_daily", "price_limits", "trading_status"):
        frames[key], manifest[key] = fetch_one(ctx, binding["execution_requests"][key], execution_prepared,
                                               binding["execution_identities"][key])
    rename = {"Date": "dt", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "vol"}
    raw, adj = [frames[k].reset_index(drop=True).rename(columns=rename) for k in ("execution_daily", "adjusted_daily")]
    pricing = account["request_identity"]["pricing"]
    if pricing["anchor_factor"] != 5.892 or pricing["basis"] != "HFQ_RESEARCH":
        raise ValueError("Original anchored HFQ pricing required")
    projected = ExecutionPricing.from_dict(pricing).apply(raw.copy(), raw_daily=raw, adjusted_daily=adj)
    projected = projected.rename(columns={v: k for k, v in rename.items()})
    projected = projected.set_index(pd.DatetimeIndex(pd.to_datetime(projected.Date))).sort_index()
    old = original_source()
    features = old.causal_features(market.reset_index(drop=True))
    features["support_floor"] = market.Close.where(market.index >= old.EVALUATION_START).shift(1).rolling(5, min_periods=5).min()
    decisions = account["runs"][0]["ledgers"]["decisions"]["data"]
    clock = {str(r["signal_date"])[:10]: str(r["valid_session"])[:10] for r in decisions}
    dates = tuple(str(r["date"])[:10] for r in account["runs"][0]["ledgers"]["account_daily"]["data"])
    if len(clock) != 1642 or len(dates) != 1642 or max(clock) != "2026-10-14" or dates[-1] != "2026-10-15":
        raise ValueError("Original full sourceD/executionE clock required")
    for D, E in clock.items():
        if D not in {"2019-12-31"} and pd.Timestamp(D) not in market.index:
            raise ValueError("Missing original source session")
        if pd.Timestamp(E) not in projected.index:
            raise ValueError("Missing original execution session")
    inputs = PreparedInputs(market, source_frames["raw"], source_frames["limits"], source_frames["status"],
                            features, projected, frames["execution_daily"], frames["price_limits"],
                            frames["trading_status"], clock, dates)
    return inputs, manifest


def seed_from_event(event, account, inputs):
    """Reauthenticate original BUY in runtime units, preserve literal ledger cost."""
    old = original_source()
    ledger = account["runs"][0]["ledgers"]
    entries = [r for r in ledger["fills"]["data"] if r["fill_id"] == event["actual_entry_fill_id"]]
    if len(entries) != 1 or entries[0]["side"] != "BUY":
        raise ValueError("Unique original actual BUY required")
    buy = entries[0]
    E, D = str(buy["fill_time"])[:10], str(buy["signal_date"])[:10]
    stamp, before = pd.Timestamp(E), pd.Timestamp(D)
    q = int(buy["quantity"])
    quote = inputs.source_market.loc[stamp]
    raw_E, raw_D = inputs.source_raw.loc[stamp], inputs.source_raw.loc[before]
    if inputs.source_status.loc[stamp, "Status"] != "TRADING":
        raise ValueError("Original source BUY requires actual trading session")
    before_source = inputs.source_market.loc[before]
    limit = old.buy_limit(float(raw_D.Close), float(before_source.Close / raw_D.Close))
    scale = float(quote.Close / raw_E.Close)
    b = inputs.source_limits.loc[stamp]
    fill = resolve_fill(OrderSpec("BUY", "LIMIT", 100, limit), session_open=float(quote.Open),
                        session_time=datetime.combine(stamp.date(), time(9, 30)), intraday_touches=(),
                        daily_quote=DailyQuote(float(quote.Low), float(quote.High)),
                        session_limits=SessionPriceLimits(stamp.date(), float(b.DownLimit * scale),
                                                         float(b.UpLimit * scale), float(.01 * scale)))
    original = next(r for r in ledger["decisions"]["data"] if str(r["signal_date"])[:10] == E)
    if not fill.filled or float(fill.price) != original["entry_fill_price"] or not original["buy_filled_today"]:
        raise ValueError("Original runtime BUY cost must replay exactly in original operation order")
    if q != int(float(event["actual_entry_quantity"])) or E != event["actual_entry_fill_E"]:
        raise ValueError("Frozen actual funded entry quantity/date differs")
    return CycleSeed(event["event_id"], event["cycle_id"], E, event["D"], int(float(event["entry_index"])),
                     int(float(event["deadline_index"])), int(float(event["reservation_index"])), q,
                     buy["price"], buy["fees"], float(fill.price))
