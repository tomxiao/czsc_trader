# Risk ownership: E2E-07
"""Real PTE expectation failure using the shared immutable inspection input seed."""
from dataclasses import replace
from strategy_manager import freeze_contracts as f
from czsc_trader.application import inspect_candidate
from test_candidate_freeze import (
    _assert_not_freezable, inspection as inspection,
    fresh_inspection as fresh_inspection, fresh_completed as fresh_completed,
    managed_evaluation as managed_evaluation,
)


def test_TDR_22_C06_wrong_pte_expectation_fails_real_runtime_and_blocks_freeze(inspection):
    context, request, _ = inspection
    pte = request.protocol.pte
    scenario = pte.scenarios[0]
    partial = next(item for item in scenario.checkpoints if item.after_event_id == 'entry_partial')
    wrong = replace(partial, position_quantity=100)
    # One real accepted order and its partial fill suffice to prove economic
    # checkpoint failures propagate through inspect_candidate and block freeze.
    # The canonical serial/parallel run owns recovery/continuous equivalence,
    # repeated reports, holding, exit and the generic fault matrix.
    scenario = replace(scenario, decisions=scenario.decisions[:1],
        channel_events=scenario.channel_events[:2], restart_after=(),
        checkpoints=tuple(item for item in scenario.checkpoints
                          if item.after_event_id in {'LOAD', 'enter:decision', 'enter:repeat', 'enter:submit'}) + (wrong,))
    request = replace(request, protocol=replace(request.protocol, pte=replace(pte, scenarios=(scenario,), failures=())))
    report = inspect_candidate(context, request)
    assert report.behavior_equivalence.status is f.InspectionStatus.PASS
    assert report.pte_runtime.status is f.InspectionStatus.FAIL
    failed = next(case for case in report.pte_runtime.cases if case.case_id == scenario.scenario_id)
    assert failed.status is f.InspectionStatus.FAIL
    assert 'entry_partial_check.position_quantity: expected 100, observed 50000' in failed.summary
    assert report.status is f.InspectionStatus.FAIL
    _assert_not_freezable(context, report)
