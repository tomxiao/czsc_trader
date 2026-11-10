"""Close the explicitly approved three-candidate assessment after publication."""
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, ResearchIntentUpdate, get_research_overview, update_research_intent,
)

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'research/S019'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def main():
    publication = read(WORK / 'others/assessment_publication.json')
    assert publication['report_validation']['status'] == 'PASS'
    assert publication['delivery_validation']['status'] == 'PASS'
    assert publication['delivery_validation']['scope'] == 'INTEGRITY'
    report_ref = d.EvidenceRef.from_dict(publication['report'])
    raw = report_ref.resolve(ROOT).read_bytes()
    assert sha256(raw).hexdigest() == report_ref.sha256
    assert json.loads(raw)['report_sha256'] == sha256((WORK / 'report.md').read_bytes()).hexdigest()
    accounts = read(WORK / 'others/account_results.json')
    assert accounts['status'] == 'COMPLETE'
    summary = read(WORK / 'others/assessment_summary.json')
    scope = read(WORK / 'protocols/scope.json')
    selected = scope['selected']
    rows = summary['candidates']
    assert {r['candidate']['candidate_id'] for r in rows} == {'S019-' + cid for cid in selected}
    assert all(r['parameter']['required_points'] == r['parameter']['valid_points'] == 80 for r in rows)
    assert all(not r['coverage_gaps'] for r in rows)
    ranking = summary['qualified_nar_ranking']
    accepted = [r for r in rows if r['acceptance_status'] == 'PASSED']
    ordered = sorted(accepted, key=lambda r: (-r['center']['nar'], r['candidate']['candidate_id']))
    passed_ids = [r['candidate']['candidate_id'].removeprefix('S019-') for r in ordered]
    assert [r['candidate']['candidate_id'].removeprefix('S019-') for r in ranking] == passed_ids
    assert len(scope['deferred']) == 18
    conclusion = (f"首批三个候选完成全部阶段四检查，{len(passed_ids)}个通过全部原目标。"
                  + ('按原NAR顺序为' + '、'.join(passed_ids) + '。' if passed_ids else '本批达标推荐集合为空。')
                  + '其余18个保留为未检，原21个中心达标集合保持。')
    next_action = ('建议用户审阅本次全部自检及选型代价，决定具体候选进入阶段五或继续补证；'
                   '阶段五与冻结分别取得明确批准，剩余6轮优化额度保持。' if passed_ids else
                   '建议回阶段二，优先比较ATR硬退出及参与阈值仓位跳变的替代表达，'
                   '保留C0355作为完整账户对照；原硬门目标和剩余6轮额度保持，等待用户批准研究方向。')
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    intent = read(ROOT / 'research/registrations/S019/family.json')['research_intent']
    assert intent['joint_search_budget']['used_rounds'] == 4
    assert intent['joint_search_budget']['remaining_rounds'] == 6
    assert intent['stage_four_candidates'] == selected
    intent.update(stage='STAGE_FOUR', stage_four_status='COMPLETE',
        stage_four_delivery=publication['assessment'], latest_experiment_report=publication['report'],
        stage_four_research_acceptance='PASSED_WITHIN_APPROVED_SCOPE' if passed_ids else 'FAILED_WITHIN_APPROVED_SCOPE',
        stage_four_qualified_candidates=passed_ids, stage_four_deferred_candidates=scope['deferred'],
        next_action=next_action)
    intent.pop('active_experiment', None)
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='完成用户批准的三候选完整阶段四自检，其余18项未检及剩余6轮优化额度明确保留。')
    handoff = BATCH / 'HANDOFF.md'
    text = handoff.read_text(encoding='utf-8')
    assert '## 首批三个达标候选阶段四成果' not in text
    _, history = text.split('## 目标与授权', 1)
    before, after = history.split('## 下一步\n\n', 1)
    _, assumptions = after.split('正式回放已通过DFLS', 1)
    top = ('# S019 独立MU研究交接\n\n2026-11-10，RSCH，分支 `codex/mu-independent-research`。' + conclusion
           + '最新[EX041报告](experiments/EX041_20261110/report.md)与[ASSESSMENT/2](deliveries/ASSESSMENT/2/report.md)'
           '发布完整性校验PASS；研究目标状态分别见报告。新增优化搜索0，已用4/10轮、剩余6轮。\n\n## 目标与授权')
    section = '\n## 首批三个达标候选阶段四成果\n\n' + conclusion + '\n\n'
    section += '|候选|中心NAR|中心MDD|中心Calmar|邻域通过率|压力Calmar|全部原目标|\n|---|---:|---:|---:|---:|---:|---|\n'
    for row in rows:
        c = row['center']
        section += (f"|{row['candidate']['candidate_id'].removeprefix('S019-')}|{c['nar']:.4%}|{c['mdd']:.4%}|"
                    f"{c['calmar']:.6f}|{row['parameter']['pass_rate']:.2%}|{row['stress']['calmar']:.6f}|"
                    f"{row['acceptance_status']}|\n")
    section += ('\n[范围与授权](experiments/EX041_20261110/protocols/authorization.md)、'
                '[完整点集与口径](experiments/EX041_20261110/protocols/plan.md)、'
                '[发布回执](experiments/EX041_20261110/others/assessment_publication.json)保留实际证据。'
                '原C0135/C0224失败结论及EX040全部21个中心达标交接保持；当前只检指定3个。'
                '采用原12目标核验及纯NAR研究排序，native多指标名次仅辅助。\n\n## 下一步\n\n'
                + next_action + '\n\n正式回放已通过DFLS' + assumptions)
    handoff.write_bytes((top + before + section).encode())
    save(WORK / 'others/closing_overview.json', get_research_overview(repo, batch).to_dict())
    save(WORK / 'others/closure.json', {'status': 'COMPLETE', 'assessed': selected,
        'qualified_nar_order': passed_ids, 'not_assessed': scope['deferred'],
        'remaining_optimization_rounds': 6, 'new_search_rounds': 0,
        'conclusion': conclusion, 'next_action': next_action})
    print('THREE_CENTER_STAGE_FOUR_CLOSED', passed_ids, flush=True)


if __name__ == '__main__':
    main()
