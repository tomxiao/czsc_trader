# Risk ownership: TDR-14
"""Declared execution plans prepare and bind only the requested points."""
from dataclasses import replace

import pytest

from czsc_trader.research_tools import ParameterEvaluationPlan
from czsc_trader.research_tools.parameter_evaluation import _plan_child
from strategy_evaluator import DeclaredParameterPointSet

from equity_parameter_support import equity_plan


def test_TDR_14_C04_declared_plan_covers_only_selected_source_points_and_binds_without_publication(tmp_path):
    with equity_plan(tmp_path) as (context, center, source, reference, children, execution):
        selected = DeclaredParameterPointSet(source.design, (1,), "d" * 64)
        child = context.evaluation.prepare(replace(children[1].request, lineage=None), execution=execution)
        plan = ParameterEvaluationPlan.create(selected, center, (child,),
            mapping_evidence=source.mapping_evidence, feasibility_evidence=source.feasibility_evidence,
            dataflows=context.data, execution=execution)
        assert len(plan.children) == 1 < source.design.point_count
        assert _plan_child(plan, 1).candidate.candidate_id == f"{child.candidate.strategy_id}-{child.candidate.candidate_id}"
        assert ParameterEvaluationPlan.from_dict(plan.to_dict()) == plan
        bound = plan.bind_point(reference, 1, child, execution=execution)
        assert bound.request.lineage.parameter_binding.point == source.design.bind_point(1)
        with pytest.raises(ValueError, match="point index"):
            plan.bind_point(reference, 0, child, execution=execution)


def test_TDR_14_X01_boolean_index_cannot_select_integer_key():
    from types import SimpleNamespace
    child = object()
    plan = SimpleNamespace(_children_by_point={1: child})
    with pytest.raises(ValueError, match="point index"):
        _plan_child(plan, True)
