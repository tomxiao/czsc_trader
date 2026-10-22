"""Authenticate explicit technical inputs and copy them through the DFLS API."""
from pathlib import Path
from dataclasses import replace
import pandas as pd
from dataflows import Dataflows, DataSpace, ProviderConfig, ProviderBinding, PreparePolicy, PrepareStatus, Dataset
from strategy_runtime.input_binding import _request_dict
from strategy_runtime import canonical_sha256
from paper_trading_engine.inspection import InspectionInputCopy, InputContentIdentity
from ..backtesting.execution_data import _execution_frames, _market_execution_rules, _require_market_rules


def portable_value(value):
    """Normalize only the physical root in a typed evidence request descriptor."""
    if isinstance(value, dict):
        result = {key: portable_value(item) for key, item in value.items()}
        if (value.get("parameter_type") == "EvidenceParameters"
                and set(value) == {"dataset", "symbol", "start", "end", "required_cutoff", "frequency", "parameters", "parameter_type", "coverage"}
                and isinstance(value.get("parameters"), dict)
                and set(value["parameters"]) == {"repository_root", "source_path", "source_sha256"}):
            result["parameters"]["repository_root"] = "$REPOSITORY"
        return result
    if isinstance(value, (tuple, list)):
        return [portable_value(item) for item in value]
    return value


def portable_binding_dict(binding):
    return portable_value(binding.to_dict())


def prepared_dict(ref):
    return {"space_id": str(ref.space_id), "preparation_id": str(ref.preparation_id),
            "manifest_sha256": ref.manifest_sha256}


def replay_identity(replay):
    data = replay.execution_data
    return {"coordinate": replay.coordinate.to_dict(), "input_binding": portable_binding_dict(replay.input_binding),
            "execution": {"symbol": data.symbol, "asset_type": data.asset_type,
                "prepared": None if data.prepared is None else prepared_dict(data.prepared),
                "requests": {k: portable_value(_request_dict(v)) for k, v in sorted(data.requests.items())},
                "input_identities": dict(data.input_identities), "fingerprint": data.fingerprint,
                "cutoff": data.cutoff.isoformat(), "sessions": [x.isoformat() for x in data.evaluation_sessions],
                "pricing": data.pricing.to_dict(),
                "market_rules": None if data.market_rules is None else data.market_rules.to_dict()},
            "initial_cash": float(replay.initial_cash), "one_way_cost": float(replay.one_way_cost),
            "baseline": None if replay.baseline is None else replay.baseline.to_dict()}


def authenticate_execution(flows, replay, cutoff):
    data = replay.execution_data
    if data.prepared is None or not data.requests or not data.input_identities:
        raise ValueError("execution data must bind complete DFLS prepared inputs")
    if data.cutoff > cutoff or replay.input_binding.plan.tradable_window.end > cutoff:
        raise ValueError("technical input exceeds selection cutoff")
    window = replay.input_binding.plan.tradable_window
    if data.symbol != replay.input_binding.plan.strategy.symbol:
        raise ValueError("execution symbol differs from strategy input binding")
    if (data.evaluation_sessions.empty or data.evaluation_sessions.has_duplicates
            or not data.evaluation_sessions.is_monotonic_increasing
            or data.cutoff != data.evaluation_end.date()
            or window.start != data.evaluation_start.date() or window.end != data.evaluation_end.date()):
        raise ValueError("execution calendar must exactly match declared strategy window")
    etf = data.asset_type == "etf"
    expected = {
        "trading_calendar": (Dataset.TRADING_CALENDAR, "daily"),
        "price_limits": (Dataset.SECURITY_PRICE_LIMITS, "daily"),
        "adjusted_daily": (Dataset.ETF_OHLCV if etf else Dataset.STOCK_OHLCV, "daily"),
        "execution_daily": (Dataset.ETF_UNADJUSTED_DAILY if etf else Dataset.STOCK_UNADJUSTED_DAILY, "daily"),
        "execution_30m": (Dataset.ETF_UNADJUSTED_INTRADAY if etf else Dataset.STOCK_UNADJUSTED_INTRADAY, "30m"),
        "execution_5m": (Dataset.ETF_UNADJUSTED_INTRADAY if etf else Dataset.STOCK_UNADJUSTED_INTRADAY, "5m"),
        "trading_status": (Dataset.SECURITY_TRADING_STATUS, "daily"),
    }
    required = {"trading_calendar", "price_limits", "adjusted_daily", "execution_daily"}
    if not etf:
        required.add("trading_status")
    if not required <= set(data.requests) or not set(data.requests) <= set(expected):
        raise ValueError("execution input roles are incomplete or unknown")
    for role, request in data.requests.items():
        dataset, frequency = expected[role]
        symbol = ({"SH": "SSE", "SZ": "SZSE"}[data.symbol.rsplit(".", 1)[-1]]
                  if role == "trading_calendar" else data.symbol)
        if (request.dataset != dataset or request.frequency != frequency or request.symbol != symbol
                or pd.Timestamp(request.end).date() > cutoff
                or pd.Timestamp(request.required_cutoff).date() > cutoff):
            raise ValueError(f"execution request differs from declared role: {role}")
    results = {name: flows.fetch(req, prepared=data.prepared) for name, req in data.requests.items()}
    if any(not x.ready for x in results.values()):
        raise ValueError("prepared execution input unavailable")
    identities = {name: result.identity.content_sha256 for name, result in results.items()}
    if identities != data.input_identities:
        raise ValueError("execution input content identity differs")
    frames = _execution_frames(results, data.pricing)
    frames["adjusted_daily"].insert(1, "symbol", data.symbol)
    for name in ("adjusted_daily", "execution_daily", "execution_intraday", "execution_five_minute", "raw_execution_daily"):
        actual, expected = getattr(data, name), frames.get(name)
        if actual is None or expected is None:
            if actual is not expected:
                raise ValueError(f"execution frame presence differs: {name}")
        else:
            pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    rules = _market_execution_rules(results, data.pricing, data.symbol, data.market_security)
    _require_market_rules(data)
    if rules != data.market_rules:
        raise ValueError("execution market rules differ from DFLS inputs")
    calendar = results["trading_calendar"].dataframe
    sessions = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.IsOpen.eq(1), "Date"]))
    if not sessions.equals(data.evaluation_sessions):
        raise ValueError("execution calendar differs from DFLS inputs")
    fingerprint = canonical_sha256({"symbol": data.symbol, "asset_type": data.asset_type,
        "evaluation_start": data.evaluation_start.date().isoformat(),
        "evaluation_end": data.evaluation_end.date().isoformat(), "inputs": identities,
        "pricing": data.pricing.to_dict(), "market_rules": rules.to_dict()})
    if data.fingerprint != fingerprint:
        raise ValueError("execution fingerprint differs")
    window = replay.input_binding.plan.tradable_window
    if window.start < data.evaluation_start.date() or window.end > data.evaluation_end.date():
        raise ValueError("strategy window exceeds execution calendar")
    plan = replay.input_binding.plan
    if plan.available_through > cutoff:
        raise ValueError("strategy calculation input exceeds selection cutoff")
    strategy_results = {}
    for role, request in plan.requests.items():
        # Published trading calendars describe structural future sessions; they
        # are not future economic observations. Signal/calculation dates remain
        # bounded above and every market/feature observation is bounded below.
        calendar_request = request.dataset is Dataset.TRADING_CALENDAR
        if not calendar_request and pd.Timestamp(request.required_cutoff).date() > cutoff:
            raise ValueError(f"strategy request exceeds selection cutoff: {role}")
        item = flows.fetch(request, prepared=replay.input_binding.prepared)
        if not item.ready or item.identity is None:
            raise ValueError(f"prepared strategy input unavailable: {role}")
        if not calendar_request and pd.Timestamp(item.identity.data_cutoff).date() > cutoff:
            raise ValueError(f"prepared strategy data exceeds selection cutoff: {role}")
        strategy_results[role] = item
    if strategy_results[plan.calendar_name].identity.content_sha256 != plan.calendar_sha256:
        raise ValueError("strategy calendar content identity differs")
    def origins(items):
        return {k: {"sha256": v.identity.content_sha256, "source": v.identity.source,
                    "data_start": v.identity.data_start, "data_cutoff": v.identity.data_cutoff,
                    "metadata": dict(v.identity.metadata)} for k, v in items.items()}
    return {"execution_prepared": prepared_dict(data.prepared), "execution": origins(results),
            "strategy_prepared": prepared_dict(replay.input_binding.prepared), "strategy": origins(strategy_results)}


def _provider_request_key(request):
    # DFLS prepares source selections without admission-only coverage/cutoff.
    # Dates, dataset, frequency, symbol and typed selector parameters stay exact.
    return canonical_sha256(_request_dict(replace(request, required_cutoff=None, coverage=None)))


def copy_pte_inputs(flows, protocol, workspace, tick):
    """Republish authenticated frames; never copy DFLS UUID/store internals."""
    groups = {}
    for scenario in protocol.scenarios:
        for step in scenario.decisions:
            source = step.binding.prepared
            roles = groups.setdefault(source, {})
            for role, request in step.binding.plan.requests.items():
                key = canonical_sha256(_request_dict(request))
                roles[key] = request
    spaces, copies = [], []
    for index, (source, requests) in enumerate(groups.items()):
        tick()
        original = {}
        for key, request in requests.items():
            result = flows.fetch(request, prepared=source)
            if not result.ready:
                raise ValueError("PTE source input unavailable")
            original[key] = result
        source_selections = {}
        for key, request in requests.items():
            selection = _provider_request_key(request)
            result = original[key]
            if selection in source_selections and source_selections[selection].identity.content_sha256 != result.identity.content_sha256:
                raise ValueError("one source selection binds conflicting prepared contents")
            source_selections[selection] = result
        def fetch(request):
            selection = _provider_request_key(request)
            if selection not in source_selections:
                raise ValueError("DFLS requested an undeclared source selection")
            result = source_selections[selection]
            return result.dataframe.copy(deep=True), dict(result.identity.metadata)
        bindings = {r.dataset: ProviderBinding("inspection-input-copy", "1", fetch) for r in requests.values()}
        target = Dataflows(base_dir=workspace, space=DataSpace(Path(f"inputs/{index}/data")),
                          providers=ProviderConfig(bindings=bindings))
        prepared = target.prepare(tuple(requests.values()), policy=PreparePolicy.REFRESH)
        if prepared.status is not PrepareStatus.READY:
            raise ValueError(f"isolated DFLS preparation failed: {prepared.items}")
        content = []
        for key, request in requests.items():
            result = target.fetch(request, prepared=prepared.reference)
            if not result.ready:
                raise ValueError("isolated input unavailable")
            content.append(InputContentIdentity(key, original[key].identity.content_sha256, result.identity.content_sha256))
        copies.append(InspectionInputCopy(source, prepared.reference, tuple(content)))
        spaces.append(target.binding)
    return tuple(spaces), tuple(copies)
