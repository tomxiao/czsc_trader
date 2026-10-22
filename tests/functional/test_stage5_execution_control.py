"""A blocked calculation must stop before its owning API returns."""
import multiprocessing
import pickle
import time
from types import SimpleNamespace

import pytest
from dataflows import DataSpace
from pathlib import Path
from strategy_manager.freeze_contracts import InspectionReason
from strategy_runtime.inspection import InspectionControl, InspectionStage
from czsc_trader.application.inspection_execution import Controller, Interrupted, equivalence_jobs


def blocked_calculation(connection, payload):
    time.sleep(30)


@pytest.mark.parametrize("stop", ["timeout", "cancel", "callback"])
def test_blocked_workers_are_quiescent_before_control_failure(tmp_path, monkeypatch, stop):
    from czsc_trader.application import inspection_replay
    monkeypatch.setattr(inspection_replay, "compute", blocked_calculation)
    began = time.monotonic()
    calls = []
    def cancel():
        calls.append(True)
        return len(calls) >= 4
    def progress(_):
        raise RuntimeError("observer failed")
    control = InspectionControl(timeout_seconds=.25 if stop == "timeout" else 10,
        cancelled=cancel if stop == "cancel" else None,
        on_progress=progress if stop == "callback" else None)
    controller = Controller("control-test", control, tmp_path)
    controller.stage = InspectionStage.EQUIVALENCE
    if stop == "callback":
        # Let the first poll start a child; the next poll emits its callback.
        controller.last_progress = -9.95
    request = SimpleNamespace(replays=(None,), protocol=SimpleNamespace(float_tolerance=0),
        research=SimpleNamespace(data=SimpleNamespace(binding=SimpleNamespace(base_dir=tmp_path, space=DataSpace(Path("data"))))))
    before = {p.pid for p in multiprocessing.active_children()}
    outcome = equivalence_jobs(request, None, None, tmp_path, controller)
    assert outcome.completed == ()
    assert outcome.interruption.quiescent
    assert outcome.interruption.reason is {"timeout": InspectionReason.RESOURCE_LIMIT,
        "cancel": InspectionReason.CANCELLED, "callback": InspectionReason.EXECUTION_ERROR}[stop]
    assert {p.pid for p in multiprocessing.active_children()} == before
    assert time.monotonic() - began < 10


def first_complete_then_block(connection, payload):
    base, _, _, _, replay, _, _ = pickle.loads(payload)
    if replay == "completed":
        connection.send((True, {"completed": True}))
        connection.close()
    else:
        (base / "blocked-started").touch()
        time.sleep(30)


def test_cancel_preserves_completed_work_and_stops_remaining_worker(tmp_path, monkeypatch):
    from czsc_trader.application import inspection_replay
    monkeypatch.setattr(inspection_replay, "compute", first_complete_then_block)
    controller = Controller("partial", InspectionControl(timeout_seconds=15,
        cancelled=lambda: (tmp_path / "blocked-started").exists()), tmp_path)
    request = SimpleNamespace(replays=("completed", "blocked"), protocol=SimpleNamespace(float_tolerance=0),
        research=SimpleNamespace(data=SimpleNamespace(binding=SimpleNamespace(base_dir=tmp_path, space=DataSpace(Path("data"))))))
    before = {p.pid for p in multiprocessing.active_children()}
    outcome = equivalence_jobs(request, None, None, tmp_path, controller)
    assert outcome.completed == ((0, True, {"completed": True}),)
    assert outcome.interruption.reason is InspectionReason.CANCELLED
    assert outcome.interruption.quiescent
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_cancel_callback_must_return_boolean(tmp_path):
    controller = Controller("bad-callback", InspectionControl(cancelled=lambda: "yes"), tmp_path)
    with pytest.raises(Interrupted, match="must return bool") as caught:
        controller.tick()
    assert caught.value.reason is InspectionReason.EXECUTION_ERROR
