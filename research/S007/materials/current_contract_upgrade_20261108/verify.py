"""Check preserved S007 financial predicates and native signal-only step."""
import ast
from hashlib import sha256
import importlib.util
import json
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
from pandas.testing import assert_frame_equal
from strategy_runtime import StrategyRuntime, StateRecord

import adaptation
from retained_inputs import load

ROOT, HERE = adaptation.ROOT, adaptation.HERE


class FrameView:
    def __init__(self, frame):
        self.frame = frame

    def to_frame(self):
        return self.frame.copy(deep=True)


def main():
    source = ROOT / '.tmp/s007-current-contract-verification' / uuid4().hex / 'strategy_runtime'
    candidate = adaptation.build('v1', 'C9998', source)
    definition = StrategyRuntime().describe(candidate)
    frames, provenance = load()
    frozen_root = adaptation.ORIGINAL_ROOT / 'S007/releases/v1/src/strategy_runtime'
    assert (frozen_root / 'signals.py').read_bytes() == (source / 'signals.py').read_bytes()
    assert (frozen_root / 'seed.csv').read_bytes() == (source / 'seed.csv').read_bytes()
    old_spec = importlib.util.spec_from_file_location('s007_original_signal_math', frozen_root / 'signals.py')
    old_module = importlib.util.module_from_spec(old_spec)
    old_spec.loader.exec_module(old_module)
    tree = ast.parse((frozen_root / 'strategy.py').read_bytes())
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'signal_history')
    old_scope = {'pd': pd, 'resolve_s007_feature_panel': old_module.resolve_s007_feature_panel,
                 'calculate_s007_history': old_module.calculate_s007_history}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), '<frozen-s007-signal-history>', 'exec'), old_scope)
    parameters = json.loads(candidate.definition.parameters_json)
    market = frames['hfq_daily'].copy(deep=True)
    market['Date'] = pd.to_datetime(market.Date).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None).dt.normalize()
    inputs = {name: frame for name, frame in frames.items() if name.startswith('incremental_') or name == 'feature_seed'}
    inputs['adjusted_daily'] = market
    end = market.Date.max()
    with candidate.bind_replay() as invocation:
        new_scope = invocation.function.__globals__
        old = old_scope['signal_history'](inputs, parameters, end)
        new = new_scope['signal_history'](inputs, parameters, end)
        assert_frame_equal(old, new, check_exact=True)
        steps = []
        for day in market.Date:
            visible = {name: frame.loc[pd.to_datetime(frame.Date).dt.normalize().le(day)].copy()
                       for name, frame in inputs.items()}
            expected = old_scope['signal_history'](visible, parameters, day)
            current = new_scope['signal_history'](visible, parameters, day)
            assert_frame_equal(expected, current, check_exact=True)
            main = frames['hfq_daily'].loc[market.Date.le(day)].copy()
            ctx = SimpleNamespace(history=FrameView(main), parameters=parameters,
                observations={name: FrameView(frame) for name, frame in visible.items() if name != 'adjusted_daily'})
            # No planning, budget, quantity, cash, execution-price or portfolio fields exist.
            outcome = invocation.function(ctx, SimpleNamespace(account=StateRecord(), cycle=None))
            assert isinstance(outcome.cycle_values, StateRecord)
            target = float(current.loc[day].target_position)
            assert outcome.decision.target == target
            steps.append({'day': day.date().isoformat(), 'target': target})
    result = {'status': 'PASS', 'candidate_content_sha256': candidate.content_identity.content_sha256,
        'candidate_diagnostic_id': candidate.candidate_id, 'financial_history_rows': len(old),
        'all_columns_exact': True, 'prefix_checks': len(steps),
        'native_step_checks': len(steps), 'signal_math_sha256': sha256((source / 'signals.py').read_bytes()).hexdigest(),
        'seed_sha256': sha256((source / 'seed.csv').read_bytes()).hexdigest(),
        'planning_fields_accessed': False, 'raw_price_accessed': False,
        'typed_cycle_state_all_decisions': True,
        'signal_targets_observed': sorted(set(x['target'] for x in steps)),
        'policy': candidate.definition.execution_policy.to_dict() if hasattr(candidate.definition.execution_policy,'to_dict') else {
            'type': candidate.definition.execution_policy.policy_type, 'capital_mode': 'target_equity_fraction'},
        'buy_premium': candidate.definition.execution_spec.buy_premium,
        'source_path': source.relative_to(ROOT).as_posix(), 'data': provenance,
        'limits': ['Financial predicates and targets only; no old/new trade or account equity equivalence claim',
                   'Old entry-cycle quantity lock removed under the authorized current-equity-target model',
                   'Current replay and formal PTE verification are separate parent orchestration steps']}
    (HERE / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status','financial_history_rows','prefix_checks','native_step_checks',
        'signal_targets_observed','buy_premium')}, ensure_ascii=False))
    assert definition is not None


if __name__ == '__main__':
    main()
