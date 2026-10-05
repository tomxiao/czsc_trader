"""Independent processes obey the SM registry write lock."""
import subprocess
import sys

import pytest
from strategy_manager import StrategyRegistry
from strategy_manager.errors import RegistryError


def test_registry_lock_excludes_other_process_and_releases_after_failure(tmp_path):
    registry = StrategyRegistry(tmp_path)
    destination = tmp_path / "value.json"
    script = '''
from pathlib import Path
import sys
from strategy_manager import StrategyRegistry
from strategy_manager.errors import RegistryError
registry = StrategyRegistry(sys.argv[1])
try:
    registry._atomic_write(Path(sys.argv[1]) / "other.json", "other")
except RegistryError as exc:
    assert "write lock" in str(exc)
else:
    raise AssertionError("competing writer acquired lock")
'''
    with pytest.raises(RuntimeError, match="abort"):
        with registry._write_lock.hold():
            registry._atomic_write(destination, "first")
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script, str(tmp_path)],
                capture_output=True, text=True, timeout=15,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            assert not (tmp_path / "other.json").exists()
            raise RuntimeError("abort")
    reopened = StrategyRegistry(tmp_path)
    reopened._atomic_write(destination, "second", b"first")
    with pytest.raises(RegistryError, match="concurrent change"):
        reopened._atomic_write(destination, "stale", b"first")
    assert destination.read_text() == "second"
