"""Audit retained EX054 contracts and observations without running any account."""
from hashlib import sha256
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
EX = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def evidence_bytes(reference):
    path = ROOT / 'research/S014/assets/evidence' / reference['experiment']['experiment_id'] / reference['evidence_id']
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != reference['sha256']:
        raise ValueError('Published evidence byte hash differs')
    return raw


def main():
    planref = read(EX / 'protocols/parameter_plan_ref.json')
    plan = json.loads(evidence_bytes(planref))
    protocol = plan['design']['protocol']
    assert (protocol['radius'], protocol['point_count'], protocol['seed'],
            protocol['random_generator'], protocol['integer_rounding'], protocol['quantile_method']) == (
                .05, 32, 13, 'PCG64', 'HALF_EVEN', 'LINEAR')
    assert len(plan['children']) == 32
    for name in ('mapping_evidence', 'feasibility_evidence'):
        evidence_bytes(plan[name])
    refs = [read(EX / 'others/center_control.json')['account']]
    failed = []
    for index in range(32):
        attempts = [read(p) for p in sorted((EX / 'others').glob(f'point_{index:02}*.json'))]
        successes = [x for x in attempts if x['status'] == 'SUCCEEDED']
        assert len(successes) == 1
        refs.append(successes[0]['account'])
        failed.extend(x for x in attempts if x['status'] != 'SUCCEEDED')
    refs.append(read(EX / 'others/stress.json')['account'])
    checks = []
    for index, reference in enumerate(refs):
        document = json.loads(evidence_bytes(reference))
        request = document['request_identity']
        run = document['runs'][0]
        observed = run['ledgers']['decisions']['data']
        account = run['ledgers']['account_daily']['data']
        mismatches = []
        for signal, funded in zip(observed, account, strict=True):
            assert signal['signal_date'][:10] == funded['signal_date'][:10]
            assert signal['valid_session'][:10] == funded['date'][:10]
            if bool(signal['held_at_close']) != bool(funded['quantity_before'] > 0):
                mismatches.append(signal['signal_date'][:10])
        row = {'candidate': request['strategy_reference'], 'scenario': run['scenario_id'],
               'account_sha256': reference['sha256'], 'dates_aligned': True,
               'signal_rows': len(observed), 'funded_rows': len(account),
               'shadow_holding_mismatch_count': len(mismatches), 'mismatch_signal_dates': mismatches}
        if 1 <= index <= 32:
            point = index - 1
            assert request['parameter_binding']['point']['point_index'] == point
            assert request['parameter_binding']['plan']['sha256'] == planref['sha256']
            assert request['content_sha256'] == plan['children'][point]['candidate']['content_sha256']
            assert request['lineage']['parent_content_sha256'] == plan['center']['candidate']['content_sha256']
            parent = request['lineage']['evidence']
            parent_path = (ROOT / 'research/S014' / parent['path']).resolve()
            assert parent_path.is_relative_to((ROOT / 'research/S014').resolve())
            assert sha256(parent_path.read_bytes()).hexdigest() == parent['sha256'] == refs[0]['sha256']
            row.update(point_index=point, point_and_plan_identity='PASS',
                       actual_parent_content_identity='PASS',
                       lineage_evidence_root='research/S014',
                       lineage_parent_account_byte_hash='PASS')
        checks.append(row)
    assert len(checks) == 34 and all(x['shadow_holding_mismatch_count'] == 0 for x in checks)
    coordinates = plan['design']['space']['coordinates']
    distances = [math.sqrt(sum(((value - coordinate['center']) /
                              (coordinate['upper'] - coordinate['lower'])) ** 2
                             for value, coordinate in zip(point['coordinates'], coordinates, strict=True)))
                 for point in plan['design']['points']]
    assert all(abs(value - .05) <= protocol['distance_tolerance'] for value in distances)
    method = (EX / 'protocols/method.md').read_bytes()
    dispatch = read(EX / 'protocols/center_dispatch.json')
    family_inventory = read(EX / 'others/family_inventory.json')
    assert (family_inventory['unique_funded_paths'], family_inventory['raw_trial_count']) == (157, 178)
    result = {
        'status': 'PASS_READONLY_RETAINED_CONTRACT_AUDIT',
        'scope': '34 retained published account files; no new strategy/account replay, supplier calls, registration or delivery publication.',
        'new_funded_accounts': 0, 'new_market_requests': 0,
        'validation_limit': 'Byte hashes, declared contract identities and saved observation alignment checked; this script does not substitute for TDR account authentication or FULL delivery validation.',
        'plan_sha256': planref['sha256'], 'parameter_points': 32,
        'design_protocol': protocol, 'actual_distance_min': min(distances),
        'actual_distance_max': max(distances),
        'retained_failed_attempts': failed,
        'holding_timing': 'decisions.held_at_close is state after signal-day fills; account_daily.quantity_before is the position immediately before the next execution session. Both are matched by signal_date and valid_session/date.',
        'checks': checks,
        'method_review': {
            'status': 'DECLARATIONS_PRESENT_WITH_EXPLICIT_SEALING_BOUNDARY',
            'method_sha256': sha256(method).hexdigest(),
            'interval': 'Paired stationary block bootstrap, 2000 repetitions, mean block 20 sessions, seed 13, SE 95% interval; all seen history, not future success probability.',
            'time': '252-session rolling window, step 21, LINEAR Q10, at least two windows; no account reruns.',
            'ranking': 'Original yearly economic targets and full-sample frequency retained; RAW Pareto and complete evidence. Ratio bins 0.0001/frequency 0.01; separate coarse 0.001/0.1 sensitivity, one center only.',
            'sealing': 'The parameter plan, complete payload identities, mapping and feasibility are published prospective evidence. method.md contains local predeclared statistical/ranking choices; method.md and complete_stage4.py are absent from the center-dispatch source-publication list. Their later publication must not be described as a center-dispatch prospective public seal.',
            'center_dispatch_published_sources': sorted(dispatch['sources']),
            'cost_stress': 'External fee 0.001 to 0.002, fixed internal simulated-feedback fee 0.001. All holdings aligned, so no observed holding-state divergence invalidates this static-policy cost scenario; this does not validate actual-fill-feedback adaptation.',
            'family': '157 distinct recovered funded paths and 178 conservatively counted recovered research attempts; reused controls/technical copies collapsed, all history seen, unpublished/missing search not claimed recovered. PBO/DSR are descriptive diagnostics, not complete removal of adaptive selection bias.',
            'remaining_required_checks': ['SE assessment/comparison actual outputs', 'formal FULL delivery validation', 'final report claims versus actual results'],
        },
    }
    output = EX / 'others/independent_contract_audit.json'
    if output.exists():
        assert read(output) == result
    else:
        with output.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
    print(json.dumps({'status': result['status'], 'accounts': len(checks),
                      'points': 32, 'shadow_holding_mismatches': 0, 'output': output.relative_to(ROOT).as_posix()}))


if __name__ == '__main__':
    main()
