"""Bounded, journaled public account diagnostics; local evidence only."""
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import sys
import requests

from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (EvaluationRequest, EvaluationWindow, EvaluationCost,
    EvaluationBenchmark, LimitBuyHold, EvaluationResources, EvaluationEvidenceWrite, ExperimentRef,
    EvidenceRef)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
PACKAGE = EX/'src/strategy_runtime'
sys.path.append(str(EX.parent/'EX017_20261017/src'))
from pinned_inputs import get_context


def no_network(*args, **kwargs):
    raise RuntimeError('EX035 only uses authenticated offline pinned providers')


# Spawned public evaluation workers also import this module.
requests.sessions.Session.request = no_network


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.write('\n')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def inventory():
    inv = read(ROOT/'research/S014/materials/20261018_e9_extension_review/inventory.json')
    nodes = sorted((r for r in inv['events'] if r['eligible'] and r['route']=='PUBLIC_H_REPLAY_REQUIRED'),
                   key=lambda r: (r['E2'], r['cycle_id']))
    assert len(nodes)==68
    return [None]+nodes


def build():
    design=read(EX/'protocols/design.json')
    assert design['execution_authorized'] and design['current_authorization']=='批准执行'
    assert EvidenceRef.from_dict(read(EX/'protocols/published_design.json')).resolve(ROOT).read_bytes()==(EX/'protocols/design.json').read_bytes()
    for relative, expected in design['source_review_hashes'].items():
        assert digest(ROOT/relative)==expected
    checked=read(EX/'others/precheck.json')
    assert checked['status']=='PASS'
    files=('strategies/repair_e9.py','strategies/calibration_samples.csv')
    source_hash=implementation_sha256(files,source_root=PACKAGE)
    rows=[]
    for i,node in enumerate(inventory()):
        cid=f'C{9000+i:04}'
        assert not (ROOT/'research/S014/assets/candidates'/cid).exists()
        payload={'runtime':{'module':'strategy_runtime.strategies.repair_e9','qualname':'RepairStrategy',
                  'contract_version':1,'source_files':list(files),'source_sha256':source_hash},
                 'parameters':{'variant':'high_H3','intervention_entry_date':node['entry_date'] if node else ''}}
        candidate=StrategyCandidate('S014',cid,payload,PACKAGE)
        description=StrategyRuntime().describe(candidate)
        write(EX/f'protocols/payloads/{i:03}.json',payload)
        rows.append({'index':i,'node':node,'candidate':candidate.reference_id,
                     'runtime_sha256':description.runtime_sha256,'payload_sha256':digest(EX/f'protocols/payloads/{i:03}.json')})
    write(EX/'protocols/execution_lock.json',{'status':'LOCKED_BEFORE_ACCOUNTS','runs':rows,
        'source_sha256':source_hash,'diagnostic_only':True,'registered_candidates':0,
        'source_hashes':{p.relative_to(EX).as_posix():digest(p) for p in [Path(__file__), EX/'src/audit_accounts.py',EX/'src/precheck.py',EX/'others/precheck.json',EX/'protocols/design.json',*[PACKAGE/f for f in files]]},
        'maximum_account_dispatches':69,'automatic_retries':0})
    print('LOCKED 69 diagnostic identities; no account dispatched',flush=True)


def execute(phase):
    from audit_accounts import audit_control, audit_path
    lock=read(EX/'protocols/execution_lock.json')
    for relative,expected in lock['source_hashes'].items():
        assert digest(EX/relative)==expected,relative
    assert lock['status']=='LOCKED_BEFORE_ACCOUNTS'
    indices={'control':[0],'pilot':[1],'batch':list(range(2,69))}[phase]
    if phase!='control':assert read(EX/'others/gate_control.json')['status']=='PASS'
    if phase=='batch':assert read(EX/'others/gate_pilot.json')['status']=='PASS'
    ctx=get_context(resources=EvaluationResources(max_workers=2,native_threads_per_worker=1,random_seed=17))
    for offset in range(0,len(indices),2):
        group=indices[offset:offset+2]
        requests_bound=[]
        for i in group:
            row=lock['runs'][i]
            assert row['index']==i
            assert not (EX/f'others/dispatches/{i:03}.json').exists(), 'No retry after dispatch'
            path=EX/f'protocols/payloads/{i:03}.json'
            assert digest(path)==row['payload_sha256']
            payload=read(path)
            candidate=StrategyCandidate('S014',f'C{9000+i:04}',payload,PACKAGE)
            request=EvaluationRequest(repository_root=ROOT,experiment_id=EX.name,strategy=candidate,
                runtime_binding={'candidate_id':candidate.reference_id,'source_files':payload['runtime']['source_files'],
                    'implementation_sha256':payload['runtime']['source_sha256']},
                symbol='600722.SH',asset_type='stock',windows=(EvaluationWindow('full',date(2020,1,2),date(2026,10,15)),),
                data_cutoff=date(2026,10,15),initial_cash=100000,costs=(EvaluationCost('baseline',.001),),
                benchmark=EvaluationBenchmark(LimitBuyHold(100,.01,.01,.1,1000000)),workers=1)
            try:
                bound=ctx.evaluation.prepare(request)
            except Exception as exc:
                write(EX/f'others/prepare_failures/{i:03}.json',{'index':i,'error':repr(exc),'account_dispatched':False})
                raise
            requests_bound.append(bound)
            write(EX/f'others/bindings/{i:03}.json',{
                'candidate':candidate.reference_id,'payload':payload,'window':['2020-01-02','2026-10-15'],
                'initial_cash':100000,'one_way_cost':.001,'benchmark':request.benchmark.to_dict(),
                'execution_requests':{k:asdict(v) for k,v in bound.execution_data.requests.items()},
                'execution_prepared':asdict(bound.execution_data.prepared),
                'execution_identities':bound.execution_data.input_identities,
                'execution_fingerprint':bound.execution_data.fingerprint,
                'input_bindings':{k:v.to_dict() for k,v in bound.input_bindings.items()}})
            print('BOUND',i,row['node']['E2'] if row['node'] else 'NOOP',flush=True)
        count=len(list((EX/'others/dispatches').glob('*.json'))) if (EX/'others/dispatches').exists() else 0
        assert count+len(group)<=69
        for i in group:
            write(EX/f'others/dispatches/{i:03}.json',{'index':i,'phase':phase,'state':'DISPATCHED_COUNTS_EVEN_IF_UNKNOWN',
                'time_utc':datetime.now(timezone.utc).isoformat(),'maximum':69,'automatic_retry_allowed':False})
        print('DISPATCH',group,flush=True)
        outcomes=ctx.evaluation.evaluate_many(tuple(requests_bound))
        success=True
        for i,request,outcome in zip(group,requests_bound,outcomes,strict=True):
            node=lock['runs'][i]['node']
            receipt={'index':i,'node':node,'candidate':request.strategy.reference_id,'status':outcome.status.value,
                     'error':asdict(outcome.error) if outcome.error else None,'audit':None}
            if outcome.result is not None:
                ref=publish_evidence(ctx,EvaluationEvidenceWrite(ExperimentRef('S014',EX.name),f'e9-diagnostic-{i:03}',request,outcome.result))
                receipt['evidence']=ref.to_dict()
                receipt['result_hash']=outcome.result.result_hash
                account=read(ref.resolve(ROOT))
                try:
                    receipt['audit']=audit_control(account) if i==0 else audit_path(account,node)
                    assert receipt['audit']['status']=='PASS',receipt['audit']
                except Exception as exc:
                    receipt['audit']={'status':'FAILED','error':repr(exc)}
                    success=False
            else:success=False
            write(EX/f'others/accounts/run-{i:03}.json',receipt)
            print('ACCOUNT',i,receipt['status'],receipt['audit'],flush=True)
        if not success:
            raise RuntimeError('Account or equivalence audit failed; no retry and no further dispatch')
    if phase in ('control','pilot'):
        write(EX/f'others/gate_{phase}.json',{'status':'PASS','indices':indices,'source_lock_sha256':digest(EX/'protocols/execution_lock.json')})
    else:
        write(EX/'others/account_completion.json',{'status':'PASS','dispatched':69,'succeeded':69,
            'H_paths':68,'noop':1,'upstream_calls':0,'model_fits':0,'registered_candidates':0})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=('build','control','pilot','batch'))
    args=parser.parse_args()
    build() if args.phase=='build' else execute(args.phase)
