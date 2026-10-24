"""Real-parameter joint coverage followed by batch-feedback constrained TPE."""
# ruff: noqa: E402
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
import argparse
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import optuna
import pandas as pd
from czsc_trader.application import open_research_execution, publish_evidence
from czsc_trader.research_tools import ExperimentRef, EvaluationEvidenceWrite, EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
HOME = Path(__file__).resolve().parents[1]
EX = ExperimentRef('S015', HOME.name)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def violations(row):
    a, b = row['runs']['full'], row['runs']['s011_common']
    return [1.5*a['benchmark_cagr']-a['cagr'], a['dd']-.8*a['benchmark_dd'], a['dd']-.25,
            6-a['frequency_median'], .9-a['frequency_good']/a['frequency_windows'],
            .9158029150000013-b['net_return'], b['dd']-.07248663749114126]


def values(row):
    return [row['runs'][w][k] for w in ('full', 's011_common') for k in ('net_return', 'dd')]


def main(resume=False):
    plan = read(HOME / 'protocols/search.json')
    for path, digest in plan['dependency_files'].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest
    refs = [EvidenceRef.from_dict(x) for x in read(HOME / 'others/protocol_refs.json')]
    own = next(x for x in refs if x.name == 'search' and x.media_type == 'text/x-python')
    assert own.resolve(ROOT).read_bytes() == Path(__file__).read_bytes()
    assert next(x for x in refs if x.name == 'search' and x.media_type == 'application/json').resolve(ROOT).read_bytes() == (HOME / 'protocols/search.json').read_bytes()
    api = module(ROOT / 'research/S015/experiments/EX062_20261024/src/accounts.py', 'account_api')
    api.SOURCE = HOME / 'src/strategy_runtime'
    suite = module(ROOT / 'research/S015/experiments/EX016_20261023/src/suite.py', 'summary_api')
    audit = module(ROOT / 'research/S015/experiments/EX061_20261024/src/account_audit.py', 'audit_api')
    ctx = api.context(8)
    base = read(ROOT / 'research/S015/experiments/EX061_20261024/others/C6105_payload.json')['parameters']
    base['max_hold'] = 30
    work = HOME / 'work'
    work.mkdir(exist_ok=True)
    database = work / 'search.sqlite'
    if not resume:
        assert not database.exists() and not (HOME / 'others/progress.json').exists()
    sampler = optuna.samplers.TPESampler(seed=13, multivariate=True, n_startup_trials=24,
        constraints_func=lambda trial: trial.user_attrs['constraint_violations'])
    study = optuna.create_study(study_name='S015-EX065', storage='sqlite:///' + database.as_posix(),
        load_if_exists=resume, directions=['maximize','minimize','maximize','minimize'], sampler=sampler)
    if not resume:
        grid = [(3,3)] + [(n,h) for n in range(2,11) for h in range(1,15) if (n,h)!=(3,3)]
        for n,h in grid:
            study.enqueue_trial({'lookback':n,'hold':h,'allocation':1.0,'rearm_mode':'positive_step'})
        for allocation in (.95,1.):
            study.enqueue_trial({'lookback':3,'hold':3,'allocation':allocation,'rearm_mode':'immediate'})
    else:
        raise RuntimeError('Explicit recovery requires reviewing outstanding trials; no automatic resume or retry.')
    rows, audits, trial_log = [], [], []
    cache = {}
    serial = None
    serial_ref = None
    with open_research_execution(ctx, experiment=EX) as session:
        for start in range(0,224,8):
            batch = []
            for _ in range(8):
                trial = study.ask()
                params = {**base, 'lookback':trial.suggest_int('lookback',2,10),
                    'hold':trial.suggest_int('hold',1,14),
                    'allocation':trial.suggest_float('allocation',.6,1.,step=.025),
                    'rearm_mode':trial.suggest_categorical('rearm_mode',['positive_step','immediate'])}
                key = json.dumps(params, sort_keys=True)
                batch.append((trial,params,key))
            pending = []
            seen = set(cache)
            for trial,params,key in batch:
                if key not in seen:
                    req = api.request(ctx, EX, len(rows)+len(pending), params)
                    pending.append((key,req))
                    seen.add(key)
            save(HOME / f'others/batch_{start//8:02}_asks.json', {
                'completed_trials_before_ask':start,
                'phase':'fixed_joint_grid' if start<128 else 'adaptive_TPE',
                'trials':[{'number':t.number,'params':t.params} for t,_,_ in batch]})
            if start == 0:
                serial = api.context(1).evaluation.evaluate(pending[0][1])
                serial_ref = publish_evidence(ctx, EvaluationEvidenceWrite(EX,'serial_control',pending[0][1],serial))
                print('SERIAL_PREFLIGHT_COMPLETE', flush=True)
            outputs = ctx.evaluation.evaluate_many(tuple(req for _,req in pending), execution=session) if pending else ()
            for (key,req),out in zip(pending,outputs,strict=True):
                if out.status.value != 'SUCCEEDED':
                    save(HOME / 'others/technical_failure.json', {'candidate':req.strategy.candidate_id,'error':str(out.error),'completed':len(rows)})
                    raise RuntimeError(out.error)
                result = out.result
                if not rows:
                    assert serial.result_hash == result.result_hash
                    for a,b in zip(serial.runs,result.runs,strict=True):
                        for name in ('account_daily','decisions','orders','fills','trades'):
                            pd.testing.assert_frame_equal(getattr(a.execution,name),getattr(b.execution,name))
                row = suite.summary(req,result)
                if not rows:
                    old = next(x for x in read(ROOT/'research/S015/experiments/EX061_20261024/others/results.json')['rows'] if x['candidate_id']=='C6105')
                    assert row['runs'] == old['runs'], 'Inactive max_hold change altered account behavior'
                ref = publish_evidence(ctx,EvaluationEvidenceWrite(EX,req.strategy.candidate_id,req,result))
                row['evidence'] = ref.to_dict()
                row['identity'] = {'key':result.runs[0].identity.candidate.to_dict(),'content_sha256':result.runs[0].identity.content_sha256}
                row['dependencies'] = [asdict(x) for x in req.dependencies]
                save(HOME / f"others/{row['candidate_id']}_payload.json", api.plain(req.strategy.payload))
                evidence = read(ref.resolve(ROOT))
                for run in evidence['runs']:
                    description = audit.describe(run,row['runs'][run['window_id']])
                    # Keep concise risk facts; full immutable account remains the source.
                    audits.append({'candidate':row['candidate_id'],'window':run['window_id'],'status':'PASS',
                        'closed_cycles':description['closed_cycle_distribution'],
                        'cycle_sums':description['cycle_sums']})
                rows.append(row)
                cache[key] = row
            for trial,params,key in batch:
                row = cache[key]
                trial.set_user_attr('constraint_violations',violations(row))
                trial.set_user_attr('evidence_candidate',row['candidate_id'])
                study.tell(trial,values(row))
                trial_log.append({'number':trial.number,'params':trial.params,'values':values(row),
                    'candidate_id':row['candidate_id'],'constraint_violations':violations(row),
                    'completed_before_ask':start,'phase':'fixed_joint_grid' if start<128 else 'adaptive_TPE'})
            save(HOME/'others/progress.json',{'completed_trials':start+8,'unique_configurations':len(rows),'rows':rows,'trials':trial_log})
            save(HOME/'others/audit.json',{'status':'ARITHMETIC_CHECKS_PASS','accounts':audits})
            print('BATCH_COMPLETE',start+8,'unique',len(rows),'passing',sum(x['both_center_pass'] for x in rows),flush=True)
        stats = asdict(session.stats)
    save(HOME/'others/results.json',{'rows':rows,'new_configurations':len(rows),'formal_accounts':2*len(rows),
        'technical_accounts':2,'serial_equal':True,'serial_ref':serial_ref.to_dict(),'old_C6105_equivalent':True,
        'center_pass_count':sum(x['both_center_pass'] for x in rows),'optuna':trial_log,'optuna_version':optuna.__version__,'execution_stats':stats})
    print('SEARCH_COMPLETE',len(rows),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume',action='store_true')
    main(parser.parse_args().resume)
