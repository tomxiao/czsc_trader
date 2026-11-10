"""Publish the center-target search, preserving prior failures and the remaining budget."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import (
    RepositoryContext, create_research_context, publish_evidence, validate_experiment,
    assemble_delivery, register_candidate, load_candidate, CandidateRegistrationRequest,
    ResearchIntentUpdate, update_research_intent, get_research_overview,
)
from dataflows import ProviderConfig
from strategy_manager import CandidateKey
from strategy_runtime import EquityStrategyCandidate, EquityStrategyDefinition

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'research/S019'
EXP = d.ExperimentRef('S019', WORK.name)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def prepare():
    summary = read(WORK / 'others/summary.json')
    qualified = read(WORK / 'others/qualified_candidates.json')
    review = read(WORK / 'others/search_review.json')
    execution = read(WORK / 'others/execution.json')
    prior = read(BATCH / 'experiments/EX038_20261110/others/budget.json')
    audit = read(WORK / 'others/semantic_audit.json')
    paths = read(WORK / 'others/final_diagnostics.json')
    assert paths['status'] == 'COMPLETE' and paths['new_accounts'] == 0
    assert paths['qualified_sha256'] == sha256((WORK / 'others/qualified_candidates.json').read_bytes()).hexdigest()
    assert paths['source_sha256'] == sha256((WORK / 'src/final_diagnostics.py').read_bytes()).hexdigest()
    assert paths['analysis_source_sha256'] == sha256((WORK / 'src/prior_diagnostics.py').read_bytes()).hexdigest()
    assert paths['prior_diagnostics_sha256'] == sha256((WORK / 'others/prior_diagnostics.json').read_bytes()).hexdigest()
    assert audit['audit_source_sha256'] == sha256((WORK / 'src/semantic_audit.py').read_bytes()).hexdigest()
    assert audit['manifest_sha256'] == sha256((WORK / 'others/audit_manifest.json').read_bytes()).hexdigest()
    assert all(x['business_rules'] == x['signal_availability'] == x['holding_and_position_feedback'] == 'PASS'
               for x in audit['results'])
    assert prior['used_rounds'] == 3 and prior['remaining_rounds'] == 7
    this = {'round': 4, 'experiment': WORK.name, 'parent': 'C0300', 'proposals': 48,
        'unique_configurations': len(summary), 'candidate_accounts': review['new_evaluations'],
        'benchmark_accounts': review['new_benchmarks'], 'imported_observations': 81,
        'inherited_qualified_implementations': 9,
        'eligible_ids': review['qualified_ids_by_nar'],
        'protocol_sha256': sha256((WORK / 'protocols/plan.md').read_bytes()).hexdigest()}
    signatures = []
    for ex in ('EX036_20261110', 'EX037_20261110', 'EX038_20261110', WORK.name):
        old = BATCH / 'experiments' / ex
        for name in read(old / 'others/summary.json'):
            definition = read(old / f'others/{name}_definition.json')
            signatures.append((definition['source_sha256'], json.dumps(json.loads(definition['parameters_json']), sort_keys=True)))
    budget = {**prior, 'used_rounds': 4, 'remaining_rounds': 6,
        'proposals': prior['proposals'] + 48,
        'unique_configurations': prior['unique_configurations'] + len(summary),
        'candidate_accounts': prior['candidate_accounts'] + review['new_evaluations'],
        'benchmark_accounts': prior['benchmark_accounts'] + review['new_benchmarks'],
        'eligible_candidates': len(qualified), 'rounds': [*prior['rounds'], this],
        'distinct_configurations_across_rounds': len(set(signatures)),
        'repeated_configurations_across_rounds': len(signatures) - len(set(signatures)),
        'imported_observation_count_this_round': 81,
        'counting_note': '81 historical observations are search inputs, not additional current proposals or account replays. Exact current/historical aliases retained separately.'}
    save(WORK / 'others/budget.json', budget)
    best = qualified[0]
    m = best['candidate']
    prior_best = read(WORK / 'others/prior_center_eligible.json')[0]['candidate']
    maximum_calmar = max(qualified, key=lambda r: r['candidate']['calmar'])
    improvement = m['nar'] - prior_best['nar']
    next_action = ('建议将全部中心达标实现纳入阶段四，复用已有账户并估算完整点集后，按用户批准的范围执行；'
                   '重点比较最高NAR及最高Calmar配置，检验ATR敏感性、费用压力和已见样本风险。剩余6轮优化额度保留。')
    conclusion = (f"第4轮中心硬门优化已完成：导入81份既有观察，48次新提议，实际新增{review['new_evaluations']}策略和"
        f"{review['new_benchmarks']}买持账户。本轮提议中{len(review['new_proposal_qualified_ids'])}个不同配置通过全部中心硬门；"
        f"合并9个既有达标点并去除精确实现重复后，共{len(qualified)}个中心达标实现。最高NAR为{best['id']}："
        f"NAR{m['nar']:.4%}、MDD{m['drawdown']:.4%}、Calmar{m['calmar']:.6f}。"
        f"相对原C0300的NAR变化为{improvement*100:+.4f}个百分点。")
    save(WORK / 'others/interpretation.json', {'conclusion': conclusion, 'next': next_action})
    lines = ['# S019第4轮：回到中心硬门的联合优化', 'Status: COMPLETE；阶段三中心目标已取得达标配置。',
        conclusion,
        '原目标保持NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费用买持80%、滚动60日闭合中位数≥6且至少3笔覆盖率≥90%。'
        '达标后按未舍入NAR降序。旧C0135/C0224的ASSESSMENT/1失败结果保留，当前新中心的完整稳健性自检待后续批准。',
        '## 方法及选择历史',
        'Optuna4.9.0多变量约束TPE，四维联合空间见[事前方案](protocols/plan.md)和[搜索配置](protocols/search.json)。'
        '导入80个C0224邻域点及原中心共81个正式观察，已超过n_startup_trials=16的总观察启动阈值；'
        '除首个强制C0300控制外，新提议直接采用TPE自适应搜索。4个账户worker、各1原生线程，'
        'InMemoryStorage与完整JSON提议/反馈检查点，48次新提议，无剪枝。导入观察、重复提议及新账户分别统计。',
        '2021预热，2022-01-03至2026-10-30连续已见开发历史；MU/SOXX、HFQ整数单位、10万美元、'
        '每侧0.1%成本、限价买入和市价卖出合同沿用。既有正式账户和投影通过公共TDR读取；没有新增样本或改变中心门槛。',
        '## 核心比较', '|配置|来源|NAR|MDD|Calmar|60日闭合中位|至少3笔覆盖|', '|---|---|---:|---:|---:|---:|---:|']
    for row in qualified:
        c = row['candidate']
        lines.append(f"|{row['id']}|{row['origin']}|{c['nar']:.4%}|{c['drawdown']:.4%}|{c['calmar']:.6f}|{c['frequency_median']:g}|{c['frequency_coverage']:.4%}|")
    lines.extend([f"最高Calmar配置为{maximum_calmar['id']}，NAR{maximum_calmar['candidate']['nar']:.4%}、"
                  f"MDD{maximum_calmar['candidate']['drawdown']:.4%}、Calmar{maximum_calmar['candidate']['calmar']:.6f}。"
                  '原排序仍以达标后的NAR为准。全部达标实现及重复别名保留在结构化结果中。',
        f"最高NAR配置参数：`{json.dumps(best['parameters'], ensure_ascii=False, sort_keys=True)}`。"
        f"命中当前搜索边界的参数为`{json.dumps(review['best_boundary_parameters'], ensure_ascii=False)}`；有限搜索覆盖与边界风险继续披露。",
        'C0367的quiet_fraction=0.735接近暂定上界0.75。较高仓位区间亦有多项Calmar失败，'
        '例如quiet_fraction=0.74的C0374和C0381，当前联合搜索尚未呈现稳定的单向改善。'
        '本轮按事前48提议停止，暂未额外扩边；优先验证新中心的参数及费用稳健性，再据结果决定是否投入剩余额度扩边。',
        '## 路径依据与风险',
        '既有C0300、C0224、C0135的117个闭合周期入退场时点相同，改善主要来自配置仓位。'
        '纯ATR上下5%的差异集中在少数退出及随后重入，保留的负面证据提示局部参数脆弱性。'
        '具体周期、MDD迁移、年度取舍及差异日集中度见[既有路径复盘](others/prior_diagnostics.md)。'
        '本轮中心达标反映已见样本内的搜索结果，正式完整参数联合通过率、费用压力和独立前瞻各自按原协议另行判断。'])
    lines.append('本轮C0367与C0355相对C0300均维持117次相同入场，仅两次实际退出改变。'
        'C0367提高弱势仓位与低参与仓位，C0355主要提高低参与仓位并调整参与阈值；'
        '两者在2025及2026年的账户收益提升，同时2023年收益下降。'
        '最大回撤均转移至2026年10月且截至样本终点尚未恢复，回撤绝对幅度也略高于C0300。'
        'C0367的Calmar仅高于原门槛0.008940，C0355高出0.180354，后续自检需重点检验这项余量。')
    baseline = read(WORK / 'others/prior_diagnostics.json')['accounts']['C0300']
    for cid, path in paths['accounts'].items():
        comparison = paths['comparisons'][cid]
        episode = path['mdd_episode']
        lines.append(f"### {cid}与C0300的实际路径比较")
        if comparison.get('identical_daily_path'):
            lines.append('逐日收益路径与C0300完全相同。')
        else:
            lines.append(f"共有{comparison['common_entries']}个相同实际入场时点，"
                f"其中{comparison['changed_exit_count']}个退出时点改变；"
                f"新配置独有入场{len(comparison['left_only_entries'])}次，C0300独有入场{len(comparison['right_only_entries'])}次。"
                f"最大回撤从{episode['peak']}至{episode['trough']}，"
                f"{'截至样本终点尚未恢复' if episode['recovery'] is None else '恢复日期' + episode['recovery']}。")
            lines.extend(['|年份|新配置实际区间收益|C0300实际区间收益|', '|---|---:|---:|'])
            for year, record in path['yearly'].items():
                lines.append(f"|{year}|{record['return']:.4%}|{baseline['yearly'][year]['return']:.4%}|")
            lines.append('2026年仅截至10月30日；表中为各自然年已覆盖区间的实际收益。')
            changes = comparison['largest_cycle_contribution_deltas'][:3]
            lines.append('归一化周期损益差异最大的三个相同入场周期：' + '；'.join(
                f"{x['entry_at']}（{x['normalized_pnl_delta']*100:+.4f}个百分点）" for x in changes) +
                '。该描述使用各自入场权益作分母，同时受仓位、退出及复利影响。')
    lines.extend(['[领先配置完整路径比较](others/final_diagnostics.json)',
        '## 全部本轮配置', '|账户|候选|NAR|MDD|Calmar|中心全部门槛|', '|---|---|---:|---:|---:|---|'])
    for name, row in summary.items():
        c = row['candidate']
        lines.append(f"|{name}|{row['id']}|{c['nar']:.4%}|{c['drawdown']:.4%}|{c['calmar']:.6f}|{c['eligible']}|")
    lines.extend(['## 执行、核验与额度',
        f"首次C0300精确控制重新回放，逐日经济路径、目标决定和实际成交等价核验PASS。"
        f"{len(audit['results'])}个代表账户共{sum(x['decisions'] for x in audit['results']):,}条决定独立业务重建PASS；"
        '全部提议账户另核验身份、源码、信息时序、目标范围、现金及整数成交。'
        '公共执行统计、历史指标投影和恢复记录按实际输出保留。',
        f"原10轮额度已用4轮，剩余6轮；本轮48提议、{len(summary)}个不同提议配置、"
        f"{review['new_evaluations']}次新策略回放。81个导入观察属于已有证据，正式阶段四EX039的90个自检账户独立记账。"
        f"本轮会话记录耗时{execution['total_seconds']/60:.2f}分钟，后续复核及发布另计。",
        '[全部提议](others/trials.json) · [全部账户指标](others/summary.json) · [达标集合](others/qualified_candidates.json) · '
        '[精确重复](others/exact_aliases.json) · [中心等价](others/center_parity.json) · [业务核验](others/semantic_audit.json) · '
        '[执行统计](others/execution.json) · [预算](others/budget.json)',
        '## 下一步', next_action])
    report_text = '\n\n'.join(lines).replace('|\n\n|', '|\n|') + '\n'
    (WORK / 'report.md').write_bytes(report_text.encode())
    print('REPORT_READY', best['id'], len(qualified), flush=True)


def publish():
    assert not (BATCH / 'deliveries/CANDIDATES/6/receipt.json').exists()
    assert not (WORK / 'report_ref.json').exists()
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    context = create_research_context(repo, batch, providers=ProviderConfig(bindings={}, equity_bindings={}))
    qualified = read(WORK / 'others/qualified_candidates.json')
    review = read(WORK / 'others/search_review.json')
    budget = read(WORK / 'others/budget.json')
    narrative = read(WORK / 'others/interpretation.json')
    entries, registrations, evidence = [], [], []
    for row in qualified:
        ref = d.EvidenceRef.from_dict(row['account'])
        assert sha256(ref.resolve(ROOT).read_bytes()).hexdigest() == ref.sha256
        candidate = EquityStrategyCandidate('S019', row['id'], EquityStrategyDefinition.from_dict(row['definition']), WORK / 'src')
        registration = register_candidate(repo, CandidateRegistrationRequest(candidate, ref.experiment,
            (ref,), tuple(candidate.definition.dependencies)))
        loaded = load_candidate(repo, CandidateKey('S019', row['id']))
        assert loaded.content_identity.content_sha256 == row['content_hash']
        registrations.append(registration.to_dict())
        entries.append(d.CandidateEntry(d.CandidateIdentityRef(candidate.key, row['content_hash']),
            '下跌后开盘恢复入场，季度相对走势与成交参与配置仓位，ATR跟踪及五日退出。',
            '完整连续账户通过原六项中心硬门；新中心完整自检待后续授权，保留旧自检失败与ATR敏感性证据。',
            (d.EvaluationEvidenceRef(ref, (row['evaluation_id'],)),)))
    save(WORK / 'others/candidate_registrations.json', registrations)
    for row in read(WORK / 'protocols/prior_observations.json'):
        evidence.append(d.EvidenceRef.from_dict(row['account_ref']))
    for row in read(WORK / 'others/summary.json').values():
        evidence.append(d.EvidenceRef.from_dict(row['account']))
    for relative in read(WORK / 'protocols/config.json')['controls']:
        evidence.append(d.EvidenceRef.from_dict(read(ROOT / relative)))
    paths = [*sorted((WORK / 'src').glob('*.py')), *sorted((WORK / 'protocols').glob('*')),
             *sorted((WORK / 'others').glob('*.json')), *sorted((WORK / 'others').glob('*.md')),
             BATCH / 'deliveries/ASSESSMENT/1/receipt.json', BATCH / 'experiments/EX038_20261110/others/budget.json',
             BATCH / 'experiments/EX013_20261110/src/runner.py',
             BATCH / 'experiments/EX003_20261110/src/data_window.py',
             BATCH / 'experiments/EX003_20261110/others/preparation.json',
             BATCH / 'experiments/EX001_20261110/src/load_data.py',
             BATCH / 'experiments/EX001_20261110/src/prepare_data.py']
    for i, path in enumerate(paths):
        if path.name in {'publication.json', 'stage_publication.json'} or not path.is_file():
            continue
        ext = path.suffix[1:]
        evidence.append(publish_evidence(context, d.MaterialEvidenceWrite(EXP, f'hard-gate-{i:03}-{path.stem}',
            path.read_bytes(), {'json': 'application/json', 'md': 'text/markdown', 'py': 'text/x-python'}[ext], ext)))
    evidence = tuple(dict.fromkeys(evidence))
    report = publish_evidence(context, d.ExperimentReportWrite(EXP, sha256((WORK / 'report.md').read_bytes()).hexdigest(),
        d.ExperimentOutcome.COMPLETED, evidence))
    validation = validate_experiment(repo, d.ExperimentValidationRequest(EXP, d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    save(WORK / 'others/publication.json', {'report': report.to_dict(), 'validation': validation.to_dict()})
    search = d.SearchSummary('C0300-IMPORTED-FOUR-DIMENSIONAL',
        'Optuna4.9.0多变量约束TPE，81份已核验历史观察导入，48次新提议，4账户并发，无剪枝。',
        '固定下跌1日、持有5日、参与跨度3日；仓位、ATR、参与阈值及低参与仓位联合空间见方案。',
        48, review['unique_proposal_configurations'], '全部六项原中心门槛通过后按未舍入NAR降序',
        ('反复使用的开发历史及自适应选择', 'ATR敏感性仍有负面证据', '新中心正式自检尚待授权'),
        (report, *evidence))
    predecessor = d.DeliveryReference.from_dict(read(BATCH / 'deliveries/PROTOTYPES/2/receipt.json')['reference'])
    stage_report = '# S019阶段三：中心硬门联合优化\n\n' + narrative['conclusion'] + '\n\n' + narrative['next']
    stage_report += '\n\n[完整报告](../../../experiments/EX040_20261110/report.md) · [预算](../../../experiments/EX040_20261110/others/budget.json)\n'
    result = assemble_delivery(repo, d.DeliveryDefinition(batch, d.DeliveryStage.CANDIDATES, 6, (predecessor,)),
        d.DeliveryContent(d.CandidateSet(tuple(entries), tuple(x.identity.key for x in entries), (search,),
            '第4轮完成，全部中心达标实现按NAR排序交接；剩余6轮。旧自检失败及本轮新中心待自检状态保留。'),
            d.DeliveryStatus.COMPLETE, (), (), report=stage_report, evidence=(report, *evidence)))
    assert result.validation.status is d.ValidationStatus.PASS
    assert result.validation.scope is d.DeliveryValidationScope.INTEGRITY
    save(WORK / 'others/stage_publication.json', result.to_dict())
    intent = read(ROOT / 'research/registrations/S019/family.json')['research_intent']
    assert intent['joint_search_budget']['used_rounds'] == 3
    intent.update(stage='STAGE_THREE', joint_search_status='ROUND_FOUR_COMPLETE', joint_search_budget=budget,
        joint_search_delivery=result.receipt.reference.to_dict(), latest_experiment_report=report.to_dict(),
        next_stage_four_approval='PENDING_USER_APPROVAL', next_action=narrative['next'])
    intent.pop('active_round_budget', None)
    intent.pop('active_experiment', None)
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='完成恢复后的第4轮中心硬门优化，交接全部达标配置并保留6轮额度。')
    handoff = BATCH / 'HANDOFF.md'
    old = handoff.read_text(encoding='utf-8')
    _, body = old.split('## 目标与授权', 1)
    before, tail = body.split('## 下一步\n\n', 1)
    _, assumptions = tail.split('正式回放已通过DFLS', 1)
    top = '# S019 独立MU研究交接\n\n2026-11-10，RSCH，分支 `codex/mu-independent-research`。'
    top += narrative['conclusion'] + ' 最新[EX040](experiments/EX040_20261110/report.md)与[CANDIDATES/6](deliveries/CANDIDATES/6/report.md)发布校验PASS。'
    top += '阶段三中心目标取得达标配置，新中心完整自检待用户决定；已用4/10轮，剩余6轮。\n\n## 目标与授权'
    section = '\n## 第4轮：恢复中心硬门联合优化\n\n' + narrative['conclusion'] + '\n\n'
    section += '81份历史观察导入后执行48提议；首个控制精确复算，全部达标实现去重后登记与交接。'
    section += '[源账户、完整搜索与核验](experiments/EX040_20261110/report.md)及[额度](experiments/EX040_20261110/others/budget.json)均留证。'
    section += '原C0135/C0224阶段四失败交付保留。\n\n## 下一步\n\n' + narrative['next'] + '\n\n正式回放已通过DFLS' + assumptions
    handoff.write_bytes((top + before + section).encode())
    save(WORK / 'others/closing_overview.json', get_research_overview(repo, batch).to_dict())
    print('ROUND_FOUR_PUBLISHED', len(entries), result.receipt.reference.content_sha256, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'publish'))
    args = parser.parse_args()
    {'prepare': prepare, 'publish': publish}[args.action]()
