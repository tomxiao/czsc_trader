"""Equal-budget constrained Optuna comparison for two to four S019 families."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sys
from time import perf_counter

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
sys.path.insert(0, str(ROOT/'research/S019/experiments/EX043_20261110/src'))
import batch_runner as core  # noqa: E402
import optuna  # noqa: E402

RESOURCES = {'workers': 12, 'native_threads': 1, 'family_batch_size': 4}


def normalize(value):
    return json.loads(core.encoded(value))


def constraints(trial):
    return trial.user_attrs['constraints']


def gate_values(m, benchmark):
    dd = benchmark['drawdown']
    relative = m['drawdown']/(.8*dd)-1 if dd > 0 else (0. if m['drawdown'] == 0 else 1.)
    return [(.55-m['nar'])/.55, (5-m['calmar'])/5 if m['calmar'] is not None else 1e6,
            (m['drawdown']-.25)/.25, relative, (6-m['frequency_median'])/6,
            (.9-m['frequency_coverage'])/.9]


def make_studies(config, controls):
    studies = {}
    for index, family in enumerate(config['families']):
        sampler = optuna.samplers.TPESampler(seed=config['seed']+index, multivariate=True,
            constant_liar=True, n_startup_trials=8, constraints_func=constraints)
        study = optuna.create_study(direction='maximize', sampler=sampler,
            study_name=family['name'], storage=optuna.storages.InMemoryStorage())
        study.enqueue_trial({key:controls[family['name']][key] for key in family['space']})
        studies[family['name']] = study
    return studies


def suggest(trial, space):
    raw, effective, distributions = {}, {}, {}
    for key, bounds in sorted(space.items()):
        if bounds['kind'] == 'int':
            value = trial.suggest_int(key, bounds['low'], bounds['high'], step=bounds['step'])
            aligned = value
        else:
            value = trial.suggest_float(key, bounds['low'], bounds['high'], step=bounds['step'])
            if bounds['step'] is None:
                aligned = value
            else:
                n = round((value-bounds['low'])/bounds['step'])
                aligned = float(Decimal(str(bounds['low']))+n*Decimal(str(bounds['step'])))
                assert abs(value-aligned) < 1e-12
        raw[key], effective[key] = value, aligned
        distributions[key] = json.loads(optuna.distributions.distribution_to_json(trial.distributions[key]))
    return raw, effective, distributions


def tell(study, trial, measured):
    g = gate_values(measured['candidate'], measured['buy_hold'])
    assert (max(g) <= 0) == measured['candidate']['eligible']
    trial.set_user_attr('constraints', g)
    trial.set_user_attr('account', measured['account'])
    study.tell(trial, measured['candidate']['nar'])
    frozen = study.trials[trial.number]
    assert tuple(frozen.system_attrs['constraints']) == tuple(g)
    return {'number': trial.number, 'state': frozen.state.name, 'value': frozen.value,
            'constraints': g, 'parameters': frozen.params, 'account': measured['account'],
            'system_constraints': frozen.system_attrs['constraints']}


def check_space(space, control):
    assert isinstance(space, dict) and space
    for key, b in space.items():
        assert set(b) == {'kind', 'low', 'high', 'step'} and b['kind'] in ('float', 'int')
        assert all(type(b[k]) in (int, float) and math.isfinite(b[k]) for k in ('low', 'high'))
        assert b['low'] < b['high']
        if b['kind'] == 'float' and b['step'] is None:
            assert type(control[key]) in (int,float) and b['low'] <= control[key] <= b['high']
            continue
        assert type(b['step']) in (int,float) and math.isfinite(b['step']) and b['step'] > 0
        if b['kind'] == 'int':
            assert all(type(b[k]) is int for k in ('low', 'high', 'step')) and type(control[key]) is int
        lo, hi, step, value = (Decimal(str(v)) for v in (b['low'], b['high'], b['step'], control[key]))
        assert (hi-lo) % step == 0 and lo <= value <= hi and (value-lo) % step == 0, key


def preflight(work, scratch):
    assert work.parent == ROOT/'research/S019/experiments' and re.fullmatch(r'EX\d{3}_\d{8}', work.name)
    assert optuna.__version__ == '4.9.0'
    config = core.read(work/'protocols/search.json')
    assert set(config) == {'families', 'state_schema', 'base_candidate', 'parameter_schema',
        'candidate_start', 'round_budget', 'seed', 'trial_budget', 'startup_trials', 'batch_size'}
    assert config['trial_budget'] == 24 and config['startup_trials'] == 8 and config['batch_size'] == 4
    assert type(config['seed']) is int and config['seed'] >= 0
    families = config['families']
    assert 2 <= len(families) <= 4 and len({f['name'].casefold() for f in families}) == len(families)
    budget = config['round_budget']
    assert set(budget) == {'allocated_rounds', 'round_index', 'total_round', 'remaining_after_completion'}
    assert all(type(v) is int for v in budget.values()) and budget['allocated_rounds'] == 6
    assert 1 <= budget['round_index'] <= 6 and budget['total_round'] == budget['round_index']+4
    assert budget['remaining_after_completion'] == 6-budget['round_index']
    first, total = config['candidate_start'], 24*len(families)
    assert type(first) is int and first >= 622 and first+total <= 10000
    reserved = {f'C{i:04}' for i in range(first, first+total)}
    pattern = re.compile(r'"(?:candidate_id|id|proposed_candidate_id)"\s*:\s*"(C\d{4})"')
    used = set()
    for directory in (work.parent, ROOT/'research/registrations/S019'):
        for path in directory.rglob('*.json'):
            if not path.is_relative_to(work):
                content = path.read_text(encoding='utf-8')
                used.update(pattern.findall(content))
                if '"reserved_proposed_candidate_ids"' in content:
                    record = json.loads(content)
                    if isinstance(record, dict):
                        used.update(record.get('reserved_proposed_candidate_ids', []))
    for directory in (ROOT/'research/S019/assets/candidates').iterdir():
        if re.fullmatch(r'C\d{4}', directory.name):
            used.add(directory.name)
    assert not reserved.intersection(used) and first == max(int(x[1:]) for x in used)+1
    repo = core.RepositoryContext.discover(ROOT)
    base = core.load_candidate(repo, core.CandidateKey('S019', config['base_candidate']))
    schema = core.StrategyStateSchema.from_dict(config['state_schema'])
    assert {f.key for f in schema.cycle_fields} == {'anchor', 'allocation', 'exiting', 'high_water', 'entry_atr', 'risk_fraction', 'breach_count'}
    validation = core.validate_source_state_schema(work/'src/strategy.py', schema)
    core.immutable(work/'others/state_schema_preflight.json', validation, scratch)
    parameter_schema = json.loads(base.definition.parameter_schema_json)
    for name, rule in config['parameter_schema'].items():
        assert set(rule) == {'type'} and rule['type'] in ('boolean', 'string', 'integer', 'number')
        assert name not in parameter_schema or parameter_schema[name] == rule
    parameter_schema.update(config['parameter_schema'])
    source_hash = core.equity_source_hash(work/'src', ('strategy.py',))
    definition = None
    controls, references = {}, {}
    for family in families:
        required = {'name', 'fixed', 'space', 'control_account'}
        assert required <= set(family) <= required | {'control_parameters', 'neutral_added_parameters'}
        assert re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}', family['name'])
        control_path = (ROOT/family['control_account']).resolve()
        assert not Path(family['control_account']).is_absolute() and control_path.is_relative_to(ROOT/'research/S019')
        ref, payload = core.read_account(control_path)
        request = payload['request']
        previous = request['candidate_definition']
        assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD' and request['window_id'] == 'FULL'
        assert previous['state_schema'] == config['state_schema']
        historical = json.loads(previous['parameters_json'])
        parameters = family.get('control_parameters', historical)
        added = family.get('neutral_added_parameters', {})
        assert set(historical) <= set(parameters) and {k:parameters[k] for k in historical} == historical
        assert {k:v for k,v in parameters.items() if k not in historical} == added
        if added or previous['source_sha256'] != source_hash:
            assert 'control_parameters' in family and added, 'Source adaptation requires explicit neutral added parameters'
        old_parameter_schema = json.loads(previous['parameter_schema_json'])
        assert {k:parameter_schema[k] for k in old_parameter_schema} == old_parameter_schema
        assert not set(family['fixed']).intersection(family['space'])
        assert set(family['fixed']) | set(family['space']) == set(parameters) == set(parameter_schema)
        assert {k:parameters[k] for k in family['fixed']} == family['fixed']
        check_space(family['space'], parameters)
        control_definition = replace(base.definition, source_files=('strategy.py',), source_sha256=source_hash,
            state_schema=schema, parameter_schema_json=json.dumps(parameter_schema,sort_keys=True,separators=(',',':')),
            parameters_json=json.dumps(parameters,sort_keys=True,separators=(',',':')))
        current = normalize(control_definition.to_dict())
        adapted = {'source_sha256', 'parameters_json', 'parameter_schema_json'}
        assert {k:v for k,v in current.items() if k not in adapted} == {k:v for k,v in previous.items() if k not in adapted}
        if definition is None:
            definition = control_definition
        controls[family['name']] = parameters
        references[family['name']] = {'path': family['control_account'], 'reference': ref.to_dict(),
            'file_sha256':core.digest(control_path), 'historical_source_sha256':previous['source_sha256'],
            'current_source_sha256':source_hash, 'neutral_added_parameters':added,
            'parity_required_before_feedback':True}
    dependencies = {str(Path(core.__file__).resolve().relative_to(ROOT)).replace('\\', '/'):core.digest(Path(core.__file__))}
    for name in ('runner', 'data_window', 'prepare_data', 'load_data'):
        path = Path(sys.modules[name].__file__).resolve()
        dependencies[path.relative_to(ROOT).as_posix()] = core.digest(path)
    manifest = normalize({'version': 1, 'experiment': work.name, 'runner_sha256':core.digest(Path(__file__)),
        'source_sha256':source_hash, 'search_sha256':core.digest(work/'protocols/search.json'),
        'plan_sha256':core.digest(work/'protocols/plan.md'), 'dependencies':dependencies,
        'optuna_version':optuna.__version__, 'storage':'InMemoryStorage + immutable JSON ask/result/tell records',
        'sampler':'Constrained multivariate TPE; constant_liar=True; maximize original NAR',
        'seeds':{f['name']:config['seed']+i for i,f in enumerate(families)}, 'resources':RESOURCES,
        'resource_waves':{'family_counts':[len(families)] if len(families)<=3 else [3,1],
            'regular_proposal_counts':[4*len(families)] if len(families)<=3 else [12,4],
            'first_controls':len(families),
            'first_remaining_proposal_counts':[3*len(families)] if len(families)<=3 else [9,3],
            'feedback_barrier':'All families complete four observations before next ask'},
        'family_trial_budget':24, 'startup_trials':8, 'proposal_budget':total, 'imported_observations':0,
        'base_definition':definition.to_dict(), 'controls':references, 'control_parameters':controls,
        'candidate_start':first, 'next_candidate_start':first+total, 'reserved_proposed_candidate_ids':sorted(reserved),
        'round_budget':budget, 'rounds_debited_by_runner':0, 'checkpoint_run_id':work.name.lower()+'-family-tpe',
        'duplicate_rule':'Exact content identity reuses canonical candidate/handle/account; proposed IDs remain recorded.'})
    core.immutable(work/'protocols/run_manifest.json', manifest, scratch)
    print('PREFLIGHT_PASS',work.name,len(families),'families',total,'proposals',flush=True)
    return config, repo, definition, controls, manifest


def validate_saved_result(work, key, proposal, definition):
    path = work/f'others/trials/{key}_result.json'
    if not path.exists():
        return None
    row = core.read(path)
    ref, payload = core.read_account(work/f'others/trials/{key}_account.json')
    assert row['account'] == ref.to_dict() and row['id'] == proposal['candidate_id']
    assert row['parameters'] == proposal['parameters'] and row['definition'] == normalize(definition.to_dict())
    request = payload['request']
    assert request['candidate_id'] == row['id'] and request['candidate_definition'] == row['definition']
    assert request['content_sha256'] == row['content_hash'] == proposal['content_hash']
    assert payload['request_hash'] == row['request_sha256']
    run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
    assert row['candidate'] == core.metrics(run,bh['metrics']['daily_max_drawdown'])
    assert row['buy_hold'] == core.metrics(bh,bh['metrics']['daily_max_drawdown'])
    return row


def check_control(work, key, original, scratch):
    _, a = core.read_account(ROOT/original)
    ref, b = core.read_account(work/f'others/trials/{key}_account.json')
    a,b = a['runs']['candidate'],b['runs']['candidate']
    assert a['metrics'] == b['metrics']
    economic = ('session','time','cash','equity','quantity','receivable','close','bar_status','valuation_price_at','valuation_stale','execution_blocked')
    for name in ('account_daily','account_points'):
        assert [tuple(r[k] for k in economic) for r in a[name]] == [tuple(r[k] for k in economic) for r in b[name]]
    assert [(r['execution_start'],r['target']) for r in a['decisions']] == [(r['execution_start'],r['target']) for r in b['decisions']]
    fields = ('interval_start','side','quantity','price','fees')
    assert [tuple(r[k] for k in fields) for r in a['fills']] == [tuple(r[k] for k in fields) for r in b['fills']]
    core.immutable(work/f'others/trials/{key}_parity.json', {'status':'PASS','original':original,
        'account':ref.to_dict(),'daily_bar_targets_fills':'EXACT_EQUAL'},scratch)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--recover',action='store_true')
    args=parser.parse_args()
    assert not args.recover or args.run
    work=args.experiment.resolve()
    scratch=ROOT/'.tmp'/(work.name.lower()+'-family-search')
    scratch.mkdir(parents=True,exist_ok=True)
    os.environ.update(TEMP=str(scratch),TMP=str(scratch))
    config,repo,base,controls,manifest=preflight(work,scratch)
    if not args.run:
        return
    directory=work/'others/trials'
    directory.mkdir(exist_ok=True)
    checkpoint_path=work/'others/search_checkpoint.json'
    attempts_path=work/'others/attempts.json'
    assert args.recover or (not checkpoint_path.exists() and not attempts_path.exists())
    if checkpoint_path.exists():
        checkpoint=core.read(checkpoint_path)
        assert checkpoint['manifest']==manifest
        for name,digest in checkpoint['files'].items():
            assert core.digest(work/name)==digest
    attempts=core.read(attempts_path) if attempts_path.exists() else []
    for old in attempts:
        if old['status']=='RUNNING':
            old.update(status='INTERRUPTED_WITH_PARTIAL_STATISTICS',statistics_complete=False)
    attempt={'attempt':len(attempts)+1,'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat(),
        'statistics_complete':True,'equity_statistics':core.zero_statistics(),'elapsed_seconds':0.,'error':None,
        'error_note':'Explicit recovery; previous unknown work remains incomplete.' if args.recover else None}
    attempts.append(attempt)
    core.save(attempts_path,attempts,scratch)
    studies=make_studies(config,controls)
    execution,started,in_compute,caught=None,perf_counter(),False,None
    status='RUNNING'
    proposals,measured,feedback,seen,handles={},{},{},{},{}

    def checkpoint():
        files={p.relative_to(work).as_posix():core.digest(p) for p in directory.glob('*.json')}
        core.save(checkpoint_path,{'manifest':manifest,'status':status,'files':files,
            'proposals':list(proposals),'results':list(measured),'feedback':list(feedback)},scratch)

    def snapshot():
        attempt.update(status=status,elapsed_seconds=perf_counter()-started,
            equity_statistics=asdict(execution.equity_statistics) if execution is not None and execution.equity_statistics is not None else core.zero_statistics())
        if execution is not None:
            attempt['execution_stats']=asdict(execution.stats)
            if attempt['execution_stats']['unknown']:
                attempt['statistics_complete']=False
        core.save(attempts_path,attempts,scratch)
        totals={k:sum(a['equity_statistics'][k] for a in attempts) for k in ('input_snapshots','candidate_runs','benchmark_runs')}
        totals['account_timings']=[t for a in attempts for t in a['equity_statistics']['account_timings']]
        core.save(work/'others/execution.json',{'status':status,'manifest':manifest,'workload':totals,
            'replay_statistics_complete':all(a['statistics_complete'] for a in attempts),'attempt_count':len(attempts),
            'elapsed_seconds':sum(a['elapsed_seconds'] for a in attempts),'round_budget':config['round_budget'],
            'rounds_debited_by_runner':0,'proposals':len(proposals),'feedback':len(feedback),
            'distinct_accounts':len({r['account']['sha256'] for r in measured.values()}),
            'aliases':sum(p['alias_of'] is not None for p in proposals.values()),
            'families':{f['name']:{
                'proposals':sum(p['family']==f['name'] for p in proposals.values()),
                'completed_feedback':sum(proposals[k]['family']==f['name'] for k in feedback),
                'unique_accounts':len({r['account']['sha256'] for k,r in measured.items() if proposals[k]['family']==f['name']}),
                'aliases':sum(p['family']==f['name'] and p['alias_of'] is not None for p in proposals.values())}
                for f in config['families']}},scratch)

    def persist(name,value):
        core.immutable(directory/name,value,scratch)
        checkpoint()

    try:
        original=core.replay_context(repo,base.execution_spec)
        context=replace(original,evaluation=core.EvaluationAccess(dataflows=original.data,
            resources=core.ExecutionResources(12,1,19),strategy_id=original.strategy_id,execution_spec=base.execution_spec))
        exp=core.d.ExperimentRef('S019',work.name)
        cp=core.d.ExecutionCheckpointRequest(manifest['checkpoint_run_id'],core.d.CheckpointMode.RESUME if args.recover else core.d.CheckpointMode.CREATE)
        with core.d.ResearchExecutionSession(context,experiment=exp,checkpoint=cp,on_progress=lambda p:print(p,flush=True)) as execution:
            families=config['families']
            groups=[families] if len(families)<=3 else [families[:3],families[3:]]

            def canonical(key):
                return proposals[key]['alias_of'] or key

            def evaluate(keys):
                nonlocal in_compute
                unique=list(dict.fromkeys(canonical(k) for k in keys))
                pending=[]
                for key in unique:
                    if key in measured:
                        continue
                    p=proposals[key]
                    definition=replace(base,parameters_json=json.dumps(p['parameters'],sort_keys=True,separators=(',',':')))
                    candidate=core.EquityStrategyCandidate('S019',p['candidate_id'],definition,work/'src')
                    handle=context.evaluation.prepare(core.request_for(exp,candidate),execution=execution)
                    handles[key]=handle
                    persist(key+'_binding.json',{'request_sha256':sha256(handle.contract_content).hexdigest(),
                        'input_snapshot_sha256':handle.snapshot.sha256,'benchmark_identity':handle.benchmark_identity.sha256})
                    row=validate_saved_result(work,key,p,definition)
                    if row is not None:
                        assert row['request_sha256']==sha256(handle.contract_content).hexdigest()
                        measured[key]=row
                        continue
                    pending.append((key,handle))
                if pending:
                    assert len(pending)<=12
                    assert len({h.snapshot.sha256 for _,h in pending})==1 and len({h.benchmark_identity.sha256 for _,h in pending})==1
                    in_compute=True
                    outcomes=context.evaluation.evaluate_many(tuple(h for _,h in pending),execution=execution)
                    in_compute=False
                    snapshot()
                    failed=[]
                    for (key,handle),outcome in zip(pending,outcomes,strict=True):
                        if outcome.result is None:
                            failed.append({'key':key,'status':outcome.status.value,'error':str(outcome.error)})
                            continue
                        ref=core.publish_evidence(context,core.d.EvaluationEvidenceWrite(exp,key,handle,outcome.result),execution=execution)
                        payload=core.materialize_equity(outcome.result).payload
                        run,bh=payload['runs']['candidate'],payload['runs']['buy_hold']
                        assert all(x['observed_through']<=x['decision_at']<=x['execution_start'] and 0<=x['target']<=1 for x in run['decisions'])
                        assert all(x['cash']>=-1e-8 and x['quantity']>=0 for x in run['account_points'])
                        assert all(x['quantity']>0 and x['quantity']==int(x['quantity']) for x in run['fills'])
                        assert payload['request']['lineage'] is None
                        p=proposals[key]
                        row={'name':key,'family':p['family'],'trial_number':p['number'],
                            'proposed_candidate_id':p['proposed_candidate_id'],'id':p['candidate_id'],
                            'parameters':p['parameters'],'content_hash':p['content_hash'],
                            'definition':normalize(handle.candidate.definition.to_dict()),'account':ref.to_dict(),
                            'request_sha256':outcome.result.request_hash,'candidate':core.metrics(run,bh['metrics']['daily_max_drawdown']),
                            'buy_hold':core.metrics(bh,bh['metrics']['daily_max_drawdown']),
                            'audit':{'chronology_cash_integer':'PASS'},'provenance':{'kind':'NEW_ACCOUNT','canonical':key}}
                        persist(key+'_account.json',ref.to_dict())
                        measured[key]=row
                        persist(key+'_result.json',row)
                        print('ACCOUNT',key,row['id'],row['candidate']['nar'],row['candidate']['calmar'],row['candidate']['eligible'],flush=True)
                    if failed:
                        core.save(work/f'others/failures_attempt_{attempt["attempt"]}.json',failed,scratch)
                        raise RuntimeError('Account execution failed; explicit review/recovery required: '+str(failed))
                for key in keys:
                    parent=canonical(key)
                    if parent!=key:
                        row={**measured[parent],'name':key,'family':proposals[key]['family'],
                            'trial_number':proposals[key]['number'],'proposed_candidate_id':proposals[key]['proposed_candidate_id'],
                            'provenance':{'kind':'EXACT_ALIAS','canonical':parent,
                            'proposed_candidate_id':proposals[key]['proposed_candidate_id']}}
                        measured[key]=row
                        persist(key+'_account.json',row['account'])
                        persist(key+'_result.json',row)
                snapshot()

            for start in range(0,24,4):
                batch={}
                for family_index,family in enumerate(families):
                    name=family['name']
                    batch[name]=[]
                    for number in range(start,start+4):
                        trial=studies[name].ask()
                        assert trial.number==number
                        raw,values,distributions=suggest(trial,family['space'])
                        parameters={**family['fixed'],**values}
                        if number==0:
                            assert parameters==controls[name]
                        proposed_id=f'C{config["candidate_start"]+family_index*24+number:04}'
                        definition=replace(base,parameters_json=json.dumps(parameters,sort_keys=True,separators=(',',':')))
                        candidate=core.EquityStrategyCandidate('S019',proposed_id,definition,work/'src')
                        key=f'{name}_{number:03}'
                        identity=candidate.content_identity.content_sha256
                        alias=seen.get(identity)
                        actual_id=proposals[alias]['candidate_id'] if alias else proposed_id
                        p={'family':name,'number':number,'proposed_candidate_id':proposed_id,'candidate_id':actual_id,
                            'alias_of':alias,'content_hash':identity,'raw_parameters':raw,'parameters':parameters,'distributions':distributions}
                        proposals[key]=p
                        seen.setdefault(identity,key)
                        persist(key+'_proposal.json',p)
                        persist(key+'_definition.json',definition.to_dict())
                        batch[name].append((key,trial))
                if start==0:
                    control_keys=[batch[f['name']][0][0] for f in families]
                    evaluate(control_keys)
                    for family,key in zip(families,control_keys,strict=True):
                        check_control(work,key,family['control_account'],scratch)
                    print('ALL_CONTROLS_PARITY_PASS',len(control_keys),flush=True)
                for group in groups:
                    evaluate([key for family in group for key,_ in batch[family['name']]])
                # Fixed feedback barrier: all families have four complete observations before any next ask.
                for family in families:
                    for key,trial in batch[family['name']]:
                        value=tell(studies[family['name']],trial,measured[key])
                        feedback[key]=value
                        persist(key+'_tell.json',value)
                core.save(work/'others/summary.json',measured,scratch)
                specs=[{**p,'name':key,'label':key,'definition_path':f'others/trials/{key}_definition.json',
                    'account_path':f'others/trials/{key}_account.json'} for key,p in proposals.items()]
                core.save(work/'others/candidate_specs.json',{'source_protocol':'protocols/search.json',
                    'source_protocol_sha256':manifest['search_sha256'],'round_budget':config['round_budget'],
                    'state_schema':config['state_schema'],'specs':specs},scratch)
                core.save(work/'others/close_inputs.json',{'format':'OPTUNA_FAMILY_SEARCH_V1',
                    'run_manifest':'protocols/run_manifest.json','static_search':'protocols/search.json',
                    'summary':'others/summary.json','dynamic_specs':'others/candidate_specs.json',
                    'execution':'others/execution.json','proposals':len(proposals),
                    'canonical_accounts':len(seen),'aliases':sum(p['alias_of'] is not None for p in proposals.values())},scratch)
                print('FAMILY_WAVE_COMPLETE',start+4,'per_family','canonical_accounts',len(seen),flush=True)
                snapshot()
            assert len(proposals)==len(feedback)==24*len(families)
            assert all(len(study.trials)==24 and all(t.state==optuna.trial.TrialState.COMPLETE for t in study.trials) for study in studies.values())
            status='COMPLETE'
            checkpoint()
    except BaseException as error:
        caught=error
        status='STOPPED'
        attempt['error']=repr(error)
        if in_compute:
            attempt['statistics_complete']=False
        checkpoint()
        raise
    finally:
        if caught is not None:
            status='STOPPED'
        snapshot()
    print('FAMILY_SEARCH_COMPLETE',len(proposals),'proposals',len(seen),'distinct_definitions',flush=True)


if __name__=='__main__':
    main()
