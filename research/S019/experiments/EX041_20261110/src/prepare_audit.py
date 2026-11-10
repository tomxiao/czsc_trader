"""Select each center's pressure, lowest-Calmar and highest-MDD parameter accounts."""
import json
from pathlib import Path
from czsc_trader.application import RepositoryContext, load_candidate
from strategy_manager import CandidateKey

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]
IDS = ('C0367', 'C0355', 'C0264')


def main():
    result = json.loads((WORK / 'others/account_results.json').read_bytes())
    assert result['status'] == 'COMPLETE' and len(result['accounts']) == 244
    manifest = []
    repo = RepositoryContext.discover(ROOT)
    for cid in IDS:
        center = load_candidate(repo, CandidateKey('S019', cid))
        points = {key: row for key, row in result['accounts'].items()
                  if row['parent'] == cid and row['label'].startswith('P')}
        assert set(points) == {f'{cid}_P{i:03}' for i in range(80)}
        selected = {f'{cid}_STRESS', min(points, key=lambda k: points[k]['candidate']['calmar']),
                    max(points, key=lambda k: points[k]['candidate']['drawdown'])}
        for key in sorted(selected):
            row = result['accounts'][key]
            definition_path = WORK / f'others/{key}_definition.json'
            definition_path.write_bytes((json.dumps(row['definition'], ensure_ascii=False, indent=2)+'\n').encode())
            manifest.append({'definition': definition_path.relative_to(ROOT).as_posix(),
                'account': f'research/S019/experiments/{WORK.name}/others/{key}_account.json',
                'source_root': center.source_root.relative_to(ROOT).as_posix()})
    (WORK / 'others/audit_manifest.json').write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode())
    print('AUDIT_SELECTED', len(manifest), flush=True)


if __name__ == '__main__':
    main()
