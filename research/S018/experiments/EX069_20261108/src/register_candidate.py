"""Retain the new target-weight candidate; do not replace the frozen version."""
from pathlib import Path
import json

from czsc_trader.application import RepositoryContext, register_candidate, load_candidate, CandidateRegistrationRequest
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from candidate import build_candidate

ROOT = Path(__file__).resolve().parents[5]
EXP = Path(__file__).resolve().parents[1]


def main():
    candidate = build_candidate()
    repo = RepositoryContext.discover(ROOT)
    ref = EvidenceRef.from_dict(json.loads((EXP/'others/account_reference.json').read_text()))
    record = register_candidate(repo, CandidateRegistrationRequest(candidate,
        ExperimentRef('S018', EXP.name), (ref,), candidate.definition.dependencies))
    loaded = load_candidate(repo, candidate.key)
    assert loaded.content_identity == candidate.content_identity
    result = {'candidate_id': candidate.candidate_id,
              'content_sha256': record.content_sha256, 'source_sha256': record.source_sha256,
              'load_verified': True, 'stage_four_inherited': False,
              'frozen_version_changed': False, 'origin': record.origin.to_dict()}
    (EXP/'others/candidate_registration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
