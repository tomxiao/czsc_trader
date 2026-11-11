"""Close the approved continuous-exit stage-four scope after public delivery."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, get_research_overview, update_research_intent,
)

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = ROOT/'research/S019/experiments/EX050_20261111'
COUNTS = {'C0966': 242, 'C1010': 728, 'C0909': 728}


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def main():
    publication = read(WORK/'others/assessment_publication.json')
    assert publication['report_validation']['status'] == 'PASS'
    assert publication['delivery_validation']['status'] == 'PASS'
    assert publication['delivery_validation']['scope'] == 'INTEGRITY'
    ref = d.EvidenceRef.from_dict(publication['report'])
    content = ref.resolve(ROOT).read_bytes()
    assert sha256(content).hexdigest() == ref.sha256
    assert json.loads(content)['report_sha256'] == sha256((WORK/'report.md').read_bytes()).hexdigest()
    accounts = read(WORK/'others/account_results.json')
    assert accounts['status'] == 'COMPLETE' and len(accounts['accounts']) == 1704
    scope = read(WORK/'protocols/scope.json')
    summary = read(WORK/'others/assessment_summary.json')
    assert scope['selected'] == list(COUNTS) and len(scope['deferred']) == 109
    for row in summary['candidates']:
        cid = row['candidate']['candidate_id'].removeprefix('S019-')
        assert row['parameter']['required_points'] == row['parameter']['valid_points'] == COUNTS[cid]
        assert not row['coverage_gaps']
    accepted = sorted((r for r in summary['candidates'] if r['acceptance_status'] == 'PASSED'),
        key=lambda r: (-r['center']['nar'], r['candidate']['candidate_id']))
    ids = [r['candidate']['candidate_id'].removeprefix('S019-') for r in accepted]
    assert ids == [r['candidate']['candidate_id'].removeprefix('S019-') for r in summary['qualified_nar_ranking']]
    next_action = ('请用户审阅阶段四结果并选择进入阶段五的具体候选；精确冻结计划另行批准。' if ids else
        '依据完整邻域的敏感轴和机制差异，建议用户审阅后确定继续优化方向或扩大自检候选范围。')
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['continuous_stage3_budget'] == scope['optimization_budget_snapshot']
    assert intent['continuous_stage3_budget']['remaining_rounds'] == 7
    assert intent['stage_four_continuous_candidates'] == scope['selected']
    intent.update(stage='STAGE_FOUR', stage_four_continuous_status='COMPLETE',
        stage_four_continuous_delivery=publication['assessment'],
        stage_four_continuous_qualified_candidates=ids,
        stage_four_continuous_deferred_candidates=scope['deferred'],
        stage_four_continuous_acceptance='PASSED_WITHIN_APPROVED_SCOPE' if ids else 'FAILED_WITHIN_APPROVED_SCOPE',
        latest_experiment_report=publication['report'], next_action=next_action)
    intent.pop('active_experiment', None)
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='三个指定候选完整阶段四已完成，109项待选和剩余7轮优化额度保持。')
    save(WORK/'others/closing_overview.json', get_research_overview(repo, batch).to_dict())
    save(WORK/'others/closure.json', {'status': 'COMPLETE', 'assessed': scope['selected'],
        'qualified_nar_order': ids, 'not_assessed': scope['deferred'], 'new_search_rounds': 0,
        'remaining_optimization_rounds': 7, 'next_action': next_action})
    print('THREE_CENTER_STAGE_FOUR_CLOSED', ids, flush=True)


if __name__ == '__main__':
    main()
