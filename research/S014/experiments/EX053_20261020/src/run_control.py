"""One pinned-input public evaluation of C9522 against original C9521 evidence."""
from datetime import date
import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import sys

from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import (
    EvaluationBenchmark, EvaluationCost, EvaluationEvidenceWrite, EvaluationRequest,
    EvaluationResources, EvaluationWindow, ExperimentRef, LimitBuyHold, MaterialEvidenceWrite,
)

ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EX / 'work'))
from build_candidate import build, build_declared_candidate  # noqa: E402
from compare_full_account import compare, ORIGINAL, ORIGINAL_SHA  # noqa: E402


def block_network(*args, **kwargs):
    raise RuntimeError('Full equivalence control uses authenticated original offline inputs only')


def write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        handle.write('\n')


def main(candidate_id='C9522'):
    socket.socket.connect = block_network
    socket.create_connection = block_network
    offline_path = ROOT / 'research/S014/experiments/EX052_20261020/src/offline_inputs.py'
    spec = importlib.util.spec_from_file_location('ex053_pinned_provider', offline_path)
    offline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(offline)
    ctx = offline.get_context(EvaluationResources(max_workers=1, native_threads_per_worker=1, random_seed=17))
    candidate, _ = build() if candidate_id == 'C9522' else build_declared_candidate()
    prefix = '' if candidate_id == 'C9522' else 'c9523_'
    source = candidate.source_root / 'strategies/trend_permission.py'
    source_sha = sha256(source.read_bytes()).hexdigest()
    assert sha256(ORIGINAL.read_bytes()).hexdigest() == ORIGINAL_SHA
    original = json.loads(ORIGINAL.read_bytes())
    request = EvaluationRequest(
        repository_root=ROOT, experiment_id=EX.name, strategy=candidate,
        runtime_binding={'candidate_id': candidate.reference_id,
            'source_files': ['strategies/trend_permission.py'],
            'implementation_sha256': candidate.payload['runtime']['source_sha256']},
        symbol='600722.SH', asset_type='stock',
        windows=(EvaluationWindow('full', date(2020, 1, 2), date(2026, 10, 15)),),
        data_cutoff=date(2026, 10, 15), initial_cash=100000,
        costs=(EvaluationCost('baseline', 0.001),),
        benchmark=EvaluationBenchmark(LimitBuyHold(100, 0.01, 0.01, 0.1, 1000000)), workers=1,
    )
    bound = ctx.evaluation.prepare(request)
    owner = ExperimentRef('S014', EX.name)
    source_ref = publish_evidence(ctx, MaterialEvidenceWrite(owner, 'c9522-window-contract-source',
        source.read_bytes(), 'text/x-python', 'py'))
    write(EX / f'others/{prefix}control_dispatch.json', {'candidate': candidate.reference_id,
        'source': source_ref.to_dict(), 'source_sha256': source_sha,
        'execution_fingerprint': bound.execution_data.fingerprint,
        'input_bindings': {k: v.to_dict() for k, v in bound.input_bindings.items()},
        'original_account_sha256': ORIGINAL_SHA, 'new_account_count': 1, 'network_enabled': False})
    outcomes = ctx.evaluation.evaluate_many((bound,))
    outcome = outcomes[0]
    assert outcome.status.value == 'SUCCEEDED', outcome
    ref = publish_evidence(ctx, EvaluationEvidenceWrite(owner, 'c9522-original-full-window-control',
                                                       bound, outcome.result))
    actual = json.loads(ref.resolve(ROOT).read_bytes())
    comparison = compare(original, actual, expected_candidate=candidate_id)
    assert sha256(source.read_bytes()).hexdigest() == source_sha
    write(EX / f'others/{prefix}full_control.json', {'status': 'PASS_EXACT_ORIGINAL_FULL_WINDOW',
        'candidate': candidate.reference_id, 'account': ref.to_dict(),
        'result_hash': outcome.result.result_hash, 'comparison': comparison,
        'source': source_ref.to_dict(), 'market_calls': 0})
    print(json.dumps({'status': 'PASS_EXACT_ORIGINAL_FULL_WINDOW', 'evidence': ref.to_dict(),
                      'comparison': comparison}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', choices=('C9522', 'C9523'), default='C9522')
    main(parser.parse_args().candidate)
