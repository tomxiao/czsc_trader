"""Native frozen snapshots and read-only CN/US release admission."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from paper_trading_engine.release_cli import (
    _verify_strategy_snapshot, _verify_runtime_configuration,
)
from paper_trading_engine.runtime_config import PteRuntimeConfig
from strategy_runtime.deployment import deployment_inventory, load_strategy_deployment
from strategy_runtime import RuntimeCompatibilityError
from test_formal_v4_runtime import formal_v4 as formal_v4


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


def _copy_retained(seed, target, reference, *, include_current=False):
    """Copy only the authenticated history closure under examination.

    The separate full-snapshot test retains collection-level release acceptance.
    No other strategy's source tree participates in a single receipt mutation.
    """
    family, _ = reference.rsplit('-', 1)
    target.mkdir()
    shutil.copytree(seed / family, target / family)
    history = target / 'deployments/history'
    history.mkdir(parents=True)
    shutil.copyfile(seed / 'deployments/history' / (reference + '.json'),
                    history / (reference + '.json'))
    if include_current:
        # A running release inventory must contain at least one current binding.
        # Include one real closure so admission reaches the history account rule.
        receipt = sorted((seed / 'deployments').glob('S*-v*.json'))[0]
        current_family, version = receipt.stem.rsplit('-', 1)
        family_root = target / current_family
        (family_root / 'versions').mkdir(parents=True)
        shutil.copyfile(seed / current_family / 'versions' / (version + '.json'),
                        family_root / 'versions' / (version + '.json'))
        shutil.copytree(seed / current_family / 'releases' / version,
                        family_root / 'releases' / version)
        shutil.copyfile(receipt, target / 'deployments' / receipt.name)


# Independent risk: PTE20; responsibility-level assertions.
@pytest.mark.release_acceptance
def test_PTE20_C01_native_snapshot_includes_undeployed_packages_and_rejects_tampering(tmp_path, release_snapshot):
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


# Independent risk: PTE20; responsibility-level assertions.
@pytest.mark.release_acceptance
@pytest.mark.parametrize('reference,damage', [
    ('S002-v1','source'),
], ids=['PTE20-C02'])
def test_retained_history_blocks_snapshot_corruption(tmp_path, release_snapshot, reference, damage):
    """History is retained and authenticated, never ignored to admit a snapshot."""
    from strategy_runtime import canonical_sha256

    strategies = tmp_path / 'snapshot'
    _copy_retained(release_snapshot, strategies, reference)
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


# Independent risk: PTE20; responsibility-level assertions.
@pytest.mark.release_acceptance
@pytest.mark.parametrize('reference,state', [
    ('S002-v1','PAUSED'),
], ids=['PTE20-C03'])
def test_history_account_preflight_is_readonly_and_never_admits_running_strategy(tmp_path, new_store, release_snapshot, monkeypatch, reference, state):
    from execution_channels.futu.store import PaperStore

    _copy_retained(release_snapshot, tmp_path / 'strategies', reference, include_current=True)
    data, config = tmp_path / 'data', tmp_path / 'config'
    data.mkdir()
    PteRuntimeConfig(data_space=Path('market')).save(config / 'pte.json')
    (config / '.env').write_text('TUSHARE_TOKEN=synthetic-offline-token\n', encoding='utf-8')
    family, version = reference.rsplit('-', 1)
    frozen = json.loads((tmp_path / 'strategies' / family / 'versions' / f'{version}.json').read_text(encoding='utf-8'))
    database = tmp_path / 'runtime.db'
    store = new_store(database)
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
