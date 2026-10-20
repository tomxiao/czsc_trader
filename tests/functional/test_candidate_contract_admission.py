from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import shutil

import pytest

from czsc_trader.application import (
    CandidateRegistrationRequest, RepositoryContext, freeze_candidate, load_candidate,
    register_candidate,
)
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from strategy_manager import freeze_contracts as f
from strategy_runtime import StrategyCandidate
from test_candidate_freeze import (
    approve, inspection as inspection, managed_evaluation as managed_evaluation,
)


@pytest.mark.parametrize('case', ['legacy_contract', 'undeclared_feedback'])
def test_new_registration_rejects_incomplete_runtime_contract_before_writes(
    minimal_repo, candidate_payload, case,
):
    payload, source = candidate_payload
    payload = deepcopy(payload)
    if case == 'legacy_contract':
        payload['runtime']['contract_version'] = 1
        message = 'contract version 2'
    else:
        payload.pop('decision_feedback')
        message = 'feedback declaration'
    target = minimal_repo / '.tmp/source/strategy_runtime'
    shutil.copytree(source, target)
    candidate = StrategyCandidate('S900', 'C0001', payload, target)
    owner = ExperimentRef('S900', 'EX001_20261020')
    evidence = EvidenceRef(owner, 'a' * 64 + '.json', 'a' * 64,
                           'application/json', 'not-read-on-contract-failure')
    with pytest.raises(ValueError, match=message):
        register_candidate(RepositoryContext.discover(minimal_repo),
                           CandidateRegistrationRequest(candidate, owner, (evidence,), ()))
    assert not (minimal_repo / 'research').exists()


@pytest.mark.parametrize('case', ['legacy_contract', 'undeclared_feedback'])
def test_prior_passing_inspection_cannot_bypass_current_freeze_admission(
    inspected_candidate, case, monkeypatch,
):
    """A valid report/approval cannot exempt the loaded candidate at publication.

    The candidate read boundary supplies a historical contract. Inspection and
    approval verification remain real; the assertion includes every file byte
    so rejection after creating a freeze stage would not pass this regression.
    """
    from czsc_trader.application import inspection_service

    context, report, source = inspected_candidate
    assert report.status is f.InspectionStatus.PASS
    operation = approve(context, report, source)
    candidate = load_candidate(context, report.plan.origin.candidate)
    payload = dict(candidate.payload)
    if case == 'legacy_contract':
        payload['runtime'] = {**dict(payload['runtime']), 'contract_version': 1}
        message = 'contract version 2'
    else:
        payload.pop('decision_feedback')
        message = 'feedback semantics'
    historical = replace(candidate, payload=payload)
    monkeypatch.setattr(inspection_service, 'load_candidate', lambda *args: historical)
    before = {path.relative_to(context.root).as_posix(): sha256(path.read_bytes()).hexdigest()
              for path in context.root.rglob('*') if path.is_file()}
    with pytest.raises(ValueError, match=message):
        freeze_candidate(context, operation)
    after = {path.relative_to(context.root).as_posix(): sha256(path.read_bytes()).hexdigest()
             for path in context.root.rglob('*') if path.is_file()}
    assert after == before
    assert not context.strategy_root.exists()


def test_committed_freeze_retry_precedes_current_candidate_admission(inspected_candidate, monkeypatch):
    from czsc_trader.application import inspection_service

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED

    def forbidden(*args):
        pytest.fail('a committed freeze must return its receipt without re-admitting the candidate')

    monkeypatch.setattr(inspection_service, 'load_candidate', forbidden)
    assert freeze_candidate(context, operation) == receipt
