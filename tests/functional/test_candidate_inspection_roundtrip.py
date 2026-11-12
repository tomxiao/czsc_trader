# Risk ownership: E2E-03
"""Real PTE input rejection against a shared authenticated release."""

from strategy_manager import StrategyRegistry
from strategy_manager import freeze_contracts as f
from test_candidate_freeze import (
    _restore_inspection_request, inspection as inspection,
    fresh_inspection as fresh_inspection,
    fresh_completed as fresh_completed, managed_evaluation as managed_evaluation,
)
def test_input_faults_are_rejected_by_real_pte_before_new_orders(inspection, frozen_seed_root):
    """Both input faults use the same package and distinct account databases."""
    from czsc_trader.application.inspection_inputs import copy_pte_inputs
    from czsc_trader.application.inspection_service import _copy_plan, _EvidenceStore, _package
    from czsc_trader.application.research_evidence import read_decision
    from paper_trading_engine.inspection import PteReleaseInspectionRequest
    from paper_trading_engine.inspection_runner import _run_scenario

    context, _, _ = inspection
    request = _restore_inspection_request(context.root, frozen_seed_root, full_protocol=True)
    registration = StrategyRegistry(context.research_registry_root).get_candidate_registration(request.candidate)
    store = _EvidenceStore(context, f.ResearchEvidenceOwner(
        request.candidate.strategy_id, request.experiment.experiment_id))
    origin = f.CandidateOrigin(registration.key, registration.content_sha256,
                               store.put_json(registration.to_dict()))
    plan = _copy_plan(context, request, registration, store, origin)
    run_id = 'input-faults'
    workspace = context.root / '.tmp' / 'strategy-inspection' / run_id
    release, verified = _package(context, plan, store, workspace / 'repository',
                                  read_decision(context.root, request.selection).subject)
    assert verified.release.strategy_family_id == request.candidate.strategy_id
    spaces, copies = copy_pte_inputs(request.research.data, request.protocol.pte, workspace, lambda: None)
    pte_request = PteReleaseInspectionRequest(run_id, workspace / 'repository', workspace,
        verified.release.release_id, release.release_sha256, release.package_sha256,
        spaces, copies, request.protocol.pte)
    scenario = request.protocol.pte.scenarios[0]
    faults = {item.case_id: item for item in request.protocol.pte.failures}
    outcomes = [
        (fault, _run_scenario(pte_request, scenario, workspace / fault.case_id, restart=False, fault=fault))
        for fault in (faults['missing_input'], faults['future_input'])
    ]
    for fault, outcome in outcomes:
        assert outcome['status'] == 'PASS', (fault.case_id, outcome)
        assert outcome['code'] == fault.fault.value, fault.case_id
        rejected = outcome['trace'][-1]
        assert rejected['event_id'] == 'enter:decision', fault.case_id
        assert rejected['expected_rejection'] == fault.fault.value, fault.case_id
        assert rejected['actual_error'], fault.case_id
        assert rejected['new_order_count'] == 0, fault.case_id
