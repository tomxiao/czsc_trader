"""Evaluate explicit acceptance contracts against assessment facts; no policy defaults."""

import math
import operator
from decimal import Context, Decimal, localcontext

from . import research_models as m


def acceptance_status(checks):
    statuses = [x.status for x in checks]
    if m.TargetCheckStatus.FAILED in statuses:
        return m.TargetCheckStatus.FAILED
    if m.TargetCheckStatus.INDETERMINATE in statuses:
        return m.TargetCheckStatus.INDETERMINATE
    if m.TargetCheckStatus.PASSED in statuses:
        return m.TargetCheckStatus.PASSED
    return m.TargetCheckStatus.INDETERMINATE


def _scalar(target, metrics, benchmark, scenario, actual_window, requested_window):
    diagnostic = metrics.get(target.metric)
    observed = None if diagnostic is None else diagnostic.value
    sources = [] if diagnostic is None else list(diagnostic.evaluation_ids)
    lower = upper = condition_value = None

    def result(status, reason=None):
        return m.TargetCheck(
            target,
            observed,
            status,
            reason,
            lower,
            upper,
            condition_value,
            tuple(dict.fromkeys(sources)),
        )

    if target.one_way_cost is not None and (
        scenario is None or scenario.one_way_cost != target.one_way_cost
    ):
        return result(m.TargetCheckStatus.INDETERMINATE, "TARGET_COST_DIFFERS_OR_MISSING")
    if target.when is not None:
        condition = target.when
        item = benchmark.get(condition.metric)
        condition_value = None if item is None else item.value
        if item is not None:
            sources.extend(item.evaluation_ids)
        if condition_value is None:
            return result(m.TargetCheckStatus.INDETERMINATE, "MISSING_CONDITION_BENCHMARK")
        operations = {
            m.ComparisonOperator.LT: operator.lt,
            m.ComparisonOperator.LE: operator.le,
            m.ComparisonOperator.GT: operator.gt,
            m.ComparisonOperator.GE: operator.ge,
        }
        if not operations[condition.operator](condition_value, condition.value):
            return result(m.TargetCheckStatus.NOT_APPLICABLE, "CONDITION_FALSE")
    if target.metric in m.FREQUENCY_METRICS and actual_window != requested_window:
        return result(m.TargetCheckStatus.INDETERMINATE, "FREQUENCY_WINDOW_DIFFERS")
    if observed is None:
        return result(
            m.TargetCheckStatus.INDETERMINATE,
            "MISSING_SCENARIO_PERFORMANCE" if diagnostic is None else diagnostic.reason,
        )
    bounds = []
    for bound in (target.lower, target.upper):
        if isinstance(bound, m.BenchmarkBound):
            item = benchmark.get(target.metric)
            if item is None or item.value is None:
                return result(m.TargetCheckStatus.INDETERMINATE, "MISSING_BOUND_BENCHMARK")
            sources.extend(item.evaluation_ids)
            # Two float representations need at most 34 significant digits for an exact product.
            with localcontext(Context(prec=40)):
                value = float(Decimal(str(item.value)) * Decimal(str(bound.multiplier)))
            m.require(math.isfinite(value), "benchmark bound overflow")
            bounds.append(value)
        else:
            bounds.append(None if bound is None else bound.value)
    lower, upper = bounds
    passed = (
        lower is None or (observed >= lower if target.lower.inclusive else observed > lower)
    ) and (upper is None or (observed <= upper if target.upper.inclusive else observed < upper))
    return result(
        m.TargetCheckStatus.PASSED if passed else m.TargetCheckStatus.FAILED,
        None if passed else "TARGET_NOT_MET",
    )


def _performance_check(target, facts):
    if facts is None:
        return _scalar(target, {}, {}, None, None, None)

    def values(annual, drawdown):
        return {
            metric: m.DiagnosticValue(
                metric,
                m.MetricUnit.RATIO,
                m.DiagnosticStatus.AVAILABLE
                if value is not None
                else m.DiagnosticStatus.INSUFFICIENT_DATA,
                value,
                None if value is not None else "MISSING_BENCHMARK",
                (facts.evaluation_id,),
            )
            for metric, value in zip(m.BENCHMARK_METRICS, (annual, drawdown))
        }

    return _scalar(
        target,
        values(facts.annual_return, facts.drawdown),
        values(facts.benchmark_return, facts.benchmark_drawdown),
        facts.scenario,
        None,
        None,
    )


def _coverage(target, row, window):
    facts = row.frequency_coverage
    reason = None
    if facts is None:
        reason = "MISSING_FREQUENCY_COVERAGE"
    elif (
        facts.window_days != target.window_days
        or target.window_days != window
        or facts.minimum_closed_cycles != target.minimum_closed_cycles
    ):
        reason = "FREQUENCY_DEFINITION_DIFFERS"
    elif facts.total_windows == 0:
        reason = "INSUFFICIENT_FREQUENCY_WINDOW"
    if reason:
        return m.FrequencyCoverageCheck(target, facts, m.TargetCheckStatus.INDETERMINATE, reason)
    passed = (
        facts.covered_windows * target.minimum_denominator
        >= facts.total_windows * target.minimum_numerator
    )
    return m.FrequencyCoverageCheck(
        target,
        facts,
        m.TargetCheckStatus.PASSED if passed else m.TargetCheckStatus.FAILED,
        None if passed else "FREQUENCY_COVERAGE_NOT_MET",
    )


def _parameter_group(target, row):
    context = row.parameter_context
    if (
        type(context) is not m.ParameterDiagnosticContext
        or context.prescribed_points != target.required_points
    ):
        return m.ParameterGroupCheck(
            target,
            0,
            0,
            (),
            m.TargetCheckStatus.INDETERMINATE,
            "PARAMETER_DESIGN_MISSING_OR_DIFFERS",
        )
    points = tuple(
        m.ParameterPointCheck(
            facts.point_index,
            facts.candidate,
            facts.evaluation_id,
            tuple(_performance_check(x, facts) for x in target.joint_targets),
            tuple(_performance_check(x, facts) for x in target.all_point_targets),
        )
        for facts in sorted(row.parameter_performances, key=lambda x: x.point_index)
    )
    joint_passes = sum(
        acceptance_status(x.joint_checks) is m.TargetCheckStatus.PASSED for x in points
    )
    if any(acceptance_status(x.all_point_checks) is m.TargetCheckStatus.FAILED for x in points):
        status, reason = m.TargetCheckStatus.FAILED, "PARAMETER_ALL_POINT_TARGET_NOT_MET"
    elif (
        context.valid_points != target.required_points
        or len(points) != target.required_points
        or {x.point_index for x in points} != set(range(target.required_points))
    ):
        status, reason = m.TargetCheckStatus.INDETERMINATE, "INCOMPLETE_PARAMETER_COVERAGE"
    elif any(
        acceptance_status(checks) is m.TargetCheckStatus.INDETERMINATE
        for x in points
        for checks in (x.joint_checks, x.all_point_checks)
    ):
        status, reason = m.TargetCheckStatus.INDETERMINATE, "INDETERMINATE_PARAMETER_CONDITION"
    elif joint_passes < target.minimum_joint_passes:
        status, reason = m.TargetCheckStatus.FAILED, "PARAMETER_JOINT_COUNT_NOT_MET"
    else:
        status, reason = m.TargetCheckStatus.PASSED, None
    return m.ParameterGroupCheck(target, len(points), joint_passes, points, status, reason)


def _parameter_neighborhood(target, row):
    context = row.parameter_context
    if type(context) is not m.ParameterNeighborhoodContext:
        return m.ParameterNeighborhoodCheck(
            target,
            0,
            0,
            0,
            0,
            (),
            m.TargetCheckStatus.INDETERMINATE,
            "PARAMETER_NEIGHBORHOOD_MISSING_OR_DIFFERS",
        )
    if context.protocol.purpose is not m.StudyPurpose.LOCAL_SENSITIVITY:
        return m.ParameterNeighborhoodCheck(
            target,
            0,
            0,
            0,
            0,
            (),
            m.TargetCheckStatus.INDETERMINATE,
            "STRUCTURAL_CONTROL_NOT_ACCEPTANCE",
        )
    if not context.is_applicable:
        return m.ParameterNeighborhoodCheck(
            target, 0, 0, 0, 0, (), m.TargetCheckStatus.NOT_APPLICABLE,
            "NO_APPLICABLE_LOCAL_NEIGHBORHOOD",
        )
    required = context.prescribed_points
    minimum = (
        required * target.minimum_numerator + target.minimum_denominator - 1
    ) // target.minimum_denominator
    points = tuple(
        m.ParameterPointCheck(
            facts.point_index,
            facts.candidate,
            facts.evaluation_id,
            tuple(_performance_check(x, facts) for x in target.joint_targets),
            tuple(_performance_check(x, facts) for x in target.all_point_targets),
        )
        for facts in sorted(row.parameter_performances, key=lambda x: x.point_index)
    )
    joint_passes = sum(
        acceptance_status(x.joint_checks) is m.TargetCheckStatus.PASSED for x in points
    )
    if any(acceptance_status(x.all_point_checks) is m.TargetCheckStatus.FAILED for x in points):
        status, reason = m.TargetCheckStatus.FAILED, "PARAMETER_ALL_POINT_TARGET_NOT_MET"
    elif (
        context.valid_points != required
        or len(points) != required
        or {x.point_index for x in points} != set(range(required))
    ):
        status, reason = m.TargetCheckStatus.INDETERMINATE, "INCOMPLETE_PARAMETER_COVERAGE"
    elif any(
        acceptance_status(checks) is m.TargetCheckStatus.INDETERMINATE
        for x in points
        for checks in (x.joint_checks, x.all_point_checks)
    ):
        status, reason = m.TargetCheckStatus.INDETERMINATE, "INDETERMINATE_PARAMETER_CONDITION"
    elif joint_passes < minimum:
        status, reason = m.TargetCheckStatus.FAILED, "PARAMETER_JOINT_COUNT_NOT_MET"
    else:
        status, reason = m.TargetCheckStatus.PASSED, None
    return m.ParameterNeighborhoodCheck(
        target, required, minimum, len(points), joint_passes, points, status, reason
    )


def check_target(target, row, frequency_window_days):
    if isinstance(target, m.FrequencyCoverageTarget):
        return _coverage(target, row, frequency_window_days)
    if isinstance(target, m.ParameterGroupTarget):
        return _parameter_group(target, row)
    if isinstance(target, m.ParameterNeighborhoodTarget):
        return _parameter_neighborhood(target, row)
    if target.scope is m.TargetScope.STRESS:
        return _performance_check(target, row.stress_performance)
    return _scalar(
        target,
        {x.metric: x for x in row.diagnostics},
        {x.metric: x for x in row.benchmark.diagnostics},
        row.baseline_scenario,
        row.frequency_window_days,
        frequency_window_days,
    )
