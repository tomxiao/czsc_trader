"""Publish corrected center-request provenance in EX080 report revision and ASSESSMENT/5.

``check`` only checks material/typed-input consistency and prints its digest.
``publish --reviewed-input-sha DIGEST --receipt .tmp/NEW.json`` publishes the corrected revision;
public assembly performs the complete source authentication and SE recomputation.
No accounts, candidate selection or platform mutation are performed here.
"""
from __future__ import annotations
# ruff: noqa: E402 -- native thread limits must precede numerical imports

import argparse
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from stage4 import ROOT, HOME, OUT, CACHE, EX, BATCH, ctx, read, save, predecessor, assert_protocol
from assessment import plans, protocol, short
from czsc_trader.application import (
    RepositoryContext, publish_evidence, assemble_delivery, validate_experiment,
)
from czsc_trader.research_tools import (
    EvidenceRef, ExecutionResources, MaterialEvidenceWrite, ExperimentOutcome,
    ExperimentReportWrite, ExperimentValidationRequest, ExperimentValidationScope,
)
from czsc_trader.research_tools import delivery as d
from strategy_evaluator import research_models as m

REQUIRED = (
    'assessment_request_v2.json', 'assessment_panel_v2.json', 'comparison_request_v2.json',
    'comparison_v2.json', 'target_bindings.json', 'summary_v2.json', 'audit.json',
    'fee_audit.json', 'common_415_checks.json', 'family_summary.json',
    'retained_sources.json', 'results.json', 'plan_refs.json', 'equivalence.json',
    'group_comparisons.json', 'group_summary_v2.json', 'recommendation.json',
    'center_replays.json', 'provenance_correction_v2.json', 'publication_attempt1.json',
)
MIME = {'py': 'text/x-python', 'json': 'application/json', 'csv': 'text/csv', 'md': 'text/markdown'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_refs(refs):
    return tuple(dict.fromkeys(refs))


def reference(raw):
    ref = EvidenceRef.from_dict(raw)
    require(ref.experiment.strategy_id == 'S015', 'Reference outside authorized batch')
    # Full authentication is deliberately delegated to public FULL assembly.
    require((ROOT / ref.repository_path).is_file(), f'Missing source: {ref.repository_path}')
    return ref


def rebase_report(text):
    destination = ROOT / 'research/S015/deliveries/ASSESSMENT/5'

    def replace_link(match):
        target = match.group(1)
        if '://' in target or target.startswith(('#', 'mailto:')):
            return match.group(0)
        require(not Path(target).is_absolute(), 'Report must use relative local links')
        path, separator, anchor = target.partition('#')
        resolved = (HOME / path).resolve()
        require(resolved.is_relative_to(ROOT), 'Report local link outside repository')
        require(resolved.exists(), f'Missing report link: {target}')
        relative = Path(os.path.relpath(resolved, destination)).as_posix()
        return '](' + relative + (separator + anchor if separator else '') + ')'

    return re.sub(r'\]\(([^)]+)\)', replace_link, text)


def prepare():
    assert_protocol()
    for name in REQUIRED:
        require((OUT / name).is_file(), f'Required result missing: {name}')
    report_path = HOME / 'report.md'
    pointer_path = HOME / 'report_ref.json'
    previous = reference(read(pointer_path)['report'])
    require(previous.experiment == EX and previous.schema == 'experiment_report',
            'A real previous EX080 report is required')
    require(reference(read(OUT / 'publication_attempt1.json')['previous_report']) == previous,
            'Previous report differs from the preserved failed assembly attempt')
    report = report_path.read_bytes()
    report_text = report.decode('utf-8')
    require('Status: COMPLETED' in report_text, 'Completed researcher-authored report required')
    cr, candidates = predecessor('CANDIDATES', 9,
        '31272c048a128a7f0bbbadb784baa500d45120ed215ac738c59044e6eef5698b')
    mr, _ = predecessor('MANDATE', 5,
        '21b74f69453b3f9cd93ca674981e6f6cd0255ddb336af444215c3f457f83354b')
    old = d.DeliveryReceipt.from_dict(read(
        ROOT / 'research/S015/assets/deliveries/ASSESSMENT/4/receipt.json')).reference
    require(old.stage is d.DeliveryStage.ASSESSMENT and old.revision == 4,
            'Prior assessment must remain an independent predecessor')
    request = m.CandidateAssessmentRequest.from_dict(read(OUT / 'assessment_request_v2.json'))
    panel = m.AssessmentPanel.from_dict(read(OUT / 'assessment_panel_v2.json'))
    comparison_request = m.CandidateComparisonRequest.from_dict(read(OUT / 'comparison_request_v2.json'))
    comparison = m.CandidateComparison.from_dict(read(OUT / 'comparison_v2.json'))
    summary = read(OUT / 'summary_v2.json')
    bindings = read(OUT / 'target_bindings.json')
    recommendation = read(OUT / 'recommendation.json')
    require(isinstance(recommendation.get('recommendation'), str)
            and recommendation['recommendation'].strip(), 'Explicit research recommendation required')
    require(isinstance(recommendation.get('pending_decisions'), list)
            and recommendation['pending_decisions'], 'User decisions must remain pending')
    require(bindings['reference'] == mr.to_dict(), 'Mandate binding changed')
    ids = {x['candidate_id'] for x in candidates['handoff']}
    require(len(request.centers) == len(ids) == 29 and {short(x) for x in request.centers} == ids,
            'All 29 handoff centers required')
    require(request.protocol == protocol() and len(request.perturbations) == 177
            and len(request.parameter_designs) == 29 and len(request.evidence) == 812,
            'Full agreed assessment scope required')
    planned = plans()
    require({x for x in request.parameter_designs} == {plan.design for _, _, plan in planned},
            'Assessment designs differ from published plans')
    require(panel.request_sha256 == request.sha256 and panel.protocol_sha256 == request.protocol.sha256,
            'Panel input identity mismatch')
    require(comparison_request.panel == panel
            and comparison.request_sha256 == comparison_request.sha256
            and set(comparison_request.candidates) == set(request.centers),
            'Comparison identity or center scope changed')
    require(comparison_request.policy.missing_evidence_policy is m.MissingEvidencePolicy.REQUIRE_COMPLETE,
            'Original complete-evidence comparison policy required')
    for collection in (panel.rows, comparison.rows):
        require(len(collection) == 29 and {x.candidate for x in collection} == set(request.centers),
                'Every center must be represented exactly once')
    for row in comparison.rows:
        checks = [x for x in row.target_checks if isinstance(x, m.ParameterNeighborhoodCheck)]
        require(len(checks) == 1 and checks[0].required_points == checks[0].valid_points > 0,
                'Every planned point must have valid evidence')
        require((checks[0].target.minimum_numerator, checks[0].target.minimum_denominator) == (13, 16),
                'Approved parameter pass fraction changed')
    require(dict(Counter(x.status.value for x in comparison.rows)) == summary['status_counts']
            and dict(Counter(x.acceptance_status.value for x in comparison.rows)) == summary['acceptance_counts'],
            'Summary counts differ from comparison')
    common = {x['candidate_id']: x for x in read(OUT / 'common_415_checks.json')}
    require(set(common) == ids, 'Common 415-day checks must cover every center')
    qualified = sum(x.acceptance_status.value == 'PASSED' and common[short(x.candidate)]['passed']
                    for x in comparison.rows)
    require(qualified == summary['qualified_count'], 'Full authorized-target count differs')
    audit = read(OUT / 'audit.json')
    fee = read(OUT / 'fee_audit.json')
    require(audit['status'] == 'PASS' and len(audit['accounts']) == audit['parameter_accounts'] == 177,
            'Complete parameter audit required')
    require(fee['status'] == 'ARITHMETIC_AND_IDENTITY_PASS' and fee['candidates'] == 29,
            'Complete cost audit required')
    require(audit['reused_fee_audit']['sha256'] == sha256((OUT / 'fee_audit.json').read_bytes()).hexdigest(),
            'Reused fee audit changed')
    retained = read(OUT / 'retained_sources.json')
    replaced = [x for x in retained if x['source_role'] == 'family' and x['candidate_id'] in ids]
    retained_current = [x for x in retained if x not in replaced]
    replay_document = read(OUT / 'center_replays.json')
    replays = replay_document['rows']
    require(replay_document['status'] == 'PASS' and replay_document['new_accounts'] == 29
            and all(x['exact_five_ledgers'] and x['signals_equal'] and x['plan_request_matches']
                    for x in replays), 'Actual exact-request replays and equivalence checks required')
    require(len(replaced) == len(replays) == 29
            and {x['candidate_id'] for x in replays} == ids,
            'Replace exactly the 29 historical standard-center requests')
    sources = [*retained_current, *replays, *audit['accounts']]
    require(len(sources) == 833, 'Expected 627 retained, 29 replayed centers and 177 parameters')
    by_id = {x.evaluation_id: x for x in request.evidence}
    require(len(by_id) == 812, 'Repeated projection identity')
    source_ids = {x['evaluation_id'] for x in sources}
    require(len(source_ids) == 833 and set(by_id) <= source_ids, 'Projection source coverage differs')
    for source in sources:
        item = by_id.get(source['evaluation_id'])
        if item is not None:
            require(short(item.candidate) == source['candidate_id'], 'Projection source candidate mismatch')
            if 'content_sha256' in source:
                require(item.candidate.content_sha256 == source['content_sha256'],
                        'Retained source content identity differs')
    family = read(HOME / 'protocols/family.json')
    require(request.family_returns.raw_trial_count == 606
            and {short(x) for x in request.family_returns.candidates} == set(family['retained_ids']),
            'Complete historical selection family must remain')
    require(source_ids - set(by_id) == {
        x['evaluation_id'] for x in sources if x['candidate_id'] in {v['excluded'] for v in family['excluded']}
    }, 'Only documented family aliases may be omitted from projections')
    for center in request.centers:
        base = [x for x in request.evidence if x.candidate == center and x.scenario_id == 'standard']
        stress = [x for x in request.evidence if x.candidate == center and x.scenario_id == 'fee_x2']
        require(len(base) == len(stress) == 1, 'Exactly one center standard/pressure pair required')
        base, stress = base[0], stress[0]
        plan = next(plan for _, _, plan in planned if plan.design.center == center)
        replay = next(x for x in replays if x['candidate_id'] == short(center))
        require(base.request_sha256 == replay['request_hash'] == plan.center_request_sha256,
                'Center evidence must use the exact published plan request')
        require(base.window_id == stress.window_id == 'full'
                and base.context_sha256 == stress.context_sha256
                and base.metric_version == stress.metric_version, 'Pressure context mismatch')
        require(base.scenario_context.one_way_cost == .001
                and stress.scenario_context.one_way_cost == .002
                and stress.scenario_context.measurement_tier == 'STRESS'
                and replace(stress.scenario_context, one_way_cost=.001,
                            measurement_tier=base.scenario_context.measurement_tier) == base.scenario_context,
                'Pressure may change only cost and declared tier')
    refs = [reference(x['evidence']) for x in sources]
    require(len(unique_refs(refs)) == 833, 'Every original account source must remain available')
    controls = read(OUT / 'equivalence.json')
    require(len(controls) == 2 and all(x['status'] == 'PASS' and x['ledgers'] == 5 for x in controls),
            'Both serial/parallel five-ledger controls must pass')
    for control in controls:
        refs.extend((reference(control['serial']), reference(control['parallel'])))
    for name in ('protocol_refs.json', 'fee_protocol_refs.json', 'family_protocol_refs.json'):
        refs.extend(reference(x) for x in read(OUT / name).values())
    refs.extend(reference(x) for x in family['proofs'])
    refs.extend(ref for _, ref, _ in planned)
    paths = sorted({
        report_path, pointer_path, OUT / 'publication_attempt1.json',
        *[p for p in (HOME / 'src').glob('*.py')],
        *[p for p in (HOME / 'protocols').rglob('*') if p.is_file() and p.suffix[1:] in MIME],
        *[p for p in OUT.iterdir() if p.is_file() and p.suffix[1:] in MIME
          and not p.name.startswith(('publication_', 'published_report'))
          and p.name != 'center_replay_progress.json'],
        HOME / 'platform_requirement.md',
        CACHE / 'nonparameter_request.json',
        HOME.parent / 'EX074_20261024/src/account_audit.py',
        HOME.parent / 'EX066_20261024/src/audit.py',
        HOME.parent / 'EX063_20261024/others/comparison_request.json',
    })
    manifest = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in paths}
    digest = sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    materials, writes = {}, []
    for path in paths:
        if path in (report_path, pointer_path):
            continue
        relative, raw, suffix = path.relative_to(ROOT).as_posix(), path.read_bytes(), path.suffix[1:]
        require(sha256(raw).hexdigest() == manifest[relative], 'Material changed during preflight')
        materials[relative] = EvidenceRef(EX, f'{manifest[relative]}.{suffix}', manifest[relative], MIME[suffix], path.stem)
        writes.append((relative, MaterialEvidenceWrite(EX, path.stem, raw, MIME[suffix], suffix)))
    all_refs = unique_refs((*refs, *materials.values()))
    def material(name):
        return materials[(OUT / name).relative_to(ROOT).as_posix()]
    plan_refs = tuple(ref for _, ref, _ in planned)
    payload = d.CandidateAssessmentDelivery(
        cr, mr, request, panel, comparison_request, comparison,
        tuple(d.TargetMandateBinding(k, v) for k, v in sorted(bindings['bindings'].items())),
        bindings['frequency'], bindings['benchmark'], recommendation['recommendation'],
        (material('summary_v2.json'), material('family_summary.json'), material('audit.json'),
         material('group_summary_v2.json'), material('recommendation.json')),
        tuple(recommendation['pending_decisions']), parameter_plans=plan_refs,
    )
    facts = (
        d.FactValue('parameter_valid_designs', 29, 'candidate_designs', d.FactStatus.AVAILABLE, plan_refs),
        d.FactValue('parameter_accounts', 177, 'local_sensitivity_accounts', d.FactStatus.AVAILABLE,
                    (material('audit.json'),)),
        d.FactValue('center_replay_accounts', 29, 'standard_center_accounts', d.FactStatus.AVAILABLE,
                    (material('center_replays.json'), material('provenance_correction_v2.json'))),
        d.FactValue('qualified', qualified, 'candidate_identities', d.FactStatus.AVAILABLE,
                    (material('summary_v2.json'),)),
        d.FactValue('expanded_selection_family', 606, 'configuration_columns', d.FactStatus.AVAILABLE,
                    (material('family_summary.json'),)),
    )
    content = d.DeliveryContent(payload, d.DeliveryStatus.COMPLETE, facts, (),
        incomplete_items=(), report=rebase_report(report_text), evidence=all_refs)
    return {
        'manifest': manifest, 'digest': digest, 'materials': materials, 'writes': writes,
        'definition': d.DeliveryDefinition(BATCH, d.DeliveryStage.ASSESSMENT, 5, (cr, mr, old)),
        'content': content, 'qualified': qualified,
        'previous_report': previous,
        'report_write': ExperimentReportWrite(EX, sha256(report).hexdigest(),
                                              ExperimentOutcome.COMPLETED, all_refs, previous=previous),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'publish'))
    parser.add_argument('--reviewed-input-sha')
    parser.add_argument('--receipt')
    args = parser.parse_args()
    data = prepare()
    if args.mode == 'check':
        print(json.dumps({'status': 'STRUCTURAL_READY_FOR_FULL_VALIDATION',
            'input_sha256': data['digest'], 'centers': 29, 'parameter_accounts': 177,
            'new_center_accounts': 29, 'source_account_references': 833,
            'retained_and_new_physical_sources': 862, 'qualified': data['qualified'],
            'recommendation': data['content'].payload.recommendation}, ensure_ascii=False), flush=True)
        return
    require(args.reviewed_input_sha == data['digest'], 'Inputs changed or review digest absent')
    require(args.receipt, 'Fresh .tmp receipt path required')
    output = (ROOT / args.receipt).resolve()
    require(output.is_relative_to(ROOT / '.tmp') and not output.exists(), 'Fresh .tmp receipt required')
    require(not (ROOT / 'research/S015/deliveries/ASSESSMENT/5').exists(), 'ASSESSMENT/5 already exists')
    require(EvidenceRef.from_dict(read(HOME / 'report_ref.json')['report']) == data['previous_report'],
            'Previous report pointer changed after review')
    journal = {'status': 'STARTED', 'input_sha256': data['digest'], 'inputs': data['manifest'], 'materials': {}}
    save(output, journal)
    context = ctx(8)
    for relative, write in data['writes']:
        require(sha256((ROOT / relative).read_bytes()).hexdigest() == data['manifest'][relative],
                'Reviewed material changed')
        ref = publish_evidence(context, write)
        require(ref == data['materials'][relative], 'Published material differs from reviewed material')
        journal['materials'][relative] = ref.to_dict()
    save(output, journal)
    report = publish_evidence(context, data['report_write'])
    repository = RepositoryContext.discover(ROOT)
    checked = validate_experiment(repository,
        ExperimentValidationRequest(EX, ExperimentValidationScope.REPORT_PUBLICATION))
    journal.update(report=report.to_dict(), experiment_validation=checked.to_dict())
    save(output, journal)
    require(checked.status.value == 'PASS', 'Experiment report validation failed')

    def progress(event):
        if event.completed % 64 == 0 or event.completed == event.total:
            print('VALIDATION', event.phase.value, event.completed, event.total, flush=True)

    print('ASSEMBLE_ASSESSMENT_FULL', 5, flush=True)
    content = replace(data['content'], evidence=unique_refs((*data['content'].evidence, report)))
    result = assemble_delivery(repository, data['definition'], content,
                               resources=ExecutionResources(8, 1, 13), on_progress=progress)
    require(result.validation.status is d.ValidationStatus.PASS
            and result.validation.scope is d.DeliveryValidationScope.FULL, 'FULL validation did not pass')
    journal.update(assembly=result.to_dict(), status='ASSESSMENT_FULL_PASS')
    save(output, journal)
    print(json.dumps({'status': journal['status'], 'reference': result.receipt.reference.to_dict(),
                      'qualified': data['qualified'], 'selected': 0}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
