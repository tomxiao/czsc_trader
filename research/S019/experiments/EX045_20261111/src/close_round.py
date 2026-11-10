"""Publish one completed mechanism round and settle its authorized budget once."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, create_research_context, publish_evidence,
    validate_experiment, update_research_intent, ResearchIntentUpdate)
from dataflows import ProviderConfig
from strategy_runtime import equity_source_hash

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())

def read(path):
    return json.loads(path.read_bytes())

def save(path, value):
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

def checked_path(base, relative):
    path = (base / relative).resolve()
    assert path.is_relative_to(base.resolve()), relative
    return path

def render_blocks(lines):
    blocks = []
    for line in lines:
        if line.startswith('|') and blocks and blocks[-1].startswith('|'):
            blocks[-1] += '\n'+line
        else:
            blocks.append(line)
    return '\n\n'.join(blocks)+'\n'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--experiment',required=True,type=Path)
    parser.add_argument('action',choices=('prepare','publish'))
    args=parser.parse_args()
    work=args.experiment.resolve()
    assert work.parent==ROOT/'research/S019/experiments'
    assert not (work/'report_ref.json').exists(), 'Published report exists; inspect publication and budget before any recovery'
    assert not (work/'others/publication.json').exists(), 'Publication receipt exists; inspect settlement rather than republishing'
    adaptive = (work/'others/close_inputs.json').exists()
    if adaptive:
        from family_close_inputs import load
        results, spec, _ = load(work)
    else:
        results=read(work/'others/results.json')
        spec=read(work/'protocols/specs.json')
    interpretation=read(work/'others/interpretation.json')
    manifest=read(work/'protocols/run_manifest.json')
    audit=read(work/'others/semantic_audit.json')
    audit_manifest=read(work/'others/audit_manifest.json')
    attempts=read(work/'others/attempts.json')
    predecessor_path = work/'protocols/technical_predecessor.json'
    technical_predecessor = read(predecessor_path) if predecessor_path.exists() else None
    if technical_predecessor is not None:
        previous_work = ROOT/'research/S019/experiments'/technical_predecessor['experiment']
        previous_results = read(checked_path(ROOT,technical_predecessor['results']))
        previous_publication = read(previous_work/'others/failure_publication.json')
        assert not previous_results['accounts'] and technical_predecessor['valid_accounts'] == 0
        assert technical_predecessor['debited_rounds'] == previous_publication['rounds_debited'] == 0
        assert previous_publication['outcome'] == 'FAILED' and previous_publication['validation']['status'] == 'PASS'
        assert technical_predecessor['unknown_tasks'] == sum(a['execution_stats']['unknown']
            for a in read(previous_work/'others/attempts.json'))
    assert results['status']=='COMPLETE' and len(results['accounts'])==len(spec['specs'])
    assert results['manifest']==manifest
    assert manifest['plan_sha256']==sha256((work/'protocols/plan.md').read_bytes()).hexdigest()
    if not adaptive:
        assert manifest['specs_sha256']==digest(work/'protocols/specs.json')
        assert manifest['runner_sha256']==digest(work/'src/batch_runner.py')
    for name, expected in manifest['dependencies'].items():
        assert digest(checked_path(ROOT,name)) == expected
    recovery = work/'protocols/technical_recovery_amendment.json'
    if recovery.exists():
        amendment = read(recovery)
        for name, expected in amendment['preserved_originals'].items():
            assert digest(checked_path(work,name)) == expected
        original = read(work/'protocols/run_manifest_v1.json')
        assert original['runner_sha256'] == amendment['old_runner_sha256']
        assert manifest['runner_sha256'] == amendment['new_runner_sha256']
        assert {k:v for k,v in original.items() if k != 'runner_sha256'} == {
            k:v for k,v in manifest.items() if k != 'runner_sha256'}
        assert amendment['formal_published_account_evidence_modified'] is False
        assert amendment['rounds_debited_by_this_technical_revision'] == 0
    assert audit['audit_source_sha256']==sha256((work/'src/semantic_audit.py').read_bytes()).hexdigest()
    assert audit['manifest_sha256']==sha256((work/'others/audit_manifest.json').read_bytes()).hexdigest()
    assert audit['results'] and all(r['business_rules']==r['signal_availability']==r['holding_and_position_feedback']=='PASS' for r in audit['results'])
    assert len(audit['results']) == len(audit_manifest)
    if adaptive:
        selection = read(work/'others/audit_selection.json')
        assert selection['summary_sha256'] == digest(work/'others/summary.json')
        assert selection['dynamic_specs_sha256'] == digest(work/'others/candidate_specs.json')
        assert selection['search_sha256'] == manifest['search_sha256']
        assert selection['manifest_sha256'] == digest(work/'others/audit_manifest.json')
        assert selection['selection_source_sha256'] == digest(work/'src/prepare_audit.py')
        assert selection['adapter_source_sha256'] == audit['adapter_source_sha256'] == digest(work/'src/family_close_inputs.py')
        assert selection['selected_accounts'] == len(audit['results'])
        assert selection['selected_decisions_expected'] == sum(r['decisions'] for r in audit['results'])

    selected = {item['account']:item for item in audit_manifest}
    assert len(selected) == len(audit_manifest)
    accounted = {}
    assert set(results['accounts']) == {s['label'] for s in spec['specs']}
    for s in spec['specs']:
        row = results['accounts'][s['label']]
        definition_path = checked_path(work,s.get("definition_path",f"others/{s['label']}_definition.json"))
        account_file = checked_path(work,s.get("account_path",f"others/{s['label']}_account.json"))
        definition = read(definition_path)
        ref = read(account_file)
        assert row['label'] == s['label'] and row['parameters'] == s['parameters']
        assert row['definition'] == definition and row['account_ref'] == ref
        assert json.loads(definition['parameters_json']) == s['parameters']
        if 'state_schema' in spec:
            assert definition['state_schema'] == spec['state_schema']
            assert read(work/'others/state_schema_preflight.json')['status'] == 'PASS'
        assert definition['source_sha256'] == manifest['source_sha256'] == equity_source_hash(
            work/'src',tuple(definition['source_files']))
        evidence = d.EvidenceRef.from_dict(ref)
        assert digest(evidence.resolve(ROOT)) == evidence.sha256
        header = read(evidence.resolve(ROOT))
        assert header['request']['candidate_definition'] == definition
        assert header['request']['content_sha256'] == row['content_hash']
        account_path = account_file.relative_to(ROOT).as_posix()
        accounted[account_path] = (row,definition)
    assert set(selected).issubset(accounted)
    assert {r['account'] for r in audit['results']} == set(selected)
    for entry in audit['results']:
        assert all(entry[k] == v for k,v in selected[entry['account']].items())
        row, definition = accounted[entry['account']]
        assert read(checked_path(ROOT,entry['definition'])) == definition
        assert entry['account_sha256'] == row['account_ref']['sha256']
        assert entry['strategy_source_sha256'] == definition['source_sha256']
        assert all(entry[key] == 'PASS' for key in (
            'cash_longonly_integer','order_fill_status','serialized_targets_exact','recorded_exit_facts'))
        assert entry['maximum_target_rounding_error'] <= 5.01e-11
    for s in spec['specs']:
        if s.get('control_account') and not adaptive:
            parity = read(work/f"others/{s['label']}_parity.json")
            control = manifest['controls'][s['label']]
            assert parity['status']=='PASS' and parity['new_account'] == results['accounts'][s['label']]['account_ref']
            assert parity['control'] == control['path'] == s['control_account']
            assert read(checked_path(ROOT,s['control_account'])) == control['reference']
            assert digest(checked_path(ROOT,s['control_account'])) == control['reference_file_sha256']
            assert parity['daily_and_bar_economic_paths'] == parity['targets_and_fills'] == 'EXACT_EQUAL'
    if adaptive:
        for control in manifest['controls'].values():
            assert read(checked_path(ROOT,control['path'])) == control['reference']
            assert digest(checked_path(ROOT,control['path'])) == control['file_sha256']
    assert attempts and all(a['status'] != 'RUNNING' for a in attempts)
    assert results['replay_statistics_complete'] == all(a['statistics_complete'] for a in attempts)
    for key in ('candidate_runs','benchmark_runs'):
        assert results['workload'][key] == sum(a['equity_statistics'][key] for a in attempts)
    unknown_tasks = sum(a.get('execution_stats',{}).get('unknown',0) for a in attempts)
    repo=RepositoryContext.discover(ROOT)
    batch=d.ResearchBatchRef('S019')
    exp=d.ExperimentRef('S019',work.name)
    intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
    round_number=spec['round_budget']['total_round']
    old_budget=intent['joint_search_budget']
    assert spec['round_budget']['allocated_rounds'] == 6
    assert 1 <= spec['round_budget']['round_index'] <= 6
    assert round_number == 4+spec['round_budget']['round_index']
    assert spec['round_budget']['remaining_after_completion'] == 10-round_number
    assert old_budget['authorized_rounds'] == 10 and old_budget['remaining_rounds'] == 11-round_number
    assert old_budget['used_rounds']==round_number-1
    assert [r['round'] for r in old_budget['rounds']] == list(range(1,round_number))
    assert all(r['experiment'] != work.name for r in old_budget['rounds'])
    assert intent['active_experiment']['experiment_id'] == work.name
    assert intent['active_round_budget']['round'] == round_number
    accounts=list(results['accounts'].values())
    unique_accounts = list({r['account_ref']['sha256']:r for r in reversed(accounts)}.values())
    eligible=sorted([r for r in unique_accounts if r['candidate']['eligible']],key=lambda r:(-r['candidate']['nar'],r['candidate_id']))
    row={'round':round_number,'experiment':work.name,'stage':'STAGE_TWO',
        'mechanism_round':spec['round_budget']['round_index'],
        'design_configurations':len(accounts),'structural_accounts':sum(r['role']!='CONTROL' for r in unique_accounts),
        'control_replays':sum(r['role']=='CONTROL' for r in unique_accounts),
        'candidate_accounts':results['workload']['candidate_runs'],
        'benchmark_accounts':results['workload']['benchmark_runs'],
        'replay_statistics_complete':results['replay_statistics_complete'],
        'unknown_compute_tasks':unknown_tasks,
        'eligible_ids':[r['candidate_id'] for r in eligible],
        'protocol_sha256':manifest['plan_sha256']}
    if adaptive:
        row.update(proposed_configurations=len(accounts),distinct_accounts=len(unique_accounts),
            exact_aliases=results['aliases'],search_protocol_sha256=manifest['search_sha256'])
    if technical_predecessor is not None:
        row['preceding_technical_failure'] = {k:technical_predecessor[k]
            for k in ('experiment','valid_accounts','unknown_tasks','debited_rounds')}
    budget={**old_budget,'used_rounds':round_number,'remaining_rounds':10-round_number,
        'candidate_accounts':old_budget['candidate_accounts']+row['candidate_accounts'],
        'benchmark_accounts':old_budget['benchmark_accounts']+row['benchmark_accounts'],
        'structural_design_configurations':old_budget.get('structural_design_configurations',0)+len(accounts),
        'rounds':[*old_budget['rounds'],row],
        'current_round_replay_statistics_complete':results['replay_statistics_complete'],
        'all_round_replay_statistics_complete':all(r.get('replay_statistics_complete',True) for r in [*old_budget['rounds'],row]),
        'unknown_compute_tasks':sum(r.get('unknown_compute_tasks',0) for r in [*old_budget['rounds'],row]),
        'counting_note':'Prior optimization proposal counts retained. New mechanism configurations and economic control replays recorded separately; unknown technical tasks are not inferred as successful replays.'}
    if args.action=='prepare':
        save(work/'others/budget.json',budget)
        lines=['# '+interpretation['title'],'Status: COMPLETE；RSCH；阶段二机制研究。',
            interpretation['conclusion'],
            '原中心NAR≥55%、Calmar≥5、日末MDD≤25%且≤同费用买持80%；60日闭合中位数≥6，至少3笔窗口覆盖≥90%。正式邻域80%及费用压力条件保持。',
            '## 尝试与收获',*interpretation['findings'],
            ('方案及实际参数见[事前方案](protocols/plan.md)、[冻结搜索协议](protocols/search.json)、[实际提议](others/candidate_specs.json)。' if adaptive else '方案及实际参数见[事前方案](protocols/plan.md)、[完整配置](protocols/specs.json)。'),
            '## 完整账户成绩',
            '|配置|候选|NAR|MDD|Calmar|60日闭合中位|至少3笔覆盖|中心六门|',
            '|---|---|---:|---:|---:|---:|---:|---|']
        for r in accounts:
            m=r['candidate']
            lines.append(f"|{r['label']}|{r['candidate_id']}|{m['nar']:.4%}|{m['drawdown']:.4%}|{m['calmar']:.6f}|{m['frequency_median']:g}|{m['frequency_coverage']:.4%}|{'通过' if m['eligible'] else '未通过'}|")
        lines += [('全部原始定义、账户引用与逐门结果见[搜索结果](others/summary.json)及[执行汇总](others/execution.json)。' if adaptive else '全部原始定义、账户引用与逐门结果见[结果](others/results.json)。'),
            '## 验证、样本及资源',
            f"完整完成{len(accounts)}个配置；已记录成功策略回放{row['candidate_accounts']}、买持回放{row['benchmark_accounts']}。逐段统计完整性为{results['replay_statistics_complete']}，历史未知计算任务{unknown_tasks}项另列保留，成功回放计数仅取已记录值。实际状态与失败/未知任务保留于[执行记录](others/attempts.json)。累计运行记录{results['elapsed_seconds']/60:.2f}分钟。",
            f"公共TDR执行会话及检查点，{manifest['resources']['workers']}账户进程、每进程{manifest['resources']['native_threads']}原生线程；完整参数、输入、源码与资源身份见[运行清单](protocols/run_manifest.json)。",
            f"适用的控制账户完整经济parity均PASS。独立业务审计覆盖{len(audit['results'])}账户、{sum(r['decisions'] for r in audit['results']):,}条决定，全部PASS，见[业务审计](others/semantic_audit.json)。",
            '2021预热，2022-01-03至2026-10-30已见开发历史；MU/SOXX、HFQ整数单位、10万美元、每侧0.1%费用、原限价买入/市价卖出及历史数据假设保持。结构对照所得认识仍属于开发证据，完整新原型稳健性与独立前瞻检验另行安排。',
            '## 下一步',interpretation['next_action'],
            f"本轮计入既有10轮额度的第{round_number}轮，此次六轮授权第{spec['round_budget']['round_index']}轮，完成后剩{10-round_number}轮。[预算](others/budget.json)。"]
        if adaptive:
            lines += [f"本轮{len(accounts)}次提议对应{len(unique_accounts)}个唯一账户，精确复用{results['aliases']}次；每族{manifest['family_trial_budget']}次提议，{manifest['startup_trials']}启动观察，各族独立约束TPE、目标原始NAR。存储：{manifest['storage']}。四观察反馈屏障、资源分波及原始ask/result/tell见运行清单和others/trials。"]
        if technical_predecessor is not None:
            lines += [f"前置技术失败实验{technical_predecessor['experiment']}保留{technical_predecessor['unknown_tasks']}项UNKNOWN、有效账户0、扣减研究轮0；其技术工作量与本轮成功账户分列，见[技术承接](protocols/technical_predecessor.json)及[失败报告](../{technical_predecessor['experiment']}/report.md)。"]
        (work/'report.md').write_bytes(render_blocks(lines).encode())
        print('ROUND_REPORT_READY',round_number,len(accounts),len(eligible),flush=True)
        return
    assert read(work/'others/budget.json')==budget
    assert not (work/'report_ref.json').exists(),'Inspect actual publication before retry'
    started=perf_counter()
    ctx=create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    refs=[d.EvidenceRef.from_dict(r['account_ref']) for r in accounts]
    for s in spec['specs']:
        if s.get('control_account'):
            refs.append(d.EvidenceRef.from_dict(read(ROOT/s['control_account'])))
    paths=[*sorted((work/'src').glob('*.py')),*sorted((work/'protocols').glob('*')),
        *sorted((work/'others').rglob('*.json')),*sorted((work/'others').rglob('*.md')),*sorted((work/'others').rglob('*.png'))]
    paths += [checked_path(ROOT,name) for name in manifest['dependencies']]
    for i,path in enumerate(dict.fromkeys(paths)):
        if not path.is_file() or path.suffix not in {'.py','.json','.md','.png'} or path.name=='publication.json':
            continue
        ext=path.suffix[1:]
        refs.append(publish_evidence(ctx,d.MaterialEvidenceWrite(exp,f'mechanism-{i:04}-{sha256(path.relative_to(ROOT).as_posix().encode()).hexdigest()[:12]}',path.read_bytes(),
            {'py':'text/x-python','json':'application/json','md':'text/markdown','png':'image/png'}[ext],ext)))
    report=publish_evidence(ctx,d.ExperimentReportWrite(exp,sha256((work/'report.md').read_bytes()).hexdigest(),
        d.ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(refs))))
    validation=validate_experiment(repo,d.ExperimentValidationRequest(exp,d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    save(work/'others/publication.json',{'report':report.to_dict(),'validation':validation.to_dict(),
        'seconds':perf_counter()-started,'new_accounts_during_publication':0})
    # Recheck immediately before the single budget mutation. Published evidence
    # stays available for explicit inspection if this check or mutation fails.
    intent=read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['joint_search_budget'] == old_budget
    assert intent['active_experiment']['experiment_id'] == work.name
    intent.update(stage='STAGE_TWO',joint_search_budget=budget,mechanism_research_status='ROUND_COMPLETE',
        latest_experiment_report=report.to_dict(),next_action=interpretation['next_action'])
    intent.pop('active_round_budget',None)
    intent.pop('active_experiment',None)
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=intent),actor='RSCH',
        reason=f'完成已批准的机制研究第{spec["round_budget"]["round_index"]}轮，实际额度结算一次。')
    settled=read(ROOT/'research/registrations/S019/family.json')['research_intent']['joint_search_budget']
    assert settled == budget
    save(work/'others/budget_settlement.json',{'status':'SETTLED_ONCE','experiment':work.name,
        'used_before':old_budget['used_rounds'],'used_after':round_number,'remaining_after':10-round_number,
        'budget_sha256':digest(work/'others/budget.json'),'report':report.to_dict()})
    print('ROUND_PUBLISHED',round_number,'remaining',10-round_number,report.sha256,flush=True)

if __name__=='__main__':
    main()
