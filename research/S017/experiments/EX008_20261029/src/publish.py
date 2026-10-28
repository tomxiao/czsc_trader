"""Publish EX008 and PROTOTYPES/6 with exact retained account references."""
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
import sys

from czsc_trader.application import assemble_delivery, publish_evidence, validate_experiment
from czsc_trader.research_tools import (EvidenceRef, ExperimentOutcome, ExperimentReportWrite,
    MaterialEvidenceWrite, ExperimentValidationRequest, ExperimentValidationScope)
from czsc_trader.research_tools import delivery as d
from strategy_runtime import ExecutionResources
from run import ROOT, WORK, EXPERIMENT, BATCH, REPOSITORY, context, read, save, material, candidate, configurations


NEW_KEYS = ('C0031', 'C0032')
CONTROL_ORIGINS = {'C0000': 'EX002_20261028', 'C0013': 'EX003_20261028',
                   'C0029': 'EX005_20261028', 'C0030': 'EX007_20261029'}
COMPONENT_PAIRS = {'recovery-mean-position': ('C0031', 'C0030'),
                   'recovery-mean-direction': ('C0032', 'C0031')}
COMPARISONS = (('C0031', 'C0030'), ('C0032', 'C0031'), ('C0031', 'C0029'), ('C0032', 'C0029'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError('cannot load exact historical publication helper')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def retained_predecessor():
    # EX005's helper imports absolute `run`. Bind its own runner temporarily,
    # restore EX008's binding, and call only the read-only retained helper.
    source = ROOT/'research/S017/experiments/EX005_20261028/src'
    runner = load('_s017_ex008_retained_runner', source/'run.py')
    sentinel = object()
    previous = sys.modules.get('run', sentinel)
    try:
        sys.modules['run'] = runner
        prior = load('_s017_ex008_retained_publication', source/'publish.py')
    finally:
        if previous is sentinel:
            del sys.modules['run']
        else:
            sys.modules['run'] = previous
    return prior.retained_delivery(5, 'EX007_20261029')


def main():
    analysis = read(WORK/'others/analysis.json')
    judgment = read(WORK/'others/judgments.json')
    precheck = read(WORK/'others/precheck.json')
    accounts = read(WORK/'others/accounts.json')
    definitions = read(WORK/'protocols/definitions.json')
    configs = configurations()
    if any(set(value) != set(NEW_KEYS) for value in (accounts, definitions, configs, judgment['prototypes'])):
        raise ValueError('accounts, definitions and judgments must cover exactly C0031 and C0032')
    if analysis['status'] != 'PASS' or precheck['status'] != 'PASS':
        raise ValueError('complete analysis and focused precheck required')
    if analysis['source_sha256'] != sha256((WORK/'src/analyze.py').read_bytes()).hexdigest():
        raise ValueError('analysis source identity differs')
    if precheck['strategy_source_sha256'] != sha256((WORK/'src/strategy.py').read_bytes()).hexdigest():
        raise ValueError('strategy source identity differs')
    expected_accounts = set(CONTROL_ORIGINS) | set(NEW_KEYS)
    if set(analysis['source_accounts']) != expected_accounts or set(analysis['summaries']) != expected_accounts:
        raise ValueError('analysis must identify exactly the six compared accounts')
    expected_diagnoses = {subject+'_vs_'+control for subject, control in COMPARISONS}
    if (set(analysis['diagnostics']) != expected_diagnoses
            or any(value['status'] != 'COMPUTED' for value in analysis['diagnostics'].values())):
        raise ValueError('four complete public diagnoses are required')
    component_judgments = {value['component_id']: value for value in judgment['components']}
    if len(judgment['components']) != 2 or set(component_judgments) != set(COMPONENT_PAIRS):
        raise ValueError('component judgments must cover exactly the position and direction tests')
    for key, pair in COMPONENT_PAIRS.items():
        value = component_judgments[key]
        if (value['subject'], value['control']) != pair:
            raise ValueError('component judgment has the wrong fixed contrast')
    comparisons = {(value['subject'], value['control']): value for value in judgment['comparisons']}
    if len(judgment['comparisons']) != 4 or set(comparisons) != set(COMPARISONS):
        raise ValueError('comparison judgments must cover the four fixed contrasts')

    predecessor, old_publication, old_content = retained_predecessor()
    old_entries = {entry.prototype_id: entry for entry in old_content.payload.prototypes}
    controls = [replace(old_entries[key], sources=(d.PrototypeReference(predecessor, key),))
                for key in CONTROL_ORIGINS]
    account_refs = {key: EvidenceRef.from_dict(value) for key, value in analysis['source_accounts'].items()}
    for entry in controls:
        reference = account_refs[entry.prototype_id]
        if (len(entry.evaluations) != 1 or entry.evaluations[0].evidence != reference
                or reference.experiment.experiment_id != CONTROL_ORIGINS[entry.prototype_id]):
            raise ValueError('retained prototype and analysis differ in their original account')
    candidates = {key: candidate(key, configs[key]) for key in NEW_KEYS}
    for key, cand in candidates.items():
        reference = account_refs[key]
        if (reference != EvidenceRef.from_dict(accounts[key]['evidence']) or reference.experiment != EXPERIMENT
                or (reference.schema, reference.schema_version) != ('equity_research', 2)):
            raise ValueError('new account evidence must belong to EX008 and match analysis')
        identity = accounts[key]['evaluation_identity']
        if (identity['candidate'] != {'strategy_id': BATCH.strategy_id, 'candidate_id': key}
                or identity['content_sha256'] != cand.content_identity.content_sha256
                or definitions[key] != json.loads(json.dumps(cand.definition.to_dict()))):
            raise ValueError('new candidate definition differs from evaluated identity')
    pre = {name: EvidenceRef.from_dict(value)
           for name, value in read(WORK/'others/pre_run_evidence.json').items()}
    expected_material = {'design': 'protocols/design.md', 'source': 'src/strategy.py',
        'definitions': 'protocols/definitions.json', 'runner': 'src/run.py',
        'authorization': 'protocols/authorization.md'}
    if not set(expected_material) <= pre.keys() or any(ref.experiment != EXPERIMENT for ref in pre.values()):
        raise ValueError('required EX008 pre-run evidence is missing or belongs to another experiment')
    for name, relative in expected_material.items():
        if pre[name].sha256 != sha256((WORK/relative).read_bytes()).hexdigest():
            raise ValueError('pre-run material changed after evaluation: '+name)
    required = {use.component_id for entry in controls for use in entry.components}
    components = [item for item in old_content.payload.components if item.component_id in required]
    if {item.component_id for item in components} != required or required & set(COMPONENT_PAIRS):
        raise ValueError('retained components are missing or collide with new component identities')

    research = context()
    references = [EvidenceRef.from_dict(value) for value in old_publication['evidence']]
    references.extend(old_content.evidence)
    references.append(EvidenceRef.from_dict(old_publication['report']))
    references.extend(pre.values())
    references.extend(account_refs.values())
    for value in analysis['diagnostics'].values():
        reference = EvidenceRef.from_dict(value['evidence'])
        if reference.experiment != EXPERIMENT:
            raise ValueError('new diagnosis evidence must belong to EX008')
        references.append(reference)
    evidence = {}
    for name, relative in (
        ('analysis', 'others/analysis.json'), ('analysis-source', 'src/analyze.py'),
        ('precheck', 'others/precheck.json'), ('precheck-source', 'src/precheck.py'),
        ('judgments', 'others/judgments.json'), ('execution-status', 'others/execution_status.json'),
        ('execution-stats', 'others/execution_stats.json'), ('publication-source', 'src/publish.py'),
        ('review', 'notes.md'), ('plot-source', 'src/plot.py'),
    ):
        evidence[name] = material(research, name, WORK/relative)
        references.append(evidence[name])
    references.append(publish_evidence(research, MaterialEvidenceWrite(EXPERIMENT, 'equity-drawdown',
        (WORK/'others/equity_drawdown.png').read_bytes(), 'image/png', 'png')))
    for key, (subject, control) in COMPONENT_PAIRS.items():
        value = component_judgments[key]
        components.append(d.ComponentEntry(key, d.ExperimentDefinitionRef(pre['source'], 'strategy:decide'),
            value['role'], value['label'],
            '已完成30分钟Close到下一可执行区间；均值排除当前Close，滞后65根采用同口径',
            control+'固定其他入口、持仓及退出管理', '价格及确认成交事实；不使用基本面事件', 'RAW',
            '原0.1%单边费用、1%限价溢价、数量与可交易规则', value['judgment'],
            (d.ComponentTestResult(key+'-comparison', EXPERIMENT.experiment_id, pre['design'],
                d.ComponentTestStatus(value['status']), value['judgment'],
                (evidence['analysis'], account_refs[subject], account_refs[control])),)))
    entries = list(controls)
    for key, cand in candidates.items():
        path = WORK/'protocols'/('definition-'+key+'.json')
        save(path, definitions[key])
        definition = material(research, 'definition-'+key, path)
        references.append(definition)
        value = judgment['prototypes'][key]
        uses = tuple(old_entries['C0030'].components)+(d.PrototypeComponentUse(
            'recovery-mean-position', '恢复入口位置条件', '恢复条件另需Close严格高于此前260根均值'),)
        if key == 'C0032':
            uses += (d.PrototypeComponentUse('recovery-mean-direction', '恢复入口方向条件',
                '在位置条件外另需均值严格高于65根前同口径均值'),)
        entries.append(d.PrototypeEntry(key, d.CandidateIdentityRef(cand.key, cand.content_identity.content_sha256),
            d.ExperimentDefinitionRef(definition, 'strategy:decide'), value['hypothesis'], uses,
            (d.EvaluationEvidenceRef(account_refs[key], (accounts[key]['evaluation_id'],)),),
            d.PrototypeDisposition(value['disposition']), value['judgment'], tuple(value['limitations']),
            value['next_step'], (definition, pre['source'], pre['design'], pre['authorization'],
                                 evidence['analysis'], evidence['judgments'])))
    questions = {('C0031', 'C0030'): '恢复入口增加均价位置条件后，完整账户收益、回撤及频率如何改变？',
        ('C0032', 'C0031'): '在位置条件外增加均价方向条件，是否提供完整账户增量？',
        ('C0031', 'C0029'): '相对无恢复入口的C0029，带位置条件的恢复是否有完整账户价值？',
        ('C0032', 'C0029'): '相对无恢复入口的C0029，带位置及方向条件的恢复是否有完整账户价值？'}
    contrasts = tuple(d.PrototypeComparison('background-'+subject+'-vs-'+control, subject, control,
        questions[(subject, control)], pre['design'],
        (evidence['analysis'], account_refs[subject], account_refs[control]),
        comparisons[(subject, control)]['conclusion']) for subject, control in COMPARISONS)
    panel = d.PrototypePanel(tuple(entries), tuple(components), contrasts, judgment['conclusion'])
    references = tuple(dict.fromkeys(references))
    if any(ref.experiment.strategy_id != BATCH.strategy_id for ref in references):
        raise ValueError('delivery evidence must stay within S017')
    report = (WORK/'report.md').read_bytes()
    report_ref = publish_evidence(research, ExperimentReportWrite(EXPERIMENT, sha256(report).hexdigest(),
        ExperimentOutcome.COMPLETED, references))
    output = assemble_delivery(REPOSITORY, d.DeliveryDefinition(BATCH, d.DeliveryStage.PROTOTYPES, 6, (predecessor,)),
        d.DeliveryContent(panel, d.DeliveryStatus.COMPLETE, (), (), report=report.decode(), evidence=references+(report_ref,)),
        resources=ExecutionResources(max_workers=4, native_threads_per_worker=1, random_seed=17),
        on_progress=lambda event: print(event, flush=True))
    validation = validate_experiment(REPOSITORY, ExperimentValidationRequest(EXPERIMENT,
        ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json', {'delivery': output.receipt.to_dict(), 'validation': output.validation.to_dict(),
        'experiment_validation': validation.to_dict(), 'report': report_ref.to_dict(),
        'evidence': [ref.to_dict() for ref in references], 'predecessor': predecessor.to_dict()})
    if output.validation.status.value != 'PASS' or validation.status.value != 'PASS':
        raise RuntimeError('prototype reference graph or report publication validation failed')
    print('PROTOTYPES/6 AND REPORT_PUBLICATION PASS', flush=True)


if __name__ == '__main__':
    main()
