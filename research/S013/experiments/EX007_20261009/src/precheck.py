"""Causal/parameter checks and two actual-parent account controls."""
from copy import deepcopy
import importlib.util
import sys
import types
import numpy as np
import pandas as pd
from strategy_runtime import ParameterSet
from czsc_trader.research_tools.evaluation import serialize_evaluation_evidence
from common import SOURCE, PROTOCOLS, RUNS, CACHE, ROOT, read, write, request, context, cache_read, cache_write
from economic_equivalence import compare_evidence


def synthetic():
    package = types.ModuleType('_s013_cost_check')
    package.__path__ = [str(SOURCE / 'strategies')]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__ + '.complement_confirmed_range',
        SOURCE / 'strategies/complement_confirmed_range.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    p = read(PROTOCOLS / 'initial_plan.json')['configurations'][0]['parameters']
    rng = np.random.default_rng(13)
    dates = pd.bdate_range('2019-01-01', periods=360)
    price = 6 * np.exp(np.cumsum(rng.normal(.0008, .02, len(dates))))
    bars = pd.DataFrame({'Date': dates, 'Open': price, 'High': price*1.01, 'Low': price*.99,
        'Close': price, 'Volume': np.exp(rng.normal(15., .2, len(dates))),
        'Amount': np.exp(rng.normal(18., .2, len(dates)))})
    sessions = dates[180:]
    parent = module.ReentryConfirmedRange(ParameterSet({k:v for k,v in p.items() if k != 'opportunity_confirmation'}))
    old = parent.calculate_history({'daily': bars}, sessions)
    control = module.ComplementConfirmedRange(ParameterSet(p)).calculate_history({'daily': bars}, sessions)
    pd.testing.assert_frame_equal(old, control, check_exact=True)
    for profile in ('all', 'acf', 'volume', 'acf_volume'):
        for application in ('all_entries', 'ordinary_entries'):
            case = deepcopy(p)
            case['opportunity_confirmation'].update(enabled=True, profile=profile,
                weighting='EQUAL_BLOCKS' if profile == 'all' else 'EQUAL_FEATURES', application=application)
            prototype = module.ComplementConfirmedRange(ParameterSet(case))
            history = prototype.calculate_history({'daily': bars}, sessions)
            cutoff = sessions[80]
            prefix = prototype.calculate_history({'daily': bars.loc[bars.Date <= cutoff]}, sessions[:81])
            pd.testing.assert_frame_equal(history.loc[:cutoff], prefix, check_exact=True)
            changed = bars.copy()
            changed.loc[changed.Date > cutoff, 'Close'] *= 1.2
            future = prototype.calculate_history({'daily': changed}, sessions)
            pd.testing.assert_frame_equal(history.loc[:cutoff], future.loc[:cutoff], check_exact=True)
            assert not history.signal_reason.eq('cooldown').any()
    for key, value in (('enabled', 1), ('threshold', float('nan')), ('threshold', True),
                       ('profile', 'bad'), ('application', 'wait_days'), ('route_scope', 'bad')):
        invalid = deepcopy(p)
        invalid['opportunity_confirmation'][key] = value
        try:
            module.ComplementConfirmedRange(ParameterSet(invalid))
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(key)
    write(RUNS / 'synthetic_check.json', {'status':'PASS', 'checks': [
        'disabled history exact', 'eight profile/context causal-prefix and future-invariance cases',
        'invalid settings rejected', 'no fixed cooldown']})


def main():
    synthetic()
    configs = read(PROTOCOLS / 'initial_plan.json')['configurations'][:2]
    research = context(1)
    proofs = []
    for i, config in enumerate(configs):
        original, result = cache_read(ROOT / '.tmp/s013-buy-confirmation' / (config['parent'] + '.pkl.gz'))
        bound = research.evaluation.prepare(request(f'C{3000+i}', config['parameters'], original.execution_data))
        computed = research.evaluation.evaluate(bound)
        proof = compare_evidence(serialize_evaluation_evidence(original, result), serialize_evaluation_evidence(bound, computed))
        cache_write(CACHE / (bound.strategy.candidate_id + '.pkl.gz'), (bound, computed))
        proofs.append({'parent': config['parent'], 'control': bound.strategy.candidate_id, 'comparison':proof})
        print({'exact_parent_controls':len(proofs)}, flush=True)
    write(RUNS / 'precheck.json', {'status':'PASS','controls':proofs,'external_provider_access':False})


if __name__ == '__main__':
    main()
