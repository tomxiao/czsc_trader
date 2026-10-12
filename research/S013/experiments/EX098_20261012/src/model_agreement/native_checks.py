"""EX098 native pure contract and known-time synthetic checks; no real data."""
import ast
from hashlib import sha256
import importlib
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet, StrategyCandidate, StrategyRuntime, ImplementationDependency, TradableWindow, implementation_sha256, canonical_sha256
from strategy_runtime.loader import StrategyLoader

WORK = Path(__file__).resolve().parent
ROOT = next(p for p in WORK.parents if (p / 'pyproject.toml').exists())
PACKAGE = WORK / 'strategy_runtime'
FILES = ['strategies/' + name for name in ('confirm_kernel.py','confirm_net.py','tree_kernel.py','huber_kernel.py','agreement_kernel.py','model_agreement.py')]
PREFIX = '_s013_agreement_synthetic'
for name, directory in ((PREFIX, PACKAGE), (PREFIX + '.strategies', PACKAGE / 'strategies')):
    module = types.ModuleType(name)
    module.__path__ = [str(directory)]
    sys.modules[name] = module
adapter = importlib.import_module(PREFIX + '.strategies.model_agreement')
parent = importlib.import_module(PREFIX + '.strategies.confirm_net')
core = importlib.import_module(PREFIX + '.strategies.confirm_kernel')

def fixture():
    signals = pd.bdate_range("2019-12-31", periods=350)
    warm = pd.bdate_range(end=signals[0], periods=180)[:-1]
    full = warm.append(signals)
    z = np.arange(len(full))
    c = np.exp(np.cumsum(0.012 * np.sin(z * 0.83) + 0.004 * np.cos(z * 0.17))) * 10
    o = c * np.exp(-0.006 * np.cos(z * 0.61))
    d = pd.DataFrame(
        {
            "Date": full,
            "Open": o,
            "Close": c,
            "High": np.maximum(o, c) * 1.01,
            "Low": np.minimum(o, c) * 0.99,
            "Volume": 10000 + z * 13 + 2000 * np.sin(z * 0.7),
            "Amount": 200000 + z * 29 + 10000 * np.cos(z * 0.33),
        }
    )
    n = d.loc[d.Date.isin(signals)].copy()
    rows = []
    for day in signals[1:]:
        row = d.loc[d.Date.eq(day)].iloc[0]
        closes = np.exp(
            np.linspace(np.log(row.Open), np.log(row.Close), 8)
            + np.array([0.001, -0.002, 0.003, -0.002, 0.001, -0.001, 0.002, 0])
        )
        for i, time in enumerate(
            ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
        ):
            op = row.Open if i == 0 else closes[i - 1]
            rows.append(
                [
                    pd.Timestamp(str(day.date()) + " " + time),
                    op,
                    max(op, closes[i]) * 1.001,
                    min(op, closes[i]) * 0.999,
                    closes[i],
                    1000 + i * 10,
                    10000 + i * 100,
                ]
            )
    bars = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume", "Amount"])
    return d, n, bars, signals

def run():
    d, n, bars, axis = fixture()
    raw, rawbars = n.copy(), bars.copy()
    for col in ('Open','High','Low','Close'):
        raw[col] /= .2803
        rawbars[col] /= .2803
    inputs = {'daily': d, 'execution': raw, 'intraday': rawbars}
    p = dict(adapter.PARAMETERS)
    model = adapter.AgreementNet(ParameterSet(p))
    original = parent.ConfirmNet(ParameterSet({'confirmation_lookback':120,'holding_sessions':4,'ridge_alpha':10.}))
    assert model.definition.inputs == original.definition.inputs
    assert model.definition.execution == original.definition.execution
    assert model.definition.decision == original.definition.decision
    assert model.definition.capabilities == original.definition.capabilities
    assert model.definition.monitoring == original.definition.monitoring
    window = TradableWindow(axis[180].date(),axis[-1].date())
    calendar = tuple(t.date() for t in pd.DatetimeIndex(d.Date))
    assert model.derive_calculation_scope(window, calendar) == original.derive_calculation_scope(window, calendar)
    assert model.calendar_request(window) == original.calendar_request(window)
    assert set(model.definition.parameters.values) == set(adapter.PARAMETERS)
    f, price = adapter.model_inputs(inputs, axis, p)
    history, labels, scores, traces = adapter.history_from_model(f, price, axis, p)
    actual = model.calculate_history(inputs, axis)
    pd.testing.assert_frame_equal(actual.drop(columns='close'), history, check_exact=True)
    assert actual.loc[actual.index.year <= 2020].target_position.eq(0).all()
    assert actual.iloc[-5:].net_forecast.notna().all()
    assert labels.iloc[-5:].return_4.isna().all()
    assert actual.positive_forecast.equals((scores.vote_score > 0).rename('positive_forecast'))
    for h in (1,4,60):
        got = adapter.net_labels(price, axis, h)
        opens = price.Open.to_numpy(float)
        for i,t in enumerate(axis):
            if i+1+h < len(opens):
                assert got.return_4.iloc[i] == float(opens[i+1+h]/opens[i+1]*(.999/1.001)-1)
                assert got.label_end_return_4.iloc[i] == axis[i+1+h]
            else:
                assert pd.isna(got.return_4.iloc[i]) and pd.isna(got.label_end_return_4.iloc[i])
    oracle_path = ROOT/'research/S013/experiments/EX080_20261012/src/reproduction/82670d42c540_audit.py'
    spec = importlib.util.spec_from_file_location('cart_native_scalar_source', oracle_path)
    oracle = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = oracle
    spec.loader.exec_module(oracle)
    observed_daily = d.set_index('Date')
    expected_f = oracle.original14(observed_daily, price, bars.set_index('Date'), axis)
    np.testing.assert_allclose(f, expected_f, atol=2e-12, rtol=2e-11, equal_nan=True)
    expected_y = oracle.net_labels(price, axis)
    pd.testing.assert_frame_equal(labels, expected_y, check_exact=True)
    p40 = {**p, 'confirmation_lookback': 40}
    f40, prices40 = adapter.model_inputs(inputs, axis, p40)
    expected40 = oracle.original14(observed_daily, prices40, bars.set_index('Date'), axis, 40)
    np.testing.assert_allclose(f40, expected40, atol=2e-12, rtol=2e-11, equal_nan=True)
    first = axis[axis.year==2021][0]
    shortaxis = axis[axis <= first + pd.offsets.BDay(2)]
    prefix = model.calculate_history(inputs, shortaxis)
    pd.testing.assert_frame_equal(prefix, actual.iloc[:len(shortaxis)], check_exact=False, atol=1e-14, rtol=0)
    for name in ('target_position','signal_reason','positive_forecast','positive_vote_count','agreement_entry_score'):
        pd.testing.assert_series_equal(prefix[name],actual.iloc[:len(shortaxis)][name],check_exact=True)
    mutation = {name: value.copy() for name,value in inputs.items()}
    for value in mutation.values():
        mask = pd.to_datetime(value.Date).dt.normalize() > shortaxis[-1]
        for col in ('Open','High','Low','Close','Volume','Amount'):
            value[col] = value[col].astype(float)
            value.loc[mask,col] = value.loc[mask,col].astype(float)*1.37
    changed = model.calculate_history(mutation, axis)
    pd.testing.assert_frame_equal(changed.iloc[:len(shortaxis)], actual.iloc[:len(shortaxis)], check_exact=True)
    policyaxis = pd.bdate_range('2021-12-29',periods=10)
    ph = core.episode_history(pd.Series(1.,index=policyaxis), policyaxis,4)
    assert ph.signal_reason.tolist()[:6] == ['entry','hold','hold','hold','expiry','entry']
    assert ph.target_position.tolist()[:6] == [1.,1.,1.,1.,0.,1.]
    assert core.episode_history(pd.Series(0.,index=policyaxis),policyaxis,4).target_position.eq(0).all()
    assert core.episode_history(pd.Series(np.nan,index=policyaxis),policyaxis,4).target_position.eq(0).all()
    # Current votes govern entry only; unavailable forecasts never start extra clocks.
    clock_axis = pd.bdate_range('2021-12-29',periods=7)
    raw_scores = pd.DataFrame([[1.,1.,1.],[-1.,-1.,-1.],[1.,1.,np.nan],[0.,0.,0.],[np.nan]*3,[1.,1.,np.nan],[1.,1.,-1.]],index=clock_axis,columns=adapter.MODELS)
    vote = importlib.import_module(PREFIX+'.strategies.agreement_kernel').aggregate(raw_scores)
    agreed = core.episode_history(vote.vote_score,clock_axis,4)
    assert agreed.signal_reason.tolist()==['entry','hold','hold','hold','expiry','flat','entry']
    assert agreed.target_position.tolist()==[1.,1.,1.,1.,0.,0.,1.]
    assert agreed.policy_age.iloc[:5].tolist()==[0.,1.,2.,3.,4.]
    for lookback,h,depth,leaf in ((40,1,1,20),(120,60,4,120)):
        adapter.AgreementNet(ParameterSet({**p,'confirmation_lookback':lookback,'holding_sessions':h,'tree_depth':depth,'minimum_leaf':leaf}))
    for alpha,multiple in ((1.,.5),(100.,3.)):
        adapter.AgreementNet(ParameterSet({**p,'ridge_alpha':alpha,'huber_multiple':multiple}))
    refusals=[]
    for name,value in (('confirmation_lookback',39),('confirmation_lookback',121),('holding_sessions',0),('holding_sessions',61),('tree_depth',0),('tree_depth',5),('minimum_leaf',19),('minimum_leaf',121),('tree_depth',True),('holding_sessions',4.),('ridge_alpha',0.),('ridge_alpha',101.),('ridge_alpha',10),('huber_multiple',.49),('huber_multiple',3.1),('huber_multiple',True)):
        bad={**p,name:value}
        try:
            adapter.AgreementNet(ParameterSet(bad))
        except ValueError:
            refusals.append(name+'='+str(value))
        else:
            raise AssertionError('Invalid domain accepted')
    for bad in ({**p,'free_vote_weight':1.},{key:value for key,value in p.items() if key!='tree_depth'}):
        try:
            adapter.AgreementNet(ParameterSet(bad))
        except ValueError:
            refusals.append('wrong_keys')
        else:
            raise AssertionError('Invalid keys accepted')
    oldroot=ROOT/'research/S013/experiments/EX080_20261012/src/adapter_revision2/strategy_runtime/strategies'
    for name in ('confirm_kernel.py','confirm_net.py'):
        assert (PACKAGE/'strategies'/name).read_bytes()==(oldroot/name).read_bytes()
    
    for name in ('tree_kernel.py','huber_kernel.py','agreement_kernel.py'):
        assert (PACKAGE/'strategies'/name).read_bytes()==(WORK/name).read_bytes()
    # Prove the exact old native pricing statements, rather than merely outcomes.
    oldtree=ast.parse((oldroot/'confirm_net.py').read_text('utf-8'))
    oldcalc=next(n for n in next(n for n in oldtree.body if isinstance(n,ast.ClassDef)).body if isinstance(n,ast.FunctionDef) and n.name=='calculate_history')
    newtree=ast.parse((PACKAGE/'strategies/model_agreement.py').read_text('utf-8'))
    newcalc=next(n for n in newtree.body if isinstance(n,ast.FunctionDef) and n.name=='model_inputs')
    def pricing_nodes(nodes):
        return [ast.dump(n,include_attributes=False) for n in nodes if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('pricing','native','bars') for t in n.targets)]
    assert pricing_nodes(oldcalc.body)==pricing_nodes(newcalc.body)
    payload={'parameters':p,'runtime':{'contract_version':1,'module':'strategy_runtime.strategies.model_agreement','qualname':'AgreementNet','source_files':FILES,'source_sha256':implementation_sha256(FILES,source_root=PACKAGE)}}
    cand=StrategyCandidate('S013','C9098',payload,PACKAGE)
    assert canonical_sha256(cand.payload)==canonical_sha256(payload)
    import strategy_runtime
    installed_before = strategy_runtime.__file__
    runtime = StrategyRuntime(ROOT/'strategies')
    definition = runtime.describe(cand)
    assert definition.parameters.values == model.definition.parameters.values
    identity = runtime.identify(cand, dependencies=tuple(ImplementationDependency(name,version(name)) for name in ('numpy','pandas','czsc-strategy-runtime')))
    assert len(identity.content_sha256) == 64
    authenticated = StrategyLoader(ROOT/'strategies').load_candidate(cand)
    pd.testing.assert_frame_equal(authenticated.calculate_history(inputs,axis), actual, check_exact=True)
    assert strategy_runtime.__file__ == installed_before
    output={'status':'PASS','synthetic_only':True,'real_inputs_read':0,'real_inputs':0,'new_accounts':0,'experiments_allocated':0,
      'checks':['Inherited input/scope/calendar/execute contracts exact','Six effective full legal domains with shared alpha and fixedvote','Original2019 warm features only and2020 cash','Exact old pricing AST and frozen parent bytes','H1/4/60 matured labels scalar exact and NA tail prediction','Complete native history/strict positive flags','Prefix/future mutation preserve prior history','H expiry priority and no same T reentry/year continuity','Runtime source copy exact and candidate canonical serialization','All illegal params refused','Frozen independent original14/net_labels reconstruction','Single shared clock survives current missing/negative scores and no twoavailable rescue','Public authenticated native loader and content identity with all relative core imports'],
      'check_count':13,'authenticated_native_loader':'PASS','installed_strategy_runtime_preserved':True,'rejections':refusals,'rejection_count':len(refusals),'signal_count':len(axis),
      'source_sha256':{name:sha256((PACKAGE/name).read_bytes()).hexdigest() for name in FILES},
      'oracle_source_sha256':sha256(oracle_path.read_bytes()).hexdigest(),'test_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'domains':adapter.DOMAINS}
    (WORK/'native_checks.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print({'status':'PASS','checks':13,'rejections':len(refusals),'real_inputs':0})


if __name__=='__main__':
    run()
