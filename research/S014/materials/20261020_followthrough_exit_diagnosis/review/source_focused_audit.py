"""EX051 bounded new-anchor semantics; synthetic only, no new economic labels."""
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

import numpy as np
import pandas as pd

ROOT=Path.cwd();BASE=Path('research/S014/materials/20261020_followthrough_exit_diagnosis')
SOURCE=Path('research/S014/experiments/EX051_20261020/src/strategy_runtime/strategies/followthrough_anchor.py')
OLD=Path('research/S014/experiments/EX050_20261020/src/strategy_runtime/strategies/shock_state_policy.py')
FIXTURE=Path('research/S014/experiments/EX043_20261019/src/precheck.py')
CHECKS=[]
def digest(path):return sha256((ROOT/path).read_bytes()).hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module
def check(name,value):
    if not value:raise AssertionError(name)
    CHECKS.append(name)
def deny(*args,**kwargs):raise RuntimeError('B EX051 focused pure audit forbids network')
socket.socket.connect=deny;socket.create_connection=deny
assert digest(SOURCE)=='a97a53b0d277ef4ee5702cc3b846ce8831fd8b182c2afca83159f31f0458f670'
assert digest(OLD)=='ac4fcdbdc5c46b1d43f31f53dda2de0635fea8f4f0cff8889a083a86f87e76f3'
new,old,toy=load('b_ex051',SOURCE),load('b_ex050',OLD),load('b_ex051_fixture',FIXTURE)
profiles=[p.value for p in new.AnchorProfile]
trees=[ast.parse((ROOT/path).read_text(encoding='utf-8')) for path in (OLD,SOURCE)]
for name in ('causal_features','tick','buy_limit','completed_sign','non_final_day_dominated','calendar_request','derive_calculation_scope'):
    nodes=[next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name) for tree in trees]
    check('inherited AST exact '+name,ast.dump(nodes[0])==ast.dump(nodes[1]))
features=new.causal_features
def run(args,profile,shock_at=None,atr0=.125,extra_shock=()):
    f=features(args[0]);f['z5']=0.;f['shock_known']=True;f['atr20_prior']=100.;f['atr_positive']=True
    if shock_at is not None:
        f.iloc[shock_at,f.columns.get_loc('z5')]=3.
        f.iloc[shock_at,f.columns.get_loc('atr20_prior')]=atr0
        f.iloc[shock_at,f.columns.get_loc('atr_positive')]=bool(np.isfinite(atr0) and atr0>0)
    for index in extra_shock:f.iloc[index,f.columns.get_loc('z5')]=3.
    new.causal_features=lambda market:f.loc[pd.to_datetime(market.Date)].copy()
    try:return new.history(*args,new.AnchorConfig.parse({'anchor_profile':profile}))
    finally:new.causal_features=features

args=toy.fixture();plain=run(args,profiles[0]);entry=int(np.flatnonzero(plain.buy_filled_today)[0]);d0=entry+1
for profile in profiles:
    actual=new.history(*args,new.AnchorConfig.parse({'anchor_profile':profile}))
    if profile==profiles[0]:
        expected=old.history(*args,old.PolicyConfig.parse({'policy_profile':'FIRST_SHOCK_AFTER_ENTRY_DAY_HOLD'}))
        pd.testing.assert_frame_equal(actual[expected.columns],expected,check_exact=True)
        CHECKS.append('fresh control every old column exact toy')

def scenario(changes):
    value=toy.fixture()
    toy.change(value,d0,close=10.)
    for index,price in changes:toy.change(value,index,close=price)
    return value

equal=scenario([(d0+1,10.)])
zero=run(equal,profiles[1],d0)
check('anchor creation only first own heldSHOCK',zero.anchor_created_today.iloc[d0] and zero.anchor_index.iloc[d0]==d0)
check('no sameSHOCKD anchor test',not zero.anchor_later_session.iloc[d0] and not zero.selected_anchor_exit.iloc[d0])
check('ZERO strict equal not trigger',not zero.anchor_raw_condition.iloc[d0+1])
check('ZERO never requires frozen ATR',not zero.anchor_atr_known.any())
persistent=scenario([(d0+1,10.1),(d0+2,9.99)])
z=run(persistent,profiles[1],d0)
check('passes nextD but persistent later triggers',not z.selected_anchor_exit.iloc[d0+1] and z.selected_anchor_exit.iloc[d0+2] and z.anchor_exit_added.iloc[d0+2])
check('ZERO nextE actual model sell',z.sell_filled_today.iloc[d0+3])
check('actualSELL clears anchor',z.anchor_index.iloc[d0+3]==-1 and pd.isna(z.shock_anchor_close_RUNTIME_HFQ.iloc[d0+3]))
exact=scenario([(d0+1,9.875)])
a=run(exact,profiles[2],d0)
check('frozen ATR stored at ownSHOCK',a.shock_anchor_ATR0_RUNTIME_HFQ.iloc[d0]==.125)
check('inclusive exact drop equality triggers',a.anchor_raw_condition.iloc[d0+1] and a.selected_anchor_exit.iloc[d0+1])
check('oneATR genuine added exit apart from support/cost',a.anchor_exit_added.iloc[d0+1] and not a.anchor_cost_overlap.iloc[d0+1] and not a.anchor_support_overlap.iloc[d0+1])
for price,expected in ((np.nextafter(9.875,np.inf),False),(np.nextafter(9.875,-np.inf),True)):
    value=run(scenario([(d0+1,price)]),profiles[2],d0)
    check('oneATR original difference operation boundary '+repr(price),bool(value.anchor_raw_condition.iloc[d0+1]) is expected)
later=scenario([(d0+1,10.1),(d0+2,9.9)])
frozen=run(later,profiles[2],d0,extra_shock=(d0+1,))
check('laterSHOCK never reanchors price or ATR',frozen.shock_condition.iloc[d0+1] and frozen.shock_anchor_close_RUNTIME_HFQ.iloc[d0+2]==10. and frozen.shock_anchor_ATR0_RUNTIME_HFQ.iloc[d0+2]==.125 and not frozen.anchor_raw_condition.iloc[d0+2])
check('later dynamic ATR does not move frozen threshold',frozen.atr20_prior.iloc[d0+2]==100. and frozen.shock_anchor_ATR0_RUNTIME_HFQ.iloc[d0+2]==.125)
loss=run(scenario([(d0+1,9.5)]),profiles[2],d0,atr0=.5)
check('no currentP positive gate',loss.net_profit.iloc[d0+1]<0 and loss.selected_anchor_exit.iloc[d0+1])
check('original support overlap retained',loss.anchor_support_overlap.iloc[d0+1] and loss.ordinary_support_exit.iloc[d0+1] and not loss.anchor_exit_added.iloc[d0+1])
pending_args=scenario([(d0+1,9.99),(d0+2,10.2)])
pending_args[3].loc[d0+2,'Status']='SUSPENDED'
p=run(pending_args,profiles[1],d0)
check('blocked anchorSELL pending remains even if anchor recovers',p.pending_inherited.iloc[d0+2] and not p.anchor_raw_condition.iloc[d0+2] and p.exit_pending.iloc[d0+2] and not p.selected_anchor_exit.iloc[d0+2])
check('pending original deadline/reservation retained',p.deadline_index.iloc[d0+2]==entry+9 and p.reservation_index.iloc[d0+2]==entry+10)
deadline_args=toy.fixture();late=entry+8;toy.change(deadline_args,late,close=11.);toy.change(deadline_args,late+1,close=10.99)
t=run(deadline_args,profiles[1],late)
check('expiry raw overlap is not newselectedexit',t.anchor_raw_condition.iloc[late+1] and t.anchor_deadline_overlap.iloc[late+1] and not t.selected_anchor_exit.iloc[late+1] and t.deadline_exit.iloc[late+1])
for profile in profiles[:2]:
    n=run(scenario([]),profile,d0,atr0=np.nan)
    check('unusedATR is no newfailure '+profile,len(n)==len(args[0]))
try:run(scenario([]),profiles[2],d0,atr0=np.nan)
except ValueError:CHECKS.append('required frozenATR unknown explicit failure')
else:raise AssertionError('requiredATR silently replaced')
failed=toy.fixture();failed[3].loc[entry,'Status']='SUSPENDED'
q=run(failed,profiles[2],entry)
check('failedBUY no anchor',q.failed_buy_reset.iloc[entry] and q.anchor_index.iloc[entry]==-1 and not q.anchor_created_today.iloc[entry])
for profile in profiles:
    full=run(persistent,profile,d0)
    stop=d0+3;prefix=[frame.iloc[:stop].copy(deep=True) for frame in persistent]
    actual=run(prefix,profile,d0)
    pd.testing.assert_frame_equal(actual,full.iloc[:stop],check_exact=True)
    CHECKS.append('newanchor ownhistory prefix '+profile)
bindings={path.as_posix():digest(path) for path in (SOURCE,OLD,FIXTURE,BASE/'method_decision.json',BASE/'review/locked_method_review.json')}
bindings[Path(__file__).resolve().relative_to(ROOT).as_posix()]=digest(Path(__file__).resolve().relative_to(ROOT))
value={'status':'PASS_FOCUSED_SOURCE_PENDING_RUNNER','reviewer':'B','blocking_findings':[],'reviewed_hashes':bindings,
       'checks_count':len(CHECKS),'checks':CHECKS,
       'scope':'New event-anchor lifecycle/clock/exact comparator/ATR freeze/ownpriority boundaries only, seven inherited helper AST and original control toy exact. No old feature-oracle expansion, real inputs, bufferhits or economic alternatives.',
       'remaining_gate':'Final source/runner/design/focusedSRT receipts and A independentdelta PASS before publiclock/freshcontrol; two treatments remain dependent on actual complete C9502 control exact and independent audit.',
       'new_funded_accounts':0,'new_market_calls':0,'new_prepared_fetches':0,'new_labels':0}
out=ROOT/BASE/'review/source_focused_review.json'
with out.open('x',encoding='utf-8',newline='\n') as handle:
    json.dump(value,handle,ensure_ascii=False,indent=2,allow_nan=False);handle.write('\n')
print(json.dumps({'path':out.relative_to(ROOT).as_posix(),'sha256':digest(out.relative_to(ROOT)),'checks':len(CHECKS)}))
