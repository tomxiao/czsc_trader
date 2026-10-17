"""Publish round evidence and update the authorized ten-round budget."""
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext,create_research_context,publish_evidence,update_research_intent,ResearchIntentUpdate
from czsc_trader.research_tools import ResearchBatchRef,ExperimentRef,MaterialEvidenceWrite
ROOT=Path(__file__).resolve().parents[5];EX=Path(__file__).resolve().parents[1]
def main():
    if (EX/'others/round_result.json').exists():raise RuntimeError('Preserve round')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'));audit=read(EX/'others/audit.json');assert audit['status']=='PASS'
    for item in audit['manifest']:assert sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256']
    repo=RepositoryContext.discover(ROOT);ctx=create_research_context(repo,ResearchBatchRef('S014'));exp=ExperimentRef('S014',EX.name);refs={}
    paths={ROOT/x['path'] for x in audit['manifest']}|{EX/'others/audit.json',EX/'protocols/report.md',Path(__file__)}
    for p in sorted(paths):
        name=p.relative_to(ROOT).as_posix().split(EX.name+'/',1)[1].replace('/','-').replace('.','-');mime={'.py':'text/x-python','.json':'application/json','.csv':'text/csv','.md':'text/markdown'}[p.suffix]
        refs[name]=publish_evidence(ctx,MaterialEvidenceWrite(exp,name,p.read_bytes(),mime,p.suffix[1:])).to_dict()
    result={'experiment':exp.to_dict(),'round':1,'status':'COMPLETED','evidence':refs,'new_supported_components':0,'source_calls':0,'stage_three_ready':False,'conclusion':'首次收盘四条件未改善固定H3，模型弱于原低环境较短持有对照；转向因果全周期环境校准与机会覆盖。'}
    (EX/'others/round_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    intent=read(ROOT/'research/registrations/S014/family.json')['research_intent'];budget=intent['autonomous_stage_two_budget'];assert exp.to_dict() in budget['allocated_rounds']
    budget['completed_rounds'].append({'experiment':exp.to_dict(),'result':'RESEARCH_COMPLETE_NO_NEW_SUPPORTED_COMPONENT','evidence':[refs['others-computation-json'],refs['others-audit-json'],refs['protocols-report-md']]})
    intent['pending']=['在10轮额度内继续现有数据阶段二；第2轮优先因果环境全期可计算性与机会规模。']
    update_research_intent(repo,ctx.batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',reason='第1轮研究完成并发布正反证，目标未完成，继续剩余额度')
    print('ROUND_SAVED',len(refs))
if __name__=='__main__':main()
