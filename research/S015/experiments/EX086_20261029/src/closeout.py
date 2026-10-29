"""Append this diagnostic result without rewriting frozen research history."""
import argparse
from czsc_trader.application import update_research_intent,ResearchIntentUpdate,get_research_overview
from czsc_trader.research_tools import ResearchBatchRef
from study import REPO,ROOT,WORK,read,save


def main(action):
    if action=='finish':
        publication=read(WORK/'others/publication.json')
        assert publication['validation']['status']=='PASS'
        intent=read(ROOT/'research/registrations/S015/family.json')['research_intent']
        assert 'post_freeze_entry_census' not in intent
        judgment=read(WORK/'others/judgment.json')
        intent['post_freeze_entry_census']={'experiment':WORK.name,'status':'COMPLETED',
            'authorization':'用户要求普查S015-v1，并选择沿用当前分支。',
            'scope':'One fixed entry census; no parameter search, new continuous account or frozen qualification change.',
            'report':publication['report'],'conclusion':judgment['conclusion'],'next_step':judgment['next_step'],
            'S017_budget_consumed':0}
        update_research_intent(REPO,ResearchBatchRef('S015'),ResearchIntentUpdate(research_intent=intent),
            actor='RSCH',reason='记录用户批准的S015-v1冻结入场普查，不改原研究阶段或冻结资格')
        print('CENSUS_RECORDED',flush=True)
    else:
        result=get_research_overview(REPO,ResearchBatchRef('S015'))
        save(WORK/'others/overview_after.json',result.to_dict())
        print('OVERVIEW_REFRESHED',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('finish','overview'))
    main(parser.parse_args().action)
