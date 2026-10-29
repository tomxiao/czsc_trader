"""Account for the integrated experiment once, including engineering checks."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from run import ROOT, WORK, REPOSITORY, EXPERIMENT, BATCH, read

def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if not quota['ablation_branch_closed'] or quota['ablation_followup_rounds_allowed'] != 0:
        raise ValueError('Ablation branch must remain closed')
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 2 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'INTEGRATED_M005_EXIT_PROTOTYPES_RUNNING'
        quota['runtime_snapshot'][key] = 'INTEGRATED_ENGINEERING_AND_THREE_FIXED_EXIT_PROTOTYPES'
        quota['integrated_prototype_authorization'] = {
            'user_statement': '纯工程化任务不占单独研究额度；同意，请继续',
            'scope': 'M005入场不变；接线、一致性检查、65柱基线及三退出完整账户比较合并1轮；无参数搜索',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md',
            'engineering_separate_rounds': 0, 'research_rounds': 1,
            'new_entry_expressions': 0, 'new_exit_mechanisms': 3}
        intent['stage'] = 'STAGE_2_INTEGRATED_M005_EXIT_PROTOTYPES_RUNNING'
        intent['next_action'] = '同轮完成M005接线核验及三退出账户竞争，诊断净收益、回撤、频率与资金占用。'
    else:
        pub, analysis = read(WORK/'others/publication.json'), read(WORK/'others/analysis.json')
        verification, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
        if (pub['validation']['status'] != 'PASS' or analysis['status'] != 'PASS'
                or verification['status'] != 'PASS' or quota['running_new_rounds'] != 1
                or key not in quota['experiments']):
            raise ValueError('Cannot close unverified or unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['reports'][key] = pub['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_INTEGRATED_M005_EXIT_PROTOTYPES_REPORT_PASS'
        quota['status'] = 'INTEGRATED_M005_EXIT_PROTOTYPES_COMPLETE'
        quota['stop_rationale'] = '条件拆解支线保持关闭；集成三退出账户比较完成，剩余一轮按本轮研究结论安排。'
        intent['stage'] = 'STAGE_2_INTEGRATED_M005_EXIT_PROTOTYPES_COMPLETE'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result.update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='INTEGRATED_M005_THREE_EXIT_ACCOUNT_PROTOTYPES', work_status='COMPLETE')
    update_research_intent(REPOSITORY, BATCH, ResearchIntentUpdate(research_intent=intent),
        actor='RSCH', reason='按用户要求合并工程接线与三退出原型竞争为一轮研究')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
