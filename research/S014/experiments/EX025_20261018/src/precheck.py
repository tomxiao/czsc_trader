"""Check that positive-candle confirmation changes only fresh BUY eligibility."""
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


def main():
    destination=EX/'others/precheck.json'
    if destination.exists():raise RuntimeError('Preserve completed precheck')
    attempts=[]
    def prohibited(*a,**kw):attempts.append('ATTEMPTED');raise RuntimeError('No upstream access')
    requests.sessions.Session.request=prohibited
    checks=[]
    def check(name,value):assert bool(value),name;checks.append(name)
    source=PACKAGE/'strategies/repair.py'
    strategy=module('ex025_up_entry',source);old=module('ex024_first_break',OLD/'src/strategy_runtime/strategies/repair.py')
    shared=module('ex021_fixture',EX.parent/'EX021_20261018/src/precheck.py')
    reserve_audit=module('ex023_clock_audit',EX.parent/'EX023_20261018/src/precheck.py')
    branch_audit=module('ex024_branch_audit',OLD/'src/precheck.py')
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    check('exact locked variants and baseline mapping',tuple(lock['new_variants'])==VARIANTS and lock['baseline_mapping']==strategy.UP_VARIANTS)
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
               for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
    def positive_fixture():
        a=shared.fixture()
        for f in a[:2]:f['Open']=9.99
        return a
    def audit(h,prices,variant):
        base=strategy.UP_VARIANTS[variant]
        if base=='support_entry_H10':shared.audit_lifecycle(h,base)
        elif base=='support_exit_reserve_H10':reserve_audit.audit_reservation(h)
        else:branch_audit.audit_branch(h,prices,base)
        assert not (h.entry_signal & ~h.up_candle).any()
    for variant in VARIANTS:
        base=strategy.UP_VARIANTS[variant]
        equal=strategy.history(*shared.fixture(),variant)
        check('equal candle rejected even above support '+variant,equal.ready.iloc[60] and equal.support_ok.iloc[60]
              and not equal.up_candle.any() and not equal.entry_signal.any())
        down=shared.fixture()
        for f in down[:2]:f['Open']=10.01
        dh=strategy.history(*down,variant)
        check('down candle rejected '+variant,not dh.entry_signal.any())
        args=positive_fixture();h=strategy.history(*args,variant)
        check('up candle keeps original startup and H10 '+variant,h.entry_signal.iloc[60] and h.buy_filled_today.iloc[61]
              and h.exit_pending.iloc[70] and h.sell_filled_today.iloc[71] and h.entry_signal.iloc[71] and h.buy_filled_today.iloc[72])
        check('B has no added reservation '+variant,('reservation_index' in h)==(base!='support_entry_H10'))
        below=positive_fixture()
        for f in below[:2]:f.loc[60,['Open','Low','Close']]=[9.4,9.3,9.5]
        bh=strategy.history(*below,variant)
        check('up candle cannot bypass support '+variant,bh.up_candle.iloc[60] and bh.support_break.iloc[60]
              and not bh.entry_signal.iloc[60] and bh.entry_signal.iloc[61])
        held_down=positive_fixture()
        for f in held_down[:2]:f.loc[62,'Open']=10.1
        hh=strategy.history(*held_down,variant)
        check('held down candle alone never forces exit '+variant,not hh.up_candle.iloc[62]
              and not hh.support_break.iloc[62] and not hh.exit_pending.iloc[62] and hh.target_position.iloc[62]==1.)
        pd.testing.assert_frame_equal(hh.drop(columns='up_candle'),h.drop(columns='up_candle'),check_exact=True)
        check('holding candle changes no lifecycle '+variant,True)
        early=positive_fixture()
        for f in early[:2]:
            f.loc[61:65,['Open','High','Low','Close']]=[11.9,12.2,11.8,12.]
            f.loc[61,['Open','Low']]=[9.99,9.8]
            f.loc[66,['Open','High','Low','Close']]=[12.,12.2,10.8,11.]
        eh=strategy.history(*early,variant)
        check('unchanged baseline-specific exit on negative candle '+variant,not eh.up_candle.iloc[66]
              and eh.support_break.iloc[66] and bool(eh.exit_pending.iloc[66])==(base!='support_entry_H10'))
        late=[f.copy() for f in early]
        for f in late[:2]:
            f.loc[67:72,['Open','High','Low','Close']]=9.
            f.loc[68,['Open','High','Low','Close']]=12.
        late[2].loc[67:72,'DownLimit']=9.;late[3].loc[68,'Status']='SUSPENDED'
        lh=strategy.history(*late,variant);start=70 if base=='support_entry_H10' else 66
        check('SELL latch ignores candle changes and remains through suspension '+variant,lh.exit_pending.iloc[start:73].all()
              and lh.sell_filled_today.iloc[73] and lh.entry_signal.iloc[73] and lh.buy_filled_today.iloc[74])
        failed=positive_fixture()
        for f in failed[:2]:f.loc[61,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
        fh=strategy.history(*failed,variant)
        check('failed BUY reset dominates up candle '+variant,fh.up_candle.iloc[61] and fh.failed_buy_reset.iloc[61]
              and not fh.entry_signal.iloc[61] and fh.entry_signal.iloc[62] and fh.buy_filled_today.iloc[63])
        suspended=positive_fixture();suspended[3].loc[61,'Status']='SUSPENDED'
        sh=strategy.history(*suspended,variant)
        check('suspended BUY reset unchanged '+variant,sh.failed_buy_reset.iloc[61] and not sh.entry_signal.iloc[61] and sh.buy_filled_today.iloc[63])
        if base=='support_first_profit_exit_H10':
            rejected=positive_fixture()
            for f in rejected[:2]:
                f.loc[61,['Low','Close']]=[9.3,9.5]
                f.loc[62:66,['Open','High','Low','Close']]=[11.9,12.2,11.8,12.]
                f.loc[67,['Open','High','Low','Close']]=[12.,12.2,10.8,11.]
            rh=strategy.history(*rejected,variant)
            check('P first rejection not reevaluated after profitable break '+variant,rh.first_break_evaluated.iloc[61]
                  and rh.float_pnl.iloc[61]<0 and not rh.early_exit_selected.iloc[61]
                  and rh.support_break.iloc[67] and rh.break_checked.iloc[67] and not rh.first_break_evaluated.iloc[62:71].any()
                  and rh.sell_filled_today.iloc[71])
            audit(rh,rejected[0],variant)
        for label,prices,history in [('normal',args,h),('below',below,bh),('held_down',held_down,hh),('early',early,eh),('late',late,lh),('failed',failed,fh),('suspended',suspended,sh)]:
            audit(history,prices[0],variant);check('independent baseline lifecycle and up-entry '+variant+'/'+label,True)
        cross=positive_fixture();cross[1].loc[61:,['Open','High','Low','Close']]/=2.;cross[2].loc[61:,['DownLimit','UpLimit']]/=2.
        pd.testing.assert_frame_equal(strategy.history(*cross,variant),h,check_exact=True)
        check('raw HFQ scale unchanged '+variant,True)
    for params in ({},{'variant':None},{'variant':'support_first_nonprofit_exit_H10'},{'variant':'support_up_entry_H9'},{'variant':VARIANTS[0],'candle_threshold':0.}):
        try:strategy.RepairStrategy.from_parameters(ParameterSet(params))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Illegal parameters accepted '+repr(params))
    check('illegal variants and threshold rejected',True)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig())
    full=shared.FULL_REFERENCE;prepared=PreparedDataRef(UUID(full['space_id']),UUID(full['preparation_id']),full['manifest_sha256'])
    datasets={};identities={}
    for dataset,symbol,start in ((Dataset.TRADING_CALENDAR,'SSE','2019-12-01'),(Dataset.STOCK_OHLCV,'600722.SH','2019-12-31'),
        (Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH','2019-12-31'),(Dataset.SECURITY_PRICE_LIMITS,'600722.SH','2020-01-01'),(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01')):
        f=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared)
        check('authenticated offline input '+dataset.value,f.ready);datasets[dataset.value]=f.dataframe;identities[dataset.value]=f.identity.content_sha256
    args=[datasets[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    sessions=pd.DatetimeIndex(pd.to_datetime(args[0].Date));evaluation=sessions[sessions>=pd.Timestamp('2020-01-02')]
    inputs=dict(zip(('market','raw','limits','status'),args,strict=True))
    check('same1642 evaluation sessions and startup',len(evaluation)==1642 and evaluation[59]==pd.Timestamp('2020-04-02'))
    equivalence=[]
    for base in strategy.UP_VARIANTS.values():
        pd.testing.assert_frame_equal(strategy.history(*args,base),old.history(*args,base),check_exact=True)
        a=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':base}));b=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        pd.testing.assert_frame_equal(a.calculate_history(inputs,sessions),b.calculate_history(inputs,sessions),check_exact=True)
        check('baseline history observations definition exact '+base,a.definition==b.definition)
        equivalence.append(dict(variant=base,rows=len(sessions),all_history_columns_equal=True,public_observations_equal=True,complete_definition_equal=True,new_identity=False))
    records=[]
    for variant in VARIANTS:
        base=strategy.UP_VARIANTS[variant];instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}));original=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        check('execution input decision unchanged '+variant,instance.definition.execution==original.definition.execution and instance.definition.inputs==original.definition.inputs and instance.definition.decision==original.definition.decision)
        h=strategy.history(*args,variant);visible=instance.calculate_history(inputs,sessions);audit(h,args[0],variant)
        check('real independent lifecycle and entry gate '+variant,True)
        check('exact real candle observation '+variant,np.array_equal(h.up_candle.to_numpy(),(args[0].Close>args[0].Open).to_numpy()))
        obs=[c for c in visible if c!='support_floor']
        check('finite public observations '+variant,all(np.isfinite(visible[c]).all() for c in obs))
        for stop in (60,61,62,72,500,1000,len(sessions)):
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
        runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex025-precheck'/variant))
        calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared);binding=StrategyInputBinding(runtime.plan_inputs(calendar),prepared)
        runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding);actual=runtime.inspect_signals()
        pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True);check('public prepare reprepare inspect1642 '+variant,len(actual)==1642)
        records.append(dict(variant=variant,baseline=base,candidate=candidate.reference_id,implementation_sha256=payload['runtime']['source_sha256'],signal_sessions=len(actual),first_ready_decision=str(evaluation[59].date()),first_actual_entry_signal=str(h.index[h.entry_signal][0].date()),input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()))
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',*list((EX/'protocols').glob('payload_*.json'))]
    check('new files LF',all(b'\r' not in p.read_bytes() for p in paths));check('zero upstream',not attempts)
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=records,baseline_equivalence=equivalence,full_prepared_reference=full,input_content_sha256=identities,
        source_sha256=sha256(source.read_bytes()).hexdigest(),source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},account_runs=0,supplier_calls=0,supplier_attempts=0,
        observation_semantics={'up_candle':'Current input HFQ Close>Open; equality false. Only new variants add this observation. Applies only to new flat-state BUY decision.','baseline_equivalence':'B/R/P history columns and observations remain exact. NewB has no reservation column; NewR/P preserve own actualBUY clock.','branch_and_reservation':'Identical to corresponding EX024 baseline; candle never changes held-state exit/latch/first-break decision.'},pending=['Formal account replay and independent actual-ledger audit.'])
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n');print('EX025_PRECHECK_PASS',len(checks))


if __name__=='__main__':main()
