"""Authorized input-contract repair; frozen sources are never written."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

from czsc_trader.application import RepositoryContext
from strategy_manager import StrategyRegistry
from strategy_runtime import StrategyCandidate, StrategyRuntime, implementation_sha256

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENT_ID = 'EX080_20261022'
EROOT = ROOT / 'research/S011/experiments' / EXPERIMENT_ID
RESULTS = ROOT / 'research/S011/assets/runs' / EXPERIMENT_ID
CANDIDATE_ID = 'C9902'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8', newline='\n')


def frozen_hashes():
    paths = list((ROOT / 'strategies/S011').rglob('*'))
    paths.append(ROOT / 'strategies/deployments/S011-v1.json')
    return {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file() and '__pycache__' not in p.parts}


def candidate():
    version = StrategyRegistry(ROOT / 'strategies').get_version('S011', 'v1')
    payload = deepcopy(version.to_dict()['strategy_payload'])
    source = EROOT / 'src/strategy_runtime'
    payload['runtime']['source_sha256'] = implementation_sha256(
        tuple(payload['runtime']['source_files']), source_root=source)
    result = StrategyCandidate('S011', CANDIDATE_ID, payload, source)
    StrategyRuntime().describe(result)
    return result


if __name__ == '__main__':
    import argparse
    import time
    from czsc_trader.application import BacktestRequest
    from czsc_trader.cli.backtest import run_independent_backtest

    parser = argparse.ArgumentParser()
    parser.add_argument('start', choices=['2026-06-30', '2026-01-05', '2025-02-17', '2025-02-06'])
    args = parser.parse_args()
    before = frozen_hashes()
    begin = time.perf_counter()
    result = run_independent_backtest(RepositoryContext.discover(ROOT), candidate(),
        BacktestRequest('159326.SZ', 'etf', date.fromisoformat(args.start), date(2026, 10, 21), 100000., 100),
        ROOT / 'outputs')
    assert frozen_hashes() == before
    record = {'start': args.start, 'end': '2026-10-21', 'elapsed_seconds': time.perf_counter() - begin,
              'status': result.status, 'data': dict(result.result), 'frozen_files_unchanged': True}
    save(RESULTS / f'backtest_{args.start}.json', record)
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
