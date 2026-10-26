"""Synthetic branch and boundary review for S001/S002 observation upgrade."""
from pathlib import Path
import ast, importlib.util, json
from copy import deepcopy
import pandas as pd
from strategy_runtime import StrategyRuntime, StrategyCandidate, implementation_sha256, RuntimeContractError
from strategy_runtime.signal_panel import materialize_signal_panel
from czsc_trader.application import RepositoryContext, validate_frozen_observation_upgrade
from strategy_manager.freeze_contracts import FrozenVersionReference

ROOT=Path(__file__).resolve().parents[5]
WORK=json.loads((ROOT/'research/S001/experiments/EX002_20261026/protocols/observation_sources.json').read_text(encoding='utf-8'))

def function(source,name):
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace={'pd':pd}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
    return namespace[name]

def load(path):
    spec=importlib.util.spec_from_file_location('obs_probe',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def run(ref):
    item=WORK[ref];source=ROOT/item['source'];old=item['original'];family=old['strategy_id'];version=old['version']
    helper='strategies/observation_s001_v4.py' if family=='S001' else 'strategies/observation_s002_v4.py'
    payload=deepcopy(old['strategy_payload']);payload['runtime']['source_files'].append(helper)
    payload['runtime']['source_sha256']=implementation_sha256(tuple(payload['runtime']['source_files']),source_root=source)
    candidate=StrategyCandidate(family,item['candidate_id'],payload,source)
    runtime=StrategyRuntime(ROOT/"strategies");definition=runtime.describe(candidate)
    manifest=json.loads((ROOT/'strategies'/family/'releases'/version/'release_manifest.json').read_text(encoding='utf-8'))
    original=FrozenVersionReference(family,version,old['release_hash'],manifest['package_hash'])
    try:
        validate_frozen_observation_upgrade(RepositoryContext.discover(ROOT),original,candidate)
        validation={'status':'PASS'}
    except ValueError as exc:
        if family!='S001': raise
        validation={'status':'BLOCKED_INHERITED_DECLARATION','reason':str(exc)}
    module=load(source/helper);rule=payload['parameters']['rule']
    if family=='S001':
        f=function(source/'strategies/s001_common.py','_positions')
        scores=pd.Series([0.,rule['entry_threshold'],.5,rule['exit_threshold'],rule['exit_threshold'],0.,rule['entry_threshold']],index=pd.date_range('2026-01-01',periods=7))
        targets=f(scores,enter=rule['entry_threshold'],exit_=rule['exit_threshold'],confirm_days=rule['confirm_days'],min_hold_days=rule['min_hold_days'],exit_confirm_days=rule['exit_confirm_days'])
        history=pd.DataFrame({'factor_score':scores,'target_position':targets,'regime':'range'})
        result=module.observation_history(history,rule)
        evidence=[row.to_dict() for _,row in result.iterrows()]
        initial=module.observation_history(history.loc[history.target_position.eq(1)].iloc[:1],rule)
        evidence.extend(row.to_dict() for _,row in initial.iterrows())
        assert result.iloc[1].obs_action=='enter', 'inclusive entry threshold'
        assert result.iloc[3].obs_action=='hold', 'minimum intent hold blocks early exit'
        assert result.iloc[4].obs_action=='exit', 'inclusive exit threshold after minimum'
        missing=history.iloc[:1].copy();missing['factor_score']=float('nan')
        unavailable=module.observation_history(missing,rule).iloc[0].to_dict()
        expected={'enter','exit','hold','cash','initial_long','initial_cash'}
    else:
        f=function(source/'strategies/s002_v1.py','_target_history')
        shape=rule['signal']['entry_state'];states=pd.Series(['other',shape,'other',shape,'other','other',shape,shape],index=pd.date_range('2026-01-01',periods=8))
        history=f(states,shape,rule['portfolio_rule']['holding_sessions']);history['factor_score']=history.signal_state.eq(shape).astype(float)
        result=module.observation_history(history,rule['signal'],rule['portfolio_rule'])
        evidence=[row.to_dict() for _,row in result.iterrows()]
        assert result.iloc[3].obs_action=='ignore_entry_while_holding'
        assert result.iloc[6].obs_action=='exit_time', 'time exit has priority over fresh entry'
        assert result.iloc[7].obs_action=='hold_cash', 'persistent shape does not retrigger'
        assert result.iloc[6].obs_age==rule['portfolio_rule']['holding_sessions']
        missing=history.iloc[:1].copy();missing['signal_state']=None
        unavailable=module.observation_history(missing,rule['signal'],rule['portfolio_rule']).iloc[0].to_dict()
        expected={'enter','hold_position','ignore_entry_while_holding','exit_time','hold_cash'}
    snapshots=[materialize_signal_panel(definition.observation.signal_panel,row).to_dict() for row in evidence]
    cases={v['explanation']['case_key'] for v in snapshots};assert cases==expected,(ref,cases)
    try: materialize_signal_panel(definition.observation.signal_panel,unavailable)
    except RuntimeContractError: pass
    else: raise AssertionError('unavailable controlling evidence must reject whole narrative')
    unknown=deepcopy(evidence[0]);unknown['obs_action']='undeclared'
    try: materialize_signal_panel(definition.observation.signal_panel,unknown)
    except RuntimeContractError: pass
    else: raise AssertionError('unknown branch must reject')
    old_runtime=runtime.describe(__import__('strategy_runtime').StrategyRelease.from_mapping(old))
    assert definition.observation.series==old_runtime.observation.series
    assert definition.observation.facts==old_runtime.observation.facts
    report={'reference':ref,'kind':'SYNTHETIC_BRANCH_SEMANTICS','cases':sorted(cases),'branch_count':len(cases),'source_files_added':[helper],
        'validation':validation,'observations':snapshots,'unavailable_rejected':True,'unknown_branch_rejected':True,'legacy_series_facts_unchanged':True,
        'limits':['Synthetic values test branch interpretation only, not economic performance.','Model targets and timing are not actual fills.']}
    path=ROOT/item['home']/'others'/f'{ref}-observation-semantics.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(ref,len(cases),validation)

if __name__=='__main__':
    for ref in ('S001-v1','S001-v2','S002-v1'):run(ref)
