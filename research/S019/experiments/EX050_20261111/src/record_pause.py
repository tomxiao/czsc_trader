"""Verify saved evidence and record the user's explicit stage-four pause."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from czsc_trader import research_tools as d
from czsc_trader.application import RepositoryContext, ResearchIntentUpdate, get_research_overview, update_research_intent

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    assert not path.exists(), path
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def main():
    pause = read(WORK/'others/process_pause.json')
    assert pause['verified_processes_terminated'] and pause['completed_batches'] == 3
    results_path, attempts_path = WORK/'others/account_results.json', WORK/'others/account_attempts.json'
    assert sha256(results_path.read_bytes()).hexdigest() == pause['account_results_sha256']
    assert sha256(attempts_path.read_bytes()).hexdigest() == pause['account_attempts_sha256']
    results, attempts = read(results_path), read(attempts_path)
    assert len(results['accounts']) == 189 and len(results['batches']) == 3
    manifest = read(WORK/'protocols/run_manifest.json')
    assert manifest['runner_sha256'] == sha256((WORK/'src/run_accounts.py').read_bytes()).hexdigest()
    prepared = {x['key']:x for x in read(WORK/'protocols/prepared_request_manifest.json')}
    checked = []
    for key, row in results['accounts'].items():
        reference = d.EvidenceRef.from_dict(row['account_ref'])
        header = json.loads(reference.resolve(ROOT).read_bytes())
        assert header['request_hash'] == row['request_sha256']
        assert header['request']['content_sha256'] == row['content_hash']
        assert header['request']['candidate_definition'] == row['definition']
        if row['role'] == 'SELF_CHECK':
            assert prepared[key]['request_sha256'] == row['request_sha256']
            assert read(WORK/f'others/{key}_result.json') == row
            assert read(WORK/f'others/{key}_account.json') == row['account_ref']
        checked.append({'key':key, 'sha256':reference.sha256, 'request_sha256':row['request_sha256']})
    for source, name in ((results_path, 'paused_account_results_attempt1.json'),
                         (attempts_path, 'paused_account_attempts_attempt1.json')):
        target = WORK/'others'/name
        assert not target.exists()
        target.write_bytes(source.read_bytes())
    # Saved account evidence is complete through this boundary. Terminating the
    # process tree does not supply final executor teardown/preparation timings.
    # Keep that statistical limit explicit for future --recover aggregation.
    attempts[-1].update(status='USER_PAUSED_AT_COMMITTED_BATCH', statistics_complete=False,
        pause_evidence='others/process_pause.json',
        statistics_limitation='All 183 completed accounts and the shared benchmark are verified. Executor statistics end at the last committed batch; final process teardown or subsequent preparation is not included.')
    results.update(status='PAUSED', replay_statistics_complete=False,
        pause_evidence='others/process_pause.json',
        pause_completed_parameter_points=183, pause_pending_parameter_points=1515)
    for path, value in ((attempts_path, attempts), (results_path, results)):
        path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())
    resume = '.venv/Scripts/python.exe -B research/S019/experiments/EX050_20261111/src/run_accounts.py --experiment research/S019/experiments/EX050_20261111 --run --recover'
    record = {'status':'PAUSED', 'reason':'USER_REQUEST', 'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'verified_evidence_count':len(checked), 'verified_evidence':checked,
        'completed_parameter_points':183, 'reused_center_and_stress':6,
        'pending_by_candidate':{'C0966':59, 'C1010':728, 'C0909':728},
        'next_point':'C0966_P183', 'remaining_parameter_points':1515,
        'resume_only_after_user_instruction':True, 'resume_command':resume,
        'run_manifest_sha256':sha256((WORK/'protocols/run_manifest.json').read_bytes()).hexdigest(),
        'remaining_optimization_rounds':7, 'optimization_rounds_debited':0,
        'statistics_state':'Bootstrap, temporal/concentration, S018 reference and historical selection analysis complete; final native-panel CI equality waits for full assessment.',
        'pending_pipeline':['run_accounts --run --recover', 'summarize_accounts.py', 'prepare_audit.py',
            'semantic_audit.py with generated manifest', 'assess.py prepare then compute',
            'statistics_finalize.py for exact native CI equality', 'write_report.py', 'assess.py publish', 'close_stage.py'],
        'selfcheck_conclusion':'PENDING_FULL_NEIGHBORHOODS', 'account_evidence_validation':'PASS',
        'execution_statistics_scope':'Verified completed accounts; executor timing coverage is explicitly partial at user pause.'}
    save(WORK/'others/pause_checkpoint.json', record)
    repo, batch = RepositoryContext.discover(ROOT), d.ResearchBatchRef('S019')
    intent = read(ROOT/'research/registrations/S019/family.json')['research_intent']
    assert intent['active_experiment']['experiment_id'] == WORK.name
    assert intent['continuous_stage3_budget']['remaining_rounds'] == 7
    intent.update(stage_four_continuous_status='PAUSED',
        stage_four_continuous_pause={'checkpoint':'research/S019/experiments/EX050_20261111/others/pause_checkpoint.json',
            'completed_neighbors':183, 'remaining_neighbors':1515, 'resume_requires_user_instruction':True},
        next_action='用户要求暂停。已保留3个完整批次、183邻点和6份复用证据；等待用户恢复后以61进程从C0966_P183续跑，剩余7轮优化额度保持。')
    update_research_intent(repo, batch, ResearchIntentUpdate(research_intent=intent), actor='RSCH',
        reason='按用户指令在第三批完整留证后暂停，停止61个工作进程并保留完整恢复检查点。')
    save(WORK/'others/paused_overview.json', get_research_overview(repo, batch).to_dict())
    (WORK/'report.md').write_bytes(('''# S019三候选阶段四：已暂停

Status: PAUSED；按用户指令，在第三批完整留证后暂停。

已完成183/1698个参数邻点，另复用3个中心和3个双倍费用账户，共189份场景证据。主进程和61个工作进程均已停止。C0966剩59点，C1010和C0909各剩728点，合计1515点。完整邻域尚待完成，当前验收结论保持待定。

已完成的Bootstrap、时间与集中性、S018-v1对照和研究族年度分析保留。原目标、完整点集、61进程资源设置与剩余7轮优化额度保持。暂停前已完成账户的身份与请求逐份核验PASS；执行器时间统计截止最后已提交批次，停止期间的准备/清理未包含在该时间统计中。

恢复须等待用户明确指令，随后使用同一源码、协议与公共检查点执行：

```powershell
'''+resume+'''
```

[恢复检查点](others/pause_checkpoint.json)、[进程停止记录](others/process_pause.json)、[执行清单](protocols/run_manifest.json)、[已保存账户](others/account_results.json)、[统计报告](others/statistics_report.md)。
''').encode())
    print('PAUSE_RECORDED',len(checked),'verified scenarios; 1515 pending; waiting for user',flush=True)


if __name__ == '__main__':
    main()
