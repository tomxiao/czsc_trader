import json
from pathlib import Path
import subprocess
import sys

import pytest

from paper_trading_engine.runtime_release import _installed_strategy_inventory


def test_service_host_imports_without_trading_dependencies():
    source = Path(__file__).resolve().parents[2] / 'src'
    script = '''
import importlib.abc, sys
class NoTradingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'strategy_runtime', 'strategy_manager', 'dataflows', 'numpy', 'pandas', 'futu',
        }:
            raise AssertionError('service host loaded ' + fullname)
sys.meta_path.insert(0, NoTradingImports())
sys.path.insert(0, sys.argv[1])
import paper_trading_engine.service_config
import paper_trading_engine.watchdog
if sys.platform == 'win32':
    import paper_trading_engine.windows_service
'''
    subprocess.run([sys.executable, '-I', '-B', '-c', script, str(source)], check=True)


@pytest.mark.parametrize('payload', [{'S900-v1': 'hash'}, [], {'S900-v1': 123}])
def test_host_inventory_uses_target_interpreter_and_validates_result(tmp_path, monkeypatch, payload):
    strategies = tmp_path / 'release' / 'strategies'
    def run(command, **kwargs):
        assert Path(command[0]).is_relative_to(strategies.parent / '.venv')
        assert command[1:4] == ['-I', '-B', '-c']
        assert command[-1] == str(strategies)
        assert kwargs['check'] and kwargs['timeout'] == 60
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), '')
    monkeypatch.setattr(subprocess, 'run', run)
    if payload == {'S900-v1': 'hash'}:
        assert _installed_strategy_inventory(strategies) == payload
    else:
        with pytest.raises(RuntimeError, match='invalid strategy inventory'):
            _installed_strategy_inventory(strategies)


def test_host_inventory_propagates_runtime_validation_failure(tmp_path, monkeypatch):
    def run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr='package hash mismatch')
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        _installed_strategy_inventory(tmp_path / 'strategies')
