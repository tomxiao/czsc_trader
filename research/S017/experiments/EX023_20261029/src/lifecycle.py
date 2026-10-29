"""One authorized fixed-entry follow-up through public governance updates."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 6 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'RETEST_DELAYED_REPAIR_RUNNING'
        quota['runtime_snapshot'][key] = 'FIXED_ENTRY_REPAIR_PROTOCOL_AND_FOCUSED_CHECKS'
        quota['retest_delayed_repair_authorization'] = {
            'user_statement': '同意，请围绕“回试前低不破后的数天修复”继续验证，保持入场规则不变，先不优化退出，自主完成下一轮实验。',
            'scope': '原T固定入场、数天修复补证、1轮、0账户、0退出优化',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage'] = 'STAGE_2_RETEST_DELAYED_REPAIR_RUNNING'
        intent['next_action'] = '核验固定T数天修复的绝对机会、背景增量、年际集中性与样本依赖。'
    else:
        pub = read(WORK/'others/publication.json')
        check, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
        if (pub['validation']['status'] != 'PASS' or check['status'] != 'PASS'
                or quota['running_new_rounds'] != 1 or key not in quota['experiments']):
            raise ValueError('Cannot close unverified or unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['reports'][key] = pub['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_RETEST_DELAYED_REPAIR_REPORT_PUBLICATION_PASS'
        quota['status'] = 'RETEST_DELAYED_REPAIR_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale'] = '完成批准的固定T数天修复补证；未改入场或优化退出。'
        intent['stage'] = 'STAGE_2_RETEST_DELAYED_REPAIR_COMPLETE_AWAITING_DIRECTION'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_downside_failure_result'] = {k: v for k, v in result.items() if k in (
            'latest_experiment', 'latest_experiment_report', 'latest_experiment_conclusion', 'latest_experiment_scope')}
        result.update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='UNCHANGED_RETEST_ENTRY_DELAYED_REPAIR_EVIDENCE_ONLY', work_status='COMPLETE')
    update_research_intent(REPOSITORY, ResearchBatchRef('S017'), ResearchIntentUpdate(research_intent=intent),
                          actor='RSCH', reason='按用户授权完成原T固定入场的数天修复补证')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
