"""S017 operational intent updates only through the public governance API."""
import argparse
from czsc_trader.application import update_research_intent,ResearchIntentUpdate,get_research_overview
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT,WORK,REPOSITORY,EXPERIMENT,read,save


def main(action):
    intent=read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota=intent['expanded_stage_two_authorization']
    key=EXPERIMENT.experiment_id
    if action=='start':
        if key in quota['experiments'] or quota['remaining_rounds']!=9 or quota['running_new_rounds']:
            raise ValueError('Quota or experiment state changed; inspect before retry')
        quota['experiments'].append(key)
        quota['initiated_new_rounds']+=1
        quota['remaining_rounds']-=1
        quota['running_new_rounds']=1
        quota['status']='ENTRY_COMPETITION_RUNNING'
        quota['runtime_snapshot'][key]='FIXED_PROTOCOL_IMPLEMENTATION_AND_FOCUSED_CHECKS'
        quota['entry_competition_authorization']={'user_statement':'执行',
            'scope':'批准五种入场表达竞争性诊断，固定五期限，1轮额度，0新完整账户',
            'protocol':'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage']='STAGE_2_ENTRY_COMPETITION_RUNNING'
        intent['next_action']='完成获准5表达入场诊断与旧PAT复核，依据结果提出后续方向。'
    elif action=='finish':
        publication=read(WORK/'others/publication.json')
        validation=read(WORK/'others/result_validation.json')
        judgment=read(WORK/'others/judgment.json')
        if (publication['validation']['status']!='PASS' or validation['status']!='PASS'
                or quota['running_new_rounds']!=1 or key not in quota['experiments']):
            raise ValueError('Cannot finish unverified or unstarted experiment')
        quota['completed_new_rounds']+=1
        quota['running_new_rounds']=0
        quota['reports'][key]=publication['report']
        quota['runtime_snapshot'][key]='COMPLETED_ENTRY_COMPETITION_REPORT_PUBLICATION_PASS'
        quota['status']='ENTRY_COMPETITION_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale']='完成获准单轮5表达竞争性诊断；未优化退出或启动完整账户，下一项依据报告建议决定。'
        quota['new_entry_diagnostic_expressions']=quota.get('new_entry_diagnostic_expressions',0)+5
        intent['stage']='STAGE_2_ENTRY_COMPETITION_COMPLETE_AWAITING_DIRECTION'
        intent['next_action']=judgment['next_step']
        result=intent['stage_two_result']
        result['prior_signal_diagnosis_result']={k:v for k,v in result.items()
            if k in ('latest_experiment','latest_experiment_report','latest_experiment_conclusion','latest_experiment_scope')}
        result.update(latest_experiment=key,latest_experiment_report=publication['report'],
            latest_experiment_conclusion=judgment['conclusion'],conclusion=judgment['conclusion'],
            latest_experiment_scope='FIVE_ENTRY_EXPRESSIONS_INFORMATION_AND_PRICE_LABELS_ONLY',work_status='COMPLETE')
    else:
        overview=get_research_overview(REPOSITORY,ResearchBatchRef('S017'))
        save(WORK/'others/overview_after.json',overview.to_dict())
        print('OVERVIEW_REFRESHED',flush=True)
        return
    update_research_intent(REPOSITORY,ResearchBatchRef('S017'),ResearchIntentUpdate(research_intent=intent),
        actor='RSCH',reason='按用户执行指令完成入场机制竞争性诊断；不改历史账户或验收标准')
    print(action.upper(),key,'remaining',quota['remaining_rounds'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','finish','overview'])
    main(parser.parse_args().action)
