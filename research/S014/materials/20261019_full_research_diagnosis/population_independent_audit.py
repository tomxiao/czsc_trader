"""Independent CSV/evidence review; no fitting, return labels or account runs."""
import argparse
import csv
from collections import Counter
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
import socket

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
OUT = ROOT / 'research/S014/materials/20261019_full_research_diagnosis'

def block(*args, **kwargs):
    raise RuntimeError('Network prohibited in independent existing-evidence review')

socket.socket.connect = block
socket.create_connection = block

def digest(p):
    return sha256(p.read_bytes()).hexdigest()

def read_json(p):
    return json.loads(p.read_bytes())

checks = []
sources = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

def published_csv(ex, filename):
    directory = ROOT / 'research/S014/experiments' / ex
    path = directory / 'others' / filename
    raw = path.read_bytes()
    h = sha256(raw).hexdigest()
    result_path = directory / 'others/result.json'
    refs = [r for r in read_json(result_path)['evidence'].values()
            if isinstance(r, dict) and r.get('type') == 'EvidenceRef'
            and r.get('sha256') == h]
    check(ex + '/' + filename + ' explicitly published', bool(refs))
    ref = EvidenceRef.from_dict(refs[0])
    published_path = ref.resolve(ROOT)
    check(ex + '/' + filename + ' exact published bytes', published_path.read_bytes() == raw)
    sources.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': h,
                    'bytes': len(raw), 'reference': ref.to_dict(),
                    'result_sha256': digest(result_path)})
    return list(csv.DictReader(StringIO(raw.decode('utf-8-sig'))))

coverage = read_json(OUT / 'population_coverage.json')
members = list(csv.DictReader((OUT / 'entry_population_members.csv').open(encoding='utf-8-sig', newline='')))
inputs = published_csv('EX032_20261018', 'inputs.csv')
check('inputs have exactly 1642 rows', len(inputs) == 1642)
check('input original signal positions consecutive', [int(x['signal']) for x in inputs] == list(range(1642)))
check('input date sequence strictly increasing unique', all(a['date'] < b['date'] for a, b in zip(inputs, inputs[1:])))
check('inherited A boolean complete', all(x['A'] in ('True', 'False') for x in inputs))
check('inherited A matches stored gap-down-repair flag',
      all((x['A'] == 'True') == (float(x['gap_down_repair']) == 1.0) for x in inputs))
preceding = {x['date']: inputs[i - 1] for i, x in enumerate(inputs) if i > 0}
recomputed = {}
max_member_log_error = 0.0

for ex, variant, candidate, closed, marked, expected_return in [
    ('EX023_20261018', 'support_exit_reserve_H10', 'S014-C0056', 138, 0, 7.08722425),
    ('EX024_20261018', 'support_first_profit_exit_H10', 'S014-C0057', 137, 1, 7.11877827),
]:
    raw_cycles = published_csv(ex, 'path_cycles.csv')
    cycles = [x for x in raw_cycles if x['variant'] == variant
              and x['cutoff'] == '2026-10-15' and x['window'] == 'ALL']
    check(candidate + ' 138 unique entry dates and cycle identities',
          len(cycles) == 138 and len({x['entry_date'] for x in cycles}) == 138
          and len({x['cycle_id'] for x in cycles}) == 138)
    check(candidate + ' correct closed/marked inventory',
          Counter(x['status'] for x in cycles) == Counter({'CLOSED': closed, 'MARKED_OPEN_NO_EXIT_FEE': marked}))
    own_members = [x for x in members if x['candidate'] == candidate]
    check(candidate + ' exact member count', len(own_members) == 138)
    by_id = {x['cycle_id']: x for x in own_members}
    check(candidate + ' exact member cycle identities', set(by_id) == {x['cycle_id'] for x in cycles})
    parts = {True: [], False: []}
    years = {}
    for row in cycles:
        prior = preceding[row['entry_date']]
        a = prior['A'] == 'True'
        m = by_id[row['cycle_id']]
        check(candidate + '/' + row['cycle_id'] + ' preceding-session mapping and unchanged fields',
              m['decision_date'] == prior['date'] and m['entry_date'] == row['entry_date']
              and m['variant'] == row['variant'] and m['status'] == row['status']
              and m['entry_year'] == row['entry_year']
              and (m['in_A_population'] == 'True') == a)
        error = abs(float(m['existing_cycle_log']) - float(row['cycle_log']))
        max_member_log_error = max(max_member_log_error, error)
        check(candidate + '/' + row['cycle_id'] + ' existing log copied within decimal roundtrip', error < 1e-14)
        parts[a].append(float(row['cycle_log']))
        y = years.setdefault(row['entry_year'], {'entries': 0, 'A_true': 0, 'A_false': 0})
        y['entries'] += 1
        y['A_true' if a else 'A_false'] += 1
    total = math.fsum(parts[True] + parts[False])
    summary = {
        'entries': 138, 'closed': closed, 'marked_open_no_exit_fee': marked,
        'A_true': len(parts[True]), 'A_false': len(parts[False]),
        'outside_A_fraction': len(parts[False]) / 138,
        'A_true_existing_log_sum': math.fsum(parts[True]),
        'A_false_existing_log_sum': math.fsum(parts[False]),
        'existing_total_cycle_log': total,
        'cycle_log_reconciliation_return': math.expm1(total),
        'entry_year_counts_not_annual_pnl': years}
    supplied = coverage['summaries'][candidate]
    for key, val in summary.items():
        if isinstance(val, float):
            check(candidate + '/' + key + ' summary reconciled', abs(val - supplied[key]) < 1e-12)
        else:
            check(candidate + '/' + key + ' summary reconciled', val == supplied[key])
    check(candidate + ' original full return reconciled including terminal mark', abs(math.expm1(total) - expected_return) < 1e-12)
    recomputed[candidate] = summary

check('exactly 276 representative member rows, no extra candidates',
      len(members) == 276 and {x['candidate'] for x in members} == set(recomputed))
check('coverage source references match independent evidence resolution',
      {(x['path'], x['sha256']) for x in coverage['sources']} == {(x['path'], x['sha256']) for x in sources})
check('coverage declares no new fits/accounts/labels/data',
      all(coverage[k] == 0 for k in ('new_fits', 'new_return_labels', 'new_accounts', 'new_market_data_calls')))

review = {
    'status': 'PASS_WITH_INTERPRETATION_LIMITS',
    'reviewer': 'independent RSCH subagent diagnose_accounts',
    'method': 'Independent standard-library csv parsing, math.fsum and per-cycle joins; main population function not executed or imported',
    'scope': 'EX023, EX024, EX032 explicitly published existing CSV evidence and supplied diagnosis outputs only',
    'sources': sources,
    'reviewed_output_sha256': {p: digest(OUT / p) for p in (
        'review_inventory.py', 'population_coverage.json', 'entry_population_members.csv')},
    'review_script': {'path': Path(__file__).relative_to(ROOT).as_posix(),
                      'sha256': digest(Path(__file__))},
    'assertion_count': len(checks),
    'checks': checks,
    'maximum_member_log_roundtrip_error': max_member_log_error,
    'independent_summaries': recomputed,
    'interpretation_limits': [
        '98/138 = 71.0144927536% is actual-entry coverage outside the A parent opportunity evaluation population, not proof models never trained on these dates or used only A rows.',
        'C0056 has 138 CLOSED cycles; C0057 has 137 CLOSED plus one MARKED_OPEN_NO_EXIT_FEE. Total C0057 return includes terminal mark, not 138 realized round trips.',
        'These two previously seen accounts are purposeful diagnostic representatives, not a random sample of all 66 accounts and not independent confirmation.',
        'A is evaluated at the decision session immediately preceding actual BUY; using entry-day A would introduce a timing mismatch.',
        'Grouped cycle-log contributions include whole entry-to-exit or mark periods and cannot substitute for calendar-year account returns, marginal filter effects or a newly simulated account.',
        'Coverage mismatch does not establish predictive signal value, prove A filtering caused existing losses, prove broader opportunity models will pass targets, or authorize a new account.',
        'H3 labels and H10 support/reservation actions have different horizons and state dependencies; population coverage alone does not repair this action/label mismatch.'
    ],
    'followup_correction': {
        'prior_E_plus_6_proposal_is_not_new': True,
        'basis': 'Parent confirmed EX034/EX035 already completed the E+6 diagnostic; those out-of-scope experiments were not opened in this subtask.',
        'instruction': 'Do not propose rerunning the already completed E+6 study; combine this coverage result with existing EX034/EX035 findings in the parent review.'},
    'new_fits': 0, 'new_return_labels': 0, 'new_accounts': 0,
    'new_market_data_calls': 0, 'new_matching_or_replay_calls': 0,
}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path,
                    help='Optional new audit JSON path; existing files are never overwritten. Default: stdout only.')
target = parser.parse_args().output
if target is not None:
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(review, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
print(json.dumps({'status': review['status'], 'assertions': len(checks),
                  'review_path': None if target is None else str(target),
                  'sha256': None if target is None else digest(target),
                  'max_member_error': max_member_log_error}))
