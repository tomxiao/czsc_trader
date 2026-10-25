"""Fresh independent accounts for the user's exact 2026 comparison window."""
from __future__ import annotations

# ruff: noqa: E402 -- bound native threads before numerical imports
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from czsc_trader.application import RepositoryContext, create_research_context, load_candidate, publish_evidence, BacktestRequest
from czsc_trader.cli.backtest import run_independent_backtest
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, ExecutionResources, MaterialEvidenceWrite
from strategy_manager import StrategyRegistry, CandidateKey
from strategy_runtime import validate_release_package, StrategyRuntime

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX083_20261025')
HOME = EX.resolve(ROOT)
OUT = HOME / 'others'
S011_HASH = '5da4a999f28aa699ef60641bc26d34f66e124dda8236063aeeea9b18afa9e89e'
C9700_HASH = '3f92791519e1f9422fef11bb5c9177db4d9d83e628ea5f5cba0ec684b9530d5f'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'), resources=ExecutionResources(2, 1, 13))


def material(ctx, path):
    media = {'.py': 'text/x-python', '.json': 'application/json', '.md': 'text/markdown',
             '.png': 'image/png', '.zip': 'application/zip'}[path.suffix]
    return publish_evidence(ctx, MaterialEvidenceWrite(EX, path.stem, path.read_bytes(), media, path.suffix[1:]))


def identities():
    repo = RepositoryContext.discover(ROOT)
    version = StrategyRegistry(repo.strategy_root).get_version('S011', 'v1')
    assert version.release_hash == S011_HASH
    validate_release_package(repo.strategy_root, 'S011-v1')
    candidate = load_candidate(repo, CandidateKey('S015', 'C9700'))
    assert StrategyRuntime().identify(candidate, dependencies=()).content_sha256 == C9700_HASH
    registration = StrategyRegistry(repo.research_registry_root).get_candidate_registration(CandidateKey('S015', 'C9700'))
    files = [p for p in (ROOT / 'strategies/S011').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [ROOT / 'strategies/deployments/S011-v1.json', *[candidate.source_root / p for p in candidate.payload['runtime']['source_files']]]
    return {'s011_version': version.to_dict(), 'c9700_registration': registration.to_dict(),
            'files': {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in files}}


def prepare():
    path = HOME / 'protocols/comparison.json'
    assert not path.exists()
    protocol = {'authorization': '对S011-v1、C9700执行独立回测，窗口为2026-1-5至2026-10-21，然后做绩效对比',
        'window': {'start': '2026-01-05', 'end': '2026-10-21'}, 'symbol': '159326.SZ',
        'account': {'initial_cash': 100000, 'initial_quantity': 0, 'fee_per_side': .001,
                    'price_basis': 'HFQ_RESEARCH', 'lot_size': 100, 'execution_model': 'DAILY_RANGE_V3', 'force_end_liquidation': False},
        'preserved_differences': {'buy_limit_premium': {'S011-v1': .003, 'C9700': .01},
            'capital_and_signals': 'Use each authenticated strategy contract unchanged; do not harmonize away strategy design.'},
        'independence': 'Two newly calculated standalone cash accounts; preserve canonical signal prehistory but no old account equity or positions. Already-observed history is not independent out-of-sample validation.',
        'metrics': ['net return', 'max drawdown magnitude', 'final equity', 'annualized return (252 sessions)',
                    'Sharpe', 'Calmar', 'closed trade count', 'win rate', 'win/loss ratio', 'fees', 'time in market', 'drawdown dates'],
        'scope': 'Fixed comparison only. No optimization, candidate change, freeze, deployment or production action. No change to earlier research gates or qualification.',
        'benchmark_limit': 'Complete backtest buyhold/MA baselines are contextual; not the research mandate LimitBuyHold acceptance test.',
        'resources': {'parallel_accounts': 2, 'native_threads_per_process': 1}, 'identities': identities()}
    save(path, protocol)
    ctx = context()
    save(OUT / 'prepared.json', {'references': [material(ctx, p).to_dict() for p in (path, Path(__file__))],
        'source_hashes': {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in (path, Path(__file__))}})
    print('PROTOCOL_READY', flush=True)


def run(label):
    assert not (OUT / f'{label}_run.json').exists()
    for path, digest in read(OUT / 'prepared.json')['source_hashes'].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest
    protocol = read(HOME / 'protocols/comparison.json')
    assert identities() == protocol['identities']
    repo = RepositoryContext.discover(ROOT)
    strategy = (StrategyRegistry(repo.strategy_root).get_version('S011', 'v1') if label == 'S011-v1'
                else load_candidate(repo, CandidateKey('S015', 'C9700')))
    started = perf_counter()
    result = run_independent_backtest(repo, strategy,
        BacktestRequest('159326.SZ', 'etf', date(2026, 1, 5), date(2026, 10, 21), 100000., 100), ROOT / 'outputs')
    assert result.status == 'PASS'
    assert identities() == protocol['identities']
    saved = {'status': result.status, 'elapsed_seconds': perf_counter() - started,
             'data': dict(result.result), 'artifacts': dict(result.artifacts), 'strategy_files_unchanged': True}
    save(OUT / f'{label}_run.json', saved)
    print(json.dumps({'strategy': label, 'status': result.status, 'output': result.result['output_dir'],
                      'metrics': result.result['metrics']['strategy']['metrics']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'S011-v1', 'C9700'))
    mode = parser.parse_args().mode
    prepare() if mode == 'prepare' else run(mode)
