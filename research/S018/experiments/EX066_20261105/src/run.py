"""Authorized retrospective selection supplement; consume saved accounts only."""
# ruff: noqa: E402
from pathlib import Path
import os
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
TMP=ROOT/'.tmp/s018-selection'
TMP.mkdir(parents=True,exist_ok=True)
sys.pycache_prefix=str(TMP/'pycache')
os.environ['TMP']=os.environ['TEMP']=str(TMP)
import argparse
import json
from hashlib import sha256
from time import perf_counter
from statistics import median
from czsc_trader.application import (RepositoryContext,create_research_context,project_selection_window_facts,
    publish_evidence,assemble_delivery,validate_delivery,validate_experiment)
from czsc_trader import research_tools as d
from dataflows import ProviderConfig
from strategy_runtime.equity_definition import execution_spec_from_dict
from strategy_evaluator import SelectionRule,assess_selection_stability

WORK=Path(__file__).resolve().parents[1]
EXP=d.ExperimentRef('S018',WORK.name)
OUT=WORK/'others'

def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def encoded(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def save(p,v): p.write_bytes(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False).encode()+b'\n')
def protected():
    expected=read(WORK/'protocols/protected_originals.json')
    assert all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in expected.items())
    return expected
def setup():
    repo=RepositoryContext.discover(ROOT)
    source=read(WORK/'protocols/request.json')['sources'][0]['evaluation']
    header=read(ROOT/d.EvidenceRef.from_dict(source).repository_path)
    context=create_research_context(repo,d.ResearchBatchRef('S018'),providers=ProviderConfig(bindings={},equity_bindings={}),
        execution_spec=execution_spec_from_dict(header['request']['specification']))
    return repo,context
def material(context,name,value):
    return publish_evidence(context,d.MaterialEvidenceWrite(EXP,name,encoded(value),'application/json','json'))
def values(fact): return {v.metric.value:v.value for v in fact.diagnostics}

def compute():
    assert not (OUT/'computation_receipt.json').exists(),'Do not repeat a published computation.'
    protected()
    repo,context=setup()
    request=d.SelectionWindowFactsRequest.from_dict(read(WORK/'protocols/request.json'))
    rule=SelectionRule.from_dict(read(WORK/'protocols/rule.json'))
    started=perf_counter()
    print('PROJECT',len(request.sources),'sources',len(request.plan.windows),'unique windows',flush=True)
    projection=project_selection_window_facts(repo,request)
    projected=perf_counter()
    if projection.failures:
        ref=material(context,'selection-projection-failure',projection.to_dict())
        save(OUT/'projection_failure.json',{'reference':ref.to_dict(),'failures':[x.to_dict() for x in projection.failures]})
        raise RuntimeError('Declared source failure: no reduced-universe selection performed')
    analysis=projection.analysis_request(rule)
    result=assess_selection_stability(analysis)
    analyzed=perf_counter()
    evidence=d.SelectionStabilityEvidence(projection,analysis,result,request.plan.limitations)
    payload=encoded(evidence.to_dict())
    serialized=perf_counter()
    ref=publish_evidence(context,d.MaterialEvidenceWrite(EXP,'selection-stability',payload,'application/json','json'))
    published=perf_counter()
    facts={(f.source_id,f.window.window_id):f for f in projection.facts}
    center=next(s for s in projection.sources if s.candidate.candidate_id=='S018-C9380')
    rows=[]
    for pair,decision in zip(request.plan.pairs,result.decisions,strict=True):
        checks=next(c for c in decision.checks if c.candidate==center.candidate)
        obs=[o for o in result.observations if o.pair_id==pair.pair_id]
        center_observation=facts[center.source_id,pair.observation.window_id]
        center_benchmark=facts[center.benchmark_source_id,pair.observation.window_id]
        rows.append({'pair':pair.to_dict(),'status':decision.status.value,'eligible_count':len(decision.eligible),
            'selected':[c.candidate_id for c in decision.selected],
            'center_selection_check':checks.to_dict(),'center_selected':center.candidate in decision.selected,
            'center_selection':facts[center.source_id,pair.selection.window_id].to_dict(),
            'center_observation':center_observation.to_dict(),'benchmark_observation':center_benchmark.to_dict(),
            'observations':[o.to_dict() for o in obs]})
    groups={}
    for group in ('MAIN','LONG'):
        selected=[r for r in rows if r['pair']['pair_id'].startswith(group)]
        obs=[o for r in selected for o in r['observations']]
        primary=[o['primary_value'] for o in obs if o['primary_value'] is not None]
        excess=[o['excess_primary'] for o in obs if o['excess_primary'] is not None]
        groups[group]={'planned_windows':len(selected),'selected_windows':sum(bool(r['selected']) for r in selected),
            'no_eligible':sum(r['status']=='NO_ELIGIBLE_CANDIDATE' for r in selected),
            'insufficient':sum(r['status']=='INSUFFICIENT_SELECTION_EVIDENCE' for r in selected),
            'center_selected_windows':sum(r['center_selected'] for r in selected),
            'center_eligible_windows':sum(r['center_selection_check']['status']=='PASSED' for r in selected),
            'observations':len(obs),'passed':sum(o['acceptance_status']=='PASSED' for o in obs),
            'failed':sum(o['acceptance_status']=='FAILED' for o in obs),
            'unknown':sum(o['acceptance_status']=='INDETERMINATE' for o in obs),
            'primary_min':min(primary) if primary else None,'primary_median':median(primary) if primary else None,
            'primary_max':max(primary) if primary else None,'excess_min':min(excess) if excess else None,
            'excess_median':median(excess) if excess else None,
            'positive_excess':sum(x>0 for x in excess),'known_excess':len(excess)}
    save(OUT/'window_results.json',rows)
    save(OUT/'summary.json',{'status':result.status.value,'groups':groups,
        'candidate_selection_counts':[c.to_dict() for c in result.candidates if c.selected_windows],
        'limitations':result.limitations})
    save(OUT/'computation_receipt.json',{'evidence':ref.to_dict(),'projection_stats':projection.stats.to_dict(),
        'projection_wall_seconds':projected-started,'selection_seconds':analyzed-projected,
        'serialization_seconds':serialized-analyzed,'publication_seconds':published-serialized,
        'total_seconds':published-started,'new_strategy_replays':0,'new_candidates':0,
        'first_five_recalculations':0,'evidence_bytes':len(payload),'originals_unchanged':protected()})
    print(json.dumps({'status':result.status.value,'groups':groups,'seconds':published-started},ensure_ascii=False),flush=True)

def publish():
    assert not (OUT/'publication_receipt.json').exists(),'Inspect existing receipt before republishing.'
    protected()
    repo,context=setup()
    computation=read(OUT/'computation_receipt.json')
    evidence=d.EvidenceRef.from_dict(computation['evidence'])
    # Existing assessment payload is retained exactly, including all first-five results.
    previous_root=ROOT/'research/S018/assets/deliveries/ASSESSMENT/1'
    previous=read(previous_root/'delivery.json')
    old_content=d.DeliveryContent.from_dict(previous['content'])
    old_receipt=d.DeliveryReceipt.from_dict(read(ROOT/'research/S018/deliveries/ASSESSMENT/1/receipt.json'))
    old_definition=d.DeliveryDefinition.from_dict(previous['definition'])
    report=(WORK/'report.md').read_text(encoding='utf-8')
    refs=[evidence]
    for directory in ('src','protocols','others'):
        for path in sorted((WORK/directory).glob('*')):
            if not path.is_file() or path.suffix not in ('.py','.json','.md'):
                continue
            mime={'.py':'text/x-python','.json':'application/json','.md':'text/markdown'}[path.suffix]
            refs.append(publish_evidence(context,d.MaterialEvidenceWrite(EXP,directory+'-'+path.stem,
                path.read_bytes(),mime,path.suffix[1:])))
    stage_report=report.replace('(../../','(../../../')
    stage_report=stage_report.replace('(protocols/','(../../../experiments/'+EXP.experiment_id+'/protocols/')
    stage_report=stage_report.replace('(others/','(../../../experiments/'+EXP.experiment_id+'/others/')
    delivery=assemble_delivery(repo,d.DeliveryDefinition(d.ResearchBatchRef('S018'),d.DeliveryStage.ASSESSMENT,2,
        predecessors=tuple(dict.fromkeys((*old_definition.predecessors,old_receipt.reference))),schema_version=15),
        d.DeliveryContent(old_content.payload,d.DeliveryStatus.COMPLETE,old_content.facts,old_content.explanations,
            report=stage_report,evidence=tuple(dict.fromkeys((*old_content.evidence,*refs)))))
    assert delivery.validation.status is d.ValidationStatus.PASS
    checked=validate_delivery(repo,delivery.receipt.reference)
    assert checked.status is d.ValidationStatus.PASS
    assert checked.stats.accounts_authenticated==0 and checked.stats.recomputation_seconds==0
    new=read(ROOT/'research/S018/assets/deliveries/ASSESSMENT/2/delivery.json')
    assert new['content']['payload']==previous['content']['payload']
    save(OUT/'assessment_receipt.json',delivery.receipt.to_dict())
    save(OUT/'delivery_validation.json',checked.to_dict())
    save(OUT/'preservation_check.json',{'payload_equal':True,'first_five_recalculations':0,
        'originals':protected(),'old_payload_sha256':sha256(encoded(previous['content']['payload'])).hexdigest(),
        'new_payload_sha256':sha256(encoded(new['content']['payload'])).hexdigest()})
    for name in ('assessment_receipt','delivery_validation','preservation_check'):
        refs.append(material(context,name,read(OUT/(name+'.json'))))
    report_ref=publish_evidence(context,d.ExperimentReportWrite(EXP,sha256((WORK/'report.md').read_bytes()).hexdigest(),
        d.ExperimentOutcome.COMPLETED,tuple(refs)))
    artifacts=tuple(d.ExperimentArtifactRef(EXP,p.relative_to(WORK).as_posix(),sha256(p.read_bytes()).hexdigest())
        for folder in ('src','protocols','others') for p in sorted((WORK/folder).glob('*')) if p.is_file())
    valid=validate_experiment(repo,d.ExperimentValidationRequest(EXP,d.ExperimentValidationScope.REPORT_PUBLICATION,artifacts))
    assert valid.status.value=='PASS',valid.issues
    from dataclasses import asdict
    save(OUT/'publication_receipt.json',{'report':report_ref.to_dict(),'assessment':delivery.receipt.reference.to_dict(),
        'experiment_validation':asdict(valid),'delivery_validation':checked.to_dict(),
        'first_five_unchanged':True,'stage5_authorized':False})
    print('PUBLISHED',delivery.receipt.reference.content_sha256,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('compute','publish'))
    globals()[parser.parse_args().action]()
