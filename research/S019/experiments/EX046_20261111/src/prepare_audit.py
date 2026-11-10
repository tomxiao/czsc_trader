"""Select approved anchors' three-exit centers and worst Calmar, plus maximum MDD."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def immutable(path, value):
    if path.exists():
        assert read(path) == value, path
    else:
        path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def main(work):
    results = read(work/'others/results.json')
    protocol = work/'protocols/specs.json'
    spec = read(protocol)
    anchors = read(work/'protocols/anchors.json')
    rows = results['accounts']
    assert results['status'] == 'COMPLETE' and len(rows) == len(spec['specs']) == anchors['design_configurations']
    specs = {s['label']:s for s in spec['specs']}
    assert set(rows) == set(specs)
    assert all(rows[label]['parameters'] == s['parameters'] for label, s in specs.items())
    assert {a['name'] for a in anchors['anchors']} in (
        {'original','adapted'}, {'original','adapted','qualified_linear'})
    anchor_map = {a['name']:a for a in anchors['anchors']}
    assert len(anchor_map) == len(anchors['anchors'])
    original_anchor, adapted_anchor = anchor_map['original'], anchor_map['adapted']
    identities = {name:json.dumps({k:v for k,v in anchor['parameters'].items() if k != 'exit_policy'},
        sort_keys=True, separators=(',',':')) for name, anchor in anchor_map.items()}
    if 'qualified_linear' in anchor_map:
        assert identities['qualified_linear'] not in {identities['original'],identities['adapted']}, 'Third-anchor parameter collision requires explicit review'
    duplicate = original_anchor['parameters'] == adapted_anchor['parameters']
    parity_chain = None
    if duplicate:
        chain_path = (ROOT/anchors['dedup_control_parity']).resolve()
        assert chain_path.is_relative_to(ROOT)
        assert digest(chain_path) == anchors['dedup_control_parity_sha256']
        parity_chain = read(chain_path)
        assert parity_chain['status'] == 'PASS'
        assert parity_chain['original'] == original_anchor['reference']
        assert parity_chain['account'] == read(ROOT/adapted_anchor['reference'])
        assert parity_chain['daily_bar_targets_fills'] == 'EXACT_EQUAL'
        assert adapted_anchor['members'] == original_anchor['members']
    else:
        assert 'dedup_control_parity' not in anchors
    selected, groups, covered = {}, {}, set()

    def choose(label, reason):
        selected.setdefault(label, []).append(reason)

    for anchor in anchors['anchors']:
        assert set(anchor['members']) == {'hard','ramp','ramp_rebuild'}
        control_policy = anchor['control_policy']
        assert control_policy == ('hard' if anchor['name'] == 'qualified_linear' else 'ramp')
        assert anchor['parameters']['exit_policy'] == control_policy
        original_path = (ROOT/anchor['reference']).resolve()
        assert original_path.is_relative_to(ROOT) and original_path.is_file()
        for policy, members in anchor['members'].items():
            assert set(members) == {'low','center','high'}
            labels = list(members.values())
            assert len(set(labels)) == 3 and set(labels) <= set(rows)
            for level, factor in (('low',.95),('center',1.),('high',1.05)):
                label = members[level]
                p = rows[label]['parameters']
                expected = {**anchor['parameters'], 'exit_policy':policy}
                assert {k:v for k,v in p.items() if k != 'trail_atr'} == {k:v for k,v in expected.items() if k != 'trail_atr'}
                assert abs(p['trail_atr']-expected['trail_atr']*factor) <= 1e-12
            key = anchor['name']+':'+policy
            worst = min(labels, key=lambda label:(rows[label]['candidate']['calmar'] if rows[label]['candidate']['calmar'] is not None else float('-inf'),label))
            choose(members['center'],f'center:{key}')
            choose(worst,f'lowest_calmar:{key}')
            groups[key] = {'members':members, 'center':members['center'], 'lowest_calmar':worst}
            covered.update(labels)
        control = anchor['members'][control_policy]['center']
        expected_control = original_anchor['reference'] if duplicate and anchor['name'] in {'original','adapted'} else anchor['reference']
        assert specs[control]['control_account'] == expected_control
    assert covered == set(rows)
    maximum_mdd = min(rows, key=lambda label:(-rows[label]['candidate']['drawdown'],label))
    choose(maximum_mdd,'global_maximum_mdd')
    manifest = []
    for label, reasons in sorted(selected.items()):
        definition = work/f'others/{label}_definition.json'
        account = work/f'others/{label}_account.json'
        assert read(definition) == rows[label]['definition'] and read(account) == rows[label]['account_ref']
        manifest.append({'definition':definition.relative_to(ROOT).as_posix(),
            'account':account.relative_to(ROOT).as_posix(), 'source_root':(work/'src').relative_to(ROOT).as_posix(),
            'specs_protocol':protocol.relative_to(ROOT).as_posix(), 'specs_protocol_sha256':digest(protocol),
            'spec_label':label, 'selection_reasons':reasons})
    immutable(work/'others/audit_manifest.json',manifest)
    immutable(work/'others/audit_selection.json',{
        'rule':'Each exact anchor x exit-policy center and lowest unrounded Calmar; union global maximum MDD; label breaks exact ties. Canonical duplicate configurations audited once.',
        'results_sha256':digest(work/'others/results.json'),'specs_sha256':digest(protocol),
        'anchors_sha256':digest(work/'protocols/anchors.json'),'selection_source_sha256':digest(Path(__file__)),
        'manifest_sha256':digest(work/'others/audit_manifest.json'),'groups':groups,'selected':sorted(selected),
        'maximum_mdd':maximum_mdd,'selected_accounts':len(manifest),
        'effective_unique_parameter_anchors':len(set(identities.values())),
        'dedup_control_parity':parity_chain,
        'selected_decisions_expected':len(manifest)*15702,'new_account_replays':0})
    print('AUDIT_MANIFEST_READY',len(manifest),sorted(selected),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment',type=Path,default=Path(__file__).resolve().parents[1])
    main(parser.parse_args().experiment.resolve())
