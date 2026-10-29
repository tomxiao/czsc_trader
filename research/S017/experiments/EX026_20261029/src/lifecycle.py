"""One authorized final-disjoint-ablation research round through public governance APIs."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 3 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'FINAL_DISJOINT_ABLATION_RUNNING'
        quota['runtime_snapshot'][key] = 'FINAL_DISJOINT_ABLATION_PROTOCOL_AND_FOCUSED_CHECKS'
        quota['final_disjoint_ablation_authorization'] = {
            'user_statement': '允许你再用一轮实验来拆解，如果仍然没有明确结论，就回归主线。',
            'scope': '最后一轮互斥对照拆解；0新表达、0账户、0退出优化；不明确则结束拆解回归M005原型主线',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage'] = 'STAGE_2_FINAL_DISJOINT_ABLATION_RUNNING'
        intent['next_action'] = '以互斥控制核验放量贡献，窄幅作为次要诊断；本轮后不得追加拆解。'
    else:
        pub = read(WORK/'others/publication.json')
        check, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
        if (pub['validation']['status'] != 'PASS' or check['status'] != 'PASS'
                or quota['running_new_rounds'] != 1 or key not in quota['experiments']):
            raise ValueError('Cannot close unverified or unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['reports'][key] = pub['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_FINAL_DISJOINT_ABLATION_REPORT_PUBLICATION_PASS'
        quota['status'] = 'ABLATION_CLOSED_RETURN_TO_MAINLINE'
        quota['stop_rationale'] = '完成用户允许的最后一轮拆解；本支线关闭，回归完整组合的原型验证。'
        intent['stage'] = 'STAGE_2_MAINLINE_PROTOTYPE_PENDING'
        quota['ablation_branch_closed'] = True
        quota['ablation_followup_rounds_allowed'] = 0
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_volume_range_ablation_result'] = {k: v for k, v in result.items() if k in (
            'latest_experiment', 'latest_experiment_report', 'latest_experiment_conclusion', 'latest_experiment_scope')}
        result.update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='FINAL_DISJOINT_ABLATION_DIAGNOSTIC_ONLY', work_status='COMPLETE')
    update_research_intent(REPOSITORY, ResearchBatchRef('S017'), ResearchIntentUpdate(research_intent=intent),
                          actor='RSCH', reason='完成最后一轮互斥条件拆解并按用户要求关闭拆解支线')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
