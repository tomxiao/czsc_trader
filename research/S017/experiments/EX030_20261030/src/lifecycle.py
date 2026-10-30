"""Open-ended stage-two continuation, keeping the original quota history intact."""
import argparse
from common import ROOT, WORK, REPOSITORY, BATCH, EXPERIMENT, read
from czsc_trader.application import ResearchIntentUpdate, update_research_intent


def main(action):
    intent = read(ROOT/'research/registrations/S017/family.json')['research_intent']
    key = EXPERIMENT.experiment_id
    continuation = intent.setdefault('stage_two_continuation_authorization', {
        'date': '2026-10-30', 'user_statement': '不用受额度约束，可以继续开展实验',
        'scope': '阶段二证据驱动自主续研；原样本、目标和交易合同保持，不自动进入阶段三',
        'round_limit': None, 'experiments': [], 'completed_experiments': [], 'running_experiments': [],
        'reports': {}, 'original_twenty_rounds': '保留原expanded_stage_two_authorization历史，不重置或改写'})
    if action == 'start':
        if key in continuation['experiments'] or continuation['running_experiments']:
            raise ValueError('Already initiated or another experiment is running')
        continuation['experiments'].append(key)
        continuation['running_experiments'].append(key)
        continuation['status'] = 'RUNNING'
        intent['stage'] = 'STAGE_2_REPAIR_CONTEXT_COMPETITION_RUNNING'
        intent['next_action'] = '固定6柱退出，比较均价方向与低点结构两个竞争背景，复用M017完整控制。'
    else:
        pub, judgment = read(WORK/'others/publication.json'), read(WORK/'others/judgment.json')
        if pub['validation']['status'] != 'PASS' or key not in continuation['running_experiments']:
            raise ValueError('Current published verified report required')
        continuation['running_experiments'].remove(key)
        continuation['completed_experiments'].append(key)
        continuation['reports'][key] = pub['report']
        continuation['status'] = 'COMPLETED_REVIEWED_NEXT_STEP'
        intent['stage'] = 'STAGE_2_REPAIR_CONTEXT_COMPETITION_COMPLETE'
        intent['next_action'] = judgment['next_step']
        intent['stage_two_result'].update(latest_experiment=key, latest_experiment_report=pub['report'],
            latest_experiment_conclusion=judgment['conclusion'], conclusion=judgment['conclusion'],
            latest_experiment_scope='REPAIR_CONTEXT_COMPETITION', work_status='COMPLETE')
    update_research_intent(REPOSITORY, BATCH, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='用户解除原实验额度约束；保留旧20轮事实，另记阶段二定向续研')
    print(action.upper(), key, 'CONTINUATION_UNCAPPED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'finish'))
    main(parser.parse_args().action)
