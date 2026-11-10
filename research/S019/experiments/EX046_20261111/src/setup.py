"""Open a subsequent round within the approved six-round mechanism allocation."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig

ROOT=Path.cwd()
def read(path):
    return json.loads(path.read_bytes())
def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('recipe',type=Path)
    args=parser.parse_args()
    recipe=read(args.recipe)
    work=ROOT/'research/S019/experiments'/recipe['experiment_id']
    assert not work.exists()
    intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
    total=recipe['specs']['round_budget']['total_round']
    assert intent['stage']=='STAGE_TWO' and total==4+recipe['specs']['round_budget']['round_index']
    assert intent['joint_search_budget']['used_rounds']==total-1 and total<=10
    previous=ROOT/recipe['previous_experiment']
    assert read(previous/'others/publication.json')['validation']['status']=='PASS'
    assert read(previous/'others/budget_settlement.json')['status']=='SETTLED_ONCE'
    sources={name:ROOT/path for name,path in recipe['source_paths'].items()}
    assert all(path.is_file() and path.resolve().is_relative_to(ROOT) for path in sources.values())
    repo=RepositoryContext.discover(ROOT)
    batch=d.ResearchBatchRef('S019')
    ctx=create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    exp=create_experiment(ctx,ExperimentRequest(recipe['title'],recipe['question'],date.fromisoformat(recipe['date'])))
    assert exp.resolve(ROOT)==work
    (work/'src/setup.py').write_bytes(Path(__file__).read_bytes())
    for name,path in sources.items():
        (work/'src'/name).write_bytes(path.read_bytes())
    save(work/'protocols/specs.json',recipe['specs'])
    (work/'protocols/plan.md').write_bytes(recipe['plan'].encode())
    save(work/'protocols/continuation.json',{'authorization_decision':'S019-RESUME-MECHANISMS-20261110',
        'previous_experiment':recipe['previous_experiment'],
        'previous_report':read(previous/'others/publication.json')['report'],
        'source_origins':{name:{'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path.read_bytes()).hexdigest()} for name,path in sources.items()},
        'research_question':recipe['question'],'budget':recipe['specs']['round_budget']})
    (work/'report.md').write_bytes(('# '+recipe['title']+'\n\nStatus: IN_PROGRESS\n').encode())
    intent.update(active_experiment=exp.to_dict(),mechanism_research_status='ROUND_PREPARING',
        active_round_budget={'round':total,'allocated_mechanism_rounds':6,
            'mechanism_round':recipe['specs']['round_budget']['round_index'],'remaining_after_completion':10-total},
        next_action=recipe['question'])
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='在用户批准的六轮机制研究内，依据上一轮完成证据开展下一项明确对照。')
    print('ROUND_OPENED',work.name,total,len(recipe['specs']['specs']),flush=True)

if __name__=='__main__':
    main()
