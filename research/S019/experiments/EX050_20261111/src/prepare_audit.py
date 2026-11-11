"""Select each exact center, pressure, lowest-Calmar and maximum-MDD neighbor."""
from hashlib import sha256
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext, load_candidate
from strategy_manager import CandidateKey

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'research/RSCH_AGENT.md').is_file())
WORK = Path(__file__).resolve().parents[1]
if WORK.parent != ROOT/'research/S019/experiments':
    WORK = ROOT/'research/S019/experiments/EX050_20261111'
COUNTS = {'C0966':242,'C1010':728,'C0909':728}


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def immutable(path,value):
    if path.exists():
        assert read(path)==value, path
    else:
        path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


def main():
    result = read(WORK/'others/account_results.json')
    expected = {f'{cid}_P{i:03}' for cid,n in COUNTS.items() for i in range(n)} | {
        f'{cid}_{label}' for cid in COUNTS for label in ('CENTER','STRESS')}
    assert result['status']=='COMPLETE' and set(result['accounts'])==expected
    state_schema = result['accounts']['C0966_CENTER']['definition']['state_schema']
    specs = []
    for key,row in sorted(result['accounts'].items()):
        assert row['definition']['state_schema']==state_schema
        assert json.loads(row['definition']['parameters_json'])==row['parameters']
        specs.append({'label':key,'candidate_id':row['candidate_id'],
            'parameters':row['parameters'],'source_sha256':row['definition']['source_sha256'],
            'account_ref':row['account_ref']})
    specs_path = WORK/'others/audit_specs.json'
    immutable(specs_path,{'state_schema':state_schema,'specs':specs,
        'scope':'All 1698 neighborhood accounts and six reused center/stress scenarios.',
        'results_sha256':digest(WORK/'others/account_results.json'),
        'scope_sha256':digest(WORK/'protocols/scope.json')})
    manifest,selection = [],{}
    repo = RepositoryContext.discover(ROOT)
    for cid,n in COUNTS.items():
        center = load_candidate(repo,CandidateKey('S019',cid))
        points = {key:row for key,row in result['accounts'].items() if row['parent']==cid and row['label'].startswith('P')}
        assert set(points)=={f'{cid}_P{i:03}' for i in range(n)}
        choices = ((f'{cid}_CENTER','standard_center'),(f'{cid}_STRESS','double_fee_pressure'),
            (min(points,key=lambda k:(points[k]['candidate']['calmar'],k)),'lowest_neighbor_calmar'),
            (min(points,key=lambda k:(-points[k]['candidate']['drawdown'],k)),'maximum_neighbor_mdd'))
        for key,reason in choices:
            selection.setdefault(key,[]).append(reason)
        for key in sorted({key for key,_ in choices}):
            row = result['accounts'][key]
            definition_path = WORK/f'others/{key}_definition.json'
            immutable(definition_path,row['definition'])
            account_path = WORK/f'others/{key}_account.json'
            assert read(account_path)==row['account_ref']
            assert json.loads(row['definition']['parameters_json'])==row['parameters']
            assert row['definition']['source_sha256']==center.definition.source_sha256
            manifest.append({'definition':definition_path.relative_to(ROOT).as_posix(),
                'account':account_path.relative_to(ROOT).as_posix(),
                'source_root':center.source_root.relative_to(ROOT).as_posix(),
                'specs_protocol':specs_path.relative_to(ROOT).as_posix(),
                'specs_protocol_sha256':digest(specs_path),'spec_label':key,
                'selection_reasons':selection[key]})
    immutable(WORK/'others/audit_manifest.json',manifest)
    immutable(WORK/'others/audit_selection.json',{'rule':'Per selected candidate: standard center, double-fee pressure, minimum unrounded neighbor Calmar and maximum neighbor MDD; merge repeated choices, key breaks ties.',
        'selected':selection,'selected_accounts':len(manifest),'selected_decisions_expected':len(manifest)*15702,
        'results_sha256':digest(WORK/'others/account_results.json'),'scope_sha256':digest(WORK/'protocols/scope.json'),
        'selection_source_sha256':digest(Path(__file__)),'manifest_sha256':digest(WORK/'others/audit_manifest.json'),
        'specs_protocol_sha256':digest(specs_path),'specs_count':len(specs),
        'semantic_audit_source_sha256':digest(WORK/'src/semantic_audit.py'),
        'new_account_replays':0})
    print('AUDIT_SELECTED',len(manifest),sorted(selection),flush=True)


if __name__ == '__main__':
    main()
