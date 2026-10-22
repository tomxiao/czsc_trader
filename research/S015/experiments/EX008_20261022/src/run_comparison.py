"""Fixed two-account rerun after the explicitly authorized S011-v1 repair."""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

from czsc_trader.application import (
    RepositoryContext, create_research_context, load_candidate, publish_evidence, BacktestRequest,
)
from czsc_trader.cli.backtest import run_independent_backtest
from czsc_trader.research_tools import ResearchBatchRef, ExperimentRef, EvaluationResources, MaterialEvidenceWrite
from strategy_manager import StrategyRegistry, CandidateKey
from strategy_runtime import validate_release_package

ROOT = Path(__file__).resolve().parents[5]
EX = ExperimentRef('S015', 'EX008_20261022')
EROOT = EX.resolve(ROOT)
S011_HASH = '5da4a999f28aa699ef60641bc26d34f66e124dda8236063aeeea9b18afa9e89e'
C0031_CONTENT = '6a6e536c6c2f017c43d238633267c05f1f2b9d647aa22d52506d9e8e0a81d580'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')


def read(path):
    return json.loads(path.read_bytes())


def context():
    return create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S015'),
                                   resources=EvaluationResources(2, 1, 13))


def identities():
    version = StrategyRegistry(ROOT / 'strategies').get_version('S011', 'v1')
    assert version.release_hash == S011_HASH
    validate_release_package(ROOT / 'strategies', 'S011-v1')
    registry = StrategyRegistry(ROOT / 'research/registrations')
    registration = registry.get_candidate_registration(CandidateKey('S015', 'C0031'))
    assert registration.content_sha256 == C0031_CONTENT
    files = [p for p in (ROOT / 'strategies/S011').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files.append(ROOT / 'strategies/deployments/S011-v1.json')
    return {'s011_version': version.to_dict(), 'c0031_registration': registration.to_dict(),
            'frozen_files': {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in files}}


def prepare():
    path = EROOT / 'protocols/comparison.json'
    assert not path.exists()
    value = {'authorization': '同意，切换RSCH，重做修复后的S011-v1与C0031的全周期比较，重点看收益和回撤，请自主完成。',
        'prior_requirement': '全周期的收益、回撤均好于S011-v1，其他维度延用默认指标，才值得占用PTE的资源',
        'window': {'start': '2025-02-06', 'end': '2026-10-21', 'expected_sessions': 415},
        'boundary_reason': 'S011 restored canonical first execution day; S015 starts earlier, so this is the longest common unchanged-strategy window.',
        'account': {'initial_cash': 100000, 'initial_quantity': 0, 'fee_per_side': .001,
            'price_basis': 'HFQ_RESEARCH', 'lot_size': 100, 'execution': 'DAILY_RANGE_V3', 'force_end_liquidation': False},
        'primary_checks': ['C0031 net return strictly exceeds S011-v1', 'C0031 absolute maximum drawdown strictly below S011-v1'],
        'diagnostics': ['year slices from continuous account', 'maximum drawdown peak/trough/recovery',
            'default metrics', 'rolling 60-session trade frequency', '252-session rolling returns and drawdowns, step 21'],
        'scope': 'Two fixed independent TDR accounts; no optimization, new candidate, freeze, deployment or production action.',
        'default_requirements': 'Unchanged. If the necessary comparative gate fails, do not rerun 32 perturbations or fee stress.',
        'known_limit': 'Previously observed history; rerunning does not create independent out-of-sample evidence. CLI buyhold differs from mandate limit-buyhold; do not claim default benchmark acceptance from it.',
        'resources': {'parallel_accounts': 2, 'native_threads_per_account': 1}, 'identities': identities()}
    save(path, value)
    refs = []
    for p in (path, Path(__file__)):
        ref = publish_evidence(context(), MaterialEvidenceWrite(EX, p.stem, p.read_bytes(),
            'text/x-python' if p.suffix == '.py' else 'application/json', p.suffix[1:]))
        refs.append(ref.to_dict())
    save(EROOT / 'others/protocol_evidence.json', {'references': refs})
    print('PROTOCOL_READY', flush=True)


def run(label):
    protocol = read(EROOT / 'protocols/comparison.json')
    assert identities() == protocol['identities']
    assert not (EROOT / f'others/{label}_run.json').exists()
    repo = RepositoryContext.discover(ROOT)
    strategy = (StrategyRegistry(repo.strategy_root).get_version('S011', 'v1') if label == 'S011-v1'
                else load_candidate(repo, CandidateKey('S015', 'C0031')))
    started = perf_counter()
    result = run_independent_backtest(repo, strategy,
        BacktestRequest('159326.SZ', 'etf', date(2025, 2, 6), date(2026, 10, 21), 100000., 100), ROOT / 'outputs')
    assert result.status == 'PASS'
    assert identities() == protocol['identities']
    saved = {'status': result.status, 'elapsed_seconds': perf_counter()-started,
             'data': dict(result.result), 'artifacts': dict(result.artifacts), 'strategy_files_unchanged': True}
    save(EROOT / f'others/{label}_run.json', saved)
    print(json.dumps(saved, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'S011-v1', 'C0031'))
    mode = parser.parse_args().mode
    prepare() if mode == 'prepare' else run(mode)
