"""Check the locked reservation lifecycle and prepare the single new candidate."""
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
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def audit_reservation(h):
    entry=None;deadline=None;reservation=-1;pending=False
    for i,r in enumerate(h.itertuples()):
        if r.sell_filled_today:
            entry=None;deadline=None;pending=False
        if r.buy_filled_today:
            entry=i;deadline=i+9;reservation=i+10
        if r.held_at_close:
            pending=pending or i>=deadline or r.support_break
            assert r.target_position==(0. if pending else 1.)
        assert r.entry_index==(entry if entry is not None else -1)
        assert r.deadline_index==(deadline if deadline is not None else -1)
        assert r.reservation_index==reservation and r.exit_pending==pending
        if r.entry_signal:
            assert not r.held_at_close and not r.failed_buy_reset and r.ready and r.support_ok and i>=reservation
        if r.failed_buy_reset:
            assert r.target_position==0 and not r.entry_signal and not r.held_at_close
        if not r.held_at_close and i<reservation:
            assert not r.entry_signal and r.target_position==0


def main():
    destination=EX/'others/precheck.json'
    if destination.exists():raise RuntimeError('Preserve completed precheck')
    attempts=[]
    def prohibited(*args,**kwargs):
        attempts.append('ATTEMPTED');raise RuntimeError('No upstream access')
    requests.sessions.Session.request=prohibited
    checks=[]
    def check(name,value):
        assert bool(value),name
        checks.append(name)
    source=PACKAGE/'strategies/repair.py'
    strategy=module('ex023_reserve_precheck',source)
    old=module('ex021_support_precheck',OLD/'src/strategy_runtime/strategies/repair.py')
    shared=module('ex021_checks_reuse',OLD/'src/precheck.py')
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    check('exact locked single new variant',tuple(lock['new_variants'])==VARIANTS==('support_exit_reserve_H10',))
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
               for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
    variant=VARIANTS[0];args=shared.fixture();h=strategy.history(*args,variant)
    check('first entry no additional wait and prewindow excluded',h.warmup_sessions.iloc[0]==0 and not h.ready.iloc[:60].any()
          and h.entry_signal.iloc[60] and h.buy_filled_today.iloc[61] and h.reservation_index.iloc[61]==71)
    check('ordinary H10 sale and next day reentry',h.exit_pending.iloc[70] and h.sell_filled_today.iloc[71]
          and h.entry_signal.iloc[71] and h.buy_filled_today.iloc[72] and h.reservation_index.iloc[72]==82)
    early=shared.fixture()
    for f in early[:2]:f.loc[61,['Low','Close']]=[9.3,9.5]
    e=strategy.history(*early,variant)
    check('early exit unchanged E close break E+1 sale',e.buy_filled_today.iloc[61] and e.exit_pending.iloc[61]
          and e.sell_filled_today.iloc[62] and e.support_ok.iloc[62])
    check('restored support cannot buy before original E+10 close',e.support_ok.iloc[62:72].all()
          and not e.entry_signal.iloc[62:71].any() and e.reservation_index.iloc[62:72].eq(71).all()
          and e.entry_signal.iloc[71] and e.buy_filled_today.iloc[72])
    original_early=old.history(*early,'support_exit_H10')
    check('counterfactual original C immediately reenters',original_early.entry_signal.iloc[62] and original_early.buy_filled_today.iloc[63])
    late=shared.fixture()
    for f in late[:2]:
        f.loc[61,['Low','Close']]=[9.3,9.5]
        f.loc[62:72,['Open','High','Low','Close']]=9.
        f.loc[63,['Open','High','Low','Close']]=10.
    late[2].loc[62:72,'DownLimit']=9.
    late[3].loc[63,'Status']='SUSPENDED'
    late_h=strategy.history(*late,variant)
    check('failed SELL persists beyond reservation with recovered support',late_h.exit_pending.iloc[61:73].all()
          and not late_h.sell_filled_today.iloc[62:73].any() and late_h.support_ok.iloc[63]
          and late_h.sell_filled_today.iloc[73] and late_h.entry_signal.iloc[73] and late_h.buy_filled_today.iloc[74])
    failed=shared.fixture()
    for f in failed[:2]:f.loc[61,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
    nofill=strategy.history(*failed,variant)
    check('failed BUY reset and reservation only after actual fill',nofill.failed_buy_reset.iloc[61]
          and nofill.reservation_index.iloc[61]==-1 and not nofill.entry_signal.iloc[61]
          and nofill.entry_signal.iloc[62] and nofill.buy_filled_today.iloc[63] and nofill.reservation_index.iloc[63]==73)
    suspended=shared.fixture();suspended[3].loc[61,'Status']='SUSPENDED'
    halted=strategy.history(*suspended,variant)
    check('suspended BUY has no invented clock',halted.failed_buy_reset.iloc[61] and halted.reservation_index.iloc[61]==-1
          and halted.buy_filled_today.iloc[63] and halted.reservation_index.iloc[63]==73)
    below=shared.fixture()
    for f in below[:2]:f.loc[60,['Low','Close']]=[9.3,9.5]
    below_h=strategy.history(*below,variant)
    check('support excludes T and below support blocks entry',below_h.support_floor.iloc[60]==10. and not below_h.entry_signal.iloc[60])
    for name,frame in [('normal',h),('early',e),('late',late_h),('failed_buy',nofill),('suspended',halted)]:
        audit_reservation(frame);check('synthetic independent reservation reconstruction '+name,True)
    cross=shared.fixture();cross[1].loc[61:,['Open','High','Low','Close']]/=2.;cross[2].loc[61:,['DownLimit','UpLimit']]/=2.
    pd.testing.assert_frame_equal(strategy.history(*cross,variant),h,check_exact=True)
    check('HFQ raw scale leaves lifecycle unchanged',True)
    for params in ({},{'variant':None},{'variant':'support_exit_reserve_H9'},{'variant':'repeated_H10'},{'variant':variant,'reserve':10}):
        try:strategy.RepairStrategy.from_parameters(ParameterSet(params))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Illegal parameter accepted '+repr(params))
    check('illegal parameters rejected',True)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig())
    full=shared.FULL_REFERENCE
    prepared=PreparedDataRef(UUID(full['space_id']),UUID(full['preparation_id']),full['manifest_sha256'])
    datasets={};identities={}
    for dataset,symbol,start in ((Dataset.TRADING_CALENDAR,'SSE','2019-12-01'),
        (Dataset.STOCK_OHLCV,'600722.SH','2019-12-31'),(Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH','2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS,'600722.SH','2020-01-01'),(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01')):
        result=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared)
        check('authenticated offline input '+dataset.value,result.ready)
        datasets[dataset.value]=result.dataframe;identities[dataset.value]=result.identity.content_sha256
    args=[datasets[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    sessions=pd.DatetimeIndex(pd.to_datetime(args[0].Date));evaluation=sessions[sessions>=pd.Timestamp('2020-01-02')]
    inputs=dict(zip(('market','raw','limits','status'),args,strict=True))
    check('same1642 evaluation sessions and original startup',len(evaluation)==1642 and evaluation[59]==pd.Timestamp('2020-04-02'))
    equivalence=[]
    for base in ('support_entry_H10','support_exit_H10'):
        pd.testing.assert_frame_equal(strategy.history(*args,base),old.history(*args,base),check_exact=True)
        new_instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        old_instance=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        pd.testing.assert_frame_equal(new_instance.calculate_history(inputs,sessions),old_instance.calculate_history(inputs,sessions),check_exact=True)
        check('baseline full history and public observation exact '+base,new_instance.definition==old_instance.definition)
        equivalence.append(dict(variant=base,rows=len(sessions),all_history_columns_equal=True,public_observations_equal=True,complete_definition_equal=True,new_identity=False))
    instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}))
    original=old.RepairStrategy.from_parameters(ParameterSet({'variant':'support_exit_H10'}))
    check('new candidate unchanged execution inputs decision',instance.definition.execution==original.definition.execution
          and instance.definition.inputs==original.definition.inputs and instance.definition.decision==original.definition.decision)
    h=strategy.history(*args,variant);visible=instance.calculate_history(inputs,sessions)
    audit_reservation(h);check('real independent full reservation lifecycle',True)
    check('real original ready and first signal',h.index[h.ready][0]==evaluation[59] and h.index[h.entry_signal][0]==evaluation[59])
    expected=pd.Series(args[0].Close.to_numpy(),index=sessions).where(sessions>=pd.Timestamp('2020-01-02')).shift(1).rolling(5).min()
    check('real support unchanged',np.allclose(h.support_floor,expected,equal_nan=True))
    check('finite observations including reservation',all(np.isfinite(visible[n]).all() for n in (*strategy.OBSERVED,'reservation_index')))
    for stop in (60,61,62,72,500,1000,len(sessions)):
        cut=[f.loc[pd.to_datetime(f.Date).le(sessions[stop-1])].copy() for f in args]
        pd.testing.assert_frame_equal(strategy.history(*cut,variant),h.iloc[:stop],check_exact=True)
        check('causal prefix '+str(stop),True)
    changed=[f.copy() for f in args]
    for f in changed[:2]:f.loc[pd.to_datetime(f.Date).ge(sessions[1000]),['Open','High','Low','Close']]*=1.2
    changed[2].loc[pd.to_datetime(changed[2].Date).ge(sessions[1000]),['DownLimit','UpLimit']]*=1.2
    pd.testing.assert_frame_equal(strategy.history(*changed,variant).iloc[:1000],h.iloc[:1000],check_exact=True)
    check('future perturbation does not alter past',True)
    changed=[f.copy() for f in args]
    for f in changed[:2]:f.loc[pd.to_datetime(f.Date).lt(pd.Timestamp('2020-01-02')),['Open','High','Low','Close']]*=3.
    pd.testing.assert_frame_equal(strategy.history(*changed,variant),h,check_exact=True)
    check('prewindow excluded from signal and reservation',True)
    payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text())
    candidate=StrategyCandidate('S014','C0056',payload,PACKAGE)
    check('locked candidate identity',candidate.reference_id==lock['candidate_ids'][variant])
    runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex023-precheck'/variant))
    calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared)
    binding=StrategyInputBinding(runtime.plan_inputs(calendar),prepared)
    runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding)
    actual=runtime.inspect_signals()
    pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True)
    check('public prepare reprepare inspect1642',len(actual)==1642)
    check('zero upstream attempts',not attempts)
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',EX/f'protocols/payload_{variant}.json']
    check('new files LF only',all(b'\r' not in p.read_bytes() for p in paths))
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=[dict(variant=variant,candidate=candidate.reference_id,
        implementation_sha256=payload['runtime']['source_sha256'],signal_sessions=len(actual),first_ready_decision=str(evaluation[59].date()),
        input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest())],
        baseline_equivalence=equivalence,full_prepared_reference=full,input_content_sha256=identities,
        source_sha256=sha256(source.read_bytes()).hexdigest(),source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},
        account_runs=0,supplier_calls=0,supplier_attempts=0,
        observation_semantics={'reservation_index':'Last actual BUY source index+10; retained after SELL; -1 before first actualBUY. Flat entry requires current index>=reservation.','deadline_index':'Current actual BUY source index+9; -1 when flat; unchanged SELL clock.','index_origin':'2019-12-31 is source index0, excluded from60-session warmup.','baseline_columns':'B/C remain exactly original; only new reserve candidate adds reservation_index observation.'},
        pending=['Parent formal-account replay and independent actual-ledger audit.'])
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('EX023_PRECHECK_PASS',len(checks))


if __name__=='__main__':main()
