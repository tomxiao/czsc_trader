"""One authorized volume-range-ablation research round through public governance APIs."""
import argparse
from czsc_trader.application import ResearchIntentUpdate, update_research_intent
from czsc_trader.research_tools import ResearchBatchRef
from study import ROOT, WORK, REPOSITORY, EXPERIMENT, read


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 4 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'VOLUME_RANGE_ABLATION_RUNNING'
        quota['runtime_snapshot'][key] = 'VOLUME_RANGE_ABLATION_PROTOCOL_AND_FOCUSED_CHECKS'
        quota['volume_range_ablation_authorization'] = {
            'user_statement': '这个发现有意义，请继续；同意按S017-M005原规则拆解放量与窄幅。',
            'scope': '保留S017-M001/S017-M002/S017-M005；新增S017-M006至S017-M008三项条件删减对照；1轮、0账户、0退出优化',
            'protocol': 'research/S017/experiments/'+key+'/protocols/design.md'}
        intent['stage'] = 'STAGE_2_VOLUME_RANGE_ABLATION_RUNNING'
        intent['next_action'] = '核验S017-M005中放量、窄幅条件相对共同收复底座的条件增量。'
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
        quota['runtime_snapshot'][key] = 'COMPLETED_VOLUME_RANGE_ABLATION_REPORT_PUBLICATION_PASS'
        quota['status'] = 'VOLUME_RANGE_ABLATION_COMPLETE_AWAITING_DIRECTION'
        quota['stop_rationale'] = '完成批准的S017-M005放量与窄幅条件拆解，未优化退出或创建账户。'
        intent['stage'] = 'STAGE_2_VOLUME_RANGE_ABLATION_COMPLETE_AWAITING_DIRECTION'
        intent['next_action'] = judgment['next_step']
        result = intent['stage_two_result']
        result['prior_numbered_entry_competition_result'] = {k: v for k, v in result.items() if k in (
            'latest_experiment', 'latest_experiment_report', 'latest_experiment_conclusion', 'latest_experiment_scope')}
        result.update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='VOLUME_RANGE_ABLATION_DIAGNOSTIC_ONLY', work_status='COMPLETE')
    update_research_intent(REPOSITORY, ResearchBatchRef('S017'), ResearchIntentUpdate(research_intent=intent),
                          actor='RSCH', reason='按用户授权完成S017-M005放量与窄幅条件拆解')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
