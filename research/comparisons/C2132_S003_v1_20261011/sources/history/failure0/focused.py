"""Public SE synthetic fixtures and adapter delegation spies; no real accounts."""
from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS
import importlib.util
import json

import numpy as np
from strategy_evaluator import (
    AccountPoint, AssessmentCandidate, AssessmentDerivationKind, AssessmentEvidence,
    AssessmentFill, AssessmentPanel, CandidateAssessmentRequest, ClosedCycle,
    DiagnosticStatus, EvaluationScenarioContext, FillSide, ParameterCoordinate,
    ParameterCoordinateKind, ParameterDesignRequest, ParameterPerturbationDesign,
    ParameterSpace, ResearchMetric, build_parameter_perturbation_design,
)

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('unified_helper', HERE / 'assessment_helper.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
checks, refusals = [], []


def check(name, condition):
    assert condition, name
    checks.append(name)


def refuse(name, fn):
    try:
        fn()
    except (ValueError, TypeError, IndexError):
        refusals.append(name)
    else:
        raise AssertionError('Expected refusal: ' + name)


def evidence(candidate, *, pressure=False, open_core=False, profit=10.):
    cash, quantity = 2000., 0
    rows, fills, cycles = [], [], []
    fee = .002 if pressure else .001
    for i in range(600):
        day = (date(2020, 1, 1) + timedelta(days=i)).isoformat()
        close = 10. + .0001 * i
        if open_core:
            close += .3 * np.sin(i / 29.)
            if i == 0:
                quantity = 100
                cash -= quantity * close * (1 + fee)
                fills.append(AssessmentFill('open_core', day, FillSide.BUY, quantity, close, quantity * close * fee))
            elif i == 80:
                quantity -= 10
                cash += 10 * close * (1 - fee)
                fills.append(AssessmentFill('open_core', day, FillSide.SELL, 10, close, 10 * close * fee))
        else:
            key = str(i // 8)
            if i % 8 == 0:
                quantity = 10
                cash -= quantity * close * (1 + fee)
                fills.append(AssessmentFill(key, day, FillSide.BUY, quantity, close, quantity * close * fee))
            elif i % 8 == 2:
                close = 10. + .0001 * (i - 2) + profit / 10
                cash += quantity * close * (1 - fee)
                fills.append(AssessmentFill(key, day, FillSide.SELL, quantity, close, quantity * close * fee))
                quantity = 0
                cycles.append(ClosedCycle(key, day))
        rows.append(AccountPoint(day, cash, quantity, close, cash + quantity * close))
    scenario = 'stress_20bp_per_side' if pressure else 'baseline'
    identity = sha256((candidate.candidate_id + scenario).encode()).hexdigest()
    return AssessmentEvidence(
        candidate, 'pure_fixture', identity[:32], identity, identity, identity,
        'a' * 64, 'common', scenario, 'pure-v3',
        EvaluationScenarioContext(fee, 'STRESS' if pressure else 'FORMAL', 'BuyHold', 'BUYHOLD', 'b' * 64),
        2000., 2000., 0, 60, tuple(rows), tuple(fills), tuple(cycles),
        tuple(2000 * (1.00001 ** (i + 1)) for i in range(600)), behavior_sha256='c' * 64,
    )


def fixtures(open_core=False):
    center = AssessmentCandidate('S003-C0001' if open_core else 'S013-C2132', 'd' * 64)
    coordinates = tuple(ParameterCoordinate(key, .5, 0., 1., ParameterCoordinateKind.CONTINUOUS)
                        for key in ('x', 'y'))
    generated = build_parameter_perturbation_design(ParameterDesignRequest(
        center, helper.unified_protocol().parameter_protocol,
        ParameterSpace(coordinates, 'e' * 64, 'f' * 64)), feasibility=lambda point: True)
    design = generated.design
    assert type(design) is ParameterPerturbationDesign
    base = evidence(center, open_core=open_core)
    stress = evidence(center, pressure=True, open_core=open_core)
    neighbors = []
    for i in range(32):
        candidate = AssessmentCandidate(('S003-' if open_core else 'S013-') + f'C{i + 100:04d}', sha256(str(i).encode()).hexdigest())
        item = evidence(candidate, open_core=open_core, profit=5. + i * .1)
        neighbors.append(replace(item, parent=center, derivation_sha256=sha256(('lineage' + str(i)).encode()).hexdigest(),
                                 derivation_kind=AssessmentDerivationKind.PARAMETERS, parameter_point=design.bind_point(i)))
    return base, stress, tuple(neighbors), design


native_adapter = helper.build_assessment_evidence
calls = []


def adapted_spy(request, result):
    assert request is result.request
    calls.append(request)
    return result.evidence


def invoke(base, stress, children, design):
    def pair(item):
        token = object()
        return token, NS(request=token, evidence=(item,))
    helper.build_assessment_evidence = adapted_spy
    return helper.assess_unified(pair(base), pair(stress), tuple(pair(item) for item in children), design)


base, stress, children, design = fixtures()
out = invoke(base, stress, children, design)
request = CandidateAssessmentRequest.from_dict(out['assessment_request'])
panel = AssessmentPanel.from_dict(out['assessment_panel'])
metrics = {item.metric: item for item in panel.rows[0].diagnostics}
check('full serialized request and panel strong-type roundtrip', request.sha256 == out['assessment_request_sha256'] and panel.sha256 == out['assessment_panel_sha256'])
check('complete public v3 formula version', panel.formula_version == 'research-assessment-v3')
check('actual adapter delegation all 34 supplied pairs', len(calls) == 34)
check('complete exact declared32 lineage/point coverage', len(request.perturbations) == 32 and panel.rows[0].parameter_context.valid_points == 32)
check('missing whole family matrix remains explicit None', request.family_returns is None and out['applicability']['family_returns'] is None)
check('PBO and both DSR report evidence gaps', all(item.status is DiagnosticStatus.INSUFFICIENT_DATA and item.reason == 'FAMILY_RETURN_MATRIX_NOT_SUPPLIED' for item in panel.family_diagnostics))
check('all original five factors are available without family matrix', all(metrics[key].status is DiagnosticStatus.AVAILABLE for key in [ResearchMetric.PARAMETER_RETURN_DEGRADATION, ResearchMetric.PARAMETER_DRAWDOWN_DEGRADATION, ResearchMetric.ROLLING_EXCESS_Q10, ResearchMetric.PROFIT_CONCENTRATION, ResearchMetric.STRESS_ANNUAL_LOSS]) and panel.rows[0].uncertainty.status is DiagnosticStatus.AVAILABLE)
values = [(item.account[-1].equity / item.initial_cash) ** (252 / len(item.account)) - 1 for item in children]
center_return = (base.account[-1].equity / base.initial_cash) ** (252 / len(base.account)) - 1
check('parameter return degradation public LINEAR Q10 formula', metrics[ResearchMetric.PARAMETER_RETURN_DEGRADATION].value == max(0., center_return - float(np.quantile(values, .1, method='linear'))))
check('closed frequency uses full daily denominator and60 unit', metrics[ResearchMetric.FULL_SAMPLE_FREQUENCY].value == len(base.closed_cycles) * 60 / len(base.account))
check('configured stress is true one-way20bp', request.protocol.stress_scenario == 'stress_20bp_per_side' and stress.scenario_context.one_way_cost == .002)
check('protocol exactly matches requested fixed computation', request.protocol.to_dict() == helper.unified_protocol().to_dict())

core_base, core_stress, core_children, core_design = fixtures(open_core=True)
core_out = invoke(core_base, core_stress, core_children, core_design)
core_panel = AssessmentPanel.from_dict(core_out['assessment_panel'])
core_metrics = {item.metric: item for item in core_panel.rows[0].diagnostics}
check('open core partial sell not falsely closed', len(core_base.fills) == 2 and core_base.account[-1].quantity == 90 and not core_base.closed_cycles)
check('open core closed frequency zero is applicable count', core_metrics[ResearchMetric.FULL_SAMPLE_FREQUENCY].value == 0.)
check('no profitable closed cycles concentration is NOT_APPLICABLE', core_metrics[ResearchMetric.PROFIT_CONCENTRATION].status is DiagnosticStatus.NOT_APPLICABLE and core_metrics[ResearchMetric.PROFIT_CONCENTRATION].value is None and core_metrics[ResearchMetric.PROFIT_CONCENTRATION].reason == 'NO_PROFITABLE_CLOSED_CYCLES')
check('open core retains full account return and rolling uncertainty', core_metrics[ResearchMetric.NET_ANNUAL_RETURN].status is DiagnosticStatus.AVAILABLE and core_metrics[ResearchMetric.ROLLING_EXCESS_Q10].status is DiagnosticStatus.AVAILABLE and core_panel.rows[0].uncertainty.status is DiagnosticStatus.AVAILABLE)

for label, bad in [('EXECUTION lineage', replace(children[0], derivation_kind=AssessmentDerivationKind.EXECUTION, parameter_point=None)),
                   ('missing parameter binding', replace(children[0], parameter_point=None)),
                   ('wrong parent', replace(children[0], parent=AssessmentCandidate('S013-C9999', 'f' * 64))),
                   ('wrong point index', replace(children[0], parameter_point=design.bind_point(1))),
                   ('wrong point coordinates', replace(children[0], parameter_point=replace(design.bind_point(0), coordinates=(.5, .5)))),
                   ('wrong frequency units', replace(children[0], frequency_window_days=59))]:
    refuse(label, lambda bad=bad: invoke(base, stress, (bad, *children[1:]), design))
refuse('31 points cannot silently compute subset', lambda: invoke(base, stress, children[:-1], design))
refuse('repeated child and point refused', lambda: invoke(base, stress, (children[1], *children[1:]), design))
refuse('wrong pressure fee name not substitute', lambda: invoke(base, replace(stress, scenario_context=replace(stress.scenario_context, one_way_cost=.0015)), children, design))
refuse('wrong baseline fee refused', lambda: invoke(replace(base, scenario_context=replace(base.scenario_context, one_way_cost=.0015)), stress, children, design))
refuse('wrong pressure tier refused', lambda: invoke(base, replace(stress, scenario_context=replace(stress.scenario_context, measurement_tier='FORMAL')), children, design))
refuse('wrong center stress identity refused', lambda: invoke(base, replace(stress, candidate=children[0].candidate), children, design))
refuse('missing requested common baseline refused', lambda: invoke(replace(base, window_id='other'), stress, children, design))
refuse('SE design wrong type refused', lambda: invoke(base, stress, children, design.to_dict()))
refuse('different parameter protocol refused', lambda: invoke(base, stress, children, replace(design, protocol=replace(design.protocol, seed=14))))
helper.build_assessment_evidence = native_adapter
refuse('real public adapter refuses untyped raw input', lambda: helper.assess_unified((object(), object()), (object(), object()), tuple((object(), object()) for _ in range(32)), design))

proof = {'status': 'PASS', 'check_count': len(checks), 'checks': checks,
         'refusal_count': len(refusals), 'refusals': refusals,
         'source_sha256': sha256((HERE / 'assessment_helper.py').read_bytes()).hexdigest(),
         'focused_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
         'protocol': helper.unified_protocol().to_dict(),
         'market_reads': 0, 'real_native_account_reads': 0, 'account_evaluations': 0,
         'account_preparations': 0, 'family_matrix_invented': False,
         'scope': 'Real public SE computation on wholly synthetic ledgers; adapter delegation spy plus real public adapter type refusal. Actual TDR authentication remains the real adapter responsibility.'}
(HERE / 'focused.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: proof[key] for key in ['status', 'check_count', 'refusal_count', 'source_sha256']}, indent=2))
