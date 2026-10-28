"""One serial PROTOTYPES/7 publisher; no replay, registration or experiment-report write.

Inputs: others/judgments.json plus explicitly listed successful experiments.
Commands: template prints the input template; check authenticates and constructs the
typed panel without publishing; publish adds owner material evidence and calls the
public assemble_delivery API. Run only after experiment report publications finish.

Historical PROTOTYPES/6 entries, comparisons, components, facts and explanations
are retained verbatim. New experiments must be explicitly listed: no directory
scan and no automatic inclusion of failed EX010 or later experiments. Judgment
text and enum decisions are supplied by RSCH, never inferred from performance.
Outputs: others/panel_publication.json and others/panel_report.md. The existing
others/publication.json continues to identify this experiment's separate report.
"""
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import argparse
import json

from czsc_trader.application import assemble_delivery, publish_evidence, validate_delivery, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentRef, ExperimentOutcome,
    ExperimentValidationRequest, ExperimentValidationScope, MaterialEvidenceWrite)
from czsc_trader.research_tools.experiment_artifacts import ExperimentReportSnapshot
from czsc_trader.research_tools import delivery as d
from strategy_runtime import EquityStrategyDefinition, ExecutionResources, equity_source_hash
from strategy_manager import CandidateKey
from run import ROOT, WORK, BATCH, REPOSITORY, EXPERIMENT, context, read, save

PREDECESSOR_EXPERIMENT = ExperimentRef('S017', 'EX008_20261029')
OWNER_JUDGMENTS = WORK / 'others/judgments.json'


def template():
    experiments = [('EX011_20261029', ['C0036', 'C0037']),
                   ('EX012_20261029', ['C0038', 'C0039']),
                   ('EX013_20261029', ['C0040', 'C0041', 'C0042'])]
    pairs = [('C0036', 'C0013'), ('C0037', 'C0013'), ('C0037', 'C0036'),
             ('C0038', 'C0013'), ('C0039', 'C0013'), ('C0039', 'C0038'),
             ('C0040', 'C0013'), ('C0041', 'C0013'), ('C0042', 'C0013'),
             ('C0042', 'C0040'), ('C0042', 'C0041')]
    mechanisms = [
        ('orb-complete-rule', 'EX011_20261029', [('C0036', 'C0013')]),
        ('orb-volume-gate', 'EX011_20261029', [('C0037', 'C0036')]),
        ('market-reversal-rule', 'EX012_20261029', [('C0038', 'C0013')]),
        ('market-reversal-antidip', 'EX012_20261029', [('C0039', 'C0038')]),
        ('spy-background-gate', 'EX013_20261029', [('C0040', 'C0013')]),
        ('xlk-day-participation-gate', 'EX013_20261029', [('C0041', 'C0013')]),
        ('market-industry-conjunction', 'EX013_20261029', [('C0042', 'C0040'), ('C0042', 'C0041')]),
    ]
    uses = {'C0036': ['orb-complete-rule'], 'C0037': ['orb-complete-rule', 'orb-volume-gate'],
        'C0038': ['market-reversal-rule'], 'C0039': ['market-reversal-rule', 'market-reversal-antidip'],
        'C0040': ['spy-background-gate'], 'C0041': ['xlk-day-participation-gate'],
        'C0042': ['spy-background-gate', 'xlk-day-participation-gate', 'market-industry-conjunction']}
    return {
        'schema_version': 1, 'revision': 7,
        'experiments': [{'experiment_id': exp, 'candidate_ids': keys} for exp, keys in experiments],
        'prototypes': {key: {
            'hypothesis': 'TODO:完整假设', 'inherit_components_from': 'C0013' if key in ('C0040', 'C0041', 'C0042') else None,
            'components': [{'component_id': name, 'role': 'TODO:职责', 'rationale': 'TODO:为什么使用'} for name in uses[key]],
            'disposition': 'TODO:DEVELOP|INVESTIGATE|STOP', 'judgment': 'TODO:整体价值和代价',
            'limitations': ['TODO:最强反证和证据限制'], 'next_step': 'TODO:下一项问题或停止依据'}
            for _, keys in experiments for key in keys},
        'components': [{'component_id': name, 'experiment_id': exp, 'role': 'TODO:职责',
            'label': 'TODO:机制说明', 'horizon': 'TODO:观察和持有跨度',
            'availability': 'TODO:决策时可得性', 'price_basis': 'RAW',
            'applicability': 'TODO:适用范围与执行前提', 'judgment': 'TODO:组件用途及限制',
            'tests': [{'subject': subject, 'control': control,
                'status': 'TODO:SUPPORTED|INEFFECTIVE|NOT_APPLICABLE|INSUFFICIENT_DATA|TECHNICAL_FAILURE|REDUNDANT',
                'judgment': 'TODO:精确对照结论，不将多因素整体替换称为单因素归因'} for subject, control in comparisons]}
            for name, exp, comparisons in mechanisms],
        'comparisons': [{'subject': subject, 'control': control, 'question': 'TODO:固定对照回答的问题',
                         'conclusion': 'TODO:完整账户结论及代价'} for subject, control in pairs],
        'conclusion': 'TODO:阶段二统一结论；保留旧判断，说明新原型、剩余问题及阶段边界',
    }


def check_fields(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(label + ' has unexpected or missing fields')


def reject_placeholders(value):
    if isinstance(value, str) and (not value.strip() or value.startswith('TODO')):
        raise ValueError('all judgment fields must be explicitly completed by RSCH')
    if isinstance(value, dict):
        for child in value.values():
            reject_placeholders(child)
    if isinstance(value, list):
        for child in value:
            reject_placeholders(child)


def evidence_bytes(reference):
    data = reference.resolve(ROOT).read_bytes()
    if sha256(data).hexdigest() != reference.sha256:
        raise ValueError('evidence changed after authentication')
    return data


def evidence_json(reference):
    return json.loads(evidence_bytes(reference))


def retained_panel(resources):
    publication = read(PREDECESSOR_EXPERIMENT.resolve(ROOT) / 'others/publication.json')
    receipt = d.DeliveryReceipt.from_dict(publication['delivery'])
    reference = receipt.reference
    if (reference.batch, reference.stage, reference.revision) != (BATCH, d.DeliveryStage.PROTOTYPES, 6):
        raise ValueError('predecessor must be exact S017 PROTOTYPES/6 from EX008')
    if publication['validation']['status'] != 'PASS' or publication['experiment_validation']['status'] != 'PASS':
        raise ValueError('retained predecessor publication did not pass')
    validation = validate_delivery(REPOSITORY, reference, scope=d.DeliveryValidationScope.INTEGRITY,
                                   resources=resources)
    if validation.status is not d.ValidationStatus.PASS:
        raise ValueError('retained predecessor integrity failed: ' + str(validation.issues))
    data = (ROOT / 'research/S017/assets/deliveries/PROTOTYPES/6/delivery.json').read_bytes()
    expected, = (item.sha256 for item in receipt.files if item.path == 'delivery.json')
    if sha256(data).hexdigest() != expected:
        raise ValueError('retained delivery document differs from its authenticated receipt')
    document = json.loads(data)
    definition = d.DeliveryDefinition.from_dict(document['definition'])
    content = d.DeliveryContent.from_dict(document['content'])
    if type(content.payload) is not d.PrototypePanel or content.status is not d.DeliveryStatus.COMPLETE:
        raise ValueError('retained predecessor must be a complete typed prototype panel')
    return reference, definition, content, publication


def successful_experiment(item):
    check_fields(item, ('experiment_id', 'candidate_ids'), 'experiment selection')
    experiment = ExperimentRef('S017', item['experiment_id'])
    keys = tuple(item['candidate_ids'])
    if not keys or len(set(keys)) != len(keys):
        raise ValueError('experiment selection needs unique candidate IDs')
    work = experiment.resolve(ROOT)
    publication, analysis = read(work / 'others/publication.json'), read(work / 'others/analysis.json')
    if (publication['experiment'] != experiment.experiment_id
            or publication['experiment_validation']['status'] != 'PASS'
            or publication['panel_published'] is not False
            or analysis['experiment'] != experiment.experiment_id or analysis['status'] != 'PASS'):
        raise ValueError('only successful standalone experiment reports may join the panel')
    accounts = read(work / 'others/accounts.json')
    if set(keys) != set(read(work / 'protocols/configurations.json')) or set(keys) != set(accounts):
        raise ValueError('explicit candidate selection must cover the entire successful fixed experiment')
    references = tuple(EvidenceRef.from_dict(value) for value in publication['evidence'])
    report_ref = EvidenceRef.from_dict(publication['report'])
    report = ExperimentReportSnapshot.from_dict(evidence_json(report_ref))
    if (report.experiment != experiment or report.outcome is not ExperimentOutcome.COMPLETED
            or report.evidence != references or report.report != (work / 'report.md').read_bytes().decode('utf-8')):
        raise ValueError('experiment report differs from its completed immutable publication')
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(experiment,
        ExperimentValidationScope.REPORT_PUBLICATION))
    if validation.status.value != 'PASS':
        raise ValueError('current experiment report validation failed')
    refs = set(references)
    pre = {key: EvidenceRef.from_dict(value) for key, value in read(work / 'others/pre_run_evidence.json').items()}
    materials = {key: EvidenceRef.from_dict(value) for key, value in publication['materials'].items()}
    if not set(pre.values()) <= refs or not set(materials.values()) <= refs:
        raise ValueError('published report omitted required source materials')
    if evidence_json(materials['analysis']) != analysis:
        raise ValueError('analysis changed after report publication')
    for name, relative in (('source', 'src/strategy.py'), ('design', 'protocols/design.md'),
                           ('authorization', 'protocols/authorization.md')):
        if evidence_bytes(pre[name]) != (work / relative).read_bytes() or pre[name].experiment != experiment:
            raise ValueError('new experiment pre-run source has changed')
    definitions, account_refs, identities = {}, {}, {}
    if set(publication['definitions']) != set(keys):
        raise ValueError('definition references must cover every new candidate')
    for key in keys:
        definition_ref = EvidenceRef.from_dict(publication['definitions'][key])
        account_ref = EvidenceRef.from_dict(publication['accounts'][key])
        if (definition_ref not in refs or account_ref not in refs
                or definition_ref.experiment != experiment or account_ref.experiment != experiment
                or account_ref != EvidenceRef.from_dict(accounts[key]['evidence'])
                or account_ref != EvidenceRef.from_dict(analysis['source_accounts'][key])):
            raise ValueError('candidate account or definition has a different original evidence reference')
        definition = EquityStrategyDefinition.from_dict(evidence_json(definition_ref))
        identity = accounts[key]['evaluation_identity']
        if (identity['candidate'] != {'strategy_id': 'S017', 'candidate_id': key}
                or identity['content_sha256'] != definition.content_identity.content_sha256
                or equity_source_hash(work / 'src', definition.source_files) != definition.source_sha256):
            raise ValueError('candidate evaluated identity and exact definition differ')
        payload = evidence_json(account_ref)
        if (payload['evaluation_identity'] != identity or payload['evaluation_id'] != accounts[key]['evaluation_id']
                or payload['request']['experiment'] != {'strategy_id': 'S017', 'experiment_id': experiment.experiment_id}):
            raise ValueError('formal account does not match the exact manifest identity')
        definitions[key], account_refs[key] = definition_ref, account_ref
        identities[key] = d.CandidateIdentityRef(CandidateKey('S017', key), definition.content_identity.content_sha256)
    diagnostics = {}
    for name, value in analysis['diagnostics'].items():
        ref = EvidenceRef.from_dict(value['evidence'])
        if (value['status'] != 'COMPUTED' or ref not in refs or ref.experiment != experiment
                or ref != EvidenceRef.from_dict(publication['diagnostics'][name])):
            raise ValueError('comparison is not a published completed public diagnosis')
        raw = evidence_json(ref)
        subject, control = name.split('_vs_')
        expected = [asdict(EvidenceRef.from_dict(analysis['source_accounts'][key])) for key in (control, subject)]
        if raw['status'] != 'COMPUTED' or raw['sources'] != expected:
            raise ValueError('diagnosis does not bind the requested original accounts')
        diagnostics[(subject, control)] = ref
    return {'experiment': experiment, 'keys': keys, 'publication': publication, 'analysis': analysis,
        'accounts': accounts, 'account_refs': account_refs, 'definitions': definitions, 'identities': identities,
        'diagnostics': diagnostics, 'materials': materials, 'pre': pre, 'report': report_ref, 'references': references}


def build(judgment, resources):
    check_fields(judgment, ('schema_version', 'revision', 'experiments', 'prototypes', 'components',
                            'comparisons', 'conclusion'), 'panel judgments')
    reject_placeholders(judgment)
    if judgment['schema_version'] != 1 or judgment['revision'] != 7:
        raise ValueError('this publisher supports only input schema 1 and PROTOTYPES/7')
    predecessor, old_definition, old, old_publication = retained_panel(resources)
    experiments, candidates, contrasts = {}, {}, {}
    for selected in judgment['experiments']:
        data = successful_experiment(selected)
        name = data['experiment'].experiment_id
        if name in experiments or set(data['keys']) & set(candidates):
            raise ValueError('duplicate experiment or candidate identity')
        experiments[name] = data
        candidates.update({key: data for key in data['keys']})
        for pair, ref in data['diagnostics'].items():
            if pair in contrasts:
                raise ValueError('duplicate comparison identity across experiments')
            contrasts[pair] = (data, ref)
    if not experiments or set(judgment['prototypes']) != set(candidates):
        raise ValueError('prototype judgments must cover every explicitly selected new candidate exactly')
    required = {'EX011_20261029': {'C0036', 'C0037'}, 'EX012_20261029': {'C0038', 'C0039'},
                'EX013_20261029': {'C0040', 'C0041', 'C0042'}}
    if any(name not in experiments or set(experiments[name]['keys']) != keys for name, keys in required.items()):
        raise ValueError('PROTOTYPES/7 must include all seven planned prototypes from EX011, EX012 and EX013')
    old_entries = {entry.prototype_id: entry for entry in old.payload.prototypes}
    if set(old_entries) & set(candidates):
        raise ValueError('new candidates cannot overwrite historical prototype identities or judgments')
    for (subject, control), (data, _) in contrasts.items():
        if subject not in data['keys']:
            raise ValueError('comparison subject must be from its published experiment')
        control_ref = EvidenceRef.from_dict(data['analysis']['source_accounts'][control])
        if control in old_entries:
            expected = {entry.evidence for entry in old_entries[control].evaluations}
        elif control in candidates:
            expected = {candidates[control]['account_refs'][control]}
        else:
            raise ValueError('comparison control is absent from the explicitly selected panel')
        if control_ref not in expected:
            raise ValueError('comparison silently replaced the historical or new control account')
    components = list(old.payload.components)
    names = {item.component_id for item in components}
    for item in judgment['components']:
        check_fields(item, ('component_id', 'experiment_id', 'role', 'label', 'horizon', 'availability',
                           'price_basis', 'applicability', 'judgment', 'tests'), 'component judgment')
        if item['component_id'] in names or not item['tests']:
            raise ValueError('new component must have a new identity and at least one explicit mechanism comparison')
        names.add(item['component_id'])
        data = experiments[item['experiment_id']]
        tests = []
        for test in item['tests']:
            check_fields(test, ('subject', 'control', 'status', 'judgment'), 'component test')
            pair = (test['subject'], test['control'])
            if pair not in data['diagnostics'] or pair[0] not in data['keys']:
                raise ValueError('component test must use this experiment\'s exact published comparison')
            sources = tuple(EvidenceRef.from_dict(data['analysis']['source_accounts'][key]) for key in pair)
            tests.append(d.ComponentTestResult(item['component_id'] + '-' + '-vs-'.join(pair),
                data['experiment'].experiment_id, data['pre']['design'], d.ComponentTestStatus(test['status']),
                test['judgment'], (data['materials']['analysis'], data['diagnostics'][pair], *sources)))
        components.append(d.ComponentEntry(item['component_id'], d.ExperimentDefinitionRef(data['pre']['source'],
            'strategy:decide'), item['role'], item['label'], item['horizon'],
            '; '.join(test['subject'] + ' versus ' + test['control'] for test in item['tests']),
            item['availability'], item['price_basis'], item['applicability'], item['judgment'], tuple(tests)))
    entries = list(old.payload.prototypes)
    for key, item in judgment['prototypes'].items():
        check_fields(item, ('hypothesis', 'inherit_components_from', 'components', 'disposition', 'judgment',
                           'limitations', 'next_step'), 'prototype judgment')
        data = candidates[key]
        inherited = () if item['inherit_components_from'] is None else old_entries[item['inherit_components_from']].components
        uses = inherited + tuple(d.PrototypeComponentUse(**use) for use in item['components'])
        if not uses:
            raise ValueError('new complete prototype must identify its component roles')
        entries.append(d.PrototypeEntry(key, data['identities'][key],
            d.ExperimentDefinitionRef(data['definitions'][key], 'strategy:decide'), item['hypothesis'], uses,
            (d.EvaluationEvidenceRef(data['account_refs'][key], (data['accounts'][key]['evaluation_id'],)),),
            d.PrototypeDisposition(item['disposition']), item['judgment'], tuple(item['limitations']), item['next_step'],
            tuple(dict.fromkeys((data['definitions'][key], data['pre']['source'], data['pre']['design'],
                data['pre']['authorization'], data['materials']['analysis'], data['report'])))))
    comparisons = list(old.payload.comparisons)
    pairs = []
    for item in judgment['comparisons']:
        check_fields(item, ('subject', 'control', 'question', 'conclusion'), 'comparison judgment')
        pair = (item['subject'], item['control'])
        if pair not in contrasts or pair in pairs:
            raise ValueError('comparison must identify one unique published diagnosis')
        pairs.append(pair)
        data, diagnosis = contrasts[pair]
        sources = tuple(EvidenceRef.from_dict(data['analysis']['source_accounts'][key]) for key in pair)
        comparisons.append(d.PrototypeComparison('panel7-' + '-vs-'.join(pair), *pair, item['question'],
            data['pre']['design'], (data['materials']['analysis'], diagnosis, *sources), item['conclusion']))
    if set(pairs) != set(contrasts):
        raise ValueError('comparison judgments must cover all selected experiment diagnoses exactly')
    panel = d.PrototypePanel(tuple(entries), tuple(components), tuple(comparisons), judgment['conclusion'])
    if (panel.prototypes[:len(old.payload.prototypes)] != old.payload.prototypes
            or panel.components[:len(old.payload.components)] != old.payload.components
            or panel.comparisons[:len(old.payload.comparisons)] != old.payload.comparisons):
        raise ValueError('historical entries or judgments changed')
    references = [*old.evidence, EvidenceRef.from_dict(old_publication['report'])]
    references.extend(EvidenceRef.from_dict(value) for value in old_publication['evidence'])
    for data in experiments.values():
        references.extend((*data['references'], data['report']))
    # Existing entries retain their original source references, including /5.
    predecessors = tuple(dict.fromkeys((predecessor, *old_definition.predecessors)))
    report = '# S017 PROTOTYPES/7 阶段二统一交付\n\n' + judgment['conclusion'] + '\n\n'
    report += 'PROTOTYPES/6历史条目、判断和原始证据全部保留；本次追加以下完整原型。\n\n'
    for key, item in judgment['prototypes'].items():
        report += f"- {key}：{item['disposition']}。{item['judgment']} 下一步：{item['next_step']}\n"
    report += '\n各实验的正式报告和完整账本见交付EvidenceRefs。开发池反复使用，不代表独立验证；本交付不注册候选、不进入阶段三、不冻结或部署。\n'
    return (d.DeliveryDefinition(BATCH, d.DeliveryStage.PROTOTYPES, 7, predecessors),
        d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, old.facts, old.explanations,
                          report=report, evidence=tuple(dict.fromkeys(references))))


def main(action, workers):
    if action == 'template':
        print(json.dumps(template(), ensure_ascii=False, indent=2))
        return
    if not 1 <= workers <= 4:
        raise ValueError('workers must fit the explicitly coordinated 1..4 budget')
    resources = ExecutionResources(max_workers=workers, native_threads_per_worker=1, random_seed=17)
    judgment_bytes = OWNER_JUDGMENTS.read_bytes()
    source_bytes = Path(__file__).read_bytes()
    judgment = json.loads(judgment_bytes)
    definition, content = build(judgment, resources)
    if action == 'check':
        print('PANEL_INPUTS_CHECKED', len(content.payload.prototypes), 'prototypes', flush=True)
        return
    from dataclasses import replace
    research = context(workers)
    additions = (
        publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'panel-judgments',
            judgment_bytes, 'application/json', 'json')),
        publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'panel-publication-source',
            source_bytes, 'text/plain', 'py')))
    content = replace(content, evidence=tuple(dict.fromkeys((*content.evidence, *additions))))
    save(WORK / 'others/panel_build.json', {'definition': definition.to_dict(),
        'candidate_ids': [entry.prototype_id for entry in content.payload.prototypes],
        'judgments': additions[0].to_dict(), 'source': additions[1].to_dict()})
    (WORK / 'others/panel_report.md').write_bytes(content.report.encode('utf-8'))
    result = assemble_delivery(REPOSITORY, definition, content, resources=resources,
        on_progress=lambda event: print(event, flush=True))
    save(WORK / 'others/panel_publication.json', {'delivery': result.receipt.to_dict(),
        'validation': result.validation.to_dict(), 'judgments': additions[0].to_dict(),
        'source': additions[1].to_dict(), 'evidence': [ref.to_dict() for ref in content.evidence]})
    if result.validation.status is not d.ValidationStatus.PASS:
        raise RuntimeError('unified prototype panel did not pass full public validation')
    print('PROTOTYPES/7 FULL PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['template', 'check', 'publish'])
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    main(args.action, args.workers)
