"""Fixed-exit equivalence and causal permission-exit checks; no accounts."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
import ast
from copy import deepcopy
from datetime import date
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import numpy as np
import pandas as pd
from czsc_trader.application import RepositoryContext,create_research_context
from czsc_trader.research_tools import ResearchBatchRef,ExecutionResources,EvidenceRef
from dataflows import DataRequest,Dataset,PreparedDataRef
from strategy_runtime import ParameterSet,TradableWindow

ROOT=Path(__file__).resolve().parents[5];HERE=Path(__file__).resolve().parents[1];BASE=HERE.parent


def read(path):return json.loads(path.read_bytes())
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);out=importlib.util.module_from_spec(spec);spec.loader.exec_module(out);return out


def main():
    old_here=BASE/'EX042_20261023';key='src/strategy_runtime/strategies/price_information.py'
    published=read(old_here/'others/published_refs.json')['materials']
    ref=EvidenceRef.from_dict(published[key]);old_source=old_here/key;source=HERE/key
    assert old_source.read_bytes()==ref.resolve(ROOT).read_bytes()
    old=module(old_source,'authenticated_fixed_exit_42');new=module(source,'permission_exit_45')
    checks=[]
    def record(name):checks.append(name)
    def function_ast(path,name):
        tree=ast.parse(path.read_text(encoding='utf-8'))
        return ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)
    assert function_ast(source,'causal_features')==function_ast(old_source,'causal_features')
    assert new.COLUMNS==old.COLUMNS and len(new.COLUMNS)==13
    record('all_13_feature_implementation_AST_identical_to_authenticated_EX042')
    schedules={};schedule_refs={}
    for family in ('A','B'):
        r=EvidenceRef.from_dict(published[f'others/models_{family}.json'])
        local=old_here/f'others/models_{family}.json'
        assert local.read_bytes()==r.resolve(ROOT).read_bytes()
        schedules[family]=read(local);schedule_refs[family]=r.to_dict()
    price_refs=read(BASE/'EX035_20261023/others/published_refs.json')['materials']
    inputref=EvidenceRef.from_dict(price_refs['others/input_refs.json'])
    inputfacts=read(inputref.resolve(ROOT));factref=EvidenceRef.from_dict(inputfacts['source_inputs']['inputs'])
    facts=read(factref.resolve(ROOT));ctx=create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S015'),resources=ExecutionResources(1,1,13))
    frames={};identities={}
    for dataset in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.ETF_UNADJUSTED_INTRADAY):
        minute=dataset==Dataset.ETF_UNADJUSTED_INTRADAY;p=facts['minute_prepared' if minute else 'daily_prepared']
        prep=PreparedDataRef(UUID(p['space_id']),UUID(p['preparation_id']),p['manifest_sha256'])
        req=DataRequest(dataset,'159326.SZ','2025-01-02' if minute else '2024-09-09','2026-10-21','2026-10-21',frequency='30m' if minute else 'daily')
        result=ctx.data.fetch(req,prepared=prep);assert result.ready,result.error
        assert result.identity.content_sha256==facts['identities'][dataset.value]['content_sha256']
        frames[dataset]=result.dataframe.sort_values('Date').reset_index(drop=True);frames[dataset].attrs={};identities[dataset.value]=result.identity.content_sha256
    adj,raw,bars=(frames[d] for d in (Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.ETF_UNADJUSTED_INTRADAY))
    x=new.causal_features(adj,raw,bars);oldx=old.causal_features(adj,raw,bars)
    pd.testing.assert_frame_equal(x,oldx,check_exact=True)
    assert len(x)==435 and not x.feature_ready.iloc[0] and x.feature_ready.iloc[1:].all()
    record('435_canonical_rows_and_13_actual_features_exactly_match_original')
    prefixes=(0,1,39,99,183,351,433)
    for pos in prefixes:
        small=new.causal_features(adj.iloc[:76+pos],raw.iloc[:76+pos],bars.iloc[:8*(pos+1)])
        pd.testing.assert_frame_equal(small,x.iloc[:pos+2],check_exact=True)
    record('seven_market_history_prefixes_exact')
    same_configs=[];permission_counts=[];prefix_count=0;scope_count=0
    calendar=tuple(pd.Timestamp(d).date() for d in adj.Date)
    for family in ('A','B'):
        for mode in ('path','risk','and'):
            for hold in (3,7):
                original={'family':family,'mode':mode,'hold':hold,'exposure':1.,'schedule':schedules[family]}
                fixed=new.intentions(x,{**original,'exit_rule':'fixed'})
                oldout=old.intentions(x,original)
                pd.testing.assert_frame_equal(fixed,oldout,check_exact=True)
                same_configs.append({'family':family,'mode':mode,'hold':hold,'canonical_rows':435,'development_rows':434})
                params={**original,'exit_rule':'permission'};out=new.intentions(x,params)
                for col in ('path_prediction','risk_prediction','risk_threshold','model_ready','permission'):
                    np.testing.assert_array_equal(out[col],oldout[col])
                # Independent scalar state transition with explicitly ordered events.
                age=0;expected=[];early=0;expired=0;opened=0
                for row in out.itertuples():
                    permitted=bool(row.permission)
                    if age>0:
                        if age>=hold:age=0;expired+=1
                        elif not permitted:age=0;early+=1
                        else:age+=1
                    elif permitted:age=1;opened+=1
                    expected.append(age)
                np.testing.assert_array_equal(out.intent_age,expected)
                np.testing.assert_array_equal(out.target_position,np.array(expected)>0)
                permission_counts.append({'family':family,'mode':mode,'hold':hold,'opened_intent_cycles':opened,'early_permission_exits':early,'maximum_age_exits':expired,'not_actual_trades':True})
                for pos in prefixes:
                    prefix=new.intentions(x.iloc[:pos+2],params)
                    pd.testing.assert_frame_equal(prefix,out.iloc[:pos+2],check_exact=True);prefix_count+=1
                runtime=new.PriceInformation(ParameterSet(params))
                histories=[]
                for start in (date(2025,1,2),date(2025,2,6)):
                    window=TradableWindow(start,date(2026,10,21));runtime.calendar_request(window)
                    scope=runtime.derive_calculation_scope(window,calendar)
                    assert scope.calculation_dates[0]==date(2024,12,31)
                    truncated={'market':adj[pd.to_datetime(adj.Date)<=pd.Timestamp(scope.inputs['market'].end)],
                      'execution':raw[pd.to_datetime(raw.Date)<=pd.Timestamp(scope.inputs['execution'].end)],
                      'intraday':bars[pd.to_datetime(bars.Date).dt.normalize()<=pd.Timestamp(scope.inputs['intraday'].end)]}
                    history=runtime.calculate_context_history(truncated,SimpleNamespace(sessions=pd.DatetimeIndex(scope.calculation_dates)))
                    pd.testing.assert_frame_equal(history,out.reindex(pd.DatetimeIndex(scope.calculation_dates)),check_exact=True)
                    histories.append(history);scope_count+=1
                pd.testing.assert_frame_equal(histories[0],histories[1],check_exact=True)
                definition=runtime.definition
                assert definition.execution.settings['exit']['order_type']=='MARKET'
                assert definition.execution.settings['capital']=={'fee_rate':.001,'mode':'available_cash_fraction','target_scope':'entry_cycle','allocation_fraction':1.}
    record('twelve_fixed_configs_A_B_path_risk_and_hold3_7_all435_outputs_exactly_equal_EX042')
    record('permission_mode_uses_identical_models_predictions_thresholds_and_permissions')
    record('twelve_permission_configs_independent_scalar_state_recompute')
    record('84_intention_prefixes_exact')
    record('24_runtime_window_scopes_replay_same_canonical_history')
    record('unchanged_market_sell_and_entry_cycle_available_cash_execution_contract')

    # Constant scheduled models isolate exit behavior without market outcomes.
    def schedule_item(day,path=1.,risk=0.,known=None):
        ix=x.index.get_loc(pd.Timestamp(day));known=known or x.index[ix-1].date().isoformat()
        model={'columns':['r1'],'center':[0.],'scale':[1.],'beta':[path,0.]}
        riskmodel={'columns':['r1'],'center':[0.],'scale':[1.],'beta':[risk,0.],'threshold':.1}
        return {'date':day,'train_known_max':known,'models':{'path':model,'risk':riskmodel}}
    seed=schedule_item('2025-01-02');base={'family':'A','mode':'and','hold':3,'exposure':1.,'schedule':[seed],'exit_rule':'permission'}
    always=new.intentions(x,base)
    assert always.intent_age.iloc[:10].tolist()==[0,1,2,3,0,1,2,3,0,1]
    record('permanent_permission_still_exits_at_hold_and_does_not_reenter_same_day')
    falling=deepcopy(base);falling['hold']=7;falling['schedule']+=[schedule_item('2025-01-03',path=-1.),schedule_item('2025-01-06',path=1.)]
    fallen=new.intentions(x,falling)
    assert fallen.intent_age.iloc[:5].tolist()==[0,1,0,1,2]
    pd.testing.assert_frame_equal(fallen.loc[:'2025-01-02'],new.intentions(x,{**falling,'schedule':[seed]}).loc[:'2025-01-02'],check_exact=True)
    record('entry_T_permission_lost_Tplus1_exit_intent_then_market_sell_next_session')
    record('permission_return_can_start_cycle_only_on_later_signal_day')
    record('future_model_change_does_not_affect_prior_intents')
    for mode in ('path','risk','and'):
        for badrole in ('path','risk'):
            bad=schedule_item('2025-01-03',path=-1. if badrole=='path' else 1.,risk=.2 if badrole=='risk' else 0.)
            params={**base,'mode':mode,'hold':7,'schedule':[seed,bad]}
            output=new.intentions(x,params)
            should_exit=mode=='and' or mode==badrole
            assert output.intent_age.iloc[2]==(0 if should_exit else 2)
    record('six_permission_role_combinations_exit_only_on_relevant_prediction_failure')
    inclusive={**base,'schedule':[schedule_item('2025-01-02',path=0.,risk=.1)]}
    assert new.intentions(x,inclusive).intent_age.iloc[1]==1
    assert new.intentions(x,{**base,'schedule':[]}).target_position.eq(0).all()
    record('inclusive_path_zero_risk_threshold_boundary_and_empty_schedule')
    invalid=[]
    for value in (None,'',True,1,'PERMISSION','other',[]):invalid.append({**base,'exit_rule':value})
    missing=deepcopy(base);del missing['exit_rule'];invalid.append(missing)
    for p in invalid:
        try:new.validate_parameters(p)
        except ValueError:pass
        else:raise AssertionError('Invalid exit_rule accepted')
    record('eight_invalid_or_missing_exit_rule_inputs_rejected')
    result={'status':'PASS','source_sha256':sha256(source.read_bytes()).hexdigest(),'source_baseline':ref.to_dict(),
      'original_source_sha256':sha256(old_source.read_bytes()).hexdigest(),'fixed_equivalence':same_configs,
      'fixed_equivalence_development_outputs':12*434,'fixed_equivalence_canonical_outputs':12*435,
      'feature_prefixes':len(prefixes),'intention_prefixes':prefix_count,'canonical_window_calculations':scope_count,
      'checks':checks,'permission_cycle_diagnostics':permission_counts,'schedule_refs':schedule_refs,'data_identities':identities,
      'input_facts':factref.to_dict(),'accounts_created':0,'limits':'Signals and market-intent ages only. No account evaluation, fills, actual hold duration, fees or performance claim. Existing NEXT_SESSION/MARKET policy retained; account runner must bind new source identity.'}
    (HERE/'others/runtime_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    print(json.dumps({'status':'PASS','source_sha256':result['source_sha256'],'fixed_configs':12,'intention_prefixes':prefix_count,'window_calculations':scope_count}),flush=True)


if __name__=='__main__':main()
