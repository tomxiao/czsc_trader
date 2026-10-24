"""Deterministic research diagnostics. No evaluation scheduling or economic gates."""

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
from itertools import combinations
import math

import numpy as np

from . import research_models as m
from .research_acceptance import acceptance_status, check_target as _check_target
from .bootstrap import _paired_stationary_bootstrap_cagr
from .audit_models import ReturnMatrixEvidence
from .search_bias import annualized_sharpe, calculate_dsr_bundle, cscv_pbo, effective_trial_count


def _quantile(values, q, method, weights=None):
    values = np.asarray(values, dtype=float)
    if method is m.QuantileMethod.LINEAR:
        return float(np.quantile(values, q, method="linear"))
    weights = np.ones(len(values)) if weights is None else np.asarray(weights, dtype=float)
    weights = weights / weights.max()
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order] / weights.sum())
    return float(values[order[min(int(np.searchsorted(cumulative, q)), len(values) - 1)]])


def _performance(evidence):
    return _equity_performance([x.equity for x in evidence.account], evidence.initial_cash)


def _equity_performance(equity, initial_cash):
    equity = np.asarray(equity)
    wealth = np.r_[initial_cash, equity]
    annual = float((equity[-1] / initial_cash) ** (252 / len(equity)) - 1)
    drawdown = float(-np.min(wealth / np.maximum.accumulate(wealth) - 1))
    m.require(math.isfinite(annual), "annual return overflow")
    return annual, drawdown


def _performance_facts(evidence):
    annual, drawdown = _performance(evidence)
    benchmark = (_equity_performance(evidence.benchmark_equity, evidence.initial_cash)
                 if evidence.benchmark_equity else (None, None))
    return m.PerformanceFacts(evidence.candidate, evidence.evaluation_id, evidence.scenario_context,
        annual, drawdown, *benchmark,
        None if evidence.parameter_point is None else evidence.parameter_point.point_index)


def _returns(evidence):
    equity = np.asarray([x.equity for x in evidence.account])
    return equity / np.r_[evidence.initial_cash, equity[:-1]] - 1


def _concentration(evidence, tolerance):
    daily = defaultdict(list)
    for fill in evidence.fills:
        daily[fill.session].append(fill)
    cash, quantity = evidence.opening_cash, evidence.opening_quantity
    flows, quantities, last_dates = defaultdict(float), defaultdict(int), {}
    for row in evidence.account:
        for fill in daily[row.session]:
            side = 1 if fill.side is m.FillSide.BUY else -1
            flow = -side * fill.quantity * fill.price - fill.fees
            cash += flow
            quantity += side * fill.quantity
            flows[fill.cycle_id] += flow
            quantities[fill.cycle_id] += side * fill.quantity
            last_dates[fill.cycle_id] = row.session
        if (
            quantity != row.quantity
            or abs(cash - row.cash) > tolerance
            or abs(row.cash + row.quantity * row.close - row.equity) > tolerance
        ):
            return None, m.DiagnosticStatus.FAILED, "ACCOUNT_RECONCILIATION_FAILED"
    closed = {x.cycle_id: x for x in evidence.closed_cycles}
    if evidence.opening_quantity and any(quantities[key] < 0 for key in closed):
        return (
            None,
            m.DiagnosticStatus.INSUFFICIENT_DATA,
            "OPENING_POSITION_COST_ATTRIBUTION_MISSING",
        )
    if any(
        key not in flows or quantities[key] != 0 or last_dates[key] != cycle.exit_session
        for key, cycle in closed.items()
    ) or any(qty < 0 or (qty == 0 and key not in closed) for key, qty in quantities.items()):
        return None, m.DiagnosticStatus.FAILED, "CLOSED_CYCLE_RECONCILIATION_FAILED"
    # Open cycles retain both realized cash flows and the terminal marked position.
    closed_pnl = sum(flows[key] for key in closed)
    open_pnl = sum(
        flows[key] + quantities[key] * evidence.account[-1].close
        for key in flows
        if key not in closed
    )
    opening_adjustment = (
        evidence.opening_cash
        - evidence.initial_cash
        + evidence.opening_quantity * evidence.account[-1].close
    )
    if (
        abs(
            closed_pnl
            + open_pnl
            + opening_adjustment
            - (evidence.account[-1].equity - evidence.initial_cash)
        )
        > tolerance
    ):
        return None, m.DiagnosticStatus.FAILED, "PNL_RECONCILIATION_FAILED"
    winners = sorted((flows[key] for key in closed if flows[key] > 0), reverse=True)
    if not winners:
        return None, m.DiagnosticStatus.NOT_APPLICABLE, "NO_PROFITABLE_CLOSED_CYCLES"
    return (
        float(sum(winners[: math.ceil(0.1 * len(winners))]) / sum(winners)),
        m.DiagnosticStatus.AVAILABLE,
        None,
    )


def _family(request):
    family = request.family_returns
    names = ("PBO", "DSR_RAW", "DSR_EFFECTIVE")
    if family is None:
        return tuple(
            m.FamilyDiagnostic(
                n, m.DiagnosticStatus.INSUFFICIENT_DATA, None, "FAMILY_RETURN_MATRIX_NOT_SUPPLIED"
            )
            for n in names
        ), ()
    matrix = np.asarray(family.returns, dtype=float)
    base = {(x.candidate, x.window_id, x.scenario_id): x for x in request.evidence}
    contexts = set()
    for column, candidate in enumerate(family.candidates):
        evidence = base.get(
            (candidate, request.protocol.baseline_window, request.protocol.standard_scenario)
        )
        m.require(evidence is not None, "family matrix requires matching evaluation evidence")
        m.require(
            tuple(x.session for x in evidence.account) == family.sessions
            and np.array_equal(_returns(evidence), matrix[:, column]),
            "family returns differ from account",
        )
        contexts.add((evidence.context_sha256, evidence.metric_version, evidence.scenario_context))
    m.require(len(contexts) == 1, "family return comparison contexts differ")
    values = []

    def append(name, operation):
        try:
            value = float(operation())
            m.require(math.isfinite(value), "nonfinite statistic")
            values.append(m.FamilyDiagnostic(name, m.DiagnosticStatus.AVAILABLE, value, None))
        except (ValueError, FloatingPointError, ZeroDivisionError) as exc:
            values.append(
                m.FamilyDiagnostic(name, m.DiagnosticStatus.INSUFFICIENT_DATA, None, str(exc))
            )

    evidence = ReturnMatrixEvidence(
        family.sessions, tuple(c.candidate_id for c in family.candidates), family.returns, ""
    )
    append("PBO", lambda: cscv_pbo(evidence, request.protocol.pbo_blocks).pbo)

    try:
        sharpes = np.array([annualized_sharpe(matrix[:, i]) for i in range(matrix.shape[1])])
        selected = matrix[:, family.candidates.index(family.selected)]
        bundle = calculate_dsr_bundle(
            selected,
            sharpes,
            raw_count=family.raw_trial_count,
            effective_count=effective_trial_count(matrix),
        )
    except (ValueError, FloatingPointError, ZeroDivisionError) as exc:
        for name in ("DSR_RAW", "DSR_EFFECTIVE"):
            values.append(
                m.FamilyDiagnostic(name, m.DiagnosticStatus.INSUFFICIENT_DATA, None, str(exc))
            )
    else:
        append("DSR_RAW", lambda: bundle.raw.probability)
        append("DSR_EFFECTIVE", lambda: bundle.effective.probability)
    return tuple(values), family.limitations


def assess_candidates(request: m.CandidateAssessmentRequest) -> m.AssessmentPanel:
    if type(request) is not m.CandidateAssessmentRequest:
        raise TypeError("assess_candidates requires CandidateAssessmentRequest")
    m.require(isinstance(request.protocol, m.NeighborhoodSelfCheckProtocol)
              and request.protocol.parameter_protocol.version == "parameter-cartesian-neighborhood-v2",
              "historical assessment protocols are read-only")
    return _assess_candidates(request)


def recompute_historical_assessment(request: m.CandidateAssessmentRequest) -> m.AssessmentPanel:
    """Recompute stored v5/v6 evidence without upgrading its protocol or identity."""
    if type(request) is not m.CandidateAssessmentRequest:
        raise TypeError("historical assessment requires CandidateAssessmentRequest")
    m.require(isinstance(request.protocol, m.SelfCheckProtocol) or (
        isinstance(request.protocol, m.NeighborhoodSelfCheckProtocol)
        and request.protocol.parameter_protocol.version == "parameter-cartesian-neighborhood-v1"
    ), "historical assessment requires a historical protocol")
    return _assess_candidates(request)


def _assess_candidates(request: m.CandidateAssessmentRequest) -> m.AssessmentPanel:
    if type(request) is not m.CandidateAssessmentRequest:
        raise TypeError("assess_candidates requires CandidateAssessmentRequest")
    # Revalidate at the public boundary, including values restored from storage.
    request = m.CandidateAssessmentRequest.from_dict(request.to_dict())
    p = request.protocol
    evidence = {(x.candidate, x.window_id, x.scenario_id): x for x in request.evidence}
    rows = []
    for center in request.centers:
        base = evidence.get((center, p.baseline_window, p.standard_scenario))
        gaps = [
            f"{x.candidate.candidate_id}:{x.window_id}:{x.scenario_id}:{x.status.value}:{x.reason}"
            for x in request.incomplete
            if x.candidate == center
            or any(
                link.parent == center and link.child == x.candidate
                for link in request.perturbations
            )
        ]
        diagnostics = {}
        coverage = None
        point_facts = ()
        stress_facts = None

        def put(
            metric,
            value=None,
            status=m.DiagnosticStatus.INSUFFICIENT_DATA,
            reason="MISSING_BASELINE",
            sources=(),
        ):
            unit = (
                m.MetricUnit.CLOSED_CYCLES_PER_WINDOW
                if metric in m.FREQUENCY_METRICS and metric is not m.ResearchMetric.FREQUENCY_COVERAGE
                else m.MetricUnit.RATIO
            )
            diagnostics[metric] = m.DiagnosticValue(
                metric,
                unit,
                m.DiagnosticStatus.AVAILABLE if value is not None else status,
                None if value is None else float(value),
                None if value is not None else reason,
                tuple(x.evaluation_id for x in sources),
            )

        for metric in m.ResearchMetric:
            put(metric)
        interval = m.UncertaintyInterval(
            m.DiagnosticStatus.INSUFFICIENT_DATA, None, None, "MISSING_BASELINE"
        )
        if base is not None:
            annual, drawdown = _performance(base)
            put(m.ResearchMetric.NET_ANNUAL_RETURN, annual, sources=(base,))
            put(m.ResearchMetric.DRAWDOWN_MAGNITUDE, drawdown, sources=(base,))
            sessions = tuple(x.session for x in base.account)
            size = base.frequency_window_days
            put(
                m.ResearchMetric.FULL_SAMPLE_FREQUENCY,
                size * len(base.closed_cycles) / len(sessions),
                sources=(base,),
            )
            if base.benchmark_equity:
                years = defaultdict(list)
                for session, equity in zip(sessions, base.benchmark_equity):
                    years[session[:4]].append(equity)
                opening = base.initial_cash
                positive_years = set()
                for year, equity in years.items():
                    if equity[-1] > opening:
                        positive_years.add(year)
                    opening = equity[-1]
                positive_days = sum(session[:4] in positive_years for session in sessions)
                put(
                    m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY,
                    size * sum(x.exit_session[:4] in positive_years for x in base.closed_cycles)
                    / positive_days
                    if positive_days else None,
                    status=m.DiagnosticStatus.NOT_APPLICABLE,
                    reason="NO_BENCHMARK_POSITIVE_YEARS",
                    sources=(base,),
                )
            else:
                put(
                    m.ResearchMetric.BENCHMARK_POSITIVE_YEAR_FREQUENCY,
                    reason="MISSING_BENCHMARK",
                    sources=(base,),
                )
            counts = [
                sum(
                    sessions[i - size + 1] <= x.exit_session <= sessions[i]
                    for x in base.closed_cycles
                )
                for i in range(size - 1, len(sessions))
            ]
            for metric, q in (
                (m.ResearchMetric.FREQUENCY_MEDIAN, 0.5),
                (m.ResearchMetric.FREQUENCY_Q10, 0.1),
            ):
                put(
                    metric,
                    _quantile(counts, q, m.QuantileMethod.LINEAR) if counts else None,
                    reason="INSUFFICIENT_FREQUENCY_WINDOW",
                    sources=(base,),
                )
            if p.frequency_min_closed_cycles is not None:
                coverage = m.FrequencyCoverageFacts(size, p.frequency_min_closed_cycles, len(counts),
                    sum(x >= p.frequency_min_closed_cycles for x in counts), (base.evaluation_id,))
                put(m.ResearchMetric.FREQUENCY_COVERAGE,
                    coverage.covered_windows / coverage.total_windows if coverage.total_windows else None,
                    reason="INSUFFICIENT_FREQUENCY_WINDOW", sources=(base,))
            else:
                put(m.ResearchMetric.FREQUENCY_COVERAGE, reason="FREQUENCY_COVERAGE_NOT_REQUESTED", sources=(base,))
            concentration, state, reason = _concentration(base, p.reconciliation_tolerance)
            put(m.ResearchMetric.PROFIT_CONCENTRATION, concentration, state, reason, (base,))
            if reason:
                gaps.append(reason)
            links = [x for x in request.perturbations if x.parent == center]
            design = next((x for x in request.parameter_designs if x.center == center), None)
            neighbors = [
                evidence.get((x.child, p.baseline_window, p.standard_scenario)) for x in links
            ]
            for link, neighbor in zip(links, neighbors):
                if neighbor is not None:
                    m.require(
                        (neighbor.parent, neighbor.derivation_sha256)
                        == (center, link.derivation_sha256),
                        "perturbation evidence has a different parent/derivation",
                    )
                    m.require(
                        neighbor.derivation_kind is m.AssessmentDerivationKind.PARAMETERS,
                        "parameter self-check requires a parameter-only derivation",
                    )
                    m.require(
                        neighbor.parameter_point == link.parameter_point,
                        "parameter evidence point differs from link",
                    )
            comparable = all(
                x is not None
                and x.context_sha256 == base.context_sha256
                and x.metric_version == base.metric_version
                and x.scenario_context == base.scenario_context
                and (not isinstance(p, m.NeighborhoodSelfCheckProtocol)
                     or (bool(base.benchmark_equity) and x.benchmark_equity == base.benchmark_equity))
                for x in neighbors
            )
            if design is not None:
                point_facts = tuple(_performance_facts(x) for x in neighbors
                    if x is not None and x.parameter_point is not None
                    and x.context_sha256 == base.context_sha256
                    and x.metric_version == base.metric_version
                    and x.scenario_context == base.scenario_context
                    and (not isinstance(p, m.NeighborhoodSelfCheckProtocol) or bool(base.benchmark_equity))
                    and x.benchmark_equity == base.benchmark_equity)
            declared_complete = design is None or (
                len(links) == _point_count(design)
                and {x.parameter_point.point_index for x in links}
                == set(range(_point_count(design)))
            )
            if isinstance(design, m.ParameterNeighborhoodDesign) and not design.is_applicable:
                for metric in (
                    m.ResearchMetric.PARAMETER_RETURN_Q10,
                    m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
                    m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                    m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
                ):
                    put(metric, status=m.DiagnosticStatus.NOT_APPLICABLE,
                        reason="NO_APPLICABLE_LOCAL_NEIGHBORHOOD", sources=(base,))
                gaps.append("NO_APPLICABLE_LOCAL_NEIGHBORHOOD")
            elif (
                len(neighbors) >= (1 if isinstance(p, m.NeighborhoodSelfCheckProtocol) else p.minimum_perturbations)
                and comparable
                and declared_complete
                and (p.parameter_protocol is None or design is not None)
            ):
                performances = [_performance(x) for x in neighbors]
                weights = [x.weight for x in links]
                return_q10 = _quantile([x[0] for x in performances], 0.1, p.quantile_method, weights)
                drawdown_q90 = _quantile([x[1] for x in performances], 0.9, p.quantile_method, weights)
                values = (
                    return_q10, drawdown_q90,
                    max(0.0, annual - return_q10), max(0.0, drawdown_q90 - drawdown),
                )
                for metric, value in zip(
                    (
                        m.ResearchMetric.PARAMETER_RETURN_Q10,
                        m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
                        m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                        m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
                    ),
                    values,
                ):
                    put(metric, value, sources=(base, *neighbors))
            else:
                for metric in (
                    m.ResearchMetric.PARAMETER_RETURN_Q10,
                    m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
                    m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                    m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
                ):
                    put(metric, reason="INCOMPLETE_OR_INCOMPARABLE_PERTURBATIONS", sources=(base,))
                gaps.append("INCOMPLETE_OR_INCOMPARABLE_PERTURBATIONS")
            stress = evidence.get((center, p.baseline_window, p.stress_scenario))
            if (
                stress
                and base.scenario_context.measurement_tier in {"FORMAL", "SCREENING"}
                and stress.scenario_context.measurement_tier == "STRESS"
                and stress.scenario_context.one_way_cost > base.scenario_context.one_way_cost
                and replace(
                    stress.scenario_context,
                    one_way_cost=base.scenario_context.one_way_cost,
                    measurement_tier=base.scenario_context.measurement_tier,
                )
                == base.scenario_context
                and (stress.context_sha256, stress.metric_version)
                == (
                    base.context_sha256,
                    base.metric_version,
                )
            ):
                stress_facts = _performance_facts(stress)
                put(
                    m.ResearchMetric.STRESS_ANNUAL_LOSS,
                    annual - _performance(stress)[0],
                    sources=(base, stress),
                )
            else:
                put(
                    m.ResearchMetric.STRESS_ANNUAL_LOSS,
                    reason="MISSING_OR_INCOMPARABLE_STRESS",
                    sources=(base,),
                )
                gaps.append("MISSING_OR_INCOMPARABLE_STRESS")
            if base.benchmark_equity:
                strategy = np.r_[base.initial_cash, [x.equity for x in base.account]]
                benchmark = np.r_[base.initial_cash, base.benchmark_equity]
                excess = [
                    strategy[i + p.rolling_window_days] / strategy[i]
                    - benchmark[i + p.rolling_window_days] / benchmark[i]
                    for i in range(
                        0, len(base.account) - p.rolling_window_days + 1, p.rolling_step_days
                    )
                ]
                put(
                    m.ResearchMetric.ROLLING_EXCESS_Q10,
                    _quantile(excess, 0.1, p.quantile_method)
                    if len(excess) >= p.minimum_rolling_windows
                    else None,
                    reason="INSUFFICIENT_ROLLING_WINDOWS",
                    sources=(base,),
                )
                if len(base.account) >= 2:
                    result = _paired_stationary_bootstrap_cagr(
                        _returns(base),
                        benchmark[1:] / benchmark[:-1] - 1,
                        repetitions=p.bootstrap_repetitions,
                        mean_block_length=p.bootstrap_block_length,
                        seed=p.seed,
                    )
                    interval = m.UncertaintyInterval(
                        m.DiagnosticStatus.AVAILABLE,
                        result.lower_95,
                        result.upper_95,
                        None,
                    )
                else:
                    interval = m.UncertaintyInterval(
                        m.DiagnosticStatus.INSUFFICIENT_DATA, None, None, "TOO_FEW_RETURNS"
                    )
            else:
                put(
                    m.ResearchMetric.ROLLING_EXCESS_Q10, reason="MISSING_BENCHMARK", sources=(base,)
                )
                interval = m.UncertaintyInterval(
                    m.DiagnosticStatus.INSUFFICIENT_DATA, None, None, "MISSING_BENCHMARK"
                )
                gaps.append("MISSING_BENCHMARK")
        else:
            gaps.append("MISSING_BASELINE")
        benchmark_values = (
            _equity_performance(base.benchmark_equity, base.initial_cash)
            if base is not None and base.benchmark_equity
            else (None, None)
        )
        benchmark = m.BenchmarkAssessment(
            tuple(
                m.DiagnosticValue(
                    metric,
                    m.MetricUnit.RATIO,
                    m.DiagnosticStatus.AVAILABLE
                    if value is not None
                    else m.DiagnosticStatus.INSUFFICIENT_DATA,
                    value,
                    None if value is not None else "MISSING_BENCHMARK",
                    (base.evaluation_id,) if base is not None else (),
                )
                for metric, value in zip(m.BENCHMARK_METRICS, benchmark_values)
            )
        )
        rows.append(
            m.CandidateAssessment(
                center,
                None if base is None else base.context_sha256,
                None if base is None else base.metric_version,
                None if base is None else base.frequency_window_days,
                None if base is None else base.scenario_context,
                None if base is None or stress is None else stress.scenario_context,
                tuple(diagnostics[x] for x in m.ResearchMetric),
                interval,
                tuple(gaps),
                None if base is None else base.behavior_sha256,
                benchmark,
                None
                if not request.parameter_designs
                else _parameter_context(request, center, evidence, base),
                coverage, point_facts, stress_facts,
            )
        )
    family, limitations = _family(request)
    return m.AssessmentPanel(request.sha256, p.sha256, tuple(rows), family, limitations,
        formula_version=("research-assessment-v7" if p.parameter_protocol.version == "parameter-cartesian-neighborhood-v2"
                         else "research-assessment-v6") if isinstance(p, m.NeighborhoodSelfCheckProtocol)
        else "research-assessment-v5")


def _point_count(design):
    return design.point_count if isinstance(design, m.ParameterNeighborhoodDesign) else design.protocol.point_count


def parameter_comparison_key(context):
    if isinstance(context, m.ParameterNeighborhoodContext):
        return ("neighborhood", context.comparison_sha256)
    return ("legacy-sphere", context.protocol.method_sha256)


def _parameter_context(request, center, evidence, base):
    design = next((x for x in request.parameter_designs if x.center == center), None)
    if design is None:
        return None
    valid = 0
    for link in request.perturbations:
        if link.parent != center:
            continue
        neighbor = evidence.get(
            (link.child, request.protocol.baseline_window, request.protocol.standard_scenario)
        )
        if (
            base is not None
            and neighbor is not None
            and neighbor.parameter_point == link.parameter_point
            and neighbor.context_sha256 == base.context_sha256
            and neighbor.metric_version == base.metric_version
            and neighbor.scenario_context == base.scenario_context
            and (not isinstance(request.protocol, m.NeighborhoodSelfCheckProtocol)
                 or (bool(base.benchmark_equity) and neighbor.benchmark_equity == base.benchmark_equity))
        ):
            valid += 1
    if isinstance(design, m.ParameterNeighborhoodDesign):
        return m.ParameterNeighborhoodContext(
            design.protocol, design.sha256, design.space.sha256, len(design.space.axes),
            design.point_count, valid, design.comparison_sha256,
        )
    return m.ParameterDiagnosticContext(
        design.protocol,
        design.sha256,
        design.space.sha256,
        len(design.space.coordinates),
        _point_count(design),
        valid,
    )


def _bin(value, spec):
    if value is None:
        return None
    rounding = {
        m.BinRounding.FLOOR: ROUND_FLOOR,
        m.BinRounding.NEAREST_HALF_EVEN: ROUND_HALF_EVEN,
        m.BinRounding.NEAREST_HALF_UP: ROUND_HALF_UP,
    }[spec.rounding]
    return int(
        (
            (Decimal(str(value)) - Decimal(str(spec.origin))) / Decimal(str(spec.resolution))
        ).to_integral_value(rounding=rounding)
    )


def _compare_pair(a, b, layer, order, parameter_methods):
    for metric, left, right in zip(order, a.bin_values, b.bin_values):
        floor_a, floor_b = metric in (a.floor_metrics or ()), metric in (b.floor_metrics or ())
        if floor_a or floor_b:
            if floor_a and floor_b:
                continue
            # A missing real measurement never becomes a floor or a valid comparison.
            if (right if floor_a else left) is None:
                return m.PairwiseComparison(a.candidate, b.candidate, layer,
                    m.PairwiseRelation.INCOMPARABLE, metric, "MISSING_METRIC")
            return m.PairwiseComparison(a.candidate, b.candidate, layer,
                m.PairwiseRelation.B_BEFORE_A if floor_a else m.PairwiseRelation.A_BEFORE_B,
                metric, None)
        if metric in (
            m.ResearchMetric.PARAMETER_RETURN_Q10,
            m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
        ):
            method_a, method_b = parameter_methods[a.candidate], parameter_methods[b.candidate]
            if method_a is None or method_b is None or method_a != method_b:
                return m.PairwiseComparison(
                    a.candidate,
                    b.candidate,
                    layer,
                    m.PairwiseRelation.INCOMPARABLE,
                    metric,
                    "MISSING_DECLARED_PARAMETER_METHOD"
                    if method_a is None or method_b is None
                    else "PARAMETER_METHODS_DIFFER",
                )
        if left is None or right is None:
            return m.PairwiseComparison(
                a.candidate,
                b.candidate,
                layer,
                m.PairwiseRelation.INCOMPARABLE,
                metric,
                "MISSING_METRIC",
            )
        if left != right:
            maximize = metric in (
                *m.FREQUENCY_METRICS,
                m.ResearchMetric.PARAMETER_RETURN_Q10,
                m.ResearchMetric.ROLLING_EXCESS_Q10,
            )
            relation = (
                m.PairwiseRelation.A_BEFORE_B
                if (left > right) == maximize
                else m.PairwiseRelation.B_BEFORE_A
            )
            return m.PairwiseComparison(a.candidate, b.candidate, layer, relation, metric, None)
    return m.PairwiseComparison(a.candidate, b.candidate, layer, m.PairwiseRelation.TIE, None, None)


def _order_layer(members, layer, order, parameter_methods):
    members = sorted(members, key=lambda x: x.candidate.candidate_id)
    ids = [x.candidate for x in members]
    edges, ties, unknown = ({x: set() for x in ids} for _ in range(3))
    pairs = tuple(
        _compare_pair(a, b, layer, order, parameter_methods) for a, b in combinations(members, 2)
    )
    for pair in pairs:
        a, b = pair.candidate_a, pair.candidate_b
        if pair.relation is m.PairwiseRelation.A_BEFORE_B:
            edges[a].add(b)
        elif pair.relation is m.PairwiseRelation.B_BEFORE_A:
            edges[b].add(a)
        elif pair.relation is m.PairwiseRelation.TIE:
            ties[a].add(b)
            ties[b].add(a)
        else:
            unknown[a].add(b)
            unknown[b].add(a)
    after = {}
    for who in ids:
        seen, stack = set(), list(edges[who])
        while stack:
            other = stack.pop()
            m.require(other != who, "partial-order cycle")
            if other not in seen:
                seen.add(other)
                stack.extend(edges[other])
        after[who] = seen
    result = []
    for row in members:
        who = row.candidate
        before = {other for other in ids if who in after[other]}
        lo, hi = len(before) + 1, len(ids) - len(after[who])
        exact = (
            lo
            if lo == hi or (ties[who] and not unknown[who] and hi - lo + 1 == len(ties[who]) + 1)
            else None
        )
        status = (
            m.ComparisonStatus.PARTIALLY_ORDERED
            if unknown[who]
            else m.ComparisonStatus.TIED
            if ties[who]
            else m.ComparisonStatus.RANKED
        )
        result.append(
            replace(
                row,
                status=status,
                pareto_layer=layer,
                rank_in_layer=exact,
                rank_min=lo,
                rank_max=hi,
            )
        )
    return sorted(result, key=lambda x: (x.rank_min, x.candidate.candidate_id)), pairs


def _rank(request, bins, order):
    specifications = {x.metric: x for x in bins}
    records, profiles, eligible_rows = [], [], []
    for row in request.panel.rows:
        metrics = {x.metric: x for x in row.diagnostics}
        floor_metrics = () if request.policy.formula_version == "research-ranking-v4" else None
        if (floor_metrics is not None
                and isinstance(row.parameter_context, m.ParameterNeighborhoodContext)
                and not row.parameter_context.is_applicable
                and all(metrics[x].status is m.DiagnosticStatus.NOT_APPLICABLE for x in (
                    m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90))):
            floor_metrics = (m.ResearchMetric.PARAMETER_RETURN_Q10, m.ResearchMetric.PARAMETER_DRAWDOWN_Q90)
        checks = tuple(
            _check_target(x, row, request.targets.frequency_window_days)
            for x in request.targets.requirements
        )
        accepted = acceptance_status(checks)
        reasons = [
            x.reason
            for x in checks
            if x.status in (m.TargetCheckStatus.FAILED, m.TargetCheckStatus.INDETERMINATE)
        ]
        missing = [
            metric for metric in (*m.BENCHMARK_METRICS, *order)
            if metrics[metric].value is None and metric not in (floor_metrics or ())
        ]
        reasons.extend(f"{metric.value}:{metrics[metric].reason}" for metric in missing)
        missing_parameter_method = row.parameter_context is None
        if missing_parameter_method:
            reasons.append("MISSING_DECLARED_PARAMETER_METHOD")
            missing.extend(
                metric
                for metric in order
                if metric
                in (
                    m.ResearchMetric.PARAMETER_RETURN_Q10,
                    m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
                )
                and metric not in missing
            )
        if accepted is m.TargetCheckStatus.FAILED:
            status = m.ComparisonStatus.TARGET_NOT_MET
        elif (
            (bool(checks) and accepted is m.TargetCheckStatus.INDETERMINATE)
            or row.frequency_window_days != request.targets.frequency_window_days
            or row.context_sha256 is None
            or any(x in missing for x in m.BENCHMARK_METRICS)
            or (
                missing
                and request.policy.missing_evidence_policy
                is m.MissingEvidencePolicy.REQUIRE_COMPLETE
            )
        ):
            status = m.ComparisonStatus.INCOMPARABLE
            if row.context_sha256 is None:
                reasons.append("EVALUATION_CONTEXTS_DIFFER")
            if row.frequency_window_days != request.targets.frequency_window_days:
                reasons.append("FREQUENCY_WINDOW_DIFFERS")
        else:
            status = m.ComparisonStatus.RANKED
        values = tuple(
            None
            if missing_parameter_method
            and metric
            in (
                m.ResearchMetric.PARAMETER_RETURN_Q10,
                m.ResearchMetric.PARAMETER_DRAWDOWN_Q90,
            )
            else _bin(metrics[metric].value, specifications[metric])
            for metric in order
        )
        records.append(
            m.CandidateRank(
                row.candidate, status, checks, None, None, values, tuple(reasons), None, None, accepted,
                floor_metrics,
            )
        )
        if status is m.ComparisonStatus.RANKED:
            eligible_rows.append(row)
            raw = request.policy.pareto_basis is m.ParetoBasis.RAW
            annual, dd = (
                metrics[x].value if raw else _bin(metrics[x].value, specifications[x])
                for x in m.BENCHMARK_METRICS
            )
            profiles.append((row.candidate.candidate_id, annual, -dd))

    contexts = {
        (x.context_sha256, x.metric_version, x.frequency_window_days, x.baseline_scenario)
        for x in eligible_rows
    }
    # Absent pressure evidence is missing data; two different known scenarios remain incompatible.
    stress_contexts = {x.stress_scenario for x in eligible_rows if x.stress_scenario is not None}
    parameter_methods = {
        x.candidate: None
        if x.parameter_context is None
        else parameter_comparison_key(x.parameter_context)
        for x in eligible_rows
    }
    incompatible_parameter_methods = (
        len({key for who, key in parameter_methods.items()
             if not any(record.candidate == who and record.floor_metrics for record in records)}) > 1
        and request.policy.missing_evidence_policy is m.MissingEvidencePolicy.REQUIRE_COMPLETE
    )
    if len(contexts) > 1 or len(stress_contexts) > 1 or incompatible_parameter_methods:
        records = [
            replace(
                x,
                status=m.ComparisonStatus.INCOMPARABLE,
                reasons=(
                    *x.reasons,
                    "PARAMETER_METHODS_DIFFER"
                    if incompatible_parameter_methods
                    else "EVALUATION_CONTEXTS_DIFFER",
                ),
            )
            if x.status is m.ComparisonStatus.RANKED
            else x
            for x in records
        ]
        profiles = []
    # Keep integer bins exact; coercing them to float can merge distinct cells.
    remaining = {who: (annual, negative_dd) for who, annual, negative_dd in profiles}
    layers = {}
    layer_number = 0
    while remaining:
        front = [
            who
            for who, vector in remaining.items()
            if not any(
                all(a >= b for a, b in zip(other, vector))
                and any(a > b for a, b in zip(other, vector))
                for key, other in remaining.items()
                if key != who
            )
        ]
        m.require(bool(front), "dominance cycle")
        layer_number += 1
        for who in front:
            layers[who] = layer_number
            del remaining[who]
    result, pairs = [], []
    for layer in sorted(set(layers.values())):
        members = [x for x in records if layers.get(x.candidate.candidate_id) == layer]
        ranked, comparisons = _order_layer(members, layer, order, parameter_methods)
        result.extend(ranked)
        pairs.extend(comparisons)
    result.extend(
        sorted(
            (x for x in records if x.candidate.candidate_id not in layers),
            key=lambda x: x.candidate.candidate_id,
        )
    )
    return tuple(result), tuple(pairs)


def compare_candidates(request: m.CandidateComparisonRequest) -> m.CandidateComparison:
    if type(request) is not m.CandidateComparisonRequest:
        raise TypeError("compare_candidates requires CandidateComparisonRequest")
    m.require(request.policy.formula_version == "research-ranking-v4"
              and request.panel.formula_version == "research-assessment-v7",
              "historical comparison protocols are read-only")
    return _compare_candidates(request)


def recompute_historical_comparison(request: m.CandidateComparisonRequest) -> m.CandidateComparison:
    """Read-only numeric verification of stored v3 rankings from v5/v6 panels."""
    if type(request) is not m.CandidateComparisonRequest:
        raise TypeError("historical comparison requires CandidateComparisonRequest")
    m.require(request.policy.formula_version == "research-ranking-v3"
              and request.panel.formula_version in ("research-assessment-v5", "research-assessment-v6"),
              "historical comparison requires historical formulas")
    return _compare_candidates(request)


def _compare_candidates(request: m.CandidateComparisonRequest) -> m.CandidateComparison:
    if type(request) is not m.CandidateComparisonRequest:
        raise TypeError("compare_candidates requires CandidateComparisonRequest")
    request = m.CandidateComparisonRequest.from_dict(request.to_dict())
    baseline, pairs = _rank(request, request.policy.bins, request.policy.ranking_metrics)
    sensitivities = []
    for variant in request.policy.sensitivities:
        order = list(request.policy.ranking_metrics)
        if variant.adjacent_swap is not None:
            i = variant.adjacent_swap
            order[i], order[i + 1] = order[i + 1], order[i]
        rows, comparisons = _rank(request, variant.bins, tuple(order))
        sensitivities.append(m.SensitivityRanking(variant.name, rows, comparisons))
    groups = defaultdict(list)
    for row in request.panel.rows:
        if row.behavior_sha256 is not None:
            groups[row.behavior_sha256].append(row.candidate)
    behavior = tuple(
        m.BehaviorGroup(key, tuple(sorted(values, key=lambda x: x.candidate_id)))
        for key, values in sorted(groups.items())
        if len(values) > 1
    )
    return m.CandidateComparison(request.sha256, baseline, tuple(sensitivities), behavior, pairs)
