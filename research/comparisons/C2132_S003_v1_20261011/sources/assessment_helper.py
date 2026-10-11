"""Unified public SE/TDR assessment; consumes authenticated caller-supplied facts.

No account scheduling, filesystem reads, market access, optimization or family
matrix synthesis. Open holdings remain in whole-account performance; frequency
and concentration use only the actual CLOSED cycles supplied by TDR.
"""
from czsc_trader.research_tools import (
    EvaluationRequest,
    EvaluationResult,
    build_assessment_evidence,
)
from strategy_evaluator import (
    AssessmentDerivationKind,
    AssessmentPanel,
    CandidateAssessmentRequest,
    ParameterPerturbationDesign,
    ParameterPerturbationProtocol,
    PerturbationLink,
    QuantileMethod,
    SelfCheckProtocol,
    assess_candidates,
)

EvaluationPair = tuple[EvaluationRequest, EvaluationResult]


def unified_protocol() -> SelfCheckProtocol:
    """The prospective fixed common comparison protocol, without economic vetoes."""
    return SelfCheckProtocol(
        version='1', baseline_window='common', standard_scenario='baseline',
        stress_scenario='stress_20bp_per_side', rolling_window_days=126,
        rolling_step_days=21, quantile_method=QuantileMethod.LINEAR,
        minimum_perturbations=32, minimum_rolling_windows=20,
        bootstrap_repetitions=2000, bootstrap_block_length=20, seed=13,
        reconciliation_tolerance=1e-6, pbo_blocks=10,
        parameter_protocol=ParameterPerturbationProtocol(radius=.05, point_count=32, seed=13),
    )


def _select(pair: EvaluationPair, scenario: str):
    if type(pair) is not tuple or len(pair) != 2:
        raise TypeError('An exact (EvaluationRequest, EvaluationResult) tuple is required')
    # The public adapter authenticates the complete request/result, including
    # all its runs, lineage, execution identities and economic ledger.
    evidence = build_assessment_evidence(*pair)
    selected = [item for item in evidence
                if item.window_id == 'common' and item.scenario_id == scenario]
    if len(selected) != 1:
        raise ValueError('Exactly one authenticated common/' + scenario + ' evidence required')
    return selected[0]


def assess_unified(
    standard: EvaluationPair,
    stress: EvaluationPair,
    perturbations: tuple[EvaluationPair, ...],
    design: ParameterPerturbationDesign,
) -> dict:
    """Return the complete serialized v3 SE request and five-factor panel.

    Pass one original strategy center per invocation, its 20bp-per-side center
    pressure evaluation and all 32 genuine typed PARAMETERS descendants. The
    original parameter geometry must already be declared in `design`.
    Family returns are explicitly absent: two compared strategies are not a
    substitute for their complete, comparable historical research families.
    """
    if type(design) is not ParameterPerturbationDesign:
        raise TypeError('A typed SE ParameterPerturbationDesign is required')
    protocol = unified_protocol()
    if design.protocol != protocol.parameter_protocol:
        raise ValueError('Design must use the exact fixed 5%/32/seed13 parameter protocol')
    if type(perturbations) is not tuple or len(perturbations) != 32:
        raise ValueError('Exactly 32 typed parameter evaluation pairs required')
    base = _select(standard, protocol.standard_scenario)
    pressure = _select(stress, protocol.stress_scenario)
    if base.candidate != design.center or pressure.candidate != base.candidate:
        raise ValueError('Standard, stress and declared design must identify the same center')
    if base.frequency_window_days != 60 or pressure.frequency_window_days != 60:
        raise ValueError('Unified comparison requires the original 60-session frequency unit')
    if base.scenario_context.one_way_cost != .001:
        raise ValueError('Baseline must be actual 10bp per side')
    if base.scenario_context.measurement_tier not in ('FORMAL', 'SCREENING'):
        raise ValueError('Baseline measurement tier must be FORMAL or SCREENING')
    if pressure.scenario_context.one_way_cost != .002 or pressure.scenario_context.measurement_tier != 'STRESS':
        raise ValueError('Pressure must be actual 20bp per side with STRESS tier')
    children = tuple(_select(pair, protocol.standard_scenario) for pair in perturbations)
    indices, identities, links = set(), set(), []
    for child in children:
        if child.derivation_kind is not AssessmentDerivationKind.PARAMETERS:
            raise ValueError('Parameter diagnostics require actual typed PARAMETERS lineage')
        if child.parent != base.candidate or child.derivation_sha256 is None:
            raise ValueError('Parameter evidence must derive from this exact original center')
        point = child.parameter_point
        if point is None or point != design.bind_point(point.point_index):
            raise ValueError('Actual parameter evidence must bind an exact declared SE point')
        if point.point_index in indices or child.candidate in identities:
            raise ValueError('Duplicated parameter point or child identity')
        if child.frequency_window_days != 60:
            raise ValueError('Parameter frequency unit must remain 60 sessions')
        indices.add(point.point_index)
        identities.add(child.candidate)
        links.append(PerturbationLink(base.candidate, child.candidate, 1.,
                                      child.derivation_sha256, point))
    if indices != set(range(32)):
        raise ValueError('All original 32 SE design points must be represented')
    request = CandidateAssessmentRequest(
        centers=(base.candidate,), protocol=protocol, perturbations=tuple(links),
        evidence=(base, pressure, *children), incomplete=(), family_returns=None,
        parameter_designs=(design,),
    )
    panel = assess_candidates(request)
    if panel.formula_version != 'research-assessment-v3':
        raise ValueError('The installed public SE assessment version has changed')
    return {'assessment_request': request.to_dict(), 'assessment_panel': panel.to_dict(),
            'assessment_request_sha256': request.sha256, 'assessment_panel_sha256': panel.sha256,
            'applicability': {
                'open_holdings': 'Included in account equity, return, drawdown, rolling excess and bootstrap; never force-liquidated.',
                'closed_cycle_metrics': 'Only actual CLOSED cycles enter completed frequency and positive closed-cycle concentration; partial sells of an open core are not closed cycles.',
                'no_profitable_closed_cycles': 'Public SE concentration is NOT_APPLICABLE, not zero and not proof of diversified whole-account profits.',
                'family_returns': None,
                'family_selection_bias': 'Full comparable historical family matrices unavailable; PBO/DSR remain INSUFFICIENT_DATA. A two-strategy matrix is not substituted.',
                'historical_bias': 'Original S013 EX008 and S003 EX047 historical diagnostics, if separately cited, retain their historical scope and are not unified v3 results.',
                'scope': 'Read-only computation of supplied account facts; no evaluation, preparation, registration or strategy changes.',
            }}


def assess_comparison(
    central: EvaluationPair,
    stress: EvaluationPair,
    points: tuple[EvaluationPair, ...],
    design: ParameterPerturbationDesign,
) -> AssessmentPanel:
    """Typed single-center v3 panel for the comparison driver's native interface."""
    return AssessmentPanel.from_dict(assess_unified(central, stress, points, design)['assessment_panel'])
