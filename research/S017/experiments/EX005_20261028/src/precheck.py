"""Independent EX005 risk-component checks; no strategy-account replay."""
from datetime import date
from hashlib import sha256
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import os
import sys

from dataflows import PreparedDataRef, EquityDataRequest, EquityQuery, EquityProduct
from run import ROOT, WORK, SOURCE, INSTRUMENT, context, configurations, candidate, read, save
from strategy import cycle_levels, decide


def load(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PRIOR = ROOT/'research/S017/experiments/EX004_20261028/src'
OLD = load('_s017_ex005_retained_strategy',PRIOR/'strategy.py')
_saved = {name:sys.modules.get(name) for name in ('run','strategy')}
try:
    sys.modules['run'] = load('_s017_ex005_retained_runner',PRIOR/'run.py')
    sys.modules['strategy'] = OLD
    CHECK = load('_s017_ex005_independent_helpers',PRIOR/'precheck.py')
finally:
    for _name,_module in _saved.items():
        if _module is None:
            sys.modules.pop(_name,None)
        else:
            sys.modules[_name] = _module


def call(frame, account, parameters):
    return decide(SimpleNamespace(history=frame,portfolio=account,parameters=parameters))


def baseline_parameters():
    return {**configurations()['C0028'],'initial_atr_multiple':3.,'profit_protection':False}


def oracle(frame, account, parameters):
    """Sequential independent fold, sharing only EX004's separately implemented daily TR oracle."""
    atrs = CHECK.oracle_atr(frame,parameters['atr_days'])
    rows = [row for row in frame.itertuples() if row.Date > account.cycle_entry]
    CHECK.require(bool(rows),'oracle requires post-entry completed closes')
    entry_day = account.cycle_entry.astimezone(CHECK.ZONE).date()
    entry_atr = atrs[entry_day]
    basis = account.cycle_cost/account.quantity
    level = basis-parameters['initial_atr_multiple']*entry_atr
    initial, peak, hit, levels = level, basis, False, []
    for row in rows:
        peak = max(peak,float(row.Close))
        atr = atrs[row.Date.tz_convert('America/New_York').date()]
        level = max(level,peak-parameters['atr_multiple']*atr)
        if parameters['profit_protection'] and peak >= basis+parameters['protect_gain_atr']*entry_atr:
            level = max(level,basis)
        hit = hit or float(row.Close) <= level
        levels.append(level)
    return dict(stop=level,initial_stop=initial,peak_close=peak,stop_hit=hit,
                entry_cost_per_share=basis,entry_atr=entry_atr,levels=levels,cycle_observations=len(rows))


def stable_frame():
    frame = CHECK.synthetic()
    frame[['Open','Close']] = 100.
    frame['High'],frame['Low'] = 101.,99.
    return frame


def risk_boundaries():
    frame = stable_frame().iloc[:305].copy()
    first = 300
    account = CHECK.portfolio(frame.BarStart.iloc[first],basis=100.)
    configs = configurations()
    initial = {key:cycle_levels(frame.iloc[:first+1],account,p) for key,p in configs.items()}
    CHECK.close(initial['C0027']['initial_stop'],98.,'one ATR initial distance')
    CHECK.close(initial['C0028']['initial_stop'],94.,'three ATR initial distance')
    CHECK.close(initial['C0029']['initial_stop'],98.,'combined initial distance')
    CHECK.close(initial['C0028']['entry_atr'],2.,'exact synthetic entry ATR')
    frame.loc[frame.index[first],'Close'] = 103.999
    below = cycle_levels(frame.iloc[:first+1],account,configs['C0028'])
    CHECK.require(below['stop'] < 100.,'protection activated below two-ATR threshold')
    frame.loc[frame.index[first],'Close'] = 104.
    exact = cycle_levels(frame.iloc[:first+1],account,configs['C0028'])
    CHECK.close(exact['stop'],100.,'threshold equality did not activate cost floor')
    CHECK.require(not exact['stop_hit'],'reaching positive threshold should not itself exit')
    no_protection = cycle_levels(frame.iloc[:first+1],account,baseline_parameters())
    CHECK.close(no_protection['stop'],98.,'disabled protection changed trailing rule')
    frame.loc[frame.index[first:],'Close'] = [104.,103.,100.,110.,109.]
    state = cycle_levels(frame,account,configs['C0028'])
    CHECK.same_state(state,oracle(frame,account,configs['C0028']))
    CHECK.require(state['stop_hit'],'equal cost floor did not latch exit')
    CHECK.require(call(frame,account,configs['C0028']).target == 0,'rebound canceled triggered exit')
    CHECK.require(all(level >= 100. for level in state['levels']),'activated floor moved below cost')
    altered = frame.copy()
    altered.loc[altered.index[first],'High'] = 100000.
    CHECK.same_state(cycle_levels(altered,account,configs['C0028']),state)
    reset = CHECK.portfolio(frame.BarStart.iloc[-1],basis=109.)
    CHECK.require(not cycle_levels(frame,reset,configs['C0028'])['stop_hit'],'new cycle retained old trigger')
    # The stop floor includes the entry fee, but sale proceeds still pay an exit fee.
    basis,quantity,fee = 100.1,10,.001
    exact_floor_net = quantity*basis*(1.-fee)-quantity*basis
    gap_net = quantity*95.*(1.-fee)-quantity*basis
    CHECK.require(exact_floor_net < 0 and gap_net < exact_floor_net,
                  'cost-line protection was incorrectly interpreted as net breakeven')
    return {'boundary_scenarios':['one_ATR_initial','three_ATR_initial','combined_initial','exact_entry_ATR',
                'below_protection_threshold','equal_protection_threshold','disabled_protection',
                'floor_only_up','trigger_latch','entry_high_excluded','new_cycle_reset','exit_fee_loss','gap_loss'],
            'illustrative_fee_arithmetic':{'cost_per_share':basis,'quantity':quantity,'exit_fee_rate':fee,
                'sale_at_cost_net_pnl':exact_floor_net,'sale_after_gap_at_95_net_pnl':gap_net,
                'scope':'Synthetic arithmetic only; not a simulated fill or research return.'}}


def synthetic_prefixes():
    frame = CHECK.synthetic().iloc[:455].copy()
    first = 390
    account = CHECK.portfolio(frame.BarStart.iloc[first],basis=float(frame.Close.iloc[first]))
    frame.loc[frame.index[first+10:first+14],'Close'] *= 1.2
    frame.loc[frame.index[first+20:first+23],'Close'] *= .6
    frame['High'] = frame[['High','Close']].max(axis=1)
    frame['Low'] = frame[['Low','Close']].min(axis=1)
    configs,states,baseline_checks = configurations(),0,0
    for parameters in configs.values():
        full = cycle_levels(frame,account,parameters)
        CHECK.same_state(full,oracle(frame,account,parameters))
        for stop in range(first+1,len(frame)+1):
            prefix = frame.iloc[:stop]
            actual = cycle_levels(prefix,account,parameters)
            CHECK.same_state(actual,oracle(prefix,account,parameters))
            for left,right in zip(actual['levels'],full['levels'][:stop-first]):
                CHECK.close(left,right,'future data altered historical stop')
            CHECK.require(call(prefix,account,parameters).target == int(not actual['stop_hit']),
                          'decision differs from independently verified latch')
            states += 1
    params = baseline_parameters()
    for stop in range(first+1,len(frame)+1):
        prefix = frame.iloc[:stop]
        CHECK.same_state(cycle_levels(prefix,account,params),OLD.cycle_levels(prefix,account,params))
        for held in (account,CHECK.portfolio(None,quantity=0)):
            old = OLD.decide(SimpleNamespace(history=prefix,portfolio=held,parameters=params))
            CHECK.require(call(prefix,held,params).target == old.target,'three/false baseline decision drift')
            baseline_checks += 1
    return {'independent_full_sequences':len(configs),'independent_prefix_states':states,
            'old_C0025_prefix_states':len(frame)-first,'old_C0025_held_flat_decisions':baseline_checks}


def prepared_samples():
    saved = read(ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json')
    identity = saved['reference']
    prepared = PreparedDataRef(UUID(identity['space_id']),UUID(identity['preparation_id']),identity['manifest_sha256'])
    query = EquityDataRequest(INSTRUMENT,SOURCE,EquityQuery(EquityProduct.BARS,date(2018,11,1),date(2025,12,31)))
    fetched = context().data.fetch(query,prepared=prepared)
    CHECK.require(fetched.ready,str(fetched.error))
    frame = fetched.dataframe
    local = frame.Date.dt.tz_convert('America/New_York')
    CHECK.require(local.min().date() == date(2018,11,1) and local.max().date() == date(2025,12,31),
                  'prepared data is outside exact approved bounds')
    CHECK.require(frame.BarStatus.eq('OBSERVED').all() and (frame.Volume > 0).all(),'unexpected unavailable bar')
    CHECK.require(int(frame.ExecutionBlocked.sum()) == 5,'known blocked bar count changed')
    original = next(item for item in saved['items'] if item['product'] == EquityProduct.BARS.value)
    CHECK.require(fetched.identity.content_sha256 == original['sha256'],'prepared bar content changed')
    indices = sorted({508+int(i*(len(frame)-508-131)/7) for i in range(8)})
    states,baseline_checks = 0,0
    for first in indices:
        account = CHECK.portfolio(frame.BarStart.iloc[first],basis=float(frame.Open.iloc[first])*1.001)
        for length in (1,13,65):
            prefix = frame.iloc[:first+length]
            for parameters in configurations().values():
                CHECK.same_state(cycle_levels(prefix,account,parameters),oracle(prefix,account,parameters))
                states += 1
            params = baseline_parameters()
            CHECK.same_state(cycle_levels(prefix,account,params),OLD.cycle_levels(prefix,account,params))
            for held in (account,CHECK.portfolio(None,quantity=0)):
                old = OLD.decide(SimpleNamespace(history=prefix,portfolio=held,parameters=params))
                CHECK.require(call(prefix,held,params).target == old.target,'causal sample baseline drift')
                baseline_checks += 1
    return {'reference':identity,'fetch_calls':1,'authorized_range':['2018-11-01','2025-12-31'],
            'bars':len(frame),'content_sha256':fetched.identity.content_sha256,
            'known_blocked_bars':int(frame.ExecutionBlocked.sum()),'sampled_entry_indices':indices,
            'independent_prefix_states':states,'old_C0025_held_flat_decisions':baseline_checks,
            'scope':'Synthetic portfolio snapshots at causal sampled entries; no actual fills, accounts or returns.'}


def check():
    scratch = ROOT/'.tmp/s017-trend'
    scratch.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    source = WORK/'src/strategy.py'
    source_hash = sha256(source.read_bytes()).hexdigest()
    old_hashes = {name:sha256((PRIOR/name).read_bytes()).hexdigest() for name in ('strategy.py','run.py','precheck.py')}
    cases = {}
    for name,function in (('risk_boundaries',risk_boundaries),('synthetic_prefixes',synthetic_prefixes),
                          ('prepared_causal_samples',prepared_samples)):
        try:
            cases[name] = {'status':'PASS',**function()}
            print('PASS',name,flush=True)
        except Exception as exc:
            cases[name] = {'status':'FAIL','error_type':type(exc).__name__,'error':str(exc)}
            print('FAIL',name,type(exc).__name__,str(exc),flush=True)
    try:
        for key,parameters in configurations().items():
            definition = candidate(key,parameters).definition
            CHECK.require(definition.from_dict(definition.to_dict()) == definition,'definition roundtrip differs')
        CHECK.require(sha256(source.read_bytes()).hexdigest() == source_hash,'new source changed during precheck')
        for name,digest in old_hashes.items():
            CHECK.require(sha256((PRIOR/name).read_bytes()).hexdigest() == digest,'published EX004 source changed')
        cases['definitions_and_immutable_source'] = {'status':'PASS','definitions':len(configurations()),'old_source_hashes':old_hashes}
    except Exception as exc:
        cases['definitions_and_immutable_source'] = {'status':'FAIL','error_type':type(exc).__name__,'error':str(exc)}
    passed = sum(case['status'] == 'PASS' for case in cases.values())
    output = {'status':'PASS' if passed == len(cases) else 'FAIL','passed_groups':passed,'total_groups':len(cases),
        'strategy_source_sha256':source_hash,'precheck_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Synthetic and prepared-development causal checks only; no formal account replay or holdout access.',
        'oracle_source':'EX004 independent daily TR fold reused; EX005 initial distance and protection independently folded bar by bar.',
        'cases':cases}
    save(WORK/'others/precheck.json',output)
    if output['status'] != 'PASS':
        raise RuntimeError('EX005 focused precheck failed; see others/precheck.json')
    print('EX005 PRECHECK PASS',passed,'groups',flush=True)


if __name__ == '__main__':
    check()
