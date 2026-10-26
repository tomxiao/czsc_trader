"""Real PTE expectation failure using the shared immutable inspection input seed."""
from dataclasses import replace
from strategy_manager import freeze_contracts as f
from czsc_trader.application import inspect_candidate
from test_candidate_freeze import (
    _assert_not_freezable, inspection as inspection,
    fresh_inspection as fresh_inspection, fresh_completed as fresh_completed,
    managed_evaluation as managed_evaluation,
)


def test_wrong_pte_expectation_fails_real_runtime_and_blocks_freeze(inspection):
    context, request, _ = inspection
    pte = request.protocol.pte
    scenario = pte.scenarios[0]
    wrong = replace(scenario.checkpoints[-1], position_quantity=100)
    scenario = replace(scenario, checkpoints=(*scenario.checkpoints[:-1], wrong))
    # The full serial/parallel roundtrip owns the generic PTE fault matrix.
    # This negative scenario targets its deliberately wrong economic checkpoint.
    request = replace(request, protocol=replace(request.protocol, pte=replace(pte, scenarios=(scenario,), failures=())))
    report = inspect_candidate(context, request)
    assert report.behavior_equivalence.status is f.InspectionStatus.PASS
    assert report.pte_runtime.status is f.InspectionStatus.FAIL
    assert next(case for case in report.pte_runtime.cases
                if case.case_id == scenario.scenario_id).status is f.InspectionStatus.FAIL
    assert report.status is f.InspectionStatus.FAIL
    _assert_not_freezable(context, report)
