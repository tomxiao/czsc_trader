"""Record the last authorized round through the public research-intent API."""
import argparse
from common import ROOT, WORK, REPOSITORY, BATCH, EXPERIMENT, read
from czsc_trader.application import ResearchIntentUpdate, update_research_intent


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    quota = intent['expanded_stage_two_authorization']
    key = EXPERIMENT.experiment_id
    if action == 'start':
        if key in quota['experiments'] or quota['remaining_rounds'] != 1 or quota['running_new_rounds']:
            raise ValueError('Quota or running state changed')
        quota['experiments'].append(key)
        quota['initiated_new_rounds'] += 1
        quota['remaining_rounds'] -= 1
        quota['running_new_rounds'] = 1
        quota['status'] = 'SHORT_ENTRY_TEMPORAL_COMPETITION_RUNNING'
        quota['runtime_snapshot'][key] = 'AUTHORIZED_PROTOCOL_AND_FOCUSED_CHECKS'
        quota['short_entry_temporal_authorization'] = {
            'user_statement': '这个思路可以，请继续',
            'scope': '新分支三入场短周期普查、时间变化及因果顺序检验；至多四静态账户；剩余1轮',
            'protocol': str((WORK/'protocols/design.md').relative_to(ROOT)).replace('\\', '/'),
            'research_rounds': 1, 'engineering_separate_rounds': 0}
        intent['stage'] = 'STAGE_2_SHORT_ENTRY_TEMPORAL_COMPETITION_RUNNING'
        intent['next_action'] = '固定三表达与3/6/13柱标签，检验时间延续和有依据的完整账户。'
    else:
        pub, judgment = read(WORK/'others/publication.json'), read(WORK/'others/judgment.json')
        if pub['validation']['status'] != 'PASS' or not quota['running_new_rounds'] or key not in quota['experiments']:
            raise ValueError('Cannot finish without published verified report')
        quota['completed_new_rounds'] += 1
        quota['running_new_rounds'] = 0
        quota['reports'][key] = pub['report']
        quota['runtime_snapshot'][key] = 'COMPLETED_SHORT_ENTRY_TEMPORAL_REPORT_PASS'
        quota['status'] = 'STAGE_TWO_BUDGET_EXHAUSTED_AWAITING_USER'
        quota['stop_rationale'] = '20轮额度已用完；不追加研究、不自动进入阶段三。'
        intent['stage'] = 'STAGE_2_SHORT_ENTRY_TEMPORAL_COMPLETE_AWAITING_USER'
        intent['next_action'] = judgment['next_step']
        intent['stage_two_result'].update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='SHORT_ENTRY_AND_TEMPORAL_COMPETITION', work_status='COMPLETE')
    update_research_intent(REPOSITORY, BATCH, ResearchIntentUpdate(research_intent=intent),
        actor='RSCH', reason='按用户批准执行短周期入场及时间延续联合实验，保持原目标和样本')
    print(action.upper(), key, 'remaining', quota['remaining_rounds'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
