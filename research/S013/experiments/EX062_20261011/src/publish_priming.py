"""Publish explicit local input-binding correction before materialization."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').exists())
WORK = ROOT / '.tmp/s013-robust-center'
FOLDER = ROOT / 'research/S013/experiments/EX062_20261011'
sys.path.insert(0, str(FOLDER / 'src'))
import driver  # noqa: E402
from czsc_trader.application import publish_evidence  # noqa: E402
from czsc_trader.research_tools import MaterialEvidenceWrite  # noqa: E402
from czsc_trader.research_tools.evidence import EvidenceRef  # noqa: E402


def main():
    method = EvidenceRef.from_dict(driver.read(WORK / 'method_reference.json'))
    ctx = driver.draft.existing_only_context(method, 1)
    coverage_path = WORK / 'priming/coverage.json'
    coverage = driver.read(coverage_path)
    source = WORK / 'prime_existing_assets.py'
    assert coverage['status'] == 'READONLY_COVERAGE_PASS'
    assert coverage['source_sha256'] == sha256(source.read_bytes()).hexdigest()
    assert coverage['role_count'] == 297 and coverage['standard_unique_configurations'] == 294
    assert not (driver.WORK / 'checkpoint.json').exists()
    items = {'failed-declare-attempt0': driver.WORK / 'failure.json',
             'local-subset-coverage': coverage_path,
             'local-subset-materializer-source': source,
             'local-subset-publication-source': Path(__file__)}
    refs = {}
    for name, path in items.items():
        suffix = path.suffix[1:]
        media = 'text/x-python' if suffix == 'py' else 'application/json'
        ref = publish_evidence(ctx, MaterialEvidenceWrite(driver.EXPERIMENT, name, path.read_bytes(), media, suffix))
        refs[name] = ref.to_dict()
    for path in (source, Path(__file__)):
        shutil.copyfile(path, FOLDER / 'src' / path.name)
    shutil.copyfile(coverage_path, FOLDER / 'protocols/local_subset_coverage.json')
    shutil.copyfile(driver.WORK / 'failure.json', FOLDER / 'protocols/failed_declare_attempt0.json')
    amendment = {'status': 'PROSPECTIVE_TECHNICAL_CORRECTION',
        'method_reference': method.to_dict(), 'materials': refs,
        'source_sha256': coverage['source_sha256'],
        'coverage_sha256': sha256(coverage_path.read_bytes()).hexdigest(),
        'new_account_evaluations_before_correction': 0,
        'economic_method_changes': [],
        'authorization': '用户授权自主完成S013研究；本修正仅从已授权旧资产显式准备所需子集，不访问外部数据，不改变经济规则。',
        'reason': 'Exact-request preparation cache lacked a narrower calendar key although pinned S013 assets fully cover all297 fixed roles.',
        'execution': 'Explicit separate public Dataflows materialization from pinned PreparedDataRef; compare every resulting frame exactly with old source, including adjustment metadata. Original financial driver/context remain unchanged and forbid provider calls.',
        'failure_preservation': 'Initial declaration FAILED before any financial evaluation; original failure retained as immutable evidence. No automatic retry, replacement or dropped point.'}
    payload = (json.dumps(amendment, ensure_ascii=False, indent=2) + '\n').encode()
    ref = publish_evidence(ctx, MaterialEvidenceWrite(driver.EXPERIMENT, 'explicit-local-subset-correction', payload, 'application/json', 'json'))
    driver.write(FOLDER / 'protocols/local_subset_correction.json', amendment)
    driver.write(FOLDER / 'protocols/local_subset_correction_reference.json', ref.to_dict())
    print({'status': 'CORRECTION_PUBLISHED', 'new_accounts': 0,
           'source_sha256': amendment['source_sha256'], 'coverage_sha256': amendment['coverage_sha256']}, flush=True)


if __name__ == '__main__':
    main()
