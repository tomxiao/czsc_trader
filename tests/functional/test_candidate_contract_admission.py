# Risk ownership: TDR-22
from dataclasses import replace
from hashlib import sha256

import pytest

from czsc_trader.application import (
    freeze_candidate,
)
from czsc_trader.application._inspection_candidate import _load_inspection_candidate
from strategy_manager import freeze_contracts as f
from test_candidate_freeze import (
    approve, inspection as inspection, managed_evaluation as managed_evaluation,
)




@pytest.mark.parametrize('case', ['legacy_contract'])
def test_TDR_22_C04_prior_passing_inspection_cannot_bypass_current_freeze_admission(
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
    candidate = _load_inspection_candidate(context, report.plan.origin.candidate)
    payload = dict(candidate.payload)
    if case == 'legacy_contract':
        payload['runtime'] = {**dict(payload['runtime']), 'contract_version': 1}
        message = 'contract version 2'
    else:
        payload.pop('decision_feedback')
        message = 'feedback semantics'
    historical = replace(candidate, payload=payload)
    monkeypatch.setattr(inspection_service, '_load_inspection_candidate', lambda *args: historical)
    before = {path.relative_to(context.root).as_posix(): sha256(path.read_bytes()).hexdigest()
              for path in context.root.rglob('*') if path.is_file()}
    with pytest.raises(ValueError, match=message):
        freeze_candidate(context, operation)
    after = {path.relative_to(context.root).as_posix(): sha256(path.read_bytes()).hexdigest()
             for path in context.root.rglob('*') if path.is_file()}
    assert after == before
    assert not context.strategy_root.exists()


def test_TDR_22_C05_committed_freeze_retry_precedes_current_candidate_admission(inspected_candidate, monkeypatch):
    from czsc_trader.application import inspection_service

    context, report, source = inspected_candidate
    operation = approve(context, report, source)
    receipt = freeze_candidate(context, operation)
    assert receipt.status is f.FreezeStatus.COMMITTED

    def forbidden(*args):
        pytest.fail('a committed freeze must return its receipt without re-admitting the candidate')

    monkeypatch.setattr(inspection_service, '_load_inspection_candidate', forbidden)
    assert freeze_candidate(context, operation) == receipt
