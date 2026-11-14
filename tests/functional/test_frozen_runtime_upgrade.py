# Risk ownership: TDR-23
"""Local publication transactions using synthetic releases in isolated repos.

Candidate sources, audit references, package construction, CAS, archives and
rollback run through the real upgrade API without completed-inspection substitutes.
"""

from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import shutil
from types import SimpleNamespace

import pytest
from strategy_runtime import RuntimeCompatibilityError, StrategyCandidate, implementation_sha256
from dataflows import Dataset, MarketId

from czsc_trader.application import RepositoryContext, validate_release_package
from czsc_trader.application import runtime_migration as m
from strategy_manager import StrategyRegistry
from strategy_manager import freeze_contracts as f
from frozen_contract_support import (
    current_frozen as current_frozen, inspection as inspection,
    managed_evaluation as managed_evaluation,
)


def _audit_ref(context, value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = sha256(data).hexdigest()
    owner = f.ResearchEvidenceOwner("S900", "EX001_20261020")
    path = context.root / owner.repository_path / (digest + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f.ResearchEvidenceRef(owner, path.name, digest)


@pytest.fixture
def upgrade(current_frozen):
    context, stored = current_frozen
    root, strategies = context.root, context.strategy_root
    original_manifest, binding, source = validate_release_package(context, "S900-v1")
    stored = StrategyRegistry(strategies).get_version("S900", "v1")
    original = f.FrozenVersionReference("S900", "v1", stored.release_hash, original_manifest["package_hash"])
    lifecycle = {"schema_version": 1, "event_id": "EVT-synthetic-paper", "event_type": "PAPER_APPROVED",
        "strategy_id": "S900", "version": "v1", "release_hash": stored.release_hash,
        "from_state": "RESEARCH", "to_state": "PAPER_READY", "evidence_ids": [],
        "actor": "synthetic-fixture", "reason": "transaction qualification boundary",
        "occurred_at": "2026-10-20T00:00:00+08:00"}
    (strategies / "S900/lifecycle.jsonl").write_text(json.dumps(lifecycle) + "\n")
    ref = _audit_ref(context, {"authorization": "Synthetic explicit same-version upgrade approval"})
    candidate_source = root / ".tmp/upgrade-source/strategy_runtime"
    shutil.copytree(source, candidate_source)
    payload = json.loads(json.dumps(dict(stored.strategy_payload), default=dict))
    payload["parameters"]["threshold"] = 0.75
    changed_source = candidate_source / payload["runtime"]["source_files"][0]
    changed_source.write_bytes(changed_source.read_bytes() + b"\n# Synthetic upgrade revision.\n")
    payload["runtime"]["source_sha256"] = implementation_sha256(
        tuple(payload["runtime"]["source_files"]), source_root=candidate_source)
    candidate = StrategyCandidate("S900", "C9876", payload, candidate_source)
    request = m.FrozenRuntimeUpgradeRequest(
        original, candidate, ref,
        "Synthetic parameter and implementation revision", "synthetic-researcher", (),
        root / ".tmp/prepared",
    )
    return context, request, stored


def _bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _upgrade_closure(context, request, prepared=None):
    """Only the actual frozen package, candidate and audited preparation inputs.

    Dataframes, DFLS stores and old setup staging are unrelated to these
    migration contracts and must not become per-case filesystem fixtures.
    """
    roots = [context.strategy_root, request.candidate.source_root]
    if prepared is not None:
        roots.extend((prepared.plan_path.parent / "staged",))
    files = {path.relative_to(context.root): path.read_bytes()
             for root in roots for path in root.rglob("*") if path.is_file()}
    for ref in (request.confirmation, *request.evidence):
        path = ref.resolve(context.root)
        files[path.relative_to(context.root)] = path.read_bytes()
    if prepared is not None:
        files[prepared.plan_path.relative_to(context.root)] = prepared.plan_path.read_bytes()
    return files


def _restore_files(root, files):
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _relocated_request(request, original_root, root):
    return replace(request,
        candidate=replace(request.candidate, source_root=root / request.candidate.source_root.relative_to(original_root)),
        output_directory=root / request.output_directory.relative_to(original_root))


@pytest.fixture(scope="module")
def committed_upgrade_seed():
    return {}


@pytest.fixture
def committed_upgrade(request, tmp_path, committed_upgrade_seed):
    """Audit/retry tests consume a real committed upgrade, built once privately."""
    cache = committed_upgrade_seed
    if not cache:
        context, change, stored = request.getfixturevalue('upgrade')
        prepared = m.prepare_frozen_runtime_upgrade(context, change)
        receipt = m.apply_frozen_runtime_upgrade(context, prepared)
        cache.update(files=_upgrade_closure(context, change, prepared), root=context.root,
                     change=change, stored=stored, prepared=prepared, receipt=receipt)
    root = tmp_path / 'committed-upgrade'
    _restore_files(root, cache['files'])
    original_root = cache['root']
    context = RepositoryContext(root, root / 'research', root / 'research/registrations', root / 'strategies')
    change = _relocated_request(cache['change'], original_root, root)
    prepared = replace(cache['prepared'], plan_path=root / cache['prepared'].plan_path.relative_to(original_root))
    receipt = replace(cache['receipt'],
        archive_path=root / cache['receipt'].archive_path.relative_to(original_root),
        receipt_path=root / cache['receipt'].receipt_path.relative_to(original_root))
    return context, change, cache['stored'], prepared, receipt


def _with_seed(candidate):
    from strategy_runtime import FrozenDataAsset, ObservationAvailability, StepDataInput
    path = candidate.source_root / 'assets/seed.csv'
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b'Date,score\n2026-10-12,1\n')
    asset = FrozenDataAsset('assets/seed.csv', sha256(path.read_bytes()).hexdigest())
    item = StepDataInput('seed', Dataset.STRATEGY_FEATURE_EVIDENCE, 'S900-v1', 'daily', 1,
        ObservationAvailability(candidate.instrument.timezone, '00:00'), asset=asset)
    return replace(candidate, definition=replace(candidate.definition, step_data_inputs=(item,)))


def _legacy_source_identity(context, request, stored):
    """An authenticated schema-1 import with historical, non-CandidateKey provenance."""
    from strategy_manager import canonical_sha256
    stored = replace(stored, source_candidate='S002-C001')
    stored = replace(stored, release_hash=canonical_sha256(stored.release_payload()))
    package = context.strategy_root / 'S900/releases/v1'
    binding = json.loads((package / 'runtime_binding.json').read_bytes())
    binding['release_hash'] = stored.release_hash
    (package / 'runtime_binding.json').write_bytes(json.dumps(binding, sort_keys=True).encode())
    manifest = json.loads((package / 'release_manifest.json').read_bytes())
    manifest.update(strategy_version_hash=stored.release_hash, source_candidate_id='S900-S002-C001')
    manifest['files']['runtime_binding.json'] = sha256((package / 'runtime_binding.json').read_bytes()).hexdigest()
    manifest.pop('package_hash')
    manifest['package_hash'] = canonical_sha256(manifest)
    (package / 'release_manifest.json').write_bytes(json.dumps(manifest, sort_keys=True).encode())
    (context.strategy_root / 'S900/versions/v1.json').write_bytes(json.dumps(stored.to_dict(), sort_keys=True).encode())
    path = context.strategy_root / 'deployments/S900-v1.json'
    deployment = json.loads(path.read_bytes())
    deployment.update(strategy_version_hash=stored.release_hash, package_hash=manifest['package_hash'])
    deployment.pop('receipt_hash')
    deployment['receipt_hash'] = canonical_sha256(deployment)
    path.write_bytes(json.dumps(deployment, sort_keys=True).encode())
    return replace(request, original=f.FrozenVersionReference('S900', 'v1', stored.release_hash, manifest['package_hash'])), stored


def _build_obsolete_v4(upgrade, market):
    """Authentic frozen bytes from before execution_policy became mandatory."""
    from strategy_manager import canonical_sha256
    from strategy_runtime.deployment import validate_release_integrity
    from adjusted_observation_support import setup_adjusted

    context, change, _ = upgrade
    fixture = context.root / '.tmp/obsolete-v4-fixture'
    fixture.mkdir()
    _, native, _, _, _ = setup_adjusted(fixture, market)
    candidate = replace(native.candidate, strategy_id='S900', candidate_id='C9877')
    initial = m.prepare_frozen_runtime_upgrade(context, replace(change, candidate=candidate))
    m.apply_frozen_runtime_upgrade(context, initial)

    # Recreate a historical package by signing its old raw definition. Parsing
    # that definition with today's contract would defeat the regression case.
    package = context.strategy_root / 'S900/releases/v1'
    version_path = context.strategy_root / 'S900/versions/v1.json'
    frozen = json.loads(version_path.read_bytes())
    definition = frozen['strategy_payload']['equity_definition']
    definition.pop('execution_policy')
    definition['contract_version'] = 4
    frozen['strategy_payload']['runtime']['contract_version'] = 4
    frozen.pop('release_hash')
    frozen['release_hash'] = canonical_sha256(frozen)
    version_path.write_bytes(m._upgrade_json(frozen))
    binding_path = package / 'runtime_binding.json'
    binding = json.loads(binding_path.read_bytes())
    binding.update(release_hash=frozen['release_hash'], observation_sha256=canonical_sha256(
        {'contract': 'equity-account-v4', 'definition': definition}))
    binding_path.write_bytes(m._upgrade_json(binding))
    manifest_path = package / 'release_manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    manifest['strategy_version_hash'] = frozen['release_hash']
    manifest['files']['runtime_binding.json'] = sha256(binding_path.read_bytes()).hexdigest()
    manifest.pop('package_hash')
    manifest['package_hash'] = canonical_sha256(manifest)
    manifest_path.write_bytes(m._upgrade_json(manifest))
    deployment_path = context.strategy_root / 'deployments/S900-v1.json'
    deployment = json.loads(deployment_path.read_bytes())
    deployment.update(strategy_version_hash=frozen['release_hash'], package_hash=manifest['package_hash'])
    deployment.pop('receipt_hash')
    deployment['receipt_hash'] = canonical_sha256(deployment)
    deployment_path.write_bytes(m._upgrade_json(deployment))
    original = f.FrozenVersionReference('S900', 'v1', frozen['release_hash'], manifest['package_hash'])
    assert validate_release_integrity(context.strategy_root, 'S900-v1').package_sha256 == original.package_hash
    with pytest.raises(TypeError, match='explicit execution policy'):
        validate_release_package(context, 'S900-v1')
    return context, replace(change, original=original, candidate=candidate,
                            output_directory=context.root / '.tmp/upgrade-obsolete'), frozen


@pytest.fixture(scope='module')
def obsolete_v4_seeds():
    return {}


@pytest.fixture(params=[MarketId.US], ids=['TDR-23-C01-US'])
def obsolete_v4(request, tmp_path, obsolete_v4_seeds):
    """Each market builds its historical package once; each fault gets private bytes.

    The setup upgrade is not the operation under test. Every consumer still
    calls the real preparation/apply/rollback path against its own old package.
    """
    market = request.param
    if market not in obsolete_v4_seeds:
        context, change, frozen = _build_obsolete_v4(request.getfixturevalue('upgrade'), market)
        files = _upgrade_closure(context, change)
        obsolete_v4_seeds[market] = (files, context.root, change, frozen)
    files, original_root, change, frozen = obsolete_v4_seeds[market]
    root = tmp_path / 'obsolete-upgrade-repo'
    _restore_files(root, files)
    change = _relocated_request(change, original_root, root)
    context = RepositoryContext(root, root / 'research', root / 'research/registrations', root / 'strategies')
    return context, change, json.loads(json.dumps(frozen))


def test_obsolete_contract_upgrades_without_loading_old_runtime(obsolete_v4):
    from strategy_runtime import load_strategy_deployment

    context, request, old = obsolete_v4
    before = _bytes(context.strategy_root)
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    assert _bytes(context.strategy_root) == before
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    after = _bytes(context.strategy_root)
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt
    assert _bytes(context.strategy_root) == after
    original, _, _, source = m._migration_original(context, request.original)
    assert original.to_dict() == old
    assert source.is_relative_to(receipt.archive_path)
    installed = load_strategy_deployment(context.strategy_root, 'S900-v1')
    assert installed.release_hash == prepared.migrated.release_hash
    current = StrategyRegistry(context.strategy_root).get_version('S900', 'v1').to_dict()
    for field in old.keys() - {'release_hash', 'strategy_payload'}:
        assert current[field] == old[field]
    assert current['strategy_payload']['equity_definition']['execution_policy']
    assert prepared.migrated != request.original


@pytest.mark.parametrize('side', ['new-candidate', 'old-package'], ids=['TDR-23-C06', 'TDR-23-C13'])
def test_obsolete_contract_upgrade_still_rejects_changed_sources(obsolete_v4, side):
    context, request, _ = obsolete_v4
    source = (context.strategy_root / 'S900/releases/v1/src/strategy_runtime' if side == 'old-package'
              else request.candidate.source_root)
    entry = source / 'strategy.py'
    entry.write_bytes(entry.read_bytes() + b'\n# unreviewed change\n')
    before = _bytes(context.strategy_root)
    with pytest.raises((RuntimeCompatibilityError, ValueError), match='package file differs|source closure changed'):
        m.prepare_frozen_runtime_upgrade(context, request)
    assert _bytes(context.strategy_root) == before
    assert not request.output_directory.exists()


@pytest.mark.parametrize('market', [MarketId.CN, MarketId.US], ids=['TDR-23-C01', 'TDR-23-C02'])
def test_native_upgrade_preserves_history_and_resets_qualification(upgrade, market, monkeypatch):
    """Both market contracts cross the same legacy/native and native/native transaction."""
    from adjusted_observation_support import setup_adjusted
    from strategy_runtime import EquityStrategyCandidate, equity_source_hash, load_strategy_deployment
    context, request, original_version = upgrade
    request, original_version = _legacy_source_identity(context, request, original_version)
    fixture = context.root / '.tmp/native-fixture'
    fixture.mkdir()
    _, native_request, _, _, _ = setup_adjusted(fixture, market)
    candidate = _with_seed(replace(native_request.candidate, strategy_id='S900', candidate_id='C9877'))
    request = replace(request, candidate=candidate)
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt
    installed = load_strategy_deployment(context.strategy_root, 'S900-v1')
    assert installed.release_hash == prepared.migrated.release_hash
    assert installed.runtime_candidate_id == candidate.candidate_id
    manifest, _, _ = validate_release_package(context, 'S900-v1')
    assert manifest['schema_version'] == 2
    assert manifest['runtime_candidate_id'] == 'C9877'
    assert manifest['source_candidate_id'] == 'S900-S002-C001'
    assert installed.binding.spec.source_files == ('strategy.py',)
    assert set(installed.install_files) == {'strategy.py', 'assets/seed.csv'}
    assert (installed.source_root / 'assets/seed.csv').read_bytes() == (candidate.source_root / 'assets/seed.csv').read_bytes()
    current = StrategyRegistry(context.strategy_root).get_version('S900', 'v1')
    from strategy_manager.freeze_store import _package
    assert _package(context.strategy_root / 'S900/releases/v1', current, manifest['package_hash']) == manifest['package_hash']
    for field in ('source_experiment', 'source_candidate', 'selection_data_cutoff', 'forward_start', 'parent_version'):
        assert getattr(current, field) == getattr(original_version, field)
    assert current.strategy_payload['runtime']['kind'] == 'ACCOUNT_REPLAY'
    assert current.strategy_payload['equity_definition']['instrument']['market'] == market.value
    assert StrategyRegistry(context.strategy_root).current_qualification('S900', 'v1').value == 'RESEARCH'
    from paper_trading_engine.srt_advice_client import _strategy_identity
    from paper_trading_engine.errors import AdviceClientError
    from strategy_runtime import StrategyRelease
    with pytest.raises(AdviceClientError, match='not approved'):
        _strategy_identity(context.root, StrategyRelease.from_mapping(current.to_dict()))
    # Qualification is an independent boundary; grant only this isolated fixture.
    lifecycle = json.loads((context.strategy_root / 'S900/lifecycle.jsonl').read_text().splitlines()[-1])
    lifecycle.update(event_id='EVT-synthetic-native-paper', release_hash=current.release_hash,
                     from_state='RESEARCH', to_state='PAPER_READY')
    with (context.strategy_root / 'S900/lifecycle.jsonl').open('a') as stream:
        stream.write(json.dumps(lifecycle) + '\n')
    from paper_trading_engine.equity_runtime import EquityRuntimeAdviceClient
    from paper_trading_engine.ec_boundary import execution_rules
    store = SimpleNamespace(virtual_account=lambda _: {'strategy_id': 'S900', 'strategy_version': 'v1',
        'release_hash': current.release_hash, 'run_state': 'PAUSED'}, equity_account_rules=lambda _: execution_rules(
        candidate.instrument, candidate.definition.execution_spec))
    client = EquityRuntimeAdviceClient(repo_root=context.root, store=store, dataflows=None, data_dir=context.root / '.tmp/pte')
    _, loaded_release, loaded = client._account_release('native')
    assert loaded.candidate_id == 'C9877'
    assert loaded.content_identity == candidate.content_identity
    assert loaded_release.release_hash == current.release_hash
    source = candidate.source_root / 'strategy.py'
    source.write_bytes(source.read_bytes() + b'\n# native revision\n')
    revised = EquityStrategyCandidate('S900', 'C9878', replace(candidate.definition,
        source_sha256=equity_source_hash(candidate.source_root, candidate.definition.source_files)), candidate.source_root)
    next_request = replace(request, original=prepared.migrated, candidate=revised,
                           output_directory=context.root / '.tmp/prepared-native')
    next_prepared = m.prepare_frozen_runtime_upgrade(context, next_request)
    publishing = next_prepared.plan_path.parent / "publishing_release"
    original_replace = m.os.replace
    attempts = []

    def deny_first_publication(source, target):
        if source == publishing:
            attempts.append(source)
            if len(attempts) == 1:
                error = PermissionError("synthetic Windows release directory conflict")
                error.winerror = 5
                raise error
        return original_replace(source, target)

    monkeypatch.setattr(m.os, "replace", deny_first_publication)
    monkeypatch.setattr(m, "_FILE_REPLACE_DELAYS", (0.025, 0.050, 0.100, 0.200))
    next_receipt = m.apply_frozen_runtime_upgrade(context, next_prepared)
    assert len(attempts) >= 2
    assert next_receipt.original == prepared.migrated
    assert m.apply_frozen_runtime_upgrade(context, next_prepared) == next_receipt
    assert load_strategy_deployment(context.strategy_root, 'S900-v1').release_hash == next_prepared.migrated.release_hash


def test_upgrade_prepares_then_preserves_history_archives_and_commits_idempotently(upgrade):
    context, request, stored = upgrade
    before = _bytes(context.strategy_root)
    assert StrategyRegistry(context.strategy_root).current_qualification("S900", "v1").value == "PAPER_READY"
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    assert _bytes(context.strategy_root) == before
    assert prepared.migrated.version == prepared.original.version == "v1"
    candidate = request.candidate
    stage_context = replace(context, strategy_root=prepared.plan_path.parent / "staged")
    manifest, binding, staged_source = validate_release_package(stage_context, "S900-v1")
    assert manifest["package_hash"] == prepared.migrated.package_hash
    assert binding["source_files"] == list(candidate.payload["runtime"]["source_files"])
    for name in binding["source_files"]:
        assert (staged_source / name).read_bytes() == (candidate.source_root / name).read_bytes()
    plan = json.loads(prepared.plan_path.read_bytes())
    assert plan["schema_version"] == 2
    assert plan["confirmation"] == request.confirmation.to_dict()
    assert plan["change_summary"] == request.change_summary
    assert plan["operator"] == request.operator
    assert plan["evidence"] == []
    assert "inspection" not in plan
    # Application publishes the reviewed snapshot, not the mutable research workspace.
    workspace_source = candidate.source_root / binding["source_files"][0]
    workspace_source.write_bytes(workspace_source.read_bytes() + b"\n# Later workspace edit.\n")
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    assert receipt.status == "COMMITTED"
    current = StrategyRegistry(context.strategy_root).get_version("S900", "v1")
    old, new = stored.to_dict(), current.to_dict()
    for field in ("strategy_payload", "release_hash"):
        old.pop(field)
        new.pop(field)
    assert old == new
    assert current.strategy_payload["parameters"]["threshold"] == 0.75
    assert current.strategy_payload["decision_feedback"] == "MARKET_INTENT"
    assert current.strategy_payload["runtime"]["contract_version"] == 2
    assert StrategyRegistry(context.strategy_root).current_qualification("S900", "v1").value == "RESEARCH"
    for name, data in before.items():
        if name.startswith("S900/releases/v1/"):
            assert (receipt.archive_path / "strategies" / name).read_bytes() == data
        elif name == "S900/versions/v1.json":
            assert (receipt.archive_path / "strategies" / name).read_bytes() == data
        elif name == "deployments/S900-v1.json":
            assert (receipt.archive_path / "strategies" / name).read_bytes() == data
        else:
            assert (context.strategy_root / name).read_bytes() == data
    committed = _bytes(context.strategy_root)
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt
    assert _bytes(context.strategy_root) == committed
    historic, _, _, source = m._migration_original(context, request.original)
    assert historic.to_dict() == stored.to_dict()
    assert source.is_relative_to(receipt.archive_path)


@pytest.mark.parametrize('change', ['archive'])
def test_committed_upgrade_retry_authenticates_archive_and_deployment(committed_upgrade, change):
    context, request, _, prepared, receipt = committed_upgrade
    if change == "archive":
        path = receipt.archive_path / "strategies/S900/versions/v1.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        (context.strategy_root / "deployments/S900-v1.json").write_bytes(
            (receipt.archive_path / "strategies/deployments/S900-v1.json").read_bytes())
    with pytest.raises((ValueError, RuntimeCompatibilityError), match="archived file|archive differs|deployment|receipt"):
        m.apply_frozen_runtime_upgrade(context, prepared)


def test_upgrade_rejects_changed_staging_before_original_writes(upgrade):
    context, request, stored = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    package = prepared.plan_path.parent / "staged/S900/releases/v1"
    manifest = json.loads((package / "release_manifest.json").read_bytes())
    source = stored.strategy_payload["runtime"]["source_files"][0]
    (package / manifest["runtime_root"] / source).write_bytes(b"changed")
    before = _bytes(context.strategy_root)
    with pytest.raises(ValueError, match="staged file identity"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert _bytes(context.strategy_root) == before


def test_upgrade_compares_original_version_bytes_after_preparation(upgrade):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    path = context.strategy_root / "S900/versions/v1.json"
    path.write_bytes(path.read_bytes() + b"\n")
    before = _bytes(context.strategy_root)
    with pytest.raises(ValueError, match="changed after preparation"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert all((context.strategy_root / name).read_bytes() == data for name, data in before.items())
    assert not (context.strategy_root / "revisions").exists()


@pytest.mark.parametrize('failure', ['publication-error'])
def test_upgrade_deployment_failure_restores_original_package_version_and_receipt(upgrade, monkeypatch, failure):
    context, request, _ = upgrade
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    before = _bytes(context.strategy_root)
    original_write = m._upgrade_write
    failed = False

    def fail_once(path, data, scratch):
        nonlocal failed
        if path.parent.name == "deployments" and not failed:
            failed = True
            raise OSError("injected deployment publication failure")
        return original_write(path, data, scratch)

    attempts, waits = [], []
    if failure == "publication-error":
        monkeypatch.setattr(m, "_upgrade_write", fail_once)
    else:
        original_replace = m.os.replace
        def denied(source, target):
            nonlocal failed
            if target.parent.name == "deployments":
                failed = True
                attempts.append(source)
                error = PermissionError("synthetic Windows access conflict")
                error.winerror = 5
                raise error
            return original_replace(source, target)
        monkeypatch.setattr(m.os, "replace", denied)
        monkeypatch.setattr(m, "_FILE_REPLACE_DELAYS", (0.025, 0.050, 0.100, 0.200))
        monkeypatch.setattr(m.clock, "sleep", waits.append)
    with pytest.raises(RuntimeError, match="original content restored"):
        m.apply_frozen_runtime_upgrade(context, prepared)
    assert failed
    if failure == "persistent-windows-conflict":
        assert len(attempts) == 5 and len(set(attempts)) == 1
        assert waits == [0.025, 0.050, 0.100, 0.200]
    assert all((context.strategy_root / name).read_bytes() == data for name, data in before.items())
    manifest, _, _ = validate_release_package(context, "S900-v1")
    assert manifest["package_hash"] == request.original.package_hash
    archive = context.strategy_root / "revisions/S900-v1" / request.original.release_hash
    assert json.loads((archive / "rollback.json").read_bytes())["status"] == "ROLLED_BACK"
    assert not (archive / "upgrade_receipt.json").exists()
    with pytest.raises(ValueError, match="nonterminal archive"):
        m.apply_frozen_runtime_upgrade(context, prepared)


@pytest.mark.parametrize('status', ['FAIL'])
def test_upgrade_records_optional_evidence_without_interpreting_research_result(upgrade, status):
    context, request, _ = upgrade
    evidence = _audit_ref(context, {"status": status, "summary": "Synthetic research diagnostic"})
    request = replace(request, evidence=(evidence,))
    prepared = m.prepare_frozen_runtime_upgrade(context, request)
    plan = json.loads(prepared.plan_path.read_bytes())
    assert plan["evidence"] == [evidence.to_dict()]
    receipt = m.apply_frozen_runtime_upgrade(context, prepared)
    audit = json.loads(receipt.receipt_path.read_bytes())
    assert audit["status"] == "COMMITTED"
    assert audit["confirmation"] == request.confirmation.to_dict()
    assert audit["evidence"] == [evidence.to_dict()]
    assert audit["operator"] == request.operator
    assert audit["change_summary"] == request.change_summary
    assert json.loads(evidence.resolve(context.root).read_bytes())["status"] == status


def test_archived_audit_snapshot_remains_bound_to_original_evidence_hash(committed_upgrade):
    context, request, _, prepared, receipt = committed_upgrade
    name = "audit/" + request.confirmation.sha256
    changed = receipt.archive_path / name
    changed.write_bytes(b"replacement confirmation")
    # Recomputing a local file manifest must not change the evidence identity.
    snapshot_path = receipt.archive_path / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_bytes())
    snapshot["files"][name] = sha256(changed.read_bytes()).hexdigest()
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ValueError, match="archived audit evidence differs"):
        m.apply_frozen_runtime_upgrade(context, prepared)


def test_committed_upgrade_audit_is_self_contained_after_source_evidence_is_unavailable(committed_upgrade):
    context, request, _, prepared, receipt = committed_upgrade
    request.confirmation.resolve(context.root).unlink()
    assert m.apply_frozen_runtime_upgrade(context, prepared) == receipt


@pytest.mark.parametrize('operation', ['read', 'apply'], ids=['TDR-23-C14', 'TDR-23-C15'])
def test_schema_one_archive_is_read_only_and_preserves_original_bytes(committed_upgrade, operation):
    context, request, stored, prepared, receipt = committed_upgrade
    archive = receipt.archive_path
    plan_path = archive / "upgrade_plan.json"
    plan = json.loads(plan_path.read_bytes())
    plan["schema_version"] = 1
    plan["inspection"] = request.confirmation.to_dict()
    for name in ("change_summary", "operator", "evidence", "candidate_identity", "changes"):
        plan.pop(name)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    plan_sha = sha256(plan_path.read_bytes()).hexdigest()
    raw = json.loads(receipt.receipt_path.read_bytes())
    for name in ("schema_version", "change_summary", "operator", "evidence", "committed_at"):
        raw.pop(name)
    raw.update(plan_sha256=plan_sha, inspection=plan["inspection"])
    receipt.receipt_path.write_text(json.dumps(raw), encoding="utf-8")
    snapshot_path = archive / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_bytes())
    snapshot["plan_sha256"] = plan_sha
    snapshot["files"]["upgrade_plan.json"] = plan_sha
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    before = _bytes(archive)
    if operation == 'read':
        original, _, _, source = m._migration_original(context, request.original)
        assert original.to_dict() == stored.to_dict()
        assert source.is_relative_to(archive)
    else:
        prepared.plan_path.write_bytes(plan_path.read_bytes())
        old_prepared = replace(prepared, plan_sha256=plan_sha)
        with pytest.raises(ValueError, match="historical plans are read-only"):
            m.apply_frozen_runtime_upgrade(context, old_prepared)
    assert _bytes(archive) == before



def test_new_candidate_must_satisfy_current_contract(obsolete_v4):
    context, request, _ = obsolete_v4
    candidate = request.candidate
    invalid = replace(candidate, definition=replace(candidate.definition, contract_version=2,
        feature_graph=None, state_schema=None, computation=None, auxiliary_inputs=(), observation_inputs=(),
        execution_policy=None, analysis_price='RAW'))
    before = _bytes(context.strategy_root)
    with pytest.raises(ValueError, match='V5 DFLS step contract'):
        replace(request, candidate=invalid)
    assert _bytes(context.strategy_root) == before
