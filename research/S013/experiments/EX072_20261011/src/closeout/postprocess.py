"""Source-only EX072 negative closeout CANDIDATES58->59, no registration/accounts."""
from pathlib import Path
from hashlib import sha256
import argparse,json,sys
from czsc_trader.application import publish_evidence,assemble_delivery,validate_delivery
from czsc_trader.research_tools import MaterialEvidenceWrite,delivery as api
from czsc_trader.research_tools.evidence import EvidenceRef
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from strategy_evaluator import AssessmentPanel
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-overnight-filter'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def digest(p):return sha256(Path(p).read_bytes()).hexdigest()
def refs_in(x):
    if isinstance(x,dict):
        if x.get('type')=='EvidenceRef':yield EvidenceRef.from_dict(x)
        else:
            for q in x.values():yield from refs_in(q)
    elif isinstance(x,(tuple,list)):
        for q in x:yield from refs_in(q)
def run(reviewref,sourcehash):
    if digest(__file__)!=sourcehash:raise ValueError('Root-reviewed closeout source drift')
    if reviewref.experiment.strategy_id!='S013' or reviewref.experiment.experiment_id!='EX072_20261011':raise ValueError('Root review must belong EX072')
    review=read(reviewref.resolve(ROOT))
    sys.path.insert(0,str(WORK));import driver as d
    exp,plan,path=d.stage();common=d.oldcommon();ctx=common.context(1)
    ref=EvidenceRef.from_dict(read(path/'protocols/centre_refutation_reference.json'));report=read(ref.resolve(ROOT))
    if review.get('status')!='ROOT_SCIENTIFIC_REVIEWED' or review.get('analysis_reference')!=ref.to_dict() or review.get('analysis_sha256')!=ref.sha256 or review.get('objective_achieved') is not False:
        raise ValueError('Exact actual refutation review required; overall robust goal not achieved')
    expected={'new_financial_accounts':1,'baseline_financial_reuse':1,'new_standard32':0,'new_fee':0,'new_neighbours':0,'new_technical_financial':0,'registration':0,'delivery_assembly':0}
    if report['status']!='COMPLETE_FIXED_CENTRE_REFUTATION' or report['counts']!=expected or report['stop_confirmed'] is not True:raise ValueError('Finite1+reuse1 stop required')
    if report['economics']['gates']!={'return':True,'annual_drawdown':True,'frequency':False,'negative_buyhold_year_profit':True} or report['economics']['qualified'] is not False:raise ValueError('Actual original-four-gate failure required')
    if report['raw_counts']!={'signal_days':1636,'pressure_dominant_all_days':434,'own_flat_bear_pressure_rejected':31,'signal_buy_entries':108,'actual_buy_fills':108,'actual_sell_fills':107,'raw_trade_rows':108,'closed_cycles':107,'open_cycles':1}:raise ValueError('Actual raw/closed/open roles differ')
    if report['orders_first_touch_audit']['status']!='PASS':raise ValueError('Actual order first-touch audit missing')
    complete=read(WORK/'execution_complete.json');cache=WORK/'centre.pkl.gz'
    if digest(cache)!=complete['cache_sha256']:raise ValueError('Native cache drift')
    pair=common.cache_read(cache)
    if serialize_evaluation_evidence(*pair)!=read(EvidenceRef.from_dict(complete['reference']).resolve(ROOT)):raise ValueError('Whole public native changed')
    if pair[0].strategy.candidate_id!='C9072' or pair[1].request_hash!=complete['request_hash'] or pair[1].result_hash!=complete['result_hash']:raise ValueError('Actual candidate/request/result role differs')
    oldproof=read(EvidenceRef.from_dict(report['independent_verification_reference']).resolve(ROOT))
    if oldproof['status']!='PASS' or oldproof['whole_formal_native_exact'] is not True or oldproof['economics']!=report['economics']:raise ValueError('Source/state/cash proof missing')
    if (ROOT/'research/registrations/S013/candidates/C9072.json').exists():raise ValueError('Failed candidate must not register')
    if (WORK/'parameters').exists():raise ValueError('Stopped candidate has unexpected future account directory')
    previous=api.DeliveryReference.from_dict(read(ROOT/'research/S013/assets/deliveries/CANDIDATES/58/receipt.json')['reference'])
    mandate=api.DeliveryReference.from_dict(read(ROOT/'research/S013/assets/deliveries/MANDATE/6/receipt.json')['reference'])
    if validate_delivery(ctx.repository,previous,scope=api.DeliveryValidationScope.INTEGRITY).status is not api.ValidationStatus.PASS:raise ValueError('Candidate58 integrity failed')
    prev=api.DeliveryContent.from_dict(read(ROOT/'research/S013/assets/deliveries/CANDIDATES/58/delivery.json')['content']).payload
    refs={}
    def add(x):
        if x.experiment.strategy_id!='S013':raise ValueError('Only S013 public evidence')
        x.resolve(ROOT);refs[x.repository_path]=x
    add(ref);add(reviewref)
    for q in (path/'protocols').glob('*.json'):
        for x in refs_in(read(q)):add(x)
    for x in refs_in(report):add(x)
    for item in prev.candidates:
        for ev in item.evaluations:add(EvidenceRef.from_dict(ev.evidence.to_dict()))
    # Explicitly historical context, not EX072 new financial roles or a new panel.
    oldfive=EvidenceRef.from_dict(read(ROOT/'research/S013/experiments/EX070_20261011/protocols/baseline_selfchecks_reference.json'))
    olddoc=read(oldfive.resolve(ROOT));AssessmentPanel.from_dict(olddoc['panel'])
    if olddoc['status']!='PASS' or olddoc['actual_new_accounts']!=0 or olddoc['baseline_reused_standard']!=33 or olddoc['baseline_reused_fee']!=1:raise ValueError('Declared historical B0 latest5 context invalid')
    add(oldfive)
    out=WORK/'formal-closeout'
    if out.exists():raise ValueError('Prior formal attempt cannot silently replay')
    out.mkdir()
    summary={'status':'PASS','new_candidates':0,'retained_candidate58_keys':[x.identity.key.to_dict() for x in prev.candidates],'retained_handoff':[x.to_dict() for x in prev.handoff],'counts':expected,'closed107_raw108_open1':True,'no_new_panel':True,'root_scientific_review':reviewref.to_dict(),'objective_achieved':False}
    d.write(out/'verification.json',summary)
    paths=[Path(__file__),*(path/'src').rglob('*.py'),*(path/'protocols').glob('*.json'),WORK/'centre_refutation.json',WORK/'centre_refutation.md',WORK/'verification.json',WORK/'preflight.json',WORK/'execution_complete.json',WORK/'orders_technical_failure.json',*(WORK.glob('*.csv')),out/'verification.json']
    for q in paths:add(publish_evidence(ctx,MaterialEvidenceWrite(exp,'overnight-filter-closeout-'+digest(q)[:32],q.read_bytes(),'application/json' if q.suffix=='.json' else 'text/plain',q.suffix[1:])))
    text=(WORK/'centre_refutation.md').read_text(encoding='utf-8')+'\n根科学评审：'+review['conclusion']+'\n\n'
    text+='|自然年|相同买入持有基准净收益|基准年度回撤|\n|---|---:|---:|\n'
    for y,a in report['economics']['benchmark_annual'].items():text+=f"|{y}|{a['return']:.4%}|{a['drawdown']:.4%}|\n"
    text+='\n原B0最新五自检仅引用EX070已验证的旧33标准+1双费用历史上下文；本EX072未运行32或双费用，没有完整新五自检，缺失不当通过或零。\n'
    text+='\n动态每次入场风险预算目前只有source-only需求和接口可行性反证，未证明能改善；本轮没有DEV实施或替代执行器。\n'
    for x in refs.values():text+=f'\n- [证据 {x.name}]({x.path})'
    search=api.SearchSummary(exp.experiment_id+'-fixed-overnight-pressure-entry-filter','固定lookback4原C8880熊市入场过滤；14有效参数完整域已声明，中心硬门失败即停后续','既有HFQ开发池、原1m/10bp每侧/LimitBuyHold1%；本轮新centre1、B0 centre复用1，基线最新5仅历史引用',2,2,review['conclusion'],('硬频率未过，不能优选或登记C9072','2023改善保留，整体收益下降/fullDD上升','实际自身31拒绝不等于旧15静态触发或31笔净减成交','已有开发池选择未校正，无封存或整体抗扰动证明'),tuple(refs.values()))
    payload=api.CandidateSet(prev.candidates,prev.handoff,(search,),review['conclusion'])
    receipt=assemble_delivery(ctx.repository,api.DeliveryDefinition(ctx.batch,api.DeliveryStage.CANDIDATES,59,(mandate,previous)),api.DeliveryContent(payload,api.DeliveryStatus.COMPLETE,(),(),report=text,evidence=tuple(refs.values())))
    d.write(out/'delivery_reference.json',receipt.reference.to_dict())
    validation=validate_delivery(ctx.repository,receipt.reference,scope=api.DeliveryValidationScope.FULL);d.write(out/'delivery_validation.json',validation.to_dict())
    if validation.status is not api.ValidationStatus.PASS:raise ValueError('FULL validation failed; preserve attempt, no implicit retry')
    return receipt.reference.to_dict()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--review-reference',type=Path,required=True);parser.add_argument('--source-sha256',required=True);args=parser.parse_args()
    print(json.dumps(run(EvidenceRef.from_dict(read(args.review_reference)),args.source_sha256),ensure_ascii=False))
