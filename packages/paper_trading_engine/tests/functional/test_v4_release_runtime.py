"""Native frozen snapshots and read-only CN/US release admission."""
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
from strategy_runtime.deployment import deployment_inventory
from test_formal_v4_runtime import formal_v4 as formal_v4
from test_watchdog_service import create_release


ROOT = Path(__file__).resolve().parents[4]


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
    assert {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()} == files
    assert {key: registry.current_qualification(*key.rsplit("-", 1)) for key in before} == before


@pytest.mark.release_acceptance
def test_native_snapshot_includes_undeployed_packages_and_rejects_tampering(tmp_path):
    strategies = tmp_path / "snapshot"
    shutil.copytree(ROOT / "strategies", strategies)
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


def _files(root):
    # SQLite readers update WAL shared-memory lock slots even in query_only
    # mode. The durable database/WAL and every data/config file remain fixed.
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.name.endswith("-shm")}


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
        "from paper_trading_engine.futu_gateway import FutuGateway\n"
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
    monkeypatch.setattr("paper_trading_engine.futu_gateway.FutuGateway.__init__", forbidden)
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
