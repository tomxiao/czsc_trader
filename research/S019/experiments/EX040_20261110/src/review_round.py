"""Verify center qualification, retain exact aliases, and choose adverse audit cases."""
from hashlib import sha256
import json
from math import isclose
from pathlib import Path

from czsc_trader import research_tools as d
from strategy_runtime import equity_source_hash

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def main():
    design = read(WORK / 'protocols/search.json')
    summary = read(WORK / 'others/summary.json')
    trials = read(WORK / 'others/trials.json')['trials']
    execution = read(WORK / 'others/execution.json')
    assert len(trials) == design['trial_budget'] == 48
    assert all(x['state'] == 'COMPLETE' for x in trials)
    assert {x['account_name'] for x in trials} == set(summary)
    assert all(isclose(x['value'], summary[x['account_name']]['candidate']['nar'],
                       abs_tol=1e-12, rel_tol=1e-12) for x in trials)
    assert read(WORK / 'others/center_parity.json')['status'] == 'PASS'
    assert 1 <= execution['equity_statistics']['candidate_runs'] <= 48
    current_source = equity_source_hash(WORK / 'src', ('strategy.py',))
    qualified, aliases = {}, []

    def inspect(row, name, origin, definition, reference):
        ref = d.EvidenceRef.from_dict(reference)
        raw = ref.resolve(ROOT).read_bytes()
        assert sha256(raw).hexdigest() == ref.sha256
        header = json.loads(raw)
        assert header['request']['candidate_id'] == row['id']
        assert header['request']['candidate_definition'] == definition
        assert definition['source_sha256'] == current_source
        assert json.loads(definition['parameters_json']) == row['parameters']
        m = row['candidate']
        expected = {'nar': m['nar'] >= .55, 'calmar': m['calmar'] >= 5,
            'absolute_dd': m['drawdown'] <= .25, 'relative_dd': m['drawdown'] <= .8 * row['buy_hold']['drawdown'],
            'frequency_median': m['frequency_median'] >= 6, 'frequency_coverage': m['frequency_coverage'] >= .9}
        assert expected == m['gates'] and all(expected.values()) == m['eligible']
        if not m['eligible']:
            return
        content = header['request']['content_sha256']
        item = {**row, 'name': name, 'origin': origin, 'content_hash': content,
                'account': reference, 'definition': definition, 'evaluation_id': header['evaluation_id']}
        if content in qualified:
            old = qualified[content]
            assert old['candidate'] == item['candidate'], 'Exact implementation metrics differ'
            aliases.append({'canonical_id': old['id'], 'alias_id': item['id'],
                            'account': reference, 'origin': origin, 'content_hash': content})
        else:
            qualified[content] = item

    old = read(WORK / 'protocols/prior_observations.json')
    prior_qualified = [row for row in old if row['candidate']['eligible']]
    assert len(prior_qualified) == 9
    # Original public observations precede later exact control aliases.
    for row in old:
        if not row['candidate']['eligible']:
            continue
        benchmark = row['benchmark']
        inspect({'id': row['candidate_id'], 'parameters': row['parameters'],
                 'candidate': row['candidate'], 'buy_hold': benchmark}, row['name'],
                'EX039_REUSED_CENTER_QUALIFIED', row['definition'], row['account_ref'])
    for name, row in summary.items():
        inspect(row, name, 'EX040_PROPOSAL', read(WORK / f'others/{name}_definition.json'), row['account'])
    ordered = sorted(qualified.values(), key=lambda r: r['candidate']['nar'], reverse=True)
    assert {row['content_hash'] for row in prior_qualified} <= set(qualified)
    assert ordered, 'Retain the nine prior qualified points even if new proposals all fail'
    save(WORK / 'others/qualified_candidates.json', ordered)
    save(WORK / 'others/exact_aliases.json', aliases)
    new_eligible = sorted([n for n, r in summary.items() if r['candidate']['eligible']],
                          key=lambda n: summary[n]['candidate']['nar'], reverse=True)
    select = {'trial000', max(summary, key=lambda n: summary[n]['candidate']['nar']),
              max(summary, key=lambda n: summary[n]['candidate']['calmar']),
              min(summary, key=lambda n: summary[n]['candidate']['calmar'])}
    if new_eligible:
        select.add(new_eligible[0])
    manifest = [{'definition': (WORK / f'others/{name}_definition.json').relative_to(ROOT).as_posix(),
                 'account': (WORK / f'others/{name}_account.json').relative_to(ROOT).as_posix()}
                for name in sorted(select)]
    save(WORK / 'others/audit_manifest.json', manifest)
    gates = {k: sum(r['candidate']['gates'][k] for r in summary.values()) for k in ordered[0]['candidate']['gates']}
    result = {'proposal_count': len(trials), 'unique_proposal_configurations': len(summary),
        'new_evaluations': execution['equity_statistics']['candidate_runs'],
        'new_benchmarks': execution['equity_statistics']['benchmark_runs'],
        'new_proposal_qualified_ids': [summary[n]['id'] for n in new_eligible],
        'all_qualified_exact_implementations': len(ordered), 'exact_aliases': len(aliases),
        'qualified_ids_by_nar': [r['id'] for r in ordered], 'frontier': ordered[0],
        'gate_pass_counts_in_proposals': gates, 'audit_cases': len(manifest),
        'best_boundary_parameters': {k: v for k, v in ordered[0]['parameters'].items()
            if k in design['space'] and v in (design['space'][k]['low'], design['space'][k]['high'])},
        'new_account_replays_in_review': 0}
    save(WORK / 'others/search_review.json', result)
    print('REVIEW_COMPLETE', len(ordered), ordered[0]['id'], 'audit', len(manifest), flush=True)


if __name__ == '__main__':
    main()
