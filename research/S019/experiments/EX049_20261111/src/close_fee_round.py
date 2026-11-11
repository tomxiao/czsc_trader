"""Close a paired fee-development round with explicit pressure criteria."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from czsc_trader import research_tools as d
from czsc_trader.application import (RepositoryContext, ResearchIntentUpdate, create_research_context,
    publish_evidence, update_research_intent, validate_experiment)
from czsc_trader.research_tools.equity_replay import materialize_equity
from dataflows import ProviderConfig
from strategy_runtime import equity_source_hash
from strategy_runtime.equity import equity_hash

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
sys.path.insert(0, str(ROOT/'research/S019/experiments/EX013_20261110/src'))
from runner import metrics  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def checked_path(root, relative):
    path = (root/relative).resolve()
    assert path.is_relative_to(root.resolve())
    return path


def pressure_gates(candidate, benchmark):
    relative = candidate['drawdown'] < benchmark['drawdown'] if benchmark['drawdown'] > 0 else candidate['drawdown'] == 0
    return {'nar': candidate['nar'] >= .5,
            'calmar': candidate['calmar'] is not None and candidate['calmar'] >= 4.5,
            'absolute_dd': candidate['drawdown'] <= .25, 'relative_dd': relative}


def account_payload(reference):
    ref = d.EvidenceRef.from_dict(reference)
    path = ref.resolve(ROOT)
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == ref.sha256

    def resolve(item):
        content = path.with_name(item['sha256']+'.json').read_bytes()
        assert sha256(content).hexdigest() == item['sha256']
        return content

    return ref, json.loads(raw), materialize_equity(raw, resolve).payload


def verify_account(row, fee_rate, pressure):
    ref, header, payload = account_payload(row['account_ref'])
    request = payload['request']
    assert request['candidate_id'] == row['candidate_id']
    assert request['candidate_definition'] == row['definition']
    assert request['content_sha256'] == row['content_hash']
    assert header['request_hash'] == row['request_sha256']
    assert json.loads(row['definition']['parameters_json']) == row['parameters']
    assert request['fee_rate'] == fee_rate and request['window_id'] == 'FULL'
    assert request['initial_cash'] == 100000. and request['drawdown_basis'] == 'SESSION_CLOSE'
    source = checked_path(ROOT, row['source_root'])
    assert equity_source_hash(source,tuple(row['definition']['source_files'])) == row['definition']['source_sha256']
    run, benchmark = payload['runs']['candidate'], payload['runs']['buy_hold']
    measured = metrics(run, benchmark['metrics']['daily_max_drawdown'])
    buy_hold = metrics(benchmark, benchmark['metrics']['daily_max_drawdown'])
    if pressure:
        assert fee_rate == .002 and request['scenario_id'] == request['measurement_tier'] == 'STRESS'
        measured = {key: value for key, value in measured.items() if key not in ('gates','eligible')}
        assert 'gates' not in row['candidate'] and 'eligible' not in row['candidate']
        expected = pressure_gates(measured, buy_hold)
        assert expected == row['pressure_gates'] and all(expected.values()) == row['pressure_eligible']
        assert row['frequency_diagnostic'] == {'median':measured['frequency_median'],
            'coverage':measured['frequency_coverage'],'median_ge_6':measured['frequency_median'] >= 6,
            'coverage_ge_90pct':measured['frequency_coverage'] >= .9,'used_for_pressure_acceptance':False}
    else:
        assert fee_rate == .001 and request['scenario_id'] == 'STANDARD' and request['measurement_tier'] == 'FORMAL'
    assert measured == row['candidate'] and buy_hold == row['benchmark']
    assert equity_hash(payload['audit_inputs']) == request['audit_inputs_sha256']
    return ref, request, payload['audit_inputs']


def verify_audit(work, pressure_rows):
    manifest_path = work/'others/audit_manifest.json'
    audit_path = work/'others/semantic_audit.json'
    manifest, audit = read(manifest_path), read(audit_path)
    assert audit['manifest_sha256'] == digest(manifest_path)
    assert audit['audit_source_sha256'] == digest(work/'src/semantic_audit.py')
    assert len(manifest) == len(audit['results']) == len(pressure_rows)
    expected = {f'others/{label}_stress_account.json': row for label, row in pressure_rows.items()}
    items = {item['account']: item for item in manifest}
    assert len(items) == len(manifest)
    assert {checked_path(ROOT, path).relative_to(work).as_posix() for path in items} == set(expected)
    assert {item['account'] for item in audit['results']} == set(items)
    for result in audit['results']:
        item = items[result['account']]
        assert all(result[key] == value for key, value in item.items())
        relative = checked_path(ROOT, result['account']).relative_to(work).as_posix()
        row = expected[relative]
        assert result['account_sha256'] == row['account_ref']['sha256']
        assert result['strategy_source_sha256'] == row['definition']['source_sha256']
        assert read(checked_path(ROOT, item['definition'])) == row['definition']
        assert result['decisions'] == 15702
        for field in ('business_rules','signal_availability','holding_and_position_feedback',
                      'cash_longonly_integer','order_fill_status','serialized_targets_exact','recorded_exit_facts'):
            assert result[field] == 'PASS'
        assert result['maximum_target_rounding_error'] <= 5.01e-11
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('action',choices=('prepare','publish'))
    args = parser.parse_args()
    work = args.experiment.resolve()
    assert work.parent == ROOT/'research/S019/experiments'
    assert not (work/'report_ref.json').exists() and not (work/'others/publication.json').exists(), 'Inspect any existing publication before recovery'
    protocol = read(work/'protocols/fee_pairs.json')
    results = read(work/'others/results.json')
    manifest = read(work/'protocols/run_manifest.json')
    attempts = read(work/'others/attempts.json')
    interpretation = read(work/'others/interpretation.json')
    assert results['status'] == 'COMPLETE' and results['manifest'] == manifest
    assert protocol['standard_fee_rate'] == .001 and protocol['pressure_fee_rate'] == .002
    assert manifest['fee_pairs_sha256'] == digest(work/'protocols/fee_pairs.json')
    assert manifest['plan_sha256'] == digest(work/'protocols/plan.md')
    assert manifest['specs_sha256'] == digest(work/'protocols/specs.json')
    assert manifest['runner_sha256'] == digest(work/'src/fee_runner.py')
    assert manifest['source_sha256'] == equity_source_hash(work/'src',('strategy.py',))
    for name, expected in manifest['dependencies'].items():
        assert digest(checked_path(ROOT,name)) == expected
    pairs = {pair['label']: pair for pair in protocol['pairs']}
    standard, pressure = results['accounts'], results['pressure_accounts']
    assert len(pairs) == len(protocol['pairs']) == 7
    assert set(pairs) == set(standard) == set(pressure)
    assert len({row['candidate_id'] for row in standard.values()}) == len(pairs)
    prepared_list = read(work/'protocols/prepared_request_manifest.json')
    prepared = {item['label']:item for item in prepared_list}
    assert len(prepared) == len(prepared_list) == len(pairs) and set(prepared) == set(pairs)
    assert len({item['input_snapshot_sha256'] for item in prepared.values()}) == 1
    assert len({item['standard_benchmark_identity'] for item in prepared.values()}) == 1
    assert len({item['pressure_benchmark_identity'] for item in prepared.values()}) == 1
    assert {item['standard_benchmark_identity'] for item in prepared.values()}.isdisjoint({item['pressure_benchmark_identity'] for item in prepared.values()})
    comparisons, references = [], []
    for label, pair in pairs.items():
        baseline, stress = standard[label], pressure[label]
        assert baseline['role'] == 'REUSED_EVIDENCE' and stress['role'] == 'PRESSURE_DIAGNOSTIC'
        assert baseline['candidate_id'] == stress['candidate_id'] == pair['candidate_id']
        assert baseline['definition'] == stress['definition'] and baseline['parameters'] == stress['parameters']
        assert baseline['content_hash'] == stress['content_hash']
        assert read(checked_path(ROOT,pair['standard_account'])) == baseline['account_ref']
        assert read(work/f'others/{label}_account.json') == baseline['account_ref']
        assert read(work/f'others/{label}_stress_account.json') == stress['account_ref']
        assert read(work/f'others/{label}_definition.json') == baseline['definition']
        base_ref, base_request, base_inputs = verify_account(baseline,.001,False)
        stress_ref, stress_request, stress_inputs = verify_account(stress,.002,True)
        assert stress_inputs == {**base_inputs,'fee_rate':.002}
        allowed = {'experiment','fee_rate','scenario_id','measurement_tier','audit_inputs_sha256'}
        assert {key:value for key,value in base_request.items() if key not in allowed} == {
            key:value for key,value in stress_request.items() if key not in allowed}
        references.extend((base_ref,stress_ref))
        contract_path = work/f'others/{label}_fee_pair_contract.json'
        contract = read(contract_path)
        assert contract['status'] == 'PASS' and contract['label'] == label and contract['candidate_id'] == baseline['candidate_id']
        assert contract['standard_account_ref'] == base_ref.to_dict() == stress['standard_account_ref']
        assert contract['source_standard_request_sha256'] == baseline['request_sha256']
        assert contract['standard_request_sha256'] == prepared[label]['standard_request_sha256'] == baseline['prepared_request_sha256']
        assert contract['pressure_request_sha256'] == prepared[label]['pressure_request_sha256'] == stress['request_sha256']
        assert contract['standard_request_sha256'] == equity_hash(contract['standard_request'])
        assert contract['pressure_request_sha256'] == equity_hash(contract['pressure_request'])
        assert contract['pressure_request'] == stress_request
        assert {key:value for key,value in contract['standard_request'].items() if key != 'experiment'} == {
            key:value for key,value in base_request.items() if key != 'experiment'}
        assert contract['standard_request']['experiment'] == contract['pressure_request']['experiment'] == {
            'strategy_id':'S019','experiment_id':work.name}
        assert contract['standard_audit_inputs_sha256'] == equity_hash(base_inputs)
        assert contract['pressure_audit_inputs_sha256'] == equity_hash(stress_inputs)
        assert contract['allowed_business_changes'] == ['experiment','fee_rate','scenario_id','measurement_tier']
        comparisons.append({'label':label,'candidate_id':baseline['candidate_id'],'content_hash':baseline['content_hash'],
            'standard':baseline['candidate'],'pressure':stress['candidate'],'pressure_buy_hold':stress['benchmark'],
            'pressure_gates':stress['pressure_gates'],'pressure_eligible':stress['pressure_eligible'],
            'frequency_diagnostic':stress['frequency_diagnostic'],
            'standard_account':base_ref.to_dict(),'pressure_account':stress_ref.to_dict(),
            'pair_contract_sha256':digest(contract_path),
            'pressure_minus_standard':{key:stress['candidate'][key]-baseline['candidate'][key]
                if stress['candidate'][key] is not None and baseline['candidate'][key] is not None else None
                for key in ('nar','drawdown','calmar','fees')}})
        print('FEE_ACCOUNT_PAIR_VERIFIED',label,flush=True)
    audit = verify_audit(work, pressure)
    assert attempts and all(attempt['status'] != 'RUNNING' for attempt in attempts)
    assert results['replay_statistics_complete'] == all(attempt['statistics_complete'] for attempt in attempts)
    for key in ('candidate_runs','benchmark_runs'):
        assert results['workload'][key] == sum(attempt['equity_statistics'][key] for attempt in attempts)
    assert results['workload']['reused_accounts'] == len(standard)
    assert results['workload']['candidate_runs'] >= len(pressure) and results['workload']['benchmark_runs'] >= 1
    unknown = sum(attempt.get('execution_stats',{}).get('unknown',0) for attempt in attempts)
    repo = RepositoryContext.discover(ROOT)
    batch = d.ResearchBatchRef('S019')
    exp = d.ExperimentRef('S019',work.name)
    intent_path = ROOT/'research/registrations/S019/family.json'
    intent = read(intent_path)['research_intent']
    assert intent['stage'] == 'STAGE_THREE'
    before, historical = intent['continuous_stage3_budget'], intent['joint_search_budget']
    assert before['authorization_decision'] == 'S019-STAGE3-CONTINUOUS-20261111'
    number = protocol['round_budget']['round_index']
    assert protocol['round_budget'] == {'allocated_rounds':10,'round_index':number,'total_round':number,'remaining_after_completion':10-number}
    assert 1 <= number <= 10 and before['authorized_rounds'] == 10
    assert before['used_rounds'] == number-1 and before['remaining_rounds'] == 11-number
    assert [record['round'] for record in before['rounds']] == list(range(1,number))
    assert all(record['experiment'] != work.name for record in before['rounds'])
    assert intent['active_experiment']['experiment_id'] == work.name and intent['active_round_budget']['round'] == number
    eligible = sorted((row for row in standard.values() if row['candidate']['eligible']),key=lambda row:(-row['candidate']['nar'],row['candidate_id']))
    record = {'round':number,'experiment':work.name,'stage':'STAGE_THREE','optimization_round':number,
        'research_kind':'PAIRED_FEE_DEVELOPMENT_DIAGNOSTIC','design_configurations':len(pairs),
        'paired_configurations':len(pairs),'scenario_accounts':2*len(pairs),'new_parameter_configurations':0,
        'structural_accounts':0,'control_replays':0,'reused_evidence_accounts':len(standard),
        'candidate_accounts':results['workload']['candidate_runs'],'benchmark_accounts':results['workload']['benchmark_runs'],
        'replay_statistics_complete':results['replay_statistics_complete'],'unknown_compute_tasks':unknown,
        'eligible_ids':[row['candidate_id'] for row in eligible],
        'pressure_pass_ids':[row['candidate_id'] for row in pressure.values() if row['pressure_eligible']],
        'protocol_sha256':manifest['plan_sha256'],'fee_pairs_sha256':manifest['fee_pairs_sha256']}
    budget = {**before,'used_rounds':number,'remaining_rounds':10-number,
        'candidate_accounts':before['candidate_accounts']+record['candidate_accounts'],
        'benchmark_accounts':before['benchmark_accounts']+record['benchmark_accounts'],
        'reused_evidence_accounts':sum(row.get('reused_evidence_accounts',0) for row in [*before['rounds'],record]),
        'fee_diagnostic_pairs':before.get('fee_diagnostic_pairs',0)+len(pairs),
        'rounds':[*before['rounds'],record],
        'current_round_replay_statistics_complete':results['replay_statistics_complete'],
        'all_round_replay_statistics_complete':all(row.get('replay_statistics_complete',True) for row in [*before['rounds'],record]),
        'unknown_compute_tasks':sum(row.get('unknown_compute_tasks',0) for row in [*before['rounds'],record])}
    review = {'status':'COMPLETE','mode':'DEVELOPMENT_DIAGNOSTIC','formal_stage_four_acceptance':False,
        'criteria':{'pressure_fee_rate':.002,'nar_min':.5,'calmar_min':4.5,'mdd_max':.25,
            'relative_mdd':'Strictly below same-fee buy-hold MDD; if benchmark MDD is zero, candidate MDD must equal zero.',
            'frequency_participates_in_pressure_acceptance':False},
        'pairs':comparisons,'standard_six_gate_pass_count':len(eligible),
        'pressure_pass_count':sum(row['pressure_eligible'] for row in pressure.values()),
        'denominator':len(pairs),'audit_accounts':len(audit['results']),
        'audit_decisions':sum(row['decisions'] for row in audit['results']),
        'results_sha256':digest(work/'others/results.json'),'audit_sha256':digest(work/'others/semantic_audit.json'),
        'source_sha256':digest(Path(__file__))}
    if args.action == 'prepare':
        save(work/'others/budget.json',budget)
        save(work/'others/fee_gate_review.json',review)
        lines = ['# '+interpretation['title'],'','Status: COMPLETE；RSCH；阶段三费用开发诊断。','',interpretation['conclusion'],'',
            '## 尝试与收获','',*interpretation['findings'],'',
            '标准场景每侧0.1%，原中心NAR≥55%、Calmar≥5及原MDD/双频率目标保持。压力场景每侧0.2%，使用原费用门NAR≥50%、Calmar≥4.5、MDD≤25%且低于同费买持；买持MDD为零时策略须为零。频率在压力场景单列诊断。','',
            '## 标准与压力配对成绩','',
            '|候选|标准NAR|标准MDD|标准Calmar|标准六门|压力NAR|压力MDD|压力Calmar|费用门|',
            '|---|---:|---:|---:|---|---:|---:|---:|---|']
        for item in comparisons:
            a, b = item['standard'], item['pressure']
            lines.append(f"|{item['candidate_id']}|{a['nar']:.4%}|{a['drawdown']:.4%}|{a['calmar']}|{a['eligible']}|{b['nar']:.4%}|{b['drawdown']:.4%}|{b['calmar']}|{item['pressure_eligible']}|")
        lines += ['', '## 压力频率与费用','', '|候选|压力60日闭合中位|压力至少3笔覆盖|标准费用|压力费用|', '|---|---:|---:|---:|---:|']
        for item in comparisons:
            a, b = item['standard'], item['pressure']
            lines.append(f"|{item['candidate_id']}|{b['frequency_median']}|{b['frequency_coverage']:.4%}|{a['fees']:.2f}|{b['fees']:.2f}|")
        lines += ['', '## 证据与额度','',
            f"复用{len(standard)}份标准账户；新完成{record['candidate_accounts']}次压力策略回放、{record['benchmark_accounts']}次同费买持回放，无新参数。压力费用门通过{review['pressure_pass_count']}/{len(pairs)}。实际回放统计完整性{results['replay_statistics_complete']}，未知任务{unknown}。",
            f"全部{len(audit['results'])}份压力账户、{review['audit_decisions']:,}条决定独立业务重建PASS。公共账户复验绑定参数、源码、费用、原标准六门及独立压力四门。",
            '样本继续为2021预热、2022-01-03至2026-10-30已见历史；期末未平仓纳入账户收益与MDD。该少数代表配对支持阶段三研究决策，完整阶段四仍按用户批准及完整协议执行。',
            f"新10轮授权已用{number}轮、剩余{10-number}轮，旧joint_search_budget保留。[预算](others/budget.json)。",
            '[事前费用设计](protocols/fee_pairs.json) · [全部账户结果](others/results.json) · [费用门核对](others/fee_gate_review.json) · [独立业务审计](others/semantic_audit.json)','',
            '## 下一步','',interpretation['next_action']]
        (work/'report.md').write_bytes(('\n'.join(lines)+'\n').encode())
        print('FEE_ROUND_REPORT_READY',number,review['pressure_pass_count'],len(pairs),flush=True)
        return
    assert read(work/'others/budget.json') == budget and read(work/'others/fee_gate_review.json') == review
    context = create_research_context(repo,batch,providers=ProviderConfig(bindings={},equity_bindings={}))
    paths = [*sorted((work/'src').glob('*.py')),*sorted((work/'protocols').glob('*')),
             *sorted((work/'others').rglob('*.json')),*sorted((work/'others').rglob('*.md')),
             *(checked_path(ROOT,name) for name in manifest['dependencies'])]
    for index, path in enumerate(dict.fromkeys(paths)):
        if not path.is_file() or path.suffix not in ('.py','.json','.md') or path.name == 'publication.json':
            continue
        ext = path.suffix[1:]
        references.append(publish_evidence(context,d.MaterialEvidenceWrite(exp,f'fee-diagnostic-{index:04}-{sha256(path.relative_to(ROOT).as_posix().encode()).hexdigest()[:12]}',
            path.read_bytes(),{'py':'text/x-python','json':'application/json','md':'text/markdown'}[ext],ext)))
    started = perf_counter()
    report = publish_evidence(context,d.ExperimentReportWrite(exp,digest(work/'report.md'),d.ExperimentOutcome.COMPLETED,tuple(dict.fromkeys(references))))
    validation = validate_experiment(repo,d.ExperimentValidationRequest(exp,d.ExperimentValidationScope.REPORT_PUBLICATION))
    assert validation.status is d.ValidationStatus.PASS
    save(work/'others/publication.json',{'report':report.to_dict(),'validation':validation.to_dict(),
        'seconds':perf_counter()-started,'new_accounts_during_publication':0})
    fresh = read(intent_path)['research_intent']
    assert fresh['continuous_stage3_budget'] == before and fresh['joint_search_budget'] == historical
    assert fresh['active_experiment']['experiment_id'] == work.name
    fresh.update(stage='STAGE_THREE',continuous_stage3_budget=budget,continuous_stage3_status='ROUND_COMPLETE',
        latest_experiment_report=report.to_dict(),next_action=interpretation['next_action'])
    fresh.pop('active_experiment',None)
    fresh.pop('active_round_budget',None)
    update_research_intent(repo,batch,ResearchIntentUpdate(research_intent=fresh),actor='RSCH',
        reason=f'完成新授权阶段三第{number}轮配对费用开发诊断；按原费用门独立判断，结算一次并保留旧预算。')
    retained = read(intent_path)['research_intent']
    assert retained['continuous_stage3_budget'] == budget and retained['joint_search_budget'] == historical
    save(work/'others/budget_settlement.json',{'status':'SETTLED_ONCE','experiment':work.name,
        'used_before':before['used_rounds'],'used_after':number,'remaining_after':10-number,
        'budget_sha256':digest(work/'others/budget.json'),'report':report.to_dict()})
    print('FEE_ROUND_PUBLISHED',number,'remaining',10-number,report.sha256,flush=True)


if __name__ == '__main__':
    main()
