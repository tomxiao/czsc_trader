"""Exact saved-account comparison, authenticated input checks and publication."""
from hashlib import sha256
from dataclasses import asdict
import json
import pandas as pd
from repair import ROOT, EROOT, RESULTS, EXPERIMENT_ID, read, save, candidate, frozen_hashes
from dataflows import Dataflows, DataSpace, ProviderConfig
from pathlib import Path
from strategy_runtime import StrategyInputBinding, StrategyRuntime
from czsc_trader.application import RepositoryContext, create_research_context, publish_evidence, load_candidate
from czsc_trader.research_tools import (ResearchBatchRef, ExperimentRef, MaterialEvidenceWrite,
    EvidenceRef, EvaluationResources)
from czsc_trader.research_tools.evaluation import validate_evaluation_evidence
from strategy_manager import CandidateKey


def main():
    flows = Dataflows(base_dir=ROOT, space=DataSpace(Path('data/backtest')), providers=ProviderConfig(bindings={}))
    identity_columns = {'decision_id', 'order_id', 'fill_id', 'cycle_id'}
    comparisons = []
    for start, original in [('2026-06-30', '1022_02_S011-v1'), ('2026-01-05', '1022_04_S011-v1'), ('2025-02-17', '1022_06_S011-v1')]:
        a = ROOT / 'outputs' / original
        b = ROOT / read(RESULTS / f'backtest_{start}.json')['data']['output_dir']
        tables, mappings = {}, {}
        for name in ('decisions', 'orders', 'fills', 'trades', 'account_daily'):
            left = pd.read_csv(a / f'{name}.csv', float_precision='round_trip')
            right = pd.read_csv(b / f'{name}.csv', float_precision='round_trip')
            assert list(left.columns) == list(right.columns)
            # Check one-to-one ID remapping consistently across all linked ledgers.
            for col in identity_columns.intersection(left.columns):
                mapping = mappings.setdefault(col, {})
                for old, new in zip(left[col], right[col], strict=True):
                    if pd.isna(old):
                        assert pd.isna(new)
                        continue
                    assert pd.notna(new)
                    assert mapping.setdefault(old, new) == new
                assert len(set(mapping.values())) == len(mapping)
            cols = [col for col in left.columns if col not in identity_columns]
            pd.testing.assert_frame_equal(left[cols], right[cols], check_exact=True)
            tables[name] = {'rows': len(left), 'economic_columns': cols, 'exact_equal': True,
                'old_sha256': sha256((a / f'{name}.csv').read_bytes()).hexdigest(),
                'new_sha256': sha256((b / f'{name}.csv').read_bytes()).hexdigest()}
        old, new = read(a / 'manifest.json'), read(b / 'manifest.json')
        assert old['request'] == new['request']
        assert old['execution_data'] == new['execution_data']
        assert old['metrics']['strategy']['metrics'] == new['metrics']['strategy']['metrics']
        assert old['metrics']['benchmarks'] == new['metrics']['benchmarks']
        bindings = [StrategyInputBinding.from_mapping(m['signal_support']['input_binding']) for m in (old, new)]
        inputs = {}
        for name in bindings[0].plan.requests:
            data = [flows.fetch(binding.plan.requests[name], prepared=binding.prepared) for binding in bindings]
            assert all(item.ready for item in data)
            pd.testing.assert_frame_equal(data[0].dataframe, data[1].dataframe, check_exact=True)
            inputs[name] = {'rows': len(data[0].dataframe), 'content_sha256': data[0].identity.content_sha256,
                            'exact_equal': True}
        comparisons.append({'start': start, 'old': a.relative_to(ROOT).as_posix(), 'new': b.relative_to(ROOT).as_posix(),
            'tables': tables, 'inputs': inputs, 'metrics_exact_equal': True,
            'execution_data_exact_equal': True, 'identities_bijective_and_referentially_consistent': True})

    # Earlier audit supplies a pre-repair frozen baseline. Deployment receipt is
    # tracked separately and git diff verifies it at delivery.
    baseline = read(ROOT / 'outputs/1022_09_S011_implementation_review/checks.json')['frozen_files_sha256']
    for path, expected in baseline.items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == expected
    ref = EvidenceRef.from_dict(read(EROOT / 'others/account_evidence.json'))
    evidence = read(ref.resolve(ROOT))
    validate_evaluation_evidence(evidence)
    account = pd.DataFrame(evidence['runs'][0]['ledgers']['account_daily']['data'])
    restored_path = ROOT / read(RESULTS / 'backtest_2025-02-06.json')['data']['output_dir']
    restored = pd.read_csv(restored_path / 'account_daily.csv', float_precision='round_trip')
    assert len(account) == len(restored) == 415
    for col in ('cash', 'quantity', 'equity'):
        pd.testing.assert_series_equal(account[col], restored[col], check_dtype=False, check_exact=True)
    extra = restored[restored.date < '2025-02-17']
    assert len(extra) == 7 and extra.quantity.eq(0).all() and extra.equity.eq(100000).all()
    repo = RepositoryContext.discover(ROOT)
    saved = load_candidate(repo, CandidateKey('S011', 'C9902'))
    runtime = StrategyRuntime()
    assert runtime.identify(saved, dependencies=()) == runtime.identify(candidate(), dependencies=())
    result = {'status': 'PASS', 'comparisons': comparisons,
        'restored': {'sessions': 415, 'extra_initial_cash_sessions': 7,
                     'metrics': read(restored_path / 'metrics.json')['strategy']['metrics'],
                     'formal_evidence': ref.to_dict(), 'formal_tdr_cash_quantity_equity_exact': True},
        'candidate_identity': asdict(runtime.identify(saved, dependencies=())),
        'frozen_files_unchanged': True, 'frozen_sha256': frozen_hashes()}
    save(RESULTS / 'verification.json', result)
    ctx = create_research_context(repo, ResearchBatchRef('S011'), resources=EvaluationResources(1, 1, 13))
    published = publish_evidence(ctx, MaterialEvidenceWrite(ExperimentRef('S011', EXPERIMENT_ID),
        'technical_repair_verification', (RESULTS / 'verification.json').read_bytes(), 'application/json', 'json'))
    save(EROOT / 'others/verification_evidence.json', published.to_dict())
    print(json.dumps({'status': 'PASS', 'windows': len(comparisons), 'restored_sessions': 415,
                      'evidence': published.to_dict()}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
