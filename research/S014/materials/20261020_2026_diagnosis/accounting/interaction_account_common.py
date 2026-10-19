"""Identity/unchanged-prefix checks derived from frozen EX046 independent audit."""
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / 'research/S014/materials/20261020_preentry_diagnosis/accounting'))
import audit_pause_accounts as Q  # noqa: E402

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EX = ROOT / 'research/S014/experiments/EX048_20261020'
A, H = Q.A, Q.H
PAUSE_FIELDS = Q.PAUSE_FIELDS
FIXED = [{'pause_profile': value} for value in ['AFTER_NET_LOSS_SKIP1', 'BASE']]
SOURCE_SHA = '5a4347527aad29cb647d9c44a26cf1b970dda471af9d1419f817b39e4476a66b'
DERIVED_FROM_SHA256 = '9950b9ae7c04142632ebe39cfa5aab954326762fc3966b06bca6e7605dd72f40'
assert sha256(Path(Q.__file__).read_bytes()).hexdigest() == DERIVED_FROM_SHA256


def run_lock(record):
    preflight = A.published(record['preflight_ref'])
    lock_sha = preflight['source_lock']
    reviewed = [A.read(p) for p in OUT.glob('interaction_public_lock_review*.json')]
    matching = [r for r in reviewed if r['status'] == 'PASS' and r['source_lock_ref']['sha256'] == lock_sha]
    A.check('actual per-record dispatch lock independently reviewed', len(matching) == 1)
    ref = matching[0]['source_lock_ref']
    return A.published(ref), ref


def identity(record, account, frozen, prior):
    source_review = A.read(OUT / 'interaction_source_review.json')
    runner_review = A.read(OUT / 'interaction_runner_pre_review.json')
    A.check('independent source/runner PASS', source_review['status'] == runner_review['status'] == 'PASS')
    A.check('reviewed source identity', source_review['source_sha256'] == runner_review['source_sha256'] == SOURCE_SHA)
    lock, lock_ref = run_lock(record)
    locked = next(r for r in lock['runs'] if r['index'] == record['index'])
    for key in ['mode', 'parameters', 'candidate', 'runtime_sha256', 'payload_sha256']:
        A.check('locked immutable ' + key, record[key] == locked[key])
    A.check('fixed canonical parameters', record['parameters'] == FIXED[record['index']] and set(record['parameters']) == {'pause_profile'})
    payload, binding = A.published(record['published_payload_ref']), A.published(record['binding_ref'])
    A.public_bytes(record['published_source_ref'])
    A.check('published source exact', record['published_source_ref']['sha256'] == SOURCE_SHA)
    A.check('implementation closure', record['runtime_implementation_sha256'] == lock['runtime_implementation_sha256'] == payload['runtime']['source_sha256'])
    A.check('payload exact binding', record['payload_sha256'] == record['published_payload_ref']['sha256'] and payload == binding['payload'])
    A.check('payload parameters/candidate', payload['parameters'] == record['parameters'] and binding['candidate'] == record['candidate'])
    req = account['request_identity']
    A.check('new experiment', req['experiment_id'] == 'EX048_20261020')
    for key in ['asset_type', 'benchmark', 'costs', 'data_cutoff', 'execution_mode', 'frequency_window_days', 'initial_cash', 'market_rules', 'metric_semantics_version', 'price_basis', 'pricing', 'symbol', 'windows']:
        A.check('original unchanged contract ' + key, req[key] == frozen['request_identity'][key])
    A.check('request and runtime bindings', req['content_sha256'] == record['request_content_sha256'] and account['runtime_binding_hash'] == req['runtime_binding_hash'] == record['runtime_binding_hash'])
    A.check('actual candidate', account['runs'][0]['candidate_id'] == record['candidate'].split('-')[-1])
    A.check('causal plan binding', req['input_bindings'] == binding['input_bindings'])
    previous = A.published(prior['binding_ref'])
    for key in ['execution_requests', 'execution_prepared', 'execution_identities', 'execution_fingerprint']:
        A.check('existing prepared asset identical ' + key, binding[key] == previous[key])
    A.check('actual data fingerprint', req['data_identity'] == binding['execution_fingerprint'] == frozen['request_identity']['data_identity'])
    plan, oldplan = req['input_bindings']['full']['plan'], frozen['request_identity']['input_bindings']['full']['plan']
    A.check('plan schema unchanged', plan.keys() == oldplan.keys())
    for key in plan:
        if key != 'strategy':
            A.check('original causal clock exact ' + key, plan[key] == oldplan[key])
    strategy = plan['strategy']
    A.check('new runtime identity', strategy['reference_id'] == record['candidate'] and strategy['runtime_sha256'] == record['runtime_sha256'] and strategy['release_hash'] == account['strategy_identity'] == req['strategy_identity'] and account['strategy_identity'] != frozen['strategy_identity'])
    return binding, lock_ref


def divergence(account, frozen, index):
    old, new = frozen['runs'][0]['ledgers'], account['runs'][0]['ledgers']
    source_control = account if index == 0 else A.published(A.read(EX / 'others/accounts/run-000.json')['evidence'])
    control_rows = source_control['runs'][0]['ledgers']['decisions']['data']
    feedback = [A.day(r['signal_date']) for r in new['decisions']['data'] if r['completed_net_known'] or r['pause_armed_before_candidate'] or r['pause_armed']]
    feedback_difference = [A.day(r['signal_date']) for c, r in zip(control_rows, new['decisions']['data'], strict=True) if any(c[k] != r[k] for k in PAUSE_FIELDS if k not in {'pause_loss_profile', 'pause_profit_profile'})]
    armed_dates = [A.day(r['signal_date']) for r in new['decisions']['data'] if r['pause_armed_before_candidate'] or r['pause_armed']]
    state = [A.day(r['signal_date']) for c, r in zip(old['decisions']['data'], new['decisions']['data'], strict=True) if any(r[k] != v for k, v in c.items() if k not in A.ID_KEYS | {'pause_loss_profile', 'pause_profit_profile'})]
    target = [A.day(r['signal_date']) for c, r in zip(old['decisions']['data'], new['decisions']['data'], strict=True) if c['target_position'] != r['target_position']]
    funded = [A.day(r['date']) for c, r in zip(old['account_daily']['data'], new['account_daily']['data'], strict=True) if any(c[k] != r[k] for k in ['cash', 'cash_before', 'quantity', 'quantity_before', 'equity'])]
    if not state:
        A.noop_equivalence(frozen, account)
    else:
        D = state[0]
        before = max(A.day(r['signal_date']) for r in new['decisions']['data'] if A.day(r['signal_date']) < D)
        for name, key, cutoff in [('decisions', 'signal_date', before), ('orders', 'signal_date', before), ('fills', 'fill_time', D), ('account_daily', 'date', D)]:
            left, right = old[name]['data'], new[name]['data']
            if name == 'decisions':
                left = [{k: v for k, v in r.items() if k not in {'pause_loss_profile', 'pause_profit_profile'}} for r in left]
                right = [{k: v for k, v in r.items() if k not in {'pause_loss_profile', 'pause_profit_profile'}} for r in right]
            A.economic_rows(left, right, 'exact original funded prefix ' + name, cutoff, key)
    return {'first_feedback_state_D': feedback[0] if feedback else None, 'first_original_state_divergence_D': state[0] if state else None,
            'first_target_divergence_D': target[0] if target else None, 'first_funded_state_E': funded[0] if funded else None,
            'first_armed_D': armed_dates[0] if armed_dates else None,
            'first_feedback_difference_vs_source_control_D': feedback_difference[0] if feedback_difference else None,
            'feedback_definition': 'First actual completion enters new known memory, including BASE; original state and wealth may remain exact.',
            'feedback_constant_profile_flags_excluded': True, 'constant_pause_profile_certification_excluded_from_mutable_state': ['pause_loss_profile', 'pause_profit_profile'], 'old_columns_exact_until_first_original_state_D': True}
