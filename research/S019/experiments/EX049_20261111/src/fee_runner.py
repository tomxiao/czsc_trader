"""Seven fixed fee pairs for stage-three development through public TDR execution."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
sys.path.insert(0, str(ROOT/'research/S019/experiments/EX048_20261111/src'))
import batch_runner as core  # noqa: E402
from strategy_runtime import EquityStrategyDefinition  # noqa: E402
from strategy_runtime.equity import equity_hash  # noqa: E402

IDS = {'C0798', 'C0801', 'C0804', 'C0966', 'C1010', 'C1045', 'C0909'}
RESOURCES = {'workers':12, 'native_threads':1, 'batch_size':7, 'random_seed':19}
ORIGINAL_SOURCE = ROOT/'research/S019/experiments/EX046_20261111/src/strategy.py'


def normalize(value):
    return json.loads(core.encoded(value))


def path_in_batch(relative):
    assert isinstance(relative, str) and not Path(relative).is_absolute()
    path = (ROOT/relative).resolve()
    assert path.is_relative_to(ROOT/'research/S019') and path.exists()
    return path


def pressure_acceptance(m, benchmark):
    """Original pressure economics; frequency is an explicitly separate diagnostic."""
    dd, bh = m['drawdown'], benchmark['drawdown']
    gates = {'nar':m['nar'] >= .5, 'calmar':m['calmar'] is not None and m['calmar'] >= 4.5,
        'absolute_dd':dd <= .25, 'relative_dd':dd < bh if bh > 0 else dd == 0}
    frequency = {'median':m['frequency_median'], 'coverage':m['frequency_coverage'],
        'median_ge_6':m['frequency_median'] >= 6, 'coverage_ge_90pct':m['frequency_coverage'] >= .9,
        'used_for_pressure_acceptance':False}
    return gates, all(gates.values()), frequency


def check_fee_contract(standard, pressure, standard_audit_inputs):
    assert standard['fee_rate'] == .001 and standard['scenario_id'] == 'STANDARD' and standard['measurement_tier'] == 'FORMAL'
    assert pressure['fee_rate'] == .002 and pressure['scenario_id'] == pressure['measurement_tier'] == 'STRESS'
    assert standard['window_id'] == pressure['window_id'] == 'FULL'
    assert standard['experiment']['strategy_id'] == pressure['experiment']['strategy_id'] == 'S019'
    assert standard_audit_inputs['fee_rate'] == .001
    assert equity_hash(standard_audit_inputs) == standard['audit_inputs_sha256']
    pressure_audit_hash = equity_hash({**standard_audit_inputs, 'fee_rate':.002})
    assert pressure_audit_hash == pressure['audit_inputs_sha256'], 'Fee-derived input identity differs'
    allowed = {'experiment', 'fee_rate', 'scenario_id', 'measurement_tier', 'audit_inputs_sha256'}
    assert {k:v for k,v in standard.items() if k not in allowed} == {
        k:v for k,v in pressure.items() if k not in allowed}, [
        k for k in set(standard) | set(pressure) if k not in allowed and standard.get(k) != pressure.get(k)]
    return {'status':'PASS', 'allowed_business_changes':['experiment','fee_rate','scenario_id','measurement_tier'],
        'derived_audit_inputs_check':'Exact original audit input with fee_rate alone replaced by 0.002',
        'standard_audit_inputs_sha256':standard['audit_inputs_sha256'],
        'pressure_audit_inputs_sha256':pressure_audit_hash}


def preflight(work, scratch):
    assert work.parent == ROOT/'research/S019/experiments' and re.fullmatch(r'EX\d{3}_\d{8}',work.name)
    protocol = work/'protocols/fee_pairs.json'
    config = core.read(protocol)
    assert set(config) == {'standard_fee_rate','pressure_fee_rate','round_budget','pairs'}
    assert config['standard_fee_rate'] == .001 and config['pressure_fee_rate'] == .002
    assert config['round_budget'] == {'allocated_rounds':10,'round_index':3,'total_round':3,'remaining_after_completion':7}
    pairs = config['pairs']
    assert len(pairs) == 7 and {p['candidate_id'] for p in pairs} == IDS
    assert len({p['label'] for p in pairs}) == 7
    assert (work/'src/strategy.py').read_bytes() == ORIGINAL_SOURCE.read_bytes()
    source_hash = core.equity_source_hash(work/'src', ('strategy.py',))
    specs = core.read(work/'protocols/specs.json')
    bound = {s['label']:s for s in specs['specs']}
    assert len(bound) == len(specs['specs']) == 7 and set(bound) == {p['label'] for p in pairs}
    candidates, originals, jobs = [], {}, []
    for pair in pairs:
        assert set(pair) == {'label','candidate_id','standard_account','source_root'}
        label = pair['label']
        assert re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}',label)
        account = path_in_batch(pair['standard_account'])
        source = path_in_batch(pair['source_root'])
        ref = core.d.EvidenceRef.from_dict(core.read(account))
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        header = json.loads(raw)
        definition = EquityStrategyDefinition.from_dict(header['request']['candidate_definition'])
        assert definition.source_files == ('strategy.py',) and definition.source_sha256 == source_hash
        assert (source/'strategy.py').read_bytes() == ORIGINAL_SOURCE.read_bytes()
        old_id, original = core.reuse_header(pair['standard_account'], definition)
        assert old_id == pair['candidate_id']
        assert json.loads(definition.parameters_json) == bound[label]['parameters']
        assert normalize(definition.state_schema.to_dict()) == specs['state_schema']
        assert core.validate_source_state_schema(work/'src/strategy.py',definition.state_schema)['status'] == 'PASS'
        candidate = core.EquityStrategyCandidate('S019', old_id, definition, work/'src')
        assert candidate.content_identity.content_sha256 == header['request']['content_sha256']
        candidates.append(candidate)
        originals[label] = {**original, 'source_root':pair['source_root']}
        jobs.append({'label':label, 'candidate_id':old_id, 'content_hash':candidate.content_identity.content_sha256,
            'definition':normalize(definition.to_dict()), 'parameters':json.loads(definition.parameters_json),
            'standard_account':pair['standard_account'], 'source_root':pair['source_root']})
    assert len({job['content_hash'] for job in jobs}) == 7
    dependencies = {Path(core.__file__).resolve().relative_to(ROOT).as_posix():core.digest(Path(core.__file__))}
    for name in ('runner','data_window','prepare_data','load_data'):
        path = Path(sys.modules[name].__file__).resolve()
        dependencies[path.relative_to(ROOT).as_posix()] = core.digest(path)
    manifest = {'version':1, 'experiment':work.name, 'stage':'STAGE_THREE', 'diagnostic_kind':'FEE_PAIRED_DEVELOPMENT',
        'runner_sha256':core.digest(Path(__file__)), 'fee_pairs_sha256':core.digest(protocol),
        'plan_sha256':core.digest(work/'protocols/plan.md'), 'specs_sha256':core.digest(work/'protocols/specs.json'),
        'source_sha256':source_hash, 'source_raw_sha256':core.digest(ORIGINAL_SOURCE), 'dependencies':dependencies,
        'standard_fee_rate':.001, 'pressure_fee_rate':.002, 'resources':RESOURCES,
        'expected_new_strategy_runs':7, 'expected_benchmark_runs':1, 'expected_reused_accounts':7,
        'expected_paired_configurations':7, 'expected_scenario_accounts':14,
        'checkpoint_run_id':work.name.lower()+'-stage3-fee-pairs', 'originals':originals, 'jobs':jobs,
        'round_budget':config['round_budget'], 'rounds_debited_by_runner':0,
        'formal_stage_four_acceptance':False}
    core.immutable(work/'protocols/run_manifest.json', manifest, scratch)
    for job in jobs:
        core.immutable(work/f'others/{job["label"]}_definition.json',job['definition'],scratch)
    print('FEE_PREFLIGHT_PASS',work.name,'standard reuse 7; pressure new 7; one pressure BH',flush=True)
    return core.RepositoryContext.discover(ROOT), config, candidates, manifest


def request_for(exp, candidate, pressure):
    standard = core.request_for(exp, candidate)
    return replace(standard,fee_rate=.002,scenario_id='STRESS',measurement_tier='STRESS') if pressure else standard


def basic_audit(payload):
    run = payload['runs']['candidate']
    assert all(r['observed_through'] <= r['decision_at'] <= r['execution_start'] and 0 <= r['target'] <= 1 for r in run['decisions'])
    assert all(r['cash'] >= -1e-8 and r['quantity'] >= 0 for r in run['account_points'])
    assert all(r['quantity'] > 0 and r['quantity'] == int(r['quantity']) for r in run['fills'])
    assert payload['request']['lineage'] is None
    return {'chronology':'PASS','cash_longonly_integer':'PASS'}


def pressure_row(work, pair, handle, ref, payload, original):
    assert payload['request'] == json.loads(handle.contract_content)
    assert payload['request_hash'] == sha256(handle.contract_content).hexdigest()
    run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
    m, b = core.metrics(run,bh['metrics']['daily_max_drawdown']), core.metrics(bh,bh['metrics']['daily_max_drawdown'])
    gates, passed, frequency = pressure_acceptance(m,b)
    return {'label':pair['label'], 'candidate_id':handle.candidate.candidate_id,
        'content_hash':handle.candidate.content_identity.content_sha256,
        'parameters':json.loads(handle.candidate.definition.parameters_json),
        'definition':normalize(handle.candidate.definition.to_dict()), 'account_ref':ref.to_dict(),
        'request_sha256':payload['request_hash'], 'candidate':{k:v for k,v in m.items() if k not in ('gates','eligible')},
        'benchmark':b,
        'pressure_gates':gates, 'pressure_eligible':passed, 'frequency_diagnostic':frequency,
        'role':'PRESSURE_DIAGNOSTIC', 'source_root':(work/'src').relative_to(ROOT).as_posix(),
        'standard_account_ref':original['reference'], 'audit':basic_audit(payload)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--recover',action='store_true')
    args = parser.parse_args()
    assert not args.recover or args.run
    work = args.experiment.resolve()
    scratch = ROOT/'.tmp'/(work.name.lower()+'-fee-pairs')
    scratch.mkdir(parents=True,exist_ok=True)
    os.environ.update(TEMP=str(scratch),TMP=str(scratch),PYTHONDONTWRITEBYTECODE='1')
    repo, config, candidates, manifest = preflight(work,scratch)
    if not args.run:
        return
    path, attempts_path = work/'others/results.json', work/'others/attempts.json'
    assert args.recover or (not path.exists() and not attempts_path.exists()), 'Existing work requires explicit --recover'
    results = core.read(path) if path.exists() else {'status':'RUNNING','manifest':manifest,'accounts':{},'pressure_accounts':{},'batches':[]}
    assert results['manifest'] == manifest
    labels = {p['label'] for p in config['pairs']}
    assert set(results['accounts']) <= labels and set(results['pressure_accounts']) <= labels
    attempts = core.read(attempts_path) if attempts_path.exists() else []
    for old in attempts:
        if old['status'] == 'RUNNING':
            old.update(status='INTERRUPTED_WITH_PARTIAL_STATISTICS',statistics_complete=False)
    attempt = {'attempt':len(attempts)+1, 'started_utc':datetime.now(timezone.utc).isoformat(), 'status':'RUNNING',
        'statistics_complete':True,'equity_statistics':core.zero_statistics(),'elapsed_seconds':0.,'error':None,
        'resources':RESOURCES, 'completed_at_start':len(results['pressure_accounts'])}
    attempts.append(attempt)
    core.save(attempts_path,attempts,scratch)
    results.update(status='RUNNING',error=None)
    execution, caught, in_compute, started = None, None, False, perf_counter()

    def snapshot(status):
        attempt.update(status=status,elapsed_seconds=perf_counter()-started,
            equity_statistics=asdict(execution.equity_statistics) if execution is not None and execution.equity_statistics is not None else core.zero_statistics())
        if execution is not None:
            attempt['execution_stats'] = asdict(execution.stats)
            if attempt['execution_stats']['unknown']:
                attempt['statistics_complete'] = False
        core.save(attempts_path,attempts,scratch)
        workload = {key:sum(a['equity_statistics'][key] for a in attempts) for key in ('input_snapshots','candidate_runs','benchmark_runs')}
        workload.update(account_timings=[t for a in attempts for t in a['equity_statistics']['account_timings']],
            reused_accounts=len(results['accounts']), new_pressure_evidence_accounts=len(results['pressure_accounts']),
            paired_configurations=len(set(results['accounts']) & set(results['pressure_accounts'])),
            scenario_accounts=len(results['accounts'])+len(results['pressure_accounts']))
        results.update(status=status,workload=workload,elapsed_seconds=sum(a['elapsed_seconds'] for a in attempts),
            replay_statistics_complete=all(a['statistics_complete'] for a in attempts),attempt_count=len(attempts),
            round_budget=config['round_budget'],rounds_debited_by_runner=0)
        core.save(path,results,scratch)

    try:
        original = core.replay_context(repo,candidates[0].definition.execution_spec)
        context = replace(original,evaluation=core.EvaluationAccess(dataflows=original.data,
            resources=core.ExecutionResources(12,1,19),strategy_id=original.strategy_id,execution_spec=candidates[0].definition.execution_spec))
        exp = core.d.ExperimentRef('S019',work.name)
        checkpoint = core.d.ExecutionCheckpointRequest(manifest['checkpoint_run_id'],
            core.d.CheckpointMode.RESUME if args.recover else core.d.CheckpointMode.CREATE)
        with core.d.ResearchExecutionSession(context,experiment=exp,checkpoint=checkpoint,on_progress=lambda p:print(p,flush=True)) as execution:
            prepared = [(pair,context.evaluation.prepare(request_for(exp,candidate,False),execution=execution),
                context.evaluation.prepare(request_for(exp,candidate,True),execution=execution))
                for pair,candidate in zip(config['pairs'],candidates,strict=True)]
            assert len({h.snapshot.sha256 for _,a,b in prepared for h in (a,b)}) == 1
            assert len({b.benchmark_identity.sha256 for _,_,b in prepared}) == 1
            assert len({a.benchmark_identity.sha256 for _,a,_ in prepared}) == 1
            assert prepared[0][1].benchmark_identity.sha256 != prepared[0][2].benchmark_identity.sha256
            core.immutable(work/'protocols/prepared_request_manifest.json',[
                {'label':pair['label'], 'standard_request_sha256':sha256(a.contract_content).hexdigest(),
                 'pressure_request_sha256':sha256(b.contract_content).hexdigest(), 'input_snapshot_sha256':a.snapshot.sha256,
                 'standard_benchmark_identity':a.benchmark_identity.sha256,'pressure_benchmark_identity':b.benchmark_identity.sha256}
                for pair,a,b in prepared],scratch)
            for pair, standard, pressure in prepared:
                label, record = pair['label'], manifest['originals'][pair['label']]
                assert core.digest(ROOT/pair['standard_account']) == record['reference_file_sha256']
                ref, payload = core.read_account(ROOT/pair['standard_account'])
                assert ref.to_dict() == record['reference'] and payload['request_hash'] == record['source_request_sha256']
                std_request, pressure_request = json.loads(standard.contract_content), json.loads(pressure.contract_content)
                core.check_reuse_contract(payload['request'],std_request)
                check = check_fee_contract(std_request,pressure_request,payload['audit_inputs'])
                contract = {**check,'label':label,'candidate_id':pair['candidate_id'], 'standard_account_ref':ref.to_dict(),
                    'source_standard_request_sha256':payload['request_hash'],
                    'standard_request_sha256':sha256(standard.contract_content).hexdigest(),
                    'pressure_request_sha256':sha256(pressure.contract_content).hexdigest(),
                    'standard_request':std_request,'pressure_request':pressure_request}
                core.immutable(work/f'others/{label}_fee_pair_contract.json',contract,scratch)
                run, bh = payload['runs']['candidate'],payload['runs']['buy_hold']
                row = {'label':label,'candidate_id':pair['candidate_id'],'parameters':json.loads(standard.candidate.definition.parameters_json),
                    'definition':normalize(standard.candidate.definition.to_dict()),'content_hash':standard.candidate.content_identity.content_sha256,
                    'request_sha256':payload['request_hash'],'prepared_request_sha256':sha256(standard.contract_content).hexdigest(),
                    'account_ref':ref.to_dict(),'candidate':core.metrics(run,bh['metrics']['daily_max_drawdown']),
                    'benchmark':core.metrics(bh,bh['metrics']['daily_max_drawdown']),'role':'REUSED_EVIDENCE',
                    'source_root':pair['source_root'],'reuse_provenance':record,'audit':basic_audit(payload)}
                if label in results['accounts']:
                    assert results['accounts'][label] == row
                results['accounts'][label] = row
                core.immutable(work/f'others/{label}_account.json',ref.to_dict(),scratch)
                saved = work/f'others/{label}_stress_account.json'
                if saved.exists():
                    stress_ref, stress_payload = core.read_account(saved)
                    restored = pressure_row(work,pair,pressure,stress_ref,stress_payload,record)
                    if label in results['pressure_accounts']:
                        assert results['pressure_accounts'][label] == restored
                    results['pressure_accounts'][label] = restored
                else:
                    assert label not in results['pressure_accounts']
                snapshot('RUNNING')
                print('FEE_PAIR_CONTRACT_PASS',label,flush=True)
            pending = [(pair,h) for pair,_,h in prepared if pair['label'] not in results['pressure_accounts']]
            if pending:
                in_compute = True
                outcomes = context.evaluation.evaluate_many(tuple(h for _,h in pending),execution=execution)
                in_compute = False
                snapshot('RUNNING')
                statuses = []
                for (pair,handle),outcome in zip(pending,outcomes,strict=True):
                    label = pair['label']
                    statuses.append({'label':label,'status':outcome.status.value,'error':str(outcome.error) if outcome.error else None})
                    if outcome.result is None:
                        continue
                    ref = core.publish_evidence(context,core.d.EvaluationEvidenceWrite(exp,label+'_stress',handle,outcome.result),execution=execution)
                    core.immutable(work/f'others/{label}_stress_account.json',ref.to_dict(),scratch)
                    payload = core.materialize_equity(outcome.result).payload
                    row = pressure_row(work,pair,handle,ref,payload,manifest['originals'][label])
                    results['pressure_accounts'][label] = row
                    snapshot('RUNNING')
                    print('PRESSURE_ACCOUNT',label,row['candidate']['nar'],row['candidate']['calmar'],row['pressure_eligible'],flush=True)
                results['batches'].append({'attempt':attempt['attempt'],'statuses':statuses})
                snapshot('RUNNING')
                assert all(s['status'] == 'SUCCEEDED' for s in statuses), 'Inspect failed pressure work before explicit recovery'
            assert set(results['accounts']) == set(results['pressure_accounts']) == labels
            audit = [{'definition':(work/f'others/{pair["label"]}_definition.json').relative_to(ROOT).as_posix(),
                'account':(work/f'others/{pair["label"]}_stress_account.json').relative_to(ROOT).as_posix(),
                'source_root':(work/'src').relative_to(ROOT).as_posix(),
                'specs_protocol':(work/'protocols/specs.json').relative_to(ROOT).as_posix(),
                'specs_protocol_sha256':manifest['specs_sha256'],'spec_label':pair['label'],
                'selection_reasons':['all_seven_pressure_accounts']} for pair in config['pairs']]
            core.immutable(work/'others/audit_manifest.json',audit,scratch)
            snapshot('COMPLETE')
            if len(attempts) == 1 and results['replay_statistics_complete']:
                assert results['workload']['candidate_runs'] == 7 and results['workload']['benchmark_runs'] == 1
    except BaseException as error:
        caught = error
        if in_compute:
            attempt['statistics_complete'] = False
        attempt['error'] = repr(error)
        results['error'] = repr(error)
        raise
    finally:
        snapshot('COMPLETE' if caught is None and results['status'] == 'COMPLETE' else 'STOPPED')
    print('FEE_PAIRS_COMPLETE',{k:v for k,v in results['workload'].items() if k != 'account_timings'},flush=True)


if __name__ == '__main__':
    main()
