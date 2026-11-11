"""S019 contract migration controls. No formal stage-four publication or batch run."""
import argparse
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
import json
from math import ceil
import os
from pathlib import Path
import re
import shutil
from time import perf_counter
from uuid import uuid4

import run_accounts as previous
from czsc_trader.research_tools.parameter_evaluation import equity_parameter_contract
from strategy_runtime import (EquityStrategyDefinition, MarketFeature, MarketWindow,
                              StrategyPerformanceBudget, equity_source_hash)


ROOT, core = previous.ROOT, previous.core
WORK = Path(__file__).resolve().parents[1]
SOURCE = WORK / 'src/v4_bounded'
SOURCE_HASH = equity_source_hash(SOURCE, ('strategy.py',))
MANIFEST = WORK / 'others/v4_migration/manifest.json'
EXPERIMENT = core.d.ExperimentRef('S019', WORK.name)
DAILY = MarketWindow('mu_daily', 65)
FEATURES = (
    MarketFeature('daily_days', 'strategy:_daily_days', (DAILY,), max_values=65),
    MarketFeature('daily_atr', 'strategy:_daily_atr', (DAILY,)),
    MarketFeature('entry_daily', 'strategy:_entry_daily', (DAILY, MarketWindow('soxx_daily', 65)),
                  ('down_days', 'participation_days'), max_values=6),
    MarketFeature('opening_volume', 'strategy:_opening_volume', (MarketWindow(None, 400),),
                  ('participation_days',), session_date=True),
)


def read(path):
    return json.loads(path.read_bytes())


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False).encode('utf-8')


def digest(raw):
    return sha256(raw).hexdigest()


def migrated_definition(original, parameters):
    if parameters['participation_days'] != 3:
        raise ValueError('this fixed-window migration is scoped to the declared three-day participation')
    definition = EquityStrategyDefinition.from_dict(original['definition'])
    if definition.content_identity.content_sha256 != original['content_hash'] or definition.source_files != ('strategy.py',):
        raise ValueError('original strategy definition changed')
    return replace(definition, source_sha256=SOURCE_HASH, parameters_json=canonical(parameters).decode(),
                   market_features=FEATURES)


def new_candidate(original, new_id, parameters):
    return core.EquityStrategyCandidate('S019', new_id, migrated_definition(original, parameters), SOURCE)


def published_neighbors():
    return {path.name.removesuffix('_account.json'): read(path) for path in (WORK / 'others').glob('*_P*_account.json')
            if re.fullmatch(r'C\d{4}_P\d{3}_account.json', path.name)}


def build_manifest(scratch):
    centers = read(WORK / 'protocols/centers.json')
    jobs = read(WORK / 'protocols/job_manifest.json')
    published = published_neighbors()
    if len(jobs) != 1698 or len(published) != 183:
        raise ValueError('stage-four pause inventory differs from the approved migration scope')
    if MANIFEST.exists():
        start = read(MANIFEST)['first_new_id']
    else:
        observed = previous.used_ids(exclude=WORK) | {row['candidate_id'] for row in jobs}
        start = max(int(cid[1:]) for cid in observed) + 1
    all_new = tuple(f'C{i:04d}' for i in range(start, start + 2 * len(centers) + len(jobs)))
    if len(all_new[-1]) != 5:
        raise ValueError('candidate identity namespace exhausted')
    center_by_id = {row['id']: row for row in centers}
    migrated_centers, migrated_jobs = [], []
    definitions = {}
    for old, new_id, stress_id in zip(centers, all_new[:len(centers)], all_new[-len(centers):], strict=True):
        candidate = new_candidate(old, new_id, json.loads(old['definition']['parameters_json']))
        definitions[old['id']] = candidate.definition
        migrated_centers.append({'original_id': old['id'], 'new_id': new_id,
            'stress_control_id': stress_id,
            'original_content_sha256': old['content_hash'],
            'new_content_sha256': candidate.content_identity.content_sha256,
            'definition': candidate.definition.to_dict()})
    for old, new_id in zip(jobs, all_new[len(centers):-len(centers)], strict=True):
        if old['parameters']['participation_days'] != 3:
            raise ValueError('neighborhood exceeds declared migration window')
        definition = replace(definitions[old['parent']], parameters_json=canonical(old['parameters']).decode())
        key = old['parent'] + '_' + old['label']
        migrated_jobs.append({'point': key, 'original_id': old['candidate_id'], 'new_id': new_id,
            'original_content_sha256': old['content_hash'], 'new_content_sha256': definition.content_identity.content_sha256,
            'parameters': old['parameters'], 'old_evidence': published.get(key)})
    expected = {'C0966': 59, 'C1010': 728, 'C0909': 728}
    pending = Counter(row['point'].split('_')[0] for row in migrated_jobs if row['old_evidence'] is None)
    if pending != expected:
        raise ValueError('remaining point counts differ from the paused execution')
    manifest = {'kind': 'S019_V4_MIGRATION_PLAN', 'status': 'STAGED', 'first_new_id': start,
        'original_jobs_sha256': digest((WORK / 'protocols/job_manifest.json').read_bytes()),
        'migration_source_sha256': SOURCE_HASH,
        'source': SOURCE.relative_to(ROOT).as_posix(), 'original_pending_by_center': expected,
        'centers': migrated_centers, 'points': migrated_jobs}
    MANIFEST.parent.mkdir(exist_ok=True)
    core.immutable(MANIFEST, manifest, scratch)
    return center_by_id, manifest


def control_cases(centers, manifest):
    cases = []
    for migrated in manifest['centers']:
        old = centers[migrated['original_id']]
        for stress, name in ((False, 'center_account'), (True, 'stress_account')):
            new_id = migrated['stress_control_id'] if stress else migrated['new_id']
            candidate = new_candidate(old, new_id, json.loads(old['definition']['parameters_json']))
            cases.append((f"{old['id']}_{'STRESS' if stress else 'CENTER'}", candidate, stress, old[name]))
    for point in ('C0966_P000', 'C0966_P182'):
        row, = (item for item in manifest['points'] if item['point'] == point)
        cases.append((point, new_candidate(centers['C0966'], row['new_id'], row['parameters']), False, row['old_evidence']))
    return cases


def normalized_account(content):
    account = json.loads(content)
    owner = account['owner']
    kind = owner['kind']
    if kind == 'CANDIDATE':
        key = owner['candidate']
        fingerprint = owner['content_sha256']
        owner_id = f"candidate:{key['strategy_id']}:{key['candidate_id']}:{fingerprint}"
    elif kind == 'BENCHMARK':
        fingerprint = owner['run_sha256']
        owner_id = f'benchmark:{fingerprint}'
    else:
        raise ValueError('unexpected account owner')
    run = account['run']
    decision_ids = {row['decision_id']: f'decision-{i}' for i, row in enumerate(run['decisions'])}
    if len(decision_ids) != len(run['decisions']):
        raise ValueError('decision identity is duplicated')

    def convert(value):
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, str):
            head, sep, rest = value.partition(':')
            if head in decision_ids:
                return decision_ids[head] + sep + rest
            if value == fingerprint:
                return 'implementation-identity'
            if value == owner_id:
                return 'account-owner'
        return value

    return {'normalized_sha256': digest(canonical({**account, 'owner': {'kind': kind}, 'run': convert(run)})),
            'input_sha256': account['input_sha256'], 'decisions': len(run['decisions']),
            'orders': len(run['orders']), 'fills': len(run['fills']), 'trades': len(run['trades']),
            'metrics': run['metrics']}


def published_header(pointer):
    ref = core.d.EvidenceRef.from_dict(pointer)
    path = ref.resolve(ROOT)
    raw = path.read_bytes()
    if digest(raw) != ref.sha256:
        raise ValueError('published account header does not match its reference')
    return path, ref.sha256, json.loads(raw)


def old_account(path, header, key, cache):
    item = header[key]
    if item['sha256'] not in cache:
        content = (path.parent / (item['sha256'] + '.json')).read_bytes()
        if digest(content) != item['sha256']:
            raise ValueError('published account artifact does not match its reference')
        cache[item['sha256']] = normalized_account(content)
    return item['sha256'], cache[item['sha256']]


def prepare_isolation(scratch, spec):
    isolated = scratch / ('sample-' + uuid4().hex[:8])
    isolated.mkdir()
    shutil.copyfile(ROOT / 'pyproject.toml', isolated / 'pyproject.toml')
    (isolated / 'src/czsc_trader').mkdir(parents=True)
    shutil.copytree(ROOT / 'research/registrations/S019', isolated / 'research/registrations/S019')
    experiment = isolated / WORK.relative_to(ROOT)
    experiment.mkdir(parents=True)
    shutil.copyfile(WORK / 'experiment.json', experiment / 'experiment.json')
    repository = core.RepositoryContext.discover(isolated, explicit_root=isolated)
    base = core.replay_context(repository, spec)
    context = replace(base, evaluation=core.EvaluationAccess(dataflows=base.data,
        strategy_id=base.strategy_id, execution_spec=base.execution_spec))
    if not isolated.is_relative_to(ROOT / '.tmp') or context.repository.root != isolated or context.data.binding.base_dir != isolated:
        raise ValueError('calibration must run in the isolated .tmp research space')
    return context


def run(limit):
    scratch = ROOT / '.tmp/s019-v4-migration'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ.update(TMP=str(scratch), TEMP=str(scratch), PYTHONDONTWRITEBYTECODE='1')
    centers, manifest = build_manifest(scratch)
    cases = control_cases(centers, manifest)
    report_path = MANIFEST.parent / ('profile.json' if limit is None else 'budget_validation.json')
    if report_path.exists():
        raise FileExistsError(f'preserve existing validation: {report_path}')
    context = prepare_isolation(scratch, cases[0][1].definition.execution_spec)
    report = {'kind': 'S019_V4_MIGRATION_CONTROL', 'budget': limit, 'cases': [],
              'migration_source_sha256': SOURCE_HASH, 'manifest_sha256': digest(MANIFEST.read_bytes()),
              'normalized_fields': ['account owner identity', 'implementation identity',
                                    'decision IDs in time order and their dependent references']}
    baseline_path = scratch / 'preliminary/profile.json'
    if limit is not None and baseline_path.is_file():
        baseline = read(baseline_path)
        worst = max(case['cpu_per_1000_calls'] for case in baseline['cases'])
        calibrated = ceil(2 * worst / .05) / 20
        if limit != calibrated:
            raise ValueError(f'budget differs from rounded twofold calibration: {calibrated}')
        report['calibration'] = {'preliminary_profile_sha256': digest(baseline_path.read_bytes()),
            'preliminary_source_sha256': read(baseline_path.with_name('manifest.json'))['migration_source_sha256'],
            'source_difference': 'removed one unused local assignment before final acceptance',
            'decision_count_per_account': 15702, 'preliminary_evaluate_seconds': baseline['evaluate_seconds'],
            'preliminary_profiles': {case['case']: case['strategy_profile'] for case in baseline['cases']},
            'preliminary_max_cpu_per_1000_calls': worst, 'margin_multiplier': 2, 'round_up_increment': .05}
    with core.d.ResearchExecutionSession(context, experiment=EXPERIMENT,
            performance_budget=StrategyPerformanceBudget(max_seconds_per_1000_calls=limit)) as execution:
        handles = tuple(context.evaluation.prepare(previous.request_for(EXPERIMENT, candidate, stress), execution=execution)
                        for _, candidate, stress, _ in cases)
        started = perf_counter()
        outcomes = context.evaluation.evaluate_many(handles, execution=execution)
        report['evaluate_seconds'] = perf_counter() - started
        report['stats'] = asdict(execution.stats)
        stats = execution.equity_statistics
        report['runs'] = {'candidates': stats.candidate_runs, 'benchmarks': stats.benchmark_runs}
        if report['runs'] != {'candidates': 8, 'benchmarks': 2} or len(execution.stats.worker_bindings) != 8:
            raise ValueError('validation did not exercise the planned account and worker load')
        profiles = {item.owner: item for item in stats.account_timings if item.kind == 'CANDIDATE'}
        cache = {}
        for (name, candidate, _, pointer), outcome in zip(cases, outcomes, strict=True):
            if outcome.result is None:
                raise ValueError(f'{name}: {outcome.error}')
            artifacts = {item.sha256: item for item in outcome.result.artifacts}
            new_hash = outcome.result.payload['candidate_ref']['sha256']
            owner = f'candidate:S019:{candidate.candidate_id}:{candidate.implementation_hash}'
            timing = profiles[owner].strategy_performance
            path, header_hash, old_header = published_header(pointer)
            old_context = equity_parameter_contract(old_header['request'])['nonparameter_context_sha256']
            new_context = equity_parameter_contract(outcome.result.payload['request'])['nonparameter_context_sha256']
            if timing.calls != 15702 or old_context == new_context:
                raise ValueError(f'{name}: expected the full workload and distinct plan contexts')
            matches = {}
            for key in ('candidate_ref', 'benchmark_ref'):
                old_hash, old = old_account(path, old_header, key, cache)
                new = outcome.result.payload[key]['sha256']
                if new not in cache:
                    cache[new] = normalized_account(artifacts[new].content)
                if old != cache[new]:
                    raise ValueError(f'{name} {key} parity differs: {old} != {cache[new]}')
                matches[key] = {'old_sha256': old_hash, 'new_sha256': new, **old}
            report['cases'].append({'case': name, 'new_id': candidate.candidate_id, 'header_sha256': header_hash,
                'candidate_sha256': new_hash, 'equality': matches,
                'old_plan_context_sha256': old_context, 'new_plan_context_sha256': new_context,
                'strategy_profile': asdict(timing), 'cpu_per_1000_calls': timing.strategy_cpu_seconds * 1000 / timing.calls})
            print(name, 'EQUAL', report['cases'][-1]['cpu_per_1000_calls'], flush=True)
    report['status'] = 'PASS'
    core.immutable(report_path, report, scratch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=float)
    run(parser.parse_args().limit)
