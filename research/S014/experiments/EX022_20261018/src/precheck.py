"""Initial-delay equivalence, causal lifecycle and public prepare; no accounts."""
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
    strategy=module('ex022_delay_precheck',source)
    old=module('ex021_support_precheck',OLD/'src/strategy_runtime/strategies/repair.py')
    old_checks=module('ex021_checks_reuse',OLD/'src/precheck.py')
    for name in ('tick','buy_limit'):
        nodes=[next(n for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
               for p in (source,OLD/'src/strategy_runtime/strategies/repair.py')]
        check('unchanged execution helper '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
    lock=json.loads((EX/'protocols/comparison_lock.json').read_text(encoding='utf-8'))
    check('exact locked new variants',tuple(lock['new_variants'])==VARIANTS)
    check('only A/B and fixed initial delay 0..10',len(strategy.VARIANTS)==22 and set(strategy.BASES)=={'repeated_H10','support_entry_H10'})
    check('no calibration source dependency','calibration' not in '\n'.join(source.read_text().splitlines()[1:]) and not (PACKAGE/'strategies/calibration_samples.csv').exists())
    for variant in strategy.VARIANTS:
        base,delay=strategy.parse_variant(variant)
        first=60+delay;entry=first+1;sale=entry+10
        args=old_checks.fixture();h=strategy.history(*args,variant)
        check('once-only initial warmup '+variant,
              h.warmup_sessions.iloc[0]==0 and h.warmup_sessions.iloc[first]==60+delay
              and not h.ready.iloc[:first].any() and h.ready.iloc[first]
              and h.entry_signal.iloc[first] and h.buy_filled_today.iloc[entry])
        check('fixed H10 and no recurrent delay '+variant,
              h.target_position.iloc[entry:sale-1].eq(1).all() and h.exit_pending.iloc[sale-1]
              and h.sell_filled_today.iloc[sale] and h.entry_signal.iloc[sale] and h.buy_filled_today.iloc[sale+1])
        old_checks.audit_lifecycle(h,base);check('independent lifecycle '+variant,True)
        if delay==0:
            pd.testing.assert_frame_equal(h,old.history(*args,base),check_exact=True)
            check('synthetic delay0 all-column equivalence '+base,True)
        changed=old_checks.fixture()
        for frame in changed[:2]:frame.loc[first,['Low','Close']]=[9.3,9.5]
        lower=strategy.history(*changed,variant)
        check('support excludes currentclose and remains unchanged '+variant,
              lower.support_floor.iloc[first]==10. and lower.support_break.iloc[first]
              and bool(lower.entry_signal.iloc[first])==(base=='repeated_H10'))
        failed=old_checks.fixture()
        for frame in failed[:2]:frame.loc[entry,['Open','High','Low','Close']]=[10.3,10.4,10.2,10.35]
        nofill=strategy.history(*failed,variant)
        check('failed BUY one-attempt reset unchanged '+variant,
              nofill.failed_buy_reset.iloc[entry] and not nofill.entry_signal.iloc[entry]
              and nofill.entry_signal.iloc[entry+1] and nofill.buy_filled_today.iloc[entry+2])
        suspended=old_checks.fixture();suspended[3].loc[entry,'Status']='SUSPENDED'
        halted=strategy.history(*suspended,variant)
        check('suspended BUY no false fill '+variant,
              halted.failed_buy_reset.iloc[entry] and not halted.buy_filled_today.iloc[entry] and halted.buy_filled_today.iloc[entry+2])
        delayed=old_checks.fixture()
        for frame in delayed[:2]:
            frame.loc[sale,['Open','High','Low','Close']]=9.
            frame.loc[sale+1,['Open','High','Low','Close']]=[10.,10.2,9.8,10.]
            frame.loc[sale+2,['Open','High','Low','Close']]=[9.,9.01,9.,9.]
        delayed[2].loc[[sale,sale+2],'DownLimit']=9.
        delayed[3].loc[sale+1,'Status']='SUSPENDED'
        latched=strategy.history(*delayed,variant)
        check('failed SELL latched through recovered support and suspension '+variant,
              latched.exit_pending.iloc[sale-1:sale+2].all() and latched.support_ok.iloc[sale+1]
              and not latched.sell_filled_today.iloc[sale:sale+2].any()
              and latched.target_position.iloc[sale-1:sale+2].eq(0).all() and latched.sell_filled_today.iloc[sale+2])
        old_checks.audit_lifecycle(latched,base)
        cross=old_checks.fixture()
        cross[1].loc[entry:,['Open','High','Low','Close']]/=2.
        cross[2].loc[entry:,['DownLimit','UpLimit']]/=2.
        pd.testing.assert_frame_equal(strategy.history(*cross,variant),h,check_exact=True)
        check('HFQ raw price scale unchanged '+variant,True)
    for params in ({'variant':None},{'variant':[]},{'variant':True},{'variant':'repeated_H10'},
        {'variant':'repeated_H10_delay-1'},{'variant':'repeated_H10_delay11'},
        {'variant':'repeated_H10_delay01'},{'variant':'support_exit_H10_delay0'},
        {'variant':'repeated_H10_delay1.0'},{'variant':'repeated_H10_delay1','delay':2},{}):
        try:strategy.RepairStrategy.from_parameters(ParameterSet(params))
        except (TypeError,ValueError):pass
        else:raise AssertionError('Illegal parameter accepted '+repr(params))
    check('invalid parameter names types and domains rejected',True)
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
    check('full evaluation count1642 and prewindow',len(evaluation)==1642 and sessions[0]==pd.Timestamp('2019-12-31'))
    inputs=dict(zip(('market','raw','limits','status'),args,strict=True))
    records=[];equivalence=[]
    for variant in strategy.VARIANTS:
        base,delay=strategy.parse_variant(variant)
        first_decision=evaluation[59+delay]
        instance=strategy.RepairStrategy.from_parameters(ParameterSet({'variant':variant}))
        original=old.RepairStrategy.from_parameters(ParameterSet({'variant':base}))
        check('unchanged execution input decision observation contracts '+variant,
              instance.definition.execution==original.definition.execution and instance.definition.inputs==original.definition.inputs
              and instance.definition.decision==original.definition.decision and instance.definition.observation==original.definition.observation)
        h=strategy.history(*args,variant);visible=instance.calculate_history(inputs,sessions)
        old_checks.audit_lifecycle(h,base);check('real lifecycle independently reconstructed '+variant,True)
        check('real exact earliest eligibility '+variant,
              h.index[h.ready][0]==first_decision and not h.loc[h.index<first_decision,'entry_signal'].any())
        expected=pd.Series(args[0].Close.to_numpy(),index=sessions).where(sessions>=pd.Timestamp('2020-01-02')).shift(1).rolling(5).min()
        check('real support definition exact '+variant,np.allclose(h.support_floor,expected,equal_nan=True))
        check('finite public observations '+variant,all(np.isfinite(visible[c]).all() and pd.api.types.is_float_dtype(visible[c]) for c in strategy.OBSERVED))
        for stop in sorted({60+delay,61+delay,62+delay,500,1000,len(sessions)}):
            cut=[f.loc[pd.to_datetime(f.Date).le(sessions[stop-1])].copy() for f in args]
            pd.testing.assert_frame_equal(strategy.history(*cut,variant),h.iloc[:stop],check_exact=True)
            check(f'causal prefix {variant}/{stop}',True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).ge(sessions[1000]),['Open','High','Low','Close']]*=1.2
        changed[2].loc[pd.to_datetime(changed[2].Date).ge(sessions[1000]),['DownLimit','UpLimit']]*=1.2
        pd.testing.assert_frame_equal(strategy.history(*changed,variant).iloc[:1000],h.iloc[:1000],check_exact=True)
        check('future perturbation does not change past '+variant,True)
        changed=[f.copy() for f in args]
        for f in changed[:2]:f.loc[pd.to_datetime(f.Date).lt(pd.Timestamp('2020-01-02')),['Open','High','Low','Close']]*=3.
        pd.testing.assert_frame_equal(strategy.history(*changed,variant),h,check_exact=True)
        check('prewindow excluded from warmup and support '+variant,True)
        if delay==0:
            pd.testing.assert_frame_equal(h,old.history(*args,base),check_exact=True)
            pd.testing.assert_frame_equal(visible,original.calculate_history(inputs,sessions),check_exact=True)
            check('real delay0 all-column and public observation equivalence '+base,True)
            equivalence.append({'variant':variant,'baseline_variant':base,'candidate_reuse':lock['baseline_reuse'][variant]['candidate'],
                'all_history_columns_equal':True,'public_observations_equal':True,'new_identity':False,
                'history_rows':len(h),'first_ready_decision':str(first_decision.date())})
            continue
        payload=json.loads((EX/f'protocols/payload_{variant}.json').read_text())
        candidate_id=lock['candidate_ids'][variant]
        candidate=StrategyCandidate('S014',candidate_id.split('-')[1],payload,PACKAGE)
        runtime=StrategyRuntime(ROOT,dataflows=ctx.data).create(StrategyInit(candidate,TradableWindow(date(2020,1,2),date(2026,10,15)),ROOT/'.tmp/s014-ex022-precheck'/variant))
        calendar=ctx.data.fetch(runtime.calendar_request(),prepared=prepared)
        plan=runtime.plan_inputs(calendar);binding=StrategyInputBinding(plan,prepared)
        runtime.prepare_data(binding=binding);runtime.prepare_data(binding=binding)
        actual=runtime.inspect_signals()
        pd.testing.assert_frame_equal(actual,visible.loc[actual.index],check_names=False,check_exact=True)
        check('public prepare reprepare inspect1642 '+variant,len(actual)==1642)
        records.append(dict(variant=variant,base=base,initial_delay=delay,candidate=candidate.reference_id,
            implementation_sha256=payload['runtime']['source_sha256'],
            input_binding_canonical_sha256=sha256(json.dumps(binding.to_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            prepared_reference=FULL_REFERENCE,signal_sessions=len(actual),first_signal=str(actual.index[0].date()),
            last_signal=str(actual.index[-1].date()),first_ready_decision=str(first_decision.date()),
            first_possible_entry=str(evaluation[60+delay].date()),first_actual_entry_signal=str(h.index[h.entry_signal][0].date())))
        print('PRECHECK_VARIANT_PASS',variant,flush=True)
    check('zero upstream attempts',not attempts)
    paths=[source,EX/'src/build_candidates.py',EX/'src/precheck.py',*list((EX/'protocols').glob('payload_*.json'))]
    check('source and payload LF',all(b'\r' not in p.read_bytes() for p in paths))
    check('exactly20 new payloads and two baseline reuses',len(records)==20 and len(equivalence)==2 and len(list((EX/'protocols').glob('payload_*.json')))==20)
    result=dict(status='PASS',check_count=len(checks),checks=checks,candidates=records,baseline_equivalence=equivalence,
        full_prepared_reference=FULL_REFERENCE,input_content_sha256=identities,
        source_sha256=sha256(source.read_bytes()).hexdigest(),
        source_files_sha256={p.relative_to(EX).as_posix():sha256(p.read_bytes()).hexdigest() for p in paths},
        account_runs=0,supplier_calls=0,supplier_attempts=0,registered_or_published=False,
        observation_semantics={'ready':'At least60+delay completed evaluation sessions, once only; execution prewindow excluded.',
            'warmup_sessions':'Unchanged cumulative evaluation sessions, never reset and never reduced by delay.',
            'support_floor':'Prior5 evaluation HFQ closes excluding current; unchanged by delay.',
            'entry_index':'Actual fill index, source index starts2019-12-31; -1 flat.',
            'deadline_index':'Actual buy index+9 decision close; -1 flat.',
            'exit_pending':'Latched once H10 reaches deadline until actual sale.',
            'holding_horizon':'Fixed10; delay only changes first eligibility, no support exit.'},
        pending=['Parent formal-account execution and independent actual-ledger audit.'])
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('EX022_PRECHECK_PASS',len(checks))


if __name__=='__main__':
    main()
