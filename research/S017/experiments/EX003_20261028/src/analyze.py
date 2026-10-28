"""EX003 continuous-account analysis, reusing EX002's pure summary calculations."""
from datetime import date
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import EvidenceRef, ExperimentRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest, AccountRunRef
from czsc_trader.research_tools.equity_evaluation import EquityEvaluationResult
from czsc_trader.research_tools.evaluation import EvaluationIdentity, EvaluationWindow
from strategy_manager import CandidateKey


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load analysis dependency: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Give both runners distinct module identities. Temporarily satisfy EX002's
# existing absolute `from run import ...`, then restore the caller's module.
RUN = _load_module('_s017_ex003_analysis_runner', Path(__file__).with_name('run.py'))
ROOT, WORK, REPOSITORY, EXPERIMENT = RUN.ROOT, RUN.WORK, RUN.REPOSITORY, RUN.EXPERIMENT
PRIOR_EXPERIMENT = ExperimentRef('S017', 'EX002_20261028')
PRIOR_WORK = PRIOR_EXPERIMENT.resolve(ROOT)
PRIOR_SOURCE = PRIOR_WORK/'src/analyze.py'
_prior_runner = _load_module('_s017_ex002_analysis_runner', PRIOR_WORK/'src/run.py')
_sentinel = object()
_saved_run = sys.modules.get('run', _sentinel)
try:
    sys.modules['run'] = _prior_runner
    PRIOR = _load_module('_s017_ex002_analysis_helpers', PRIOR_SOURCE)
finally:
    if _saved_run is _sentinel:
        del sys.modules['run']
    else:
        sys.modules['run'] = _saved_run


def load_subset(work, experiment, keys, *, exact_manifest=False):
    rows = RUN.read(work/'others/accounts.json')
    if exact_manifest and set(rows) != set(keys):
        raise ValueError('new account manifest differs from fixed EX003 configurations')
    if not set(keys) <= set(rows):
        raise ValueError('requested control account is missing')
    payloads, references = {}, {}
    for key in keys:
        record = rows[key]
        reference = EvidenceRef.from_dict(record['evidence'])
        if reference.experiment != experiment or (reference.schema, reference.schema_version) != ('equity_research', 2):
            raise ValueError('account evidence experiment or schema differs')
        payload = EquityEvaluationResult(record['request_hash'], reference.resolve(ROOT).read_bytes()).payload
        if (payload.get('schema'), payload.get('schema_version')) != ('equity-research/v2', 2):
            raise ValueError('unexpected serialized account schema')
        if (payload['evaluation_id'] != record['evaluation_id']
                or payload['evaluation_identity'] != record['evaluation_identity']
                or payload['request']['candidate_id'] != key
                or payload['request']['experiment'] != {
                    'strategy_id': experiment.strategy_id, 'experiment_id': experiment.experiment_id}):
            raise ValueError('account manifest identity differs from published evidence')
        for run in payload['runs'].values():
            PRIOR._validate_run(run, payload['request']['initial_cash'])
        payloads[key], references[key] = payload, reference
    return payloads, references


def account_ref(reference, payload):
    value = dict(payload['evaluation_identity'])
    value['candidate'] = CandidateKey(**value['candidate'])
    return AccountRunRef(reference, EvaluationIdentity(**value))


def diagnostics(payloads, references):
    root = ROOT/'research/S017/assets/runs/EX003_20261028/diagnostics'
    research = RUN.context()
    result = {}
    for subject, control in (('C0011','C0001'), ('C0012','C0011'), ('C0013','C0012')):
        key = subject+'_vs_'+control
        path = root/(key+'.json')
        diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            account_ref(references[control], payloads[control]),
            account_ref(references[subject], payloads[subject]),
            EvaluationWindow('DEV_2019_2025', date(2019,1,2), date(2025,12,31))))
        raw = diagnosis.to_dict()
        RUN.save(path, raw)
        evidence = RUN.material(research, 'diagnosis-'+key, path)
        summaries = []
        for index, pnl in enumerate(diagnosis.pnl_breakdown):
            summaries.append({'evaluation_id': pnl.evaluation_id,
                'opening_equity': pnl.daily[0].opening_equity if pnl.daily else None,
                'closing_equity': pnl.daily[-1].closing_equity if pnl.daily else None,
                'entry': sum(p.entry for p in pnl.daily), 'holding': sum(p.holding for p in pnl.daily),
                'exit': sum(p.exit for p in pnl.daily), 'fees': sum(p.fees for p in pnl.daily),
                'residual': sum(p.residual for p in pnl.daily),
                'annual': raw['pnl_breakdown'][index]['annual']})
        result[key] = {'status': diagnosis.status.value, 'issues': list(diagnosis.issues),
            'baseline': control, 'alternative': subject, 'raw_path': path.relative_to(ROOT).as_posix(),
            'evidence': evidence.to_dict(), 'pnl_summary': summaries,
            'cycle_path_rows': len(diagnosis.path_comparison), 'daily_path_rows': len(diagnosis.daily_paths),
            'reconciliation': raw['reconciliation'],
            'partial_year_note': 'Original platform flag retained; Jan 1 calendar-day comparison can label a full trading year partial.',
            'attribution': 'Both entry and exit buffers change for C0013 versus C0012; this is scale sensitivity, not single-factor attribution.'
                if subject == 'C0013' else 'One configured rule changes; resulting account paths and subsequent opportunities may both change.'}
        print('DIAGNOSIS', key, diagnosis.status.value, flush=True)
    return result


def main():
    source_hash = sha256(PRIOR_SOURCE.read_bytes()).hexdigest()
    new_keys = tuple(RUN.configurations())
    new_payloads, new_references = load_subset(WORK, EXPERIMENT, new_keys, exact_manifest=True)
    controls, control_references = load_subset(PRIOR_WORK, PRIOR_EXPERIMENT, ('C0000', 'C0001'))
    payloads = {**controls, **new_payloads}
    references = {**control_references, **new_references}
    path_check = PRIOR.verify_hold_path(payloads)
    summary = {key: PRIOR.summarize(value) for key,value in new_payloads.items()}
    # Control summaries are derived from the same retained account definitions,
    # not from new replay or re-registration.
    control_summary = {key: PRIOR.summarize(value) for key,value in controls.items()}
    diagnosis = diagnostics(payloads, references)
    if sha256(PRIOR_SOURCE.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('reused analysis source changed during computation')
    okay = path_check['status'] == 'PASS' and all(d['status'] == 'COMPUTED' for d in diagnosis.values())
    output = {
        'schema': 's017-stage2-ex003-analysis/v1', 'status': 'PASS' if okay else 'FAIL',
        'scope': '2019-01-02 through 2025-12-31 development only; stage two',
        'analysis_source': {'path': PRIOR_SOURCE.relative_to(ROOT).as_posix(), 'sha256': source_hash,
            'reused_functions': ['summarize', 'verify_hold_path', '_validate_run'],
            'module_isolation': 'EX002 and EX003 runners use distinct importlib module identities; main output/publication belongs to EX003'},
        'source_accounts': {key: ref.to_dict() for key,ref in references.items()},
        'control_usage': {'C0000': 'Retained EX002 independent buyhold account for economic path authentication',
                          'C0001': 'Retained EX002 unbuffered trend prototype; no replay or new candidate registration'},
        'semantics': {
            'annual_return': 'year-end equity divided by preceding session equity, initial cash for first year',
            'rolling_return': '252 retained sessions, 21-session step, incomplete trailing windows excluded',
            'excess_return': 'candidate net return minus embedded buy_hold return on the same continuous-account slice',
            'holding': 'positive-quantity bar/session-close observation fraction, not elapsed wall-clock exposure',
            'drawdown': 'slice-opening and full-account inherited peak reported separately; positive magnitudes',
            'independence': 'development comparisons and overlapping windows are not independent validation',
            'economic_acceptance': 'descriptive account comparisons; no automatic research acceptance or stage advancement'},
        'buy_hold_path_verification': path_check,
        'accounts': summary, 'controls': control_summary, 'diagnostics': diagnosis,
    }
    RUN.save(WORK/'others/analysis.json', output)
    if not okay:
        raise RuntimeError('analysis contains failed economic-path verification or account diagnosis')
    print('EX003 ANALYSIS PASS', WORK/'others/analysis.json', flush=True)


if __name__ == '__main__':
    main()
