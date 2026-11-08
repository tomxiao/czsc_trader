"""Verify S011 financial signals using retained DFLS inputs; no orders or searches."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef
from dataflows import ProviderConfig
from strategy_runtime import StrategyInputBinding, StrategyRuntime, StateRecord
import adaptation as a


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def inputs():
    path = a.ROOT / 'research/S011/experiments/EX084_20261026/others/S011-v1/equivalence/new_binding.json'
    binding = StrategyInputBinding.from_mapping(json.loads(path.read_bytes()))
    context = create_research_context(RepositoryContext.discover(a.ROOT), ResearchBatchRef('S011'),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    frames, provenance = {}, {}
    for name in ('daily', 'bars', 'market', 'spx'):
        request = binding.plan.requests[name]
        fetched = context.data.fetch(request, prepared=binding.prepared)
        if not fetched.ready:
            raise RuntimeError(str(fetched.error))
        frames[name] = fetched.dataframe.copy()
        provenance[name] = {'content_sha256': fetched.identity.content_sha256, 'rows': len(fetched.dataframe)}
    return frames, {'binding_path': path.relative_to(a.ROOT).as_posix(), 'binding': binding.to_dict(), 'assets': provenance}


def main():
    frames, provenance = inputs()
    # Preserve the full-window cutoff used by the last native migration.
    frames = {k: v.loc[pd.to_datetime(v.Date).dt.normalize() <= '2026-09-29'].copy() for k, v in frames.items()}
    candidate = a.build('v1', 'C9990', a.ROOT / '.tmp/s011-current-contract-verification' / uuid4().hex / 'strategy_runtime')
    StrategyRuntime().describe(candidate)
    old = module(a.ORIGINAL_STRATEGIES / 'S011/releases/v1/src/strategy_runtime/signal_math.py', 's011_old_math')
    old_history = old.policy(old.features(frames), dict(candidate.definition.parameters),
        pd.DatetimeIndex(frames['daily'].Date)[pd.to_datetime(frames['daily'].Date) >= '2025-02-05'])
    def view(frame):
        return SimpleNamespace(to_frame=lambda: frame.copy())
    count = 0
    reasons = set()
    with candidate.bind_replay() as invocation:
        for day, expected in old_history.iterrows():
            cut = {k: frame.loc[pd.to_datetime(frame.Date).dt.normalize() <= day].copy() for k, frame in frames.items()}
            context = SimpleNamespace(history=view(cut['daily']), auxiliary_histories={'intraday': view(cut['bars'])},
                observations={'market': view(cut['market']), 'spx': view(cut['spx'])}, parameters=dict(candidate.definition.parameters))
            outcome = invocation.function(context, None)
            assert outcome.decision.target == float(expected.target_position)
            assert not outcome.account.values and type(outcome.cycle_values) is StateRecord
            assert not outcome.cycle_values.values
            count += 1
            reasons.add(str(expected.reason))
    result = {'status': 'PASS', 'candidate_content_sha256': candidate.content_identity.content_sha256,
        'prefix_decisions': count, 'target_differences': 0, 'reasons': sorted(reasons),
        'first': str(old_history.index[0].date()), 'last': str(old_history.index[-1].date()),
        'signal_math_unchanged': True, 'strategy_account_fields_removed': True,
        'verification': 'Each prefix executes new entrypoint against original pure financial signal target; no financial/economic equivalence claim for execution.',
        'inputs': provenance}
    (Path(__file__).parent / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'inputs'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
