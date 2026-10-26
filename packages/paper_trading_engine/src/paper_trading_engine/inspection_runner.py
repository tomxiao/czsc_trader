"""Bounded isolated workers exercising normal PTE decision, order and ledger code."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from dataflows import Dataflows, ProviderConfig, PreparedDataRef, Dataset
from strategy_runtime import (StrategyRuntime, StrategyInputBinding, PlannedOrder, OrderSide,
                              OrderType, canonical_sha256)
from strategy_runtime.input_binding import _request_dict
from strategy_runtime.inspection import (InspectionControl, InspectionProgress, InspectionStage,
    InspectionRuntimePermit, collect_inspection_environment)
from strategy_runtime.deployment import validate_release_package, load_inspection_deployment

from .inspection_contracts import (
    PteSubmissionResult, PteOrderUpdate, PteRepeatedOrderReport, PteDecisionInput,
    PteFault, PteInspectionCapability, PteOrderKey, SubmissionOutcome,
    InspectionOrderStatus, PteReleaseInspectionRequest, PteInspectionOutcome,
    PteInspectionStatus, PteScenarioResult, PteArtifact, CoverageRequirement,
    PteCoverageResult, encode,
)
from .lifecycle import AccountHealth
from .inspection_broker import RecordedFillBroker, money
from .account_data_preparer import AccountDataPreparer
from .account_engine import AccountEngine
from .account_strategy_cycle import AccountStrategyCycle
from .broker import BrokerSubmissionUncertainError, TERMINAL_INTENT_STATUSES
from .futu_execution import FutuExecution, OrderSubmissionBatchError
from .srt_advice_client import SrtAdviceClient
from .store import PaperStore

_PROGRESS_INTERVAL_SECONDS = 25


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encode(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _permit(request):
    return InspectionRuntimePermit(request.run_id, request.expected_release_id,
        request.expected_release_sha256, request.expected_package_sha256,
        canonical_sha256(request.protocol.to_dict()), request.isolated_repository, request.workspace)


def _inputs(request, permit, selected_scenario=None):
    spaces = {}
    for binding in request.data_spaces:
        permit.validate_path(binding.base_dir)
        permit.validate_path(binding.base_dir / binding.space.path)
        flows = Dataflows(base_dir=binding.base_dir, space=binding.space, providers=ProviderConfig(bindings={}))
        if flows.binding != binding or binding.space_id in spaces:
            raise ValueError("private DFLS space identity is missing or duplicated")
        spaces[binding.space_id] = flows
    copies = {x.source: x for x in request.input_copies}
    if len(copies) != len(request.input_copies):
        raise ValueError("duplicate source preparation mapping")
    bound = {}
    for scenario in request.protocol.scenarios:
        if selected_scenario is not None and scenario.scenario_id != selected_scenario:
            continue
        for step in scenario.decisions:
            mapping = copies.get(step.binding.prepared)
            if mapping is None or mapping.isolated.space_id not in spaces:
                raise ValueError("PTE input has no explicit isolated preparation mapping")
            flow = spaces[mapping.isolated.space_id]
            identities = {x.role: x for x in mapping.content_mapping}
            for role, req in step.binding.plan.requests.items():
                key = canonical_sha256(_request_dict(req))
                result = flow.fetch(req, prepared=mapping.isolated)
                identity = identities.get(key)
                if not result.ready or identity is None or result.identity.content_sha256 != identity.isolated_sha256:
                    raise ValueError(f"isolated input content differs or is unavailable: {role}")
            bound[(scenario.scenario_id, step.step_id)] = (flow, StrategyInputBinding(step.binding.plan, mapping.isolated))
    return bound


def _event_schedule(scenario):
    events = []
    for index, step in enumerate(scenario.decisions):
        events.append((step.decision_at, 0, index, step.step_id + ":decision", step))
        if step.repeat_decision:
            events.append((step.decision_at, 1, index, step.step_id + ":repeat", step))
        events.append((step.submit_at, 2, index, step.step_id + ":submit", step))
    for index, event in enumerate(scenario.channel_events):
        if not isinstance(event, PteSubmissionResult):
            events.append((event.observed_at, 3 if isinstance(event, PteOrderUpdate) else 4,
                           index, event.event_id, event))
    ordered = sorted(events)
    # Input ordering is not an implicit clock tie-breaker for unrelated actions.
    for left, right in zip(ordered, ordered[1:]):
        if left[0] == right[0] and left[1] == right[1]:
            raise ValueError("ambiguous simultaneous inspection events")
    return ordered


def _orders(payload):
    return tuple(PlannedOrder(OrderSide(x["side"]), int(x["quantity"]), OrderType(x["order_type"]),
                              money(x["limit_price"])) for x in (payload or {}).get("orders", []))


def _snapshot(store, account_id, broker):
    account = store.virtual_account(account_id)
    payload = json.loads(account["last_decision_payload"]) if account.get("last_decision_payload") else {}
    intents = store.account_intents(account_id)
    return {
        "position_quantity": int(account["quantity"]),
        "available_cash": str(money(account["cash"])),
        "frozen_cash": str(money(account["frozen_cash"])),
        "cycle_target_quantity": account.get("cycle_target"),
        "entry_cycle": None if account.get("entry_cycle_json") is None else json.loads(account["entry_cycle_json"]),
        "target_quantity": payload.get("target_quantity"),
        "health": str(account["health"]),
        "cumulative_order_count": len(broker.called),
        "expected_orders": encode(_orders(payload)),
        "decision_count": len(store.account_decisions(account_id)),
        "fills": [{key: row[key] for key in ("side", "quantity", "price", "fee")} for row in store.account_fills(account_id)],
        "intents": [{"side": x["side"], "quantity": int(x["quantity"]), "price": str(money(x["limit_price"])),
                     "status": x["status"]} for x in intents],
        "pending": sum(x["status"] not in TERMINAL_INTENT_STATUSES for x in intents),
        "channel": encode(broker.snapshot()),
    }


def _comparison_snapshot(snapshot):
    value = dict(snapshot)
    # Broker identifiers/timestamps and account runtime identifiers are not
    # economic facts. All order direction, quantity, status and fills remain.
    channel = dict(value["channel"])
    channel["orders"] = [{k: v for k, v in row.items() if k not in {"channel_order_id", "remark", "created_at", "updated_at"}}
                         for row in channel["orders"]]
    value["channel"] = channel
    return value


def _assert_checkpoint(expected, actual):
    for name in ("position_quantity", "available_cash", "frozen_cash", "cycle_target_quantity", "health", "cumulative_order_count"):
        value = getattr(expected, name)
        if isinstance(value, Decimal):
            value = str(money(value))
        elif isinstance(value, AccountHealth):
            value = value.value
        if actual[name] != value:
            raise AssertionError(f"{expected.checkpoint_id}.{name}: expected {value!r}, observed {actual[name]!r}")
    normalized = tuple(replace(order, limit_price=None if order.limit_price is None else money(order.limit_price)) for order in expected.expected_orders)
    if actual["expected_orders"] != encode(normalized):
        raise AssertionError(f"{expected.checkpoint_id}.expected_orders differs")


def _mark_price(flow, binding, moment):
    import pandas as pd
    for req in binding.plan.requests.values():
        if req.dataset is not Dataset.ETF_UNADJUSTED_DAILY:
            continue
        result = flow.fetch(req, prepared=binding.prepared)
        if not result.ready:
            raise ValueError("inspection pricing input unavailable")
        frame = result.dataframe
        # Closing price from the preceding session is causal at both the
        # after-close decision and next-session submission points.
        eligible = frame.loc[pd.to_datetime(frame["Date"]).dt.date <= binding.plan.available_through]
        if eligible.empty:
            raise ValueError("inspection has no causal valuation price")
        return Decimal(str(eligible.iloc[-1]["Close"]))
    raise ValueError("inspection requires declared unadjusted ETF prices")


def _run_scenario(request, scenario, directory, *, restart=True, fault=None):
    permit = _permit(request)
    directory = permit.validate_path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    trace_path = directory / "trace.jsonl"
    trace = []
    covered = set()
    result_code = "OK"
    store = None
    execution = accounts = advice = cycle = None
    clock = [scenario.decisions[0].decision_at]
    broker = RecordedFillBroker(scenario.initial_cash, scenario.decisions[0].binding.plan.strategy.symbol,
        [x for x in scenario.channel_events if isinstance(x, PteSubmissionResult)],
        [x for x in scenario.channel_events if isinstance(x, PteOrderUpdate)], lambda: clock[0])
    all_inputs = _inputs(request, permit, scenario.scenario_id)
    current_flow, current_binding = all_inputs[(scenario.scenario_id, scenario.decisions[0].step_id)]
    loaded = False
    restarted = False
    restart_qualified = False
    holdings_at_decision = []
    target_values = []
    checkpoints = {event: [x for x in scenario.checkpoints if x.after_event_id == event]
                   for event in {x.after_event_id for x in scenario.checkpoints}}
    fault_seen = False

    def open_components():
        nonlocal store, execution, accounts, advice, cycle
        store = PaperStore(directory / "runtime.db", inspection_permit=permit)
        advice = SrtAdviceClient(repo_root=request.isolated_repository, data_dir=directory / "account-data",
            dataflows=current_flow, now=lambda: clock[0], inspection_permit=permit,
            inspection_bindings=(current_binding,),
            session_resolver=lambda signal_date: next((x.trading_date for x in scenario.decisions
                                                      if x.binding.plan.available_through == signal_date), None))
        accounts = AccountEngine(store, advice, now=lambda: clock[0])
        execution = FutuExecution(store, broker, now=lambda: clock[0])
        cycle = AccountStrategyCycle(accounts, AccountDataPreparer(advice=advice), store)

    def close_components():
        if accounts is not None:
            accounts.begin_shutdown()
        if execution is not None:
            execution.begin_shutdown()
        if store is not None:
            store.close()

    def completed(event_id):
        nonlocal restarted, restart_qualified
        snapshot = _snapshot(store, account_id, broker)
        for expected in checkpoints.get(event_id, ()):
            _assert_checkpoint(expected, snapshot)
        row = {"event_id": event_id, "observed_at": clock[0].isoformat(), "snapshot": snapshot}
        trace.append(row)
        with trace_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(encode(row), ensure_ascii=False, sort_keys=True) + "\n")
            out.flush()
        if restart and event_id in scenario.restart_after:
            qualified = snapshot["position_quantity"] > 0 or snapshot["pending"] > 0
            close_components()
            open_components()
            # Restoration reads the persisted current binding and real account
            # state; the external channel retains its independent order facts.
            restored = _snapshot(store, account_id, broker)
            if _comparison_snapshot(restored) != _comparison_snapshot(snapshot):
                raise AssertionError("restart changed persisted account facts")
            restarted = True
            restart_qualified |= qualified

    account_id = "inspection-account"
    try:
        load_inspection_deployment(request.isolated_repository / "strategies", request.expected_release_id, permit)
        runtime = StrategyRuntime(request.isolated_repository / "strategies", inspection_permit=permit)
        release = validate_release_package(request.isolated_repository / "strategies", request.expected_release_id).release
        definition = runtime.describe(release)
        open_components()
        binding = advice.validate_account_binding(strategy_id=release.strategy_family_id, strategy_version=release.version,
                                                   symbol=broker.symbol, asset="etf")
        store.set_setting("futu_capital_pool", str(scenario.initial_cash))
        store.create_channel_reconciliation_account()
        store.create_virtual_account(account_id, "Isolated technical inspection", release.release_id,
            release.release_hash, scenario.initial_cash, symbol=broker.symbol, strategy_id=release.strategy_family_id,
            strategy_version=release.version, release_hash=release.release_hash,
            strategy_name_snapshot=binding.name, qualification_snapshot="INSPECTION",
            selection_data_cutoff=binding.selection_data_cutoff.isoformat())
        store.set_virtual_paused(account_id, False)
        store.set_paused(False)
        broker.price = _mark_price(current_flow, current_binding, clock[0])
        execution.refresh_account()
        execution.refresh_orders()
        loaded = True
        completed("LOAD")
        for moment, priority, index, event_id, item in _event_schedule(scenario):
            clock[0] = moment
            before = _snapshot(store, account_id, broker)
            if isinstance(item, PteDecisionInput):
                current_flow, current_binding = all_inputs[(scenario.scenario_id, item.step_id)]
                advice.dataflows = current_flow
                advice.inspection_bindings = (current_binding,)
                broker.price = _mark_price(current_flow, current_binding, clock[0])
                if event_id.endswith((":decision", ":repeat")):
                    if fault is not None and fault.at_event_id == event_id:
                        fault_seen = True
                        if fault.fault is PteFault.INPUT_UNAVAILABLE:
                            ref = current_binding.prepared
                            missing = PreparedDataRef(ref.space_id, uuid4(), ref.manifest_sha256)
                            advice.inspection_bindings = (replace(current_binding, prepared=missing),)
                        elif fault.fault is PteFault.INPUT_AFTER_DECISION:
                            clock[0] = datetime.combine(current_binding.plan.available_through - timedelta(days=1),
                                                       clock[0].timetz())
                    try:
                        cycle.run(account_id, signal_date=current_binding.plan.available_through, observed_at=clock[0])
                    except Exception as exc:
                        if fault_seen:
                            unchanged = len(broker.called) == before["cumulative_order_count"]
                            if not unchanged:
                                raise AssertionError("input rejection submitted an order") from exc
                            # Require the expected origin of rejection, rather
                            # than treating any unrelated exception as success.
                            chain = []
                            current = exc
                            while current is not None and current not in chain:
                                chain.append(current)
                                current = current.__cause__
                            from .errors import AdviceClientError
                            from strategy_runtime.errors import RuntimeContractError
                            valid_rejection = (
                                any(isinstance(error, AdviceClientError) and str(error) == "inspection calendar input unavailable" for error in chain)
                                if fault.fault is PteFault.INPUT_UNAVAILABLE else
                                any(isinstance(error, RuntimeContractError) and str(error) == "calculation time precedes the signal-session close" for error in chain)
                            )
                            if not valid_rejection:
                                raise
                            result_code = fault.fault.value
                            trace.append({"event_id": event_id, "expected_rejection": result_code,
                                          "actual_error": str(exc), "new_order_count": 0})
                            return {"status": "PASS", "code": result_code, "trace": trace,
                                    "summary": "declared input fault rejected at its decision boundary without new orders",
                                    "capabilities": [PteInspectionCapability.RELEVANT_FAILURE.value]}
                        raise
                    if fault_seen:
                        raise AssertionError("declared input fault did not reject")
                    payload = json.loads(store.virtual_account(account_id)["last_decision_payload"])
                    intents = [x for x in store.account_intents(account_id) if x["decision_id"] == payload["decision_id"]]
                    # The persisted business order sequence owns the mapping;
                    # neither UUID sorting nor channel timing selects orders.
                    intents.sort(key=lambda x: int(x["order_sequence"]))
                    broker.bind_intents({x["intent_id"]: PteOrderKey(item.step_id, ordinal) for ordinal, x in enumerate(intents)})
                    if event_id.endswith(":repeat"):
                        after = _snapshot(store, account_id, broker)
                        if _comparison_snapshot(before) != _comparison_snapshot(after):
                            raise AssertionError("repeat decision changed account or order facts")
                        if checkpoints.get(event_id):
                            covered.add(PteInspectionCapability.IDEMPOTENCE.value)
                    else:
                        holdings_at_decision.append(before["position_quantity"])
                        target_values.append(payload.get("target_quantity"))
                        if checkpoints.get(event_id):
                            covered.add(PteInspectionCapability.LOAD_PREPARE.value)
                else:
                    declared = [x for x in scenario.channel_events if isinstance(x, PteSubmissionResult)
                                and x.order.decision_step_id == item.step_id]
                    try:
                        execution.refresh_account()
                        execution.submit_pending()
                        # A synchronous MARKET fill is already a channel fact;
                        # normal reconciliation records it before submit ends.
                        execution.refresh_account()
                        execution.refresh_orders()
                    except BrokerSubmissionUncertainError:
                        if not any(x.outcome is SubmissionOutcome.UNKNOWN for x in declared):
                            raise
                        after = _snapshot(store, account_id, broker)
                        if after["health"] != "BLOCKED" or not any(x["status"] == "SUBMISSION_UNCERTAIN" for x in after["intents"]):
                            raise AssertionError("unknown submission failed to block and retain intent")
                        covered.add(PteInspectionCapability.RELEVANT_FAILURE.value)
                    except OrderSubmissionBatchError:
                        if not any(x.outcome is SubmissionOutcome.REJECTED for x in declared):
                            raise
                    for result in declared:
                        if result.order not in broker.used_submissions:
                            raise AssertionError("declared channel submission did not occur")
                        completed(result.event_id)
            elif isinstance(item, (PteOrderUpdate, PteRepeatedOrderReport)):
                update = item if isinstance(item, PteOrderUpdate) else broker.updates[item.source_event_id]
                broker.apply(update)
                execution.refresh_account()
                execution.refresh_orders()
                after = _snapshot(store, account_id, broker)
                if isinstance(item, PteRepeatedOrderReport):
                    if _comparison_snapshot(before) != _comparison_snapshot(after):
                        raise AssertionError("repeat report changed account or order facts")
                    if checkpoints.get(event_id):
                        covered.add(PteInspectionCapability.IDEMPOTENCE.value)
                if update.status in {InspectionOrderStatus.OPEN, InspectionOrderStatus.PARTIAL} and checkpoints.get(event_id):
                    covered.add(PteInspectionCapability.NO_OR_PARTIAL_FILL.value)
            completed(event_id)
        if set(broker.submissions) != broker.used_submissions or set(broker.updates) != broker.used_updates:
            raise AssertionError("declared channel events were not consumed")
        final = _snapshot(store, account_id, broker)
        positive = [i for i, quantity in enumerate(holdings_at_decision) if quantity > 0]
        final_checkpoint = bool(trace and checkpoints.get(trace[-1]["event_id"]))
        held_check = any(row["event_id"].endswith(":decision") and row["snapshot"]["position_quantity"] > 0
                        and not row["snapshot"]["expected_orders"] and checkpoints.get(row["event_id"]) for row in trace if "snapshot" in row)
        if positive and final_checkpoint and held_check and final["position_quantity"] == 0 and len(store.account_fills(account_id)) >= 2:
            covered.add(PteInspectionCapability.ENTER_HOLD_EXIT.value)
        if restarted and restart_qualified and final_checkpoint and any(checkpoints.get(event) for event in scenario.restart_after):
            covered.add(PteInspectionCapability.RECOVERY.value)
        quantities = [row["snapshot"]["position_quantity"] for row in trace if "snapshot" in row]
        changes = [(a, b) for a, b in zip(quantities, quantities[1:]) if a > 0 and b > 0 and a != b]
        if any(a < b for a, b in changes) and any(a > b for a, b in changes) and len(set(target_values)) > 1:
            covered.add(PteInspectionCapability.POSITION_CHANGE.value)
        return {"status": "PASS", "code": "OK", "trace": trace, "capabilities": sorted(covered),
                "position_change_applicable": definition.execution.settings.get("capital", {}).get("mode") == "target_equity_fraction"}
    except Exception as exc:
        if fault is not None and fault.fault is PteFault.PACKAGE_CONTENT_CHANGED and not loaded:
            from strategy_runtime.errors import RuntimeCompatibilityError
            if isinstance(exc, RuntimeCompatibilityError) and "file differs" in str(exc) and not broker.called:
                return {"status": "PASS", "code": fault.fault.value,
                        "summary": "changed package rejected at LOAD before account creation or order submission",
                        "trace": [{"event_id": "LOAD", "expected_rejection": fault.fault.value,
                                   "actual_error": str(exc), "new_order_count": 0}],
                        "capabilities": [PteInspectionCapability.RELEVANT_FAILURE.value]}
        return {"status": "FAIL", "code": "PTE_FAILURE", "summary": f"{type(exc).__name__}: {exc}",
                "trace": trace, "capabilities": []}
    finally:
        close_components()


def _worker(input_path, case_id, output_dir, variant):
    request = PteReleaseInspectionRequest.from_dict(json.loads(Path(input_path).read_text(encoding="utf-8")))
    fault = next((x for x in request.protocol.failures if x.case_id == case_id), None)
    scenario_id = case_id if fault is None else fault.scenario_id
    scenario = next(x for x in request.protocol.scenarios if x.scenario_id == scenario_id)
    directory = Path(output_dir)
    if fault is not None and fault.fault is PteFault.PACKAGE_CONTENT_CHANGED:
        root = directory.parent / (directory.name + "-repository")
        _permit(request).validate_path(root)
        shutil.copytree(request.isolated_repository, root)
        package = validate_release_package(root / "strategies", request.expected_release_id)
        source = next(path for path in package.source_root.rglob("*.py") if path.is_file())
        source.write_bytes(source.read_bytes() + b"\n# controlled inspection fault\n")
        request = replace(request, isolated_repository=root)
    result = _run_scenario(request, scenario, directory, restart=variant == "restart", fault=fault)
    _write(directory / "result.json", result)


class _InspectionWorkerNotQuiescent(RuntimeError):
    """Evidence cannot be collected while an owned worker may still write it."""

    quiescent = False


def _stop_worker(process):
    if process.poll() is not None:
        return
    for action in (process.terminate, process.kill):
        try:
            action()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if process.poll() is not None:
            return
    raise _InspectionWorkerNotQuiescent("PTE worker did not stop after bounded terminate/kill")


def inspect_release(request: PteReleaseInspectionRequest, *, control: InspectionControl | None = None):
    if type(request) is not PteReleaseInspectionRequest or (control is not None and type(control) is not InspectionControl):
        raise TypeError("inspect_release requires typed request/control")
    control = control or InspectionControl()
    permit = _permit(request)
    environment = collect_inspection_environment(request.isolated_repository)
    requirement = request.protocol.environment
    if (environment.platform_build_sha256, environment.pte_contract_version, environment.srt_contract_version) != (
        requirement.platform_build_sha256, requirement.pte_contract_version, requirement.srt_contract_version):
        return PteInspectionOutcome(request.run_id, PteInspectionStatus.NOT_RUN, environment,
            (PteScenarioResult("environment", PteInspectionStatus.NOT_RUN, "ENVIRONMENT_MISMATCH", "actual environment differs from the protocol", ()),), (), ())
    _inputs(request, permit)
    input_path = permit.validate_path(request.workspace / "pte-request.json")
    if input_path.exists():
        raise ValueError("PTE inspection workspace already used")
    _write(input_path, request)
    started = time.monotonic()
    results, artifacts, observations = [], [], {}
    total = len(request.protocol.scenarios) + len(request.protocol.failures)
    cases = [(s.scenario_id, bool(s.restart_after)) for s in request.protocol.scenarios]
    cases.extend((f.case_id, False) for f in request.protocol.failures)
    interrupted = None
    interruption_detail = ""

    def control_boundary():
        nonlocal interrupted, interruption_detail
        try:
            cancelled = control.cancelled() if control.cancelled else False
            if type(cancelled) is not bool:
                raise TypeError("cancelled callback must return bool")
            if cancelled:
                interrupted, interruption_detail = "CANCELLED", "inspection cancelled"
            elif control.timeout_seconds is not None and time.monotonic() - started >= control.timeout_seconds:
                interrupted, interruption_detail = "RESOURCE_LIMIT", "PTE execution deadline exceeded"
        except Exception as exc:
            interrupted, interruption_detail = "EXECUTION_ERROR", f"cancelled callback failed: {exc}"
        return interrupted is not None

    def report(done, message):
        nonlocal interrupted, interruption_detail
        if control.on_progress:
            try:
                control.on_progress(InspectionProgress(request.run_id, InspectionStage.PTE, done, total,
                                                       time.monotonic() - started, message))
            except Exception as exc:
                interrupted, interruption_detail = "EXECUTION_ERROR", f"progress callback failed: {exc}"

    variants = [("restart", "continuous") if control_case else ("restart",) for _, control_case in cases]
    outputs_by_case = [[] for _ in cases]
    artifacts_by_case = [[] for _ in cases]
    pending = deque(range(len(cases)))
    active = {}
    peak_workers = 0

    def incomplete_result():
        return {"status": "FAIL" if interrupted == "EXECUTION_ERROR" else "INCOMPLETE",
                "code": interrupted, "summary": interruption_detail, "trace": [], "capabilities": []}

    def collect(index, worker):
        process, out, directory, log, variant = worker
        # Only collect after the writer is quiescent, including on cancellation.
        if process.poll() is None:
            raise _InspectionWorkerNotQuiescent("cannot collect an active PTE worker")
        out.close()
        result_path = directory / "result.json"
        if process.returncode == 0 and result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                PteInspectionStatus(result["status"])
                if not isinstance(result["code"], str) or not isinstance(result.get("trace"), list):
                    raise ValueError("invalid PTE worker result")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                result = {"status": "FAIL", "code": "EXECUTION_ERROR", "summary": str(exc),
                          "trace": [], "capabilities": []}
        elif interrupted:
            result = incomplete_result()
        else:
            result = {"status": "FAIL", "code": "EXECUTION_ERROR",
                      "summary": log.read_text(encoding="utf-8", errors="replace")[-4000:],
                      "trace": [], "capabilities": []}
        outputs_by_case[index].append(result)
        for path in (result_path, log, directory / "trace.jsonl"):
            if path.is_file():
                artifact_id = f"{cases[index][0]}:{variant}:{path.name}"
                schema = {".jsonl": "pte.inspection.trace", ".log": "pte.inspection.log", ".json": "pte.inspection.result"}[path.suffix]
                artifacts_by_case[index].append(PteArtifact(artifact_id, path.relative_to(request.workspace).as_posix(),
                    hashlib.sha256(path.read_bytes()).hexdigest(), schema, 1))

    def completed_count():
        return sum(len(outputs) == len(expected) for outputs, expected in zip(outputs_by_case, variants, strict=True))

    last_progress = 0.0
    try:
        while pending or active:
            # Harvest completed results before observing cancellation, so completed facts survive it.
            for index, worker in tuple(active.items()):
                if worker[0].poll() is None:
                    continue
                del active[index]
                collect(index, worker)
                if len(outputs_by_case[index]) < len(variants[index]):
                    pending.appendleft(index)
                else:
                    report(completed_count(), f"PTE {cases[index][0]} completed")
                if interrupted:
                    break
            if interrupted or control_boundary():
                break
            while pending and len(active) < control.max_workers:
                if control_boundary():
                    break
                index = pending.popleft()
                case_id = cases[index][0]
                variant = variants[index][len(outputs_by_case[index])]
                directory = request.workspace / "scenarios" / case_id / variant
                permit.validate_path(directory)
                log = directory.parent / f"{variant}-worker.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                env = dict(os.environ)
                env.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
                env["TMP"] = env["TEMP"] = str(request.workspace)
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                out = log.open("wb")
                try:
                    process = subprocess.Popen([sys.executable, "-m", __name__, "--worker", str(input_path), case_id, str(directory), variant],
                        cwd=request.workspace, env=env, stdout=out, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except BaseException:
                    out.close()
                    raise
                active[index] = process, out, directory, log, variant
                peak_workers = max(peak_workers, len(active))
            if interrupted:
                break
            elapsed = time.monotonic() - started
            if active and elapsed - last_progress >= _PROGRESS_INTERVAL_SECONDS:
                report(completed_count(), f"PTE active workers: {len(active)}")
                last_progress = elapsed
            if not interrupted and active:
                time.sleep(0.1)
    except Exception as exc:
        interrupted, interruption_detail = "EXECUTION_ERROR", f"worker orchestration failed: {exc}"
    finally:
        stop_error = None
        for worker in active.values():
            try:
                _stop_worker(worker[0])
            except _InspectionWorkerNotQuiescent as exc:
                stop_error = exc
            finally:
                worker[1].close()
        if stop_error is not None:
            raise stop_error
    for index, worker in active.items():
        collect(index, worker)

    # Stable protocol order, independent of process completion order.
    for index, (case_id, _) in enumerate(cases):
        outputs = outputs_by_case[index]
        if not outputs:
            continue
        artifacts.extend(artifacts_by_case[index])
        artifact_ids = tuple(item.artifact_id for item in artifacts_by_case[index])
        outcome = next((item for item in outputs if item["status"] == "FAIL"), outputs[0])
        if len(outputs) < len(variants[index]) and outcome["status"] != "FAIL":
            outcome = incomplete_result()
        elif len(outputs) == 2 and outputs[0]["status"] == "PASS":
            comparison = [[(row["event_id"], _comparison_snapshot(row["snapshot"])) for row in x["trace"] if "snapshot" in row] for x in outputs]
            if outputs[1]["status"] != "PASS":
                outcome = {**outputs[1], "summary": "uninterrupted control failed: " + outputs[1].get("summary", outputs[1]["code"])}
            elif comparison[0] != comparison[1]:
                outcome = {**outcome, "status": "FAIL", "code": "RECOVERY_DIFFERENCE", "summary": "restarted execution differs from uninterrupted execution", "capabilities": []}
        observations[case_id] = outcome
        results.append(PteScenarioResult(case_id, PteInspectionStatus(outcome["status"]), outcome["code"],
                                        outcome.get("summary", "declared scenario and checkpoints completed"), tuple(artifact_ids)))
    if interrupted:
        results.append(PteScenarioResult("execution-control",
            PteInspectionStatus.FAIL if interrupted == "EXECUTION_ERROR" else PteInspectionStatus.INCOMPLETE,
            interrupted, interruption_detail, ()))
    coverage = []
    for required in request.protocol.coverage:
        relevant = [observations.get(case_id, {}) for case_id in required.scenario_ids]
        if required.capability is PteInspectionCapability.RELEVANT_FAILURE:
            relevant.extend(observations.get(f.case_id, {}) for f in request.protocol.failures if f.scenario_id in required.scenario_ids)
        covered = any(x.get("status") == "PASS" and required.capability.value in x.get("capabilities", ()) for x in relevant)
        if required.requirement is CoverageRequirement.NOT_APPLICABLE:
            if not relevant:
                relevant = [observations.get(x.scenario_id, {}) for x in request.protocol.scenarios]
            covered = bool(relevant) and all(x.get("status") == "PASS" and x.get("position_change_applicable") is False for x in relevant)
        coverage.append(PteCoverageResult(required.capability, required.requirement, covered, required.scenario_ids, required.reason))
    current_environment = collect_inspection_environment(request.isolated_repository)
    status = PteInspectionStatus.PASS
    if any(x.status is PteInspectionStatus.FAIL for x in results) or current_environment != environment:
        status = PteInspectionStatus.FAIL
    elif interrupted or len(results) != total or not all(x.covered for x in coverage):
        status = PteInspectionStatus.INCOMPLETE
    if current_environment != environment:
        results.append(PteScenarioResult("environment-final", PteInspectionStatus.FAIL, "ENVIRONMENT_MISMATCH", "execution environment changed during inspection", ()))
    summary = {"status": status, "coverage": coverage, "scenarios": results, "elapsed_seconds": time.monotonic() - started,
               "channel_model": "RECORDED_FILLS_V1", "effective_workers": peak_workers}
    summary_path = request.workspace / "pte-summary.json"
    _write(summary_path, summary)
    artifacts.append(PteArtifact("pte-summary", summary_path.relative_to(request.workspace).as_posix(),
                                hashlib.sha256(summary_path.read_bytes()).hexdigest(), "pte.inspection.summary", 1))
    return PteInspectionOutcome(request.run_id, status, environment, tuple(results), tuple(coverage), tuple(artifacts))


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] != "--worker":
        raise SystemExit("inspection worker requires a managed request and case")
    _worker(*sys.argv[2:])
