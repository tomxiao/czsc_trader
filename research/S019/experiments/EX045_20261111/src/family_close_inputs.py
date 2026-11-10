"""Authenticate Optuna records and expose an in-memory report view; preserve protocols."""
from decimal import Decimal
from hashlib import sha256
import json
import math


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def validate_parameters(parameters, family):
    assert set(parameters) == set(family['fixed']) | set(family['space'])
    assert all(parameters[k] == v for k, v in family['fixed'].items())
    for key, bounds in family['space'].items():
        value = parameters[key]
        assert type(value) in (int, float) and math.isfinite(value)
        assert bounds['low'] <= value <= bounds['high'], (key, value, bounds)
        if bounds['kind'] == 'int':
            assert type(value) is int
        if bounds['step'] is not None:
            lo, step, x = (Decimal(str(v)) for v in (bounds['low'], bounds['step'], value))
            assert (x-lo) % step == 0, (key, value, bounds)


def load(work):
    inputs = read(work/'others/close_inputs.json')
    expected = {'format':'OPTUNA_FAMILY_SEARCH_V1', 'run_manifest':'protocols/run_manifest.json',
        'static_search':'protocols/search.json', 'summary':'others/summary.json',
        'dynamic_specs':'others/candidate_specs.json', 'execution':'others/execution.json'}
    assert all(inputs[k] == v for k, v in expected.items())
    config = read(work/inputs['static_search'])
    manifest = read(work/inputs['run_manifest'])
    dynamic = read(work/inputs['dynamic_specs'])
    summary = read(work/inputs['summary'])
    execution = read(work/inputs['execution'])
    checkpoint = read(work/'others/search_checkpoint.json')
    assert execution['status'] == checkpoint['status'] == 'COMPLETE'
    assert execution['manifest'] == checkpoint['manifest'] == manifest
    assert manifest['search_sha256'] == dynamic['source_protocol_sha256'] == digest(work/'protocols/search.json')
    assert dynamic['source_protocol'] == 'protocols/search.json'
    assert dynamic['round_budget'] == config['round_budget'] == manifest['round_budget']
    assert dynamic['state_schema'] == config['state_schema']
    assert manifest['runner_sha256'] == digest(work/'src/family_search.py')
    assert manifest['plan_sha256'] == digest(work/'protocols/plan.md')
    for name, value in checkpoint['files'].items():
        path = (work/name).resolve()
        assert path.is_relative_to(work.resolve()) and digest(path) == value
    families = {f['name']: f for f in config['families']}
    specs = dynamic['specs']
    assert len(summary) == len(specs) == inputs['proposals'] == manifest['proposal_budget']
    assert set(summary) == {s['name'] for s in specs} == set(checkpoint['results']) == set(checkpoint['feedback'])
    assert execution['feedback'] == execution['proposals'] == len(specs)
    accounts, adapted_specs = {}, []
    for s in specs:
        key, family = s['name'], families[s['family']]
        prefix = f'others/trials/{key}'
        assert s['definition_path'] == prefix+'_definition.json' and s['account_path'] == prefix+'_account.json'
        proposal = read(work/(prefix+'_proposal.json'))
        assert {k:s[k] for k in proposal} == proposal
        row = summary[key]
        assert row == read(work/(prefix+'_result.json'))
        assert row['name'] == key and row['family'] == s['family'] and row['trial_number'] == s['number']
        assert row['parameters'] == s['parameters'] and row['id'] == s['candidate_id']
        assert row['proposed_candidate_id'] == s['proposed_candidate_id']
        assert row['content_hash'] == s['content_hash']
        assert row['definition'] == read(work/s['definition_path'])
        assert row['account'] == read(work/s['account_path'])
        validate_parameters(row['parameters'], family)
        tell = read(work/(prefix+'_tell.json'))
        assert tell['state'] == 'COMPLETE' and tell['number'] == s['number']
        assert tell['account'] == row['account'] and tell['value'] == row['candidate']['nar']
        assert tell['parameters'] == s['raw_parameters']
        assert tell['constraints'] == tell['system_constraints']
        m, bh = row['candidate'], row['buy_hold']
        dd = bh['drawdown']
        relative = m['drawdown']/(.8*dd)-1 if dd > 0 else (0. if m['drawdown'] == 0 else 1.)
        gates = [(.55-m['nar'])/.55, (5-m['calmar'])/5 if m['calmar'] is not None else 1e6,
            (m['drawdown']-.25)/.25, relative, (6-m['frequency_median'])/6, (.9-m['frequency_coverage'])/.9]
        assert tell['constraints'] == gates and m['eligible'] == (max(gates) <= 0)
        if s['alias_of'] is not None:
            canonical = summary[s['alias_of']]
            assert row['provenance']['kind'] == 'EXACT_ALIAS'
            assert all(row[k] == canonical[k] for k in ('id','account','parameters','definition','candidate','buy_hold','content_hash'))
        else:
            assert row['provenance'] == {'kind':'NEW_ACCOUNT','canonical':key}
        item = dict(s)
        if s['number'] == 0:
            item['control_account'] = family['control_account']
            parity = read(work/(prefix+'_parity.json'))
            control = manifest['controls'][s['family']]
            assert parity['status'] == 'PASS' and parity['original'] == family['control_account'] == control['path']
            assert parity['account'] == row['account'] and parity['daily_bar_targets_fills'] == 'EXACT_EQUAL'
        accounts[key] = {**row, 'label':key, 'candidate_id':row['id'], 'account_ref':row['account'],
            'benchmark':row['buy_hold'], 'role':'CONTROL' if s['number'] == 0 else 'STRUCTURAL_EXPERIMENT'}
        adapted_specs.append(item)
    for name in families:
        group = [s for s in specs if s['family'] == name]
        assert sorted(s['number'] for s in group) == list(range(config['trial_budget']))
    canonical = {r['account']['sha256'] for r in summary.values()}
    assert len(canonical) == inputs['canonical_accounts'] == execution['distinct_accounts']
    assert inputs['aliases'] == execution['aliases'] == sum(s['alias_of'] is not None for s in specs)
    spec = {**config, 'specs':adapted_specs}
    return {**execution, 'accounts':accounts}, spec, manifest
