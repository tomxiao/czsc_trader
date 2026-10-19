"""Final static runner gate and pure aggregation audit; no component data fetch."""
import ast
from hashlib import sha256
import importlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path.cwd()
BASE = Path('research/S014/materials/20261020_shock_state_diagnosis')
EX = Path('research/S014/experiments/EX049_20261020')
def digest(path):
    return sha256((ROOT / path).read_bytes()).hexdigest()

def deny(*args, **kwargs):
    raise RuntimeError('B runner review is static/synthetic-only')

socket.socket.connect = deny
socket.create_connection = deny
expected = {
    (EX / 'src/run_component.py').as_posix(): 'f6f851d242dda48c56ca1fe4d4b5d919676cbfbd9663025cf6e5891561d6529f',
    (EX / 'protocols/design.json').as_posix(): '473778576626672f9d01ff112d77b11f76f1aac155bbafb49ce00a5bbb89e4a1',
    (EX / 'src/local_cycle.py').as_posix(): '58827ad8d59e4b3ebd99f250a25a05f8a1f552a9ebf8626ed1fef027f9134f6b',
    (EX / 'src/prepared_reader.py').as_posix(): '078c5d78033f40e2c73767b6ac92f1f36dbc296282ff0b00e8159bf68d2952a7',
    (EX / 'src/precheck.py').as_posix(): '74277aacf810152efc390d7e469e62b79395968070ed66e4b26bdd6b14ea3eda',
}
design = json.loads((ROOT / EX / 'protocols/design.json').read_bytes())
expected.update(design['external_source_hashes'])
for path, value in expected.items():
    assert digest(path) == value, path
assert design['new_funded_account_budget'] == 0 and design['event_count'] == 21
assert design['states'] == json.loads((ROOT / BASE / 'method_decision.json').read_bytes())['state_direction_locked_before_new_labels']
pre = json.loads((ROOT / EX / 'others/synthetic_precheck.json').read_bytes())
assert pre['status'] == 'PASS_PURE_SYNTHETIC_ONLY' and pre['checks_count'] == 32
for name, value in pre['source_hashes'].items():
    assert digest(EX / 'src' / name) == value
text = (ROOT / EX / 'src/run_component.py').read_text(encoding='utf-8')
tree = ast.parse(text)
on_ast = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'on')
off_ast = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'off')
assert 'OFF_LOCAL_CYCLE' not in ast.unparse(on_ast)
off_text = ast.unparse(off_ast)
assert off_text.index("check_gate('gate_ON_independent')") < off_text.index('R.fetch_inputs(') < off_text.index('Action.OFF_LOCAL_CYCLE')
assert "original = R.published(gate['ON_ref'])" in off_text
assert "resolve(ROOT).read_bytes() == (EX / 'others/on_controls.json').read_bytes()" in off_text
assert "{v['reviewer'] for v in gate['reviews']} == {'A', 'B'}" in ast.unparse(tree)
for required in ('source_lock_sha256', 'ON_ref', 'reviewed_hashes'):
    assert required in ast.unparse(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'check_gate'))
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr in {'evaluate', 'prepare', 'run_account', 'register_candidate'} for node in ast.walk(tree))
sys.path.insert(0, str(ROOT / EX / 'src'))
runner = importlib.import_module('run_component')
rows = []
for state, advantage, status in ((True, .1, 'CLOSED'), (False, -.2, 'CLOSED'), (None, .3, 'CLOSED'), (True, None, 'CENSORED')):
    rows.append({'origin_actual_event': {'year_of_D': '2024', 'holding_age_D': '0', 'remaining_D_sessions_to_deadline': '9'},
                 'D_known_states': {'PRIOR_TREND_ESTABLISHED': state},
                 'label_POSTHOC': {'advantage': advantage}, 'alternative_MODELLED_POSTHOC': {'status': status}})
summary = runner.aggregate(rows, 'PRIOR_TREND_ESTABLISHED')
assert summary['N'] == 4
assert [cell['N'] for cell in summary['cells']] == [2, 1, 1]
assert summary['cells'][0]['censored_n'] == 1
reference = summary['same_closed_known_cohort_reference']
assert reference['N'] == 2 and reference['always_exit_mean'] == 0
assert reference['always_hold_mean'] == -.05 and reference['frozen_true_hold_false_exit_mean'] == .05
assert runner.aggregate(rows, 'PRIOR_TREND_ESTABLISHED', year=2022)['N'] == 0
assert runner.aggregate(rows, 'PRIOR_TREND_ESTABLISHED', remaining=8)['same_closed_known_cohort_reference']['N'] == 0
for path in ('others/synthetic_precheck.json',):
    rel = (EX / path).as_posix()
    expected[rel] = digest(rel)
expected[Path(__file__).resolve().relative_to(ROOT).as_posix()] = digest(Path(__file__).resolve().relative_to(ROOT))
result = {
    'status': 'PASS', 'reviewer': 'B', 'blocking_findings': [], 'reviewed_hashes': expected,
    'kernel_review': {'path': (BASE / 'review/source_kernel_review_v2.json').as_posix(),
                      'sha256': '060598ab8dac8b12c52301fc895ff470538309df2473161fe53ecc1d9bcc743a', 'pure_checks': 36},
    'runner_review': [
        'Only build/on/off component interfaces; no funded account evaluation/prepare/registration. Build creates an explicit zero-funded index and authenticates immutable source/external bytes.',
        'ON phase never calls OFF. ON public output includes original actual provenance, modelled control and frozen D-known states; all21 population protected and rawsource inputs authenticated.',
        'OFF requires exact A+B current-lock ON reviews and full published ON_ref; local ON bytes must equal immutable published bytes before use. Original source lock and current runner hash gates prevent stale source reviews.',
        'Counterfactual/modelled POSTHOC fields separate from original actual observations; equalcycle label denominator and two fixed TRUE-hold directions unchanged.',
        'Pure aggregation confirms unknown/censored rows retained and all choices reference the same known/closed cohort. Emptyyear/exactremaining rows remain explicit; no accountwealth sum, annualization or invented sample gate.',
        'S2 finite boundary was corrected before real computation; prelock source/review history retained. Current finite formulas and <= equality direction unchanged.',
    ],
    'release_scope': 'Permit immutable public source lock and ON controls only after independent A source review also PASS. Real OFF labels require later A+B original21 ON exactcontrol PASS. No funded policy selected.',
    'real_prepared_fetches': 0, 'real_state_values': 0, 'real_ON_controls': 0,
    'real_OFF_labels': 0, 'new_funded_accounts': 0, 'new_market_calls': 0,
}
out = ROOT / BASE / 'review/source_runner_review.json'
with out.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({'path': out.relative_to(ROOT).as_posix(), 'sha256': digest(out.relative_to(ROOT)), 'bindings': len(expected), 'status': result['status']}))
