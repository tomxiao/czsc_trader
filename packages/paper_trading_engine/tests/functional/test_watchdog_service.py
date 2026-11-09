from collections import deque
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from paper_trading_engine.runtime_release import (
    activate_release,
    file_sha256,
    resolve_active_release,
    tree_sha256,
)
from execution_channels.futu.store import (
    RUNTIME_DATABASE_COMPATIBLE_VERSIONS,
    RUNTIME_DATABASE_SCHEMA_VERSION,
)
from paper_trading_engine.release_cli import deploy_release
from paper_trading_engine.web_api import PteWebApi
from strategy_runtime.deployment import deployment_inventory


class Process:
    def __init__(self, code=None):
        self.code, self.terminated = code, False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated, self.code = True, 0

    def wait(self, timeout=None):
        return self.code or 0

    def kill(self):
        self.code = -9


# Independent risk: PTE23; responsibility-level assertions.


# Independent risk: PTE22; responsibility-level assertions.
@pytest.mark.parametrize(
    "healthy",
    [
        False,
    ],
    ids=["PTE22-C03"],
)
def test_deployment_requires_healthy_scheduler_before_accepting_release(
    pte_frozen,
    tmp_path,
    monkeypatch,
    healthy,
):
    from contextlib import nullcontext
    from paper_trading_engine import release_cli

    body = {"runtime": "RUNNING", "watchdog_healthy": healthy, "release": {"release_id": "v0.6.6"}}
    bodies = deque(
        [
            body,
            {"runtime": "RUNNING", "watchdog_healthy": True, "release": {"release_id": "v0.6.5"}},
        ]
    )

    def response(*_args, **_kwargs):
        return nullcontext(
            SimpleNamespace(status=200, read=lambda: json.dumps(bodies.popleft()).encode())
        )

    monkeypatch.setattr(release_cli, "urlopen", response)
    runtime = (tmp_path / "runtime").resolve()
    (runtime / "shared/config").mkdir(parents=True)
    (runtime / "shared/config/.env").write_text("TUSHARE_TOKEN=test", encoding="utf-8")
    for version, marker in (("v0.6.5", "a"), ("v0.6.6", "b")):
        create_release(pte_frozen[0].strategy_root, runtime, version, marker)
    activate_release(runtime, "v0.6.5")
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout='{"accounts":0,"releases":[]}', stderr=""
        )

    if healthy:
        assert deploy_release(runtime, "v0.6.6", runner=runner)["status"] == "READY"
        assert resolve_active_release(runtime).release_id == "v0.6.6"
        assert sum("restart" in command for command in commands) == 1
    else:
        with pytest.raises(RuntimeError, match="health check failed"):
            deploy_release(runtime, "v0.6.6", runner=runner)
        assert resolve_active_release(runtime).release_id == "v0.6.5"
        assert sum("restart" in command for command in commands) == 2


# Independent risk: PTE23; responsibility-level assertions.
@pytest.mark.parametrize(
    "becomes_healthy",
    [
        False,
    ],
    ids=["PTE23-C02"],
)
def test_restart_waits_for_new_healthy_runtime(
    new_store, tmp_path, monkeypatch, becomes_healthy, capsys
):
    from paper_trading_engine import cli
    from contextlib import nullcontext

    database = tmp_path / "restart.db"
    store = new_store(database)
    store.set_setting("control_token", "test-token")
    store.close()
    responses = deque(
        [
            (200, {"instance_id": "old"}),
            (202, {"instance_id": "old"}),
            (200, {"instance_id": "old", "runtime": "RUNNING", "watchdog_healthy": True}),
            (200, {"instance_id": "old", "runtime": "RUNNING", "watchdog_healthy": True}),
        ]
    )
    if becomes_healthy:
        responses.append(
            (
                200,
                {
                    "instance_id": "new",
                    "runtime": "RUNNING",
                    "watchdog_healthy": True,
                },
            )
        )
    calls = []

    def read(request, **kwargs):
        calls.append(request)
        if not isinstance(request, str):
            assert request.get_method() == "POST"
            assert request.get_header("X-pte-control-token") == "test-token"
        status, payload = (
            responses.popleft()
            if responses
            else (
                200,
                {
                    "instance_id": "old",
                    "runtime": "RUNNING",
                    "watchdog_healthy": True,
                },
            )
        )
        return nullcontext(
            SimpleNamespace(status=status, read=lambda: json.dumps(payload).encode())
        )

    clock = iter(range(100))
    monkeypatch.setattr(cli, "urlopen", read)
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    argv = [
        "control",
        "restart",
        "--repo-root",
        str(tmp_path),
        "--database",
        str(database),
        "--wait",
        "5",
    ]
    if becomes_healthy:
        assert cli.main(argv) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "PASS" and payload["command"] == "pte.control.restart"
        assert payload["result"] == {
            "status": "READY",
            "old_instance_id": "old",
            "new_instance_id": "new",
        }
        assert len(calls) == 5
    else:
        assert cli.main(argv) == 5
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "FAIL" and payload["command"] == "pte.control"
        assert "did not become healthy" in payload["error"]["message"]


def create_release(strategy_root, runtime_root, release_id, marker):
    release = runtime_root / "releases" / release_id
    strategies = release / "strategies"
    shutil.copytree(strategy_root, strategies)
    (strategies / "registry.json").write_text(
        json.dumps({"schema_version": 1, "marker": marker}),
        encoding="utf-8",
    )
    runtime_file = release / "runtime.txt"
    runtime_file.write_text(marker, encoding="utf-8")
    scripts = release / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    for name in ("pte.exe", "czsc-trader.exe"):
        (scripts / name).write_bytes(b"launcher")
    (release / ".venv" / "Lib" / "site-packages").mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "git_commit": marker * 40,
        "python_version": "3.12.10",
        "database_schema": {
            "current": RUNTIME_DATABASE_SCHEMA_VERSION,
            "compatible": list(RUNTIME_DATABASE_COMPATIBLE_VERSIONS),
        },
        "strategy_snapshot_sha256": tree_sha256(strategies),
        "strategy_releases": deployment_inventory(strategies),
        "runtime_files": {"runtime.txt": file_sha256(runtime_file)},
    }
    (release / "release-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return release


# Independent risk: PTE22; responsibility-level assertions.


# Independent risk: PTE22; responsibility-level assertions.


# Independent risk: PTE22; responsibility-level assertions.
@pytest.mark.parametrize(
    "reject_rollback",
    [
        False,
        True,
    ],
    ids=["PTE22-C02", "PTE22-C04"],
)
def test_deployment_binding_failure_never_activates_incompatible_release(
    pte_frozen,
    tmp_path,
    monkeypatch,
    reject_rollback,
):
    runtime = tmp_path / "runtime"
    (runtime / "shared/config").mkdir(parents=True)
    (runtime / "shared/config/.env").write_text("TUSHARE_TOKEN=test", encoding="utf-8")
    for release_id, marker in (("v0.4.1", "a"), ("v0.4.2", "b")):
        create_release(pte_frozen[0].strategy_root, runtime, release_id, marker)
    activate_release(runtime, "v0.4.1")
    verified = []
    restarted = []

    def verify(_root, release_id, **kwargs):
        verified.append(release_id)
        if reject_rollback and release_id == "v0.4.1":
            from paper_trading_engine.runtime_release import load_release

            load_release(_root, release_id)
        elif not reject_rollback and release_id == "v0.4.2":
            raise RuntimeError("account release hash differs from frozen strategy")
        return {"accounts": 1, "releases": ["S900-v1"]}

    monkeypatch.setattr("paper_trading_engine.release_cli.verify_release_configuration", verify)

    def runner(command, **kwargs):
        restarted.append(command)
        if reject_rollback:
            (runtime / "releases/v0.4.1/runtime.txt").write_text("tampered", encoding="utf8")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    with pytest.raises(
        RuntimeError, match="rollback blocked" if reject_rollback else "hash differs"
    ):
        deploy_release(runtime, "v0.4.2", runner=runner, running_release=lambda *_: None)
    assert resolve_active_release(runtime).release_id == ("v0.4.2" if reject_rollback else "v0.4.1")
    assert len(restarted) == int(reject_rollback)
    assert verified == (["v0.4.2", "v0.4.1"] if reject_rollback else ["v0.4.2"])


# Independent risk: PTE23; responsibility-level assertions.
def test_PTE23_C03_ft_pte06_business_health_exposes_stalled_scheduler(memory_store):
    store = memory_store()
    store.set_setting("scheduler_heartbeat_at", "2026-09-01T00:00:00+00:00")

    class Channel:
        @staticmethod
        def status():
            return {
                "alerts": [],
                "scheduler_failures": [],
                "reconciliation_status": "OK",
                "account": None,
            }

    class Operations:
        def __init__(self):
            self.store = store
            self.channel = Channel()
            self.virtual = object()

    status = PteWebApi(Operations()).system_status()
    assert status["runtime"] == "RUNNING"
    assert status["watchdog_healthy"] is False
    assert "SCHEDULER_STALLED" in status["alerts"]
    assert PteWebApi(Operations()).health() == {
        "runtime": "RUNNING",
        "watchdog_healthy": False,
        "scheduler_heartbeat_at": "2026-09-01T00:00:00+00:00",
        "release": {},
    }
    store.close()
