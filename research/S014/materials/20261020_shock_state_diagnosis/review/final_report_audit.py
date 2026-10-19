"""Exact local report/evidence/publication gate; no economic reevaluation."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd
from czsc_trader.research_tools import EvidenceRef

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
HASHES = {}
COUNT = 0
SEEN_REFS = set()
def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def check(value, name):
    global COUNT
    if not value:
        raise AssertionError(name)
    COUNT += 1

def bind(path, expected=None):
    path = Path(path)
    actual = digest(path)
    if expected is not None:
        check(actual == expected, path.as_posix())
    HASHES[path.as_posix()] = actual
    return actual

def walk_refs(value):
    if isinstance(value, dict):
        if value.get('type') == 'EvidenceRef':
            ref = EvidenceRef.from_dict(value)
            key = (ref.experiment.experiment_id, ref.evidence_id)
            if key in SEEN_REFS:
                return
            SEEN_REFS.add(key)
            check(ref.experiment.strategy_id == 'S014', 'S014 evidence domain')
            path = ref.resolve(ROOT)
            bind(path.relative_to(ROOT), ref.sha256)
        for item in value.values():
            walk_refs(item)
    elif isinstance(value, list):
        for item in value:
            walk_refs(item)

report_path = BASE / 'report.md'
judgment_path = BASE / 'judgment.json'
bind(report_path, 'ec00ff9bf828302f645561e829e64c79f21788c4a24188fdd580eef03c904189')
bind(judgment_path, '1c68c18f07c85841626abbfc50664a9d30f03c3a4761bac6c37d078065ce55b7')
report = (ROOT / report_path).read_text(encoding='utf-8')
judgment = json.loads((ROOT / judgment_path).read_bytes())
for link in re.findall(r'\]\(([^)]+)\)', report):
    if link.startswith('https://'):
        continue
    path = (ROOT / BASE / link).resolve()
    check(path.is_relative_to(ROOT) and path.is_file(), 'report relative link ' + link)
    bind(path.relative_to(ROOT))

yearly = pd.read_csv(ROOT / BASE / 'accounting/full_policy_yearly_summary.csv', float_precision='round_trip')
summary = pd.read_csv(ROOT / BASE / 'accounting/full_policy_summary.csv', float_precision='round_trip')
check(judgment['all_policy_years'] == yearly.to_dict('records'), '21 yearly exact source rows')
check(judgment['all_policy_summary'] == summary.to_dict('records'), '3 policy exact source rows')
check(len(yearly) == 21 and len(summary) == 3, 'complete fixed policies/years')
for row in yearly.to_dict('records'):
    expected_return_pass = row['return'] >= row['required_return'] if row['buyhold_return'] > 0 else row['return'] > 0
    check(row['return_pass'] == expected_return_pass, 'original annual return rule')
    check(row['drawdown_pass'] == (row['max_drawdown'] < row['buyhold_drawdown']), 'strict DD')
    check(row['technical_only'] is False, 'all7 original economic scope')
for row in summary.to_dict('records'):
    check(not row['all_original_economic_goals_pass'], 'no fully qualified policy')
    check(row['frequency_full_contract'] == 60 * row['closed_trades_full_contract'] / 1642, 'original public frequency operation order')
    check(row['original_frequency_pass'], 'all actual frequency pass')
check(judgment['original_full_contract_all_targets_pass'] is False, 'original goals not relaxed')
check(judgment['original_partial2026_hard_goal_retained'] is True, 'partial2026 retained')
check(judgment['complete_year_goal_pass_profiles'] == ['S014-C9500'], 'only control six-completeyear pass')
check(judgment['original_full_contract_all_goal_pass_profiles'] == [], 'no 7yearpass')
check(judgment['actual_resources'] == {'diagnostic_account_dispatches':3,'fresh_controls':1,'treatments':2,'succeeded':3,'failed':0,'unknown':0,'cancelled':0,'retries':0}, 'actual resources')
check(judgment['component_resources'] == {'original_events':21,'original_ON_controls':21,'alternative_model_OFF_cycles':21,'closed_model_OFF_cycles':21,'censored':0,'unknown_state_events':0,'funded_accounts':0}, 'component not funded')
for field in ('new_registered_candidates','new_qualified_candidates','new_formal_components','new_external_calls','new_fits','new_dependencies','new_threshold_scans'):
    check(judgment[field] == 0, field)
check(judgment['stage_advance'] is False, 'no automatic advance')

for experiment, expected_ref in [('EX049_20261020','8596c8fe516be2673ebea5a6e173e844f0b9bc4265462d59db147bccdee61327'),
                                  ('EX050_20261020','73cfbaf18bc98e6b72e2db3d4daf9d48cac0cc77642dede9fdebd604c024c0f8')]:
    ex = Path('research/S014/experiments') / experiment
    ref_path = ex / 'others/final_verification_ref.json'
    bind(ref_path)
    ref = json.loads((ROOT / ref_path).read_bytes())
    check(ref['sha256'] == expected_ref, 'expected formal final')
    walk_refs(ref)
    final = json.loads(EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes())
    check(final['status'].startswith('PASS'), 'final scope PASS')
    check((ROOT / ex / 'others/final_verification.json').read_bytes() == EvidenceRef.from_dict(ref).resolve(ROOT).read_bytes(), 'final local/public exact')
    bind(ex / 'others/final_verification.json')
    walk_refs(final)
    lock_path = ex / 'protocols/execution_lock.json'
    bind(lock_path)
    lock = json.loads((ROOT / lock_path).read_bytes())
    for relative, expected in lock['source_hashes'].items():
        bind(ex / relative, expected)
    for relative, expected in lock['external_source_hashes'].items():
        bind(relative, expected)
    for file in ('others/accounts_index.json','others/accounts_index_ref.json'):
        bind(ex / file)
    index = json.loads((ROOT / ex / 'others/accounts_index.json').read_bytes())
    check(len(index['records']) == (0 if 'EX049' in experiment else 3), 'actual account count')

for name in ('accounting/local_off_independent_review.json', 'accounting/independent_policy_audit_summary.json'):
    path = BASE / name
    bind(path)
    review = json.loads((ROOT / path).read_bytes())
    check(review['status'].startswith('PASS'), 'independent full audit')
    for item in review.get('outputs', []) + review.get('account_reports', []):
        bind(item['path'], item['sha256'])
    walk_refs(review)
for name in ('review/interpretation_results.json', 'review/component_final_review.json',
             'review/policy_interpretation_results.json', 'review/policy_actual_path_bridge_review.json',
             'review/policy_actual_2025_2026_cycle_bridge.csv', 'review/component_review_delivery.json',
             'review/policy_review_delivery.json', 'review/publication_destination_independent_review.json',
             'publication_destination_review_v2.json'):
    bind(BASE / name)

helper = Path('.tmp/s014_publish_shock_state_v2.py')
bind(helper, '48bbdf46b31b7ee6206abc83fd1f3ec8489a88d3cd847ca9a26bc5aecc99e06d')
destination = json.loads((ROOT / BASE / 'publication_destination_review_v2.json').read_bytes())
for path, expected in destination['implementation_sources'].items():
    bind(path, expected)
baseline = json.loads((ROOT / BASE / 'baseline_integrity.json').read_bytes())
for path, expected in baseline['protected_files'].items():
    check(digest(path) == expected, 'protected old bytes ' + path)
family = json.loads((ROOT / 'research/registrations/S014/family.json').read_bytes())
canonical = json.dumps(family['research_intent'], sort_keys=True, ensure_ascii=True).encode()
check(sha256(canonical).hexdigest() == baseline['prior_intent_sha256'], 'prior canonical intent intact')
check('shock_state_diagnosis_20261020' not in family['research_intent'], 'not yet aggregate-published')
bind(Path(__file__).resolve().relative_to(ROOT))
result = {
    'status':'PASS','reviewer':'B','blocking_findings':[],'reviewed_hashes':HASHES,
    'checks_count':COUNT,'verified_declared_EvidenceRefs':len(SEEN_REFS),
    'report_scope':'Exact final prose/tables/judgment, original7goals,21 local component labels,3 actual full accounts, source locks/finalrefs, relative links and local aggregate publisher. No account/model/market recomputation.',
    'content_judgment':'AGE provides concrete2026 fullpolicy improvement but fails2025; all3 remain unqualified under original annual criteria. S2 clock counterevidence, postlabel age selection, known adverse cases, different own funding and local-vs-funded distinction are correctly retained. Next research question is specific and bounded, not an approved new rule or promised repair.',
    'actual_path_review':'Marchhold loss -> own April9 slot -> missing original April10 cycle, followed by retained May30/June19 actual cycles is accurately described. The own-year contribution bridge is an accounting identity with differentQ/cash, explicitly not causal additive effects. 2026 goodextensions and Jan6 negative case coexist; no year selector.',
    'scope_limits':'No claim of unseen validation, confidence/sample/noharm gate, repository-wide regression, phase4 selfinspection, formal registration/production or remote git operation. Earlier timestamp audit-expression incident and prelock source changes preserved separately from successful actual accounts.',
    'publication_gate':{'helper_sha256':HASHES[helper.as_posix()],
                        'local_only':True,'component_funded_accounts':0,'actual_dispatches':3,
                        'protected_original_files_verified':len(baseline['protected_files']),
                        'prior_intent_preserved':True,
                        'pre_delivery_condition':'PREDELIVERY_LOCAL_PUBLICATION_REQUIRED: execute only this reviewed local helper under required filesystem hardlink permissions, then verify publication.json plus oldintent/byte preservation. The downstream receipt does not yet exist and is not falsely treated as published.'},
    'report_recommendation':'Content is ready for the declared local publication. Preserve reviewed bytes and both EX finals; later factual/content edits require a successor exact review.',
    'new_funded_accounts':0,'new_market_calls':0,'new_fits':0,
}
out = ROOT / BASE / 'final_report_review.json'
with out.open('x',encoding='utf-8',newline='\n') as handle:
    json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
    handle.write('\n')
print(json.dumps({'status':'PASS','checks':COUNT,'refs':len(SEEN_REFS),'bound_files':len(HASHES),
                  'path':out.relative_to(ROOT).as_posix(),'sha256':digest(out.relative_to(ROOT)),
                  'report_sha256':HASHES[report_path.as_posix()],'judgment_sha256':HASHES[judgment_path.as_posix()]}))
