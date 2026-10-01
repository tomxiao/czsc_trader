"""Deterministic research diagnostics. No evaluation scheduling or economic gates."""

from collections import defaultdict
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_EVEN
import math

import numpy as np

from . import research_models as m
from .bootstrap import paired_stationary_bootstrap
from .audit_models import ReturnMatrixEvidence
from .models import CandidateProfile
from .pareto import pareto_layers
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
    equity = np.asarray([x.equity for x in evidence.account])
    wealth = np.r_[evidence.initial_cash, equity]
    annual = float((equity[-1] / evidence.initial_cash) ** (252 / len(equity)) - 1)
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
                if metric in (m.ResearchMetric.FREQUENCY_MEDIAN, m.ResearchMetric.FREQUENCY_Q10)
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
                and replace(
                    stress.scenario_context, one_way_cost=base.scenario_context.one_way_cost
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
            )
        )
    family, limitations = _family(request)
    return m.AssessmentPanel(request.sha256, p.sha256, tuple(rows), family, limitations)


def _rank(request, bins, order):
    specifications = {x.metric: x for x in bins}
    records, comparable = [], []
    for row in request.panel.rows:
        metrics = {x.metric: x for x in row.diagnostics}
        checks, reasons = [], []
        for target in request.targets.requirements:
            value = metrics[target.metric].value
            frequency = target.metric in (
                m.ResearchMetric.FREQUENCY_MEDIAN,
                m.ResearchMetric.FREQUENCY_Q10,
            )
            if frequency and row.frequency_window_days != request.targets.frequency_window_days:
                checks.append(m.TargetCheck(target, value, None, "FREQUENCY_WINDOW_DIFFERS"))
            elif value is None:
                checks.append(m.TargetCheck(target, None, None, metrics[target.metric].reason))
            else:
                passed = (target.lower is None or value >= target.lower) and (
                    target.upper is None or value <= target.upper
                )
                checks.append(
                    m.TargetCheck(target, value, passed, None if passed else "TARGET_NOT_MET")
                )
        if any(x.passed is False for x in checks):
            status = m.ComparisonStatus.TARGET_NOT_MET
            reasons.append("TARGET_NOT_MET")
        else:
            reasons.extend(x.reason for x in checks if x.passed is None)
            reasons.extend(
                f"{metric.value}:{metrics[metric].reason}"
                for metric in order
                if metrics[metric].value is None
            )
            if row.context_sha256 is None:
                reasons.append("EVALUATION_CONTEXTS_DIFFER")
            status = m.ComparisonStatus.INCOMPARABLE if reasons else m.ComparisonStatus.RANKED
        rank = m.CandidateRank(row.candidate, status, tuple(checks), None, None, (), tuple(reasons))
        if status is m.ComparisonStatus.RANKED:
            values = []
            for metric in order:
                spec = specifications[metric]
                rounding = ROUND_FLOOR if spec.rounding is m.BinRounding.FLOOR else ROUND_HALF_EVEN
                value = (
                    (Decimal(str(metrics[metric].value)) - Decimal(str(spec.origin)))
                    / Decimal(str(spec.resolution))
                ).to_integral_value(rounding=rounding)
                values.append(int(value))
            rank = replace(rank, bin_values=tuple(values))
            comparable.append(
                CandidateProfile(
                    row.candidate.candidate_id,
                    True,
                    True,
                    (
                        ("net_annual", metrics[m.ResearchMetric.NET_ANNUAL_RETURN].value),
                        ("negative_drawdown", -metrics[m.ResearchMetric.DRAWDOWN_MAGNITUDE].value),
                    ),
                )
            )
        records.append(rank)
    eligible_ids = {
        x.candidate.candidate_id for x in records if x.status is m.ComparisonStatus.RANKED
    }
    contexts = {
        (
            x.context_sha256,
            x.metric_version,
            x.frequency_window_days,
            x.baseline_scenario,
            x.stress_scenario,
        )
        for x in request.panel.rows
        if x.candidate.candidate_id in eligible_ids
    }
    if len(contexts) > 1:
        records = [
            replace(
                x,
                status=m.ComparisonStatus.INCOMPARABLE,
                bin_values=(),
                reasons=(*x.reasons, "EVALUATION_CONTEXTS_DIFFER"),
            )
            if x.candidate.candidate_id in eligible_ids
            else x
            for x in records
        ]
        comparable = []
    layers = {x.candidate_id: x.pareto_layer for x in pareto_layers(tuple(comparable))}

    def sort_key(row):
        return tuple(
            -value
            if metric in (m.ResearchMetric.NET_ANNUAL_RETURN, m.ResearchMetric.ROLLING_EXCESS_Q10)
            else value
            for metric, value in zip(order, row.bin_values)
        )

    result = []
    for layer in sorted(set(layers.values())):
        members = [x for x in records if layers.get(x.candidate.candidate_id) == layer]
        keys = sorted(set(sort_key(x) for x in members))
        result.extend(
            replace(x, pareto_layer=layer, rank_in_layer=keys.index(sort_key(x)) + 1)
            for x in sorted(members, key=lambda x: (sort_key(x), x.candidate.candidate_id))
        )
    result.extend(
        sorted(
            (x for x in records if x.status is not m.ComparisonStatus.RANKED),
            key=lambda x: x.candidate.candidate_id,
        )
    )
    return tuple(result)


def compare_candidates(request: m.CandidateComparisonRequest) -> m.CandidateComparison:
    if type(request) is not m.CandidateComparisonRequest:
        raise TypeError("compare_candidates requires CandidateComparisonRequest")
    request = m.CandidateComparisonRequest.from_dict(request.to_dict())
    baseline = _rank(request, request.policy.bins, m.RANKING_METRICS)
    sensitivities = []
    for variant in request.policy.sensitivities:
        order = list(m.RANKING_METRICS)
        if variant.adjacent_swap is not None:
            i = variant.adjacent_swap
            order[i], order[i + 1] = order[i + 1], order[i]
        sensitivities.append(
            m.SensitivityRanking(variant.name, _rank(request, variant.bins, tuple(order)))
        )
    groups = defaultdict(list)
    for row in request.panel.rows:
        if row.behavior_sha256 is not None:
            groups[row.behavior_sha256].append(row.candidate)
    behavior = tuple(
        m.BehaviorGroup(key, tuple(sorted(values, key=lambda x: x.candidate_id)))
        for key, values in sorted(groups.items())
        if len(values) > 1
    )
    return m.CandidateComparison(request.sha256, baseline, tuple(sensitivities), behavior)
