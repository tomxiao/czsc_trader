"""Compare frozen and proposed runtimes on explicit, authenticated market inputs.

No supplier access or synthetic features are used. The caller prepares a DFLS
reference first; every subsequent read is through public fetch/prepare APIs.
Each case writes a new result directory and never replaces earlier evidence.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import traceback
from uuid import UUID
from zoneinfo import ZoneInfo

import pandas as pd

from czsc_trader.application import RepositoryContext, validate_release_package
from czsc_trader.application.runtime_acceptance import prospective_release
from dataflows import (
    Dataflows, DataRequest, DataSpace, Dataset, EvidenceParameters,
    PreparedDataRef, ProviderConfig,
)
from strategy_manager import StrategyRegistry
from strategy_runtime import (
    ExecutionState, PortfolioSnapshot, RuntimeBinding, SignalHistoryMode,
    StrategyCandidate, StrategyInit, StrategyInputBinding, StrategyRuntime,
    TradableWindow, TradingPoint,
)
from trading_execution_engine import (
    HistoricalExecutor, MarketExecutionRules, SessionPriceLimits, SuspensionInformation,
)


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
IDENTITY_COLUMNS = frozenset(("decision_id", "order_id", "fill_id", "cycle_id"))
LEDGERS = ("decisions", "orders", "fills", "account_daily", "trades")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def plain(value):
    if is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID, Path)):
        return str(value)
    if hasattr(value, "item"):
        return plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite value cannot enter review JSON")
    return value


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(plain(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def managed(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Verification paths must stay within the repository")
    return path


def assert_frame_exact(left, right, *, name, maps=None):
    """Zero-tolerance business comparison with linked ID bijections only."""
    if set(left.columns) != set(right.columns) or len(left) != len(right):
        raise AssertionError(f"{name}: columns or row count differ")
    maps = {} if maps is None else maps
    for offset in range(len(left)):
        for column in left.columns:
            a, b = left.iloc[offset][column], right.iloc[offset][column]
            missing_a, missing_b = bool(pd.isna(a)), bool(pd.isna(b))
            if missing_a or missing_b:
                if missing_a != missing_b:
                    raise AssertionError(f"{name}[{offset}].{column}: missing value differs")
                continue
            if column in IDENTITY_COLUMNS:
                if not isinstance(a, str) or not isinstance(b, str):
                    raise AssertionError(f"{name}[{offset}].{column}: invalid identity")
                forward, reverse = maps.setdefault(column, ({}, {}))
                if forward.setdefault(a, b) != b or reverse.setdefault(b, a) != a:
                    raise AssertionError(f"{name}[{offset}].{column}: non-bijective linkage")
            elif a != b:
                raise AssertionError(f"{name}[{offset}].{column}: {a!r} != {b!r}")
    return {"name": name, "rows": len(left), "columns": len(left.columns),
            "comparison": "EXACT_VALUES_ZERO_TOLERANCE"}


def compare_ledgers(left, right):
    maps = {}
    checks = [assert_frame_exact(getattr(left, name), getattr(right, name),
                                 name=name, maps=maps) for name in LEDGERS]
    return {"checks": checks,
            "identity_bijections": {k: len(v[0]) for k, v in maps.items()}}


def comparable_requests(plan):
    requests = plan.to_dict()["requests"]
    for item in requests.values():
        if item["parameter_type"] == "EvidenceParameters":
            # Only the physical root is movable. Source path and source hash
            # remain strict selection fields, including for the S007 seed.
            item["parameters"]["repository_root"] = "<physical-evidence-root>"
    return requests


def compare_plans(left, right):
    old, new = plain(left), plain(right)
    for field in ("strategy", "signal_identity", "plan_identity"):
        old.pop(field)
        new.pop(field)
    if old != new:
        changed = [k for k in old if old[k] != new.get(k)]
        raise AssertionError(f"plan business fields differ: {changed}")


def fetch(flows, request, prepared):
    result = flows.fetch(request, prepared=prepared)
    if not result.ready:
        raise RuntimeError(f"Prepared input not READY: {request.dataset} {request.start}..{request.end}: {result}")
    return result


def plain_request(raw):
    raw = dict(raw)
    # The execution procurement boundary is raw ETF OHLCV only; strategy input
    # parameters are derived by each strategy's own public plan_inputs.
    kind = raw.pop("parameter_type", "NoParameters")
    parameters = raw.pop("parameters", {})
    if kind != "NoParameters" or parameters:
        raise ValueError("Raw execution requests require NoParameters")
    if raw.pop("coverage", None) is not None:
        raise ValueError("Declare execution coverage in the prepared request, not this raw reader")
    return DataRequest(**raw)


def execution_request(raw, *, name=None):
    request = plain_request(raw)
    if request.dataset not in {Dataset.ETF_UNADJUSTED_DAILY, Dataset.ETF_UNADJUSTED_INTRADAY}:
        raise ValueError("Frozen ETF verification requires raw ETF execution quotes")
    if name is not None:
        expected = {"daily": (Dataset.ETF_UNADJUSTED_DAILY, "daily"),
                    "intraday": (Dataset.ETF_UNADJUSTED_INTRADAY, "30m"),
                    "five_minute": (Dataset.ETF_UNADJUSTED_INTRADAY, "5m")}[name]
        if (request.dataset, request.frequency) != expected:
            raise ValueError(f"{name} requires {expected[0].value} {expected[1]} execution quotes")
    return request


def quotes(flows, raw, prepared):
    request = execution_request(raw)
    result = fetch(flows, request, prepared)
    frame = result.dataframe.copy(deep=True)
    frame.attrs = {}
    frame = frame.rename(columns={"Date": "dt", "Open": "open", "High": "high",
                                  "Low": "low", "Close": "close"})
    if not {"dt", "open", "high", "low", "close"}.issubset(frame):
        raise ValueError("Raw execution quote schema is incomplete")
    return frame, {"request": plain(request), "content_sha256": result.identity.content_sha256,
                   "rows": len(frame)}


def market_contract(case, instance, plan):
    if instance.execution_policy.policy_type == "INTRADAY_OVERLAY":
        return None, {"applied": False,
            "reason": "Existing TXE INTRADAY_OVERLAY contract does not support MarketExecutionRules; raw 5m checkpoints are used.",
            "scope_limit": "This is the unchanged overlay capability boundary, not price-limit-contract equivalence."}
    if "limits" not in case:
        raise ValueError("FROZEN_RULE real-market verification requires an explicit prepared limits binding")
    raw = case["limits"]
    values = raw["prepared"]
    prepared = PreparedDataRef(UUID(values["space_id"]), UUID(values["preparation_id"]), values["manifest_sha256"])
    flows = Dataflows(base_dir=ROOT, space=DataSpace(Path(raw["space"])),
                      providers=ProviderConfig(bindings={}))
    if flows.binding.space_id != prepared.space_id:
        raise ValueError("Limits preparation differs from selected DFLS space")
    request = plain_request(raw["request"])
    if request.dataset is not Dataset.SECURITY_PRICE_LIMITS or request.symbol != instance.identity.symbol:
        raise ValueError("Limits request must select this ETF's actual exchange price limits")
    result = fetch(flows, request, prepared)
    frame = result.dataframe.copy()
    frame["Date"] = pd.to_datetime(frame.Date)
    frame = frame.loc[frame.Date.dt.date.isin(plan.signal_dates)].sort_values("Date")
    if tuple(frame.Date.dt.date) != tuple(plan.signal_dates):
        raise ValueError("Actual price limits do not exactly cover execution sessions")
    rules = MarketExecutionRules(instance.identity.symbol,
        tuple(SessionPriceLimits(row.Date.date(), float(row.DownLimit), float(row.UpLimit), .001)
              for row in frame.itertuples()), (), SuspensionInformation.NOT_PROVIDED)
    return rules, {"applied": True, "prepared": raw["prepared"], "space": raw["space"],
                   "request": plain(request), "content_sha256": result.identity.content_sha256,
                   "fingerprint": rules.fingerprint, "contract": rules.to_dict()}


def public_instances(case, directory):
    repository = RepositoryContext.discover(ROOT)
    reference = case["reference"]
    family, version = reference.rsplit("-", 1)
    stored = StrategyRegistry(repository.strategy_root).get_version(family, version)
    _, runtime_binding, old_source = validate_release_package(repository, reference)
    candidate_raw = case["candidate"]
    payload_path = managed(candidate_raw["payload_path"])
    payload = read(payload_path)
    candidate = StrategyCandidate(family, candidate_raw["candidate_id"], payload,
                                  managed(candidate_raw["source_root"]))
    raw = case["prepared"]
    prepared = PreparedDataRef(UUID(raw["space_id"]), UUID(raw["preparation_id"]), raw["manifest_sha256"])
    flows = Dataflows(base_dir=ROOT, space=DataSpace(Path(case["space"])),
                      providers=ProviderConfig(bindings={}))
    if flows.binding.space_id != prepared.space_id:
        raise ValueError("Prepared reference differs from selected DFLS space")
    runtime = StrategyRuntime(repository.strategy_root, dataflows=flows)
    window = TradableWindow(date.fromisoformat(case["start"]), date.fromisoformat(case["end"]))
    # Runtime caches are task-temporary; review artifacts below contain only
    # selected bindings, real observations, ledgers and the actual conclusion.
    cache = ROOT / ".tmp/frozen-market-verification" / directory.name
    if cache.exists():
        raise FileExistsError(f"Runtime cache already exists: {cache.relative_to(ROOT)}")
    old = runtime.create(StrategyInit(prospective_release(stored), window, cache / "old",
                         source_root=old_source, runtime_binding=RuntimeBinding.from_dict(runtime_binding)))
    new = runtime.create(StrategyInit(candidate, window, cache / "new"))
    old_request, new_request = old.calendar_request(), new.calendar_request()
    if old_request != new_request:
        raise AssertionError("Old and new complete prerequisite calendar requests differ")
    calendar = fetch(flows, old_request, prepared)
    old_plan = old.plan_inputs(calendar)
    new_derived = new.plan_inputs(calendar)
    write_json(directory / "old_derived_plan.json", old_plan.to_dict())
    write_json(directory / "new_derived_plan.json", new_derived.to_dict())
    for field in ("tradable_window", "calendar_name", "calendar_sha256", "calendar_dates",
                  "signal_dates", "calculation_dates"):
        if getattr(old_plan, field) != getattr(new_derived, field):
            raise AssertionError(f"Derived input scope differs: {field}")
    if comparable_requests(old_plan) != comparable_requests(new_derived):
        raise AssertionError("Derived logical requests differ (source path/hash are strict)")
    requests = dict(new_derived.requests)
    for name, request in requests.items():
        if isinstance(request.parameters, EvidenceParameters):
            requests[name] = replace(request, parameters=replace(request.parameters,
                repository_root=old_plan.requests[name].parameters.repository_root))
    new_plan = replace(new_derived, requests=requests)
    for name, instance, plan in (("old", old, old_plan), ("new", new, new_plan)):
        binding = StrategyInputBinding(plan, prepared)
        instance.prepare_data(binding=binding)
        write_json(directory / f"{name}_binding.json", binding.to_dict())
    if old.execution_policy != new.execution_policy:
        raise AssertionError("Execution policy differs")
    if old.definition.capabilities != new.definition.capabilities:
        raise AssertionError("Execution capabilities differ")
    return old, new, old_plan, flows, prepared, {"payload_path": payload_path.relative_to(ROOT).as_posix(),
             "payload_sha256": digest(payload_path), "old_identity": plain(old.identity),
             "new_identity": plain(new.identity)}


def run_account(instance, plan, mode, execution, directory, side, market_rules):
    executor = HistoricalExecutor(
        strategy_reference=instance.identity.reference_id, symbol=instance.identity.symbol,
        execution_daily=execution["daily"], execution_intraday=execution["intraday"],
        execution_five_minute=execution.get("five_minute"),
        evaluation_start=pd.Timestamp(instance.tradable_window.start),
        evaluation_end=pd.Timestamp(instance.tradable_window.end), initial_cash=100000.,
        execution_policy=instance.execution_policy,
        order_types=instance.definition.capabilities.order_types,
        checkpoints=instance.definition.capabilities.checkpoints,
        market_rules=market_rules,
    )
    # Both modes use the same public plan_at and real TXE. CONTINUOUS differs
    # only in strategy-state replay scope, never in account initialization.
    for execution_date, signal_date in plan.signal_dates.items():
        point = TradingPoint(execution_date, datetime.combine(signal_date, time(20, 31), tzinfo=SHANGHAI))
        portfolio, state = executor.snapshot(point)
        actual_plan = instance.plan_at(point=point, portfolio=portfolio, state=state, history_mode=mode)
        outcome = executor.execute(actual_plan)
        if outcome.status.value != "SETTLED" or outcome.plan_identity != actual_plan.plan_identity:
            raise RuntimeError("Historical executor did not settle the exact plan")
    result = executor.finish()
    for name in LEDGERS:
        with (directory / f"{side}_{mode.value}_{name}.csv").open("x", encoding="utf-8", newline="") as stream:
            getattr(result, name).to_csv(stream, index=False)
    if result.account_daily.empty:
        raise AssertionError("Historical account has no covered sessions")
    if result.account_daily.cash_before.iloc[0] != 100000. or result.account_daily.quantity_before.iloc[0] != 0:
        raise AssertionError("Account did not initialize at 100000 and zero quantity")
    if result.account_daily.cash.lt(0).any() or result.account_daily.quantity.lt(0).any():
        raise AssertionError("Historical account has negative cash or quantity")
    if not result.fills.empty:
        if not result.fills.quantity.gt(0).all() or not result.fills.quantity.mod(100).eq(0).all():
            raise AssertionError("Executed quantities violate 100-share lots")
        settings = instance.execution_policy.settings
        rate = float(settings["one_way_cost"] if instance.execution_policy.policy_type == "INTRADAY_OVERLAY"
                     else settings["capital"]["fee_rate"])
        expected = result.fills.quantity * result.fills.price * rate
        if not all(math.isclose(actual, wanted, rel_tol=0, abs_tol=1e-12)
                   for actual, wanted in zip(result.fills.fees, expected, strict=True)):
            raise AssertionError("Executed fees differ from the actual strategy fee contract")
    return result


def selected_probe_points(history, plan):
    sessions = pd.DatetimeIndex(tuple(plan.signal_dates.values()))
    selected = history.loc[sessions]
    target = selected.target_position.astype(float)
    previous = target.shift(1, fill_value=0.)
    groups = {"ENTRY": target.gt(previous), "EXIT": target.lt(previous),
              "HOLD_POSITION": target.gt(0) & target.eq(previous),
              "HOLD_CASH": target.eq(0) & target.eq(previous)}
    chosen = {}
    reverse_dates = {pd.Timestamp(signal): trading for trading, signal in plan.signal_dates.items()}
    for label, mask in groups.items():
        if mask.any():
            signal = selected.index[mask][0]
            chosen[signal] = {"category": label, "trading_date": reverse_dates[signal]}
    return chosen, [name for name, mask in groups.items() if not mask.any()]


def probe_coverage(policy_type, successes, expected_core_rejections, point_count):
    if policy_type == "INTRADAY_OVERLAY":
        return successes[600] > 0 and expected_core_rejections == point_count and point_count > 0
    return all(successes.values())


def probe_plans(old, new, history, plan, mode, directory, execution_daily):
    chosen, absent = selected_probe_points(history, plan)
    cases = []
    failures = []
    successes = {600: 0, 200: 0}
    expected_core_rejections = 0
    overlay = old.execution_policy.policy_type == "INTRADAY_OVERLAY"
    for signal, selection in chosen.items():
        when = datetime.combine(signal.date(), time(20, 31), tzinfo=SHANGHAI)
        point = TradingPoint(selection["trading_date"], when)
        for quantity, cash in ((600, Decimal("12345.67")), (200, Decimal("99.50"))):
            # The same nonzero account snapshot goes through each complete
            # plan_at path. Actual account holdings need not match intent state.
            raw_close = execution_daily.loc[
                pd.to_datetime(execution_daily["dt"]).eq(signal), "close"]
            if len(raw_close) != 1:
                raise ValueError("Probe requires exactly one authenticated raw signal-session close")
            price = float(raw_close.iloc[0])
            portfolio = PortfolioSnapshot("market-probe", old.identity.symbol, cash,
                cash + Decimal(str(price)) * quantity, quantity, 7, when)
            state = ExecutionState(11, when, 600)
            outputs = []
            for instance in (old, new):
                try:
                    outputs.append(("PLAN", instance.plan_at(point=point, portfolio=portfolio,
                                    state=state, history_mode=mode)))
                except Exception as error:
                    message = str(error).replace(old.identity.reference_id, "<strategy>").replace(new.identity.reference_id, "<strategy>")
                    outputs.append(("ERROR", {"type": type(error).__name__, "message": message}))
            if outputs[0][0] != outputs[1][0]:
                status = "FAIL_PLAN_VS_REJECTION"
                failures.append(status)
            elif outputs[0][0] == "PLAN":
                try:
                    compare_plans(outputs[0][1], outputs[1][1])
                    successes[quantity] += 1
                    status = "EXACT_PUBLIC_PLAN"
                except AssertionError as error:
                    status = "FAIL_BUSINESS_PLAN_DIFFERENCE"
                    failures.append(str(error))
            else:
                if outputs[0][1] != outputs[1][1]:
                    status = "FAIL_DIFFERENT_REJECTIONS"
                    failures.append(status)
                else:
                    expected = {"type": "RuntimeContractError",
                                "message": "intraday overlay account differs from core quantity"}
                    if overlay and quantity == 200 and outputs[0][1] == expected:
                        status = "EXPECTED_INVALID_CORE_QUANTITY_BOUNDARY"
                        expected_core_rejections += 1
                    else:
                        status = "FAIL_UNEXPECTED_MATCHING_REJECTION"
                        failures.append({"signal_date": signal.date().isoformat(),
                                         "quantity": quantity, "error": outputs[0][1]})
            cases.append({"signal_date": signal.date(), "trading_date": selection["trading_date"],
                          "category": selection["category"], "quantity": quantity, "cash": cash,
                          "cycle_target": 600, "status": status,
                          "valuation": {"basis": "UNADJUSTED", "raw_signal_close": price},
                          "old": plain(outputs[0][1]), "new": plain(outputs[1][1])})
    result = {"cases": cases, "absent_market_categories": absent,
              "successful_nonzero_cases": successes,
              "expected_invalid_core_quantity_cases": expected_core_rejections,
              "failures": failures,
              "coverage_sufficient": probe_coverage(old.execution_policy.policy_type,
                  successes, expected_core_rejections, len(chosen))}
    write_json(directory / f"nonzero_plan_probes_{mode.value}.json", result)
    if failures:
        raise AssertionError(f"Nonzero account plan differences: {failures}")
    return {"cases": len(cases), "absent_market_categories": absent,
            "successful_nonzero_cases": successes,
            "expected_invalid_core_quantity_cases": expected_core_rejections,
            "coverage_sufficient": result["coverage_sufficient"]}


def verify(case, directory):
    old, new, plan, flows, prepared, identity = public_instances(case, directory)
    requests = case["execution_requests"]
    if set(requests) - {"daily", "intraday", "five_minute"} or not {"daily", "intraday"} <= set(requests):
        raise ValueError("execution_requests require daily and intraday; S003 additionally five_minute")
    if old.execution_policy.policy_type == "INTRADAY_OVERLAY" and "five_minute" not in requests:
        raise ValueError("Intraday overlay verification requires raw 5m execution inputs")
    execution, execution_identities = {}, {}
    for name, request in requests.items():
        execution_request(request, name=name)
        execution[name], execution_identities[name] = quotes(flows, request, prepared)
    write_json(directory / "execution_inputs.json", execution_identities)
    rules, rules_evidence = market_contract(case, old, plan)
    write_json(directory / "market_rules.json", rules_evidence)
    modes = {}
    for mode in (SignalHistoryMode.WINDOW, SignalHistoryMode.CONTINUOUS):
        record = {"status": "FAIL"}
        modes[mode.value] = record
        try:
            dates = tuple(plan.signal_dates.values()) if mode is SignalHistoryMode.WINDOW else plan.calculation_dates
            sessions = pd.DatetimeIndex(dates)
            histories = [instance.inspect_signals(history_mode=mode) for instance in (old, new)]
            for side, history in zip(("old", "new"), histories, strict=True):
                with (directory / f"{side}_{mode.value}_signals_full.csv").open("x", encoding="utf-8", newline="") as stream:
                    history.to_csv(stream, index=True, index_label="signal_date")
            record["extra_history_rows"] = {side: len(history.index.difference(sessions))
                for side, history in zip(("old", "new"), histories, strict=True)}
            selected = [history.loc[sessions].rename_axis("signal_date").reset_index() for history in histories]
            record["signals"] = assert_frame_exact(selected[0], selected[1], name=f"{mode.value}.signals")
            results = [run_account(instance, plan, mode, execution, directory, side, rules)
                for side, instance in (("old", old), ("new", new))]
            record["ledgers"] = compare_ledgers(*results)
            record["actual_fills"] = {side: len(result.fills)
                for side, result in zip(("old", "new"), results, strict=True)}
            record["trade_rows"] = {side: len(result.trades)
                for side, result in zip(("old", "new"), results, strict=True)}
            record["closed_trades"] = {side: int(result.trades.status.eq("CLOSED").sum())
                for side, result in zip(("old", "new"), results, strict=True)}
            record["nonzero_plans"] = probe_plans(old, new, histories[0], plan, mode,
                                                  directory, execution["daily"])
            sufficient = all(record["actual_fills"].values()) and record["nonzero_plans"]["coverage_sufficient"]
            record["status"] = "PASS" if sufficient else "COVERAGE_INSUFFICIENT"
        except Exception as error:
            record["error"] = {"type": type(error).__name__, "message": str(error).replace(str(ROOT), ".")}
    statuses = [value["status"] for value in modes.values()]
    return {"status": "FAIL" if "FAIL" in statuses else "COVERAGE_INSUFFICIENT" if "COVERAGE_INSUFFICIENT" in statuses else "PASS",
            "reference": case["reference"], "case_id": case.get("case_id", case["reference"]),
            "identity": identity, "window": {"start": case["start"], "end": case["end"]},
            "initial_cash": 100000., "initial_quantity": 0, "modes": modes,
            "scope": "REAL_AUTHENTICATED_MARKET_PUBLIC_SRT_PLAN_AT_AND_TXE",
            "limits": ["Migration equivalence on declared market windows, not an unseen alpha holdout or production activation.",
                       "Market-intent decision semantics only; no claim of confirmed-fill-dependent strategy support."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Prepared real-market case configuration JSON")
    parser.add_argument("reference", help="Exactly one frozen reference, for example S001-v1")
    parser.add_argument("--case-id", help="Select one case when the same reference has multiple windows")
    args = parser.parse_args()
    config = read(args.config)
    cases = [case for case in config["cases"] if case["reference"] == args.reference
             and (args.case_id is None or case.get("case_id", case["reference"]) == args.case_id)]
    if len(cases) != 1:
        parser.error("Select exactly one case; use --case-id for repeated references")
    case = cases[0]
    case_id = case.get("case_id", case["reference"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", case_id):
        parser.error("case_id must be one safe directory name")
    directory = EX / "others/market_equivalence" / case_id
    directory.mkdir(parents=True, exist_ok=False)
    try:
        result = verify(case, directory)
    except Exception as error:
        result = {"status": "FAIL", "reference": args.reference, "case_id": case_id,
                  "error": {"type": type(error).__name__, "message": str(error).replace(str(ROOT), "."),
                            "traceback": traceback.format_exc().replace(str(ROOT), ".")}}
    result["config_sha256"] = digest(args.config)
    result["driver_sha256"] = digest(Path(__file__))
    result["artifacts"] = [{"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
                           for path in sorted(directory.iterdir()) if path.is_file()]
    write_json(directory / "result.json", result)
    print(json.dumps({"status": result["status"], "result": (directory / "result.json").relative_to(ROOT).as_posix()}))
    return 0 if result["status"] == "PASS" else 2 if result["status"] == "COVERAGE_INSUFFICIENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
