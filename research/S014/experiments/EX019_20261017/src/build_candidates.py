"""Describe four fixed extension candidates; baseline identities stay original."""
from hashlib import sha256
import json
from pathlib import Path

from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
OLD = EX.parent / 'EX018_20261017'
PACKAGE = EX / 'src/strategy_runtime'
EXTENSIONS = ('extend_profit', 'extend_rising', 'extend_both', 'extend_either')
VARIANTS = ('baseline_H3', 'baseline_H6') + EXTENSIONS
BASELINES = {
    'baseline_H3': ('EX017_20261017', 'payload_v3_high_H3.json', 'C0011', 'high_H3'),
    'baseline_H6': ('EX018_20261017', 'payload_parent_high_H6.json', 'C0016', 'parent_high_H6'),
}


def main():
    original = json.loads((OLD / 'protocols/payload_parent_high_H6.json').read_text(encoding='utf-8'))
    runtime = original['runtime']
    assert implementation_sha256(tuple(runtime['source_files']), source_root=OLD / 'src/strategy_runtime') == runtime['source_sha256']
    samples = (PACKAGE / 'strategies/calibration_samples.csv').read_bytes()
    assert samples == (OLD / 'src/strategy_runtime/strategies/calibration_samples.csv').read_bytes()
    files = ('strategies/repair.py', 'strategies/calibration_samples.csv')
    assert all(b'\r' not in (PACKAGE / name).read_bytes() for name in files)
    digest = implementation_sha256(files, source_root=PACKAGE)
    identities = []
    for number, variant in enumerate(EXTENSIONS, 21):
        destination = EX / 'protocols' / f'payload_{variant}.json'
        if destination.exists():
            raise RuntimeError('Preserve existing fixed payload: ' + variant)
        payload = {'runtime': {'module': 'strategy_runtime.strategies.repair', 'qualname': 'RepairStrategy',
                              'contract_version': 1, 'source_files': list(files), 'source_sha256': digest},
                   'parameters': {'variant': variant}}
        candidate = StrategyCandidate('S014', f'C{number:04}', payload, PACKAGE)
        description = StrategyRuntime().describe(candidate)
        destination.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8', newline='\n')
        identities.append({'candidate': candidate.reference_id, 'variant': variant,
                           'runtime_sha256': description.runtime_sha256, 'source_sha256': digest})
    print(json.dumps({'prepared_candidates': identities, 'original_baselines': BASELINES,
                      'calibration_sha256': sha256(samples).hexdigest(), 'account_runs': 0,
                      'supplier_calls': 0, 'registered_or_published': False}))


if __name__ == '__main__':
    main()
