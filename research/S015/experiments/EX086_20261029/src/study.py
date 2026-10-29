"""Frozen S015-v1 entry census; research-unit event labels, not new accounts."""
# ruff: noqa: E402
import argparse
from datetime import datetime,time
from decimal import Decimal
from hashlib import sha256
import gzip
from io import StringIO
import json
import os
from pathlib import Path
from time import perf_counter

for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import cloudpickle
import pandas as pd
from czsc_trader.application import (RepositoryContext,create_research_context,validate_release_package,
    publish_evidence,validate_experiment)
from czsc_trader.research_tools import (ResearchBatchRef,ExperimentRef,ExecutionResources,EvidenceRef,
    MaterialEvidenceWrite,ExperimentReportWrite,ExperimentOutcome,ExperimentValidationRequest,ExperimentValidationScope)
from dataflows import ProviderConfig,canonical_frame_sha256
from strategy_manager import StrategyRegistry
from strategy_runtime import (StrategyRuntime,StrategyInit,StrategyRelease,RuntimeBinding,
    StrategyInputBinding,SignalHistoryMode,CycleTarget)
from strategy_runtime.execution_rules import ExecutionRuleInput,build_frozen_execution_plan
from trading_execution_engine import OrderSpec,DailyQuote,resolve_fill
from stats import summarize,match,nonoverlap,bootstrap,block_weights,concentration

ROOT=Path.cwd().resolve()
WORK=Path(__file__).resolve().parents[1]
OLD=ROOT/'research/S015/experiments/EX085_20261026/others/S015-v1'
REPO=RepositoryContext.discover(ROOT)
HORIZONS=(1,3,5,10,20)
PRIMARY=1
NAMES=('permission','entry_signal')
RELEASE='42213c1d07a712f712bcaef5a2fad21dc03b7660e6b24247209af51ece605cfc'


def read(path):
    return json.loads(path.read_bytes())


def save(path,value):
    path.write_bytes(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False).encode('utf-8'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def reference():
    return ExperimentRef('S015',WORK.name)


def context():
    scratch=ROOT/'.tmp/s015-entry-census'
    scratch.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(scratch)
    return create_research_context(REPO,ResearchBatchRef('S015'),providers=ProviderConfig(bindings={}),
        resources=ExecutionResources(2,1,17))


def old_refs():
    refs={r['name']:EvidenceRef.from_dict(r) for r in read(OLD/'published_equivalence_refs.json')}
    return {name:refs[name] for name in ('new_binding','new_CONTINUOUS_signals',
        'new_CONTINUOUS_orders','new_CONTINUOUS_fills','result')}


def inputs(ctx):
    manifest,runtime_binding,source=validate_release_package(REPO,'S015-v1')
    assert manifest['strategy_version_hash']==RELEASE
    request_ref=EvidenceRef.from_dict(read(OLD/'request_ref.json'))
    q=cloudpickle.loads(request_ref.resolve(ROOT).read_bytes())
    data=q.execution_data
    refs=old_refs()
    resolved={k:r.resolve(ROOT) for k,r in refs.items()}
    prior=read(resolved['result'])
    assert prior['new_release_hash']==RELEASE and prior['status']=='PASS'
    # Re-derive the current public plan against the original typed preparation.
    # The saved current binding is a JSON identity record, not a deserialization API.
    binding=next(iter(q.input_bindings.values()))
    hashes={}
    for name,request in binding.plan.requests.items():
        fetched=ctx.data.fetch(request,prepared=binding.prepared)
        assert fetched.ready
        hashes[name]=canonical_frame_sha256(fetched.dataframe)
        assert hashes[name]==fetched.identity.content_sha256==prior['source_hashes'][name]
    execution_hashes={}
    for name,request in data.requests.items():
        fetched=ctx.data.fetch(request,prepared=data.prepared)
        assert fetched.ready
        execution_hashes[name]=canonical_frame_sha256(fetched.dataframe)
        assert execution_hashes[name]==fetched.identity.content_sha256
    release=StrategyRelease.from_mapping(StrategyRegistry(REPO.strategy_root).get_version('S015','v1').to_dict())
    instance=StrategyRuntime(REPO.strategy_root,dataflows=ctx.data).create(StrategyInit(
        release,binding.plan.tradable_window,ROOT/'.tmp/s015-entry-census/runtime',
        source_root=source,runtime_binding=RuntimeBinding.from_dict(runtime_binding),pricing=data.pricing))
    calendar=ctx.data.fetch(binding.plan.requests[binding.plan.calendar_name],prepared=binding.prepared)
    plan=instance.plan_inputs(calendar)
    before,after=read(resolved['new_binding'])['plan'],plan.to_dict()
    before.pop('strategy')
    after.pop('strategy')
    assert before==after,'Current public plan differs from authenticated input contract'
    current=StrategyInputBinding(plan,binding.prepared)
    instance.prepare_data(binding=current)
    history=instance.inspect_signals(history_mode=SignalHistoryMode.CONTINUOUS)
    prior_history=pd.read_csv(resolved['new_CONTINUOUS_signals'],index_col=0,parse_dates=True,float_precision='round_trip')
    csv_history=pd.read_csv(StringIO(history.to_csv()),index_col=0,parse_dates=True,float_precision='round_trip')
    csv_history.index=csv_history.index.as_unit('ns')
    prior_history.index=prior_history.index.as_unit('ns')
    prior_history.index.name=history.index.name
    pd.testing.assert_frame_equal(csv_history,prior_history,check_freq=False,check_exact=True)
    assert data.pricing.basis.value=='HFQ_RESEARCH' and data.market_rules is not None
    assert pd.Timestamp(data.execution_daily.dt.max()).date().isoformat()=='2026-10-21'
    assert len(data.execution_daily)==435 and len(history)==434
    save(WORK/'others/input_identity.json',{'release':RELEASE,'manifest':manifest,
        'request_ref':request_ref.to_dict(),'old_refs':{k:r.to_dict() for k,r in refs.items()},
        'input_binding':current.to_dict(),'source_hashes':hashes,'execution_hashes':execution_hashes,
        'execution_fingerprint':data.fingerprint,'pricing':data.pricing.to_dict(),
        'signal_rows_exactly_reproduced':len(history),'window':prior['window'],
        'representation_normalization':'Same CSV round-trip parser on current and archived signals; date indexes in datetime64[ns], CSV empty strings/NA normalized, numerical values exact.'})
    return instance,history,data,resolved


def indexed(frame):
    return frame.copy().set_index('dt').sort_index()


def buy_limit(day,raw,execution,adjusted,policy):
    raw_close=float(raw.loc[day,'close'])
    close=float(execution.loc[day,'close'])
    req=ExecutionRuleInput(policy.policy_type,policy.settings,{},100000.,0,1.,
        float(adjusted.loc[day,'close']),close,price_scale=close/raw_close,
        unadjusted_reference_price=raw_close,cycle_target=CycleTarget(True,Decimal('1')),
        opening_signal_identity=sha256(str(day).encode()).hexdigest(),account_id='S015-entry-label')
    result=build_frozen_execution_plan(req)
    assert len(result['orders'])==1 and result['orders'][0]['side']=='BUY'
    return float(result['orders'][0]['limit_price'])


def fill(side,day,daily,intraday,rules,limit=None):
    bar=daily.loc[day]
    touches=intraday.loc[(intraday.index>=day)&(intraday.index<day+pd.Timedelta(days=1))]
    return resolve_fill(OrderSpec(side,'LIMIT' if side=='BUY' else 'MARKET',100,limit),
        session_open=float(bar['open']),session_time=datetime.combine(day.date(),time(9,30)),
        intraday_touches=[(dt.to_pydatetime(),float(r['low' if side=='BUY' else 'high'])) for dt,r in touches.iterrows()],
        daily_quote=DailyQuote(float(bar['low']),float(bar['high'])),session_limits=rules.for_session(day.date()))


def label(i,n,days,daily,intraday,rules,limit):
    signal,entry_day=days[i],days[i+1]
    row={'i':i,'n':n,'signal_at':str(signal.date()),'entry_at':str(entry_day.date()),
        'date':str(entry_day.date()),'month':entry_day.strftime('%Y-%m'),
        'stratum':entry_day.strftime('%Y-%m|09:30'),'information_return':None,'price_net_return':None,
        'entry_price':None,'exit_price':None,'close_path_min':None,'close_path_max':None,
        'entry_status':'NOT_OBSERVED','exit_status':'NOT_OBSERVED','limit_price':limit}
    if i+n<len(days):
        row['information_return']=float(daily.loc[days[i+n],'close']/daily.loc[signal,'close']-1)
    entry=fill('BUY',entry_day,daily,intraday,rules,limit)
    row.update(entry_price=entry.price,entry_status=entry.reason,entry_filled_at=str(entry.filled_at),entry_precision=entry.time_precision.value)
    if not entry.filled:
        row['status']='NO_ENTRY'
        return row
    if i+n+1>=len(days):
        row['status']='RIGHT_CENSORED_EXIT'
        return row
    held=daily.loc[days[i+1:i+n+1],'close']/entry.price-1
    row.update(close_path_min=float(min(0,held.min())),close_path_max=float(max(0,held.max())))
    exit_day=days[i+n+1]
    exit_=fill('SELL',exit_day,daily,intraday,rules)
    row.update(exit_price=exit_.price,exit_status=exit_.reason,exit_at=str(exit_day.date()),
        exit_filled_at=str(exit_.filled_at),exit_precision=exit_.time_precision.value)
    if not exit_.filled:
        row['status']='NO_EXIT'
        return row
    row.update(status='COMPLETE',price_net_return=float(exit_.price*.999/(entry.price*1.001)-1))
    return row


def verify_old_orders(paths,daily,raw,adjusted,intraday,rules,policy):
    orders=pd.read_csv(paths['new_CONTINUOUS_orders'],float_precision='round_trip')
    fills=pd.read_csv(paths['new_CONTINUOUS_fills'],float_precision='round_trip')
    checked=[]
    for _,r in orders.iterrows():
        day,signal=pd.Timestamp(r.execution_date),pd.Timestamp(r.signal_date)
        limit=buy_limit(signal,raw,daily,adjusted,policy) if r.side=='BUY' else None
        if r.side=='BUY':
            assert limit==r.limit_price
        outcome=fill(r.side,day,daily,intraday,rules,limit)
        old=fills.loc[fills.order_id==r.order_id]
        assert outcome.filled==(len(old)>0)
        assert len(old)<=1
        if len(old):
            assert outcome.price==float(old.iloc[0]['price'])
            assert pd.Timestamp(outcome.filled_at)==pd.Timestamp(old.iloc[0]['fill_time'])
        checked.append({'order_id':r.order_id,'signal_date':str(signal.date()),'execution_date':str(day.date()),
            'side':r.side,'filled':outcome.filled,'price':outcome.price,'reason':outcome.reason,
            'filled_at':str(outcome.filled_at),'price_precision':outcome.time_precision.value})
    assert len(orders)==109 and len(fills)==108
    save(WORK/'others/order_reproduction.json',{'status':'PASS','orders':len(orders),'fills':len(fills),'details':checked,
        'scope':'Same public fill prices and timestamps, not a new continuous account or funding replay.'})


def material(ctx,name,path):
    return publish_evidence(ctx,MaterialEvidenceWrite(reference(),name,path.read_bytes(),
        {'.json':'application/json','.gz':'application/gzip'}.get(path.suffix,'text/plain'),path.suffix[1:]))


def sources():
    return [(p.stem+'-source',p) for p in sorted((WORK/'src').glob('*.py')) if p.stem not in ('render','closeout')]


def run():
    start=perf_counter()
    ctx=context()
    checked=read(WORK/'others/checks.json')
    assert checked['status']=='PASS' and checked['sources']=={p.name:digest(p) for _,p in sources()}
    assert not (WORK/'others/pre_run_evidence.json').exists(),'Do not overwrite frozen run evidence'
    pairs=sources()+[('design',WORK/'protocols/design.md'),('checks',WORK/'others/checks.json'),
        ('overview-before',WORK/'others/overview_before.json')]
    pre={name:material(ctx,name,path).to_dict() for name,path in pairs}
    save(WORK/'others/pre_run_evidence.json',pre)
    print('PROTOCOL_AND_SOURCES_FROZEN',flush=True)
    instance,history,data,paths=inputs(ctx)
    daily,raw,adjusted,intraday=map(indexed,(data.execution_daily,data.raw_execution_daily,data.adjusted_daily,data.execution_intraday))
    days=list(daily.index)
    assert not daily.index.duplicated().any() and not daily.isna().any().any()
    assert not data.market_rules.suspended_sessions
    verify_old_orders(paths,daily,raw,adjusted,intraday,data.market_rules,instance.definition.execution)
    print('FROZEN_HISTORY_AND_109_ORDERS_REPRODUCED',flush=True)
    eligible=[i for i,d in enumerate(days[:-1]) if d in history.index and bool(history.loc[d,'feature_ready'])]
    limits={i:buy_limit(days[i],raw,daily,adjusted,instance.definition.execution) for i in eligible}
    flags={name:{i for i in eligible if bool(history.loc[days[i],name])} for name in NAMES}
    # The stateful entry pulse must always be a subset of that day's independent permission.
    assert flags['entry_signal']<=flags['permission']
    date_keys=[str(d.date()) for d in days[1:]]
    weights,weight_hash=block_weights(len(date_keys),replicates=1000,block=20,seed=17)
    summaries,all_rows,draws={},{},{}
    for n in HORIZONS:
        rows=[label(i,n,days,daily,intraday,data.market_rules,limits[i]) for i in eligible]
        for r in rows:
            r['signals']=[name for name in NAMES if r['i'] in flags[name]]
        result={'all':summarize(rows),'signals':{}}
        for name in NAMES:
            chosen=[r for r in rows if name in r['signals']]
            members=nonoverlap(sorted(flags[name]),n)
            reduced=[r for r in chosen if r['i'] in members]
            value={'raw':summarize(chosen),'nonoverlap':summarize(reduced),
                'matched_raw':match(rows,chosen),'matched_nonoverlap':match(rows,reduced),
                'concentration_raw':concentration(chosen),'concentration_nonoverlap':concentration(reduced)}
            if n==PRIMARY:
                value['years']={}
                value['months']={}
                for group in sorted({r['month'] for r in rows}):
                    selected=[r for r in chosen if r['month']==group]
                    value['months'][group]=summarize(selected)
                for year in sorted({r['date'][:4] for r in rows}):
                    selected=[r for r in chosen if r['date'].startswith(year)]
                    controls=[r for r in rows if r['date'].startswith(year)]
                    value['years'][year]={'raw':summarize(selected),'matched':match(controls,selected)}
                for mode,pop in [('raw',chosen),('nonoverlap',reduced)]:
                    value['bootstrap_'+mode],draws[f'{name}_{n}_{mode}']=bootstrap(rows,pop,rows,date_keys,weights)
            result['signals'][name]=value
        summaries[str(n)]=result
        all_rows[str(n)]=rows
    facts=[{'i':i,'signal_at':str(days[i].date()),'entry_at':str(days[i+1].date()),
        'permission':i in flags['permission'],'entry_signal':i in flags['entry_signal'],
        'center_gain':float(history.loc[days[i],'center_gain']),'p':float(history.loc[days[i],'p']),
        'm':float(history.loc[days[i],'m']),'repair_space':float(history.loc[days[i],'repair_space'])} for i in eligible]
    for name,value in [('events',all_rows),('signal_facts',facts),('bootstrap_draws',draws)]:
        (WORK/f'others/{name}.json.gz').write_bytes(gzip.compress(json.dumps(value,allow_nan=False).encode(),mtime=0))
    save(WORK/'others/analysis.json',{'schema':'s015-entry-census/v1','experiment':reference().to_dict(),
        'release':RELEASE,'primary_horizon':PRIMARY,'eligible':len(eligible),'signals':{k:len(v) for k,v in flags.items()},
        'horizons':summaries,'bootstrap':{'replicates':1000,'block_sessions':20,'seed':17,'sessions':len(date_keys),'starts_sha256':weight_hash},
        'sources':{p.name:digest(p) for _,p in sources()},'protocol_sha256':digest(WORK/'protocols/design.md'),
        'artifacts':{name:digest(WORK/f'others/{name}.json.gz') for name in ('events','signal_facts','bootstrap_draws')},
        'input_identity_sha256':digest(WORK/'others/input_identity.json'),
        'order_reproduction_sha256':digest(WORK/'others/order_reproduction.json'),
        'new_accounts':0,'new_parameters':0,'new_data':False,'seconds':perf_counter()-start})
    print('CENSUS_COMPLETE',len(eligible),{k:len(v) for k,v in flags.items()},perf_counter()-start,flush=True)


def publish():
    ctx=context()
    pre=read(WORK/'others/pre_run_evidence.json')
    for name,path in sources()+[('design',WORK/'protocols/design.md'),('checks',WORK/'others/checks.json')]:
        ref=EvidenceRef.from_dict(pre[name])
        ref.resolve(ROOT)
        assert digest(path)==ref.sha256,name
    validation=read(WORK/'others/result_validation.json')
    assert validation['status']=='PASS' and validation['analysis_sha256']==digest(WORK/'others/analysis.json')
    extras={}
    for path in sorted((WORK/'others').iterdir()):
        if path.name not in ('pre_run_evidence.json','publication.json','overview_after.json'):
            extras[path.name]=material(ctx,'result-'+path.name.replace('.','-'),path).to_dict()
    extras['render-source']=material(ctx,'render-source',WORK/'src/render.py').to_dict()
    retained=[*pre.values(),*extras.values(),*[r.to_dict() for r in old_refs().values()],read(OLD/'request_ref.json')]
    ref=publish_evidence(ctx,ExperimentReportWrite(reference(),digest(WORK/'report.md'),ExperimentOutcome.COMPLETED,
        tuple(EvidenceRef.from_dict(r) for r in retained)))
    result=validate_experiment(REPO,ExperimentValidationRequest(reference(),ExperimentValidationScope.REPORT_PUBLICATION))
    save(WORK/'others/publication.json',{'report':ref.to_dict(),'validation':result.to_dict(),'materials':extras})
    assert result.status.value=='PASS'
    print('REPORT_PUBLICATION_PASS',ref.sha256,flush=True)


def prepare():
    instance,_,data,paths=inputs(context())
    daily,raw,adjusted,intraday=map(indexed,(data.execution_daily,data.raw_execution_daily,data.adjusted_daily,data.execution_intraday))
    verify_old_orders(paths,daily,raw,adjusted,intraday,data.market_rules,instance.definition.execution)
    print('ORIGINAL_CONTRACT_REPRODUCTION_PASS',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('prepare','run','publish'))
    {'prepare':prepare,'run':run,'publish':publish}[parser.parse_args().action]()
