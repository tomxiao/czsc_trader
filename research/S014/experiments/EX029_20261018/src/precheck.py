"""Offline boundary checks for fixed exits and conditional H10 reservation."""
from datetime import date
from hashlib import sha256
import ast,importlib.util,json
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
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

def audit(h,market,variant):
    profit=variant=='support_exit_profit_reserve_H10';entry=None;deadline=None;reservation=-1;pending=False;checked=False;selected=False;price=0.
    for i,r in enumerate(h.itertuples()):
        evaluated=False;floating=0.
        if r.sell_filled_today:
            entry=None;deadline=None;pending=False;price=0.
            if checked and not selected:reservation=-1
        if r.buy_filled_today:entry=i;deadline=i+9;reservation=i+10;pending=False;checked=False;selected=True;price=r.entry_fill_price
        if r.held_at_close:
            if not pending and not checked and i<deadline and r.support_break:
                checked=True;evaluated=True;floating=float(market.Close.iloc[i])/(price*1.001)-1
                selected=floating>0 if profit else floating<=0
            pending=pending or i>=deadline or r.support_break
            assert r.target_position==(0. if pending else 1.)
        assert r.reservation_index==reservation and r.reservation_evaluated==evaluated
        assert r.reservation_selected==selected and r.reservation_checked==checked
        assert r.reservation_float_pnl==floating and r.entry_fill_price==price
        assert r.entry_index==(entry if entry is not None else -1) and r.deadline_index==(deadline if deadline is not None else -1)
        assert r.exit_pending==pending
        if r.entry_signal:assert not r.held_at_close and not r.failed_buy_reset and r.ready and r.support_ok and i>=reservation
        if r.failed_buy_reset:assert not r.entry_signal and not r.held_at_close

def main():
    dest=EX/'others/precheck.json'
    if dest.exists():raise RuntimeError('Preserve precheck')
    attempts=[]
    def block(*a,**kw):attempts.append(1);raise RuntimeError('No upstream')
    requests.sessions.Session.request=block;checks=[]
    def check(name,truth):assert bool(truth),name;checks.append(name)
    source=PACKAGE/'strategies/repair.py';strategy=module('ex029_reservations',source);old=module('ex023_baselines',OLD/'src/strategy_runtime/strategies/repair.py')
    shared=module('ex021_fixtures',EX.parent/'EX021_20261018/src/precheck.py');lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    check('locked two variants',tuple(lock['new_variants'])==VARIANTS==strategy.CONDITIONAL)
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name) for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('execution helper unchanged '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
    for variant in VARIANTS:
        profit=variant==VARIANTS[0];normal=shared.fixture();h=strategy.history(*normal,variant)
        check('startup and ordinary timeout '+variant,not h.ready.iloc[:60].any() and h.entry_signal.iloc[60] and h.buy_filled_today.iloc[61] and h.exit_pending.iloc[70] and h.sell_filled_today.iloc[71] and h.entry_signal.iloc[71] and not h.reservation_evaluated.iloc[:72].any())
        cases=[('normal',normal,h)]
        for label,opening,closing in [('positive',9.,9.5),('nonpositive',10.,9.5),('zero',9.5,9.5*1.001)]:
            args=shared.fixture()
            for f in args[:2]:f.loc[61,['Open','Low','Close']]=[opening,min(opening,closing)-.1,closing]
            hist=strategy.history(*args,variant);selected=(label=='positive')==profit
            check('entry-day early exit unchanged '+variant+'/'+label,hist.buy_filled_today.iloc[61] and hist.exit_pending.iloc[61] and hist.sell_filled_today.iloc[62] and hist.reservation_evaluated.iloc[61])
            check('P branch sign and equality '+variant+'/'+label,hist.reservation_selected.iloc[61]==selected and (hist.reservation_float_pnl.iloc[61]==0 if label=='zero' else (hist.reservation_float_pnl.iloc[61]>0)==(label=='positive')))
            if selected:
                check('selected reservation held across flat '+variant+'/'+label,not hist.entry_signal.iloc[62:71].any() and hist.reservation_index.iloc[62:72].eq(71).all() and hist.entry_signal.iloc[71] and hist.buy_filled_today.iloc[72])
            else:
                check('release only on actual SELL then reenter '+variant+'/'+label,hist.reservation_index.iloc[61]==71 and hist.reservation_index.iloc[62]==-1 and hist.entry_signal.iloc[62] and hist.buy_filled_today.iloc[63])
            cases.append((label,args,hist))
            late=[f.copy() for f in args]
            for f in late[:2]:
                f.loc[62:73,['Open','High','Low','Close']]=9.
                f.loc[63,['Open','High','Low','Close']]=12.
            late[2].loc[62:73,'DownLimit']=9.;late[3].loc[63,'Status']='SUSPENDED';lh=strategy.history(*late,variant)
            check('failed SELL latch and no reclassification '+variant+'/'+label,lh.exit_pending.iloc[61:74].all() and lh.reservation_index.iloc[61:74].eq(71).all() and lh.reservation_selected.iloc[61:75].eq(selected).all() and not lh.reservation_evaluated.iloc[62:75].any() and lh.sell_filled_today.iloc[74] and lh.entry_signal.iloc[74] and lh.buy_filled_today.iloc[75])
            cases.append(('late_'+label,late,lh))
        deadline=shared.fixture()
        for f in deadline[:2]:f.loc[70,['Low','Close']]=[9.3,9.5]
        dh=strategy.history(*deadline,variant)
        check('deadline equality is TIME not conditional '+variant,dh.support_break.iloc[70] and dh.exit_pending.iloc[70] and not dh.reservation_evaluated.iloc[70] and dh.sell_filled_today.iloc[71] and dh.entry_signal.iloc[71]);cases.append(('deadline',deadline,dh))
        boundary=shared.fixture()
        for f in boundary[:2]:
            f.loc[61,['Open','Low']]=[9.5,9.3]
            f.loc[69,['Low','Close']]=[9.3,9.9]
        bh=strategy.history(*boundary,variant)
        check('last strictly early day '+variant,bh.reservation_evaluated.iloc[69] and bh.reservation_float_pnl.iloc[69]>0 and bh.sell_filled_today.iloc[70] and bh.reservation_selected.iloc[69]==profit);cases.append(('last_early',boundary,bh))
        failed=shared.fixture()
        for f in failed[:2]:f.loc[61,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
        fh=strategy.history(*failed,variant)
        check('failed BUY resets until actual fill '+variant,fh.failed_buy_reset.iloc[61] and not fh.entry_signal.iloc[61] and fh.buy_filled_today.iloc[63] and fh.reservation_index.iloc[63]==73 and fh.deadline_index.iloc[63]==72);cases.append(('failedbuy',failed,fh))
        suspended=shared.fixture();suspended[3].loc[61,'Status']='SUSPENDED';sh=strategy.history(*suspended,variant)
        check('suspended BUY reset '+variant,sh.failed_buy_reset.iloc[61] and sh.buy_filled_today.iloc[63]);cases.append(('suspendedbuy',suspended,sh))
        cross=shared.fixture();cross[1].loc[61:,['Open','High','Low','Close']]/=2;cross[2].loc[61:,['DownLimit','UpLimit']]/=2
        pd.testing.assert_frame_equal(strategy.history(*cross,variant),h,check_exact=True);check('raw HFQ scale '+variant,True)
        for label,args,hist in cases:audit(hist,args[0],variant);check('independent state '+variant+'/'+label,True)
    for values in ({},{'variant':None},{'variant':[]},{'variant':'unknown'},{'variant':VARIANTS[0],'profit_threshold':.1}):
        try:strategy.RepairStrategy.from_parameters(ParameterSet(values))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Invalid parameter accepted')
    check('invalid parameters rejected',True)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig());full=shared.FULL_REFERENCE;prepared=PreparedDataRef(UUID(full['space_id']),UUID(full['preparation_id']),full['manifest_sha256'])
    datasets={};identities={}
    for dataset,symbol,start in ((Dataset.TRADING_CALENDAR,'SSE','2019-12-01'),(Dataset.STOCK_OHLCV,'600722.SH','2019-12-31'),(Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH','2019-12-31'),(Dataset.SECURITY_PRICE_LIMITS,'600722.SH','2020-01-01'),(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01')):
        f=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared);check('pinned ready '+dataset.value,f.ready);datasets[dataset.value]=f.dataframe;identities[dataset.value]=f.identity.content_sha256
    args=[datasets[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')];sessions=pd.DatetimeIndex(pd.to_datetime(args[0].Date));inputs=dict(zip(('market','raw','limits','status'),args,strict=True));equivalence=[]
    for base in old.VARIANTS:
        pd.testing.assert_frame_equal(strategy.history(*args,base),old.history(*args,base),check_exact=True)
        a=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':base}));b=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        pd.testing.assert_frame_equal(a.calculate_history(inputs,sessions),b.calculate_history(inputs,sessions),check_exact=True);check('baseline history observations definition exact '+base,a.definition==b.definition);equivalence.append({'variant':base,'rows':len(sessions),'all_columns_equal':True,'definition_equal':True,'new_identity':False})
    records=[]
    for variant in VARIANTS:
        instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}));baseline=old.RepairStrategy.from_parameters(ParameterSet({'variant':'support_exit_reserve_H10'}))
        check('execution inputs decision unchanged '+variant,instance.definition.execution==baseline.definition.execution and instance.definition.inputs==baseline.definition.inputs and instance.definition.decision==baseline.definition.decision)
        h=strategy.history(*args,variant);visible=instance.calculate_history(inputs,sessions);audit(h,args[0],variant);check('real independent lifecycle '+variant,True)
        check('finite observations '+variant,all(np.isfinite(visible[c]).all() for c in visible if c!='support_floor'))
        for stop in (60,61,62,63,69,70,71,72,500,1000,len(sessions)):
            cut=[f.loc[pd.to_datetime(f.Date).le(sessions[stop-1])].copy() for f in args];pd.testing.assert_frame_equal(strategy.history(*cut,variant),h.iloc[:stop],check_exact=True);check(f'causal prefix {variant}/{stop}',True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).ge(sessions[1000]),['Open','High','Low','Close']]*=1.2
        changed[2].loc[pd.to_datetime(changed[2].Date).ge(sessions[1000]),['DownLimit','UpLimit']]*=1.2
        pd.testing.assert_frame_equal(strategy.history(*changed,variant).iloc[:1000],h.iloc[:1000],check_exact=True);check('future perturbation '+variant,True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).lt(pd.Timestamp('2020-01-02')),['Open','High','Low','Close']]*=3
        pd.testing.assert_frame_equal(strategy.history(*changed,variant),h,check_exact=True);check('prewindow excluded '+variant,True)
        payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text());candidate=StrategyCandidate('S014',lock['candidate_ids'][variant].split('-')[1],payload,PACKAGE)
        runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex029-precheck'/variant));calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared);binding=StrategyInputBinding(runtime.plan_inputs(calendar),prepared)
        runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding);actual=runtime.inspect_signals();pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True);check('public prepare reprepare inspect1642 '+variant,len(actual)==1642)
        records.append(dict(variant=variant,candidate=candidate.reference_id,implementation_sha256=payload['runtime']['source_sha256'],signal_sessions=len(actual),input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()))
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',*list((EX/'protocols').glob('payload_*.json'))];check('all new files LF',all(b'\r' not in p.read_bytes() for p in paths));check('zero upstream',not attempts)
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=records,baseline_equivalence=equivalence,full_prepared_reference=full,input_content_sha256=identities,source_sha256=sha256(source.read_bytes()).hexdigest(),source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},account_runs=0,supplier_calls=0,observation_semantics={'reservation_evaluated':'Event only, first support break strictly before E+9 with no previous SELL intent.','reservation_selected':'Selection frozen after classification; default true on BUY to preserve natural TIME clock; persists across SELL/flat until next BUY.','reservation_checked':'First early classification completed; persists across SELL/flat until next BUY.','reservation_float_pnl':'Decision-close P event only,0 otherwise.','entry_fill_price':'Actual public BUY price in source HFQ scale while held;0 flat.','reservation_index':'ActualBUY E+10. Unselected early classification releases to -1 only on actualSELL; selected remains E+10 through flat.','baseline_C_R':'Existing fields and definitions unchanged; no new candidate identity.'},pending=['Formal account replay and independent actual-ledger audit.'])
    dest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n');print('EX029_PRECHECK_PASS',len(checks))
if __name__=='__main__':main()
