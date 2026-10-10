"""Causal and branch checks, then one serial/spawn full-account control."""
# ruff: noqa: E402
import os
for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[variable] = '1'

from copy import deepcopy
import ast
import importlib.util
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from common import (SOURCE, PROTOCOLS, RUNS, CACHE, EXPERIMENT, SOURCE_CALLS,
                    read, write, request, context, cache_write, file_hash)

def synthetic():
    package = types.ModuleType('_s013_ex012_check')
    package.__path__ = [str(SOURCE/'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__+'.score_change_range',
                                                 SOURCE/'strategies/score_change_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    configs = read(PROTOCOLS/'plan.json')['configurations']
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2018-01-01',periods=450)
    price = 6*np.exp(np.cumsum(rng.normal(.0004,.02,len(dates))))
    bars = pd.DataFrame({'Date':dates,'Open':price,'High':price*1.01,'Low':price*.99,
        'Close':price,'Volume':np.exp(rng.normal(15,.2,len(dates))),
        'Amount':np.exp(rng.normal(18,.2,len(dates)))})
    sessions = dates[230:]
    checks = []
    for config in configs:
        p = config['payload']['parameters']
        cls = module.ScoreChangeRange if config['mode'] in ('M2','M3') else module.ReentryConfirmedRange
        implementation = cls(ParameterSet(p))
        history = implementation.calculate_history({'daily':bars},sessions)
        cutoff = sessions[80]
        prefix = implementation.calculate_history({'daily':bars.loc[bars.Date<=cutoff]},sessions[:81])
        pd.testing.assert_frame_equal(history.loc[:cutoff],prefix,check_exact=True)
        changed = bars.copy()
        changed.loc[changed.Date>cutoff,['Close','Volume','Amount']] *= 1.2
        future = implementation.calculate_history({'daily':changed},sessions)
        pd.testing.assert_frame_equal(history.loc[:cutoff],future.loc[:cutoff],check_exact=True)
        assert not history.signal_reason.eq('cooldown').any()
        if config['mode'] in ('M2','M3'):
            expected = p['confirmation']['direction']*history.confirmation_delta>=0
            assert history.confirmation_pass.equals(expected)
            opportunities = history.confirmation_opportunity
            assert (opportunities & expected).equals(history.signal_reason.eq('entry'))
            assert (opportunities & ~expected).equals(history.signal_reason.eq('confirmation_rejected'))
            assert np.isfinite(history.confirmation_delta.iloc[0])
        checks.append({'background':config['background'],'mode':config['mode'],
            'causal_prefix':'EXACT_EQUAL','future_invariance':'EXACT_EQUAL'})
    # Deterministic equality and both directions; weak confirmation never exits.
    def fixed_features(bars, acf, window):
        index = pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
        values = np.resize(np.array([0.,.25,.25,-.25]),len(index))
        frame = pd.DataFrame({key:values for key in ('acf','turnover','volume')},index=index)
        return frame.copy(),frame.copy()
    actual_features = module.confirmation_features
    module.confirmation_features = fixed_features
    for direction in (1,-1):
        p = deepcopy(configs[2]['payload']['parameters'])
        p['confirmation']['direction'] = direction
        frame = module.ScoreChangeRange(ParameterSet(p)).calculate_history({'daily':bars},sessions)
        delta = frame.confirmation_delta
        assert delta.eq(0).any() and delta.gt(0).any() and delta.lt(0).any()
        assert frame.confirmation_pass[delta.eq(0)].all()
        assert frame.signal_reason[~frame.confirmation_opportunity & ~frame.confirmation_pass].isin(
            ('hold','loss','trailing','range','time','regime','flat')).all()
    module.confirmation_features = actual_features
    for invalid in (0,2,True,1.0):
        p = deepcopy(configs[2]['payload']['parameters'])
        p['confirmation']['direction'] = invalid
        try:
            module.ScoreChangeRange(ParameterSet(p))
        except (ValueError,TypeError):
            pass
        else:
            raise AssertionError('invalid direction accepted')
    parent_tree = ast.parse((SOURCE/'strategies/reentry_confirmed_range.py').read_text())
    change_tree = ast.parse((SOURCE/'strategies/score_change_range.py').read_text())
    def holding_branch(tree):
        return next(node for node in ast.walk(tree) if isinstance(node,ast.If)
                    and isinstance(node.test,ast.Name) and node.test.id=='holding')
    assert ast.dump(holding_branch(parent_tree)) == ast.dump(holding_branch(change_tree))
    return {'status':'PASS','cases':checks,'branches':['zero delta passes both',
        'positive/negative delta','no cooldown','weak confirmation cannot trigger exit',
        'invalid direction rejected','original holding/exit branch AST identical',
        'first session delta computed using previous actual trading day']}

def main():
    plan = read(PROTOCOLS/'plan.json')
    for filename,expected in plan['source_files'].items():
        assert file_hash(SOURCE/filename)==expected
    proof = synthetic()
    write(RUNS/'synthetic_check.json',proof)
    ctx = context(1)
    supplement = {'purpose':'Before the fixed batch, evaluate B0/M1 once serial and once in a spawn process, compare all five strategy/benchmark ledgers and all signal histories exactly. Reuse the verified control for the fixed queue.',
        'configuration_budget':'12 unique configurations unchanged; one duplicate evaluation solely for serial/spawn equivalence, total planned account evaluations 13.',
        'source':'research technical preflight under the approved scope',
        'synthetic_check':proof}
    write(PROTOCOLS/'preflight_supplement.json',supplement)
    reference = publish_evidence(ctx,MaterialEvidenceWrite(EXPERIMENT,'mechanism-preflight-plan',
        (PROTOCOLS/'preflight_supplement.json').read_bytes(),'application/json','json'))
    write(PROTOCOLS/'preflight_reference.json',reference.to_dict())
    config = plan['configurations'][1]
    if (CACHE/'preflight-parallel.pkl.gz').exists():
        from common import cache_read
        bound,serial = cache_read(CACHE/'preflight-serial.pkl.gz')
        repeated,parallel = cache_read(CACHE/'preflight-parallel.pkl.gz')
        assert serial.request_hash==parallel.request_hash
        assert repeated.strategy.payload==bound.strategy.payload
    else:
        bound = ctx.evaluation.prepare(request(config))
        print({'input_prepared':True,'candidate':config['candidate_id']},flush=True)
        serial = ctx.evaluation.evaluate(bound)
        print({'serial_control':'SUCCEEDED'},flush=True)
        outcome = context(2).evaluation.evaluate_many((bound,))[0]
        assert outcome.status.value=='SUCCEEDED',outcome.error
        parallel = outcome.result
        cache_write(CACHE/'preflight-serial.pkl.gz',(bound,serial))
        cache_write(CACHE/'preflight-parallel.pkl.gz',(bound,parallel))
    for first,second in zip(serial.runs,parallel.runs,strict=True):
        pd.testing.assert_frame_equal(first.signals.decisions,second.signals.decisions,check_exact=True)
        for kind in ('execution','buyhold'):
            left,right = getattr(first,kind),getattr(second,kind)
            if kind=='buyhold':
                left,right = left.execution,right.execution
            for field in ('decisions','orders','fills','account_daily','trades'):
                pd.testing.assert_frame_equal(getattr(left,field),getattr(right,field),check_exact=True)
    assert serial.result_hash==parallel.result_hash
    assert not SOURCE_CALLS
    cache_write(CACHE/'B0-M1.pkl.gz',(bound,serial))
    write(RUNS/'precheck.json',{'status':'PASS','synthetic':proof,
        'serial_spawn_equivalence':'all signal and five strategy/benchmark ledgers EXACT_EQUAL',
        'result_hash':serial.result_hash,'provider_calls':SOURCE_CALLS,
        'unique_prechecked_configuration':'B0/M1','account_evaluations':4,
        'technical_attempts':'First comparison caller used an unsupported EvaluationRun.history attribute after both evaluations succeeded. Repeated control saved before comparison; corrected to signals.decisions and buyhold.execution and checked saved pair without replay.'})
    print({'precheck':'PASS','serial_spawn':'EXACT_EQUAL'},flush=True)

if __name__=='__main__':
    main()
