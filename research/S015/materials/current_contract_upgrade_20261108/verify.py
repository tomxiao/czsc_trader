"""Verify S015 price-center semantics using retained RAW/HFQ DFLS assets."""
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
    source = a.ROOT / 'research/S015/experiments/EX081_20261025/others/input_identity.json'
    binding = StrategyInputBinding.from_mapping(json.loads(source.read_bytes())['coordinates'][0]['input_binding'])
    context = create_research_context(RepositoryContext.discover(a.ROOT), ResearchBatchRef('S015'),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    frames, provenance = {}, {'s015_binding': binding.to_dict(), 's015_binding_path': source.relative_to(a.ROOT).as_posix(), 'assets': {}}
    for name in ('market', 'execution', 'intraday'):
        fetched = context.data.fetch(binding.plan.requests[name], prepared=binding.prepared)
        if not fetched.ready:
            raise RuntimeError(str(fetched.error))
        frames[name] = fetched.dataframe.copy()
        provenance['assets'][name] = {'content_sha256': fetched.identity.content_sha256, 'rows': len(fetched.dataframe)}
    # The same authorized ETF's existing HFQ30m asset is retained in S011.
    source = a.ROOT / 'research/S011/experiments/EX084_20261026/others/S011-v1/equivalence/new_binding.json'
    hfq_binding = StrategyInputBinding.from_mapping(json.loads(source.read_bytes()))
    other = create_research_context(RepositoryContext.discover(a.ROOT), ResearchBatchRef('S011'),
        providers=ProviderConfig(bindings={}, equity_bindings={}))
    fetched = other.data.fetch(hfq_binding.plan.requests['bars'], prepared=hfq_binding.prepared)
    if not fetched.ready:
        raise RuntimeError(str(fetched.error))
    frames['hfq_intraday'] = fetched.dataframe.copy()
    provenance['s011_binding'] = hfq_binding.to_dict()
    provenance['s011_binding_path'] = source.relative_to(a.ROOT).as_posix()
    provenance['assets']['hfq_intraday'] = {'content_sha256': fetched.identity.content_sha256, 'rows': len(fetched.dataframe)}
    last = min(pd.to_datetime(frames[x].Date).dt.normalize().max() for x in frames)
    frames = {k: frame.loc[pd.to_datetime(frame.Date).dt.normalize() <= last].copy() for k, frame in frames.items()}
    frames['hfq_intraday'] = frames['hfq_intraday'].loc[pd.to_datetime(frames['hfq_intraday'].Date) >= '2025-01-02'].copy()
    return frames, provenance


def main():
    frames, provenance = inputs()
    candidate = a.build('v1', 'C9990', a.ROOT / '.tmp/s015-current-contract-verification' / uuid4().hex / 'strategy_runtime')
    StrategyRuntime().describe(candidate)
    parameters = dict(candidate.definition.parameters)
    old = module(a.ORIGINAL_STRATEGIES / 'S015/releases/v1/src/strategy_runtime/signal_math.py', 's015_old_math')
    new = module(candidate.source_root / 'signal_math.py', 's015_new_math')
    before = old.intentions(old.causal_features(frames['market'], frames['execution'], frames['intraday'],
        parameters['lookback'], parameters['center_kind']), parameters)
    after = new.intentions(new.causal_features(frames['market'], frames['hfq_intraday'],
        parameters['lookback'], parameters['center_kind']), parameters)
    pd.testing.assert_index_equal(before.index, after.index)
    for column in ('target_position', 'entry_signal', 'exit_signal', 'permission'):
        assert before[column].equals(after[column]), column
    differences = {column: float((before[column] - after[column]).abs().max())
        for column in ('m', 'p', 'center_gain', 'repair_space', 'repair_target', 'invalidation_origin')}
    assert max(differences.values()) < 1e-12
    def view(frame):
        return SimpleNamespace(to_frame=lambda: frame.copy())
    count = 0
    with candidate.bind_replay() as invocation:
        for day, expected in before.iterrows():
            if day < pd.Timestamp('2025-01-02'):
                continue
            context = SimpleNamespace(history=view(frames['market'].loc[pd.to_datetime(frames['market'].Date) <= day]),
                auxiliary_histories={'intraday': view(frames['hfq_intraday'].loc[pd.to_datetime(frames['hfq_intraday'].Date).dt.normalize() <= day])},
                parameters=parameters)
            outcome = invocation.function(context, None)
            assert outcome.decision.target == float(expected.target_position) * parameters['allocation']
            assert not outcome.account.values and type(outcome.cycle_values) is StateRecord
            assert not outcome.cycle_values.values
            count += 1
    # Allocation remains a strategy target proportion, independent of channel cash.
    active_days = before.index[before.target_position > 0]
    assert len(active_days)
    day = active_days[0]
    context = SimpleNamespace(history=view(frames['market'].loc[pd.to_datetime(frames['market'].Date) <= day]),
        auxiliary_histories={'intraday': view(frames['hfq_intraday'].loc[pd.to_datetime(frames['hfq_intraday'].Date).dt.normalize() <= day])},
        parameters={**parameters, 'allocation': .25})
    with candidate.bind_replay() as invocation:
        assert invocation.function(context, None).decision.target == .25
    result = {'status': 'PASS', 'candidate_content_sha256': candidate.content_identity.content_sha256,
        'prefix_decisions': count, 'target_differences': 0, 'max_feature_differences': differences,
        'first': str(before.index[1].date()), 'last': str(before.index[-1].date()),
        'allocation_preserved': parameters['allocation'], 'allocation_boundary_check': .25,
        'input_model': 'DFLS HFQ30m replaces RAW30m plus daily-factor conversion; matched financial targets, not old/new economic execution equivalence.',
        'inputs': provenance}
    (Path(__file__).parent / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'inputs'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
