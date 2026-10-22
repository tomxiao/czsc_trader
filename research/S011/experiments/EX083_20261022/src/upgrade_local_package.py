"""One-off, explicitly authorized S011-v1 input-coverage repair.

This is a local publication maintenance operation, not a contract migration or
PTE deployment. Only the exact inspected C9902 package is eligible. Old release
bytes and metadata remain in the content-addressed revisions archive.
"""
from dataclasses import replace
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import shutil

from strategy_manager import StrategyRegistry, StrategyVersion, CandidateKey, canonical_sha256
from strategy_manager import freeze_contracts as f
from strategy_manager.write_lock import RegistryWriteLock
from strategy_runtime import load_strategy_deployment
from czsc_trader.application import RepositoryContext, load_candidate
from czsc_trader.application.research_evidence import validate_inspection, read_decision
from czsc_trader.application.runtime_migration import (
    _upgrade_files, _upgrade_json, _upgrade_write, _validated_upgrade_archive,
)
from czsc_trader.application.strategy_runtime_service import validate_release_package

ROOT = Path(__file__).resolve().parents[5]
EX = ROOT / 'research/S011/experiments/EX083_20261022'
ORIGINAL = f.FrozenVersionReference('S011', 'v1',
    'fee15dd2fcae4484df7610f8aadbec0ab2682da55e608bc0deaa2a080000a535',
    '483b20888a57ad548adb21090dd0ee3c4c8f1566cf2b63d39a57d6c09b891615')
CONTENT = 'e3b172664d26eb396528dac9ccc812434c2314b465c25eaf60f459c909fb7a12'
KEY = CandidateKey('S011', 'C9902')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def plain(value):
    return json.loads(json.dumps(dict(value), default=dict))


def checked_report():
    repository = RepositoryContext.discover(ROOT)
    raw = f.CandidateInspectionReport.from_dict(read(EX / 'others/inspection_report.json'))
    report = validate_inspection(ROOT, raw.reference)
    require(report.status is f.InspectionStatus.PASS, 'both technical goals must pass')
    decision = read_decision(ROOT, report.selection)
    registration = StrategyRegistry(repository.research_registry_root).get_candidate_registration(KEY)
    require(registration.content_sha256 == CONTENT, 'candidate content differs')
    require(decision.subject == f.CandidateSelectionSubject(KEY, CONTENT, registration.record_sha256),
            'selected candidate differs')
    authorization = read(decision.confirmation_source.resolve(ROOT))
    require(authorization['user_request_verbatim'] == '请做原地升级，保持策略ID为S011-v1'
            and authorization['user_reply_verbatim'] == '仅升级 S011-v1 发布包，PTE 另行处理',
            'explicit local-only authorization differs')
    version = StrategyVersion.from_dict(read(report.release.version_record.resolve(ROOT)))
    require((version.release_id, version.version, version.parent_version, version.source_candidate,
             version.source_experiment, version.selection_data_cutoff, version.forward_start) ==
            ('S011-v1', 'v1', None, 'C9902', 'EX080_20261022', '2026-10-21', '2026-10-22'),
            'inspected revision provenance differs')
    candidate = load_candidate(repository, KEY)
    require(plain(version.strategy_payload) == plain(candidate.payload), 'payload differs from candidate')
    return report, decision, candidate, version


def prepare(context, workspace):
    require(workspace.resolve().is_relative_to((ROOT / '.tmp').resolve()), 'scratch must stay under .tmp')
    require(not workspace.exists(), 'preparation already exists')
    report, decision, candidate, version = checked_report()
    manifest, binding, source = validate_release_package(context, 'S011-v1')
    require((manifest['strategy_version_hash'], manifest['package_hash']) ==
            (ORIGINAL.release_hash, ORIGINAL.package_hash), 'original CAS differs')
    original_version = StrategyRegistry(context.strategy_root).get_version('S011', 'v1')
    original_payload = json.loads(json.dumps(dict(original_version.strategy_payload), default=dict))
    expected_payload = json.loads(json.dumps(original_payload))
    expected_payload['runtime']['source_sha256'] = candidate.payload['runtime']['source_sha256']
    require(expected_payload == plain(candidate.payload), 'repair changed parameters or runtime contract')
    # Whitelist all source changes, including their exact occurrence counts.
    strategy = 'strategies/s011_reversal.py'
    old_text = (source / strategy).read_text(encoding='utf-8')
    replacements = (
        ("'159326.SZ', 'daily', 30, CutoffRule.SIGNAL_SESSION", "'159326.SZ', 'daily', 20, CutoffRule.SIGNAL_SESSION"),
        ("'159326.SZ', '30m', 30, CutoffRule.SIGNAL_SESSION", "'159326.SZ', '30m', 20, CutoffRule.SIGNAL_SESSION"),
        ("'000300.SH', 'daily', 30, CutoffRule.SIGNAL_SESSION", "'000300.SH', 'daily', 21, CutoffRule.SIGNAL_SESSION"),
    )
    for before, after in replacements:
        require(old_text.count(before) == 1, 'source repair scope differs')
        old_text = old_text.replace(before, after)
    require(old_text == (candidate.source_root / strategy).read_text(encoding='utf-8'), 'unreviewed strategy edits')
    require((source / 'calculation.py').read_bytes() == (candidate.source_root / 'calculation.py').read_bytes(),
            'helper source changed')
    stage = workspace / 'staged'
    package = stage / 'S011/releases/v1'
    package.mkdir(parents=True)
    for item in report.release.files:
        target = package / item.path
        require(target.resolve().is_relative_to(package.resolve()), 'unsafe package path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.source.resolve(ROOT).read_bytes())
    (package / 'release_manifest.json').write_bytes(report.release.manifest.resolve(ROOT).read_bytes())
    (stage / 'S011/versions').mkdir()
    (stage / 'S011/versions/v1.json').write_bytes(report.release.version_record.resolve(ROOT).read_bytes())
    deployed = load_strategy_deployment(context.strategy_root, 'S011-v1')
    require((deployed.release_hash, deployed.package_hash) == (ORIGINAL.release_hash, ORIGINAL.package_hash),
            'original local deployment receipt differs')
    deployment_path = context.strategy_root / 'deployments/S011-v1.json'
    receipt = read(deployment_path)
    receipt.update(strategy_version_hash=version.release_hash, package_hash=report.release.package_sha256)
    receipt.pop('receipt_hash')
    receipt['receipt_hash'] = canonical_sha256(receipt)
    (stage / 'deployments').mkdir()
    (stage / 'deployments/S011-v1.json').write_bytes(_upgrade_json(receipt))
    validate_release_package(replace(context, strategy_root=stage), 'S011-v1')
    load_strategy_deployment(stage, 'S011-v1')
    new_binding = read(package / 'runtime_binding.json')
    require({k:v for k,v in new_binding.items() if k not in ('release_hash','implementation_sha256')} ==
            {k:v for k,v in binding.items() if k not in ('release_hash','implementation_sha256')},
            'binding contracts changed')
    plan = {'schema_version': 1, 'status': 'PREPARED_SAME_VERSION_UPGRADE',
        'upgrade_kind': 'AUTHORIZED_S011_INPUT_COVERAGE_REPAIR',
        'original': ORIGINAL.to_dict(),
        'migrated': f.FrozenVersionReference('S011', 'v1', version.release_hash, report.release.package_sha256).to_dict(),
        'candidate': KEY.to_dict(), 'inspection': report.reference.to_dict(),
        'confirmation': decision.confirmation_source.to_dict(), 'files': _upgrade_files(stage),
        'original_version_sha256': sha256((context.strategy_root / 'S011/versions/v1.json').read_bytes()).hexdigest(),
        'original_deployment_sha256': sha256(deployment_path.read_bytes()).hexdigest(),
        'original_package_files': _upgrade_files(context.strategy_root / 'S011/releases/v1'),
        'qualification': 'RESEARCH', 'production_writes': 0}
    (workspace / 'upgrade_plan.json').write_bytes(_upgrade_json(plan))
    return plan


def apply(context, workspace, *, inject_failure=False):
    report, decision, candidate, version = checked_report()
    stage = workspace / 'staged'
    plan_path = workspace / 'upgrade_plan.json'
    plan = read(plan_path)
    digest = sha256(plan_path.read_bytes()).hexdigest()
    require(plan['original'] == ORIGINAL.to_dict() and plan['inspection'] == report.reference.to_dict()
            and plan['confirmation'] == decision.confirmation_source.to_dict(), 'upgrade plan provenance differs')
    require(plan['migrated'] == f.FrozenVersionReference('S011', 'v1', version.release_hash,
            report.release.package_sha256).to_dict(), 'planned new identity differs from inspected release')
    require(_upgrade_files(stage) == plan['files'], 'staged content changed')
    expected = {item.path: item.source.resolve(ROOT).read_bytes() for item in report.release.files}
    expected['release_manifest.json'] = report.release.manifest.resolve(ROOT).read_bytes()
    require(_upgrade_files(stage / 'S011/releases/v1') == {k:sha256(v).hexdigest() for k,v in expected.items()},
            'stage is not the exact inspected package')
    require((stage / 'S011/versions/v1.json').read_bytes() == report.release.version_record.resolve(ROOT).read_bytes(),
            'stage version is not the exact inspected version')
    root = context.strategy_root
    package, version_path, deployment = root/'S011/releases/v1', root/'S011/versions/v1.json', root/'deployments/S011-v1.json'
    archive = root / 'revisions/S011-v1' / ORIGINAL.release_hash
    with RegistryWriteLock(root).hold():
        require(not archive.exists(), 'revision archive already exists')
        require(sha256(version_path.read_bytes()).hexdigest() == plan['original_version_sha256']
                and sha256(deployment.read_bytes()).hexdigest() == plan['original_deployment_sha256']
                and _upgrade_files(package) == plan['original_package_files'], 'original changed after preparation')
        manifest, _, _ = validate_release_package(context, 'S011-v1')
        require((manifest['strategy_version_hash'], manifest['package_hash']) ==
                (ORIGINAL.release_hash, ORIGINAL.package_hash), 'locked original identity differs')
        old_version, old_receipt = version_path.read_bytes(), deployment.read_bytes()
        archived = archive / 'strategies'
        shutil.copytree(package, archived / 'S011/releases/v1')
        (archived / 'S011/versions').mkdir()
        (archived / 'S011/versions/v1.json').write_bytes(old_version)
        (archived / 'deployments').mkdir()
        (archived / 'deployments/S011-v1.json').write_bytes(old_receipt)
        (archive / 'upgrade_plan.json').write_bytes(plan_path.read_bytes())
        (archive / 'snapshot.json').write_bytes(_upgrade_json({'original': ORIGINAL.to_dict(),
            'plan_sha256': digest, 'files': _upgrade_files(archive)}))
        require(_upgrade_files(archived/'S011/releases/v1') == plan['original_package_files'], 'backup differs')
        for path in archive.rglob('*'):
            if path.is_file():
                with path.open('r+b') as stream: os.fsync(stream.fileno())
        next_package = workspace / 'publishing_release'
        shutil.copytree(stage / 'S011/releases/v1', next_package)
        displaced = installed = False
        try:
            os.replace(package, workspace / 'displaced_release'); displaced = True
            os.replace(next_package, package); installed = True
            _upgrade_write(version_path, (stage/'S011/versions/v1.json').read_bytes(), workspace)
            if inject_failure: raise RuntimeError('controlled failure after version replacement')
            _upgrade_write(deployment, (stage/'deployments/S011-v1.json').read_bytes(), workspace)
            validate_release_package(context, 'S011-v1')
            actual = load_strategy_deployment(root, 'S011-v1')
            require((actual.release_hash, actual.package_hash) == (version.release_hash, report.release.package_sha256),
                    'installed identity differs')
            require(StrategyRegistry(root).current_qualification('S011','v1').value == 'RESEARCH', 'old qualification inherited')
            receipt = {'status': 'COMMITTED', 'original': ORIGINAL.to_dict(), 'migrated': plan['migrated'],
                'plan_sha256': digest, 'inspection': plan['inspection'], 'confirmation': plan['confirmation'],
                'qualification': 'RESEARCH', 'production_writes': 0}
            _upgrade_write(archive/'upgrade_receipt.json', _upgrade_json(receipt), workspace)
            _validated_upgrade_archive(context, ORIGINAL, plan_sha256=digest)
        except BaseException as error:
            (archive/'upgrade_receipt.json').unlink(missing_ok=True)
            if installed: os.replace(package, workspace/'failed_release')
            if displaced: os.replace(workspace/'displaced_release', package)
            _upgrade_write(version_path, old_version, workspace)
            _upgrade_write(deployment, old_receipt, workspace)
            validate_release_package(context, 'S011-v1')
            (archive/'rollback.json').write_bytes(_upgrade_json({'status':'ROLLED_BACK','error':str(error)}))
            raise
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare','apply'))
    args = parser.parse_args()
    context = RepositoryContext.discover(ROOT)
    workspace = ROOT/'.tmp/s011-v1-authorized-repair'
    result = prepare(context, workspace) if args.mode == 'prepare' else apply(context, workspace)
    output = EX/'others'/('local_upgrade_plan.json' if args.mode == 'prepare' else 'local_upgrade_receipt.json')
    output.write_bytes(_upgrade_json(result))
    print(json.dumps(result, ensure_ascii=False))
