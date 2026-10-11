"""Source-only EX070 CandidateSet57->58; root scientific review required.

No execution/prepare API. Not invoked by financial runner or analysis helpers.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import sys
from hashlib import sha256
from czsc_trader.application import CandidateRegistrationRequest,register_candidate,load_candidate,assemble_delivery,validate_delivery,publish_evidence
from czsc_trader.research_tools import delivery as delivery,MaterialEvidenceWrite
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from strategy_manager import CandidateDerivationKind,CandidateKey
from strategy_evaluator import AssessmentPanel

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-short-alt'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def module():
    sys.path.insert(0,str(WORK))
    import driver,perturbation_driver
    return driver,perturbation_driver
def refs_in(value):
    if isinstance(value,dict):
        if value.get('type')=='EvidenceRef':yield EvidenceRef.from_dict(value)
        else:
            for x in value.values():yield from refs_in(x)
    elif isinstance(value,(list,tuple)):
        for x in value:yield from refs_in(x)
def run(review,expected_sha):
    if digest(__file__)!=expected_sha:raise ValueError('Root-reviewed closeout source changed')
    if review.get('status')!='ROOT_SCIENTIFIC_REVIEWED' or review.get('objective_achieved') is not False:
        raise ValueError('Explicit root scientific review with unresolved overall goal required')
    d,p=module();ctx,exp,path,common,state,method,requests,fee,audit=p.stage()
    if state['status']!='FINANCIAL34_COMPLETE':raise ValueError('Complete canonical34 required')
    local=read(WORK/'neighbours_state.json')
    if local['status']!='FINANCIAL36_COMPLETE':raise ValueError('Both separately declared local3/5 required')
    analysis_ref=EvidenceRef.from_dict(read(path/'protocols/analysis_reference.json'))
    if review.get('analysis_reference')!=analysis_ref.to_dict() or review.get('analysis_sha256')!=analysis_ref.sha256:
        raise ValueError('Root scientific review must reference exact actual public analysis bytes')
    analysis=read(analysis_ref.resolve(ROOT))
    if analysis['status']!='COMPLETE' or analysis['counts']!={'new_centre':1,'new_standard32':32,'new_fee':1,'new_integer_neighbours':2,'new_financial_total':36,'new_technical_financial':0,'baseline_reuse_standard':33,'baseline_reuse_fee':1,'all_native_accounts_including_reuse':70}:
        raise ValueError('Complete finite financial-role budget required')
    if analysis['comparison']['paired_geometry'] is not False or method['lookback_actual_counts']!={'4':32}:
        raise ValueError('14D unpaired comparison and integer coverage disclosure required')
    if set(state['accounts'])!={*(f'P{i:02}' for i in range(32)),'FEE'} or set(local['accounts'])!={'L3','L5'}:
        raise ValueError('Exact32/FEE and separate3/5 actual role sets required')
    for item in analysis['fivechecks'].values():AssessmentPanel.from_dict(item['panel'])
    if set(analysis['fivechecks'])!={'B0','N_SHORT_ALT'}:raise ValueError('Both complete latest fivecheck panels required')
    baseline_ref=EvidenceRef.from_dict(read(path/'protocols/baseline_selfchecks_reference.json'))
    baseline=read(baseline_ref.resolve(ROOT))
    if (baseline['status']!='PASS' or baseline['actual_new_accounts']!=0 or baseline['baseline_reused_standard']!=33 or baseline['baseline_reused_fee']!=1 or len(baseline['audits'])!=33):
        raise ValueError('Actual read-only original34 audit completeness required')
    AssessmentPanel.from_dict(baseline['panel'])
    if baseline['panel']!=analysis['fivechecks']['B0']['panel'] or baseline['economics']!=analysis['fivechecks']['B0']['economics']:
        raise ValueError('Actual baseline latest fivechecks differ from analysis')
    for item in [*baseline['audits'],baseline['fee_audit']]:
        if item['status']!='PASS' or item['whole_formal_native_exact'] is not True:raise ValueError('Baseline whole native audit failed')
    if [item['native_reference'] for item in baseline['audits']]!=[item['reference'] for item in [method['baseline_reuse']['center'],*method['baseline_reuse']['points']]] or baseline['fee_audit']['native_reference']!=method['baseline_fee_reuse']['reference']:
        raise ValueError('Actual baseline original33+fee public reference roles differ')
    refs={}
    def add(ref):
        if ref.experiment.strategy_id!='S013':raise ValueError('Only S013 evidence')
        ref.resolve(ROOT);refs[ref.repository_path]=ref
    for q in (path/'protocols').glob('*.json'):
        for ref in refs_in(read(q)):add(ref)
    for ref in refs_in(analysis):add(ref)
    for ref in refs_in(baseline):add(ref)
    add(baseline_ref)
    for label,item in state['accounts'].items():
        if item['status']!='AUDITED':raise ValueError('Unaudited '+label)
        if digest(ROOT/item['cache'])!=item['cache_sha256']:raise ValueError('Native cache changed')
        pair=common.cache_read(ROOT/item['cache'])
        if serialize_evaluation_evidence(*pair)!=read(EvidenceRef.from_dict(item['reference']).resolve(ROOT)):raise ValueError('Whole native changed')
        proof=read(EvidenceRef.from_dict(item['audit_reference']).resolve(ROOT))
        if proof['status']!='PASS' or proof['whole_formal_native_exact'] is not True:raise ValueError('Whole native audit failed')
    for label,item in local['accounts'].items():
        if item['status']!='AUDITED' or digest(ROOT/item['cache'])!=item['cache_sha256']:raise ValueError('Neighbour cache/audit failed')
        neighbour=common.cache_read(ROOT/item['cache'])
        if neighbour[0].strategy.payload['parameters']['short_confirmation_lookback4']!=int(label[1:]):raise ValueError('Neighbour role/actual lookback differs')
        if serialize_evaluation_evidence(*neighbour)!=read(EvidenceRef.from_dict(item['reference']).resolve(ROOT)):raise ValueError('Neighbour native changed')
        proof=read(EvidenceRef.from_dict(item['audit_reference']).resolve(ROOT))
        if proof['status']!='PASS' or proof['whole_formal_native_exact'] is not True:raise ValueError('Neighbour whole native audit failed')
    centre=common.cache_read(WORK/'centre.pkl.gz');centre_ref=EvidenceRef.from_dict(read(path/'protocols/centre_reference.json'))
    if serialize_evaluation_evidence(*centre)!=read(centre_ref.resolve(ROOT)):raise ValueError('Centre native changed')
    if not analysis['rows']['N_SHORT_ALT']['center']['qualified']:raise ValueError('Only original4-qualified centre registers')
    derivation=centre[0].lineage.derivation
    if derivation.kind is not CandidateDerivationKind.IMPLEMENTATION or derivation.parent!=CandidateKey('S013','C8880'):raise ValueError('Implementation parent must C8880')
    previous=delivery.DeliveryReference.from_dict(read(ROOT/'research/S013/assets/deliveries/CANDIDATES/57/receipt.json')['reference'])
    mandate=delivery.DeliveryReference.from_dict(read(ROOT/'research/S013/assets/deliveries/MANDATE/6/receipt.json')['reference'])
    if validate_delivery(ctx.repository,previous,scope=delivery.DeliveryValidationScope.INTEGRITY).status is not delivery.ValidationStatus.PASS:raise ValueError('CandidateSet57 failed integrity')
    previousdoc=read(ROOT/'research/S013/assets/deliveries/CANDIDATES/57/delivery.json')
    content=delivery.DeliveryContent.from_dict(previousdoc['content']);retained=content.payload.candidates
    for entry in retained:
        for evaluation in entry.evaluations:add(EvidenceRef.from_dict(evaluation.evidence.to_dict()))
    out=WORK/'formal-closeout'
    if out.exists():raise ValueError('Existing attempt cannot silently rerun')
    out.mkdir()
    registration=register_candidate(ctx.repository,CandidateRegistrationRequest(centre[0].strategy,exp,(centre_ref,),centre[0].dependencies,derivation))
    if ctx.runtime.identify(load_candidate(ctx.repository,registration.key),dependencies=centre[0].dependencies).content_sha256!=analysis['rows']['N_SHORT_ALT']['center']['candidate']['content_sha256']:raise ValueError('Registered content mismatch')
    d.write(out/'registration.json',registration.to_dict())
    d.write(out/'review.json',review)
    manifest={'status':'PASS','counts':analysis['counts'],'qualified_registered':['C9070'],'baseline_not_reregistered':True,'standard_points_not_registered':True,'local_neighbours_not_registered':True,'prepare':0,'evaluate':0,'objective_achieved':False,'technical_revision_chain_preserved':True,'lookback_standard_counts':{'4':32},'integer_neighbour_scope':'local sensitivity only','attribution_scope':'actual alternative-entry origin group; not causal net added trades'}
    d.write(out/'verification.json',manifest)
    for q in [Path(__file__),*(path/'protocols').glob('*.json'),*(path/'src').glob('*.py'),*(WORK/'parameters').glob('*-audit.json'),WORK/'analysis.json',WORK/'perturbation_state.json',WORK/'neighbours_state.json',*(out.glob('*.json'))]:
        add(publish_evidence(ctx,MaterialEvidenceWrite(exp,'short-alt-closeout-'+digest(q)[:32],q.read_bytes(),'application/json' if q.suffix=='.json' else 'text/plain',q.suffix[1:])))
    entry=delivery.CandidateEntry(delivery.CandidateIdentityRef(CandidateKey('S013','C9070'),derivation.child_content_sha256),'原C8880加此前4日未上涨的替代确认路径','中心原四门合格；32和五自检为诊断；未宣告稳健研究目标达成',(delivery.EvaluationEvidenceRef(centre_ref),))
    summary=delivery.SearchSummary(exp.experiment_id+'-fixed-short-alt','固定14有效参数/.05/32/seed13/HALF_EVEN；另固定3/5两账户局部敏感性','共同开发池/原现金费用/HFQ/1%合同；B0旧13维只作描述比较',70,68,'根科学评审：'+review['selection_summary'],('反复开发池选择未校正；PBO/DSR不可用不能零值；整数标准32未覆盖3/5；没有封存验证；实际替代入场组不是隔离因果',),tuple(refs.values()))
    payload=delivery.CandidateSet((*retained,entry),(),(summary,),review['selection_summary'])
    report=review['report_markdown']
    receipt=assemble_delivery(ctx.repository,delivery.DeliveryDefinition(ctx.batch,delivery.DeliveryStage.CANDIDATES,58,(mandate,previous)),delivery.DeliveryContent(payload,delivery.DeliveryStatus.COMPLETE,(),(),report=report,evidence=tuple(refs.values())))
    d.write(out/'delivery_reference.json',receipt.reference.to_dict())
    check=validate_delivery(ctx.repository,receipt.reference,scope=delivery.DeliveryValidationScope.FULL);d.write(out/'delivery_validation.json',check.to_dict())
    if check.status is not delivery.ValidationStatus.PASS:raise ValueError('FULL validation failed, preserve attempted delivery')
    return receipt.reference.to_dict()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--review',type=Path,required=True);parser.add_argument('--source-sha256',required=True);args=parser.parse_args()
    print(json.dumps(run(read(args.review),args.source_sha256),ensure_ascii=False))
