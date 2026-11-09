# Risk ownership: E2E-03
"""One real serial/parallel inspection sequence, followed by exact-package freeze."""

import pytest
from strategy_manager import StrategyRegistry
from strategy_manager import freeze_contracts as f
from test_candidate_freeze import (
    _restore_inspection_request, inspected_candidate as inspected_candidate, inspection as inspection,
    fresh_inspection as fresh_inspection,
    fresh_completed as fresh_completed, managed_evaluation as managed_evaluation,
)




@pytest.mark.parametrize('fault_id', ['missing_input', 'future_input'])
def test_input_fault_is_rejected_by_real_pte_before_new_orders(inspection, frozen_seed_root, fault_id):
    """Input fault behavior belongs to the runtime; spawning is covered above."""
    from czsc_trader.application._inspection_candidate import _load_inspection_candidate
    from czsc_trader.application.inspection_inputs import copy_pte_inputs
    from czsc_trader.application.inspection_service import _copy_plan, _EvidenceStore, _package
    from czsc_trader.application.research_evidence import read_decision
    from paper_trading_engine.inspection import PteReleaseInspectionRequest
    from paper_trading_engine.inspection_runner import _run_scenario

    context, _, _ = inspection
    request = _restore_inspection_request(context.root, frozen_seed_root, full_protocol=True)
    candidate = _load_inspection_candidate(context, request.candidate)
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    store = _EvidenceStore(context, f.ResearchEvidenceOwner(
        request.candidate.strategy_id, request.experiment.experiment_id))
    origin = f.CandidateOrigin(registration.key, registration.content_sha256,
                               store.put_json(registration.to_dict()))
    plan = _copy_plan(context, request, registration, store, origin)
    workspace = context.root / '.tmp' / 'strategy-inspection' / ('fault-' + fault_id)
    release, verified = _package(context, plan, store, workspace / 'repository',
                                  read_decision(context.root, request.selection).subject)
    assert verified.release.strategy_family_id == candidate.strategy_family_id
    spaces, copies = copy_pte_inputs(request.research.data, request.protocol.pte, workspace, lambda: None)
    pte_request = PteReleaseInspectionRequest('fault-' + fault_id, workspace / 'repository', workspace,
        verified.release.release_id, release.release_sha256, release.package_sha256,
        spaces, copies, request.protocol.pte)
    fault = next(item for item in request.protocol.pte.failures if item.case_id == fault_id)
    scenario = request.protocol.pte.scenarios[0]
    outcome = _run_scenario(pte_request, scenario, workspace / 'scenario', restart=False, fault=fault)
    assert outcome['status'] == 'PASS', outcome
    assert outcome['code'] == fault.fault.value
    rejected = outcome['trace'][-1]
    assert rejected['event_id'] == 'enter:decision'
    assert rejected['expected_rejection'] == fault.fault.value
    assert rejected['actual_error']
    assert rejected['new_order_count'] == 0
