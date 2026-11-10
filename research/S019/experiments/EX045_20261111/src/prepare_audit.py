"""Select predeclared family controls, winners/counterexamples and global MDD."""
import argparse
from pathlib import Path
from family_close_inputs import digest, load, read
import json

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())


def immutable(path, value):
    if path.exists():
        assert read(path) == value, path
    else:
        path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode())


def main(work):
    results, spec, manifest = load(work)
    rows = results['accounts']
    selected, details = {}, {}

    def choose(key, reason):
        selected.setdefault(key, []).append(reason)

    def violations(key):
        values = read(work/f'others/trials/{key}_tell.json')['constraints']
        positive = [max(0, x) for x in values]
        return sum(positive), max(positive), -rows[key]['candidate']['nar'], key

    for family in spec['families']:
        name = family['name']
        keys = [key for key, row in rows.items() if row['family'] == name]
        control = next(k for k in keys if rows[k]['trial_number'] == 0)
        eligible = [k for k in keys if rows[k]['candidate']['eligible']]
        winner = min(eligible, key=lambda k:(-rows[k]['candidate']['nar'], k)) if eligible else min(keys, key=violations)
        worst = min(keys, key=lambda k:(rows[k]['candidate']['calmar'] if rows[k]['candidate']['calmar'] is not None else float('-inf'), k))
        choose(control, f'control:{name}')
        choose(winner, f'highest_nar_eligible:{name}' if eligible else f'minimum_positive_normalized_violations:{name}')
        choose(worst, f'lowest_calmar:{name}')
        details[name] = {'control':control, 'representative':winner, 'lowest_calmar':worst,
            'eligible_proposals':len(eligible), 'total_proposals':len(keys)}
    max_mdd = min(rows, key=lambda k:(-rows[k]['candidate']['drawdown'], k))
    choose(max_mdd, 'global_maximum_mdd')
    by_ref = {}
    specs = {s['label']:s for s in spec['specs']}
    for key, reasons in sorted(selected.items()):
        identity = rows[key]['account_ref']['sha256']
        if identity in by_ref:
            by_ref[identity]['selection_reasons'].extend(reasons)
            by_ref[identity]['selected_proposal_aliases'].append(key)
            continue
        s = specs[key]
        by_ref[identity] = {'definition':(work/s['definition_path']).relative_to(ROOT).as_posix(),
            'account':(work/s['account_path']).relative_to(ROOT).as_posix(),
            'source_root':(work/'src').relative_to(ROOT).as_posix(), 'family':s['family'],
            'search_protocol':(work/'protocols/search.json').relative_to(ROOT).as_posix(),
            'search_protocol_sha256':manifest['search_sha256'],
            'selection_reasons':reasons, 'selected_proposal_aliases':[key]}
    audit = list(by_ref.values())
    immutable(work/'others/audit_manifest.json', audit)
    immutable(work/'others/audit_selection.json', {
        'rule':'Per family: control, highest unrounded NAR among original six-gate eligible proposals (otherwise minimum sum positive normalized constraints, then minimum maximum violation, then higher NAR), and lowest Calmar; union global maximum MDD. Key breaks exact ties. Exact account aliases audited once.',
        'groups':details, 'global_maximum_mdd':max_mdd, 'selected':sorted(selected),
        'selected_accounts':len(audit), 'selected_decisions_expected':len(audit)*15702,
        'summary_sha256':digest(work/'others/summary.json'), 'dynamic_specs_sha256':digest(work/'others/candidate_specs.json'),
        'search_sha256':manifest['search_sha256'], 'selection_source_sha256':digest(Path(__file__)),
        'adapter_source_sha256':digest(Path(__file__).with_name('family_close_inputs.py')),
        'manifest_sha256':digest(work/'others/audit_manifest.json'), 'new_account_replays':0})
    print('AUDIT_MANIFEST_READY', len(audit), sorted(selected), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', type=Path, required=True)
    main(parser.parse_args().experiment.resolve())
