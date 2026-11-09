"""The selected PTE release owns runtime configuration and launch semantics."""

from types import SimpleNamespace

import pytest

from paper_trading_engine import cli


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


# Independent risk: PTE16; responsibility-level assertions.
@pytest.mark.parametrize("component", [
    "prefix",
], ids=['PTE16-C01'])
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


# Independent risk: PTE16; responsibility-level assertions.
def test_PTE16_C02_runtime_entry_requires_explicit_pte_config(tmp_path, monkeypatch):
    _installed_runtime(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        cli.build_parser().parse_args(["serve-runtime", "--runtime-root", str(tmp_path)])


# Independent risk: PTE16; responsibility-level assertions.
def test_PTE16_C03_runtime_entry_rejects_relative_root_before_loading_release(monkeypatch):
    def forbidden(_root):
        pytest.fail("relative runtime root must fail before release discovery")
    monkeypatch.setattr(cli, "resolve_active_release", forbidden)
    with pytest.raises(ValueError, match="must be absolute"):
        cli.build_parser().parse_args(["serve-runtime", "--runtime-root", "runtime"])
