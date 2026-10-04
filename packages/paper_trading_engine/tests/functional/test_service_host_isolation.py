import json
from pathlib import Path
import subprocess
import sys

import pytest

from paper_trading_engine.service_config import ServiceConfig
from paper_trading_engine.runtime_release import file_sha256


def test_service_host_launches_without_trading_dependencies_or_pte_config(tmp_path):
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
from pathlib import Path
from paper_trading_engine.service_config import ServiceConfig
import paper_trading_engine.watchdog
if sys.platform == 'win32':
    import paper_trading_engine.windows_service
command = ServiceConfig(Path(sys.argv[2])).pte_command()
assert command[1:] == ['serve-runtime', '--runtime-root', sys.argv[2]]
assert 'paper_trading_engine.runtime_config' not in sys.modules
'''
    root = _selection(tmp_path)
    # WDG does not interpret even a future PTE configuration schema.
    (root / 'shared/config/pte.json').write_text('{"schema_version":999}', encoding='utf-8')
    subprocess.run([sys.executable, '-I', '-B', '-c', script, str(source), str(root)], check=True)


def _selection(root):
    config = root / 'shared/config'
    config.mkdir(parents=True)
    release = root / 'releases/v9.8.7'
    executable = release / '.venv' / ('Scripts/pte.exe' if sys.platform == 'win32' else 'bin/pte')
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'launch')
    manifest = release / 'release-manifest.json'
    manifest.write_text('{"schema_version":999,"future_manifest":true}', encoding='utf-8')
    (config / 'active-release.json').write_text(json.dumps({
        'schema_version': 1, 'release_id': 'v9.8.7', 'manifest_sha256': file_sha256(manifest),
    }), encoding='utf-8')
    return root


@pytest.mark.parametrize('damage', ['hash', 'path', 'missing_executable', 'selection_schema'])
def test_watchdog_rejects_invalid_launch_selection(tmp_path, damage):
    root = _selection(tmp_path)
    active_path = root / 'shared/config/active-release.json'
    active = json.loads(active_path.read_text())
    if damage == 'hash':
        active['manifest_sha256'] = '0' * 64
    elif damage == 'path':
        active['release_id'] = '../outside'
    elif damage == 'selection_schema':
        active['schema_version'] = True
    else:
        executable = Path(ServiceConfig(root).pte_command()[0])
        executable.unlink()
    active_path.write_text(json.dumps(active), encoding='utf-8')
    with pytest.raises(ValueError):
        ServiceConfig(root).pte_command()
