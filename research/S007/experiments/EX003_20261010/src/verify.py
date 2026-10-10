"""Focused source, relational-ledger and immutable-input verification."""
from dataclasses import fields
import pandas as pd
from strategy_runtime import StrategyCandidate
from common import ROOT, FROZEN_SOURCE, SOURCE, PROTOCOLS, RUNS
from common import payload, candidate, context, read, write, fingerprint, cache_read, material


def ids(tables):
    registries, normalized = {}, {}
    for name, frame in tables.items():
        rows = []
        for record in frame.to_dict('records'):
            row = {}
            for field in ('decision_id', 'order_id', 'fill_id', 'cycle_id'):
                if field not in record or pd.isna(record[field]):
                    continue
                registry = registries.setdefault(field, {})
                value = record[field]
                registry.setdefault(value, len(registry))
                row[field] = registry[value]
            rows.append(row)
        normalized[name] = rows
    return normalized


def main():
    original_payload = read(ROOT/'strategies/S007/versions/v1.json')['strategy_payload']
    original = StrategyCandidate('S007', 'C9000', original_payload, source_root=FROZEN_SOURCE)
    runtime = context(1).runtime
    before, after = runtime.describe(original), runtime.describe(candidate())
    differences = [x.name for x in fields(before) if getattr(before, x.name) != getattr(after, x.name)]
    assert set(differences) == {'release_hash', 'implementation', 'observation'}
    copies = []
    for name in original_payload['runtime']['source_files']:
        first, second = fingerprint(FROZEN_SOURCE/name), fingerprint(SOURCE/name)
        assert first['sha256'] == second['sha256']
        copies.append({'original': first, 'research': second})
    old_plan, new_plan = read(PROTOCOLS/'plan.json'), read(PROTOCOLS/'adapted_plan.json')
    for key in ('parameter_design', 'account', 'profit_concentration', 'time_stability'):
        assert old_plan[key] == new_plan[key]
    for old, new in zip(old_plan['cases'], new_plan['cases'], strict=True):
        assert {k:v for k,v in old.items() if k not in {'source_sha256','content_sha256'}} == {
            k:v for k,v in new.items() if k not in {'source_sha256','content_sha256'}}
    bound, result = cache_read(ROOT/'.tmp/s007-four-metrics/center.pkl.gz')
    assert bound.strategy.payload['runtime']['source_sha256'] == payload()['runtime']['source_sha256']
    baseline = next(x for x in result.runs if x.scenario_id=='baseline')
    old_tables, new_tables = {}, {}
    for name in ('decisions', 'orders', 'fills', 'trades'):
        old = pd.read_csv(ROOT/f'experiments/S007/20260915_S007_EX31/artifacts/{name}.csv',
                          float_precision='round_trip')
        if name=='decisions':
            old = old.loc[pd.to_datetime(old.valid_session).between('2021-01-05','2026-09-02')]
        old_tables[name] = old
        new_tables[name] = getattr(baseline.execution, name)
    assert ids(old_tables) == ids(new_tables)
    immutable = []
    for entry in old_plan['sources']:
        current = fingerprint(ROOT/entry['path'])
        assert current == entry
        immutable.append(current)
    guide = fingerprint(ROOT/'research/RSCH_AGENT.md')
    assert guide['sha256'] == '1c9cf46d378ce23f105e2a2e896c42927bca6e861892ffafd3aec61ceb9c4792'
    report = {'status': 'PASS', 'runtime_definition_differences': differences,
        'scope': 'Trading/input definitions equal; display observation and research identity explicitly differ',
        'source_copies': copies, 'eight_points_and_scales_unchanged': True,
        'relational_ids': 'First-occurrence normalized IDs across all executed decisions/orders/fills/trades exactly equal',
        'original_source_files_unchanged': immutable, 'independent_user_guide_unchanged': guide,
        'center_reproduction': read(PROTOCOLS/'center_proof_reference.json'),
        'C2132_reproduction': read(PROTOCOLS/'c2132_center_reference.json')}
    write(RUNS/'focused_verification.json', report)
    write(PROTOCOLS/'verification_reference.json', material('four-diagnostics-focused-verification',
        RUNS/'focused_verification.json').to_dict())
    print({'focused_verification': 'PASS', 'definition_differences': differences}, flush=True)


if __name__ == '__main__':
    main()
