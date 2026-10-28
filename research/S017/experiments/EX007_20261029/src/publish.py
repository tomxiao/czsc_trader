"""Publish this bounded recovery experiment and a new immutable prototype panel."""
from dataclasses import replace
from hashlib import sha256
import importlib.util
import sys

from czsc_trader.application import assemble_delivery, publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentOutcome, ExperimentReportWrite, MaterialEvidenceWrite,
    ExperimentValidationRequest, ExperimentValidationScope)
from czsc_trader.research_tools import delivery as d
from strategy_runtime import ExecutionResources
from run import ROOT, WORK, EXPERIMENT, BATCH, REPOSITORY, context, read, save, material, candidate, configurations


def main():
    research = context()
    analysis, judgment = (read(WORK/'others'/name) for name in ('analysis.json','judgments.json'))
    precheck = read(WORK/'others/precheck.json')
    if analysis['status'] != 'PASS' or precheck['status'] != 'PASS':
        raise ValueError('complete analysis and precheck required')
    if analysis['source_sha256'] != sha256((WORK/'src/analyze.py').read_bytes()).hexdigest():
        raise ValueError('analysis source identity differs')
    if precheck['strategy_source_sha256'] != sha256((WORK/'src/strategy.py').read_bytes()).hexdigest():
        raise ValueError('strategy source identity differs')
    path = ROOT/'research/S017/experiments/EX005_20261028/src/publish.py'
    spec = importlib.util.spec_from_file_location('_s017_prior_publication', path)
    prior = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = prior
    spec.loader.exec_module(prior)
    # Only reuse retained_delivery: ROOT/BATCH/read resolve to this runner and
    # have identical meanings in both experiments. Never call prior.publish().
    predecessor, old_publication, old_content = prior.retained_delivery(4, 'EX005_20261028')
    old_entries = {entry.prototype_id: entry for entry in old_content.payload.prototypes}
    control_ids = ('C0000', 'C0013', 'C0029')
    controls = [replace(old_entries[key], sources=(d.PrototypeReference(predecessor,key),)) for key in control_ids]
    required = {use.component_id for entry in controls for use in entry.components}
    components = [item for item in old_content.payload.components if item.component_id in required]
    if {item.component_id for item in components} != required:
        raise ValueError('retained controls have missing components')
    references = [EvidenceRef.from_dict(value) for value in old_publication['evidence']]
    references.extend(old_content.evidence)
    references.append(EvidenceRef.from_dict(old_publication['report']))
    pre = {name: EvidenceRef.from_dict(value) for name,value in read(WORK/'others/pre_run_evidence.json').items()}
    references.extend(pre.values())
    evidence = {}
    for name, relative in (
        ('analysis','others/analysis.json'), ('analysis-source','src/analyze.py'),
        ('precheck','others/precheck.json'), ('precheck-source','src/precheck.py'),
        ('judgments','others/judgments.json'), ('execution-status','others/execution_status.json'),
        ('execution-stats','others/execution_stats.json'), ('publication-source','src/publish.py'),
        ('review','notes.md'), ('plot-source','src/plot.py'),
    ):
        evidence[name] = material(research, name, WORK/relative)
        references.append(evidence[name])
    references.append(publish_evidence(research,MaterialEvidenceWrite(EXPERIMENT,'equity-drawdown',
        (WORK/'others/equity_drawdown.png').read_bytes(),'image/png','png')))
    accounts = read(WORK/'others/accounts.json')
    account_refs = {key: EvidenceRef.from_dict(value) for key,value in analysis['source_accounts'].items()}
    for entry in controls:
        if len(entry.evaluations) != 1 or entry.evaluations[0].evidence != account_refs[entry.prototype_id]:
            raise ValueError('retained prototype and analysis use different historical accounts')
    references.extend(account_refs.values())
    references.extend(EvidenceRef.from_dict(value['evidence']) for value in analysis['diagnostics'].values())
    cand = candidate('C0030',configurations()['C0030'])
    definition_path = WORK/'protocols/definition-C0030.json'
    save(definition_path,cand.definition.to_dict())
    definition = material(research,'definition-C0030',definition_path)
    references.append(definition)
    component_id = 'reentry-after-confirmed-close'
    components.append(d.ComponentEntry(component_id, d.ExperimentDefinitionRef(pre['source'],'strategy:decide'),
        '恢复入场', '真实平仓后收盘严格高于首次触发止损线',
        '已完成30分钟Close到下一可执行区间；冻结线只用实际退出决策前历史',
        'C0029固定首次入场及完整持仓退出管理', '价格及确认成交事实；不使用基本面事件', 'RAW',
        '原0.1%单边费用、1%限价溢价、数量与可交易规则', judgment['component_judgment'],
        (d.ComponentTestResult(component_id+'-comparison',EXPERIMENT.experiment_id,pre['design'],
            d.ComponentTestStatus(judgment['component_status']),judgment['component_judgment'],
            (evidence['analysis'],account_refs['C0030'],account_refs['C0029'])),)))
    entry = d.PrototypeEntry('C0030',d.CandidateIdentityRef(cand.key,cand.content_identity.content_sha256),
        d.ExperimentDefinitionRef(definition,'strategy:decide'),
        '经营改善可能支撑长趋势；止损后的价格恢复可能减少错过延续上涨，基本面仅启发假设。',
        tuple(old_entries['C0029'].components)+(d.PrototypeComponentUse(component_id,'恢复入场','原突破之外增加真实闭合后的恢复入口'),),
        (d.EvaluationEvidenceRef(account_refs['C0030'],(accounts['C0030']['evaluation_id'],)),),
        d.PrototypeDisposition(judgment['disposition']), judgment['prototype_judgment'],
        tuple(judgment['limitations']),judgment['next_step'],
        (definition,pre['source'],pre['design'],pre['authorization'],evidence['analysis'],evidence['judgments']))
    comparison = d.PrototypeComparison('reentry-C0030-vs-C0029','C0030','C0029',
        '仅增加真实闭合后的恢复入口，完整账户收益、回撤及频率如何改变？',pre['design'],
        (evidence['analysis'],account_refs['C0030'],account_refs['C0029']),judgment['comparison'])
    panel = d.PrototypePanel(tuple(controls)+(entry,),tuple(components),(comparison,),judgment['conclusion'])
    references = tuple(dict.fromkeys(references))
    report = (WORK/'report.md').read_bytes()
    report_ref = publish_evidence(research,ExperimentReportWrite(EXPERIMENT,sha256(report).hexdigest(),
        ExperimentOutcome.COMPLETED,references))
    output = assemble_delivery(REPOSITORY,d.DeliveryDefinition(BATCH,d.DeliveryStage.PROTOTYPES,5,(predecessor,)),
        d.DeliveryContent(panel,d.DeliveryStatus.COMPLETE,(),(),report=report.decode(),evidence=references+(report_ref,)),
        resources=ExecutionResources(max_workers=4,native_threads_per_worker=1,random_seed=17),
        on_progress=lambda event: print(event,flush=True))
    validation = validate_experiment(REPOSITORY,ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json',{'delivery':output.receipt.to_dict(),'validation':output.validation.to_dict(),
        'experiment_validation':validation.to_dict(),'report':report_ref.to_dict(),
        'evidence':[reference.to_dict() for reference in references],'predecessor':predecessor.to_dict()})
    if output.validation.status.value != 'PASS' or validation.status.value != 'PASS':
        raise RuntimeError('prototype panel/report validation failed')
    print('PROTOTYPES/5 AND REPORT_PUBLICATION PASS',flush=True)


if __name__ == '__main__':
    main()
