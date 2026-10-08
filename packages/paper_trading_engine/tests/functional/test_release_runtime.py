from pathlib import Path
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from zipfile import ZipFile

import pytest

from paper_trading_engine.release_cli import (
    PTE_LOCAL_PROJECTS,
    PTE_SOURCE_DISTRIBUTIONS,
    build_release,
    load_built_release,
    publish_release,
    publish_watchdog_host,
    main,
    verify_release_configuration,
)
from paper_trading_engine.runtime_release import load_release
from paper_trading_engine.host_manifest import validate_watchdog_host_manifest
from czsc_trader.application.context import RepositoryContext


ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-lock regression")
def test_release_directory_publish_retries_transient_windows_lock(
    tmp_path, monkeypatch, built_release_copy,
):
    build_root, _ = built_release_copy
    runtime = tmp_path / "runtime"
    destination = runtime / "releases/v0.4.1"
    original = Path.replace
    attempts = 0

    def transient_lock(path, target):
        nonlocal attempts
        if target == destination:
            attempts += 1
            if attempts < 3:
                raise PermissionError("transient Windows lock")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", transient_lock)
    monkeypatch.setattr("paper_trading_engine.release_cli.time.sleep", lambda _delay: None)

    published = publish_release(
        build_root=build_root, runtime_root=runtime, release_id="v0.4.1",
        uv_executable=Path("C:/uv/uv.exe"), runner=FakeReleaseRunner(),
    )
    release = load_release(runtime, "v0.4.1")
    assert published["release"] == release.identity()
    assert release.pte_executable.is_file()
    assert published["active"] is False
    assert list(destination.parent.iterdir()) == [destination]


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments], cwd=repo, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _create_tagged_release_repo(repo: Path, strategy_root: Path, release_id: str = "v0.4.1") -> None:
    repo.mkdir()
    (repo / ".gitignore").write_text("build/\npackages/*/build/\n", encoding="utf-8")
    shutil.copy2(ROOT / ".gitattributes", repo / ".gitattributes")
    (repo / "pyproject.toml").write_text("[project]\nname='root'\n", encoding="utf-8")
    (repo / "src" / "czsc_trader").mkdir(parents=True)
    (repo / "src" / "czsc_trader" / "__init__.py").write_text("", encoding="utf-8")
    for project in PTE_LOCAL_PROJECTS:
        if project == ".":
            continue
        root = repo / project
        (root / "src" / root.name).mkdir(parents=True)
        (root / "src" / root.name / "__init__.py").write_text("", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            f"[project]\nname='{root.name}'\n", encoding="utf-8",
        )
    build_support = (
        repo / "packages" / "paper_trading_engine" / "src"
        / "paper_trading_engine" / "build_support"
    )
    build_support.mkdir()
    (build_support / "sitecustomize.py").write_text("", encoding="utf-8")
    shutil.copytree(strategy_root, repo / "strategies")
    evidence = repo / "experiments" / "S900" / "source.csv.gz"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"research-only")
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(
        repo, "-c", "user.name=PTE Test", "-c", "user.email=pte@example.invalid",
        "commit", "-m", "release source",
    )
    _git(
        repo, "-c", "user.name=PTE Test", "-c", "user.email=pte@example.invalid",
        "tag", "-a", release_id, "-m", release_id,
    )
    for project in PTE_LOCAL_PROJECTS:
        root = repo if project == "." else repo / project
        (root / "build").mkdir()
        (root / "build" / "stale.txt").write_text("stale", encoding="utf-8")


class FakeReleaseRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.wheel_index = 0

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append(command)
        if command[0] == "git":
            return subprocess.run(command, **kwargs)
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.3\n", stderr="")
        if command[1:5] == ["-m", "pip", "freeze", "--exclude-editable"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1:3] == ["pip", "freeze"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="paper-trading-engine==0.1.0\n", stderr="",
            )
        if command[1] == "build":
            assert not (Path(command[-1]) / "build").exists()
            destination = Path(command[command.index("--out-dir") + 1])
            destination.mkdir(parents=True, exist_ok=True)
            if str(command[-1]).endswith((".tar.gz", ".zip")):
                name = "futu_api-10.10.7008-py3-none-any.whl"
            else:
                prefixes = (
                    "czsc_dataflows", "czsc_strategy_manager", "czsc_strategy_runtime",
                    "czsc_trader_research", "paper_trading_engine",
                )
                name = f"{prefixes[self.wheel_index]}-0.1.0-py3-none-any.whl"
                self.wheel_index += 1
            wheel = destination / name
            if name.startswith("czsc_strategy_runtime-"):
                with ZipFile(wheel, "w") as archive:
                    archive.writestr("strategy_runtime/__init__.py", b"")
            else:
                wheel.write_bytes(b"wheel")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1:4] == ["-m", "pip", "wheel"] and "--constraint" in command:
            Path(command[command.index("--wheel-dir") + 1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "venv":
            venv = Path(command[2])
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            (scripts / "python.exe").write_bytes(b"python")
            (venv / "Lib" / "site-packages").mkdir(parents=True)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1:3] == ["pip", "install"]:
            scripts = Path(command[command.index("--python") + 1]).parent
            for name in ("pte.exe", "czsc-trader.exe", "pte-watchdog.exe"):
                (scripts / name).write_bytes(b"launcher")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "-c" or command[1:4] == ["-I", "-B", "-c"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)


def _source_build_fakes(runner):
    def fetch_sdist(distribution, version, destination):
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / f"{distribution.replace('-', '_')}-{version}.tar.gz"
        archive.write_bytes(b"sdist")
        return archive

    def pinned_runner(command, **kwargs):
        completed = runner(command, **kwargs)
        if list(command)[1:5] == ["-m", "pip", "freeze", "--exclude-editable"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="futu-api==10.10.7008\n", stderr="",
            )
        return completed

    return fetch_sdist, pinned_runner


@pytest.mark.parametrize("returncode", [0, 7], ids=["success", "failure"])
def test_release_command_preserves_status_with_non_utf8_windows_output(
    tmp_path, built_release_copy, returncode,
):
    build_root, _ = built_release_copy
    runtime = tmp_path / "runtime"
    delegate = FakeReleaseRunner()
    results = []

    def runner(command, **kwargs):
        if command[1] == "venv":
            completed = subprocess.run([
                sys.executable, "-B", "-c",
                f"import sys; sys.stdout.buffer.write(b'\\xb5'); sys.exit({returncode})",
            ], **kwargs)
            results.append(completed)
            if not completed.returncode:
                delegate(command, **kwargs)
            return completed
        return delegate(command, **kwargs)

    kwargs = dict(build_root=build_root, runtime_root=runtime, release_id="v0.4.1",
                  uv_executable=Path("C:/uv/uv.exe"), runner=runner)
    if returncode:
        with pytest.raises(RuntimeError, match="command failed.*"):
            publish_release(**kwargs)
        assert not (runtime / "releases/v0.4.1").exists()
    else:
        result = publish_release(**kwargs)
        assert result["release"] == load_release(runtime, "v0.4.1").identity()
    assert len(results) == 1
    assert results[0].returncode == returncode


def test_build_rejects_strategy_runtime_wheel_with_governed_assets(tmp_path, pte_frozen):
    repo = tmp_path / "repo"
    _create_tagged_release_repo(repo, pte_frozen[0].strategy_root)

    class GovernedAssetRunner(FakeReleaseRunner):
        def __call__(self, command, **kwargs):
            completed = super().__call__(command, **kwargs)
            if command[1] == "build" and str(command[-1]).endswith("strategy_runtime"):
                artifacts = Path(command[command.index("--out-dir") + 1])
                wheel = next(artifacts.glob("czsc_strategy_runtime-*.whl"))
                with ZipFile(wheel, "a") as archive:
                    archive.writestr("strategy_runtime/strategies/s003_v1.py", b"strategy")
            return completed

    fetch_sdist, runner = _source_build_fakes(GovernedAssetRunner())
    build_root = repo / ".build/pte"
    with pytest.raises(RuntimeError, match="governed strategy assets"):
        build_release(
            repo_root=repo, build_root=build_root, release_id="v0.4.1",
            uv_executable=Path("C:/uv/uv.exe"),
            source_distribution_fetcher=fetch_sdist, runner=runner,
        )
    assert not (build_root / "releases/v0.4.1").exists()
    assert not list(build_root.rglob("build-manifest.json"))


@pytest.fixture
def release_verification_runtime(pte_frozen, new_store, tmp_path):
    from paper_trading_engine.runtime_config import PteRuntimeConfig
    from test_watchdog_service import create_release

    context, version = pte_frozen
    runtime = tmp_path / "runtime"
    create_release(context.strategy_root, runtime, "v0.6.0", "a")
    shared = runtime / "shared"
    data = shared / "data"
    data.mkdir(parents=True)
    (data / "existing-input.json").write_text('{"identity":"unchanged"}', encoding="utf-8")
    config = shared / "config"
    PteRuntimeConfig(data_space=Path("market")).save(config / "pte.json")
    (config / ".env").write_text("TUSHARE_TOKEN=synthetic-offline-token\n", encoding="utf-8")
    store = new_store(shared / "state/runtime.db")
    yield runtime, version, store
    store.close()


@pytest.mark.parametrize("binding", ["empty", "valid", "legacy_v3", "wrong_hash", "wrong_cutoff", "invalid_config"])
def test_release_verifies_configuration_and_bindings_without_preparing_data(
    release_verification_runtime, binding,
):
    runtime, version, store = release_verification_runtime
    if binding != "empty":
        store.create_virtual_account(
            "verified", "Verified account", version.release_id, version.release_hash, 100000,
            strategy_id=version.strategy_id, strategy_version=version.version,
            release_hash="0" * 64 if binding == "wrong_hash" else version.release_hash,
            strategy_name_snapshot="Synthetic", qualification_snapshot="PAPER_READY",
            selection_data_cutoff="2020-01-01" if binding == "wrong_cutoff" else version.selection_data_cutoff,
        )
    if binding == "invalid_config":
        (runtime / "shared/config/pte.json").write_text('{"schema_version":999}', encoding="utf-8")
    store.close()
    database = runtime / "shared/state/runtime.db"
    if binding == "legacy_v3":
        # Verification precedes the production migration and must remain read-only.
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER decision_content_immutable")
            connection.execute("DROP TRIGGER retired_instance_irreversible")
            connection.execute("UPDATE virtual_accounts SET legacy_status='RUNNING',legacy_paused=1")
            connection.execute("ALTER TABLE virtual_accounts DROP COLUMN run_state")
            connection.execute("ALTER TABLE virtual_accounts RENAME COLUMN legacy_status TO status")
            connection.execute("ALTER TABLE virtual_accounts RENAME COLUMN legacy_paused TO paused")
            connection.execute("ALTER TABLE decisions RENAME COLUMN legacy_status TO status")
            connection.execute("DROP TABLE decision_state_events")
            connection.execute("DROP TABLE decision_adoptions")
            connection.execute("UPDATE settings SET value='3' WHERE key='runtime_database_schema_version'")
    database_before = database.read_bytes()
    data = runtime / "shared/data"
    data_before = {path.relative_to(data).as_posix(): path.read_bytes()
                   for path in data.rglob("*") if path.is_file()}
    results = []
    # Execute the product's verification script unchanged after installing only
    # forbidden-side-effect guards. Authentication, runtime description and the
    # account hash/cutoff checks all run against the real frozen package and DB.
    guard = (
        "from dataflows import Dataflows\n"
        "from paper_trading_engine.srt_advice_client import SrtAdviceClient\n"
        "def forbidden_preparation(*args,**kwargs):\n"
        "    raise AssertionError('release verification must not prepare data')\n"
        "Dataflows.prepare=forbidden_preparation\n"
        "SrtAdviceClient.prepare_account_data=forbidden_preparation\n"
    )

    def runner(command, **kwargs):
        # The isolated release has stub launchers; use the repository interpreter
        # solely as the process transport, while keeping the selected release's
        # script, working directory and all verification inputs intact.
        assert command[1] == "-c"
        completed = subprocess.run(
            [sys.executable, "-B", "-c", guard + command[2], *command[3:]], **kwargs,
        )
        results.append(completed)
        return completed

    if binding in {"wrong_hash", "wrong_cutoff", "invalid_config"}:
        message = {
            "wrong_hash": "account release hash differs",
            "wrong_cutoff": "selection cutoff differs",
            "invalid_config": "unsupported PTE runtime config schema",
        }[binding]
        with pytest.raises(RuntimeError, match=message):
            verify_release_configuration(runtime, "v0.6.0", runner=runner)
        assert results[0].returncode != 0
    else:
        verified = verify_release_configuration(runtime, "v0.6.0", runner=runner)
        expected = {"accounts": 0, "releases": []} if binding == "empty" else {
            "accounts": 1, "releases": [version.release_id],
        }
        assert verified == expected
        assert results[0].returncode == 0
        assert json.loads(results[0].stdout) == expected
    assert len(results) == 1
    assert database.read_bytes() == database_before
    assert {path.relative_to(data).as_posix(): path.read_bytes()
            for path in data.rglob("*") if path.is_file()} == data_before


@pytest.fixture(scope="module")
def release_build_cache():
    return {}


@pytest.fixture
def built_release_copy(request, frozen_seed_root, release_build_cache, tmp_path):
    """Run the tagged build once; every publication owns an independent bundle."""
    if not release_build_cache:
        repo = frozen_seed_root / "release-repo"
        build_root = repo / ".build" / "pte"
        _create_tagged_release_repo(repo, request.getfixturevalue("pte_frozen")[0].strategy_root)
        runner = FakeReleaseRunner()
        fetch_sdist, pinned_runner = _source_build_fakes(runner)
        result = build_release(
            repo_root=repo, build_root=build_root, release_id="v0.4.1",
            source_python=Path("C:/Python/python.exe"), uv_executable=Path("C:/uv/uv.exe"),
            source_distribution_fetcher=fetch_sdist, runner=pinned_runner,
        )
        release_build_cache.update(repo=repo, root=build_root, result=result, commands=runner.commands)
    build_root = tmp_path / "repo" / ".build" / "pte"
    shutil.copytree(release_build_cache["root"], build_root)
    return build_root, release_build_cache


def test_build_is_local_and_publish_installs_final_runtime(tmp_path, built_release_copy):
    build_root, build = built_release_copy
    repo = build_root.parent.parent
    runtime = (tmp_path / "pte-runtime").resolve()
    built_result = build["result"]
    runner = FakeReleaseRunner()

    built = load_built_release(build_root, "v0.4.1")
    assert built_result["build"]["release_id"] == "v0.4.1"
    assert built_result["artifact_count"] == (
        len(PTE_LOCAL_PROJECTS) + len(PTE_SOURCE_DISTRIBUTIONS)
    )
    assert not (built.release_root / ".venv").exists()
    assert not (built.release_root / "runtime-root.json").exists()
    assert not (built.release_root / ".source-archives").exists()
    assert not runtime.exists()
    assert not (built.release_root / "experiments").exists()
    wheel_commands = [command for command in build["commands"] if command[1] == "build"]
    assert len(wheel_commands) == len(PTE_LOCAL_PROJECTS) + len(PTE_SOURCE_DISTRIBUTIONS)
    assert sum(
        not str(command[-1]).endswith((".tar.gz", ".zip"))
        for command in wheel_commands
    ) == len(PTE_LOCAL_PROJECTS)
    wheelhouse = next(command for command in build["commands"] if "--constraint" in command)
    assert wheelhouse[wheelhouse.index("--cache-dir") + 1] == str(
        build["repo"] / ".tmp" / "pte-release" / "pip"
    )
    assert wheelhouse[wheelhouse.index("--only-binary") + 1] == ":all:"

    artifact = next((build_root / "releases" / "v0.4.1" / "artifacts").glob("*.whl"))
    original = artifact.read_bytes()
    artifact.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="artifact differs"):
        publish_release(
            build_root=build_root,
            runtime_root=runtime,
            release_id="v0.4.1",
            source_python=Path("C:/Python/python.exe"),
            uv_executable=Path("C:/uv/uv.exe"),
            runner=runner,
        )
    artifact.write_bytes(original)

    assert not runtime.exists()

    published = publish_release(
        build_root=build_root,
        runtime_root=runtime,
        release_id="v0.4.1",
        source_python=Path("C:/Python/python.exe"),
        uv_executable=Path("C:/uv/uv.exe"),
        runner=runner,
    )

    release = load_release(runtime, "v0.4.1")
    context = RepositoryContext.discover(
        release.release_root, explicit_root=release.release_root,
    )
    assert published["release"]["release_id"] == "v0.4.1"
    assert published["builder"] == "uv 0.11.3"
    assert release.pte_executable.is_file()
    assert context.strategy_root == release.release_root / "strategies"
    assert (release.release_root / "build-manifest.json").is_file()
    assert (release.release_root / "environment.lock").read_text(encoding="utf-8") == (
        "paper-trading-engine==0.1.0\n"
    )
    assert not (runtime / "host").exists()
    venv_targets = [Path(command[2]) for command in runner.commands if command[1] == "venv"]
    assert venv_targets == [
        runtime / "releases" / "v0.4.1" / ".venv",
    ]
    installs = [command for command in runner.commands if command[1:3] == ["pip", "install"]]
    assert all(
        command[command.index("--cache-dir") + 1]
        == str(repo / ".tmp" / "pte-release" / "uv")
        for command in installs
    )
    assert all("--refresh" in command for command in installs)
    assert not (runtime / "cache").exists()
    assert any(
        "--no-deps" in command and "czsc-trader-research==0.1.0" in command
        for command in installs
    )
    assert all("vectorbt" not in " ".join(command).lower() for command in installs)


    runtime = (tmp_path / "existing-host-runtime").resolve()
    existing_host = runtime / "host" / "releases" / "v0.4.1"
    existing_host.mkdir(parents=True)
    marker = existing_host / "untouched.txt"
    marker.write_bytes(b"existing host")
    publish_release(
        build_root=build_root,
        runtime_root=runtime,
        release_id="v0.4.1",
        source_python=Path("C:/Python/python.exe"),
        uv_executable=Path("C:/uv/uv.exe"),
        runner=runner,
    )
    assert (runtime / "releases" / "v0.4.1").exists()
    assert list(existing_host.iterdir()) == [marker]
    assert marker.read_bytes() == b"existing host"


def test_publish_watchdog_host_has_independent_identity_and_rejects_tampering(
    tmp_path, built_release_copy,
):
    build_root, _ = built_release_copy
    runtime = tmp_path / "runtime"
    runner = FakeReleaseRunner()
    kwargs = dict(
        build_root=build_root, runtime_root=runtime, release_id="v0.4.1",
        host_version="v1.0.0", uv_executable=Path("uv"), runner=runner,
    )
    result = publish_watchdog_host(**kwargs)
    host = runtime / "host" / "releases" / "v1.0.0"
    assert result["host_version"] == "v1.0.0"
    assert result["source_release_id"] == "v0.4.1"
    assert result["active"] is False
    assert not (runtime / "releases").exists()
    assert not (runtime / "shared").exists()
    assert not (runtime / "host" / "releases" / "v0.4.1").exists()
    manifest = validate_watchdog_host_manifest(host)
    assert manifest["kind"] == "wdg-host"
    assert manifest["host_version"] != manifest["source_release_id"]
    installs = [c for c in runner.commands if c[1:3] == ["pip", "install"]]
    assert any("--no-deps" in c and "paper-trading-engine==0.1.0" in c for c in installs)
    assert not any("czsc-strategy-runtime" in " ".join(c) for c in installs)
    with pytest.raises(RuntimeError, match="host already exists"):
        publish_watchdog_host(**kwargs)

    def broken_host_runner(command, **options):
        if command[1:4] == ["-I", "-B", "-c"]:
            return subprocess.CompletedProcess(
                command, 1, stdout="", stderr="host import failure",
            )
        return runner(command, **options)

    with pytest.raises(RuntimeError, match="host import failure"):
        publish_watchdog_host(**{
            **kwargs, "host_version": "v2.0.0", "runner": broken_host_runner,
        })
    assert not (runtime / "host" / "releases" / "v2.0.0").exists()
    artifact = next((host / "artifacts").glob("*.whl"))
    original = artifact.read_bytes()
    artifact.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="artifact differs"):
        validate_watchdog_host_manifest(host)
    artifact.write_bytes(original)
    source = host / "build-manifest.json"
    original_source = source.read_bytes()
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="source build differs"):
        validate_watchdog_host_manifest(host)
    source.write_bytes(original_source)
    path = host / "host-manifest.json"
    manifest["schema_version"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity differ"):
        validate_watchdog_host_manifest(host)
    manifest["schema_version"] = 1
    manifest["host_version"] = "v9.0.0"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity differ"):
        validate_watchdog_host_manifest(host)
    with pytest.raises(RuntimeError, match="invalid WDG host version"):
        publish_watchdog_host(**{**kwargs, "host_version": "../v1.0.0"})
    source_artifact = next((build_root / "releases" / "v0.4.1" / "artifacts").glob("*.whl"))
    source_artifact.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="artifact differs"):
        publish_watchdog_host(**{**kwargs, "host_version": "v1.1.0"})
    assert not (runtime / "host" / "releases" / "v1.1.0").exists()


def test_publish_host_cli_requires_explicit_version_and_dispatches(tmp_path, monkeypatch):
    calls = []

    def publish(**kwargs):
        calls.append(kwargs)
        return {"host_version": kwargs["host_version"]}

    monkeypatch.setattr("paper_trading_engine.release_cli.publish_watchdog_host", publish)
    argv = [
        "publish-host", "--build-root", str(tmp_path / "build"),
        "--runtime-root", str(tmp_path / "runtime"), "--release", "v0.6.0",
    ]
    with pytest.raises(SystemExit):
        main(argv)
    assert not calls
    assert main([*argv, "--host-version", "v1.0.0"]) == 0
    assert calls[0]["host_version"] == "v1.0.0"
    assert calls[0]["release_id"] == "v0.6.0"
