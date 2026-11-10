"""Inspect or open a frozen adaptive recipe after the previous round is settled."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, create_experiment,
    ExperimentRequest, update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())


def read(path):
    return json.loads(path.read_bytes())


def save(path,value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('recipe',type=Path)
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    recipe=read(args.recipe)
    work=ROOT/'research/S019/experiments'/recipe['experiment_id']
    assert not work.exists()
    search=recipe['search']
    budget=search['round_budget']
    assert budget=={'allocated_rounds':6,'round_index':3,'total_round':7,'remaining_after_completion':3}
    assert len(search['families'])==4 and search['trial_budget']==24 and search['startup_trials']==8 and search['batch_size']==4
    assert search['candidate_start']==684 and search['seed']==20261117
    sources={name:ROOT/path for name,path in recipe['source_paths'].items()}
    for name,path in sources.items():
        assert path.is_file() and path.resolve().is_relative_to(ROOT)
        assert digest(path)==recipe['source_sha256'][name]
    previous=ROOT/recipe['previous_experiment']
    results=read(previous/'others/results.json')
    assert results['status']=='COMPLETE' and len(results['accounts'])==24
    for family in search['families']:
        path=(ROOT/family['control_account']).resolve()
        assert path.is_relative_to(ROOT/'research/S019') and path.is_file()
        ref=d.EvidenceRef.from_dict(read(path))
        assert digest(ref.resolve(ROOT))==ref.sha256
    ready=all((previous/name).exists() for name in ('others/publication.json','others/budget_settlement.json'))
    print('RECIPE_CHECK_PASS',recipe['experiment_id'],'96 proposals','predecessor_ready',ready,flush=True)
    if not args.open:
        return
    assert ready,'Predecessor publication and settlement required before creating the experiment'
    publication=read(previous/'others/publication.json')
    settlement=read(previous/'others/budget_settlement.json')
    assert publication['validation']['status']=='PASS'
    assert settlement['status']=='SETTLED_ONCE' and settlement['used_after']==6 and settlement['remaining_after']==4
    assert settlement['report']==publication['report']
    report=d.EvidenceRef.from_dict(publication['report'])
    assert digest(report.resolve(ROOT))==report.sha256
    assert read(report.resolve(ROOT))['report_sha256']==digest(previous/'report.md')
    intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['stage']=='STAGE_TWO' and intent['joint_search_budget']['used_rounds']==6
    assert intent['joint_search_budget']['remaining_rounds']==4
    repo=RepositoryContext.discover(ROOT)
    batch=d.ResearchBatchRef('S019')
    context=create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    exp=create_experiment(context,ExperimentRequest(recipe['title'],recipe['question'],date.fromisoformat(recipe['date'])))
    assert exp.resolve(ROOT)==work
    (work/'src/setup.py').write_bytes(Path(__file__).read_bytes())
    for name,path in sources.items():
        (work/'src'/name).write_bytes(path.read_bytes())
    save(work/'protocols/search.json',search)
    (work/'protocols/plan.md').write_bytes(recipe['plan'].encode())
    save(work/'protocols/continuation.json',{'authorization_decision':'S019-RESUME-MECHANISMS-20261110',
        'previous_experiment':recipe['previous_experiment'],'previous_report':publication['report'],
        'previous_settlement_sha256':digest(previous/'others/budget_settlement.json'),
        'source_origins':{name:{'path':path.relative_to(ROOT).as_posix(),'sha256':digest(path)} for name,path in sources.items()},
        'recipe_sha256':digest(args.recipe),'research_question':recipe['question'],'budget':budget})
    (work/'report.md').write_bytes(('# '+recipe['title']+'\n\nStatus: IN_PROGRESS\n').encode())
    intent.update(active_experiment=exp.to_dict(),mechanism_research_status='ROUND_PREPARING',
        active_round_budget={'round':7,'allocated_mechanism_rounds':6,'mechanism_round':3,'remaining_after_completion':3},
        next_action=recipe['question'])
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason='在六轮机制研究授权内，以相同提议预算比较四个结构的有限参数适配潜力。')
    print('ADAPTIVE_ROUND_OPENED',work.name,'96 proposals','budget settlement remains caller-owned',flush=True)


if __name__=='__main__':
    main()
