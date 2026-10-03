from collections import deque
import json
import shutil
import sqlite3
import subprocess

import pytest

from paper_trading_engine.audit import AuditRecorder
from paper_trading_engine.cli import PortUnavailableError, _record_service_lifecycle, probe_port
from paper_trading_engine.service_config import ServiceConfig
from paper_trading_engine.runtime_release import (
    activate_release,
    file_sha256,
    load_release,
    resolve_active_release,
    rollback_release,
    tree_sha256,
)
from paper_trading_engine.store import (
    RUNTIME_DATABASE_COMPATIBLE_VERSIONS,
    RUNTIME_DATABASE_SCHEMA_VERSION,
    PaperStore,
    backup_runtime_database,
)
from paper_trading_engine.runtime_lock import RuntimeAlreadyOwnedError, RuntimeDatabaseLock
from paper_trading_engine.release_cli import deploy_previous_release, deploy_release
from paper_trading_engine.watchdog import Watchdog, rotate_log
from paper_trading_engine.windows_service import (
    _validate_service_host,
    build_bootstrap_source,
    find_pythonservice_executable,
    service_failure_command,
)
from paper_trading_engine.web_api import PteWebApi
from strategy_runtime.deployment import deployment_inventory
from strategy_runtime.errors import RuntimeCompatibilityError




class Process:
    def __init__(self, code=None): self.code, self.terminated = code, False
    def poll(self): return self.code
    def terminate(self): self.terminated, self.code = True, 0
    def wait(self, timeout=None): return self.code or 0
    def kill(self): self.code = -9


def create_release(strategy_root, runtime_root, release_id, marker):
    release = runtime_root / "releases" / release_id
    strategies = release / "strategies"
    shutil.copytree(strategy_root, strategies)
    (strategies / "registry.json").write_text(
        json.dumps({"schema_version": 1, "marker": marker}), encoding="utf-8",
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
        json.dumps(manifest), encoding="utf-8",
    )
    return release


def test_load_release_accepts_pre_deployment_inventory_snapshot(pte_frozen, tmp_path):
    runtime_root = (tmp_path / "runtime").resolve()
    release = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.1", "a")
    strategies = release / "strategies"
    shutil.rmtree(strategies / "deployments")
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("strategy_releases")
    manifest["strategy_snapshot_sha256"] = tree_sha256(strategies)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_release(runtime_root, "v0.4.1")

    assert loaded.release_id == "v0.4.1"


def test_load_release_requires_declared_deployment_inventory(pte_frozen, tmp_path):
    runtime_root = (tmp_path / "runtime").resolve()
    release = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.1", "a")
    strategies = release / "strategies"
    shutil.rmtree(strategies / "deployments")
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["strategy_snapshot_sha256"] = tree_sha256(strategies)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeCompatibilityError, match="deployment directory"):
        load_release(runtime_root, "v0.4.1")


def test_ft_pte06_watchdog_service_config_port_and_recovery(new_store, pte_frozen, tmp_path, monkeypatch):
    monkeypatch.setattr(
        'paper_trading_engine.runtime_release._installed_strategy_inventory', deployment_inventory,
    )
    audit_store = new_store(tmp_path / "lifecycle.db")
    _record_service_lifecycle(
        AuditRecorder(audit_store), "SERVICE_STARTED", "instance-1", port=8080,
    )
    lifecycle = audit_store.recent_events(1)[0]
    assert lifecycle["event_type"] == "SERVICE_STARTED"
    assert lifecycle["actor_type"] == "ENGINE"
    assert lifecycle["actor_id"] == "instance-1"
    audit_store.close()
    backup = backup_runtime_database(tmp_path / "lifecycle.db", retention=2)
    assert backup is not None and backup.is_file()
    reopened = PaperStore(backup)
    assert reopened.recent_events(1)[0]["event_type"] == "SERVICE_STARTED"
    reopened.close()

    child_log = tmp_path / "pte.log"
    child_log.write_bytes(b"x" * 32)
    rotate_log(child_log, max_bytes=16, backups=2)
    assert not child_log.exists()
    assert (tmp_path / "pte.log.1").read_bytes() == b"x" * 32

    owner = RuntimeDatabaseLock(tmp_path / "runtime.db").acquire()
    try:
        with pytest.raises(RuntimeAlreadyOwnedError, match="already owned"):
            RuntimeDatabaseLock(tmp_path / "runtime.db").acquire()
    finally:
        owner.release()
    second_owner = RuntimeDatabaseLock(tmp_path / "runtime.db").acquire()
    second_owner.release()

    runtime_root = (tmp_path / "runtime").resolve()
    (runtime_root / "shared" / "config").mkdir(parents=True)
    (runtime_root / "shared" / "config" / ".env").write_text(
        "TUSHARE_TOKEN=test", encoding="utf-8",
    )
    release = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.1", "a")
    activate_release(runtime_root, "v0.4.1")
    config = ServiceConfig(runtime_root=runtime_root)
    path = tmp_path / "service.json"
    config.save(path)
    assert ServiceConfig.load(path).serve_arguments() == [
        "serve", "--repo-root", str(release),
        "--database", str(runtime_root / "shared" / "state" / "runtime.db"),
        "--data-dir", str(runtime_root / "shared" / "data"),
        "--config-root", str(runtime_root / "shared" / "config"),
        "--release-manifest", str(release / "release-manifest.json"),
        "--host", "127.0.0.1", "--port", "8080",
    ]
    assert set(json.loads(path.read_text()).keys()) == {
        "schema_version", "runtime_root", "host", "port",
    }
    assert config.health_url == "http://127.0.0.1:8080/api/health"
    with pytest.raises(ValueError, match="localhost"):
        ServiceConfig(runtime_root=runtime_root, host="0.0.0.0")
    legacy = tmp_path / "legacy-service.json"
    legacy.write_text(
        json.dumps({"schema_version": 1, "repo_root": str(tmp_path.resolve())}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="repository-backed service config"):
        ServiceConfig.load(legacy)

    command = service_failure_command()
    assert command[0:3] == ["sc.exe", "failure", "CZSC-PTE-Watchdog"]

    processes, health, delays = [Process(), Process()], deque([False, False, False]), []
    watchdog = Watchdog(command=["pte", "serve"], working_directory=tmp_path,
                        health_url=config.health_url,
                        process_factory=lambda *_: processes.pop(0),
                        health_check=lambda *_: health.popleft(), sleep=delays.append)
    old = watchdog.start_child()
    watchdog.check_once()
    watchdog.check_once()
    watchdog.check_once()
    assert old.terminated and watchdog.child is not old and delays == [5.0]

    bootstrap = build_bootstrap_source(tmp_path / "host" / ".venv")
    assert repr(str(tmp_path / "host" / ".venv" / "Lib" / "site-packages")) in bootstrap
    assert "packages\\paper_trading_engine\\src" not in bootstrap

    import socket
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    try:
        with pytest.raises(PortUnavailableError):
            probe_port("127.0.0.1", occupied.getsockname()[1])
    finally:
        occupied.close()


def test_runtime_database_rejects_invalid_schema_identity(tmp_path):
    database = tmp_path / "invalid-schema.db"
    store = PaperStore(database)
    store.close()
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE settings SET value=? WHERE key='runtime_database_schema_version'",
        ("corrupt",),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="schema is invalid: 'corrupt'"):
        PaperStore(database)


def test_runtime_database_migrates_v1_decisions_to_supersession_schema(tmp_path):
    database = tmp_path / "schema-v1.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings(key,value) VALUES('runtime_database_schema_version','1');
        CREATE TABLE decisions (
            account_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            valid_session TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            PRIMARY KEY(account_id,decision_id)
        );
        CREATE UNIQUE INDEX uq_decisions_account_signal_date
        ON decisions(account_id,signal_date);
        """
    )
    connection.commit()
    connection.close()

    store = PaperStore(database)
    assert store.get_setting("runtime_database_schema_version") == str(RUNTIME_DATABASE_SCHEMA_VERSION)
    columns = {
        row["name"] for row in store._connection.execute("PRAGMA table_info(decisions)")
    }
    indexes = {
        row["name"] for row in store._connection.execute("PRAGMA index_list(decisions)")
    }
    assert {"status", "superseded_by", "superseded_at"}.issubset(columns)
    assert "uq_decisions_account_signal_date" not in indexes
    assert "uq_decisions_active_signal_date" in indexes
    store.close()


def test_watchdog_host_rejects_pte_and_rsch_runtime_dependencies(tmp_path, monkeypatch):
    runtime_root = (tmp_path / "runtime").resolve()
    host = runtime_root / "host" / "releases" / "v0.4.1" / ".venv"
    site_packages = host / "Lib" / "site-packages"
    (site_packages / "vectorbt").mkdir(parents=True)
    monkeypatch.setattr("paper_trading_engine.windows_service.sys.prefix", str(host))

    with pytest.raises(RuntimeError, match="runtime dependencies.*vectorbt"):
        _validate_service_host(runtime_root)


def test_pythonservice_executable_uses_pywin32_venv_layout(tmp_path):
    host = tmp_path / ".venv"
    executable = host / "Lib" / "site-packages" / "win32" / "pythonservice.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"service-host")

    assert find_pythonservice_executable(host) == executable

    with pytest.raises(RuntimeError, match="pythonservice.exe was not found"):
        find_pythonservice_executable(tmp_path / "missing")


def test_pte_release_activation_rollback_and_dynamic_watchdog(pte_frozen, tmp_path, monkeypatch):
    monkeypatch.setattr(
        'paper_trading_engine.runtime_release._installed_strategy_inventory', deployment_inventory,
    )
    runtime_root = (tmp_path / "runtime").resolve()
    (runtime_root / "shared" / "config").mkdir(parents=True)
    (runtime_root / "shared" / "config" / ".env").write_text(
        "TUSHARE_TOKEN=test", encoding="utf-8",
    )
    first = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.1", "a")
    second = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.2", "b")
    activate_release(runtime_root, "v0.4.1")
    config = ServiceConfig(runtime_root=runtime_root)
    assert config.pte_command()[0] == str(first / ".venv" / "Scripts" / "pte.exe")
    assert config.serve_arguments() == [
        "serve",
        "--repo-root", str(first),
        "--database", str(runtime_root / "shared" / "state" / "runtime.db"),
        "--data-dir", str(runtime_root / "shared" / "data"),
        "--config-root", str(runtime_root / "shared" / "config"),
        "--release-manifest", str(first / "release-manifest.json"),
        "--host", "127.0.0.1", "--port", "8080",
    ]

    launches = []
    processes = [Process(0), Process()]
    watchdog = Watchdog(
        command=config.pte_command,
        working_directory=config.working_directory,
        health_url=config.health_url,
        process_factory=lambda command, cwd, _log: (
            launches.append((command, cwd)) or processes.pop(0)
        ),
    )
    watchdog.start_child()
    activate_release(runtime_root, "v0.4.2")
    watchdog.check_once()
    assert launches[0][0][0] == str(first / ".venv" / "Scripts" / "pte.exe")
    assert launches[1][0][0] == str(second / ".venv" / "Scripts" / "pte.exe")
    assert launches[1][1] == runtime_root

    rollback_release(runtime_root)
    assert config.active_release().release_id == "v0.4.1"
    (first / "strategies" / "registry.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="strategy snapshot"):
        load_release(runtime_root, "v0.4.1")


def test_release_activation_rejects_rebuilt_active_release_identity(pte_frozen, tmp_path):
    runtime_root = (tmp_path / "runtime").resolve()
    (runtime_root / "shared" / "config").mkdir(parents=True)
    (runtime_root / "shared" / "config" / ".env").write_text(
        "TUSHARE_TOKEN=test", encoding="utf-8",
    )
    release = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.1", "a")
    activate_release(runtime_root, "v0.4.1")
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rebuilt"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="manifest identity differs"):
        activate_release(runtime_root, "v0.4.1")


def test_pte_release_rejects_editable_install(pte_frozen, tmp_path):
    runtime_root = (tmp_path / "runtime").resolve()
    release = create_release(pte_frozen[0].strategy_root, runtime_root, "v0.4.1", "a")
    site_packages = release / ".venv" / "Lib" / "site-packages"
    (site_packages / "__editable__.paper_trading_engine.pth").write_text(
        "D:/CodeBase/czsc_trader/packages/paper_trading_engine/src", encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="editable"):
        load_release(runtime_root, "v0.4.1")


def test_pte_deployment_verifies_release_and_rolls_back(pte_frozen, tmp_path):
    runtime_root = (tmp_path / "runtime").resolve()
    (runtime_root / "shared" / "config").mkdir(parents=True)
    (runtime_root / "shared" / "config" / ".env").write_text(
        "TUSHARE_TOKEN=test", encoding="utf-8",
    )
    for release_id, marker in (
        ("v0.4.1", "a"), ("v0.4.2", "b"), ("v0.4.3", "c"), ("v0.5.0", "d"),
    ):
        create_release(pte_frozen[0].strategy_root, runtime_root, release_id, marker)
    activate_release(runtime_root, "v0.4.1")
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout='{"accounts":1,"releases":["S900-v1"]}', stderr="",
        )

    result = deploy_release(
        runtime_root,
        "v0.4.2",
        runner=run,
        running_release=lambda _host, _port: "v0.4.2",
    )
    assert result == {
        "status": "READY",
        "release_id": "v0.4.2",
        "previous_release_id": "v0.4.1",
    }
    assert commands[-1][0].endswith("v0.4.1\\.venv\\Scripts\\pte.exe")

    rolled_back = deploy_previous_release(
        runtime_root,
        runner=run,
        running_release=lambda _host, _port: "v0.4.1",
    )
    assert rolled_back == {
        "status": "READY",
        "release_id": "v0.4.1",
        "previous_release_id": "v0.4.2",
    }
    assert resolve_active_release(runtime_root).release_id == "v0.4.1"
    deploy_release(
        runtime_root,
        "v0.4.2",
        runner=run,
        running_release=lambda _host, _port: "v0.4.2",
    )

    with pytest.raises(RuntimeError, match="was rolled back"):
        deploy_release(
            runtime_root,
            "v0.4.3",
            runner=run,
            running_release=lambda _host, _port: "v0.4.2",
        )
    assert resolve_active_release(runtime_root).release_id == "v0.4.2"

    incompatible_manifest = runtime_root / "releases" / "v0.5.0" / "release-manifest.json"
    incompatible = json.loads(incompatible_manifest.read_text(encoding="utf-8"))
    incompatible["database_schema"] = {"current": 99, "compatible": [99]}
    incompatible_manifest.write_text(json.dumps(incompatible), encoding="utf-8")
    with pytest.raises(RuntimeError, match=f"does not support database schema {RUNTIME_DATABASE_SCHEMA_VERSION}"):
        deploy_release(
            runtime_root,
            "v0.5.0",
            runner=run,
            running_release=lambda _host, _port: "v0.5.0",
        )
    assert resolve_active_release(runtime_root).release_id == "v0.4.2"


@pytest.mark.parametrize("reject_rollback", [False, True])
def test_deployment_binding_failure_never_activates_incompatible_release(
    pte_frozen, tmp_path, monkeypatch, reject_rollback,
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
        if release_id == ("v0.4.1" if reject_rollback else "v0.4.2"):
            raise RuntimeError("account release hash differs from frozen strategy")
        return {"accounts": 1, "releases": ["S900-v1"]}

    monkeypatch.setattr("paper_trading_engine.release_cli.verify_release_configuration", verify)

    def runner(command, **kwargs):
        restarted.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    with pytest.raises(RuntimeError, match="rollback blocked" if reject_rollback else "hash differs"):
        deploy_release(runtime, "v0.4.2", runner=runner, running_release=lambda *_: None)
    assert resolve_active_release(runtime).release_id == ("v0.4.2" if reject_rollback else "v0.4.1")
    assert len(restarted) == int(reject_rollback)
    assert verified == (["v0.4.2", "v0.4.1"] if reject_rollback else ["v0.4.2"])


def test_ft_pte06_business_health_exposes_stalled_scheduler(new_store, tmp_path):
    store = new_store(tmp_path / "health.db")
    store.set_setting("scheduler_heartbeat_at", "2026-09-01T00:00:00+00:00")

    class Channel:
        @staticmethod
        def status():
            return {
                "alerts": [], "scheduler_failures": [],
                "reconciliation_status": "OK", "account": None,
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


def test_business_health_treats_missing_heartbeat_and_channel_alert_as_degraded(new_store, tmp_path):
    store = new_store(tmp_path / "missing-heartbeat.db")

    class Channel:
        @staticmethod
        def status():
            return {
                "alerts": ["CHANNEL_CASH_MISMATCH"], "scheduler_failures": [],
                "reconciliation_status": "OK", "account": None,
            }

    class Operations:
        def __init__(self):
            self.store = store
            self.channel = Channel()
            self.virtual = object()

    status = PteWebApi(Operations()).system_status()
    assert status["watchdog_healthy"] is False
    assert status["futu_connection"] == "DEGRADED"
    assert "SCHEDULER_STALLED" in status["alerts"]
    store.close()
