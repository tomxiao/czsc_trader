"""Apply the authenticated predecessor cycle audit to registered C9700."""
from __future__ import annotations

from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

# ruff: noqa: E402 -- prevent helper/candidate bytecode writes before imports
from czsc_trader.application import RepositoryContext, load_candidate
from strategy_manager import CandidateKey, StrategyRegistry
from strategy_runtime import StrategyRuntime


ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
HELPERS = HOME.parent / 'EX081_20261025/src'
EXPECTED = {
    'C9304': 'abf26e331cac4cd030c30aa5f84269e0471d3a4c31b36f5e9f8a0dbf687beda1',
    'C9700': '3f92791519e1f9422fef11bb5c9177db4d9d83e628ea5f5cba0ec684b9530d5f',
}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def candidate_facts(repository):
    registry = StrategyRegistry(repository.research_registry_root)
    values = {}
    for cid, expected in EXPECTED.items():
        key = CandidateKey('S015', cid)
        registration = registry.get_candidate_registration(key)
        candidate = load_candidate(repository, key)
        identity = StrategyRuntime().identify(candidate, dependencies=())
        assert identity.content_sha256 == registration.content_sha256 == expected
        values[cid] = {
            'content_sha256': identity.content_sha256,
            'source_sha256': identity.source_sha256,
            'registration_sha256': registration.record_sha256,
            'source_root': candidate.source_root.relative_to(ROOT).as_posix(),
            'source_files': {name: digest(candidate.source_root / name)
                             for name in candidate.payload['runtime']['source_files']},
        }
    return values


def main():
    report_path = HOME / 'others/inspection_report.json'
    design_path = HOME / 'others/pte_design.json'
    output = HOME / 'others/entry_cycle_audit.json'
    draft = ROOT / '.tmp/s015-ex082/entry_cycle_audit_draft.json'
    assert not output.exists() and not draft.exists(), 'Preserve existing audit outputs'
    report = json.loads(report_path.read_bytes())
    assert report['origin']['candidate'] == {'type': 'CandidateKey', 'strategy_id': 'S015', 'candidate_id': 'C9700'}
    assert report['origin']['content_sha256'] == EXPECTED['C9700']
    design = json.loads(design_path.read_bytes())
    assert design['candidate'] == 'S015-C9700' and design['content_sha256'] == EXPECTED['C9700']
    repository = RepositoryContext.discover(ROOT)
    before = candidate_facts(repository)
    helper_paths = [HELPERS / name for name in ('audit_entry_cycle.py', 'audit_entry_cycle_v2.py')]
    helper_hashes = {path.relative_to(ROOT).as_posix(): digest(path) for path in helper_paths}
    sys.path.insert(0, str(HELPERS))
    helper = importlib.import_module('audit_entry_cycle_v2')
    base = importlib.import_module('audit_entry_cycle')
    assert Path(helper.__file__).resolve() == helper_paths[1].resolve()
    assert Path(base.__file__).resolve() == helper_paths[0].resolve()
    # The helper resolves public evidence relative to the same repository while
    # all report/design/output arguments explicitly target the new experiment.
    helper.main(report_path, design_path, draft)
    result = json.loads(draft.read_bytes())
    assert result['status'] == 'PASS'
    after = candidate_facts(repository)
    assert before == after, 'Candidate registration or authenticated source changed during audit'
    assert all(digest(ROOT / name) == expected for name, expected in helper_hashes.items())
    result['reuse_provenance'] = {
        'helper_source_sha256': helper_hashes,
        'helpers_unchanged_after_audit': True,
        'candidate_facts_before': before, 'candidate_facts_after': after,
        'candidate_registration_and_source_unchanged': True,
        'report_origin_verified': report['origin'],
        'method': 'Reuse the two unchanged EX081 public-evidence audit helpers with explicit EX082 report/design/output paths; scene labels remain protocol labels, not candidate identity.',
        'draft_audit_sha256': digest(draft),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'candidate_id': 'C9700',
                      'candidate_registration_and_source_unchanged': True,
                      'output': output.relative_to(ROOT).as_posix()}))


if __name__ == '__main__':
    main()
