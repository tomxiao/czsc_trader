"""Publish EX005 as PROTOTYPES/4 with exact, immutable historical controls."""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from czsc_trader.application import assemble_delivery, publish_evidence, validate_experiment
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite, ExperimentValidationRequest,
    ExperimentValidationScope, MaterialEvidenceWrite,
)
from czsc_trader.research_tools import delivery as d
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, ExecutionResources

from run import ROOT, WORK, EXPERIMENT, BATCH, REPOSITORY, context, read, save, material, configurations


CONTROL_ORIGINS = {
    'C0000': (3, 'EX002_20261028'),
    'C0013': (3, 'EX003_20261028'),
    'C0022': (3, 'EX004_20261028'),
    'C0025': (3, 'EX004_20261028'),
    'C0026': (3, 'EX004_20261028'),
}


def retained_delivery(revision, experiment_id):
    publication = read(ROOT/'research/S017/experiments'/experiment_id/'others/publication.json')
    reference = d.DeliveryReference.from_dict(publication['delivery']['reference'])
    if (reference.batch, reference.stage, reference.revision) != (BATCH, d.DeliveryStage.PROTOTYPES, revision):
        raise ValueError('retained publication does not identify the required exact predecessor')
    if publication['validation']['status'] != 'PASS' or publication['experiment_validation']['status'] != 'PASS':
        raise ValueError('retained predecessor publication has not passed validation')
    document = read(ROOT/'research/S017/assets/deliveries/PROTOTYPES'/str(revision)/'delivery.json')
    content = d.DeliveryContent.from_dict(document['content'])
    if not isinstance(content.payload, d.PrototypePanel):
        raise TypeError('retained predecessor must contain a typed PrototypePanel')
    return reference, publication, content


def publish():
    research = context()
    retained = {3: retained_delivery(3, 'EX004_20261028')}
    # Every retained control appears in revision 3, with its original formal
    # account identity. Revision 4 remains a stage-two research delivery.
    predecessors = (retained[3][0],)
    controls, component_pool, references = {}, {}, []
    for revision, (reference, publication, content) in retained.items():
        entries = {entry.prototype_id: entry for entry in content.payload.prototypes}
        component_pool.update({entry.component_id: entry for entry in content.payload.components})
        references.extend(EvidenceRef.from_dict(value) for value in publication['evidence'])
        references.append(EvidenceRef.from_dict(publication['report']))
        references.extend(content.evidence)
        for key, (origin_revision, origin_experiment) in CONTROL_ORIGINS.items():
            if revision != origin_revision:
                continue
            if key not in entries:
                raise ValueError(f'missing retained control {key}')
            entry = entries[key]
            if (len(entry.evaluations) != 1
                    or entry.evaluations[0].evidence.experiment.experiment_id != origin_experiment):
                raise ValueError('retained control must identify its original formal account')
            controls[key] = entry, reference

    accounts = read(WORK/'others/accounts.json')
    definitions = read(WORK/'protocols/definitions.json')
    judgments = read(WORK/'others/judgments.json')
    analysis = read(WORK/'others/analysis.json')
    precheck = read(WORK/'others/precheck.json')
    expected = set(configurations())
    if set(accounts) != expected or set(definitions) != expected or set(judgments['prototypes']) != expected:
        raise ValueError('EX005 accounts, definitions and judgments must cover exactly the three fixed structures')
    if set(judgments['control_judgments']) != set(CONTROL_ORIGINS):
        raise ValueError('control judgments must cover exactly the five retained controls')
    if analysis['status'] != 'PASS' or precheck['status'] != 'PASS':
        raise ValueError('analysis and focused precheck must pass before publication')
    required_diagnoses = {
        'C0027_vs_C0025', 'C0028_vs_C0025',
        'C0029_vs_C0027', 'C0029_vs_C0028',
    }
    if not required_diagnoses <= analysis['diagnostics'].keys():
        raise ValueError('EX005 is missing a required fixed account diagnosis')
    if any(value['status'] != 'COMPUTED' for value in analysis['diagnostics'].values()):
        raise ValueError('EX005 requires complete public account diagnoses')

    pre = {name: EvidenceRef.from_dict(value) for name,value in read(WORK/'others/pre_run_evidence.json').items()}
    if not {'design', 'source', 'definitions', 'runner', 'authorization'} <= pre.keys():
        raise ValueError('required EX005 pre-run protocol, authorization or implementation evidence is missing')
    if any(ref.experiment != EXPERIMENT for ref in pre.values()):
        raise ValueError('EX005 pre-run evidence has the wrong experiment origin')
    references.extend(pre.values())
    evidence = {}
    for name,path in (
        ('analysis', WORK/'others/analysis.json'),
        ('analysis-source', WORK/'src/analyze.py'),
        ('precheck', WORK/'others/precheck.json'),
        ('precheck-source', WORK/'src/precheck.py'),
        ('research-judgments', WORK/'others/judgments.json'),
        ('review-notes', WORK/'notes.md'),
        ('execution-status', WORK/'others/execution_status.json'),
        ('execution-stats', WORK/'others/execution_stats.json'),
        ('publication-source', Path(__file__)),
        ('figure-source', WORK/'src/plot.py'),
    ):
        evidence[name] = material(research, name, path)
        references.append(evidence[name])
    evidence['equity-path-figure'] = publish_evidence(research, MaterialEvidenceWrite(
        EXPERIMENT, 'equity-path-figure', (WORK/'others/equity_drawdown.png').read_bytes(), 'image/png', 'png'))
    references.append(evidence['equity-path-figure'])

    account_refs = {key: EvidenceRef.from_dict(value['evidence']) for key,value in accounts.items()}
    if any(ref.experiment != EXPERIMENT or (ref.schema, ref.schema_version) != ('equity_research', 2)
           for ref in account_refs.values()):
        raise ValueError('new account evidence must belong to EX005 and use equity_research/v2')
    references.extend(account_refs.values())
    for value in analysis['diagnostics'].values():
        ref = EvidenceRef.from_dict(value['evidence'])
        if ref.experiment != EXPERIMENT:
            raise ValueError('new diagnosis evidence must belong to EX005')
        references.append(ref)
    for key, (entry, _) in controls.items():
        account_refs[key] = entry.evaluations[0].evidence
        references.append(account_refs[key])

    definition_refs = {}
    for key,value in definitions.items():
        path = WORK/'protocols'/('definition-'+key+'.json')
        save(path, value)
        definition_refs[key] = material(research, 'definition-'+key, path)
        references.append(definition_refs[key])

    # Retain every component needed by a reused control; their immutable
    # historical tests keep their original experiment and evidence identities.
    required_components = {use.component_id for entry,_ in controls.values() for use in entry.components}
    if not required_components <= component_pool.keys():
        raise ValueError('retained controls refer to missing historical components')
    components = [component_pool[key] for key in sorted(required_components)]
    new_component_ids = [value['component_id'] for value in judgments['components']]
    if (len(set(new_component_ids)) != len(new_component_ids)
            or set(new_component_ids) & required_components
            or any(not key.startswith('risk-') for key in new_component_ids)):
        raise ValueError('new component IDs must be unique risk-prefixed names distinct from retained controls')
    for value in judgments['components']:
        key = value['component_id']
        components.append(d.ComponentEntry(
            key, d.ExperimentDefinitionRef(pre['source'], 'strategy:decide'),
            value['role'], value['label'], '下一执行区间及随后已完成30分钟收盘；日波幅仅用更早交易日',
            value['control'], '已完成且可得的价格历史与实际持仓周期；基本面不进入交易条件', 'RAW',
            'S017开发池、固定1%买入限价及0.1%单边费用；止损不保证成交价格', value['judgment'],
            (d.ComponentTestResult(key+'-test', EXPERIMENT.experiment_id, pre['design'],
                d.ComponentTestStatus(value['status']), value['judgment'],
                (evidence['analysis'], *(account_refs[k] for k in value['accounts']))),)))

    entries = []
    for key, (prior, origin) in controls.items():
        judgment = judgments['control_judgments'][key]
        entries.append(replace(prior,
            disposition=d.PrototypeDisposition(judgment['disposition']),
            judgment=judgment['judgment'], next_step=judgment['next_step'],
            sources=(d.PrototypeReference(origin, key),),
            evidence=tuple(dict.fromkeys((*prior.evidence, evidence['research-judgments'], evidence['analysis'])))))
    for key,value in judgments['prototypes'].items():
        candidate = EquityStrategyCandidate(BATCH.strategy_id, key,
            EquityStrategyDefinition.from_dict(definitions[key]), WORK/'src')
        entries.append(d.PrototypeEntry(
            key, d.CandidateIdentityRef(candidate.key, candidate.content_identity.content_sha256),
            d.ExperimentDefinitionRef(definition_refs[key], 'strategy:decide'), value['hypothesis'],
            tuple(d.PrototypeComponentUse(component, role, reason)
                  for component,role,reason in value['components']),
            (d.EvaluationEvidenceRef(account_refs[key], (accounts[key]['evaluation_id'],)),),
            d.PrototypeDisposition(value['disposition']), value['judgment'], tuple(value['limitations']), value['next_step'],
            (definition_refs[key], pre['source'], pre['design'], pre['authorization'],
             evidence['analysis'], evidence['research-judgments'])))
    comparisons = tuple(d.PrototypeComparison(
        value['id'], value['subject'], value['control'], value['question'], pre['design'],
        (evidence['analysis'], account_refs[value['subject']], account_refs[value['control']]), value['conclusion'])
        for value in judgments['comparisons'])
    panel = d.PrototypePanel(tuple(entries), tuple(components), comparisons, judgments['conclusion'])
    references = tuple(dict.fromkeys(references))
    if any(ref.experiment.strategy_id != BATCH.strategy_id for ref in references):
        raise ValueError('delivery evidence must stay within S017')
    references = references+(publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'trailing-path-figure',
        (WORK/'others/trailing_path.png').read_bytes(), 'image/png', 'png')),)
    report = (WORK/'report.md').read_text(encoding='utf-8')
    report_ref = publish_evidence(research, ExperimentReportWrite(
        EXPERIMENT, sha256(report.encode()).hexdigest(), ExperimentOutcome.COMPLETED, references))

    def progress(event):
        print(asdict(event), flush=True)

    assembled = assemble_delivery(REPOSITORY,
        d.DeliveryDefinition(BATCH, d.DeliveryStage.PROTOTYPES, 4, predecessors),
        d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (),
                          report=report, evidence=references+(report_ref,)),
        resources=ExecutionResources(max_workers=4, native_threads_per_worker=1, random_seed=17),
        on_progress=progress)
    checked = validate_experiment(REPOSITORY, ExperimentValidationRequest(
        EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {
        'delivery': assembled.receipt.to_dict(), 'validation': assembled.validation.to_dict(),
        'experiment_validation': checked.to_dict(), 'report': report_ref.to_dict(),
        'evidence': [ref.to_dict() for ref in references],
        'predecessor': retained[3][0].to_dict(),
        'predecessors': [reference.to_dict() for reference in predecessors],
        'predecessor_validation': 'Exact PROTOTYPES/3 predecessor and its dependencies included in assembly FULL validation',
    })
    if assembled.validation.status.value != 'PASS' or checked.status.value != 'PASS':
        raise RuntimeError('PROTOTYPES/4 or experiment report publication validation failed')
    print('PROTOTYPES/4', assembled.validation.status.value, checked.status.value, flush=True)


if __name__ == '__main__':
    publish()
