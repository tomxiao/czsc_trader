"""The selected PTE release owns runtime configuration and launch semantics."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dataflows import DataSpace
from paper_trading_engine import cli
from paper_trading_engine.runtime_config import PteRuntimeConfig


def _installed_runtime(tmp_path, monkeypatch):
    release_root = tmp_path / "releases/v1.2.3"
    release = SimpleNamespace(
        release_root=release_root,
        manifest_path=release_root / "release-manifest.json",
    )
    monkeypatch.setattr(cli, "resolve_active_release", lambda root: release)
    monkeypatch.setattr(cli.sys, "prefix", str(release_root / ".venv"))
    monkeypatch.setattr(cli, "__file__", str(
        release_root / ".venv/Lib/site-packages/paper_trading_engine/cli.py",
    ))
    monkeypatch.setattr(cli, "load_manifest_identity", lambda path: {
        "mode": "PTE", "release_id": "v1.2.3", "manifest": str(path),
    })
    return release


def test_runtime_entry_maps_selected_release_and_pte_configuration(tmp_path, monkeypatch):
    release = _installed_runtime(tmp_path, monkeypatch)
    config = PteRuntimeConfig(port=8123, data_space=Path("cn/market"))
    path = config.save(
        tmp_path / "shared/config/pte.json",
    )
    assert PteRuntimeConfig.load(path) == config
    args = cli.build_parser().parse_args(["serve-runtime", "--runtime-root", str(tmp_path)])
    assert args.action == "serve"
    assert args.repo_root == release.release_root
    assert args.database == tmp_path / "shared/state/runtime.db"
    assert args.data_dir == tmp_path / "shared/data"
    assert args.config_root == tmp_path / "shared/config"
    assert args.data_space == DataSpace(Path("cn/market"))
    assert (args.host, args.port) == ("127.0.0.1", 8123)
    assert args.runtime_identity["release_id"] == "v1.2.3"
    assert args.runtime_identity["manifest"] == str(release.manifest_path)


@pytest.mark.parametrize("component", ["prefix", "module"])
def test_runtime_entry_rejects_running_code_outside_active_release(
    tmp_path, monkeypatch, component,
):
    _installed_runtime(tmp_path, monkeypatch)
    if component == "prefix":
        monkeypatch.setattr(cli.sys, "prefix", str(tmp_path / "releases/v1.2.2/.venv"))
    else:
        monkeypatch.setattr(cli, "__file__", str(tmp_path / "source/cli.py"))
    with pytest.raises(RuntimeError, match="does not belong to the active release"):
        cli.build_parser().parse_args(["serve-runtime", "--runtime-root", str(tmp_path)])


def test_runtime_entry_requires_explicit_pte_config(tmp_path, monkeypatch):
    _installed_runtime(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        cli.build_parser().parse_args(["serve-runtime", "--runtime-root", str(tmp_path)])


def test_runtime_entry_rejects_relative_root_before_loading_release(monkeypatch):
    def forbidden(_root):
        pytest.fail("relative runtime root must fail before release discovery")
    monkeypatch.setattr(cli, "resolve_active_release", forbidden)
    with pytest.raises(ValueError, match="must be absolute"):
        cli.build_parser().parse_args(["serve-runtime", "--runtime-root", "runtime"])


@pytest.mark.parametrize("port", [True, "8080", 0, 65536])
def test_runtime_config_rejects_invalid_port(port):
    with pytest.raises((TypeError, ValueError)):
        PteRuntimeConfig(port=port)


@pytest.mark.parametrize("payload", [
    [], {}, {"schema_version": True}, {"schema_version": 2, "runtime_root": "runtime"},
    {"schema_version": 1, "host": "127.0.0.1", "port": 8080},
    {"schema_version": 1, "host": "127.0.0.1", "port": 8080,
     "data_space": "market", "runtime_root": "old-host-field"},
])
def test_runtime_config_rejects_missing_or_foreign_contract(tmp_path, payload):
    path = tmp_path / "pte.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    expected = ("unsupported PTE runtime config schema"
                if isinstance(payload, dict) and payload.get("schema_version") == 2 else None)
    with pytest.raises(ValueError, match=expected):
        PteRuntimeConfig.load(path)
