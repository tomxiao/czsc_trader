"""Synthetic checks of the exact EX017 scheduler; never call a real diagnosis.

Run is stubbed in parent and spawned processes. Current typed dependencies and
analysis/check source hashes are retained; historical preparation is background,
not a substitute for this independently executed synthetic validation.
"""
# ruff: noqa: E402
from datetime import date
from hashlib import sha256
from pathlib import Path
import inspect
import json
import multiprocessing
import os
import pickle
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(HERE))

from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from czsc_trader.research_tools.account_diagnosis import (AccountDiagnosisRequest, AccountRunRef,
    AccountDiagnosisResult, DiagnosisReconciliation)
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_evaluator.account_diagnosis import AccountDiagnosisStatus
from strategy_manager import CandidateKey
# The active runner must never be imported by this synthetic-only check.
def forbidden(*args, **kwargs):
    raise AssertionError('synthetic checks must never invoke public account actions')


stub = types.ModuleType('run')
stub.ROOT, stub.WORK = ROOT, WORK
stub.REPOSITORY = None
stub.EXPERIMENT = ExperimentRef('S017', 'EX017_20261029')
stub.DATA_READINESS = HERE / 'NONEXISTENT_SYNTHETIC_ONLY.json'
stub.configurations = lambda: {'C0046': {'volume_gate': True, 'allow_overnight': True}}
stub.read = lambda path: [['C0046', 'C0037'], ['C0046', 'C0044']]
for name in ('context', 'save', 'material', 'candidate', 'decision_evidence', 'checked_precheck'):
    setattr(stub, name, forbidden)
sys.modules['run'] = stub
import analyze as candidate
import publish
candidate.diagnose_accounts = forbidden
publish.publish_evidence = forbidden
publish.validate_experiment = forbidden

PAIRS = (('C0046', 'C0013'), ('C0046', 'C0037'), ('C0046', 'C0044'))


def requests():
    accounts = {}
    for key in ('C0013', 'C0037', 'C0044', 'C0046'):
        digest = sha256(('SYNTHETIC_ONLY_' + key).encode()).hexdigest()
        origin = ExperimentRef('S017', 'EX003_20261028' if key == 'C0013' else 'EX015_20261029')
        reference = EvidenceRef(origin, digest + '.json', digest, 'application/json',
                                'synthetic-' + key, 'equity_research', 2)
        identity = EvaluationIdentity(CandidateKey('S017', key), 'a' * 64, 'b' * 64, 'c' * 64, 'd' * 64)
        accounts[key] = AccountRunRef(reference, identity)
    return tuple(AccountDiagnosisRequest(accounts[control], accounts[subject],
        EvaluationWindow('DEV_2019_2025', date(2019, 1, 2), date(2025, 12, 31)))
        for subject, control in PAIRS)


def index(request):
    return PAIRS.index((request.alternative.identity.candidate.candidate_id,
                        request.baseline.identity.candidate.candidate_id))


def synthetic_result(request):
    number = index(request)
    return AccountDiagnosisResult(AccountDiagnosisStatus.COMPUTED, 'SYNTHETIC_ONLY', (),
        (request.baseline.evidence, request.alternative.evidence),
        reconciliation=(DiagnosisReconciliation(request.alternative.identity.evaluation_id,
            100., 101. + number, 1. + number, 1. + number, 0.),))


def synthetic_worker(request):
    assert type(request) is AccountDiagnosisRequest
    assert all(os.environ[name] == '1' for name in candidate.NATIVE_THREAD_ENV)
    from threadpoolctl import threadpool_info
    assert all(item['num_threads'] == 1 for item in threadpool_info())
    directory = Path(os.environ['S017_SYNTHETIC_SPAWN_DIR'])
    number = index(request)
    (directory / f'start-{number}.json').write_text(json.dumps({'pid': os.getpid()}))
    deadline = time.monotonic() + 15.
    while len(tuple(directory.glob('start-*.json'))) < 3:
        if time.monotonic() >= deadline:
            raise RuntimeError('three synthetic workers did not reach the barrier')
        time.sleep(.01)
    time.sleep((3 - number) * .12)
    (directory / f'finish-{number}.json').write_text(json.dumps({'time': time.monotonic()}))
    return synthetic_result(request)


def synthetic_failure(request):
    if index(request) == 1:
        raise RuntimeError('SYNTHETIC_SECOND_PAIR_FAILURE')
    return synthetic_result(request)


def synthetic_wrong_type(request):
    return {} if index(request) == 1 else synthetic_result(request)


def synthetic_noncomputed(request):
    if index(request) == 1:
        return AccountDiagnosisResult(AccountDiagnosisStatus.INVALID_EVIDENCE, 'SYNTHETIC_ONLY',
            ('synthetic invalid evidence',), (request.baseline.evidence, request.alternative.evidence))
    return synthetic_result(request)


def static_contracts():
    assert sys.modules['run'] is stub
    original = json.loads((WORK / 'others/analysis_scheduling_original_result.json').read_bytes())
    assert original['status'] == 'PASS' and original['real_diagnoses'] == original['real_replays'] == 0
    assert original['candidate_sha256'] == sha256((HERE / 'analyze.py').read_bytes()).hexdigest()
    assert candidate.comparison_pairs(('C0046',)) == PAIRS
    for keys in (('C0044',), ('C0046', 'C0036'), ()):
        try:
            candidate.comparison_pairs(keys)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid new candidate set accepted')
    correct_reader = candidate.read
    for pairs in ([['C0046', 'C0044'], ['C0046', 'C0037']], [['C0046', 'C0036']], []):
        candidate.read = lambda path: pairs
        try:
            candidate.comparison_pairs(('C0046',))
        except ValueError:
            pass
        else:
            raise AssertionError('changed diagnosis plan accepted')
    candidate.read = correct_reader
    assert tuple(candidate.OLD_CONTROLS) == ('C0013', 'C0037', 'C0044')
    # Pure rendering from synthetic summaries; no account reads or publication.
    run = {'metrics': {'annualized_return': .1, 'bar_max_drawdown': .3, 'daily_max_drawdown': .2,
        'closed_cycles': 1, 'rolling_60_closed_cycle_counts': [1],
        'rolling_60_closed_cycle_median': 1, 'fees': 2.},
        'account_points': [{'quantity': 1}],
        'account_daily': [{'session': '2019-01-02', 'quantity': 1, 'equity': 100001.}]}
    own = candidate.summarize_run(run, 100000.)
    checks = candidate.goals(own, own)
    summaries = {key: {'candidate': own, 'benchmark': own, 'goals': checks,
        'all_goals_met': all(checks.values())} for key in ('C0013', 'C0037', 'C0044', 'C0046')}
    references = {request.alternative.identity.candidate.candidate_id: request.alternative.evidence
                  for request in requests()}
    references.update({request.baseline.identity.candidate.candidate_id: request.baseline.evidence
                       for request in requests()})
    diagnostic_refs = {subject + '_vs_' + control: references[subject] for subject, control in PAIRS}
    report = publish.render_report({'summaries': summaries}, ('C0046',), references, diagnostic_refs, PAIRS)
    assert report.encode('utf-8').decode('utf-8') == report
    assert '1个固定配置、2个完整账户路径' in report and '3项公共账户诊断' in report
    assert all('|' + subject + ' / ' + control + '|' in report for subject, control in PAIRS)
    assert '|C0036|' not in report and '|C0036 / ' not in report
    assert '273' not in report and '弱市入场' not in report
    for path in ('analyze.py', 'publish.py'):
        compile((HERE / path).read_bytes(), str(HERE / path), 'exec')


def main():
    before = sha256((HERE / 'analyze.py').read_bytes()).hexdigest()
    static_contracts()
    values = requests()
    assert pickle.loads(pickle.dumps(values)) == values
    serial = [synthetic_result(request).to_dict() for request in values]
    original_environment = {name: os.environ.get(name) for name in candidate.NATIVE_THREAD_ENV}
    directory = ROOT / '.tmp' / 's017-analysis-scheduling' / ('spawn-' + str(os.getpid()))
    directory.mkdir(parents=True)
    os.environ['S017_SYNTHETIC_SPAWN_DIR'] = str(directory)
    with candidate.parallel_diagnoses(values, worker=synthetic_worker) as outcomes:
        actual = [result.to_dict() for result in outcomes]
    assert actual == serial
    finishes = [json.loads((directory / f'finish-{number}.json').read_text())['time'] for number in range(3)]
    assert finishes[2] < finishes[1] < finishes[0]
    pids = {json.loads(path.read_text())['pid'] for path in directory.glob('start-*.json')}
    assert len(pids) == 3
    for worker, error, message in ((synthetic_failure, RuntimeError, 'SYNTHETIC_SECOND_PAIR_FAILURE'),
                                    (synthetic_wrong_type, TypeError, 'unexpected result type')):
        observed = []
        try:
            with candidate.parallel_diagnoses(values, worker=worker) as outcomes:
                for result in outcomes:
                    observed.append(result.to_dict())
        except error as issue:
            assert message in str(issue)
        else:
            raise AssertionError('worker error was swallowed')
        assert observed == serial[:1]
        assert not multiprocessing.active_children()
    with candidate.parallel_diagnoses(values, worker=synthetic_noncomputed) as outcomes:
        statuses = [result.status for result in outcomes]
    assert statuses == [AccountDiagnosisStatus.COMPUTED, AccountDiagnosisStatus.INVALID_EVIDENCE,
                        AccountDiagnosisStatus.COMPUTED]
    try:
        with candidate.parallel_diagnoses(values[:2], worker=synthetic_result):
            raise AssertionError('incomplete pair set accepted')
    except ValueError:
        pass
    assert original_environment == {name: os.environ.get(name) for name in candidate.NATIVE_THREAD_ENV}
    assert not multiprocessing.active_children()
    assert before == sha256((HERE / 'analyze.py').read_bytes()).hexdigest()
    dependency_paths = {Path(inspect.getsourcefile(value)).resolve() for value in (
        EvidenceRef, ExperimentRef, AccountDiagnosisRequest, AccountRunRef,
        AccountDiagnosisResult, DiagnosisReconciliation, EvaluationIdentity,
        EvaluationWindow, AccountDiagnosisStatus, CandidateKey)}
    import threadpoolctl
    dependency_paths.add(Path(threadpoolctl.__file__).resolve())
    dependencies = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
                    for path in sorted(dependency_paths)}
    report = {'status': 'PASS', 'synthetic_only': True, 'workers': 3, 'native_threads': 1,
        'typed_request_result_pickle': True, 'completion_order': [2, 1, 0], 'returned_order': [0, 1, 2],
        'serial_result_fields_equal': True, 'worker_exception_propagated_without_retry': True,
        'wrong_result_type_rejected': True, 'noncomputed_status_preserved': True,
        'formal_analysis_source_unchanged': True, 'parent_publication_not_invoked': True,
        'native_environment_restored': True, 'children_joined': True, 'active_runner_never_imported': True,
        'three_fixed_pairs_and_utf8_report': True, 'real_diagnoses': 0, 'real_replays': 0,
        'candidate_sha256': before, 'check_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'dependency_sha256': dependencies,
        'original_preparation_result_sha256': sha256((WORK / 'others/analysis_scheduling_original_result.json').read_bytes()).hexdigest(),
        'original_preparation_role': 'BACKGROUND_ONLY_CURRENT_SYNTHETIC_CHECK_IS_INDEPENDENT',
        'python_version': sys.version, 'scope': 'EX017_CURRENT_ANALYSIS_SYNTHETIC_SPAWN_ONLY'}
    (WORK / 'others/analysis_scheduling_check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
