"""Focused offline boundaries: no formal qualification, network or research archive."""

from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import shutil
import json
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dataflows import DataRequest, Dataset, PreparedDataRef
from strategy_runtime import (
    StrategyIdentity,
    StrategyInputPlan,
    StrategyInputBinding,
    TradableWindow,
)
from paper_trading_engine.ec_boundary import execution_permit
from strategy_runtime.inspection import (
    InspectionRuntimePermit,
    InspectionControl,
    collect_inspection_environment,
)
from paper_trading_engine.inspection import (
    PteDecisionInput,
    PteOrderKey,
    PteSubmissionResult,
    SubmissionOutcome,
    PteOrderUpdate,
    InspectionOrderStatus,
    PteCheckpointExpectation,
    PteInspectionScenario,
    PteEnvironmentRequirement,
    PteInspectionProtocol,
    PteCoverageRequirement,
    PteInspectionCapability,
    CoverageRequirement,
    PteFailureCase,
    PteFault,
    PteReleaseInspectionRequest,
    PteInspectionStatus,
)
from paper_trading_engine.inspection_broker import RecordedFillBroker
from execution_channels.futu.broker import OrderIntent, BrokerSubmissionUncertainError
from execution_channels.futu.lifecycle import AccountHealth
from execution_channels.futu.store import PaperStore


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 16, 10, tzinfo=TZ)


@pytest.fixture(scope="module")
def controller_environment(tmp_path_factory):
    """Authenticate once; scheduler cases exercise worker control, not rehashing."""
    return collect_inspection_environment(tmp_path_factory.mktemp("inspection-controller"))


def decision_input():
    session = date(2026, 9, 16)
    prior = date(2026, 9, 15)
    request = DataRequest(Dataset.TRADING_CALENDAR, "SSE", "2026-09-15", "2026-09-16", "2026-09-16")
    plan = StrategyInputPlan(
        StrategyIdentity("S900", "S900-C0001", "a" * 64, "b" * 64, "588080.SH"),
        TradableWindow(session, session),
        "calendar",
        "c" * 64,
        {"calendar": request},
        (prior, session),
        {session: prior},
        (prior,),
    )
    return PteDecisionInput(
        "buy",
        StrategyInputBinding(plan, PreparedDataRef(uuid4(), uuid4(), "d" * 64)),
        datetime(2026, 9, 15, 20, 31, tzinfo=TZ),
        session,
        NOW,
        True,
    )


# Independent risk: PTE27; responsibility-level assertions.
def test_PTE27_C01_scenario_serialization_and_invalid_channel_boundaries():
    step = decision_input()
    key = PteOrderKey("buy", 0)
    submission = PteSubmissionResult("accepted", NOW, key, SubmissionOutcome.ACCEPTED)
    update = PteOrderUpdate(
        "partial",
        NOW + timedelta(minutes=1),
        key,
        InspectionOrderStatus.PARTIAL,
        100,
        Decimal("1"),
        Decimal("0.1"),
    )
    checkpoint = PteCheckpointExpectation(
        "empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0
    )
    scenario = PteInspectionScenario(
        "sample", Decimal("1000"), (step,), (submission, update), (checkpoint,), ("partial",)
    )
    assert PteInspectionScenario.from_dict(scenario.to_dict()) == scenario


# Independent risk: PTE27; responsibility-level assertions.


# Independent risk: PTE27; responsibility-level assertions.
def test_PTE27_C03_unknown_submission_has_no_invented_fill():
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


# Independent risk: PTE27; responsibility-level assertions.
def test_PTE27_C02_failure_reference_must_name_a_real_decision():
    checkpoint = PteCheckpointExpectation(
        "empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0
    )
    scenario = PteInspectionScenario(
        "sample", Decimal("1000"), (decision_input(),), (), (checkpoint,)
    )
    coverage = tuple(
        PteCoverageRequirement(
            capability, CoverageRequirement.REQUIRED, ("sample",), "declared boundary"
        )
        for capability in PteInspectionCapability
    )
    protocol = PteInspectionProtocol(
        PteEnvironmentRequirement("a" * 64, "pte-inspection-v1", "srt-inspection-v1"),
        (scenario,),
        coverage,
        (),
    )
    missing = PteFailureCase("missing", "sample", PteFault.INPUT_UNAVAILABLE, "wrong:decision")
    with pytest.raises(ValueError, match="missing decision event"):
        replace(protocol, failures=(missing,))


# Independent risk: EC27; responsibility-level assertions.
@pytest.mark.parametrize(
    "case",
    ["valid", "copied-normal", "copied-readonly", "release", "protocol", "admission"],
    ids=["EC27-C01", "EC27-C02", "EC27-C03", "EC27-C04", "EC27-C05", "EC27-C06"],
)
def test_technical_account_permit_boundary(tmp_path, case):
    root = tmp_path / ".tmp/strategy-inspection/isolated-test"
    permit = InspectionRuntimePermit(
        "isolated-test", "S900-v1", "a" * 64, "b" * 64, "c" * 64, root / "repository", root
    )
    path = root / "runtime.db"
    store = PaperStore(path, inspection_permit=execution_permit(permit))
    try:
        store.create_virtual_account(
            "account",
            "test",
            "S900-v1",
            "a" * 64,
            "1000",
            strategy_id="S900",
            strategy_name_snapshot="Synthetic",
            strategy_version="v1",
            release_hash="a" * 64,
            qualification_snapshot="INSPECTION",
            selection_data_cutoff="2026-09-01",
        )
        if case == "valid":
            assert store.virtual_account("account")["qualification_snapshot"] == "INSPECTION"
            assert store.set_virtual_paused("account", False)["run_state"] == "RUNNING"
            return
        if case == "admission":
            store._connection.execute(
                "DELETE FROM inspection_admissions WHERE account_id='account'"
            )
            store._connection.commit()
            with pytest.raises(ValueError, match="enable checks"):
                store.set_virtual_paused("account", False)
            assert store.virtual_account("account")["run_state"] == "PAUSED"
            return
    finally:
        store.close()
    if case.startswith("copied"):
        copied = root / "copied.db"
        shutil.copy2(path, copied)
        opener = PaperStore if case == "copied-normal" else PaperStore.open_readonly
        with pytest.raises(ValueError, match="rejects an inspection"):
            opener(copied)
    else:
        foreign = replace(
            permit, **{("release_sha256" if case == "release" else "protocol_sha256"): "d" * 64}
        )
        with pytest.raises(ValueError, match="another permit"):
            PaperStore(path, inspection_permit=execution_permit(foreign))


# Independent risk: PTE29; responsibility-level assertions.
@pytest.mark.parametrize(
    "stop",
    [
        "cancel",
        "timeout",
        "progress",
    ],
    ids=["PTE29-C01", "PTE29-C02", "PTE29-C03"],
)
def test_worker_control_retains_completed_artifacts_and_stops_writer(
    tmp_path, monkeypatch, stop, controller_environment
):
    """Real child lifecycles; the child's result is only a controller test fixture."""
    from paper_trading_engine import inspection_runner as runner

    workspace = tmp_path / ".tmp/strategy-inspection/control-test"
    workspace.mkdir(parents=True)
    environment = controller_environment
    # Environment authentication is outside the worker-control risk.
    monkeypatch.setattr(runner, "collect_inspection_environment", lambda _: environment)
    checkpoint = PteCheckpointExpectation(
        "empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0
    )
    scenarios = tuple(
        PteInspectionScenario(name, Decimal("1000"), (decision_input(),), (), (checkpoint,))
        for name in ("fast", "slow", "slow2")
    )
    coverage = tuple(
        PteCoverageRequirement(
            capability, CoverageRequirement.REQUIRED, ("fast",), "controller fixture"
        )
        for capability in PteInspectionCapability
    )
    protocol = PteInspectionProtocol(
        PteEnvironmentRequirement(
            environment.platform_build_sha256,
            environment.pte_contract_version,
            environment.srt_contract_version,
        ),
        scenarios,
        coverage,
        (),
    )
    request = PteReleaseInspectionRequest(
        "control-test",
        workspace / "repository",
        workspace,
        "S900-v1",
        "a" * 64,
        "b" * 64,
        (),
        (),
        protocol,
    )
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
    # Remain a live writer until the real controller terminates this process.
    deadline = time.monotonic() + 15
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError('controller did not stop the ready worker')
        time.sleep(0.01)
else:
    (root / 'result.json').write_text(json.dumps({'status':'PASS', 'code':'OK',
        'trace':[], 'capabilities':[]}), encoding='utf-8')
"""

    def start_child(command, **kwargs):
        if "--worker" not in command:
            return original_popen(command, **kwargs)
        process = original_popen(
            [sys.executable, "-c", child_script, command[-3], command[-2]], **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", start_child)
    fired = []
    completed = [0]
    elapsed = [0.0]
    marker = workspace / "scenarios/slow/restart/trace.jsonl"
    if stop == "timeout":
        # Replace only this module's clock reference. Real subprocess waits and
        # sleeps keep their clocks; elapsed time advances after prerequisite facts.
        monkeypatch.setattr(
            runner, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=runner.time.sleep)
        )

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
        if stop == "timeout" and value.completed >= 1 and marker.is_file():
            elapsed[0] = 3.0
        if stop == "progress" and value.completed == 1 and marker.is_file():
            raise RuntimeError("progress observer failed")

    outcome = runner.inspect_release(
        request,
        control=InspectionControl(
            max_workers=3,
            timeout_seconds=3 if stop == "timeout" else None,
            cancelled=cancel if stop in {"cancel", "invalid_cancel", "cancel_exception"} else None,
            on_progress=progress,
        ),
    )
    expected = (
        "CANCELLED"
        if stop == "cancel"
        else "RESOURCE_LIMIT"
        if stop == "timeout"
        else "EXECUTION_ERROR"
    )
    assert outcome.status is (
        PteInspectionStatus.INCOMPLETE
        if stop in {"cancel", "timeout"}
        else PteInspectionStatus.FAIL
    )
    assert (
        outcome.scenarios[0].case_id == "fast"
        and outcome.scenarios[0].status is PteInspectionStatus.PASS
    )
    assert outcome.scenarios[-1].code == expected
    assert len(processes) == 3 and all(process.poll() is not None for process in processes)
    assert all(process.returncode != 0 for process in processes[1:])
    if stop == "timeout":
        assert elapsed[0] == 3.0
    assert any(item.path == "scenarios/fast/restart/result.json" for item in outcome.artifacts)
    assert any(item.path == "scenarios/slow/restart/trace.jsonl" for item in outcome.artifacts)
    summary = json.loads((workspace / "pte-summary.json").read_text(encoding="utf-8"))
    assert summary["scenarios"][-1]["code"] == expected
    assert summary["effective_workers"] == 3


# Independent risk: PTE29; responsibility-level assertions.
def test_PTE29_C04_unstoppable_worker_cannot_publish_or_clean_evidence():
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
def concurrent_inspection(tmp_path, monkeypatch, controller_environment):
    """Exercise the public scheduler with real, deterministic fixture subprocesses."""
    from paper_trading_engine import inspection_runner as runner

    workspace = tmp_path / ".tmp/strategy-inspection/concurrency-test"
    workspace.mkdir(parents=True)
    environment = controller_environment
    # Environment authentication is outside the worker-control risk.
    monkeypatch.setattr(runner, "collect_inspection_environment", lambda _: environment)
    checkpoint = PteCheckpointExpectation(
        "empty", "LOAD", (), 0, Decimal("1000"), Decimal("0"), None, AccountHealth.OK, 0
    )
    scenarios = tuple(
        PteInspectionScenario(name, Decimal("1000"), (decision_input(),), (), (checkpoint,), ())
        for name in ("slow", "fast", "third")
    )
    coverage = tuple(
        PteCoverageRequirement(
            capability, CoverageRequirement.REQUIRED, ("slow",), "controller fixture"
        )
        for capability in PteInspectionCapability
    )
    protocol = PteInspectionProtocol(
        PteEnvironmentRequirement(
            environment.platform_build_sha256,
            environment.pte_contract_version,
            environment.srt_contract_version,
        ),
        scenarios,
        coverage,
        (),
    )
    request = PteReleaseInspectionRequest(
        "concurrency-test",
        workspace / "repository",
        workspace,
        "S900-v1",
        "a" * 64,
        "b" * 64,
        (),
        (),
        protocol,
    )
    monkeypatch.setattr(runner, "_inputs", lambda *args: {})
    original_popen = subprocess.Popen
    processes, behavior = [], {"failure": "none", "barrier_size": 1, "hold": False}
    script = """
import json, pathlib, sys, time
case, target, mode, capabilities, gate, participants, hold = sys.argv[1:]
root = pathlib.Path(target)
root.mkdir(parents=True)
start = time.perf_counter_ns()
deadline = time.monotonic() + 15
barrier = pathlib.Path(gate)
barrier.mkdir(exist_ok=True)
(barrier / (case + '-' + root.name + '.ready')).write_text('ready')
# No member can finish before all first-wave workers are demonstrably running.
# Later variants pass the already-open barrier, preserving scheduler ordering.
while len(list(barrier.glob('*.ready'))) < int(participants):
    if time.monotonic() >= deadline:
        raise TimeoutError('inspection workers did not reach the ready barrier')
    time.sleep(0.01)
while hold == 'True':
    if time.monotonic() >= deadline:
        raise TimeoutError('controller did not stop the held worker')
    time.sleep(0.01)
(root / 'timing.json').write_text(json.dumps([start, time.perf_counter_ns()]))
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
        process = original_popen(
            [
                sys.executable,
                "-c",
                script,
                command[-3],
                command[-2],
                behavior["failure"],
                json.dumps([x.value for x in PteInspectionCapability]),
                str(workspace / "worker-ready"),
                str(behavior["barrier_size"]),
                str(behavior["hold"]),
            ],
            **kwargs,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", start_child)
    return runner, request, processes, behavior


# Independent risk: PTE28; responsibility-level assertions.
@pytest.mark.parametrize(
    "workers",
    [
        2,
    ],
    ids=["PTE28-C01"],
)
def test_inspection_parallelism_is_bounded_ordered_and_recovery_paths_are_sequential(
    concurrent_inspection, workers
):
    runner, request, processes, behavior = concurrent_inspection
    behavior["barrier_size"] = min(workers, 3)
    progress = []
    result = runner.inspect_release(
        request, control=InspectionControl(max_workers=workers, on_progress=progress.append)
    )
    assert result.status is PteInspectionStatus.PASS
    assert [x.case_id for x in result.scenarios] == ["slow", "fast", "third"]
    assert all(x.covered for x in result.coverage)
    assert len(processes) == 3 and all(p.poll() is not None for p in processes)
    timings = {
        p.parent.relative_to(request.workspace).as_posix(): json.loads(p.read_text())
        for p in request.workspace.rglob("timing.json")
    }
    events = sorted(
        (instant, delta) for pair in timings.values() for instant, delta in zip(pair, (1, -1))
    )
    active = peak = 0
    for _, delta in events:
        active += delta
        peak = max(peak, active)
    assert peak == min(workers, 3)
    summary = json.loads((request.workspace / "pte-summary.json").read_text())
    assert summary["effective_workers"] == min(workers, 3)
    assert [x.completed for x in progress] == sorted(x.completed for x in progress)
    assert [x.case_id for x in result.scenarios] == [x["case_id"] for x in summary["scenarios"]]


# Independent risk: PTE28; responsibility-level assertions.


# Independent risk: PTE28; responsibility-level assertions.
def test_PTE28_C03_cancel_before_dispatch_reports_zero_workers(concurrent_inspection):
    runner, request, processes, _ = concurrent_inspection
    result = runner.inspect_release(
        request, control=InspectionControl(max_workers=8, cancelled=lambda: True)
    )
    assert result.status is PteInspectionStatus.INCOMPLETE
    assert processes == []
    assert (
        json.loads((request.workspace / "pte-summary.json").read_text())["effective_workers"] == 0
    )


# Independent risk: PTE29; responsibility-level assertions.


def test_PTE28_C02_same_scenario_recovery_steps_are_serial(concurrent_inspection):
    runner, request, processes, behavior = concurrent_inspection
    from dataclasses import replace

    scenario = replace(request.protocol.scenarios[0], restart_after=("LOAD",))
    protocol = replace(request.protocol, scenarios=(scenario,))
    request = replace(request, protocol=protocol)
    behavior["barrier_size"] = 1
    result = runner.inspect_release(request, control=InspectionControl(max_workers=2))
    assert result.status is PteInspectionStatus.PASS
    timings = {
        p.parent.name: json.loads(p.read_text()) for p in request.workspace.rglob("timing.json")
    }
    assert set(timings) == {"restart", "continuous"}
    assert timings["restart"][1] <= timings["continuous"][0]
    assert len(processes) == 2 and all(p.poll() is not None for p in processes)
