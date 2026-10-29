"""Public governance updates for the one authorized experiment."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 7 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'DOWNSIDE_FAILURE_CENSUS_RUNNING'
        quota['runtime_snapshot'][key] = 'FIXED_HYPOTHESES_AND_FOCUSED_CHECKS'
        quota['downside_failure_authorization'] = {
            'user_statement': '同意，请围绕“跌不下去”提出几种竞争性的入场假设，用同样的普查方法验证，自主完成下一轮实验。',
            'scope': '3个竞争形态、1个近期超跌背景、旧C参考，固定5期限普查，1轮、0账户',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage'] = 'STAGE_2_DOWNSIDE_FAILURE_CENSUS_RUNNING'
        intent['next_action'] = '完成跌破收回、回试不破和低点抬高的固定竞争普查。'
    else:
        publication = read(WORK/'others/publication.json')
        check = read(WORK/'others/result_validation.json')
        judgment = read(WORK/'others/judgment.json')
        if (publication['validation']['status'] != 'PASS' or check['status'] != 'PASS'
                or quota['running_new_rounds'] != 1 or key not in quota['experiments']):
            raise ValueError('Cannot close unverified or unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['reports'][key] = publication['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_DOWNSIDE_FAILURE_CENSUS_REPORT_PUBLICATION_PASS'
        quota['status'] = 'DOWNSIDE_FAILURE_CENSUS_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale'] = '完成本轮批准的固定竞争普查；下一项依据报告结论选择。'
        quota['new_entry_diagnostic_expressions'] = quota.get('new_entry_diagnostic_expressions', 0)+4
        intent['stage'] = 'STAGE_2_DOWNSIDE_FAILURE_CENSUS_COMPLETE_AWAITING_DIRECTION'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_oversold_decomposition_result'] = {k: v for k, v in result.items() if k in (
            'latest_experiment', 'latest_experiment_report', 'latest_experiment_conclusion', 'latest_experiment_scope')}
        result.update(latest_experiment=key, latest_experiment_report=publication['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='THREE_DOWNSIDE_FAILURE_ENTRIES_AND_RECENT_OVERSOLD_BACKGROUND', work_status='COMPLETE')
    update_research_intent(REPOSITORY, ResearchBatchRef('S017'), ResearchIntentUpdate(research_intent=intent),
                          actor='RSCH', reason='按用户批准完成跌不下去的竞争性入场研究')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
