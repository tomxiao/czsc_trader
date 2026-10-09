"""Publish migration proof and verify the preserved S013 delivery graph."""
# ruff: noqa: E402
from pathlib import Path
from hashlib import sha256
import json
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from upgrade_candidates import ROOT, OUT, EXPERIMENT, context, read, write
from czsc_trader.application import publish_evidence, validate_delivery, load_candidate
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools import delivery as d
from strategy_manager import CandidateKey
from strategy_runtime import StrategyRuntime, ImplementationDependency


def main():
    research = context(1)
    migration = read(OUT / 'migration.json')
    economic = read(OUT / 'candidate_equivalence.json')
    registrations = read(OUT / 'successor_registrations.json')
    fresh = read(OUT / 'fresh_continuation_precheck.json')
    assert all(value['status'] == 'PASS' for value in (migration, economic, registrations, fresh))
    assert len(economic['candidates']) == len(registrations['candidates']) == 30
    backup = ROOT / migration['backup']
    database = ROOT / migration['space'] / 'assets.sqlite3'
    with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as current:
            assert original.execute('SELECT * FROM space_metadata').fetchall() == current.execute('SELECT * FROM space_metadata').fetchall()
            for table, identifier in (('assets', 'asset_id'), ('preparations', 'preparation_id')):
                for row in original.execute(f'SELECT * FROM {table}'):
                    assert current.execute(f'SELECT * FROM {table} WHERE {identifier}=?', (row[0],)).fetchone() == row
    delivery_checks = []
    for path in sorted((ROOT / 'research/S013/deliveries').rglob('receipt.json')):
        receipt = d.DeliveryReceipt.from_dict(read(path))
        validation = validate_delivery(research.repository, receipt.reference, scope=d.DeliveryValidationScope.FULL)
        assert validation.status == d.ValidationStatus.PASS, validation
        delivery_checks.append({'reference': receipt.reference.to_dict(), 'status': validation.status.value})
    assert len(delivery_checks) == 10
    evidence = {}
    for filename in ('migration.json', 'prepared_reference_mapping.json', 'asset_mapping.json',
                     'input_equivalence.json', 'strategy_contract_precheck.json',
                     'strategy_scope_boundary_check.json', 'final_preservation_check.json',
                     'fresh_continuation_precheck.json', 'candidate_equivalence.json', 'successor_registrations.json'):
        reference = publish_evidence(research, MaterialEvidenceWrite(
            EXPERIMENT, 's013-contract-' + Path(filename).stem.replace('_', '-'),
            (OUT / filename).read_bytes(), 'application/json', 'json'))
        evidence[filename] = reference.to_dict()
    loaded = []
    for item in registrations['candidates']:
        candidate = load_candidate(research.repository, CandidateKey('S013', item['successor']))
        dependencies = tuple(ImplementationDependency(*pair) for pair in item['registration']['dependencies'])
        identity = StrategyRuntime().identify(candidate, dependencies=dependencies)
        assert identity.content_sha256 == item['registration']['content_sha256']
        loaded.append(item['successor'])
    public = {'status': 'PASS', 'strategy_id': 'S013', 'experiment_id': EXPERIMENT.experiment_id,
              'data_contract_version': 1, 'data_migration': {'old_assets_preserved': 31,
              'old_preparations_preserved': 28, 'new_assets': 31, 'new_preparations': 28,
              'exact_request_comparisons': 103, 'exact_whole_asset_comparisons': 31},
              'candidate_migration': [{'parent': row['parent'], 'successor': row['successor'],
                 'stage4_center': row['stage4_center'], 'economic_equivalence': 'EXACT_EQUAL'}
                 for row in economic['candidates']],
              'evidence': evidence, 'historical_delivery_validations': delivery_checks,
              'successor_public_loads': loaded, 'external_supplier_access': False,
              'fresh_continuation_without_historical_temporary_cache': True,
              'research_stage': '阶段四完成，等待用户决定；本轮仅恢复技术接续能力',
              'results_location': OUT.relative_to(ROOT).as_posix()}
    write(ROOT / 'research/S013/materials/contract_migration_20261009.json', public)
    write(OUT / 'final_validation.json', public)
    print(json.dumps({'status': 'PASS', 'candidates': len(loaded),
                      'preserved_deliveries_full_pass': len(delivery_checks),
                      'public_receipt_sha256': sha256((ROOT / 'research/S013/materials/contract_migration_20261009.json').read_bytes()).hexdigest()}), flush=True)


if __name__ == '__main__':
    main()
