"""Native frozen snapshots and read-only CN/US release admission."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from paper_trading_engine.release_cli import (
    _verify_strategy_snapshot, _verify_runtime_configuration, verify_release_configuration,
)
from paper_trading_engine.runtime_config import PteRuntimeConfig
from strategy_runtime.deployment import deployment_inventory, load_strategy_deployment
from strategy_runtime import RuntimeCompatibilityError
from test_formal_v4_runtime import formal_v4 as formal_v4
from test_watchdog_service import create_release


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope='module')
def release_snapshot(frozen_seed_root):
    """Copy real current/history packages once, without unrelated upgrade archives.

    The complete registered-tree acceptance below still checks the repository.
    Snapshot corruption/preflight cases own private copies of every published
    package and receipt; historical revision archives are not release inputs.
    """
    source = ROOT / 'strategies'
    seed = frozen_seed_root / 'release-snapshot'
    shutil.copytree(source, seed,
        ignore=lambda directory, names: ('revisions',) if Path(directory) == source else ())
    original = _files(seed)
    yield seed
    assert _files(seed) == original, 'release test changed its shared snapshot'


@pytest.mark.release_acceptance
def test_native_registered_snapshot_authenticates_without_changing_qualification():
    from strategy_manager import StrategyRegistry
    root = ROOT / "strategies"
    files = {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
             for p in root.rglob("*") if p.is_file()}
    registry = StrategyRegistry(root)
    before = {f"{p.parent.parent.name}-{p.stem}": registry.current_qualification(p.parent.parent.name, p.stem)
              for p in root.glob("S*/versions/v*.json")}
    assert _verify_strategy_snapshot(root) == deployment_inventory(root)
    inventory = deployment_inventory(root)
    for reference in ('S002-v1', 'S003-v1'):
        assert reference not in inventory
        assert (root / 'deployments/history' / f'{reference}.json').is_file()
        with pytest.raises(RuntimeCompatibilityError, match='retained history'):
            load_strategy_deployment(root, reference)
    assert {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()} == files
    assert {key: registry.current_qualification(*key.rsplit("-", 1)) for key in before} == before


@pytest.mark.release_acceptance
def test_native_snapshot_includes_undeployed_packages_and_rejects_tampering(tmp_path, release_snapshot):
    strategies = tmp_path / "snapshot"
    shutil.copytree(release_snapshot, strategies)
    # Deliberately withhold one deployment in the private copy. Build validation
    # still authenticates its frozen contents without manufacturing approval.
    withheld = sorted((strategies / "deployments").glob("S*-v*.json"))[-1]
    family, version = withheld.stem.rsplit("-", 1)
    withheld.unlink()
    assert _verify_strategy_snapshot(strategies) == deployment_inventory(strategies)
    assert not withheld.exists()
    source = next((strategies / family / "releases" / version / "src").rglob("*.py"))
    source.write_bytes(source.read_bytes() + b"\n# invalid frozen closure\n")
    with pytest.raises(Exception, match="differs|hash"):
        _verify_strategy_snapshot(strategies)


@pytest.mark.release_acceptance
@pytest.mark.parametrize('reference', ['S002-v1', 'S003-v1'])
@pytest.mark.parametrize('damage', ['source', 'receipt', 'package_binding', 'duplicate'])
def test_retained_history_blocks_snapshot_corruption(tmp_path, release_snapshot, reference, damage):
    """History is retained and authenticated, never ignored to admit a snapshot."""
    from strategy_runtime import canonical_sha256

    strategies = tmp_path / 'snapshot'
    shutil.copytree(release_snapshot, strategies)
    path = strategies / 'deployments/history' / f'{reference}.json'
    if damage == 'source':
        family, version = reference.rsplit('-', 1)
        source = next((strategies / family / 'releases' / version / 'src').rglob('*.py'))
        source.write_bytes(source.read_bytes() + b'\n# corrupt retained source\n')
        reason = 'file differs'
    elif damage == 'duplicate':
        shutil.copyfile(path, strategies / 'deployments' / path.name)
        with pytest.raises(RuntimeCompatibilityError, match='retained history'):
            load_strategy_deployment(strategies, reference)
        reason = 'both current releases and history'
    else:
        receipt = json.loads(path.read_text(encoding='utf-8'))
        receipt['package_hash'] = '0' * 64
        reason = 'receipt hash mismatch'
        if damage == 'package_binding':
            receipt.pop('receipt_hash')
            receipt['receipt_hash'] = canonical_sha256(receipt)
            reason = 'differs from its release package'
        path.write_text(json.dumps(receipt), encoding='utf-8')
    with pytest.raises(RuntimeCompatibilityError, match=reason):
        _verify_strategy_snapshot(strategies)


def _files(root):
    # SQLite readers update WAL shared-memory lock slots even in query_only
    # mode. The durable database/WAL and every data/config file remain fixed.
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.name.endswith("-shm")}


@pytest.mark.release_acceptance
@pytest.mark.parametrize('reference', ['S002-v1', 'S003-v1'])
@pytest.mark.parametrize('state', ['PAUSED', 'RETIRING', 'RUNNING'])
def test_history_account_preflight_is_readonly_and_never_admits_running_strategy(tmp_path, release_snapshot, monkeypatch, reference, state):
    from execution_channels.futu.store import PaperStore

    shutil.copytree(release_snapshot, tmp_path / 'strategies')
    data, config = tmp_path / 'data', tmp_path / 'config'
    data.mkdir()
    PteRuntimeConfig(data_space=Path('market')).save(config / 'pte.json')
    (config / '.env').write_text('TUSHARE_TOKEN=synthetic-offline-token\n', encoding='utf-8')
    family, version = reference.rsplit('-', 1)
    frozen = json.loads((tmp_path / 'strategies' / family / 'versions' / f'{version}.json').read_text(encoding='utf-8'))
    database = tmp_path / 'runtime.db'
    store = PaperStore(database)
    try:
        store.create_virtual_account('old', 'old', reference, frozen['release_hash'], 1000,
            strategy_id=family, strategy_version=version, release_hash=frozen['release_hash'],
            strategy_name_snapshot='history', qualification_snapshot='PAPER_READY',
            selection_data_cutoff=frozen['selection_data_cutoff'])
        with store._connection:
            store._connection.execute("UPDATE virtual_accounts SET run_state=? WHERE account_id='old'", (state,))
    finally:
        store.close()

    def forbidden(*args, **kwargs):
        pytest.fail('history preflight must not load a strategy, prepare data or connect to a broker')
    monkeypatch.setattr('paper_trading_engine.srt_advice_client.SrtAdviceClient.validate_account_binding', forbidden)
    monkeypatch.setattr('paper_trading_engine.formal_v4_advice.FormalV4AdviceClient._account_release', forbidden)
    monkeypatch.setattr('dataflows.Dataflows.__init__', forbidden)
    monkeypatch.setattr('execution_channels.futu.futu_gateway.FutuGateway.__init__', forbidden)
    # Keep SQLite's read-side WAL files present before taking the baseline, as
    # with a running host. The durable DB and WAL bytes must remain unchanged.
    with closing(PaperStore.open_readonly(database)):
        before = _files(tmp_path)
        if state == 'RUNNING':
            with pytest.raises(RuntimeError, match='retained history requires a paused or retiring account'):
                _verify_runtime_configuration(tmp_path, data, database, config)
        else:
            assert _verify_runtime_configuration(tmp_path, data, database, config) == {
                'accounts': 1, 'releases': [reference]}
        assert _files(tmp_path) == before


@pytest.mark.release_acceptance
@pytest.mark.parametrize('case', ['valid', 'missing', 'snapshot', 'inventory', 'package', 'receipt', 'running'])
def test_retained_source_preserves_exact_old_binding(tmp_path, release_snapshot, monkeypatch, case):
    from execution_channels.futu.store import PaperStore
    from paper_trading_engine.runtime_release import tree_sha256, file_sha256
    from strategy_runtime import canonical_sha256

    target = tmp_path / 'releases/v0.7.4'
    shutil.copytree(release_snapshot, target / 'strategies')
    source = tmp_path / 'releases/v0.6.21'
    shutil.copytree(release_snapshot / 'S003', source / 'strategies/S003')
    version_path = source / 'strategies/S003/versions/v1.json'
    frozen = json.loads(version_path.read_text(encoding='utf-8'))
    frozen['change_summary'] += ' (prior installed fixture)'
    frozen.pop('release_hash')
    frozen['release_hash'] = canonical_sha256(frozen)
    version_path.write_text(json.dumps(frozen), encoding='utf-8')
    package_root = source / 'strategies/S003/releases/v1'
    binding_path = package_root / 'runtime_binding.json'
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    binding['release_hash'] = frozen['release_hash']
    binding_path.write_text(json.dumps(binding), encoding='utf-8')
    package_path = package_root / 'release_manifest.json'
    package = json.loads(package_path.read_text(encoding='utf-8'))
    package['strategy_version_hash'] = frozen['release_hash']
    package['files']['runtime_binding.json'] = file_sha256(binding_path)
    package.pop('package_hash')
    package['package_hash'] = canonical_sha256(package)
    package_path.write_text(json.dumps(package), encoding='utf-8')
    receipt = json.loads((release_snapshot / 'deployments/history/S003-v1.json').read_text(encoding='utf-8'))
    receipt['strategy_version_hash'], receipt['package_hash'] = frozen['release_hash'], package['package_hash']
    receipt.pop('receipt_hash')
    receipt['receipt_hash'] = canonical_sha256(receipt)
    receipts = source / 'strategies/deployments'
    receipts.mkdir()
    (receipts / 'S003-v1.json').write_text(json.dumps(receipt), encoding='utf-8')
    manifest = {'schema_version': 1, 'release_id': source.name, 'git_commit': 'a' * 40,
                'strategy_snapshot_sha256': tree_sha256(source / 'strategies'),
                'strategy_releases': {'S003-v1': package['package_hash']}}
    if case == 'missing':
        frozen['release_hash'] = '0' * 64
    elif case == 'snapshot':
        manifest['strategy_snapshot_sha256'] = '0' * 64
    elif case == 'inventory':
        manifest['strategy_releases']['S003-v1'] = '0' * 64
    elif case == 'package':
        binding_path.write_text('{}', encoding='utf-8')
        manifest['strategy_snapshot_sha256'] = tree_sha256(source / 'strategies')
    elif case == 'receipt':
        receipt['receipt_hash'] = '0' * 64
        (receipts / 'S003-v1.json').write_text(json.dumps(receipt), encoding='utf-8')
        manifest['strategy_snapshot_sha256'] = tree_sha256(source / 'strategies')
    (source / 'release-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    data, config = tmp_path / 'shared/data', tmp_path / 'shared/config'
    data.mkdir(parents=True)
    PteRuntimeConfig().save(config / 'pte.json')
    (config / '.env').write_text('TUSHARE_TOKEN=synthetic-offline-token\n', encoding='utf-8')
    database = tmp_path / 'shared/runtime.db'
    with closing(PaperStore(database)) as store:
        store.create_virtual_account('old', 'old', 'v1', frozen['release_hash'], 1000,
            strategy_id='S003', strategy_version='v1', release_hash=frozen['release_hash'],
            strategy_name_snapshot='history', qualification_snapshot='PAPER_READY',
            selection_data_cutoff=frozen['selection_data_cutoff'])
        if case == 'running':
            store.set_virtual_paused('old', False)

    def forbidden(*args, **kwargs):
        pytest.fail('retained source verification must not load old strategy contracts')
    monkeypatch.setattr('paper_trading_engine.srt_advice_client.SrtAdviceClient.validate_account_binding', forbidden)
    monkeypatch.setattr('paper_trading_engine.formal_v4_advice.FormalV4AdviceClient._account_release', forbidden)
    with closing(PaperStore.open_readonly(database)) as store:
        before = _files(tmp_path)
        if case == 'valid':
            assert _verify_runtime_configuration(target, data, database, config) == {
                'accounts': 1, 'releases': ['S003-v1']}
            assert store.virtual_account('old')['release_hash'] == frozen['release_hash']
        else:
            message = {'missing': 'exact retained account package is unavailable',
                       'snapshot': 'source snapshot differs', 'inventory': 'installed inventory',
                       'package': 'file differs', 'receipt': 'receipt hash mismatch',
                       'running': 'paused or retiring'}[case]
            with pytest.raises((RuntimeError, RuntimeCompatibilityError), match=message):
                _verify_runtime_configuration(target, data, database, config)
        assert _files(tmp_path) == before


def test_native_release_preflight_uses_qualified_inputs_and_never_prepares(formal_v4, tmp_path, monkeypatch):
    client, _, root_store, _, _, _ = formal_v4
    client.register_recipe("formal", client.inputs("formal"))
    runtime = tmp_path / "production-copy"
    release = create_release(client.repo_root / "strategies", runtime, "v0.6.22", "a")
    shared = runtime / "shared"
    data = shared / "data"
    shutil.copytree(client.data_dir, data)
    config = shared / "config"
    PteRuntimeConfig(data_space=Path("market")).save(config / "pte.json")
    (config / ".env").write_text("TUSHARE_TOKEN=synthetic-offline-token\n", encoding="utf-8")
    database = shared / "state/runtime.db"
    database.parent.mkdir()
    with sqlite3.connect(database) as destination:
        root_store._connection.backup(destination)
        frozen = json.loads((release / "strategies/S999/versions/v1.json").read_text(encoding="utf-8"))
        destination.execute("UPDATE virtual_accounts SET selection_data_cutoff=? WHERE account_id='formal'",
                            (frozen["selection_data_cutoff"],))
    expected = {"accounts": 1, "releases": ["S999-v1"]}
    before = _files(shared)
    guard = (
        "from dataflows import Dataflows\n"
        "from paper_trading_engine.formal_v4_advice import FormalV4AdviceClient\n"
        "from execution_channels.futu.futu_gateway import FutuGateway\n"
        "def forbidden(*args,**kwargs): raise AssertionError('preflight must remain read-only and offline')\n"
        "Dataflows.__init__=forbidden\n"
        "FormalV4AdviceClient.prepare_interval=forbidden\n"
        "FutuGateway.__init__=forbidden\n"
    )
    def runner(command, **kwargs):
        return subprocess.run([sys.executable, "-B", "-c", guard + command[2], *command[3:]], **kwargs)
    assert verify_release_configuration(runtime, "v0.6.22", runner=runner) == expected
    assert _files(shared) == before

    def verify():
        original = _files(shared)
        try:
            return _verify_runtime_configuration(release, data, database, config)
        finally:
            assert _files(shared) == original

    # Do not construct a data space, invoke a provider, or connect a broker in
    # the direct failure checks either.
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must remain read-only and offline")
    monkeypatch.setattr("dataflows.Dataflows.__init__", forbidden)
    monkeypatch.setattr("paper_trading_engine.formal_v4_advice.FormalV4AdviceClient.prepare_interval", forbidden)
    monkeypatch.setattr("execution_channels.futu.futu_gateway.FutuGateway.__init__", forbidden)
    input_path = data / "v4-inputs/formal.json"
    original = input_path.read_bytes()
    malformed = json.loads(original)
    malformed["release_hash"] = "0" * 64
    input_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(RuntimeError, match="V4 inputs differ"):
        verify()
    input_path.write_bytes(original)
    recipe_path = input_path.with_suffix(".recipe.json")
    original_recipe = recipe_path.read_bytes()
    malformed = json.loads(original_recipe)
    malformed["inputs"]["fee_rate"] += .001
    recipe_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(RuntimeError, match="V4 inputs differ"):
        verify()
    recipe_path.write_bytes(original_recipe)
    with sqlite3.connect(database) as connection:
        rules, = connection.execute("SELECT equity_rules_json FROM virtual_accounts WHERE account_id='formal'").fetchone()
        connection.execute("UPDATE virtual_accounts SET equity_rules_json=NULL WHERE account_id='formal'")
    with pytest.raises(RuntimeError, match="explicit account migration"):
        verify()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE virtual_accounts SET equity_rules_json=?,quantity=1 WHERE account_id='formal'", (rules,))
    with pytest.raises(ValueError, match="state migration is required"):
        verify()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE virtual_accounts SET quantity=0,qualification_snapshot='RESEARCH' WHERE account_id='formal'")
    with pytest.raises(RuntimeError, match="qualification differs"):
        verify()
