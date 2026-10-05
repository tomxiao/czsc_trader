"""Public registry writes exclude other processes and preserve failed commits."""
import json
import subprocess
import sys

import pytest
from strategy_manager import StrategyFamily, StrategyRegistry
from strategy_manager.errors import RegistryError


def _family(strategy_id="S900"):
    return StrategyFamily.from_dict({
        "schema_version": 2, "strategy_id": strategy_id, "name": f"Family {strategy_id}",
        "scope": ["588080.SH"], "research_intent": {"objective": "original"},
        "research_state": "RESEARCHING", "created_at": "2026-10-01T10:00:00+08:00",
        "created_by": "tester", "updated_at": "2026-10-01T10:00:00+08:00",
    })


_WRITER = '''
import json
import sys
from strategy_manager import StrategyFamily, StrategyRegistry
from strategy_manager.errors import RegistryError
registry = StrategyRegistry(sys.argv[1])
operation, payload, expected = sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
try:
    if operation == "create":
        registry.create_family(StrategyFamily.from_dict(payload), actor="child", reason="create")
    else:
        registry.update_family("S900", research_intent=payload, actor="child", reason="update")
except RegistryError as exc:
    assert expected == "blocked", str(exc)
    assert "write lock" in str(exc)
else:
    assert expected == "success", "competing writer acquired lock"
'''


def _writer(root, operation, payload, expected):
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _WRITER, str(root), operation,
         json.dumps(payload), expected],
        capture_output=True, text=True, timeout=15,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _business_files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.suffix in {".json", ".jsonl"}}


@pytest.mark.parametrize("operation", ["create", "update"])
def test_public_registry_writers_exclude_competing_process_and_release_after_failure(
    tmp_path, monkeypatch, operation,
):
    from strategy_manager import registry as registry_module

    registry = StrategyRegistry(tmp_path)
    family = _family()
    if operation == "update":
        registry.create_family(family, actor="tester", reason="initial")
    before = _business_files(tmp_path)
    payload = family.to_dict() if operation == "create" else {"objective": "child update"}
    real_replace = registry_module._replace_file
    interrupted = False

    def fail_at_family_publication(source, target):
        nonlocal interrupted
        if target.name == "family.json" and not interrupted:
            interrupted = True
            # The public operation owns the lock here; another real process
            # must be refused before creating or changing any business files.
            _writer(tmp_path, operation, payload, "blocked")
            assert _business_files(tmp_path) == before
            raise RuntimeError("abort publication")
        return real_replace(source, target)

    with monkeypatch.context() as fault:
        fault.setattr(registry_module, "_replace_file", fail_at_family_publication)
        with pytest.raises(RuntimeError, match="abort publication"):
            if operation == "create":
                registry.create_family(family, actor="tester", reason="interrupted")
            else:
                registry.update_family("S900", research_intent={"objective": "parent update"},
                                       actor="tester", reason="interrupted")
    assert interrupted
    assert _business_files(tmp_path) == before
    # A fresh process performs the real write after the failure; release is
    # proved independently of the interrupted instance's reentrant lock state.
    _writer(tmp_path, operation, payload, "success")
    reopened = StrategyRegistry(tmp_path)
    assert reopened.get_family("S900").research_intent == (
        family.research_intent if operation == "create" else payload
    )
    assert reopened.validate_all()["strategies"] == 1
    events = reopened.lifecycle_events("S900")
    assert [event.event_type for event in events] == (
        ["RESEARCH_BATCH_CREATED"] if operation == "create"
        else ["RESEARCH_BATCH_CREATED", "RESEARCH_INTENT_UPDATED"]
    )


def test_public_family_registration_preserves_external_change_before_registry_commit(tmp_path, monkeypatch):
    from strategy_manager import registry as registry_module

    registry = StrategyRegistry(tmp_path)
    original = _family("S899")
    registry.create_family(original, actor="tester", reason="initial")
    before = _business_files(tmp_path)
    external = json.loads(registry.registry_path.read_text(encoding="utf-8"))
    external["strategies"][0]["aliases"] = ["external-update"]
    external_bytes = (json.dumps(external, sort_keys=True) + "\n").encode("utf-8")
    real_replace = registry_module._replace_file
    injected = False

    def change_registry_after_family_write(source, target):
        nonlocal injected
        real_replace(source, target)
        if target == tmp_path / "S900/family.json" and not injected:
            injected = True
            # Simulate an external file change, not a cooperating registry
            # writer: public writers already obey the process lock.
            registry.registry_path.write_bytes(external_bytes)

    monkeypatch.setattr(registry_module, "_replace_file", change_registry_after_family_write)
    with pytest.raises(RegistryError, match="concurrent change"):
        registry.create_family(_family(), actor="tester", reason="stale registration")
    assert injected
    assert not (tmp_path / "S900").exists()
    assert _business_files(tmp_path) == {**before, "registry.json": external_bytes}
    assert registry.resolve_family("external-update") == original
    updated = registry.update_family("S899", research_intent={"objective": "after rejection"},
                                     actor="tester", reason="retry")
    assert registry.get_family("S899") == updated
    assert registry.resolve_family("external-update") == updated
    assert len(registry.lifecycle_events("S899")) == 2
