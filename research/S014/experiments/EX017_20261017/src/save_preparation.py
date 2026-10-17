"""Publish concrete stage-three preparation and its unresolved input authorization."""
from pathlib import Path
from hashlib import sha256
import json
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]

def main():
    target=EX/'others/preparation_result.json'
    if target.exists():raise RuntimeError('Preserve preparation evidence')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'));pre=read(EX/'others/precheck.json')
    assert pre['status']=='PASS' and pre['source_sha256']==sha256((EX/'src/strategy_runtime/strategies/repair.py').read_bytes()).hexdigest()
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'));exp=ExperimentRef('S014',EX.name);refs={}
    for p in sorted([*EX.glob('src/**/*.py'),*EX.glob('src/**/*.csv'),*EX.glob('protocols/*.json'),*EX.glob('others/*.json')]):
        name=p.relative_to(EX).as_posix().replace('/','-').replace('.','-');mime={'.py':'text/x-python','.csv':'text/csv','.json':'application/json'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:])).to_dict()
    result={'status':'PREPARATION_COMPLETE_AWAITING_PREWINDOW_AUTHORIZATION','experiment':exp.to_dict(),'evidence':refs,'loaded_variants':4,'causal_checks':pre['check_count'],'actual_account_runs':0,'actual_source_calls':0,'phase_three_complete':False,
        'blocker':'原固定LimitBuyHold首日需前一可交易日参考；现有S014公开绑定从2020-01-02起，无2019预窗口输入。',
        'proposed_extension':{'calendar_and_stock_status':['2019-12-01','2019-12-31'],'stock_hfq_and_raw':'经日历/状态确认的前一可交易日','proposed_call_cap':15,'authorization':'PENDING_USER_REPLY','evaluation_window_unchanged':['2020-01-01','2026-10-15']},
        'next':'批准后用公共数据接口补齐并绑定输入，按四方案回放、逐日成交状态审核及逐年目标比较；不改基准首日，不补造现金行。'}
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent']
    intent['stage_three_preparation']={'experiment':exp.to_dict(),'status':result['status'],'implementation':refs['src-strategy_runtime-strategies-repair-py'],'precheck':refs['others-precheck-json'],'loaded_variants':4,'checks':pre['check_count'],'actual_account_runs':0,'proposed_extension':result['proposed_extension']}
    intent['pending']=['待用户确认最小2019预窗口及最多15次补数额度；已批准阶段三四方案，无需重复批准阶段推进。']
    update_research_intent(RepositoryContext.discover(ROOT),ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='完成四方案实现和37项因果检查，保留固定基准首日，等待新增预窗口输入授权')
    print('PREPARATION_SAVED',len(refs))

if __name__=='__main__':main()
