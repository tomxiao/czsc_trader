"""Publish EX003 as PROTOTYPES/2, retaining exact EX002 controls and evidence."""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from czsc_trader.application import (
    assemble_delivery, publish_evidence, validate_experiment,
)
from czsc_trader.research_tools import (
    EvidenceRef, ExperimentOutcome, ExperimentReportWrite, ExperimentValidationRequest,
    ExperimentValidationScope, MaterialEvidenceWrite,
)
from czsc_trader.research_tools import delivery as d
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition, ExecutionResources

from run import ROOT, WORK, EXPERIMENT, BATCH, REPOSITORY, context, read, save, material, configurations


def publish():
    research = context()
    old_work = ROOT/'research/S017/experiments/EX002_20261028'
    previous = read(old_work/'others/publication.json')
    old_reference = d.DeliveryReference.from_dict(previous['delivery']['reference'])
    if (old_reference.batch, old_reference.stage, old_reference.revision) != (BATCH, d.DeliveryStage.PROTOTYPES, 1):
        raise ValueError('EX003 requires the exact S017 PROTOTYPES/1 predecessor')
    if previous['validation']['status'] != 'PASS' or previous['experiment_validation']['status'] != 'PASS':
        raise ValueError('predecessor publication is not complete and validated')
    # assemble_delivery authenticates this exact predecessor recursively in FULL.
    old_document = read(ROOT/'research/S017/assets/deliveries/PROTOTYPES/1/delivery.json')
    old_content = d.DeliveryContent.from_dict(old_document['content'])
    if not isinstance(old_content.payload, d.PrototypePanel):
        raise TypeError('predecessor must contain a typed PrototypePanel')
    old_entries = {item.prototype_id: item for item in old_content.payload.prototypes}
    old_components = {item.component_id: item for item in old_content.payload.components}
    if not {'C0000', 'C0001'} <= old_entries.keys() or 'slow-direction' not in old_components:
        raise ValueError('required retained controls or slow-direction component are absent')

    accounts = read(WORK/'others/accounts.json')
    definitions = read(WORK/'protocols/definitions.json')
    judgments = read(WORK/'others/judgments.json')
    analysis = read(WORK/'others/analysis.json')
    expected = set(configurations())
    if set(accounts) != expected or set(definitions) != expected or set(judgments['prototypes']) != expected:
        raise ValueError('EX003 accounts, definitions and judgments must cover exactly its three fixed structures')
    if set(judgments['control_judgments']) != {'C0000', 'C0001'}:
        raise ValueError('control judgments must cover exactly C0000 and C0001')
    if analysis['status'] != 'PASS' or len(analysis['diagnostics']) != 3:
        raise ValueError('EX003 analysis and three diagnoses must be complete')
    if any(value['status'] != 'COMPUTED' for value in analysis['diagnostics'].values()):
        raise ValueError('EX003 contains an incomplete diagnosis')

    old_evidence = tuple(EvidenceRef.from_dict(value) for value in previous['evidence'])
    old_report = EvidenceRef.from_dict(previous['report'])
    references = [*old_evidence, old_report, *old_content.evidence]
    pre = {name: EvidenceRef.from_dict(value) for name,value in read(WORK/'others/pre_run_evidence.json').items()}
    if any(ref.experiment != EXPERIMENT for ref in pre.values()):
        raise ValueError('EX003 pre-run evidence has the wrong experiment origin')
    references.extend(pre.values())
    evidence = {}
    for name,path in (
        ('analysis', WORK/'others/analysis.json'),
        ('analysis-source', WORK/'src/analyze.py'),
        ('precheck', WORK/'others/precheck.json'),
        ('precheck-source', WORK/'src/precheck.py'),
        ('research-judgments', WORK/'others/judgments.json'),
        ('execution-status', WORK/'others/execution_status.json'),
        ('execution-stats', WORK/'others/execution_stats.json'),
        ('publication-source', Path(__file__)),
        ('figure-source', WORK/'src/plot.py'),
    ):
        evidence[name] = material(research, name, path)
        references.append(evidence[name])
    references.append(publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'equity-path-figure',
        (WORK/'others/equity_drawdown.png').read_bytes(), 'image/png', 'png')))
    account_refs = {key: EvidenceRef.from_dict(value['evidence']) for key,value in accounts.items()}
    if any(ref.experiment != EXPERIMENT or (ref.schema, ref.schema_version) != ('equity_research', 2)
           for ref in account_refs.values()):
        raise ValueError('new account evidence must belong to EX003 and use equity_research/v2')
    references.extend(account_refs.values())
    for value in analysis['diagnostics'].values():
        ref = EvidenceRef.from_dict(value['evidence'])
        if ref.experiment != EXPERIMENT:
            raise ValueError('new diagnosis evidence must belong to EX003')
        references.append(ref)
    for key in ('C0000', 'C0001'):
        evaluations = old_entries[key].evaluations
        if len(evaluations) != 1 or evaluations[0].evidence.experiment.experiment_id != 'EX002_20261028':
            raise ValueError('retained control must identify one original EX002 account')
        account_refs[key] = evaluations[0].evidence

    definition_refs = {}
    for key,value in definitions.items():
        path = WORK/'protocols'/('definition-'+key+'.json')
        save(path, value)
        definition_refs[key] = material(research, 'definition-'+key, path)
        references.append(definition_refs[key])

    prior_direction = old_components['slow-direction']
    direction_judgment = judgments['slow_direction_judgment']
    direction_test = d.ComponentTestResult('slow-direction-buffer-followup', EXPERIMENT.experiment_id, pre['design'],
        d.ComponentTestStatus.INEFFECTIVE, direction_judgment,
        (evidence['analysis'], account_refs['C0001'], account_refs['C0013']))
    components = [replace(prior_direction, judgment=direction_judgment, tests=prior_direction.tests+(direction_test,))]
    for value in judgments['components']:
        key = value['component_id']
        if key == 'slow-direction':
            raise ValueError('retain the historical slow-direction component without overwriting it')
        components.append(d.ComponentEntry(
            key, d.ExperimentDefinitionRef(pre['source'], 'strategy:decide'),
            value['role'], value['label'], '下一执行区间及后续已完成30分钟决策', value['control'],
            '仅已完成且可得的OHLC与实际持仓', 'RAW',
            'S017开发池、固定1%限价及0.1%单边费用', value['judgment'],
            (d.ComponentTestResult(key+'-test', EXPERIMENT.experiment_id, pre['design'],
                d.ComponentTestStatus(value['status']), value['judgment'],
                (evidence['analysis'], *(account_refs[k] for k in value['accounts']))),)))

    entries = []
    for key in ('C0000', 'C0001'):
        judgment = judgments['control_judgments'][key]
        prior = old_entries[key]
        entries.append(replace(prior,
            disposition=d.PrototypeDisposition(judgment['disposition']),
            judgment=judgment['judgment'], next_step=judgment['next_step'],
            sources=(d.PrototypeReference(old_reference, key),),
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
            (definition_refs[key], pre['source'], pre['design'], evidence['analysis'], evidence['research-judgments'])))
    comparisons = tuple(d.PrototypeComparison(
        value['id'], value['subject'], value['control'], value['question'], pre['design'],
        (evidence['analysis'], account_refs[value['subject']], account_refs[value['control']]), value['conclusion'])
        for value in judgments['comparisons'])
    panel = d.PrototypePanel(tuple(entries), tuple(components), comparisons, judgments['conclusion'])
    references = tuple(dict.fromkeys(references))
    if any(ref.experiment.strategy_id != BATCH.strategy_id for ref in references):
        raise ValueError('delivery evidence must stay within S017')
    report = (WORK/'report.md').read_text(encoding='utf-8')
    report_ref = publish_evidence(research, ExperimentReportWrite(
        EXPERIMENT, sha256(report.encode()).hexdigest(), ExperimentOutcome.COMPLETED, references))

    def progress(event):
        print(asdict(event), flush=True)

    assembled = assemble_delivery(REPOSITORY,
        d.DeliveryDefinition(BATCH, d.DeliveryStage.PROTOTYPES, 2, (old_reference,)),
        d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (),
                          report=report, evidence=references+(report_ref,)),
        resources=ExecutionResources(max_workers=3, native_threads_per_worker=1, random_seed=17),
        on_progress=progress)
    checked = validate_experiment(REPOSITORY, ExperimentValidationRequest(
        EXPERIMENT, ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {
        'delivery': assembled.receipt.to_dict(), 'validation': assembled.validation.to_dict(),
        'experiment_validation': checked.to_dict(), 'report': report_ref.to_dict(),
        'evidence': [ref.to_dict() for ref in references],
        'predecessor': old_reference.to_dict(), 'predecessor_validation': 'Included in assembly FULL validation',
    })
    if assembled.validation.status.value != 'PASS' or checked.status.value != 'PASS':
        raise RuntimeError('PROTOTYPES/2 or experiment report publication validation failed')
    print('PROTOTYPES/2', assembled.validation.status.value, checked.status.value, flush=True)


if __name__ == '__main__':
    publish()
