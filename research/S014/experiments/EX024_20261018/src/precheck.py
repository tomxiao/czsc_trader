"""Validate complementary first-break branches without running an account."""
import ast
from datetime import date
from hashlib import sha256
import importlib.util
import json
from uuid import UUID

import numpy as np
import pandas as pd
import requests
from dataflows import DataRequest,Dataset,PreparedDataRef,ProviderConfig
from czsc_trader.application import RepositoryContext,create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from strategy_runtime import ParameterSet,StrategyCandidate,StrategyInit,StrategyInputBinding,StrategyRuntime,TradableWindow
from build_candidates import ROOT,EX,OLD,PACKAGE,VARIANTS


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def audit_branch(h,market,variant):
    entry=None;deadline=None;reservation=-1;pending=False;checked=False;price=0.
    profit_variant=variant=='support_first_profit_exit_H10'
    for i,r in enumerate(h.itertuples()):
        evaluated=False;selected=False;floating=0.
        if r.sell_filled_today:entry=None;deadline=None;pending=False;checked=False;price=0.
        if r.buy_filled_today:
            entry=i;deadline=i+9;reservation=i+10;checked=False;price=r.entry_fill_price
            assert price>0
        if r.held_at_close:
            if not pending and not checked and i<deadline and r.support_break:
                evaluated=True;checked=True;floating=float(market.Close.iloc[i])/(price*1.001)-1
                selected=floating>0 if profit_variant else floating<=0
                pending=selected
            if i>=deadline:pending=True
            assert r.target_position==(0. if pending else 1.)
        assert r.entry_index==(entry if entry is not None else -1)
        assert r.deadline_index==(deadline if deadline is not None else -1)
        assert r.reservation_index==reservation and r.exit_pending==pending
        assert r.first_break_evaluated==evaluated and r.early_exit_selected==selected and r.break_checked==checked
        assert r.entry_fill_price==price and r.float_pnl==floating
        if r.entry_signal:
            assert not r.held_at_close and not r.failed_buy_reset and r.ready and r.support_ok and i>=reservation
        if r.failed_buy_reset:assert not r.entry_signal and not r.held_at_close and r.target_position==0
        if not r.held_at_close and i<reservation:assert not r.entry_signal and r.target_position==0


def main():
    destination=EX/'others/precheck.json'
    if destination.exists():raise RuntimeError('Preserve completed precheck')
    attempts=[]
    def prohibited(*args,**kwargs):attempts.append('ATTEMPTED');raise RuntimeError('No upstream access')
    requests.sessions.Session.request=prohibited
    checks=[]
    def check(name,value):assert bool(value),name;checks.append(name)
    source=PACKAGE/'strategies/repair.py'
    strategy=module('ex024_first_break',source)
    old=module('ex023_reserve',OLD/'src/strategy_runtime/strategies/repair.py')
    shared=module('ex021_fixture_reuse',EX.parent/'EX021_20261018/src/precheck.py')
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    check('exact locked complementary variants',tuple(lock['new_variants'])==VARIANTS==strategy.CONDITIONAL)
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
               for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))

    def positive(close=11.):
        args=shared.fixture()
        for f in args[:2]:
            f.loc[61:65,['Open','High','Low','Close']]=[12.,12.2,11.8,12.]
            f.loc[61,['Open','Low']]=[10.,9.8]
            f.loc[66,['Open','High','Low','Close']]=[12.,12.2,min(close,10.),close]
        return args

    for variant in VARIANTS:
        isprofit=variant=='support_first_profit_exit_H10'
        normal=shared.fixture();h=strategy.history(*normal,variant)
        check('original startup H10 and reservation '+variant,h.entry_signal.iloc[60] and h.buy_filled_today.iloc[61]
              and h.entry_fill_price.iloc[61]==10. and h.exit_pending.iloc[70] and h.sell_filled_today.iloc[71]
              and h.entry_signal.iloc[71] and h.buy_filled_today.iloc[72] and not h.first_break_evaluated.any())
        p=positive();ph=strategy.history(*p,variant)
        check('positive first-break branch '+variant,ph.first_break_evaluated.iloc[66] and ph.float_pnl.iloc[66]>0
              and bool(ph.early_exit_selected.iloc[66])==isprofit and bool(ph.sell_filled_today.iloc[67])==isprofit)
        if isprofit:
            check('early sale waits to original reservation '+variant,not ph.entry_signal.iloc[67:71].any()
                  and ph.entry_signal.iloc[71] and ph.buy_filled_today.iloc[72])
        else:
            check('positive rejection never rechecked after later negative break '+variant,
                  ph.support_break.iloc[67] and not ph.first_break_evaluated.iloc[67:71].any()
                  and ph.sell_filled_today.iloc[71])
        n=shared.fixture()
        for f in n[:2]:
            f.loc[61,['Low','Close']]=[9.3,9.5]
            f.loc[62:66,['Open','High','Low','Close']]=[12.,12.2,11.8,12.]
            f.loc[67,['Open','High','Low','Close']]=[12.,12.2,10.8,11.]
        nh=strategy.history(*n,variant)
        check('negative entry-day first break '+variant,nh.first_break_evaluated.iloc[61] and nh.float_pnl.iloc[61]<0
              and bool(nh.early_exit_selected.iloc[61])==(not isprofit) and bool(nh.sell_filled_today.iloc[62])==(not isprofit))
        if isprofit:
            check('negative rejection stays rejected despite later profitable break '+variant,nh.support_break.iloc[67]
                  and n[0].Close.iloc[67]>nh.entry_fill_price.iloc[67]*1.001 and nh.break_checked.iloc[67]
                  and not nh.first_break_evaluated.iloc[62:71].any() and nh.sell_filled_today.iloc[71])
        z=positive(10.*1.001);zh=strategy.history(*z,variant)
        check('exact zero belongs only to nonprofit '+variant,zh.first_break_evaluated.iloc[66]
              and zh.float_pnl.iloc[66]==0. and bool(zh.early_exit_selected.iloc[66])==(not isprofit))
        timeout=shared.fixture()
        for f in timeout[:2]:
            f.loc[61:69,['Open','High','Low','Close']]=[12.,12.2,11.8,12.]
            f.loc[61,['Open','Low']]=[10.,9.8]
            f.loc[70,['Open','High','Low','Close']]=[12.,12.2,10.8,11.]
        th=strategy.history(*timeout,variant)
        check('first break at deadline is unconditional timeout '+variant,th.support_break.iloc[70]
              and not th.first_break_evaluated.iloc[70] and th.exit_pending.iloc[70] and th.sell_filled_today.iloc[71])
        late=positive() if isprofit else shared.fixture()
        decision=66 if isprofit else 61
        if not isprofit:
            for f in late[:2]:f.loc[61,['Low','Close']]=[9.3,9.5]
        for f in late[:2]:
            f.loc[decision+1:72,['Open','High','Low','Close']]=9.
            f.loc[decision+2,['Open','High','Low','Close']]=12.
        late[2].loc[decision+1:72,'DownLimit']=9.
        late[3].loc[decision+2,'Status']='SUSPENDED'
        lh=strategy.history(*late,variant)
        check('selected SELL latched despite opposite P recovery and suspension '+variant,
              lh.early_exit_selected.iloc[decision] and lh.exit_pending.iloc[decision:73].all()
              and not lh.first_break_evaluated.iloc[decision+1:73].any()
              and lh.sell_filled_today.iloc[73] and lh.entry_signal.iloc[73] and lh.buy_filled_today.iloc[74])
        failed=shared.fixture()
        for f in failed[:2]:f.loc[61,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
        fh=strategy.history(*failed,variant)
        check('failed BUY reset creates no fill state '+variant,fh.failed_buy_reset.iloc[61]
              and fh.reservation_index.iloc[61]==-1 and fh.entry_fill_price.iloc[61]==0.
              and not fh.break_checked.iloc[61] and not fh.entry_signal.iloc[61]
              and fh.entry_signal.iloc[62] and fh.buy_filled_today.iloc[63])
        suspended=shared.fixture();suspended[3].loc[61,'Status']='SUSPENDED'
        sh=strategy.history(*suspended,variant)
        check('suspended BUY no clock or price state '+variant,sh.failed_buy_reset.iloc[61]
              and sh.reservation_index.iloc[61]==-1 and sh.entry_fill_price.iloc[61]==0. and sh.buy_filled_today.iloc[63])
        for label,prices,history in [('normal',normal,h),('positive',p,ph),('negative',n,nh),('zero',z,zh),('timeout',timeout,th),('late',late,lh),('failed',failed,fh)]:
            audit_branch(history,prices[0],variant);check('independent synthetic branch reconstruction '+variant+'/'+label,True)
        cross=shared.fixture();cross[1].loc[61:,['Open','High','Low','Close']]/=2.;cross[2].loc[61:,['DownLimit','UpLimit']]/=2.
        pd.testing.assert_frame_equal(strategy.history(*cross,variant),h,check_exact=True)
        check('raw HFQ scale unchanged '+variant,True)
    for params in ({},{'variant':None},{'variant':'support_exit_H10'},{'variant':'support_first_profit_exit_H9'},
                   {'variant':VARIANTS[0],'threshold':0.}):
        try:strategy.RepairStrategy.from_parameters(ParameterSet(params))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Illegal parameter accepted '+repr(params))
    check('illegal variants and threshold parameter rejected',True)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig())
    full=shared.FULL_REFERENCE;prepared=PreparedDataRef(UUID(full['space_id']),UUID(full['preparation_id']),full['manifest_sha256'])
    datasets={};identities={}
    for dataset,symbol,start in ((Dataset.TRADING_CALENDAR,'SSE','2019-12-01'),
        (Dataset.STOCK_OHLCV,'600722.SH','2019-12-31'),(Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH','2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS,'600722.SH','2020-01-01'),(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01')):
        fetched=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared)
        check('authenticated offline input '+dataset.value,fetched.ready)
        datasets[dataset.value]=fetched.dataframe;identities[dataset.value]=fetched.identity.content_sha256
    args=[datasets[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    sessions=pd.DatetimeIndex(pd.to_datetime(args[0].Date));evaluation=sessions[sessions>=pd.Timestamp('2020-01-02')]
    inputs=dict(zip(('market','raw','limits','status'),args,strict=True))
    check('same1642 evaluation sessions and startup',len(evaluation)==1642 and evaluation[59]==pd.Timestamp('2020-04-02'))
    equivalence=[]
    for base in ('support_entry_H10','support_exit_reserve_H10'):
        pd.testing.assert_frame_equal(strategy.history(*args,base),old.history(*args,base),check_exact=True)
        instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':base}));original=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        pd.testing.assert_frame_equal(instance.calculate_history(inputs,sessions),original.calculate_history(inputs,sessions),check_exact=True)
        check('baseline all columns observations definition exact '+base,instance.definition==original.definition)
        equivalence.append(dict(variant=base,rows=len(sessions),all_history_columns_equal=True,public_observations_equal=True,complete_definition_equal=True,new_identity=False))
    records=[]
    for variant in VARIANTS:
        instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}))
        original=old.RepairStrategy.from_parameters(ParameterSet({'variant':'support_exit_reserve_H10'}))
        check('new execution input decision contracts unchanged '+variant,instance.definition.execution==original.definition.execution
              and instance.definition.inputs==original.definition.inputs and instance.definition.decision==original.definition.decision)
        h=strategy.history(*args,variant);visible=instance.calculate_history(inputs,sessions)
        audit_branch(h,args[0],variant);check('real independent first-break lifecycle '+variant,True)
        check('finite branch observations '+variant,all(np.isfinite(visible[c]).all() for c in (*strategy.OBSERVED,'reservation_index',*strategy.BRANCH_OBSERVED)))
        check('first actual fill same original startup '+variant,h.index[h.entry_signal][0]==evaluation[59])
        for stop in (60,61,62,72,500,1000,len(sessions)):
            cut=[f.loc[pd.to_datetime(f.Date).le(sessions[stop-1])].copy() for f in args]
            pd.testing.assert_frame_equal(strategy.history(*cut,variant),h.iloc[:stop],check_exact=True)
            check(f'causal prefix {variant}/{stop}',True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).ge(sessions[1000]),['Open','High','Low','Close']]*=1.2
        changed[2].loc[pd.to_datetime(changed[2].Date).ge(sessions[1000]),['DownLimit','UpLimit']]*=1.2
        pd.testing.assert_frame_equal(strategy.history(*changed,variant).iloc[:1000],h.iloc[:1000],check_exact=True)
        check('future prices cannot change earlier branch '+variant,True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).lt(pd.Timestamp('2020-01-02')),['Open','High','Low','Close']]*=3.
        pd.testing.assert_frame_equal(strategy.history(*changed,variant),h,check_exact=True)
        check('prewindow excluded from support and startup '+variant,True)
        payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text())
        candidate=StrategyCandidate('S014',lock['candidate_ids'][variant].split('-')[1],payload,PACKAGE)
        runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex024-precheck'/variant))
        calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared);binding=StrategyInputBinding(runtime.plan_inputs(calendar),prepared)
        runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding)
        actual=runtime.inspect_signals()
        pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True)
        check('public prepare reprepare inspect1642 '+variant,len(actual)==1642)
        records.append(dict(variant=variant,candidate=candidate.reference_id,implementation_sha256=payload['runtime']['source_sha256'],
            signal_sessions=len(actual),first_ready_decision=str(evaluation[59].date()),
            input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()))
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',*list((EX/'protocols').glob('payload_*.json'))]
    check('new files LF only',all(b'\r' not in p.read_bytes() for p in paths));check('zero upstream attempts',not attempts)
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=records,baseline_equivalence=equivalence,
        full_prepared_reference=full,input_content_sha256=identities,source_sha256=sha256(source.read_bytes()).hexdigest(),
        source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},
        account_runs=0,supplier_calls=0,supplier_attempts=0,
        observation_semantics={'first_break_evaluated':'One-day event at first support break strictly before E+9; resets on next actualBUY.',
            'early_exit_selected':'One-day branch event; P>0 for profit, P<=0 for nonprofit. SelectedSELL remains latched.',
            'float_pnl':'Close/(actualHFQfill*1.001)-1 only on evaluation event;0 otherwise. No future exit fee/price.',
            'break_checked':'Current held cycle has evaluated first early break; remains true after rejection, resets on actualSELL/BUY.',
            'entry_fill_price':'Actual publicfill price in input HFQ scale while held,0 while flat. Ratio forP cancels account normalization.',
            'reservation_index':'Latest actualBUY source index+10,retained acrossSELL/flat,firstBUY before=-1.',
            'index_origin':'2019-12-31 sourceindex0,excluded from60-sessionwarmup.'},
        pending=['Parent formal replay and independent actual fill/branch audit.'])
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('EX024_PRECHECK_PASS',len(checks))


if __name__=='__main__':main()
