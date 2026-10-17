"""Fixed-support timing, lifecycle and public SRT preparation; zero account runs."""
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

FULL_REFERENCE={'space_id':'9b7260bb-f12c-4eab-bc37-884d0cc58c91',
                'preparation_id':'dfb12e42-f327-4e1b-bf25-d15201b4e69b',
                'manifest_sha256':'b68cf906d81e19a16b131fe63ca1f4f901f9baa202bae75110481b5f209d8f57'}


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture():
    dates=pd.DatetimeIndex([pd.Timestamp('2019-12-31'),*pd.bdate_range('2020-01-02',periods=100)])
    raw=pd.DataFrame({'Date':dates,'Open':10.,'High':10.2,'Low':9.8,'Close':10.,'Volume':100000.,'Amount':1000000.})
    limits=pd.DataFrame({'Date':dates,'DownLimit':5.,'UpLimit':20.})
    states=pd.DataFrame({'Date':dates,'Status':'TRADING'})
    return [raw.copy(),raw,limits,states]


def audit_lifecycle(h,variant):
    entry=None;deadline=None;pending=False
    for i,r in enumerate(h.itertuples()):
        if r.sell_filled_today:
            entry=None;deadline=None;pending=False
        if r.buy_filled_today:
            entry=i;deadline=i+9
        if r.held_at_close:
            pending=pending or i>=deadline or (variant=='support_exit_H10' and r.support_break)
            assert r.target_position==(0. if pending else 1.)
        assert r.entry_index==(entry if entry is not None else -1)
        assert r.deadline_index==(deadline if deadline is not None else -1)
        assert r.exit_pending==pending
        if r.entry_signal:
            assert not r.held_at_close and not r.failed_buy_reset and r.ready
            assert variant=='repeated_H10' or r.support_ok
        if r.failed_buy_reset:
            assert r.target_position==0 and not r.entry_signal and not r.held_at_close


def main():
    destination=EX/'others/precheck.json'
    if destination.exists():
        raise RuntimeError('Preserve completed precheck')
    attempts=[]
    def prohibited(*args,**kwargs):
        attempts.append('ATTEMPTED')
        raise RuntimeError('No upstream access')
    requests.sessions.Session.request=prohibited
    checks=[]
    def check(name,value):
        assert bool(value),name
        checks.append(name)
    source=PACKAGE/'strategies/repair.py'
    strategy=module('ex021_support_precheck',source)
    old=module('ex020_repair_precheck',OLD/'src/strategy_runtime/strategies/repair.py')
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
               for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
    check('exact fixed variants',tuple(strategy.VARIANTS)==VARIANTS)
    check('no calibration or environment source dependency','calibration' not in '\n'.join(source.read_text().splitlines()[1:]) and not (PACKAGE/'strategies/calibration_samples.csv').exists())
    for variant in VARIANTS:
        args=fixture();h=strategy.history(*args,variant)
        check('60 completed evaluation sessions exclude prewindow '+variant,
              h.warmup_sessions.iloc[0]==0 and h.warmup_sessions.iloc[59]==59 and h.warmup_sessions.iloc[60]==60
              and not h.ready.iloc[:60].any() and h.ready.iloc[60] and h.entry_signal.iloc[60] and h.buy_filled_today.iloc[61])
        check('H10 entry E61 decision E70 exit E71 '+variant,
              h.target_position.iloc[61:70].eq(1).all() and h.exit_pending.iloc[70] and h.sell_filled_today.iloc[71])
        check('sell-day close can plan next-session reentry '+variant,h.entry_signal.iloc[71] and not h.buy_filled_today.iloc[71] and h.buy_filled_today.iloc[72])
        audit_lifecycle(h,variant);check('synthetic clock independently reconstructed '+variant,True)
        changed=fixture()
        for f in changed[:2]:
            f.loc[60,['Low','Close']]=[9.3,9.5]
        lower=strategy.history(*changed,variant)
        check('previous-five support excludes current close '+variant,lower.support_floor.iloc[60]==10. and lower.support_break.iloc[60])
        check('A ignores support; B/C block below support '+variant,bool(lower.entry_signal.iloc[60])==(variant=='repeated_H10'))
        check('equality at support permits B/C entry '+variant,h.support_ok.iloc[60] and h.entry_signal.iloc[60])
        failed=fixture()
        for f in failed[:2]:
            f.loc[61,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
        nofill=strategy.history(*failed,variant)
        check('failed limit buy consumes attempt and skips same close '+variant,
              nofill.failed_buy_reset.iloc[61] and not nofill.entry_signal.iloc[61] and nofill.entry_signal.iloc[62] and nofill.buy_filled_today.iloc[63])
        suspended=fixture();suspended[3].loc[61,'Status']='SUSPENDED'
        halted=strategy.history(*suspended,variant)
        check('suspended BUY resets without false fill '+variant,halted.failed_buy_reset.iloc[61] and not halted.buy_filled_today.iloc[61] and halted.buy_filled_today.iloc[63])
        broken=fixture()
        for f in broken[:2]:
            f.loc[61,['Low','Close']]=[9.3,9.5]
        early=strategy.history(*broken,variant)
        check('entry-day break only C schedules next-session sale '+variant,
              bool(early.exit_pending.iloc[61])==(variant=='support_exit_H10') and bool(early.sell_filled_today.iloc[62])==(variant=='support_exit_H10'))
        delayed=fixture()
        sell_at=62 if variant=='support_exit_H10' else 71
        if variant=='support_exit_H10':
            for f in delayed[:2]:f.loc[61,['Low','Close']]=[9.3,9.5]
        for f in delayed[:2]:
            f.loc[sell_at,['Open','High','Low','Close']]=9.
            f.loc[sell_at+1,['Open','High','Low','Close']]=[10.,10.2,9.8,10.]
            f.loc[sell_at+2,['Open','High','Low','Close']]=[9.,9.01,9.,9.]
        delayed[2].loc[[sell_at,sell_at+2],'DownLimit']=9.
        delayed[3].loc[sell_at+1,'Status']='SUSPENDED'
        latched=strategy.history(*delayed,variant)
        check('failed sale and suspended recovery cannot revoke latch '+variant,
              latched.exit_pending.iloc[sell_at-1:sell_at+2].all() and latched.support_ok.iloc[sell_at+1]
              and not latched.sell_filled_today.iloc[sell_at:sell_at+2].any()
              and latched.target_position.iloc[sell_at-1:sell_at+2].eq(0).all() and latched.sell_filled_today.iloc[sell_at+2])
        audit_lifecycle(latched,variant);check('blocked/suspended lifecycle independently reconstructed '+variant,True)
        cross=fixture()
        cross[1].loc[61:,['Open','High','Low','Close']]/=2.
        cross[2].loc[61:,['DownLimit','UpLimit']]/=2.
        cross_h=strategy.history(*cross,variant)
        pd.testing.assert_frame_equal(cross_h,h,check_exact=True)
        check('HFQ/raw two-to-one scale leaves support and valid fills unchanged '+variant,True)
    ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S014'),providers=ProviderConfig())
    prepared=PreparedDataRef(UUID(FULL_REFERENCE['space_id']),UUID(FULL_REFERENCE['preparation_id']),FULL_REFERENCE['manifest_sha256'])
    datasets={};identities={}
    for dataset,symbol,start in ((Dataset.TRADING_CALENDAR,'SSE','2019-12-01'),
        (Dataset.STOCK_OHLCV,'600722.SH','2019-12-31'),(Dataset.STOCK_UNADJUSTED_DAILY,'600722.SH','2019-12-31'),
        (Dataset.SECURITY_PRICE_LIMITS,'600722.SH','2020-01-01'),(Dataset.SECURITY_TRADING_STATUS,'600722.SH','2019-12-01')):
        result=ctx.data.fetch(DataRequest(dataset,symbol,start,'2026-10-15','2026-10-15'),prepared=prepared)
        check('authenticated offline input '+dataset.value,result.ready)
        datasets[dataset.value]=result.dataframe;identities[dataset.value]=result.identity.content_sha256
    args=[datasets[n] for n in ('stock.ohlcv','stock.unadjusted_daily','security.price_limits','security.trading_status')]
    sessions=pd.DatetimeIndex(pd.to_datetime(args[0].Date))
    evaluation=sessions[sessions>=pd.Timestamp('2020-01-02')]
    check('full calendar evaluation count',len(evaluation)==1642 and sessions[0]==pd.Timestamp('2019-12-31'))
    first_decision=evaluation[59]
    inputs=dict(zip(('market','raw','limits','status'),args,strict=True))
    records=[]
    for variant in VARIANTS:
        instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}))
        original=old.RepairStrategy.from_parameters(ParameterSet({'variant':'baseline_H3'}))
        check('original execution/input/decision contract '+variant,
              instance.definition.execution==original.definition.execution and instance.definition.inputs==original.definition.inputs
              and instance.definition.decision==original.definition.decision)
        h=strategy.history(*args,variant)
        visible=instance.calculate_history(inputs,sessions)
        audit_lifecycle(h,variant);check('real full lifecycle independent reconstruction '+variant,True)
        check('real exact first eligible decision '+variant,h.index[h.ready][0]==first_decision and not h.loc[:evaluation[58],'entry_signal'].any())
        expected=pd.Series(args[0].Close.to_numpy(),index=sessions).where(sessions>=pd.Timestamp('2020-01-02')).shift(1).rolling(5).min()
        check('real support previous-five exact '+variant,np.allclose(h.support_floor,expected,equal_nan=True))
        check('finite declared public observations '+variant,all(np.isfinite(visible[c]).all() and pd.api.types.is_float_dtype(visible[c]) for c in strategy.OBSERVED))
        for stop in (60,61,62,500,1000,len(sessions)):
            cut=[f.loc[pd.to_datetime(f.Date).le(sessions[stop-1])].copy() for f in args]
            pd.testing.assert_frame_equal(strategy.history(*cut,variant),h.iloc[:stop],check_exact=True)
            check(f'causal prefix {variant}/{stop}',True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).ge(sessions[1000]),['Open','High','Low','Close']]*=1.2
        changed[2].loc[pd.to_datetime(changed[2].Date).ge(sessions[1000]),['DownLimit','UpLimit']]*=1.2
        pd.testing.assert_frame_equal(strategy.history(*changed,variant).iloc[:1000],h.iloc[:1000],check_exact=True)
        check('future price perturbation does not alter past '+variant,True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).lt(pd.Timestamp('2020-01-02')),['Open','High','Low','Close']]*=3.
        pd.testing.assert_frame_equal(strategy.history(*changed,variant),h,check_exact=True)
        check('prewindow prices never affect support or warmup '+variant,True)
        payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text())
        number=33+VARIANTS.index(variant)
        candidate=StrategyCandidate('S014',f'C{number:04}',payload,PACKAGE)
        runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex021-precheck'/variant))
        calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared)
        plan=runtime.plan_inputs(calendar)
        binding=StrategyInputBinding(plan,prepared)
        runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding)
        actual=runtime.inspect_signals()
        pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True)
        check('public prepare/reprepare/inspect full1642 '+variant,len(actual)==1642)
        records.append(dict(variant=variant,candidate=candidate.reference_id,implementation_sha256=payload['runtime']['source_sha256'],
                            input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                            prepared_reference=FULL_REFERENCE,signal_sessions=len(actual),first_signal=str(actual.index[0].date()),
                            last_signal=str(actual.index[-1].date()),first_ready_decision=str(first_decision.date()),
                            first_actual_entry_signal=str(h.index[h.entry_signal][0].date())))
        print('PRECHECK_VARIANT_PASS',variant,flush=True)
    for illegal in ('baseline_H3','support_entry_H5','',None):
        try:strategy.RepairStrategy.from_parameters(ParameterSet({'variant':illegal}))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Illegal variant accepted')
    check('invalid variants rejected',True);check('zero upstream attempts',not attempts)
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',*list((EX/'protocols').glob('payload_*.json'))]
    check('source closure and payload LF',all(b'\r' not in p.read_bytes() for p in paths))
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=records,
                full_prepared_reference=FULL_REFERENCE,input_content_sha256=identities,
                first_eligible_decision=str(first_decision.date()),first_possible_entry=str(evaluation[60].date()),
                source_sha256=sha256(source.read_bytes()).hexdigest(),
                source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},
                account_runs=0,supplier_calls=0,supplier_attempts=0,registered_or_published=False,
                observation_semantics={'support_floor':'Minimum of previous five evaluation-window completed HFQ closes, excluding current close; NaN before enough history, not a plotted observation.',
                    'ready':'At least60 completed evaluation sessions;2019-12-31 excluded.',
                    'deadline_index':'Actual buy index+9 (decision close); source index starts2019-12-31; -1 flat.',
                    'exit_pending':'Latched until actual sell, including resumed support and suspension.',
                    'holding_horizon':'Fixed10 from entry; C may exit earlier after support break.'},
                pending=['Reconcile actual formal-account fills, holdings and fees after parent execution.'])
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('EX021_PRECHECK_PASS',len(checks))


if __name__=='__main__':
    main()
