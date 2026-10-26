"""Focused offline boundaries: no formal qualification, network or research archive."""
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import shutil
import json
import subprocess
import sys
from uuid import uuid4

import pytest
from dataflows import DataRequest, Dataset, PreparedDataRef
from strategy_runtime import StrategyIdentity, StrategyInputPlan, StrategyInputBinding, TradableWindow
from strategy_runtime.inspection import InspectionRuntimePermit, InspectionControl, collect_inspection_environment
from paper_trading_engine.inspection import (
    PteDecisionInput, PteOrderKey, PteSubmissionResult, SubmissionOutcome,
    PteOrderUpdate, InspectionOrderStatus,
    PteCheckpointExpectation, PteInspectionScenario,
    PteEnvironmentRequirement, PteInspectionProtocol, PteCoverageRequirement,
    PteInspectionCapability, CoverageRequirement, PteFailureCase, PteFault,
    PteReleaseInspectionRequest, PteInspectionStatus,
)
from paper_trading_engine.inspection_broker import RecordedFillBroker
from paper_trading_engine.broker import OrderIntent, BrokerSubmissionUncertainError
from paper_trading_engine.lifecycle import AccountHealth
from paper_trading_engine.store import PaperStore


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 16, 10, tzinfo=TZ)


def decision_input():
    session = date(2026, 9, 16)
    prior = date(2026, 9, 15)
    request = DataRequest(Dataset.TRADING_CALENDAR, "SSE", "2026-09-15", "2026-09-16", "2026-09-16")
    plan = StrategyInputPlan(StrategyIdentity("S900", "S900-C0001", "a"*64, "b"*64, "588080.SH"),
        TradableWindow(session, session), "calendar", "c"*64, {"calendar": request},
        (prior, session), {session: prior}, (prior,))
    return PteDecisionInput("buy", StrategyInputBinding(plan, PreparedDataRef(uuid4(), uuid4(), "d"*64)),
        datetime(2026,9,15,20,31,tzinfo=TZ), session, NOW, True)


def test_scenario_serialization_and_invalid_channel_boundaries():
    step = decision_input()
    key = PteOrderKey("buy", 0)
    submission = PteSubmissionResult("accepted", NOW, key, SubmissionOutcome.ACCEPTED)
    update = PteOrderUpdate("partial", NOW+timedelta(minutes=1), key, InspectionOrderStatus.PARTIAL,
                            100, Decimal("1"), Decimal("0.1"))
    checkpoint = PteCheckpointExpectation("empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0)
    scenario = PteInspectionScenario("sample", Decimal("1000"), (step,), (submission, update), (checkpoint,), ("partial",))
    assert PteInspectionScenario.from_dict(scenario.to_dict()) == scenario
    with pytest.raises(ValueError, match="synchronous"):
        replace(scenario, channel_events=(replace(submission, observed_at=NOW+timedelta(seconds=1)),))
    with pytest.raises(ValueError, match="missing event"):
        replace(scenario, restart_after=("not-an-event",))
    with pytest.raises(ValueError, match="mean price"):
        replace(update, cumulative_filled_quantity=0)
    with pytest.raises(ValueError, match="fields"):
        PteOrderKey.from_dict({"decision_step_id": "buy", "order_ordinal": 0, "sql": "anything"})
    for identifier in ("2numeric", "a:directory", "CON", "LPT1", "a" * 101):
        with pytest.raises(ValueError, match="case id"):
            replace(scenario, scenario_id=identifier)


def test_channel_cumulative_facts_are_independent_and_idempotent():
    key = PteOrderKey("buy", 0)
    result = PteSubmissionResult("accepted", NOW, key, SubmissionOutcome.ACCEPTED)
    partial = PteOrderUpdate("partial", NOW+timedelta(minutes=1), key, InspectionOrderStatus.PARTIAL,
                            400, Decimal("1.5"), Decimal("0.6"))
    full = replace(partial, event_id="full", status=InspectionOrderStatus.FILLED,
                   cumulative_filled_quantity=1000, cumulative_fee=Decimal("1.5"))
    broker = RecordedFillBroker(Decimal("2000"), "588080.SH", (result,), (partial, full), lambda: NOW)
    intent = OrderIntent("PTE-unit", "decision", "588080.SH", "BUY", 1000, 1.6)
    broker.bind_intents({intent.intent_id: key})
    broker.place_order(intent)
    broker.apply(partial)
    before = broker.snapshot()
    broker.apply(partial)
    assert broker.snapshot() == before
    assert Decimal(str(before.account.cash)) == Decimal("1399.4")
    assert before.positions[0].quantity == 400
    assert before.account.frozen_cash == 960
    broker.apply(full)
    assert broker.snapshot().account.cash == 498.5
    assert broker.snapshot().account.frozen_cash == 0
    with pytest.raises(ValueError, match="cumulative"):
        broker.apply(partial)
    with pytest.raises(ValueError, match="repeated"):
        broker.place_order(intent)


def test_unknown_submission_has_no_invented_fill():
    key = PteOrderKey("buy", 0)
    result = PteSubmissionResult("unknown", NOW, key, SubmissionOutcome.UNKNOWN)
    broker = RecordedFillBroker(Decimal("2000"), "588080.SH", (result,), (), lambda: NOW)
    intent = OrderIntent("PTE-unit", "decision", "588080.SH", "BUY", 1000, 1.6)
    broker.bind_intents({intent.intent_id: key})
    with pytest.raises(BrokerSubmissionUncertainError):
        broker.place_order(intent)
    assert broker.snapshot().account.cash == 2000
    assert broker.snapshot().orders == broker.snapshot().positions == ()
    market = replace(intent, intent_id="market", order_type="MARKET")
    unsupported = RecordedFillBroker(Decimal("2000"), "588080.SH", (result,), (), lambda: NOW)
    unsupported.bind_intents({market.intent_id: key})
    with pytest.raises(ValueError, match="synchronous fill or rejection"):
        unsupported.place_order(market)
    assert unsupported.snapshot().orders == ()


def test_failure_reference_must_name_a_real_decision():
    checkpoint = PteCheckpointExpectation("empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0)
    scenario = PteInspectionScenario("sample", Decimal("1000"), (decision_input(),), (), (checkpoint,))
    coverage = tuple(PteCoverageRequirement(capability, CoverageRequirement.REQUIRED, ("sample",), "declared boundary")
                     for capability in PteInspectionCapability)
    protocol = PteInspectionProtocol(PteEnvironmentRequirement("a" * 64, "pte-inspection-v1", "srt-inspection-v1"),
                                    (scenario,), coverage, ())
    missing = PteFailureCase("missing", "sample", PteFault.INPUT_UNAVAILABLE, "wrong:decision")
    with pytest.raises(ValueError, match="missing decision event"):
        replace(protocol, failures=(missing,))
    with pytest.raises(ValueError, match="duplicate case"):
        replace(protocol, failures=(replace(missing, case_id="SAMPLE", at_event_id="buy:decision"),))


def test_technical_database_rejects_normal_open_and_foreign_permit():
    # Windows sandbox users cannot reopen pytest's chmod(0700) temporary root.
    # Use the repository's explicitly approved temporary space instead.
    root = Path(__file__).resolve().parents[3] / ".tmp" / ("pte-contract-" + uuid4().hex) / ".tmp/strategy-inspection/isolated-test"
    permit = InspectionRuntimePermit("isolated-test", "S900-v1", "a"*64, "b"*64, "c"*64, root/"repository", root)
    path = root / "runtime.db"
    store = PaperStore(path, inspection_permit=permit)
    store.create_virtual_account("account", "test", "S900-v1", "a"*64, "1000", strategy_id="S900",
        strategy_name_snapshot="Synthetic", strategy_version="v1", release_hash="a"*64,
        qualification_snapshot="INSPECTION", selection_data_cutoff="2026-09-01")
    assert store.virtual_account("account")["qualification_snapshot"] == "INSPECTION"
    assert store.set_virtual_paused("account", False)["run_state"] == "RUNNING"
    store.set_virtual_paused("account", True)
    store._connection.execute("DELETE FROM inspection_admissions WHERE account_id='account'")
    store._connection.commit()
    with pytest.raises(ValueError, match="enable checks"):
        store.set_virtual_paused("account", False)
    store.close()
    reopened = PaperStore(path, inspection_permit=permit)
    assert reopened.virtual_account("account")["cash"] == "1000.0000"
    reopened.close()
    with pytest.raises(ValueError, match="rejects an inspection"):
        PaperStore(path)
    with pytest.raises(ValueError, match="rejects an inspection"):
        PaperStore.open_readonly(path)
    copied = root / "copied.db"
    shutil.copy2(path, copied)
    with pytest.raises(ValueError, match="rejects an inspection"):
        PaperStore(copied)
    with pytest.raises(ValueError, match="rejects an inspection"):
        PaperStore.open_readonly(copied)
    with pytest.raises(ValueError, match="another permit"):
        PaperStore(path, inspection_permit=replace(permit, protocol_sha256="d"*64))


@pytest.mark.parametrize("stop", ["cancel", "invalid_cancel", "cancel_exception", "timeout", "progress"])
def test_worker_control_retains_completed_artifacts_and_stops_writer(tmp_path, monkeypatch, stop):
    """Real child lifecycles; the child's result is only a controller test fixture."""
    from paper_trading_engine import inspection_runner as runner
    workspace = tmp_path / ".tmp/strategy-inspection/control-test"
    workspace.mkdir(parents=True)
    environment = collect_inspection_environment(tmp_path)
    checkpoint = PteCheckpointExpectation("empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0)
    scenarios = tuple(PteInspectionScenario(name, Decimal("1000"), (decision_input(),), (), (checkpoint,))
                      for name in ("fast", "slow", "slow2"))
    coverage = tuple(PteCoverageRequirement(capability, CoverageRequirement.REQUIRED, ("fast",), "controller fixture")
                     for capability in PteInspectionCapability)
    protocol = PteInspectionProtocol(PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version), scenarios, coverage, ())
    request = PteReleaseInspectionRequest("control-test", workspace / "repository", workspace,
        "S900-v1", "a" * 64, "b" * 64, (), (), protocol)
    monkeypatch.setattr(runner, "_inputs", lambda *args: {})
    monkeypatch.setattr(runner, "_PROGRESS_INTERVAL_SECONDS", 0)
    original_popen = subprocess.Popen
    processes = []
    child_script = """
import json, pathlib, sys, time
case, target = sys.argv[1:]
root = pathlib.Path(target)
root.mkdir(parents=True)
(root / 'trace.jsonl').write_text('{}\\n', encoding='utf-8')
print('controller fixture started', flush=True)
if case.startswith('slow'):
    time.sleep(30)
else:
    (root / 'result.json').write_text(json.dumps({'status':'PASS', 'code':'OK',
        'trace':[], 'capabilities':[]}), encoding='utf-8')
"""
    def start_child(command, **kwargs):
        if "--worker" not in command:
            return original_popen(command, **kwargs)
        process = original_popen([sys.executable, "-c", child_script, command[-3], command[-2]], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runner.subprocess, "Popen", start_child)
    fired = []
    completed = [0]
    marker = workspace / "scenarios/slow/restart/trace.jsonl"
    def cancel():
        if marker.is_file() and completed[0] >= 1 and not fired:
            fired.append(True)
            if stop == "invalid_cancel":
                return "yes"
            if stop == "cancel_exception":
                raise RuntimeError("cancel observer failed")
            return True
        return False
    def progress(value):
        completed[0] = value.completed
        if stop == "progress" and value.completed == 1 and marker.is_file():
            raise RuntimeError("progress observer failed")
    outcome = runner.inspect_release(request, control=InspectionControl(
        max_workers=3,
        timeout_seconds=3 if stop == "timeout" else 10,
        cancelled=cancel if stop in {"cancel", "invalid_cancel", "cancel_exception"} else None,
        on_progress=progress))
    expected = "CANCELLED" if stop == "cancel" else "RESOURCE_LIMIT" if stop == "timeout" else "EXECUTION_ERROR"
    assert outcome.status is (PteInspectionStatus.INCOMPLETE if stop in {"cancel", "timeout"} else PteInspectionStatus.FAIL)
    assert outcome.scenarios[0].case_id == "fast" and outcome.scenarios[0].status is PteInspectionStatus.PASS
    assert outcome.scenarios[-1].code == expected
    assert len(processes) == 3 and all(process.poll() is not None for process in processes)
    assert any(item.path == "scenarios/fast/restart/result.json" for item in outcome.artifacts)
    assert any(item.path == "scenarios/slow/restart/trace.jsonl" for item in outcome.artifacts)
    summary = json.loads((workspace / "pte-summary.json").read_text(encoding="utf-8"))
    assert summary["scenarios"][-1]["code"] == expected
    assert summary["effective_workers"] == 3


def test_unstoppable_worker_cannot_publish_or_clean_evidence():
    from paper_trading_engine.inspection_runner import _stop_worker, _InspectionWorkerNotQuiescent
    class Stuck:
        def poll(self):
            return None
        def terminate(self):
            pass
        def kill(self):
            pass
        def wait(self, timeout):
            assert timeout == 5
            raise subprocess.TimeoutExpired("stuck", timeout)
    with pytest.raises(_InspectionWorkerNotQuiescent) as caught:
        _stop_worker(Stuck())
    assert caught.value.quiescent is False


@pytest.fixture
def concurrent_inspection(tmp_path, monkeypatch):
    """Exercise the public scheduler with real, deterministic fixture subprocesses."""
    from paper_trading_engine import inspection_runner as runner
    workspace = tmp_path / ".tmp/strategy-inspection/concurrency-test"
    workspace.mkdir(parents=True)
    environment = collect_inspection_environment(tmp_path)
    checkpoint = PteCheckpointExpectation("empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0)
    scenarios = tuple(PteInspectionScenario(name, Decimal("1000"), (decision_input(),), (), (checkpoint,),
        ("LOAD",) if name == "slow" else ()) for name in ("slow", "fast", "third"))
    coverage = tuple(PteCoverageRequirement(capability, CoverageRequirement.REQUIRED, ("slow",), "controller fixture")
                     for capability in PteInspectionCapability)
    protocol = PteInspectionProtocol(PteEnvironmentRequirement(environment.platform_build_sha256,
        environment.pte_contract_version, environment.srt_contract_version), scenarios, coverage, ())
    request = PteReleaseInspectionRequest("concurrency-test", workspace / "repository", workspace,
        "S900-v1", "a" * 64, "b" * 64, (), (), protocol)
    monkeypatch.setattr(runner, "_inputs", lambda *args: {})
    original_popen = subprocess.Popen
    processes, behavior = [], {"failure": "none"}
    script = """
import json, pathlib, sys, time
case, target, mode, capabilities = sys.argv[1:]
root = pathlib.Path(target)
root.mkdir(parents=True)
start = time.monotonic()
time.sleep(0.8 if case == 'slow' else 0.2)
(root / 'timing.json').write_text(json.dumps([start, time.monotonic()]))
(root / 'trace.jsonl').write_text('{}\\n')
if case == 'fast' and mode == 'exit':
    sys.exit(7)
result = '{' if case == 'fast' and mode == 'json' else json.dumps({
    'status':'PASS', 'code':'OK', 'trace':[], 'capabilities':json.loads(capabilities)})
(root / 'result.json').write_text(result)
"""
    def start_child(command, **kwargs):
        if "--worker" not in command:
            return original_popen(command, **kwargs)
        if command[-3] == "fast" and behavior["failure"] == "spawn":
            raise OSError("controlled launch failure")
        process = original_popen([sys.executable, "-c", script, command[-3], command[-2], behavior["failure"],
            json.dumps([x.value for x in PteInspectionCapability])], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runner.subprocess, "Popen", start_child)
    return runner, request, processes, behavior


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_inspection_parallelism_is_bounded_ordered_and_recovery_paths_are_sequential(concurrent_inspection, workers):
    runner, request, processes, _ = concurrent_inspection
    progress = []
    result = runner.inspect_release(request, control=InspectionControl(max_workers=workers, on_progress=progress.append))
    assert result.status is PteInspectionStatus.PASS
    assert [x.case_id for x in result.scenarios] == ["slow", "fast", "third"]
    assert all(x.covered for x in result.coverage)
    assert len(processes) == 4 and all(p.poll() is not None for p in processes)
    timings = {p.parent.relative_to(request.workspace).as_posix(): json.loads(p.read_text())
               for p in request.workspace.rglob("timing.json")}
    assert timings["scenarios/slow/restart"][1] <= timings["scenarios/slow/continuous"][0]
    events = sorted((instant, delta) for pair in timings.values() for instant, delta in zip(pair, (1, -1)))
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    assert peak == min(workers, 3)
    summary = json.loads((request.workspace / "pte-summary.json").read_text())
    assert summary["effective_workers"] == min(workers, 3)
    assert [x.completed for x in progress] == sorted(x.completed for x in progress)
    assert [x.case_id for x in result.scenarios] == [x["case_id"] for x in summary["scenarios"]]


@pytest.mark.parametrize("failure", ["exit", "json", "spawn"])
def test_parallel_inspection_failures_stop_owned_workers_and_preserve_other_results(concurrent_inspection, failure):
    runner, request, processes, behavior = concurrent_inspection
    behavior["failure"] = failure
    result = runner.inspect_release(request, control=InspectionControl(max_workers=2))
    assert result.status is PteInspectionStatus.FAIL
    assert all(p.poll() is not None for p in processes)
    if failure == "spawn":
        assert result.scenarios[-1].case_id == "execution-control"
        assert result.scenarios[-1].code == "EXECUTION_ERROR"
    else:
        assert [x.status for x in result.scenarios] == [PteInspectionStatus.PASS, PteInspectionStatus.FAIL, PteInspectionStatus.PASS]
        assert result.scenarios[1].code == "EXECUTION_ERROR"


def test_cancel_before_dispatch_reports_zero_workers(concurrent_inspection):
    runner, request, processes, _ = concurrent_inspection
    result = runner.inspect_release(request, control=InspectionControl(max_workers=8, cancelled=lambda: True))
    assert result.status is PteInspectionStatus.INCOMPLETE
    assert processes == []
    assert json.loads((request.workspace / "pte-summary.json").read_text())["effective_workers"] == 0


def test_shutdown_attempts_every_worker_before_reporting_unconfirmed_exit(concurrent_inspection, monkeypatch):
    runner, request, processes, _ = concurrent_inspection
    original_stop = runner._stop_worker
    stopped = []
    def unconfirmed(process):
        original_stop(process)
        stopped.append(process)
        if len(stopped) == 1:
            raise runner._InspectionWorkerNotQuiescent("controlled unconfirmed exit")
    monkeypatch.setattr(runner, "_stop_worker", unconfirmed)
    with pytest.raises(runner._InspectionWorkerNotQuiescent):
        runner.inspect_release(request, control=InspectionControl(max_workers=2, cancelled=lambda: len(processes) == 2))
    assert stopped == processes and len(stopped) == 2
    assert all(p.poll() is not None for p in processes)
    assert not (request.workspace / "pte-summary.json").exists()
