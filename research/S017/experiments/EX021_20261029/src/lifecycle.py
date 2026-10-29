"""One authorized quota round; public governance state changes only."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 8 or quota['running_new_rounds']:
            raise ValueError('Authorization/quota state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'OVERSOLD_DECOMPOSITION_RUNNING'
        quota['runtime_snapshot'][key] = 'FIXED_PROTOCOL_IMPLEMENTATION_AND_FOCUSED_CHECKS'
        quota['oversold_decomposition_authorization'] = {
            'user_statement': '同意，请你主导执行',
            'scope': '固定D/R/C/D_NR拆解、episode及同队列持续性诊断，1轮，0新账户',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage'] = 'STAGE_2_OVERSOLD_DECOMPOSITION_RUNNING'
        intent['next_action'] = '完成固定超跌拆解及收益持续性诊断；依据证据判断是否值得继续研究退出。'
    else:
        publication = read(WORK/'others/publication.json')
        check = read(WORK/'others/result_validation.json')
        judgment = read(WORK/'others/judgment.json')
        if (publication['validation']['status'] != 'PASS' or check['status'] != 'PASS'
                or quota['running_new_rounds'] != 1 or key not in quota['experiments']):
            raise ValueError('Cannot finish unverified or unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['reports'][key] = publication['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_OVERSOLD_DECOMPOSITION_REPORT_PUBLICATION_PASS'
        quota['status'] = 'OVERSOLD_DECOMPOSITION_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale'] = '完成批准单轮拆解；未启动退出优化、完整账户或封存验证。'
        quota['new_entry_diagnostic_expressions'] = quota.get('new_entry_diagnostic_expressions', 0)+3
        intent['stage'] = 'STAGE_2_OVERSOLD_DECOMPOSITION_COMPLETE_AWAITING_DIRECTION'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_entry_competition_result'] = {k: v for k, v in result.items() if k in (
            'latest_experiment', 'latest_experiment_report', 'latest_experiment_conclusion', 'latest_experiment_scope')}
        result.update(latest_experiment=key, latest_experiment_report=publication['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='OVERSOLD_DECOMPOSITION_FIXED_COHORT_PRICE_LABELS_ONLY', work_status='COMPLETE')
    update_research_intent(REPOSITORY, ResearchBatchRef('S017'), ResearchIntentUpdate(research_intent=intent),
                          actor='RSCH', reason='按批准的一轮固定超跌拆解执行并留存验证结果')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
