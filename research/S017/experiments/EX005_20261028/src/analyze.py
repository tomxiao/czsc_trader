"""EX005 identity-bound initial-risk/profit-protection followup analysis."""
from datetime import date
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys

from czsc_trader.application import diagnose_accounts
from czsc_trader.research_tools import ExperimentRef
from czsc_trader.research_tools.account_diagnosis import AccountDiagnosisRequest
from czsc_trader.research_tools.evaluation import EvaluationWindow


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load analysis dependency: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_module('_s017_ex005_analysis_runner', Path(__file__).with_name('run.py'))
ROOT, WORK, REPOSITORY, EXPERIMENT = RUN.ROOT, RUN.WORK, RUN.REPOSITORY, RUN.EXPERIMENT
PRIOR_WORK = ROOT/'research/S017/experiments/EX004_20261028'
PRIOR_SOURCE = PRIOR_WORK/'src/analyze.py'
# EX004 explicitly loads its own runner and temporarily binds the EX002 runner
# while importing EX002 helpers. It never takes this EX005 runner as its origin.
PRIOR = _load_module('_s017_ex004_for_ex005_helpers', PRIOR_SOURCE)
DEPENDENCY_PATHS = (PRIOR_SOURCE, PRIOR_WORK/'src/run.py', PRIOR.PRIOR_SOURCE, PRIOR.PRIOR_RUNNER_SOURCE)

COMPARISONS = (
    ('C0027', 'C0025', 'Reduce initial loss distance from 3 to 1 entry-day ATR; preserve the 3-ATR trailing rule.'),
    ('C0028', 'C0025', 'Add cost-basis stop floor after a 2-entry-ATR close gain; preserve initial and trailing distances.'),
    ('C0029', 'C0027', 'Add the same profit-protection floor to the 1-ATR initial-risk expression.'),
    ('C0029', 'C0028', 'Reduce initial loss distance from 3 to 1 ATR while keeping the profit-protection floor.'),
)


def diagnostics(payloads, references):
    root = ROOT/'research/S017/assets/runs/EX005_20261028/diagnostics'
    research, result = RUN.context(), {}
    for subject, control, question in COMPARISONS:
        key = subject+'_vs_'+control
        path = root/(key+'.json')
        diagnosis = diagnose_accounts(REPOSITORY, AccountDiagnosisRequest(
            PRIOR.account_ref(references[control], payloads[control]),
            PRIOR.account_ref(references[subject], payloads[subject]),
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
            'baseline': control, 'alternative': subject, 'question': question,
            'raw_path': path.relative_to(ROOT).as_posix(), 'evidence': evidence.to_dict(),
            'pnl_summary': summaries, 'cycle_path_rows': len(diagnosis.path_comparison),
            'daily_path_rows': len(diagnosis.daily_paths), 'reconciliation': raw['reconciliation'],
            'partial_year_note': 'Original platform flag retained; Jan 1 comparison may label a full trading year partial.',
            'attribution': 'One configured rule changes; subsequent positions and opportunities may also change. Accounting attribution is not a causal market explanation.'}
        print('DIAGNOSIS', key, diagnosis.status.value, flush=True)
    return result


def main():
    dependency_hashes = {path:sha256(path.read_bytes()).hexdigest() for path in DEPENDENCY_PATHS}
    new_keys = tuple(RUN.configurations())
    if set(new_keys) != {'C0027', 'C0028', 'C0029'}:
        raise ValueError('EX005 fixed design must contain exactly its three declared configurations')
    if set(RUN.read(WORK/'others/accounts.json')) != set(new_keys):
        raise ValueError('EX005 account manifest must exactly cover its three new configurations')
    new_payloads, new_refs = PRIOR.load_subset(WORK, EXPERIMENT, new_keys)
    controls, control_refs = {}, {}
    for experiment_id, keys in (
        ('EX002_20261028', ('C0000',)),
        ('EX003_20261028', ('C0013',)),
        ('EX004_20261028', ('C0022', 'C0025', 'C0026')),
    ):
        experiment = ExperimentRef('S017', experiment_id)
        values, refs = PRIOR.load_subset(experiment.resolve(ROOT), experiment, keys)
        if controls.keys() & values.keys():
            raise ValueError('retained control ID collision')
        controls.update(values)
        control_refs.update(refs)
    payloads, references = {**controls, **new_payloads}, {**control_refs, **new_refs}
    contract_check = PRIOR.verify_contracts(payloads)
    path_check = PRIOR.PRIOR.verify_hold_path(payloads)
    summary = {key:PRIOR.PRIOR.summarize(value) for key,value in new_payloads.items()}
    control_summary = {key:PRIOR.PRIOR.summarize(value) for key,value in controls.items()}
    giveback = {key:PRIOR.cycle_giveback(payload) for key,payload in payloads.items()}
    diagnosis = diagnostics(payloads, references)
    if any(sha256(path.read_bytes()).hexdigest() != digest for path,digest in dependency_hashes.items()):
        raise RuntimeError('reused analysis dependency changed during EX005 computation')
    okay = (contract_check['status'] == path_check['status'] == 'PASS'
            and all(value['status'] == 'PASS' for value in giveback.values())
            and len(diagnosis) == 4
            and all(value['status'] == 'COMPUTED' for value in diagnosis.values()))
    output = {
        'schema':'s017-stage2-ex005-analysis/v1', 'status':'PASS' if okay else 'FAIL',
        'scope':'2019-01-02 through 2025-12-31 development only; stage-two bounded followup',
        'analysis_dependencies':[{'path':path.relative_to(ROOT).as_posix(), 'sha256':digest}
                                 for path,digest in dependency_hashes.items()],
        'reused_functions':{
            'EX004':['load_subset', 'verify_contracts', 'cycle_giveback', 'account_ref'],
            'EX002':['summarize', 'verify_hold_path', '_validate_run'],
        },
        'module_isolation':'EX005, EX004 and EX002 runners have distinct importlib identities; EX004 helpers retain their own bindings; new diagnostics/output belong to EX005.',
        'source_accounts':{key:ref.to_dict() for key,ref in references.items()},
        'control_usage':{
            'C0000':'EX002 executable buyhold; no new replay or registration',
            'C0013':'EX003 prior highest-return timing expression; selection used known development results',
            'C0022':'EX004 65-bar breakout with daily-ATR trailing stop; retained overall comparison',
            'C0025':'EX004 260-bar breakout with 3-ATR initial/trailing distance; direct followup control',
            'C0026':'EX004 initial-stop-only ablation; retained reference for trailing protection',
        },
        'semantics':{
            'annual_return':'continuous year-end equity divided by prior session equity; initial cash only in first year',
            'rolling_return':'252 retained sessions at 21-session steps, excluding incomplete windows',
            'excess_return':'candidate minus embedded buyhold on identical continuous-account slices',
            'holding':'positive-quantity observation share, not elapsed wall-clock exposure',
            'drawdown':'slice-opening and inherited full-account peak reported separately as positive magnitudes',
            'independence':'same development pool and result-informed followup; overlapping windows are not independent',
            'profit_protection':'cost basis includes entry fee; crossing or exiting near it does not guarantee nonnegative realized return',
            'economic_acceptance':'descriptive comparison only; no automatic acceptance or stage advancement',
        },
        'contract_comparability':contract_check, 'buy_hold_path_verification':path_check,
        'accounts':summary, 'controls':control_summary, 'cycle_giveback':giveback, 'diagnostics':diagnosis,
    }
    RUN.save(WORK/'others/analysis.json', output)
    if not okay:
        raise RuntimeError('EX005 analysis contains failed account/contract/cycle verification or diagnosis')
    print('EX005 ANALYSIS PASS', WORK/'others/analysis.json', flush=True)


if __name__ == '__main__':
    main()
