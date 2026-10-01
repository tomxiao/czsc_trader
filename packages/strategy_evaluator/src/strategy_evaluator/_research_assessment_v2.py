# Frozen schema-v2 validation semantics from e130c88b; read-only.
"""Deterministic research diagnostics. No evaluation scheduling or economic gates."""

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP
from itertools import combinations
import operator
import math

import numpy as np

from . import _research_models_v2 as m
from .bootstrap import paired_stationary_bootstrap
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

    def dsr(kind):
        sharpes = np.array([annualized_sharpe(matrix[:, i]) for i in range(matrix.shape[1])])
        selected = matrix[:, family.candidates.index(family.selected)]
        bundle = calculate_dsr_bundle(
            selected,
            sharpes,
            raw_count=family.raw_trial_count,
            effective_count=effective_trial_count(matrix),
        )
        return getattr(bundle, kind).probability

    append("DSR_RAW", lambda: dsr("raw"))
    append("DSR_EFFECTIVE", lambda: dsr("effective"))
    return tuple(values), family.limitations


def assess_candidates(request: m.CandidateAssessmentRequest) -> m.AssessmentPanel:
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

        def put(
            metric,
            value=None,
            status=m.DiagnosticStatus.INSUFFICIENT_DATA,
            reason="MISSING_BASELINE",
            sources=(),
        ):
            unit = (
                m.MetricUnit.CLOSED_CYCLES_PER_WINDOW
                if metric in m.FREQUENCY_METRICS
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
            concentration, state, reason = _concentration(base, p.reconciliation_tolerance)
            put(m.ResearchMetric.PROFIT_CONCENTRATION, concentration, state, reason, (base,))
            if reason:
                gaps.append(reason)
            links = [x for x in request.perturbations if x.parent == center]
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
            comparable = all(
                x is not None
                and x.context_sha256 == base.context_sha256
                and x.metric_version == base.metric_version
                and x.scenario_context == base.scenario_context
                for x in neighbors
            )
            if len(neighbors) >= p.minimum_perturbations and comparable:
                performances = [_performance(x) for x in neighbors]
                weights = [x.weight for x in links]
                values = (
                    max(
                        0.0,
                        annual
                        - _quantile([x[0] for x in performances], 0.1, p.quantile_method, weights),
                    ),
                    max(
                        0.0,
                        _quantile([x[1] for x in performances], 0.9, p.quantile_method, weights)
                        - drawdown,
                    ),
                )
                for metric, value in zip(
                    (
                        m.ResearchMetric.PARAMETER_RETURN_DEGRADATION,
                        m.ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION,
                    ),
                    values,
                ):
                    put(metric, value, sources=(base, *neighbors))
            else:
                for metric in (
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
                    result = paired_stationary_bootstrap(
                        _returns(base),
                        benchmark[1:] / benchmark[:-1] - 1,
                        champion_id=center.candidate_id,
                        comparator_id="benchmark",
                        repetitions=p.bootstrap_repetitions,
                        mean_block_length=p.bootstrap_block_length,
                        seed=p.seed,
                    )
                    interval = m.UncertaintyInterval(
                        m.DiagnosticStatus.AVAILABLE,
                        result.cagr.lower_95,
                        result.cagr.upper_95,
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
            )
        )
    family, limitations = _family(request)
    return m.AssessmentPanel(request.sha256, p.sha256, tuple(rows), family, limitations)


def _check_target(target, row, frequency_window_days):
    metrics = {x.metric: x for x in row.diagnostics}
    benchmark = {x.metric: x for x in row.benchmark.diagnostics}
    observed = metrics[target.metric].value
    sources = list(metrics[target.metric].evaluation_ids)
    condition_value = None
    lower = upper = None

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

    if target.when is not None:
        condition = target.when
        diagnostic = benchmark[condition.metric]
        condition_value = diagnostic.value
        sources.extend(diagnostic.evaluation_ids)
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
    if target.metric in m.FREQUENCY_METRICS and row.frequency_window_days != frequency_window_days:
        return result(m.TargetCheckStatus.INDETERMINATE, "FREQUENCY_WINDOW_DIFFERS")
    if observed is None:
        return result(m.TargetCheckStatus.INDETERMINATE, metrics[target.metric].reason)
    bounds = []
    for bound in (target.lower, target.upper):
        if isinstance(bound, m.BenchmarkBound):
            diagnostic = benchmark[target.metric]
            sources.extend(diagnostic.evaluation_ids)
            if diagnostic.value is None:
                return result(m.TargetCheckStatus.INDETERMINATE, "MISSING_BOUND_BENCHMARK")
            value = diagnostic.value * bound.multiplier
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


def _compare_pair(a, b, layer, order):
    for metric, left, right in zip(order, a.bin_values, b.bin_values):
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
                m.ResearchMetric.NET_ANNUAL_RETURN,
                m.ResearchMetric.ROLLING_EXCESS_Q10,
            )
            relation = (
                m.PairwiseRelation.A_BEFORE_B
                if (left > right) == maximize
                else m.PairwiseRelation.B_BEFORE_A
            )
            return m.PairwiseComparison(a.candidate, b.candidate, layer, relation, metric, None)
    return m.PairwiseComparison(a.candidate, b.candidate, layer, m.PairwiseRelation.TIE, None, None)


def _order_layer(members, layer, order):
    members = sorted(members, key=lambda x: x.candidate.candidate_id)
    ids = [x.candidate for x in members]
    edges, ties, unknown = ({x: set() for x in ids} for _ in range(3))
    pairs = tuple(_compare_pair(a, b, layer, order) for a, b in combinations(members, 2))
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
        checks = tuple(
            _check_target(x, row, request.targets.frequency_window_days)
            for x in request.targets.requirements
        )
        reasons = [
            x.reason
            for x in checks
            if x.status in (m.TargetCheckStatus.FAILED, m.TargetCheckStatus.INDETERMINATE)
        ]
        missing = [metric for metric in order if metrics[metric].value is None]
        reasons.extend(f"{metric.value}:{metrics[metric].reason}" for metric in missing)
        if any(x.status is m.TargetCheckStatus.FAILED for x in checks):
            status = m.ComparisonStatus.TARGET_NOT_MET
        elif (
            any(x.status is m.TargetCheckStatus.INDETERMINATE for x in checks)
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
        else:
            status = m.ComparisonStatus.RANKED
        values = tuple(_bin(metrics[metric].value, specifications[metric]) for metric in order)
        records.append(
            m.CandidateRank(
                row.candidate, status, checks, None, None, values, tuple(reasons), None, None
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
    if len(contexts) > 1 or len(stress_contexts) > 1:
        records = [
            replace(
                x,
                status=m.ComparisonStatus.INCOMPARABLE,
                reasons=(*x.reasons, "EVALUATION_CONTEXTS_DIFFER"),
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
        ranked, comparisons = _order_layer(members, layer, order)
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
    request = m.CandidateComparisonRequest.from_dict(request.to_dict())
    baseline, pairs = _rank(request, request.policy.bins, m.RANKING_METRICS)
    sensitivities = []
    for variant in request.policy.sensitivities:
        order = list(m.RANKING_METRICS)
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
