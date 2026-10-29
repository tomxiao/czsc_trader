"""Update only S017 intent through the public API; preserve historical evidence."""
import argparse
from czsc_trader.application import update_research_intent, ResearchIntentUpdate, get_research_overview
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read, save


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action=='start':
        if key in quota['experiments']:
            raise ValueError('Already started: inspect state, do not consume twice')
        if quota['remaining_rounds']<1 or quota['running_new_rounds']:
            raise ValueError('Budget or running-round state needs review')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'PAT_SIGNAL_DIAGNOSIS_RUNNING'
        quota['runtime_snapshot'][key] = 'PROTOCOL_FIXED_SYNTHETIC_CHECKS_PENDING'
        quota['signal_diagnosis_authorization'] = {
            'user_statement':'ok', 'context':'同意先对现有30m PAT入场做信号诊断，再决定退出研究',
            'scope':'单一诊断实验；不运行新完整账户、不改信号、不自动追加后续实验',
            'evidence':'research/S017/experiments/'+key+'/protocols/authorization.md'}
        intent['stage'] = 'STAGE_2_PAT_SIGNAL_DIAGNOSIS_RUNNING'
        intent['next_action'] = '按冻结期限与对照完成PAT入场机会诊断，报告后决定退出研究。'
    elif action=='finish':
        publication = read(WORK/'others/publication.json')
        validation = read(WORK/'others/result_validation.json')
        judgment = read(WORK/'others/judgment.json')
        if (publication['validation']['status']!='PASS' or validation['status']!='PASS'
                or quota['running_new_rounds']!=1 or key not in quota['experiments']):
            raise ValueError('Cannot finish unverified/unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['runtime_snapshot'][key] = 'COMPLETED_SIGNAL_DIAGNOSIS_REPORT_PUBLICATION_PASS'
        quota['reports'][key] = publication['report']
        quota['status'] = 'PAT_SIGNAL_DIAGNOSIS_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale'] = '完成用户确认的单轮信号诊断，完整账户与指南保持；下一项研究依据报告建议决定。'
        intent['stage'] = 'STAGE_2_PAT_SIGNAL_DIAGNOSIS_COMPLETE_AWAITING_DIRECTION'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_pat_account_result'] = {k:v for k,v in result.items()
            if k in ('latest_experiment','latest_experiment_conclusion','latest_experiment_report','latest_experiment_goals')}
        result.pop('latest_experiment_goals',None)
        result.update(latest_experiment=key, latest_experiment_report=publication['report'],
            latest_experiment_conclusion=judgment['conclusion'],
            conclusion=judgment['conclusion'], latest_experiment_scope='SIGNAL_INFORMATION_AND_PRICE_LABELS_ONLY',
            work_status='COMPLETE')
    else:
        overview = get_research_overview(REPOSITORY,ResearchBatchRef('S017'))
        save(WORK/'others/overview_after.json',overview.to_dict())
        print('OVERVIEW_REFRESHED',flush=True)
        return
    update_research_intent(REPOSITORY,ResearchBatchRef('S017'),ResearchIntentUpdate(research_intent=intent),
        actor='RSCH',reason='用户确认后开展并留证30m PAT入场信号诊断；历史账户不变')
    print(action.upper(),key,'remaining',quota['remaining_rounds'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','finish','overview'])
    main(parser.parse_args().action)
