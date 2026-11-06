"""Explicit RSCH post-publication check of reviewed local upgrades."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader.application import RepositoryContext, validate_release_package
from strategy_manager import StrategyRegistry
from strategy_runtime import EquityStrategyDefinition

root = Path.cwd()
home = root / '.tmp/rsch-frozen-v4-upgrade'
repo = RepositoryContext.discover(root)
registry = StrategyRegistry(repo.strategy_root)
before = json.loads((home / 'inventory.json').read_text(encoding='utf-8'))
baseline = json.loads((home / 'before_files.json').read_text(encoding='utf-8'))
upgraded = {'S001', 'S002', 'S003', 'S007', 'S011', 'S015'}
results = []
for original in before['releases']:
    ref = original['release_id']
    family, number = ref.split('-')
    manifest, binding, source = validate_release_package(repo, ref)
    current = registry.get_version(family, number)
    row = {'release_id': ref, 'release_hash': current.release_hash,
           'package_hash': manifest['package_hash']}
    if family not in upgraded:
        assert current.release_hash == original['release_hash'], ref
        assert manifest['package_hash'] == original['package_hash'], ref
        checked = 0
        for path, digest in baseline.items():
            if path.startswith(f'strategies/{family}/') or path == f'strategies/deployments/{ref}.json':
                assert sha256((root / path).read_bytes()).hexdigest() == digest, path
                checked += 1
        row.update(status='UNCHANGED', files_checked=checked)
    else:
        assert current.release_hash != original['release_hash'], ref
        assert current.strategy_payload['runtime']['kind'] == 'ACCOUNT_REPLAY', ref
        definition = EquityStrategyDefinition.from_dict(current.strategy_payload['equity_definition'])
        assert definition.contract_version == 4
        assert json.loads(definition.parameters_json) == original['parameters']['values'], ref
        archive = repo.strategy_root / 'revisions' / ref / original['release_hash']
        receipt = json.loads((archive / 'upgrade_receipt.json').read_text(encoding='utf-8'))
        assert receipt['status'] == 'COMMITTED'
        assert receipt['migrated']['release_hash'] == current.release_hash
        archived_repo = replace(repo, strategy_root=archive / 'strategies')
        old_manifest, _, _ = validate_release_package(archived_repo, ref)
        assert old_manifest['package_hash'] == original['package_hash']
        old = StrategyRegistry(archived_repo.strategy_root).get_version(family, number)
        a, b = old.to_dict(), current.to_dict()
        for key in a:
            if key not in ('strategy_payload', 'release_hash'):
                assert a[key] == b[key], (ref, key)
        for path, digest in baseline.items():
            if path.startswith(f'strategies/{family}/releases/{number}/') or path == f'strategies/{family}/versions/{number}.json' or path == f'strategies/deployments/{ref}.json':
                assert sha256((archive / path).read_bytes()).hexdigest() == digest, path
        assert registry.current_qualification(family, number).value == 'RESEARCH'
        row.update(status='UPGRADED_V4', parameters='UNCHANGED', history_fields='UNCHANGED',
                   original_bytes='ARCHIVED_EXACTLY', qualification='RESEARCH',
                   archive=archive.relative_to(root).as_posix())
    results.append(row)
result = {'status': 'PASS', 'production_writes': 0, 'results': results}
(root / '.tmp/s001-v4-correction/post_upgrade_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
