"""Validate fixed H3/H5 clocks with exact H10 baseline equivalence."""
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
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def audit_clock(frame,market,variant):
    stem,H=variant.rsplit('_H',1);H=int(H)
    reserve=stem!='support_entry';conditional=stem=='support_first_profit_exit'
    entry=None;deadline=None;reservation=-1;pending=False;checked=False;price=0.
    for i,r in enumerate(frame.itertuples()):
        evaluated=False;selected=False;floating=0.
        if r.sell_filled_today:entry=None;deadline=None;pending=False;checked=False;price=0.
        if r.buy_filled_today:
            entry=i;deadline=i+H-1;reservation=i+H;checked=False
            if conditional:price=r.entry_fill_price
        if r.held_at_close:
            if conditional and not pending and not checked and i<deadline and r.support_break:
                checked=True;evaluated=True;floating=float(market.Close.iloc[i])/(price*1.001)-1
                selected=floating>0;pending=selected
            if i>=deadline or (stem=='support_exit_reserve' and r.support_break):pending=True
            assert r.target_position==(0. if pending else 1.) and r.holding_horizon==H
        assert r.entry_index==(entry if entry is not None else -1)
        assert r.deadline_index==(deadline if deadline is not None else -1) and r.exit_pending==pending
        if reserve:assert r.reservation_index==reservation
        if conditional:
            assert r.first_break_evaluated==evaluated and r.early_exit_selected==selected
            assert r.float_pnl==floating and r.break_checked==checked and r.entry_fill_price==price
        if r.entry_signal:
            assert not r.held_at_close and not r.failed_buy_reset and r.ready and r.support_ok
            assert not reserve or i>=reservation
            assert r.holding_horizon==H
        elif not r.held_at_close:assert r.holding_horizon==0
        if r.failed_buy_reset:assert not r.held_at_close and not r.entry_signal and r.target_position==0


def main():
    destination=EX/'others/precheck.json'
    if destination.exists():raise RuntimeError('Preserve completed precheck')
    attempts=[]
    def prohibited(*a,**kw):attempts.append('ATTEMPTED');raise RuntimeError('No upstream access')
    requests.sessions.Session.request=prohibited
    checks=[]
    def check(name,value):assert bool(value),name;checks.append(name)
    source=PACKAGE/'strategies/repair.py';strategy=module('ex026_short_clocks',source)
    old=module('ex024_H10_baselines',OLD/'src/strategy_runtime/strategies/repair.py')
    shared=module('ex021_fixture',EX.parent/'EX021_20261018/src/precheck.py')
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    check('exact locked six variants',tuple(lock['new_variants'])==VARIANTS==strategy.SHORT_VARIANTS)
    check('H3 H5 H10 only',set(strategy.parse_variant(v)[1] for v in strategy.VARIANTS)=={3,5,10})
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
               for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
    for variant in VARIANTS:
        base,H=strategy.parse_variant(variant);reserve=base!='support_entry_H10';conditional=base=='support_first_profit_exit_H10'
        entry=61;deadline=entry+H-1;sale=entry+H
        args=shared.fixture();h=strategy.history(*args,variant)
        check('same60-session startup without candle filter '+variant,h.entry_signal.iloc[60] and h.buy_filled_today.iloc[61]
              and h.warmup_sessions.iloc[0]==0 and not h.ready.iloc[:60].any() and 'up_candle' not in h)
        check('H-specific timeout execution and next reentry '+variant,h.target_position.iloc[entry:deadline].eq(1).all()
              and h.exit_pending.iloc[deadline] and h.sell_filled_today.iloc[sale]
              and h.entry_signal.iloc[sale] and h.buy_filled_today.iloc[sale+1])
        check('H-specific holding horizon '+variant,h.loc[h.held_at_close|h.entry_signal,'holding_horizon'].eq(H).all())
        check('B remains without reservation field '+variant,('reservation_index' in h)==reserve)
        if reserve:check('reservation actual E+H '+variant,h.reservation_index.iloc[entry]==sale)
        # Five-day support is unchanged even though the candidate horizon differs.
        changed=shared.fixture()
        for f in changed[:2]:f.loc[60,['Low','Close']]=[9.3,9.5]
        ch=strategy.history(*changed,variant)
        check('support remains previous5 and excludes T '+variant,ch.support_floor.iloc[60]==10. and ch.support_break.iloc[60] and not ch.entry_signal.iloc[60])
        positive=shared.fixture()
        for f in positive[:2]:f.loc[61,['Open','Low','Close']]=[9.,8.8,9.5]
        ph=strategy.history(*positive,variant)
        check('positive entry-day break honors exit role '+variant,ph.support_break.iloc[61]
              and bool(ph.exit_pending.iloc[61])==reserve and bool(ph.sell_filled_today.iloc[62])==reserve)
        if reserve:
            check('early exit waits to E+H close '+variant,not ph.entry_signal.iloc[62:sale].any()
                  and ph.entry_signal.iloc[sale] and ph.buy_filled_today.iloc[sale+1])
        negative=shared.fixture()
        for f in negative[:2]:
            f.loc[61,['Low','Close']]=[9.3,9.5]
            f.loc[62,['Low','Close']]=[9.2,9.4]
        nh=strategy.history(*negative,variant)
        check('negative entry-day branch '+variant,bool(nh.exit_pending.iloc[61])==(base=='support_exit_reserve_H10'))
        if conditional:
            check('first negative break rejected once then timeout '+variant,nh.first_break_evaluated.iloc[61]
                  and nh.float_pnl.iloc[61]<0 and not nh.early_exit_selected.iloc[61]
                  and nh.support_break.iloc[62] and not nh.first_break_evaluated.iloc[62:deadline+1].any()
                  and nh.sell_filled_today.iloc[sale])
            zero=shared.fixture()
            for f in zero[:2]:f.loc[61,['Open','Low','Close']]=[9.5,9.3,9.5*1.001]
            zh=strategy.history(*zero,variant)
            check('exact zero not profitable '+variant,zh.first_break_evaluated.iloc[61] and zh.float_pnl.iloc[61]==0
                  and not zh.early_exit_selected.iloc[61] and zh.sell_filled_today.iloc[sale])
            audit_clock(zh,zero[0],variant)
        boundary=shared.fixture()
        for f in boundary[:2]:f.loc[deadline,['Low','Close']]=[9.3,9.5]
        th=strategy.history(*boundary,variant)
        check('deadline break always timeout '+variant,th.support_break.iloc[deadline]
              and th.exit_pending.iloc[deadline] and th.sell_filled_today.iloc[sale])
        if conditional:check('P strict-before deadline excludes equality '+variant,not th.first_break_evaluated.iloc[deadline])
        last=shared.fixture()
        for f in last[:2]:
            f.loc[61,['Open','Low']]=[9.5,9.3]
            f.loc[deadline-1,['Low','Close']]=[9.7,9.9]
        ah=strategy.history(*last,variant)
        check('last admissible early-close boundary '+variant,ah.support_break.iloc[deadline-1]
              and bool(ah.sell_filled_today.iloc[deadline])==reserve)
        if conditional:check('P evaluates immediately before deadline '+variant,ah.first_break_evaluated.iloc[deadline-1] and ah.early_exit_selected.iloc[deadline-1])
        late=[f.copy() for f in positive];last_failed=sale+2;actual_sell=sale+3
        for f in late[:2]:
            f.loc[62:last_failed,['Open','High','Low','Close']]=9.
            f.loc[63,['Open','High','Low','Close']]=12.
        late[2].loc[62:last_failed,'DownLimit']=9.;late[3].loc[63,'Status']='SUSPENDED'
        lh=strategy.history(*late,variant);first_pending=61 if reserve else deadline
        check('failed SELL latched beyond shortened reservation '+variant,lh.exit_pending.iloc[first_pending:actual_sell].all()
              and lh.sell_filled_today.iloc[actual_sell] and lh.entry_signal.iloc[actual_sell] and lh.buy_filled_today.iloc[actual_sell+1])
        failed=shared.fixture()
        for f in failed[:2]:f.loc[61,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
        fh=strategy.history(*failed,variant)
        check('failed BUY reset starts clock only on later actual fill '+variant,fh.failed_buy_reset.iloc[61]
              and not fh.entry_signal.iloc[61] and fh.entry_signal.iloc[62] and fh.buy_filled_today.iloc[63]
              and fh.deadline_index.iloc[63]==63+H-1)
        suspended=shared.fixture();suspended[3].loc[61,'Status']='SUSPENDED'
        sh=strategy.history(*suspended,variant)
        check('suspended BUY reset unchanged '+variant,sh.failed_buy_reset.iloc[61] and sh.buy_filled_today.iloc[63] and sh.deadline_index.iloc[63]==63+H-1)
        for label,prices,history in [('normal',args,h),('positive',positive,ph),('negative',negative,nh),('timeout',boundary,th),('last',last,ah),('late',late,lh),('failed',failed,fh),('suspended',suspended,sh)]:
            audit_clock(history,prices[0],variant);check('independent synthetic clock '+variant+'/'+label,True)
        cross=shared.fixture();cross[1].loc[61:,['Open','High','Low','Close']]/=2.;cross[2].loc[61:,['DownLimit','UpLimit']]/=2.
        pd.testing.assert_frame_equal(strategy.history(*cross,variant),h,check_exact=True);check('raw HFQ scale unchanged '+variant,True)
    for params in ({},{'variant':None},{'variant':[]},{'variant':'support_entry_H03'},{'variant':'support_entry_H4'},
        {'variant':'support_entry_H20'},{'variant':'support_up_entry_H3'},{'variant':VARIANTS[0],'support_window':3}):
        try:strategy.RepairStrategy.from_parameters(ParameterSet(params))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Illegal parameters accepted '+repr(params))
    check('invalid horizon domain and extra parameters rejected',True)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig())
    full=shared.FULL_REFERENCE;prepared=PreparedDataRef(UUID(full['space_id']),UUID(full['preparation_id']),full['manifest_sha256'])
    datasets={};identities={}
    for dataset,symbol,start in ((Dataset.TRADING_CALENDAR,'SSE','2019-12-01'),(Dataset.STOCK_OHLCV,'600722.SH','2019-12-31'),
        (Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH','2019-12-31'),(Dataset.SECURITY_PRICE_LIMITS,'600722.SH','2020-01-01'),(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01')):
        f=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared)
        check('authenticated offline input '+dataset.value,f.ready);datasets[dataset.value]=f.dataframe;identities[dataset.value]=f.identity.content_sha256
    args=[datasets[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    sessions=pd.DatetimeIndex(pd.to_datetime(args[0].Date));evaluation=sessions[sessions>=pd.Timestamp('2020-01-02')]
    inputs=dict(zip(('market','raw','limits','status'),args,strict=True));check('same1642 sessions startup',len(evaluation)==1642 and evaluation[59]==pd.Timestamp('2020-04-02'))
    equivalence=[]
    for base in strategy.BASES:
        pd.testing.assert_frame_equal(strategy.history(*args,base),old.history(*args,base),check_exact=True)
        a=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':base}));b=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        pd.testing.assert_frame_equal(a.calculate_history(inputs,sessions),b.calculate_history(inputs,sessions),check_exact=True)
        check('baseline H10 history observations definition exact '+base,a.definition==b.definition)
        equivalence.append(dict(variant=base,rows=len(sessions),all_history_columns_equal=True,public_observations_equal=True,complete_definition_equal=True,new_identity=False))
    records=[]
    for variant in VARIANTS:
        base,H=strategy.parse_variant(variant);instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}));original=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        check('execution input decision unchanged '+variant,instance.definition.execution==original.definition.execution and instance.definition.inputs==original.definition.inputs and instance.definition.decision==original.definition.decision and instance.definition.observation==original.definition.observation)
        h=strategy.history(*args,variant);visible=instance.calculate_history(inputs,sessions);audit_clock(h,args[0],variant)
        check('real independent lifecycle '+variant,True)
        expected=pd.Series(args[0].Close.to_numpy(),index=sessions).where(sessions>=pd.Timestamp('2020-01-02')).shift(1).rolling(5).min()
        check('support5 remains independent of horizon '+variant,np.allclose(h.support_floor,expected,equal_nan=True))
        check('finite observations '+variant,all(np.isfinite(visible[c]).all() for c in visible if c!='support_floor'))
        for stop in (60,61,62,61+H,62+H,500,1000,len(sessions)):
            cut=[f.loc[pd.to_datetime(f.Date).le(sessions[stop-1])].copy() for f in args]
            pd.testing.assert_frame_equal(strategy.history(*cut,variant),h.iloc[:stop],check_exact=True);check(f'causal prefix {variant}/{stop}',True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).ge(sessions[1000]),['Open','High','Low','Close']]*=1.2
        changed[2].loc[pd.to_datetime(changed[2].Date).ge(sessions[1000]),['DownLimit','UpLimit']]*=1.2
        pd.testing.assert_frame_equal(strategy.history(*changed,variant).iloc[:1000],h.iloc[:1000],check_exact=True);check('future perturbation '+variant,True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).lt(pd.Timestamp('2020-01-02')),['Open','High','Low','Close']]*=3.
        pd.testing.assert_frame_equal(strategy.history(*changed,variant),h,check_exact=True);check('prewindow invariance '+variant,True)
        payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text());candidate=StrategyCandidate('S014',lock['candidate_ids'][variant].split('-')[1],payload,PACKAGE)
        runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex026-precheck'/variant))
        calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared);binding=StrategyInputBinding(runtime.plan_inputs(calendar),prepared)
        runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding);actual=runtime.inspect_signals()
        pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True);check('public prepare reprepare inspect1642 '+variant,len(actual)==1642)
        records.append(dict(variant=variant,baseline=base,horizon=H,candidate=candidate.reference_id,implementation_sha256=payload['runtime']['source_sha256'],signal_sessions=len(actual),first_ready_decision=str(evaluation[59].date()),input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()))
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',*list((EX/'protocols').glob('payload_*.json'))]
    check('new files LF',all(b'\r' not in p.read_bytes() for p in paths));check('zero upstream',not attempts)
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=records,baseline_equivalence=equivalence,full_prepared_reference=full,input_content_sha256=identities,source_sha256=sha256(source.read_bytes()).hexdigest(),source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},account_runs=0,supplier_calls=0,supplier_attempts=0,
        observation_semantics={'holding_horizon':'Actual lockedH3/H5, or baselineH10, while held or aBUY is planned;0 otherwise.','deadline_index':'ActualBUY sourceindex+H-1;flat=-1.','reservation_index':'R/P actualBUY sourceindex+H retained acrossSELL/flat;B has no column.','support':'Previous5 completed evaluation closes, excludescurrent/prewindow;unchanged acrossH.','P':'Firstsupportbreak strictly before deadline only;samefill-basedP and once-only branch asH10.','index_origin':'2019-12-31 sourceindex0 excludedfrom60-sessionstartup.'},pending=['Formal account replay and independent actual-ledger audit.'])
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print('EX026_PRECHECK_PASS',len(checks))


if __name__=='__main__':main()
