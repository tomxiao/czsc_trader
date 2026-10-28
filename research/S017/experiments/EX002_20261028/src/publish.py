"""Publish the reviewed stage-two interpretation with exact account references."""
from hashlib import sha256
from pathlib import Path
from dataclasses import asdict

from czsc_trader.application import publish_evidence, assemble_delivery, validate_experiment
from czsc_trader.research_tools import EvidenceRef, ExperimentReportWrite, ExperimentOutcome, ExperimentValidationRequest, ExperimentValidationScope
from czsc_trader.research_tools import delivery as d
from strategy_runtime import EquityStrategyDefinition, EquityStrategyCandidate, ExecutionResources
from run import WORK, EXPERIMENT, BATCH, REPOSITORY, context, read, save, material


def publish():
    research = context()
    accounts = read(WORK/'others/accounts.json')
    definitions = read(WORK/'protocols/definitions.json')
    judgments = read(WORK/'others/judgments.json')
    analysis = read(WORK/'others/analysis.json')
    pre = {k: EvidenceRef.from_dict(v) for k,v in read(WORK/'others/pre_run_evidence.json').items()}
    references = list(pre.values())
    evidence = {}
    for name,path in [('analysis', WORK/'others/analysis.json'), ('analysis-source', WORK/'src/analyze.py'),
                      ('precheck', WORK/'others/precheck.json'), ('precheck-source', WORK/'src/precheck.py'),
                      ('research-judgments', WORK/'others/judgments.json'), ('review-notes', WORK/'notes.md'),
                      ('signal-audit', WORK/'others/signal_audit.json'), ('signal-audit-source', WORK/'src/signal_audit.py'),
                      ('execution-status', WORK/'others/execution_status.json'), ('execution-stats', WORK/'others/execution_stats.json'),
                      ('publication-source', Path(__file__))]:
        evidence[name] = material(research, name, path)
        references.append(evidence[name])
    account_refs = {k: EvidenceRef.from_dict(v['evidence']) for k,v in accounts.items()}
    references.extend(account_refs.values())
    references.extend(EvidenceRef.from_dict(x['evidence']) for x in analysis['diagnostics'].values())
    definition_refs = {}
    for key,value in definitions.items():
        path = WORK/'protocols'/('definition-'+key+'.json')
        save(path, value)
        definition_refs[key] = material(research, 'definition-'+key, path)
        references.append(definition_refs[key])
    components = []
    for value in judgments['components']:
        key = value['component_id']
        components.append(d.ComponentEntry(key, d.ExperimentDefinitionRef(pre['source'], 'strategy:decide'),
            value['role'], value['label'], '下一执行区间及后续已完成30分钟决策', value['control'],
            '仅已完成且可得的OHLC与实际持仓', 'RAW', 'S017开发池、固定1%限价及0.1%单边费用', value['judgment'],
            (d.ComponentTestResult(key+'-test', EXPERIMENT.experiment_id, pre['design'], d.ComponentTestStatus(value['status']),
                value['judgment'], (evidence['analysis'], *(account_refs[k] for k in value['accounts']))),)))
    entries = []
    for key,value in judgments['prototypes'].items():
        cand = EquityStrategyCandidate('S017', key, EquityStrategyDefinition.from_dict(definitions[key]), WORK/'src')
        entries.append(d.PrototypeEntry(key, d.CandidateIdentityRef(cand.key, cand.content_identity.content_sha256),
            d.ExperimentDefinitionRef(definition_refs[key], 'strategy:decide'), value['hypothesis'],
            tuple(d.PrototypeComponentUse(c, role, reason) for c,role,reason in value['components']),
            (d.EvaluationEvidenceRef(account_refs[key], (accounts[key]['evaluation_id'],)),),
            d.PrototypeDisposition(value['disposition']), value['judgment'], tuple(value['limitations']), value['next_step'],
            (definition_refs[key], pre['source'], pre['design'], evidence['analysis'])))
    comparisons = tuple(d.PrototypeComparison(x['id'],x['subject'],x['control'],x['question'],pre['design'],
        (evidence['analysis'], account_refs[x['subject']], account_refs[x['control']]), x['conclusion']) for x in judgments['comparisons'])
    references = tuple(dict.fromkeys(references))
    report = (WORK/'report.md').read_text(encoding='utf-8')
    report_ref = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, sha256(report.encode()).hexdigest(), ExperimentOutcome.COMPLETED, references))
    mandate = read(WORK/'others/authorization_publication.json')['mandate']['reference']
    def progress(event):
        print(asdict(event), flush=True)
    assembled = assemble_delivery(REPOSITORY, d.DeliveryDefinition(BATCH, d.DeliveryStage.PROTOTYPES,1,(d.DeliveryReference.from_dict(mandate),)),
        d.DeliveryContent(d.PrototypePanel(tuple(entries),tuple(components),comparisons,judgments['conclusion']),
            d.DeliveryStatus.COMPLETE, (), (), report=report, evidence=references+(report_ref,)),
        resources=ExecutionResources(max_workers=1, native_threads_per_worker=1, random_seed=17), on_progress=progress)
    checked = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'delivery':assembled.receipt.to_dict(), 'validation':assembled.validation.to_dict(),
        'experiment_validation':checked.to_dict(), 'report':report_ref.to_dict(), 'evidence':[r.to_dict() for r in references]})
    assert checked.status.value == 'PASS'
    print('PROTOTYPES/1', assembled.validation.status.value, checked.status.value, flush=True)


if __name__ == '__main__':
    publish()
