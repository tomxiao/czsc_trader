"""Read immutable model outputs; independently audit arithmetic and fixed strata."""
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
EX = Path('research/S014/experiments/EX049_20261020')
COUNT = 0
def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def check(value, name):
    global COUNT
    if not value:
        raise AssertionError(name)
    COUNT += 1

def authenticated(path):
    ref = json.loads((ROOT / path).read_bytes())
    resolved = EvidenceRef.from_dict(ref).resolve(ROOT)
    check(resolved.read_bytes() == (ROOT / path.parent / path.name.replace('_ref', '')).read_bytes(), 'local/public bytes')
    check(digest(resolved.relative_to(ROOT)) == ref['sha256'], 'published hash')
    return json.loads(resolved.read_bytes()), ref, resolved.relative_to(ROOT)

off, off_ref, off_path = authenticated(EX / 'others/off_labels_ref.json')
on, on_ref, on_path = authenticated(EX / 'others/on_controls_ref.json')
check(off['origin_ON_control_ref'] == on_ref, 'OFF actualONref')
check(off['N'] == on['N'] == len(off['rows']) == 21, 'full original21')
check(off['source_lock_sha256'] == on['source_lock_sha256'] == digest(EX / 'protocols/execution_lock.json'), 'exact source lock')
check(off['new_funded_accounts'] == off['new_fits'] == off['new_supplier_calls'] == 0, 'component resources')
events = []
for row, prior in zip(off['rows'], on['rows'], strict=True):
    check(all(row[key] == value for key, value in prior.items()), 'exact original ON prefix')
    seed = row['seed']
    actual = row['original_ON_MODELLED_control']
    alternative = row['alternative_MODELLED_POSTHOC']
    label = row['label_POSTHOC']
    check(alternative['action'] == 'OFF_LOCAL_CYCLE' and alternative['quantity'] == seed['quantity'], 'modeled fixed Q')
    check(alternative['status'] == 'CLOSED', 'all21 modeled closed')
    actual_cash = actual['exit_price_ledger'] * seed['quantity'] - actual['exit_fee']
    model_cash = alternative['exit_price_ledger'] * seed['quantity'] - alternative['exit_fee']
    delta = model_cash - actual_cash
    capital = seed['ledger_entry_price'] * seed['quantity'] + seed['actual_buy_fee']
    advantage = delta / capital
    check(label['delta_net_proceeds'] == delta and label['advantage'] == advantage, 'total cash and capital denominator')
    check(label['sign'] == (1 if advantage > 0 else -1 if advantage < 0 else 0), 'strict sign no epsilon')
    check(alternative['exit_fee'] == alternative['exit_price_ledger'] * seed['quantity'] * .001, 'same original proportionalfee')
    check(not alternative['post_sale_close_evaluated'], 'no post-sale decisions')
    check(alternative['exit_E'] <= '2026-10-15', 'original cutoff')
    for trace in alternative['trace']:
        check(trace['D'] < alternative['exit_E'] and trace['D'] <= '2026-10-14', 'source boundary')
        check(trace['entry_index'] == seed['entry_index'] and trace['deadline_index'] == seed['deadline_index'] and trace['reservation_index'] == seed['reservation_index'], 'original anchors')
        check(trace['holding_age'] == trace['market_index'] - seed['entry_index'], 'own age')
        check(trace['shock_disable_latched'] == (trace['D'] >= seed['first_shock_D']), 'firstSHOCK once cycle latch')
        check(not trace['selected_shock_exit'], 'OFF only SHOCK action disabled')
        check(trace['exit_pending'] == (trace['pending_inherited'] or trace['deadline_exit'] or trace['selected_cost_exit'] or trace['ordinary_support_exit']), 'other exit priorities preserved')
    for state in ('PRIOR_TREND_ESTABLISHED', 'NON_FINAL_DAY_DOMINATED'):
        expected = advantage if row['D_known_states'][state] else 0.
        check(row['frozen_local_choices_POSTHOC'][state + '_TRUE_HOLD_FALSE_EXIT'] == expected, 'frozen direction unchanged')
    event = row['origin_actual_event']
    events.append({'D': event['D'], 'year': int(event['year_of_D']), 'age': int(float(event['holding_age_D'])),
                   'remaining': int(float(event['remaining_D_sessions_to_deadline'])),
                   'S1': row['D_known_states']['PRIOR_TREND_ESTABLISHED'],
                   'S2': row['D_known_states']['NON_FINAL_DAY_DOMINATED'],
                   'r1_log': row['D_known_states']['r1_log'], 'r4_log': row['D_known_states']['r4_log'],
                   'original_actual_SELL_E': event['actual_exit_fill_E'],
                   'original_actual_SELL_price': actual['exit_price_ledger'],
                   'alternative_MODELLED_POSTHOC_SELL_E': alternative['exit_E'],
                   'alternative_MODELLED_POSTHOC_SELL_price': alternative['exit_price_ledger'],
                   'advantage_POSTHOC': advantage})

def subset(summary):
    return [row for row in off['rows'] if (summary['year'] is None or int(row['origin_actual_event']['year_of_D']) == summary['year'])
            and (summary['age_kind'] is None or (float(row['origin_actual_event']['holding_age_D']) == 0) == (summary['age_kind'] == 'age0'))
            and (summary['exact_remaining'] is None or float(row['origin_actual_event']['remaining_D_sessions_to_deadline']) == summary['exact_remaining'])]

for summary in off['summaries']:
    rows = subset(summary)
    check(summary['N'] == len(rows), 'summary full population')
    for cell in summary['cells']:
        labels = [row['label_POSTHOC']['advantage'] for row in rows if row['D_known_states'][summary['state']] is cell['state_value']]
        check(cell['N'] == cell['closed_label_n'] == len(labels) and cell['censored_n'] == 0, 'summary cell N')
        for key, value in {'positive_n': sum(v > 0 for v in labels), 'negative_n': sum(v < 0 for v in labels),
                           'zero_n': sum(v == 0 for v in labels), 'mean_advantage': sum(labels) / len(labels) if labels else None,
                           'median_advantage': median(labels) if labels else None}.items():
            check(cell[key] == value, 'independent cell ' + key)
    reference = summary['same_closed_known_cohort_reference']
    labels = [row['label_POSTHOC']['advantage'] for row in rows]
    choices = [row['label_POSTHOC']['advantage'] if row['D_known_states'][summary['state']] else 0. for row in rows]
    check(reference['N'] == len(labels), 'same cohort')
    check(reference['always_hold_mean'] == (sum(labels) / len(labels) if labels else None), 'alwayshold')
    check(reference['frozen_true_hold_false_exit_mean'] == (sum(choices) / len(choices) if choices else None), 'fixed choices')

def cell(rows):
    values = [row['advantage_POSTHOC'] for row in rows]
    return {'n': len(values), 'mean': sum(values) / len(values) if values else None,
            'median': median(values) if values else None, 'positive': sum(v > 0 for v in values),
            'negative': sum(v < 0 for v in values)}

strata = {}
for state in ('S1', 'S2'):
    common = []
    layers = []
    for remaining in range(10):
        true_rows = [row for row in events if row[state] and row['remaining'] == remaining]
        false_rows = [row for row in events if not row[state] and row['remaining'] == remaining]
        weight = min(len(true_rows), len(false_rows))
        difference = cell(true_rows)['mean'] - cell(false_rows)['mean'] if weight else None
        layers.append({'remaining': remaining, 'true': cell(true_rows), 'false': cell(false_rows),
                       'common_weight_min_n': weight, 'true_minus_false': difference})
        if weight:
            common.append((weight, difference))
    strata[state] = {'exact_remaining_layers': layers,
                     'common_layer_true_minus_false_min_n_weighted': sum(w*d for w,d in common)/sum(w for w,d in common) if common else None,
                     'common_weight_total': sum(w for w,d in common),
                     'by_year': [{'year': year, 'true': cell([row for row in events if row['year'] == year and row[state]]),
                                  'false': cell([row for row in events if row['year'] == year and not row[state]])} for year in range(2020, 2027)]}
always = cell(events)['mean']
selection = {state: sum(row['advantage_POSTHOC'] if row[state] else 0. for row in events) / len(events) for state in ('S1', 'S2')}
bindings = {(EX / 'others/off_labels.json').as_posix(): digest(EX / 'others/off_labels.json'),
            off_path.as_posix(): digest(off_path), on_path.as_posix(): digest(on_path),
            (EX / 'protocols/execution_lock.json').as_posix(): digest(EX / 'protocols/execution_lock.json'),
            (BASE / 'review/on_control_review.json').as_posix(): digest(BASE / 'review/on_control_review.json'),
            Path(__file__).resolve().relative_to(ROOT).as_posix(): digest(Path(__file__).resolve().relative_to(ROOT))}
result = {'status': 'PASS_ARITHMETIC_AND_FIXED_CONTRAST_REVIEW', 'reviewer': 'B', 'blocking_findings': [],
          'reviewed_hashes': bindings, 'OFF_ref': off_ref, 'ON_ref': on_ref, 'checks_count': COUNT,
          'N': 21, 'modeled_closed': 21, 'censored': 0, 'unknown_states': 0,
          'always_hold_mean_advantage': always, 'frozen_choices_mean': selection,
          'choice_minus_always_hold': {state: value-always for state,value in selection.items()},
          'age0': cell([row for row in events if row['age'] == 0]),
          'age_ge1': cell([row for row in events if row['age'] >= 1]),
          'events': events, 'strata': strata,
          'scope': 'Independent strict cash/fee/label arithmetic, frozen summaries and local trace anchors/latch/other-exit logical consistency. A supplies independent full market-price execution oracle; no new OFF simulator or funded account executed here.',
          'new_prepared_fetches': 0, 'new_funded_accounts': 0, 'new_market_calls': 0, 'new_fits': 0}
out = ROOT / BASE / 'review/off_label_arithmetic_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({'status': result['status'], 'checks': COUNT, 'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT)), 'always_hold': always, 'choices': selection, 'common_remaining': {s: strata[s]['common_layer_true_minus_false_min_n_weighted'] for s in strata}, 'age0': result['age0'], 'age_ge1': result['age_ge1']}))
