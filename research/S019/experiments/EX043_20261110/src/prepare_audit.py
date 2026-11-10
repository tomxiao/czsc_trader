"""Select each mechanism's center and worst Calmar, plus global maximum MDD."""
from hashlib import sha256
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[3]


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def immutable(path, value):
    if path.exists():
        assert read(path) == value, f'Existing audit selection differs: {path.name}'
    else:
        path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def main():
    results = read(WORK/'others/results.json')
    specs = read(WORK/'protocols/specs.json')
    rows = results['accounts']
    assert results['status'] == 'COMPLETE' and len(rows) == len(specs['specs']) == 19
    assert set(rows) == {x['label'] for x in specs['specs']}
    center = next(s['parameters']['trail_atr'] for s in specs['specs'] if s['label']=='hard_center')
    groups = {}
    for label,row in rows.items():
        p = row['parameters']
        key = p['exit_policy'] + (f":{p['exit_width']:g}" if p['exit_policy']=='ramp' else '')
        groups.setdefault(key,[]).append(label)
    assert set(groups) == {'hard','none','confirm','daily_close','rolling_atr','ramp:0.5','ramp:1'}
    selection, group_details = {}, {}

    def choose(label, reason):
        selection.setdefault(label,[]).append(reason)

    for key,labels in sorted(groups.items()):
        centers = [label for label in labels if rows[label]['parameters']['trail_atr']==center]
        assert len(centers) == 1
        worst = min(labels,key=lambda label:(rows[label]['candidate']['calmar'],label))
        choose(centers[0],f'center:{key}')
        choose(worst,f'lowest_calmar:{key}')
        group_details[key] = {'labels':sorted(labels),'center':centers[0],'lowest_calmar':worst}
    maximum_mdd = min(rows,key=lambda label:(-rows[label]['candidate']['drawdown'],label))
    choose(maximum_mdd,'global_maximum_mdd')
    manifest = []
    for label,reasons in sorted(selection.items()):
        definition_path = WORK/f'others/{label}_definition.json'
        account_path = WORK/f'others/{label}_account.json'
        assert read(definition_path) == rows[label]['definition']
        assert read(account_path) == rows[label]['account_ref']
        manifest.append({'definition':definition_path.relative_to(ROOT).as_posix(),
            'account':account_path.relative_to(ROOT).as_posix(),
            'source_root':(WORK/'src').relative_to(ROOT).as_posix(),
            'selection_reasons':reasons})
    immutable(WORK/'others/audit_manifest.json',manifest)
    immutable(WORK/'others/audit_selection.json',{
        'rule':'Center ATR and lowest unrounded Calmar per exit policy (ramp widths separately), union global maximum MDD; label breaks exact ties.',
        'results_sha256':digest(WORK/'others/results.json'),'specs_sha256':digest(WORK/'protocols/specs.json'),
        'selection_source_sha256':digest(Path(__file__)),
        'manifest_sha256':digest(WORK/'others/audit_manifest.json'),'center_atr':center,
        'groups':group_details,'maximum_mdd':maximum_mdd,'selected':sorted(selection),
        'selected_accounts':len(manifest),'selected_decisions_expected':len(manifest)*15702,
        'new_account_replays':0})
    print('AUDIT_MANIFEST_READY',len(manifest),sorted(selection),flush=True)


if __name__=='__main__':
    main()
