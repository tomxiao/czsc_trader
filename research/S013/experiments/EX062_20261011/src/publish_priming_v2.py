"""Retain failed metadata assertion and publish exact-frame correction."""
from hashlib import sha256
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
    diagnosis = driver.read(WORK / 'priming/factor_diagnosis.json')
    assert diagnosis['status'] == 'READONLY_PASS'
    source = WORK / 'prime_existing_assets_v2.py'
    assert not (driver.WORK / 'checkpoint.json').exists()
    paths = {'factor-provenance-diagnosis': WORK / 'priming/factor_diagnosis.json',
             'factor-provenance-diagnosis-source': WORK / 'priming/factor_diagnosis.py',
             'failed-subset-attempt1': WORK / 'priming/failure-1791702401631532900.json',
             'local-subset-materializer-v2-source': source,
             'local-subset-v2-publication-source': Path(__file__)}
    refs = {}
    for name, path in paths.items():
        suffix = path.suffix[1:]
        media = 'text/x-python' if suffix == 'py' else 'application/json'
        refs[name] = publish_evidence(ctx, MaterialEvidenceWrite(driver.EXPERIMENT, name, path.read_bytes(), media, suffix)).to_dict()
    for path in (source, Path(__file__), WORK / 'priming/factor_diagnosis.py'):
        shutil.copyfile(path, FOLDER / 'src' / path.name)
    shutil.copyfile(WORK / 'priming/factor_diagnosis.json', FOLDER / 'protocols/factor_diagnosis.json')
    shutil.copyfile(WORK / 'priming/failure-1791702401631532900.json', FOLDER / 'protocols/failed_subset_attempt1.json')
    amendment = {'status': 'PROSPECTIVE_TECHNICAL_CORRECTION_V2', 'method_reference': method.to_dict(),
        'materials': refs, 'source_sha256': sha256(source.read_bytes()).hexdigest(),
        'coverage_sha256': diagnosis['coverage_sha256'], 'new_account_evaluations': 0,
        'economic_method_changes': [],
        'reason': 'Existing narrow HFQ asset and wide source subset have exactly identical eight columns and dtypes, but factor-query provenance hashes describe different full date-series. First priming attempt made no provider calls before rejecting this existing provenance difference.',
        'validation': 'Every materialized full frame/content must remain exact; adjustment/basis/anchor/source/schedule remain exact. Record both factor-query hashes and their PreparedDataRef separately, never fabricate equal provenance. No re-adjustment or changed financial source/parameters/warmup/geometry.',
        'preservation': 'Retain v1 failed priming and prior failed declaration; no automatic replay, no omitted or replaced points.'}
    driver.write(FOLDER / 'protocols/local_subset_correction_v2.json', amendment)
    payload = (FOLDER / 'protocols/local_subset_correction_v2.json').read_bytes()
    ref = publish_evidence(ctx, MaterialEvidenceWrite(driver.EXPERIMENT, 'explicit-local-subset-correction-v2', payload, 'application/json', 'json'))
    driver.write(FOLDER / 'protocols/local_subset_correction_v2_reference.json', ref.to_dict())
    print({'status': 'CORRECTION_V2_PUBLISHED', 'new_accounts': 0,
           'source_sha256': amendment['source_sha256'], 'coverage_sha256': amendment['coverage_sha256']}, flush=True)


if __name__ == '__main__':
    main()
