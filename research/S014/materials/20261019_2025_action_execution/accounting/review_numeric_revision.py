"""Independent pure synthetic review of EX040 numeric observation correction."""
import ast
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket

import pandas as pd
from strategy_runtime import ObservedSeries, ParameterSet, RuntimeContractError

ROOT = Path.cwd()
BASE = ROOT / 'research/S014/experiments/EX040_20261019'
OUT = ROOT / 'research/S014/materials/20261019_2025_action_execution/accounting/numeric_revision_independent_review.json'

def forbidden(*args, **kwargs):
    raise RuntimeError('No network allowed')

socket.socket.connect = forbidden
socket.create_connection = forbidden

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    paths = [BASE / 'src/strategy_runtime/strategies/repair_action_review.py',
             BASE / 'src/strategy_runtime_v2/strategies/repair_action_review.py']
    trees = [ast.parse(p.read_bytes()) for p in paths]
    for tree in trees:
        fn = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'RepairStrategy'
                  for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'calculate_history')
        # Remove exactly the numeric observation cast for whole-module AST equality.
        matches = [n for n in fn.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                   and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == 'astype']
        assert len(matches) == 1
        assert ast.unparse(matches[0].value.args[0]) == 'float'
        fn.body.remove(matches[0])
    assert ast.dump(trees[0]) == ast.dump(trees[1])
    old, new = [load('independent_numeric_' + str(i), p) for i, p in enumerate(paths)]
    dates = pd.DatetimeIndex([pd.Timestamp('2019-12-31'), *pd.bdate_range('2020-01-02', periods=110)])
    prices = pd.DataFrame(dict(Date=dates, Open=10., High=10.2, Low=9.8, Close=10., Volume=100000., Amount=1000000.))
    limits = pd.DataFrame(dict(Date=dates, DownLimit=5., UpLimit=20.))
    status = pd.DataFrame(dict(Date=dates, Status='TRADING'))
    data = dict(market=prices.copy(), raw=prices, limits=limits, status=status)
    history = old.history(*data.values(), 'support_exit_reserve_H10')
    first_buy = int(history.entry_signal.to_numpy().nonzero()[0][0])
    accepted_values = 0
    reviewed = []
    for mode, index in [('NOOP', None), ('SKIP_BUY_ONCE', first_buy), ('FORCE_SELL_ONCE', first_buy + 1)]:
        params = ParameterSet(dict(variant='support_exit_reserve_H10', intervention_mode=mode,
                                   intervention_decision_date='' if index is None else dates[index].date().isoformat()))
        v1, v2 = old.RepairStrategy(params), new.RepairStrategy(params)
        left, right = v1.calculate_history(data, list(dates)), v2.calculate_history(data, list(dates))
        pd.testing.assert_frame_equal(left.drop(columns=list(old.DIAGNOSTIC)), right.drop(columns=list(new.DIAGNOSTIC)), check_exact=True)
        for key in old.DIAGNOSTIC:
            assert (left[key].astype(float) == right[key]).all()
        rejected = False
        try:
            ObservedSeries('intervention_today', 'intervention_today', left.to_dict('records')[0]['intervention_today'], ())
        except RuntimeContractError:
            rejected = True
        assert rejected
        for record in right.to_dict('records'):
            for field in v2.definition.observation.series:
                ObservedSeries(field.key, field.label, record[field.value_field], ())
                accepted_values += 1
        reviewed.append(mode)
    result = dict(status='PASS_SYNTHETIC_NUMERIC_CORRECTION_ONLY', reviewed_modes=reviewed,
                  real_ObservedSeries_accepted_values=accepted_values, whole_module_AST_same_except_one_cast=True,
                  exact_economic_projection_all_modes=True, failed_v1_reproduced_all_modes=True,
                  real_NOOP_economic_equivalence='SEPARATE_ACCOUNT_AUDIT_REQUIRED',
                  real_account_dispatches=0, real_market_calls=0, fits=0,
                  source_sha256={str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths},
                  independent_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
    with OUT.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result))

if __name__ == '__main__':
    main()
