"""One authorized numbered-entry research round through public governance APIs."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 5 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'NUMBERED_ENTRY_COMPETITION_RUNNING'
        quota['runtime_snapshot'][key] = 'NUMBERED_ENTRY_PROTOCOL_AND_FOCUSED_CHECKS'
        quota['numbered_entry_authorization'] = {
            'user_statement': '你继续主导下一轮实验；机制使用带数字的编号，沟通反馈使用编号。',
            'scope': 'S017-M001/S017-M002原参照；S017-M003至S017-M005三个新入场表达；1轮、0账户、0退出优化',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage'] = 'STAGE_2_NUMBERED_ENTRY_COMPETITION_RUNNING'
        intent['next_action'] = '普查三项不强制超跌背景的数天修复入场表达，比较普通机会和背景分层后的增量。'
    else:
        pub = read(WORK/'others/publication.json')
        check, judgment = read(WORK/'others/result_validation.json'), read(WORK/'others/judgment.json')
        if (pub['validation']['status'] != 'PASS' or check['status'] != 'PASS'
                or quota['running_new_rounds'] != 1 or key not in quota['experiments']):
            raise ValueError('Cannot close unverified or unstarted experiment')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['new_entry_diagnostic_expressions'] = quota.get('new_entry_diagnostic_expressions', 0)+3
        quota['reports'][key] = pub['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_NUMBERED_ENTRY_COMPETITION_REPORT_PUBLICATION_PASS'
        quota['status'] = 'NUMBERED_ENTRY_COMPETITION_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale'] = '完成批准的一轮三项数字编号入场竞争普查，未优化退出或创建账户。'
        intent['stage'] = 'STAGE_2_NUMBERED_ENTRY_COMPETITION_COMPLETE_AWAITING_DIRECTION'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_retest_delayed_repair_result'] = {k: v for k, v in result.items() if k in (
            'latest_experiment', 'latest_experiment_report', 'latest_experiment_conclusion', 'latest_experiment_scope')}
        result.update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='NUMBERED_ENTRY_COMPETITION_DIAGNOSTIC_ONLY', work_status='COMPLETE')
    update_research_intent(REPOSITORY, ResearchBatchRef('S017'), ResearchIntentUpdate(research_intent=intent),
                          actor='RSCH', reason='按用户授权完成数字编号机制的数天修复入场竞争普查')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
