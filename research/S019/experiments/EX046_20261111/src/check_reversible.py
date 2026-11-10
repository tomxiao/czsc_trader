"""Actual strategy.step probes and exact old-source restoration; no market/account replay."""
from datetime import datetime, date
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from strategy_runtime import StateRecord, StrategyStateSchema  # noqa: E402

ROOT = Path.cwd()
WORK = ROOT / '.tmp/s019-stage2-resume'
BASE = ROOT / 'research/S019/experiments/EX044_20261110/src/strategy.py'
NEW = WORK / 'strategy_reversible.py'
CONFIG = ROOT / 'research/S019/experiments/EX044_20261110/protocols/specs.json'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class History:
    def __init__(self, frame):
        self.frame = frame

    def to_frame(self, tail):
        return self.frame.tail(tail).copy()


def main():
    original = BASE.read_text(encoding='utf8')
    restored = NEW.read_text(encoding='utf8')
    changes = [('"rolling_atr"}:', '"rolling_atr", "ramp_rebuild"}:'),
               ('elif policy == "ramp":', 'elif policy in {"ramp", "ramp_rebuild"}:'),
               ('risk_fraction = min(risk_fraction, fraction)',
                'risk_fraction = fraction if policy == "ramp_rebuild" else min(risk_fraction, fraction)'),
               ('', '        if policy == "ramp_rebuild" and old.get("exiting") and held < p["hold_days"]:\n'
                '            reason = "已触发退出，继续完成清仓"\n')]
    for old, new in changes:
        assert restored.count(new) == 1
        restored = restored.replace(new, old)
    assert restored == original
    base, new = load(BASE, 'prior_strategy'), load(NEW, 'reversible_strategy')
    config = json.loads(CONFIG.read_bytes())
    schema = StrategyStateSchema.from_dict(config['state_schema'])
    parameters = {**config['specs'][0]['parameters'], 'trail_atr': 2., 'exit_width': .5}
    zone = ZoneInfo('America/New_York')
    dates = pd.bdate_range(end='2024-04-01', periods=65, tz=zone)
    close = np.linspace(110., 100., 65)
    mu = pd.DataFrame({'Date': dates, 'AvailableDate': dates+pd.Timedelta(hours=16),
                       'Close': close, 'High': close+1., 'Low': close-1., 'Volume': np.full(65, 1000000.)})
    sector = mu.copy()
    sector['Close'] = 100.+np.arange(65)*.2+np.sin(np.arange(65))
    opening_dates = pd.DatetimeIndex([datetime(2024,3,27,9,30,tzinfo=zone), datetime(2024,3,28,9,30,tzinfo=zone),
                                      datetime(2024,4,1,9,30,tzinfo=zone), datetime(2024,4,2,9,30,tzinfo=zone)])
    opening = pd.DataFrame({'Date': opening_dates, 'AvailableDate': opening_dates+pd.Timedelta(minutes=30),
                            'Open': [99.]*4, 'Close': [99.5]*4, 'Volume': [10000.]*4})
    sector_open = opening.tail(1).copy()
    sector_open['Open'], sector_open['Close'] = 100., 100.1
    session_open = datetime(2024,4,2,9,30,tzinfo=zone)
    ctx = SimpleNamespace(parameters=parameters,
        session=SimpleNamespace(segments=(SimpleNamespace(start=session_open),), session_date=date(2024,4,2)),
        point=SimpleNamespace(decision_at=datetime(2024,4,2,10,tzinfo=zone),
                              execution_interval=SimpleNamespace(start=datetime(2024,4,2,10,tzinfo=zone))),
        history=History(opening),
        auxiliary_histories={'mu_daily': History(mu), 'soxx_daily': History(sector), 'soxx_open': History(sector_open)},
        position=SimpleNamespace(active=None))
    checks, parity_count = [], 0

    def checked(module, state):
        result = module.step(ctx, state)
        schema.validate_record(result.account, scope='account')
        if result.cycle_values is not None:
            schema.validate_record(result.cycle_values, scope='cycle')
        assert 0 <= result.decision.target <= 1
        return result

    policies = ('hard','none','confirm','ramp','daily_close','rolling_atr')
    for participation in ('hard', 'linear'):
        ctx.parameters = {**parameters, 'participation_policy': participation}
        for policy in (*policies, 'ramp_rebuild'):
            ctx.parameters['exit_policy'] = policy
            ctx.position.active = None
            entry = checked(new, SimpleNamespace(cycle=None))
            assert entry.cycle_values is not None and entry.cycle_values.get('risk_fraction') == 1.
            if policy in policies:
                assert entry == checked(base, SimpleNamespace(cycle=None))
                parity_count += 1
            checks.append({'branch': 'entry', 'policy': policy, 'participation': participation,
                           'target': entry.decision.target})

    def holding(policy, price, fraction=1., exiting=False, age=1, slot=3, prior=None):
        ctx.parameters = {**parameters, 'exit_policy': policy}
        ctx.point.execution_interval.start = session_open + pd.Timedelta(minutes=30*slot)
        ctx.point.decision_at = ctx.point.execution_interval.start
        ctx.history.frame.loc[ctx.history.frame.index[-1], 'Close'] = price
        entry_at = dates[-age].to_pydatetime() + pd.Timedelta(hours=10)
        ctx.position.active = SimpleNamespace(cycle_id='probe', entry_interval=SimpleNamespace(start=entry_at))
        values = prior or StateRecord((('anchor',100.),('allocation',.6),('exiting',exiting),('high_water',100.),
                                       ('entry_atr',2.),('risk_fraction',fraction),('breach_count',0)))
        return SimpleNamespace(cycle=SimpleNamespace(cycle_id='probe', values=values))

    for policy in policies:
        for price in (95., 95.5, 96., 96.5, 101.):
            for fraction in (.25, .5, 1.):
                for exiting in (False, True):
                    for age in (1, 5):
                        for slot in (0, 3):
                            state = holding(policy, price, fraction, exiting, age, slot)
                            assert checked(new, state) == checked(base, state)
                            parity_count += 1
    # k=2, width=.5, ATR=2: full/half/zero at prices 96.5/96/95.5.
    for price, expected in ((96.5,.6),(96.,.3),(95.5,0.)):
        result = checked(new, holding('ramp_rebuild',price))
        assert abs(result.decision.target-expected) < 1e-12
        checks.append({'branch':'boundary','price':price,'expected_target':expected})
    for policy, expected in (('ramp',.3),('ramp_rebuild',.6)):
        half = checked(new,holding(policy,96.))
        recover = checked(new,holding(policy,97.,prior=half.cycle_values))
        assert abs(recover.decision.target-expected) < 1e-12
        checks.append({'branch':'half_then_recovery','policy':policy,'target':recover.decision.target})
    zero = checked(new,holding('ramp_rebuild',95.5))
    assert zero.cycle_values.get('exiting') is True
    recover = checked(new,holding('ramp_rebuild',101.,prior=zero.cycle_values))
    assert recover.decision.target == 0 and recover.cycle_values.get('exiting') is True
    assert recover.decision.explanation.judgment == '已触发退出，继续完成清仓'
    expiry = checked(new,holding('ramp_rebuild',101.,age=5))
    assert expiry.decision.target == 0 and expiry.cycle_values.get('exiting') is True
    assert expiry.decision.explanation.judgment == '达到固定持有期限，退出'
    # Price improves while the same high-water reference persists: target is monotone within the band.
    targets = [checked(new,holding('ramp_rebuild',float(p),fraction=.1)).decision.target
               for p in np.linspace(95.5,96.5,101)]
    assert np.all(np.diff(targets) >= -1e-12) and targets[0] == 0 and targets[-1] == .6
    for boundary in (95.5,96.5):
        targets_at_boundary = [checked(new,holding('ramp_rebuild',boundary+sign*1e-8)).decision.target for sign in (-1,1)]
        assert abs(targets_at_boundary[1]-targets_at_boundary[0]) < 2e-8
    checks.extend([{'branch':'full_exit_latch','target_after_price_recovery':recover.decision.target,
                    'judgment':recover.decision.explanation.judgment},
                   {'branch':'five_day_expiry','target':expiry.decision.target},
                   {'branch':'monotone_and_continuous_band','grid_points':101}])
    bad = StateRecord(tuple((k,float(v) if k=='breach_count' else v) for k,v in zero.cycle_values.values))
    try:
        schema.validate_record(bad,scope='cycle')
    except TypeError:
        pass
    else:
        raise AssertionError('Schema accepted wrong breach_count type')
    out = {'status':'PASS','new_accounts':0,'new_experiments':0,
           'base_source_sha256':sha256(BASE.read_bytes()).hexdigest(),
           'prepared_source_sha256':sha256(NEW.read_bytes()).hexdigest(),
           'verification_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
           'schema_config_sha256':sha256(CONFIG.read_bytes()).hexdigest(),
           'exact_original_source_restoration':True,'original_actual_step_parity_cases':parity_count,
           'public_schema_validation':'All actual step account/cycle outputs; strict wrong-type negative probe.',
           'checks':checks,
           'scope':'Synthetic real step calls only; no market-data reading, accounts, experiments, or economic claims.'}
    (WORK/'reversible_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'PASS','old_step_parity_cases':parity_count,'checks':len(checks),'accounts':0}))


if __name__ == '__main__':
    main()
