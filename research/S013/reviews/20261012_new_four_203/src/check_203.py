"""Immutable 203-candidate recorded-ledger review under current four gates.

No evaluator, provider, strategy calculation, perturbations or registrations.
Legacy strategy rules/fills stay original; a separately authenticated current
fixed1percent benchmark is used only for the derived economic comparison.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from math import isclose
from pathlib import Path
import sys

from strategy_evaluator import AssessmentEvidence
from strategy_runtime import canonical_sha256
from strategy_manager import StrategyRegistry, CandidateKey

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').exists())
WORK=ROOT/'.tmp/s013-new-four-203'
INVENTORY=ROOT/'research/S013/reviews/20261012_existing_candidates/review.json'
ECON=ROOT/'research/S013/experiments/EX074_20261011/src/economics_reference.py'
GATES=ROOT/'.tmp/s013-new-goal/gates_v2.py'

def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))

def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    out=importlib.util.module_from_spec(spec)
    sys.modules[name]=out
    spec.loader.exec_module(out)
    return out

def premiums(value,prefix=''):
    found={}
    if isinstance(value,dict):
        for key,item in value.items():
            path=prefix+'.'+key if prefix else key
            if key=='limit_premium':
                found[path]=float(item)
            else:
                found.update(premiums(item,path))
    return found

def benchmark():
    ref=read(ROOT/'research/S013/experiments/EX071_20261011/protocols/plan.json')['native_ref']
    path=ROOT/'research/S013/assets/evidence'/ref['experiment']['experiment_id']/ref['evidence_id']
    assert digest(path)==ref['sha256']
    d=read(path)
    assert d['schema_version']==6 and len(d['assessment_evidence'])==1
    from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
    validate_evaluation_evidence(d)
    a=AssessmentEvidence.from_dict(d['assessment_evidence'][0])
    e=module('review_econ_parent',ECON).economics(a)
    b={'source':path.relative_to(ROOT).as_posix(),'source_sha256':digest(path),'reference':ref,
       'content_sha256':a.candidate.content_sha256,'benchmark_contract':a.scenario_context.benchmark_contract_sha256,
       'data_identity':d['data_identity'],'request_identity':d['request_identity'],
       'benchmark_equity_sha256':canonical_sha256(list(a.benchmark_equity)),
       'benchmark_cagr':e['benchmark_cagr'],'benchmark_annual':e['benchmark_annual'],
       'session_axis_sha256':canonical_sha256([r.session for r in a.account]),
       'close_sha256':canonical_sha256([r.close for r in a.account]),
       'sessions':[r.session for r in a.account],'closes':[r.close for r in a.account],
       'initial_cash':a.initial_cash,'one_way_cost':a.scenario_context.one_way_cost}
    assert b['benchmark_contract']=='7c751496de5bc7cf108e28067a859666d42fd7687f37e08253778f49c7dc7099'
    assert len(b['sessions'])==1636 and b['sessions'][0]=='2020-01-02' and b['sessions'][-1]=='2026-09-30'
    return b

def one(task):
    entry,b=task
    cid=entry['candidate_id']
    path=ROOT/entry['source']
    assert digest(path)==entry['source_sha256']
    d=read(path)
    assert d['schema_version'] in (5,6) and len(d['assessment_evidence'])==1
    registry=StrategyRegistry(ROOT/'research/registrations')
    registered=registry.get_candidate(CandidateKey('S013',cid),evidence_root=ROOT/'research/S013')
    assert registered.content_sha256==entry['content_sha256']
    record=read(ROOT/f'research/registrations/S013/candidates/{cid}.json')['record']
    payload_path=ROOT/'research/S013'/record['payload']['path']
    assert digest(payload_path)==record['payload']['sha256']
    ps=premiums(read(payload_path))
    assert ps
    raw=d['assessment_evidence'][0]
    # Only a pure read bridge to the explicitly optional default; never publish
    # this object as a migrated/current evaluation or change the original file.
    adapted=dict(raw)
    bridge='NONE'
    if 'parameter_point' not in adapted:
        assert d['schema_version']==5
        adapted['parameter_point']=None
        bridge='READ_ONLY_MISSING_OPTIONAL_PARAMETER_POINT_NONE'
    a=AssessmentEvidence.from_dict(adapted)
    assert a.candidate.candidate_id=='S013-'+cid and a.candidate.content_sha256==registered.content_sha256
    assert d['data_identity']==b['data_identity']
    assert [r.session for r in a.account]==b['sessions']
    assert all(isclose(r.close,c,rel_tol=0,abs_tol=1e-12) for r,c in zip(a.account,b['closes'],strict=True))
    assert a.initial_cash==a.opening_cash==b['initial_cash']==1_000_000 and a.opening_quantity==0
    assert a.scenario_id=='baseline' and a.window_id=='full' and a.scenario_context.one_way_cost==b['one_way_cost']==.001
    req=d['request_identity']
    assert req['symbol']=='510500.SH' and req['price_basis']=='HFQ_RESEARCH'
    assert req['pricing']==b['request_identity']['pricing'] and req['initial_cash']==b['initial_cash']
    assert d['execution_mode']=='FULL'
    if d['schema_version']==6:
        from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
        validate_evaluation_evidence(d)
    else:
        assert req['benchmark']['execution']['type']=='NextOpenBuyHold'
    facts=module('review_econ_worker',ECON).economics(a)
    gate=module('review_gates_worker',GATES)
    comparison={**facts,'benchmark_cagr':b['benchmark_cagr'],'benchmark_annual':b['benchmark_annual']}
    reviewed=gate.from_economics(comparison)
    assert digest(path)==entry['source_sha256']
    return {'candidate_id':cid,'content_sha256':registered.content_sha256,
        'source':path.relative_to(ROOT).as_posix(),'source_sha256':digest(path),'schema_version':d['schema_version'],
        'status':'CHECKED_RECORDED_LEDGER_NEW_FOUR','economics':facts,
        'gates_v2':{**asdict(reviewed),'qualified':reviewed.qualified},'payload_premiums':ps,
        'strategy_premium_1pct':all(v==.01 for v in ps.values()),'read_bridge':bridge,
        'original_benchmark_contract':a.scenario_context.benchmark_contract_sha256,
        'data_pricing_sessions_cash_fee_match':'PASS','legacy_current_schema_claim':False,
        'registration_eligibility_changed':False,'result_hash':d['result_hash'],'request_hash':d['request_hash']}

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    inventory=read(INVENTORY)['registered_inventory']
    live={p.stem for p in (ROOT/'research/registrations/S013/candidates').glob('*.json')}
    assert len(inventory)==len(live)==203 and {r['candidate_id'] for r in inventory}==live
    b=benchmark()
    rows=[]
    with ProcessPoolExecutor(max_workers=8) as pool:
        pending={pool.submit(one,(row,b)):row for row in inventory}
        for future in as_completed(pending):
            rows.append(future.result())
            if len(rows)%25==0:
                print({'checked':len(rows),'total':203},flush=True)
    rows.sort(key=lambda r:r['candidate_id'])
    qualified=[r['candidate_id'] for r in rows if r['gates_v2']['qualified']]
    result={'kind':'IMMUTABLE_RECORDED_CENTRE_NEW_FOUR_REVIEW','status':'PRIMARY_PASS',
        'human_authorization':'先对这203个候选按新四门执行检查，看看有多少个能通过，尽快完成',
        'date':'2026-10-12','timezone':'Asia/Shanghai','candidate_count':203,
        'benchmark':b,'inventory_sha256':digest(INVENTORY),'gate_source':GATES.relative_to(ROOT).as_posix(),
        'gate_source_sha256':digest(GATES),'economics_source':ECON.relative_to(ROOT).as_posix(),
        'economics_source_sha256':digest(ECON),'review_source_sha256':digest(Path(__file__)),
        'qualified_centres':qualified,'qualified_count':len(qualified),
        'qualified_same_1pct_strategy':[r['candidate_id'] for r in rows if r['gates_v2']['qualified'] and r['strategy_premium_1pct']],
        'gate_pass_counts':{k:sum(r['gates_v2']['gates'][k] for r in rows) for k in rows[0]['gates_v2']['gates']},
        'original_strategy_premium_1pct_count':sum(r['strategy_premium_1pct'] for r in rows),
        'rows':rows,'resources':{'new_accounts':0,'new_experiments':0,'new_fits':0,'new_perturbations':0,
         'provider_calls':0,'historical_files_modified':0,'candidate_parameters_changed':0},
        'limits':['原195 schema5策略账本保留，固定当前1percentBH单独用于派生新门比较，不改写原结果或schema',
            '21个非1percent策略保持原参数；即使经济门通过也不能冒称完整当前统一1percent策略合同通过',
            '本次仅中心四门，不检验标准32/费用/五项自检，不更改登记资格或进入PTE']}
    with (WORK/'results.json').open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    print({k:result[k] for k in ('candidate_count','qualified_count','qualified_centres','qualified_same_1pct_strategy','gate_pass_counts','original_strategy_premium_1pct_count')},flush=True)

if __name__=='__main__':
    main()
