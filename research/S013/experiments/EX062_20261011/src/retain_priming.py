"""Retain completed input materialization; no financial calculation."""
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
    path = WORK / 'priming-v2/priming.json'
    proof = driver.read(path)
    assert proof['status'] == 'PASS' and len(proof['completed']) == 53
    assert proof['new_account_evaluations'] == proof['external_provider_calls'] == 0
    ref = publish_evidence(ctx, MaterialEvidenceWrite(driver.EXPERIMENT, 'local-subset-materialization-v2-complete', path.read_bytes(), 'application/json', 'json'))
    shutil.copyfile(path, FOLDER / 'protocols/local_subset_materialization.json')
    driver.write(FOLDER / 'protocols/local_subset_materialization_reference.json', ref.to_dict())
    print({'status': 'INPUTS_READY', 'exact_requests': 53,
           'local_source_calls': len(proof['local_pinned_provider_calls']), 'new_accounts': 0}, flush=True)


if __name__ == '__main__':
    main()
