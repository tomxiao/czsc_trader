from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from paper_trading_engine.release_cli import (
    PTE_LOCAL_PROJECTS,
    PTE_SOURCE_DISTRIBUTIONS,
    _replace_directory,
    _run,
    _verify_strategy_runtime_wheel_boundary,
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
def test_release_directory_publish_retries_transient_windows_lock(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    destination = tmp_path / "release"
    staging.mkdir()
    (staging / "manifest.json").write_text("{}", encoding="utf-8")
    original = Path.replace
    attempts = 0

    def transient_lock(path, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("transient Windows lock")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", transient_lock)
    monkeypatch.setattr("paper_trading_engine.release_cli.time.sleep", lambda _delay: None)

    _replace_directory(staging, destination)

    assert attempts == 3
    assert (destination / "manifest.json").is_file()


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


def test_release_command_preserves_status_with_non_utf8_windows_output(tmp_path):
    completed = _run(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xb5')"],
        cwd=tmp_path,
    )

    assert completed.returncode == 0
    assert completed.stdout == "\ufffd"


def test_build_rejects_strategy_runtime_wheel_with_governed_assets(tmp_path):
    wheel = tmp_path / "czsc_strategy_runtime-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("strategy_runtime/strategies/s003_v1.py", b"strategy")

    with pytest.raises(RuntimeError, match="governed strategy assets"):
        _verify_strategy_runtime_wheel_boundary(tmp_path)


@pytest.mark.parametrize("account_count", [0, 1])
def test_release_verifies_configuration_and_bindings_without_preparing_data(
    tmp_path, monkeypatch, account_count,
):
    runtime = tmp_path / "runtime"
    release_root = runtime / "releases" / "v0.6.0"
    python = release_root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    release = SimpleNamespace(
        runtime_root=runtime,
        release_root=release_root,
    )
    monkeypatch.setattr(
        "paper_trading_engine.release_cli.load_release",
        lambda _runtime, _release_id: release,
    )
    monkeypatch.setattr(
        "paper_trading_engine.release_cli._require_database_compatibility",
        lambda _release, _database: 9,
    )
    calls = []

    def runner(command, **_kwargs):
        calls.append(list(command))
        output = {"accounts": account_count, "releases": ["S003-v1"] if account_count else []}
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(output), stderr="",
        )

    verified = verify_release_configuration(runtime, "v0.6.0", runner=runner)

    assert verified == {"accounts": account_count, "releases": ["S003-v1"] if account_count else []}
    assert "validate_account_binding" in calls[0][2]
    assert "prepare_account_data" not in calls[0][2]
    assert "current.json" not in calls[0][2]
    assert "PteRuntimeConfig.load(config/'pte.json')" in calls[0][2]
    assert calls[0][-1] == str(runtime / "shared" / "config")


def test_build_is_local_and_publish_installs_final_runtime(tmp_path, pte_frozen):
    repo = (tmp_path / "repo").resolve()
    build_root = (repo / ".build" / "pte").resolve()
    runtime = (tmp_path / "pte-runtime").resolve()
    _create_tagged_release_repo(repo, pte_frozen[0].strategy_root)
    runner = FakeReleaseRunner()
    fetch_sdist, pinned_runner = _source_build_fakes(runner)

    built_result = build_release(
        repo_root=repo,
        build_root=build_root,
        release_id="v0.4.1",
        source_python=Path("C:/Python/python.exe"),
        uv_executable=Path("C:/uv/uv.exe"),
        source_distribution_fetcher=fetch_sdist,
        runner=pinned_runner,
    )

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
    wheel_commands = [command for command in runner.commands if command[1] == "build"]
    assert len(wheel_commands) == len(PTE_LOCAL_PROJECTS) + len(PTE_SOURCE_DISTRIBUTIONS)
    assert sum(
        not str(command[-1]).endswith((".tar.gz", ".zip"))
        for command in wheel_commands
    ) == len(PTE_LOCAL_PROJECTS)
    wheelhouse = next(command for command in runner.commands if "--constraint" in command)
    assert wheelhouse[wheelhouse.index("--cache-dir") + 1] == str(
        repo / ".tmp" / "pte-release" / "pip"
    )
    assert wheelhouse[wheelhouse.index("--only-binary") + 1] == ":all:"

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


def test_publish_rejects_tampered_build_and_ignores_existing_service_host(tmp_path, pte_frozen):
    repo = (tmp_path / "repo").resolve()
    build_root = (repo / ".build" / "pte").resolve()
    runtime = (tmp_path / "pte-runtime").resolve()
    _create_tagged_release_repo(repo, pte_frozen[0].strategy_root)
    runner = FakeReleaseRunner()
    fetch_sdist, pinned_runner = _source_build_fakes(runner)
    build_release(
        repo_root=repo,
        build_root=build_root,
        release_id="v0.4.1",
        source_python=Path("C:/Python/python.exe"),
        uv_executable=Path("C:/uv/uv.exe"),
        source_distribution_fetcher=fetch_sdist,
        runner=pinned_runner,
    )
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
    tmp_path, pte_frozen,
):
    repo = (tmp_path / "repo").resolve()
    build_root = repo / ".build" / "pte"
    runtime = tmp_path / "runtime"
    _create_tagged_release_repo(repo, pte_frozen[0].strategy_root)
    runner = FakeReleaseRunner()
    fetch_sdist, pinned_runner = _source_build_fakes(runner)
    build_release(
        repo_root=repo, build_root=build_root, release_id="v0.4.1",
        uv_executable=Path("uv"), runner=pinned_runner,
        source_distribution_fetcher=fetch_sdist,
    )
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
