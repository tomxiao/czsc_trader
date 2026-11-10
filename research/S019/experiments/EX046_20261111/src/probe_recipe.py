"""Read-only recipe checks; no research creation, replay, or registration."""
import json
import math
import runpy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

root = Path.cwd()
tmp = root / '.tmp/s019-stage2-resume'
core = SimpleNamespace(**runpy.run_path(str(tmp / 'batch_runner_reversible.py'), run_name='recipe_probe'))
recipe = core.read(tmp / 'ex046_recipe.json')
selection = core.read(tmp / 'ex046_anchor_selection.json')
config = recipe['specs']
specs = [core.TrialSpec.parse(row) for row in config['specs']]
assert len(specs) == 27 and len({s.label for s in specs}) == 27
assert len({json.dumps(s.parameters, sort_keys=True) for s in specs}) == 27
assert config['candidate_start'] == 780
assert config['round_budget'] == {'allocated_rounds': 6, 'round_index': 4,
    'total_round': 8, 'remaining_after_completion': 2}
used = set()
for directory in (root/'research/S019/experiments', root/'research/registrations/S019'):
    for path in directory.rglob('*.json'):
        used.update(core.candidate_ids_in_record(path.read_text(encoding='utf-8')))
used.update(p.name for p in (root/'research/S019/assets/candidates').iterdir()
    if core.re.fullmatch(r'C\d{4}', p.name))
assert max(int(cid[1:]) for cid in used) == 779
assert not used.intersection(f'C{i:04}' for i in range(780, 807))

source = root / recipe['source_paths']['strategy.py']
local = tmp / 'ex046_recipe_probe_src'
local.mkdir(exist_ok=True)
(local/'strategy.py').write_bytes(source.read_bytes())
repo = core.RepositoryContext.discover(root)
base = core.load_candidate(repo, core.CandidateKey('S019', config['base_candidate']))
schema = json.loads(base.definition.parameter_schema_json)
assert all(k not in schema or schema[k] == v for k, v in config['parameter_schema'].items())
schema.update(config['parameter_schema'])
state_schema = core.StrategyStateSchema.from_dict(config['state_schema'])
state_check = core.validate_source_state_schema(source, state_schema)
source_hash = core.equity_source_hash(local, ('strategy.py',))
hashes, controls = [], []
for index, spec in enumerate(specs):
    assert set(spec.parameters) == set(schema)
    for key, value in spec.parameters.items():
        assert type(value) in {'boolean': (bool,), 'string': (str,), 'integer': (int,), 'number': (int, float)}[schema[key]['type']]
        assert not isinstance(value, (float, int)) or math.isfinite(value)
    definition = replace(base.definition, source_files=('strategy.py',), source_sha256=source_hash,
        state_schema=state_schema, parameters_json=json.dumps(spec.parameters, sort_keys=True, separators=(',', ':')),
        parameter_schema_json=json.dumps(schema, sort_keys=True, separators=(',', ':')))
    candidate = core.EquityStrategyCandidate('S019', f'C{780+index:04}', definition, local)
    hashes.append(candidate.content_identity.content_sha256)
    if spec.control_account:
        ref, payload = core.read_account(root/spec.control_account)
        request = payload['request']
        old = request['candidate_definition']
        new = json.loads(core.encoded(definition.to_dict()))
        assert json.loads(old['parameters_json']) == spec.parameters
        assert {k:v for k,v in old.items() if k != 'source_sha256'} == {k:v for k,v in new.items() if k != 'source_sha256'}
        assert request['fee_rate'] == .001 and request['scenario_id'] == 'STANDARD'
        assert request['window_id'] == 'FULL' and request['measurement_tier'] == 'FORMAL'
        controls.append({'label': spec.label, 'candidate_id': candidate.candidate_id,
            'reference_candidate_id': request['candidate_id'], 'reference': ref.to_dict(),
            'full_parameters_and_non_source_contract': 'EXACT_EQUAL'})
assert len(set(hashes)) == 27 and len(controls) == 3
assert [a['candidate_id'] for a in selection['anchors']] == ['C0678', 'C0754', 'C0720']
by_label = {s.label:s for s in specs}
for anchor in selection['anchors']:
    for policy, levels in anchor['members'].items():
        for level, label in levels.items():
            expected = {**anchor['parameters'], 'exit_policy': policy,
                'trail_atr': anchor['parameters']['trail_atr'] * {'low': .95, 'center': 1., 'high': 1.05}[level]}
            assert by_label[label].parameters == expected
    assert by_label[anchor['members'][anchor['control_policy']]['center']].control_account == anchor['reference']
result = {'status': 'PASS', 'scope': 'Static recipe/public definition and prior control payload checks; zero replay and zero registration',
    'configurations': 27, 'candidate_start': 780, 'candidate_end': 806,
    'next_candidate_start': 807, 'controls': controls, 'state_schema': state_check,
    'source_bundle_sha256': source_hash,
    'source_file_sha256': sha256(source.read_bytes()).hexdigest(),
    'recipe_sha256': core.digest(tmp/'ex046_recipe.json'),
    'anchors_sha256': core.digest(tmp/'ex046_anchor_selection.json'),
    'runner_sha256': core.digest(tmp/'batch_runner_reversible.py')}
(tmp/'ex046_recipe_probe.json').write_bytes(core.encoded(result))
print(json.dumps({k:v for k,v in result.items() if k not in ('controls','state_schema')}, ensure_ascii=False))
print('CONTROLS', [(r['label'],r['reference_candidate_id']) for r in controls])
