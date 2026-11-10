"""Complete three 80-point neighborhoods with explicit public TDR checkpoints."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / '.tmp/s019-ex041-accounts'
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ.update(TEMP=str(SCRATCH), TMP=str(SCRATCH), OMP_NUM_THREADS='1',
    OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
sys.path.insert(0, str(WORK.parent / 'EX013_20261110/src'))
from runner import metrics, read_account  # noqa: E402
from data_window import replay_context, HISTORY_START, SOURCE  # noqa: E402
from czsc_trader import research_tools as d  # noqa: E402
from czsc_trader.application import RepositoryContext, load_candidate, publish_evidence  # noqa: E402
from czsc_trader.research_tools.equity_replay import materialize_equity  # noqa: E402
from dataflows import TimeInterval  # noqa: E402
from strategy_manager import CandidateKey, CandidateDerivation, CandidateDerivationKind, CandidateEvidence  # noqa: E402
from strategy_evaluator import (AssessmentCandidate, ParameterAxis, BooleanDomain, CategoricalDomain,  # noqa: E402
    RealDomain, IntegerDomain, ExplicitValues, BoundedLocalStep, RelativeChangeLimit,
    ParameterNeighborhoodProtocol, ParameterNeighborhoodRequest, ParameterNeighborhoodSpace,
    build_parameter_neighborhood_design)

EXP = d.ExperimentRef('S019', WORK.name)
IDS = ('C0367', 'C0355', 'C0264')
FIRST_CHILD = 382
TOTAL = 244
RUN_ID = 'ex041-three-center-selfcheck'


def read(path):
    return json.loads(path.read_bytes())


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def save(path, value):
    temporary = SCRATCH / (path.name + '.pending')
    temporary.write_bytes(encoded(value))
    os.replace(temporary, path)


def save_or_check(path, value):
    normalized = json.loads(encoded(value))
    if path.exists():
        assert read(path) == normalized, f'Existing immutable design differs: {path.name}'
    else:
        save(path, normalized)


def request_for(candidate, label='STANDARD'):
    zone = ZoneInfo('America/New_York')
    window = TimeInterval(datetime(2022, 1, 3, 9, 30, tzinfo=zone), datetime(2026, 10, 30, 16, tzinfo=zone))
    pressure = label == 'STRESS'
    return d.EquityEvaluationRequest(EXP, candidate, window, HISTORY_START, d.EquitySources(SOURCE, SOURCE, SOURCE),
        100000., .002 if pressure else .001,
        benchmark=d.EvaluationBenchmark(d.EquityBuyHold(candidate.definition.execution_spec)),
        window_id='FULL', scenario_id='STRESS' if pressure else 'STANDARD',
        measurement_tier='STRESS' if pressure else 'FORMAL', drawdown_basis='SESSION_CLOSE',
        concentration_basis='MAX_SINGLE')


def construction(center):
    params = json.loads(center.definition.parameters_json)
    axes, explanations = [], []
    active = {'weak_fraction', 'trail_atr', 'participation_threshold', 'quiet_fraction'}
    assert active <= params.keys()
    assert (params['down_days'], params['hold_days'], params['participation_days']) == (1, 5, 3)
    for key, value in sorted(params.items()):
        if type(value) is bool:
            domain, rule, unit = BooleanDomain(), ExplicitValues((value,)), 'fixed_structure'
        elif type(value) is str:
            domain, rule, unit = CategoricalDomain((value,)), ExplicitValues((value,)), 'fixed_structure'
        elif type(value) is int:
            domain = IntegerDomain(1, 65 if key == 'hold_days' else 64)
            rule, unit = BoundedLocalStep(RelativeChangeLimit(.05)), 'trading_sessions'
        else:
            assert key in active
            domain = (RealDomain(0., 1., lower_closed=False) if key in ('weak_fraction', 'quiet_fraction')
                      else RealDomain(0., sys.float_info.max, lower_closed=False))
            rule, unit = BoundedLocalStep(RelativeChangeLimit(.05)), 'ratio'
        axes.append(ParameterAxis(key, value, domain, rule, (key,), unit))
        explanations.append({'parameter': key, 'center': value, 'varies': key in active,
            'reason': 'Continuous business parameter; full center and +/-5% Cartesian neighborhood.' if key in active else
            'Integer minimum one-session change exceeds5%; retained at center.' if type(value) is int else
            'Fixed structural category/boolean.'})
    mapping = {'center_id': center.candidate_id, 'content_hash': center.content_identity.content_sha256,
        'axes': explanations, 'payload_mapping': 'Axis names map directly to complete strategy parameters.'}
    feasibility = {'source_unchanged': True, 'fixed_structure': True,
        'fraction_domains': '0 < weak_fraction,quiet_fraction <= 1',
        'positive_atr_and_participation_threshold': True,
        'integer_domains': '1..64 for input spans;1..65 for held-count horizon',
        'warmup': 'Unchanged registered warmup900/65 covers all fixed spans.'}
    result = build_parameter_neighborhood_design(ParameterNeighborhoodRequest(
        AssessmentCandidate(f'S019-{center.candidate_id}', center.content_identity.content_sha256),
        ParameterNeighborhoodProtocol(max_combinations=1000000),
        ParameterNeighborhoodSpace(tuple(axes), sha256(encoded(mapping)).hexdigest(), sha256(encoded(feasibility)).hexdigest())),
        feasibility=lambda values: True)
    assert result.status.value == 'COMPLETE', result
    assert result.design.point_count == 80
    return result.design, mapping, feasibility


def signature(definition):
    return definition['source_sha256'], json.dumps(json.loads(definition['parameters_json']), sort_keys=True)


def preflight(repo):
    originals = read(WORK / 'protocols/centers.json')
    assert tuple(row['id'] for row in originals) == IDS
    centers = [load_candidate(repo, CandidateKey('S019', cid)) for cid in IDS]
    specs = [construction(center) for center in centers]
    children, jobs, next_id = {}, [], FIRST_CHILD
    for center, original, (design, mapping, feasibility) in zip(centers, originals, specs, strict=True):
        assert json.loads(encoded(center.definition.to_dict())) == original['definition']
        assert center.content_identity.content_sha256 == original['content_hash']
        for suffix, value in (('design', design.to_dict()), ('mapping', mapping), ('feasibility', feasibility)):
            save_or_check(WORK / f'protocols/{center.candidate_id}_{suffix}.json', value)
        child_group = []
        for point in design.points:
            parameters = {v.name: v.value for v in point.values}
            child = replace(center, candidate_id=f'C{next_id:04}', definition=replace(center.definition,
                parameters_json=json.dumps(parameters, sort_keys=True, separators=(',', ':'))))
            next_id += 1
            child_group.append(child)
        children[center.candidate_id] = child_group
    assert next_id == 622
    allocated = {c.candidate_id for group in children.values() for c in group}
    # Candidate IDs are scoped by strategy family. Inspect every earlier S019
    # experiment JSON and the S019 registry, including unregistered proposals.
    pattern = re.compile(r'"(?:candidate_id|id)"\s*:\s*"(C\d{4})"')
    conflicts, checked = [], 0
    scan_roots = (WORK.parent, ROOT / 'research/registrations/S019')
    for directory in scan_roots:
        for path in directory.rglob('*.json'):
            if path.is_relative_to(WORK):
                continue
            checked += 1
            matches = allocated.intersection(pattern.findall(path.read_text(encoding='utf-8')))
            if matches:
                conflicts.append({'file': path.relative_to(ROOT).as_posix(), 'ids': sorted(matches)})
    for cid in sorted(allocated):
        assert not (ROOT / f'research/S019/assets/candidates/{cid}').exists(), f'Candidate already retained: {cid}'
    assert not conflicts, conflicts
    save(WORK / 'others/id_reservation_check.json', {'status': 'PASS', 'namespace': 'S019',
        'first': 'C0382', 'last': 'C0621', 'count': 240, 'checked_prior_json_files': checked})
    # A standard, unbound C0264 result is required as a new center: the old
    # identical implementation's result is explicitly a C0224 parameter point.
    jobs.append(('C0264', 'CENTER', centers[2]))
    for center in centers:
        jobs.append((center.candidate_id, 'STRESS', center))
        jobs.extend((center.candidate_id, f'P{i:03}', c) for i, c in enumerate(children[center.candidate_id]))
    manifest = [{'parent': parent, 'label': label, 'candidate_id': c.candidate_id,
        'content_hash': c.content_identity.content_sha256, 'source_sha256': c.definition.source_sha256,
        'parameters': json.loads(c.definition.parameters_json), 'fee_rate': .002 if label == 'STRESS' else .001}
        for parent, label, c in jobs]
    assert len(manifest) == TOTAL
    save_or_check(WORK / 'protocols/job_manifest.json', manifest)
    historical = []
    previous = read(WORK.parent / 'EX039_20261110/others/account_results.json')['accounts']
    by_signature = {}
    for row in previous.values():
        if row['label'] != 'STRESS':
            by_signature.setdefault(signature(row['definition']), []).append(row)
    for parent, label, child in jobs:
        if not label.startswith('P'):
            continue
        for old in by_signature.get(signature(child.definition.to_dict()), []):
            historical.append({'new_parent': parent, 'new_point': label, 'new_candidate_id': child.candidate_id,
                'old_parent': old['parent'], 'old_candidate_id': old['candidate_id'], 'old_account': old['account_ref'],
                'reuse_status': 'REPLAY_REQUIRED_DIFFERENT_PARENT_PLAN_AND_CHILD_IDENTITY'})
    current_signatures = [signature(c.definition.to_dict()) for group in children.values() for c in group]
    save_or_check(WORK / 'protocols/reuse_review.json', {'historical_exact_parameter_matches': historical,
        'historical_match_count': len(historical), 'within_current_neighborhood_exact_duplicates': len(current_signatures)-len(set(current_signatures)),
        'reused_original_centers': ['C0367', 'C0355'],
        'replayed_original_center': {'id': 'C0264', 'reason': 'Remove old C0224 point lineage by a new standard request; preserve original evidence unchanged.'},
        'public_contract': 'Each new parameter result must retain its declared parent, child identity and plan binding; historical headers are never rewritten.',
        'recovery': 'Public TDR checkpoint CREATE/RESUME and exact published EX041 request references.'})
    run_manifest = {'runner_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'plan_sha256': sha256((WORK / 'protocols/plan.md').read_bytes()).hexdigest(),
        'centers_sha256': sha256((WORK / 'protocols/centers.json').read_bytes()).hexdigest(),
        'jobs_sha256': sha256(encoded(manifest)).hexdigest(),
        'source_hashes': sorted({c.definition.source_sha256 for c in centers}),
        'design_sha256': {cid: sha256((WORK / f'protocols/{cid}_design.json').read_bytes()).hexdigest() for cid in IDS},
        'checkpoint_run_id': RUN_ID, 'expected_strategy_scenarios': TOTAL,
        'parameter_points': 240, 'stress_scenarios': 3, 'standard_center_replays': 1,
        'original_center_reuses': 2, 'expected_benchmark_identities': 2}
    save_or_check(WORK / 'protocols/run_manifest.json', run_manifest)
    print('PREFLIGHT_PASS', [(cid, 80) for cid in IDS], 'jobs', TOTAL,
          'historical_matches', len(historical), flush=True)
    return originals, centers, specs, children, run_manifest


def zero_statistics():
    return {'input_snapshots': 0, 'candidate_runs': 0, 'benchmark_runs': 0, 'account_timings': []}


def center_parity(original_ref, current_ref):
    # Read exact published account closures through the shared authenticated reader.
    old_path, new_path = WORK / 'others/C0264_center_ref.json', WORK / 'others/C0264_CENTER_account.json'
    assert read(old_path) == original_ref and read(new_path) == current_ref
    _, old = read_account(old_path)
    _, new = read_account(new_path)
    a, b = old['runs']['candidate'], new['runs']['candidate']
    assert a['metrics'] == b['metrics']
    economic = ('session', 'time', 'cash', 'equity', 'quantity', 'receivable', 'close',
                'bar_status', 'valuation_price_at', 'valuation_stale', 'execution_blocked')
    for key in ('account_daily', 'account_points'):
        assert [tuple(r[k] for k in economic) for r in a[key]] == [tuple(r[k] for k in economic) for r in b[key]]
    assert [(r['execution_start'], r['target']) for r in a['decisions']] == [(r['execution_start'], r['target']) for r in b['decisions']]
    keys = ('interval_start', 'side', 'quantity', 'price', 'fees')
    assert [tuple(r[k] for k in keys) for r in a['fills']] == [tuple(r[k] for k in keys) for r in b['fills']]
    save_or_check(WORK / 'others/center_parity.json', {'status': 'PASS', 'center': 'C0264',
        'original_account': original_ref, 'standard_unbound_account': current_ref,
        'daily_points': len(a['account_daily']), 'bar_points': len(a['account_points']),
        'decisions': len(a['decisions']), 'fills': len(a['fills']), 'economic_equality': 'EXACT'})


def write_center_accounts(originals, result):
    refs = {row['id']: row['account_ref'] for row in originals}
    refs['C0264'] = result['accounts']['C0264_CENTER']['account_ref']
    center_parity(originals[2]['account_ref'], refs['C0264'])
    save_or_check(WORK / 'others/center_accounts.json', refs)


def write_assessment_inputs(originals, result):
    refs = read(WORK / 'others/center_accounts.json')
    rows = [{'id': row['id'], 'center_account': refs[row['id']],
        'stress_account': result['accounts'][f"{row['id']}_STRESS"]['account_ref'],
        'parameter_plan': read(WORK / f"others/{row['id']}_parameter_plan_ref.json"),
        'parameter_accounts': [result['accounts'][f"{row['id']}_P{i:03}"]['account_ref'] for i in range(80)]}
        for row in originals]
    save_or_check(WORK / 'others/assessment_inputs.json', {
        'source_candidates': read(ROOT / 'research/S019/deliveries/CANDIDATES/6/receipt.json')['reference'],
        'source_mandate': read(ROOT / 'research/S019/deliveries/MANDATE/2/receipt.json')['reference'], 'centers': rows})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    assert not args.recover or args.run
    repo = RepositoryContext.discover(ROOT)
    originals, centers, specs, children, manifest = preflight(repo)
    if not args.run:
        return
    result_path = WORK / 'others/account_results.json'
    assert args.recover or not result_path.exists(), 'Existing results require explicit recovery'
    result = read(result_path) if result_path.exists() else {'status': 'RUNNING', 'accounts': {}, 'batches': [],
        'manifest': manifest, 'new_search_trials': 0, 'reused_center_accounts': 2}
    assert result['manifest'] == manifest
    if result['status'] == 'COMPLETE':
        assert len(result['accounts']) == TOTAL
        write_assessment_inputs(originals, result)
        print('COMPLETE_RESULTS_REUSED', TOTAL, flush=True)
        return
    attempts_path = WORK / 'others/account_attempts.json'
    attempts = read(attempts_path) if attempts_path.exists() else []
    for old in attempts:
        if old['status'] == 'RUNNING':
            old.update(status='INTERRUPTED_WITH_PARTIAL_STATISTICS', statistics_complete=False)
    attempt = {'attempt': len(attempts)+1, 'started_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'RUNNING', 'statistics_complete': True, 'equity_statistics': zero_statistics(),
        'elapsed_seconds': 0., 'completed_at_start': len(result['accounts']), 'error': None}
    attempts.append(attempt)
    save(attempts_path, attempts)
    context = replay_context(repo, centers[0].definition.execution_spec)
    mode = d.CheckpointMode.RESUME if args.recover else d.CheckpointMode.CREATE
    checkpoint = d.ExecutionCheckpointRequest(RUN_ID, mode)
    execution, started, caught = None, perf_counter(), None

    def snapshot(status):
        attempt.update(status=status, elapsed_seconds=perf_counter()-started,
            equity_statistics=asdict(execution.equity_statistics) if execution and execution.equity_statistics is not None else zero_statistics())
        if execution is not None:
            attempt['execution_stats'] = asdict(execution.stats)
        save(attempts_path, attempts)
        result['workload'] = {key: sum(a['equity_statistics'][key] for a in attempts)
                              for key in ('input_snapshots', 'candidate_runs', 'benchmark_runs')}
        result['workload']['account_timings'] = [v for a in attempts for v in a['equity_statistics']['account_timings']]
        result.update(elapsed_seconds=sum(a['elapsed_seconds'] for a in attempts),
            replay_statistics_complete=all(a['statistics_complete'] for a in attempts), attempt_count=len(attempts))
        save(result_path, result)

    try:
        with d.ResearchExecutionSession(context, experiment=EXP, checkpoint=checkpoint,
                on_progress=lambda value: print(value, flush=True)) as execution:
            jobs = []
            for center, (design, mapping, feasibility) in zip(centers, specs, strict=True):
                def material(name, value):
                    return publish_evidence(context, d.MaterialEvidenceWrite(EXP,
                        f'{center.candidate_id}-{name}', encoded(value), 'application/json', 'json'))
                map_ref, feasible_ref = material('mapping', mapping), material('feasibility', feasibility)
                central = context.evaluation.prepare(request_for(center), execution=execution)
                child_group = children[center.candidate_id]
                prepared = tuple(context.evaluation.prepare(request_for(child), execution=execution) for child in child_group)
                plan = d.ParameterEvaluationPlan.create(design, central, prepared, mapping_evidence=map_ref,
                    feasibility_evidence=feasible_ref, dataflows=context.data, execution=execution)
                save_or_check(WORK / f'others/{center.candidate_id}_parameter_plan.json', plan.to_dict())
                plan_ref = material('parameter-plan', plan.to_dict())
                save_or_check(WORK / f'others/{center.candidate_id}_parameter_plan_ref.json', plan_ref.to_dict())
                if center.candidate_id == 'C0264':
                    jobs.insert(0, (center.candidate_id, 'CENTER', central))
                jobs.append((center.candidate_id, 'STRESS', context.evaluation.prepare(request_for(center, 'STRESS'), execution=execution)))
                for index, (child, point, handle) in enumerate(zip(child_group, design.points, prepared, strict=True)):
                    derivation = CandidateDerivation(center.key, center.content_identity.content_sha256,
                        child.key, child.content_identity.content_sha256, CandidateDerivationKind.PARAMETERS,
                        {v.name: v.value for v in point.values}, design.protocol.sha256,
                        CandidateEvidence(plan_ref.resolve(ROOT).relative_to(ROOT).as_posix(), plan_ref.sha256))
                    bound = replace(handle.request, lineage=d.EvaluationLineage(derivation,
                        plan.bind_point(plan_ref, index, repository_root=ROOT)))
                    jobs.append((center.candidate_id, f'P{index:03}', context.evaluation.prepare(bound, execution=execution)))
            assert len(jobs) == TOTAL
            prepared_manifest = [{'key': f'{parent}_{label}', 'request_sha256': sha256(handle.contract_content).hexdigest(),
                'content_hash': handle.candidate.content_identity.content_sha256,
                'benchmark_identity': handle.benchmark_identity.sha256} for parent, label, handle in jobs]
            save_or_check(WORK / 'protocols/prepared_request_manifest.json', prepared_manifest)
            pending = []
            for parent, label, handle in jobs:
                key = f'{parent}_{label}'
                if key in result['accounts']:
                    row = result['accounts'][key]
                    ref = d.EvidenceRef.from_dict(row['account_ref'])
                    raw = ref.resolve(ROOT).read_bytes()
                    assert sha256(raw).hexdigest() == ref.sha256
                    header = json.loads(raw)
                    assert header['request'] == json.loads(handle.contract_content)
                    assert row['request_sha256'] == header['request_hash'] == sha256(handle.contract_content).hexdigest()
                    assert row['content_hash'] == handle.candidate.content_identity.content_sha256
                    save_or_check(WORK / f'others/{key}_account.json', ref.to_dict())
                else:
                    pending.append((parent, label, handle))
            if 'C0264_CENTER' in result['accounts']:
                write_center_accounts(originals, result)
            snapshot('RUNNING')
            print('PLANS_READY', len(pending), 'remaining scenarios', flush=True)
            for offset in range(0, len(pending), 4):
                batch, begun = pending[offset:offset+4], perf_counter()
                outcomes = context.evaluation.evaluate_many(tuple(h for _, _, h in batch), execution=execution)
                snapshot('RUNNING')
                statuses = []
                for (parent, label, handle), outcome in zip(batch, outcomes, strict=True):
                    key = f'{parent}_{label}'
                    statuses.append({'key': key, 'status': outcome.status.value, 'error': str(outcome.error) if outcome.error else None})
                    if outcome.result is None:
                        continue
                    ref = publish_evidence(context, d.EvaluationEvidenceWrite(EXP, key, handle, outcome.result), execution=execution)
                    payload = materialize_equity(outcome.result).payload
                    run, bh = payload['runs']['candidate'], payload['runs']['buy_hold']
                    m, b = metrics(run, bh['metrics']['daily_max_drawdown']), metrics(bh, bh['metrics']['daily_max_drawdown'])
                    assert all(x['observed_through'] <= x['decision_at'] <= x['execution_start'] and 0 <= x['target'] <= 1 for x in run['decisions'])
                    assert all(x['cash'] >= -1e-8 and x['quantity'] >= 0 for x in run['account_points'])
                    assert all(x['quantity'] > 0 and x['quantity'] == int(x['quantity']) for x in run['fills'])
                    gates = {'nar': m['nar'] >= .5, 'calmar': m['calmar'] is not None and m['calmar'] >= 4.5,
                        'relative_dd': (m['drawdown'] < b['drawdown'] if b['drawdown'] > 0 else m['drawdown'] == 0)
                            if label == 'STRESS' else m['drawdown'] <= .9*b['drawdown'],
                        'absolute_dd': m['drawdown'] <= .25}
                    result['accounts'][key] = {'parent': parent, 'label': label, 'candidate_id': handle.candidate.candidate_id,
                        'content_hash': handle.candidate.content_identity.content_sha256,
                        'request_sha256': outcome.result.request_hash, 'parameters': json.loads(handle.candidate.definition.parameters_json),
                        'definition': handle.candidate.definition.to_dict(), 'account_ref': ref.to_dict(),
                        'candidate': m, 'benchmark': b, 'selfcheck_gates': gates, 'selfcheck_pass': all(gates.values()),
                        'chronology_cash_integer_audit': 'PASS', 'role': 'CENTER_REPLAY' if label == 'CENTER' else 'SELF_CHECK'}
                    save_or_check(WORK / f'others/{key}_account.json', ref.to_dict())
                    save(result_path, result)
                    if label == 'CENTER':
                        assert payload['request']['lineage'] is None
                        write_center_accounts(originals, result)
                    print('ACCOUNT', key, round(m['nar'], 6), round(m['drawdown'], 6),
                          round(m['calmar'], 6), all(gates.values()), flush=True)
                result['batches'].append({'attempt': attempt['attempt'], 'statuses': statuses, 'seconds': perf_counter()-begun})
                snapshot('RUNNING')
                assert all(x['status'] == 'SUCCEEDED' for x in statuses), 'Inspect failed or unknown results before explicit recovery'
            assert len(result['accounts']) == TOTAL
            result.update(status='COMPLETE', new_search_trials=0, reused_center_accounts=2, standard_center_replays=1)
    except BaseException as error:
        caught = error
        result.update(status='STOPPED', error=repr(error))
        attempt['error'] = repr(error)
        raise
    finally:
        snapshot('COMPLETE' if caught is None and result['status'] == 'COMPLETE' else 'STOPPED')
    write_assessment_inputs(originals, result)
    print('STAGE4_ACCOUNTS_COMPLETE', len(result['accounts']), result['workload']['candidate_runs'],
          result['workload']['benchmark_runs'], flush=True)


if __name__ == '__main__':
    main()
