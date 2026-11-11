"""Select fixed-diagnostic centers, controls, eligible leaders and adverse cases for audit."""
import argparse
from hashlib import sha256
import json
import math
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


def select(rows, specs, design):
    """Membership is explicit; full configuration binding is checked before selection."""
    assert set(design) == {'anchors'} and isinstance(design['anchors'], list) and design['anchors']
    assert rows and set(rows) == set(specs)
    for label, row in rows.items():
        assert row['label'] == specs[label]['label'] == label
        assert row['parameters'] == specs[label]['parameters']
        assert json.loads(row['definition']['parameters_json']) == specs[label]['parameters']
        metrics = row['candidate']
        assert type(metrics['nar']) in (int, float) and math.isfinite(metrics['nar'])
        assert set(metrics['gates']) == {'nar', 'calmar', 'absolute_dd', 'relative_dd', 'frequency_median', 'frequency_coverage'}
        assert metrics['eligible'] == all(metrics['gates'].values())
        assert type(metrics['drawdown']) in (int, float) and math.isfinite(metrics['drawdown']) and metrics['drawdown'] >= 0
        assert metrics['calmar'] is None or (type(metrics['calmar']) in (int, float) and math.isfinite(metrics['calmar']))
        assert metrics['gates']['frequency_median'] == (metrics['frequency_median'] >= 6)
        assert metrics['gates']['frequency_coverage'] == (metrics['frequency_coverage'] >= .9)
    selected, groups, covered = {}, {}, set()

    def choose(label, reason):
        selected.setdefault(label, []).append(reason)

    for anchor in design['anchors']:
        assert set(anchor) == {'name', 'center_label', 'members'}
        name, center, members = anchor['name'], anchor['center_label'], anchor['members']
        assert isinstance(name, str) and name and name not in groups
        assert isinstance(members, list) and members and len(members) == len(set(members))
        assert center in members and set(members) <= set(rows)
        labels = sorted(members)
        controls = [label for label in labels if specs[label].get('control_account')]
        worst = min(labels, key=lambda label:(rows[label]['candidate']['calmar']
            if rows[label]['candidate']['calmar'] is not None else float('-inf'), label))
        maximum = min(labels, key=lambda label:(-rows[label]['candidate']['drawdown'], label))
        eligible = [label for label in labels if rows[label]['candidate']['eligible']]
        highest_nar = min(eligible, key=lambda label:(-rows[label]['candidate']['nar'],
            rows[label]['candidate_id'], label)) if eligible else None
        frequency_failures = [label for label in labels if not all(rows[label]['candidate']['gates'][key]
            for key in ('frequency_median', 'frequency_coverage'))]
        choose(center, 'center:'+name)
        for control in controls:
            choose(control, 'control:'+name)
        choose(worst, 'lowest_calmar:'+name)
        choose(maximum, 'maximum_mdd:'+name)
        if highest_nar is not None:
            choose(highest_nar, 'highest_nar_eligible:'+name)
        if frequency_failures:
            choose(frequency_failures[0], 'first_frequency_failure:'+name)
        groups[name] = {'members':members, 'center':center, 'controls':controls,
            'lowest_calmar':worst, 'maximum_mdd':maximum, 'highest_nar_eligible':highest_nar,
            'first_frequency_failure':frequency_failures[0] if frequency_failures else None,
            'frequency_failure_count':len(frequency_failures)}
        covered.update(members)
    assert covered == set(rows), 'Diagnostic anchors must cover every configuration'
    maximum_mdd = min(rows, key=lambda label:(-rows[label]['candidate']['drawdown'], label))
    choose(maximum_mdd, 'global_maximum_mdd')
    return selected, groups, maximum_mdd


def main(work):
    assert work.is_relative_to(ROOT) and work.is_dir()
    results_path = work/'others/results.json'
    protocol = work/'protocols/specs.json'
    design_path = work/'protocols/diagnostic_design.json'
    results, config, design = read(results_path), read(protocol), read(design_path)
    assert results['status'] == 'COMPLETE'
    rows = results['accounts']
    specs = {item['label']:item for item in config['specs']}
    assert len(specs) == len(config['specs']) == len(rows)
    assert results['manifest']['specs_sha256'] == digest(protocol)
    for label, row in rows.items():
        assert read(work/f'others/{label}_definition.json') == row['definition']
        assert read(work/f'others/{label}_account.json') == row['account_ref']
        assert row['definition']['state_schema'] == config['state_schema']
    selected, groups, maximum_mdd = select(rows, specs, design)
    # Labels selected for several reasons share one audit. Exact account aliases must
    # carry exactly the same definition/parameters and share the canonical audit.
    by_account = {}
    for label, reasons in sorted(selected.items()):
        row = rows[label]
        identity = row['account_ref']['sha256']
        if identity in by_account:
            item = by_account[identity]
            canonical = rows[item['spec_label']]
            assert all(row[key] == canonical[key] for key in ('definition', 'parameters', 'account_ref', 'content_hash'))
            item['selection_reasons'].extend(reasons)
            item['selected_spec_labels'].append(label)
            continue
        by_account[identity] = {
            'definition':(work/f'others/{label}_definition.json').relative_to(ROOT).as_posix(),
            'account':(work/f'others/{label}_account.json').relative_to(ROOT).as_posix(),
            'source_root':(work/'src').relative_to(ROOT).as_posix(),
            'specs_protocol':protocol.relative_to(ROOT).as_posix(),
            'specs_protocol_sha256':digest(protocol), 'spec_label':label,
            'selection_reasons':reasons, 'selected_spec_labels':[label]}
    manifest = list(by_account.values())
    immutable(work/'others/audit_manifest.json', manifest)
    immutable(work/'others/audit_selection.json', {
        'rule':'Per declared anchor: center, all controls, lowest unrounded Calmar (unavailable first), maximum MDD, highest unrounded NAR passing all original six gates, and first frequency failure by lexical label; union global maximum MDD. Eligible NAR ties use candidate ID then label; other exact ties use label. Exact account aliases audited once.',
        'results_sha256':digest(results_path), 'specs_sha256':digest(protocol),
        'diagnostic_design_sha256':digest(design_path), 'selection_source_sha256':digest(Path(__file__)),
        'audit_selection_supplement_sha256':digest(work/'protocols/audit_selection_supplement.md'),
        'manifest_sha256':digest(work/'others/audit_manifest.json'), 'groups':groups,
        'selected':sorted(selected), 'maximum_mdd':maximum_mdd,
        'selected_accounts':len(manifest), 'selected_decisions_expected':len(manifest)*15702,
        'control_parity_validation':'Runner and close_round own exact economic parity checks',
        'new_account_replays':0})
    print('AUDIT_MANIFEST_READY', len(manifest), sorted(selected), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', type=Path, required=True)
    main(parser.parse_args().experiment.resolve())
