"""Focused preparation/center verification adapted from EX041; no account replay."""
from hashlib import sha256
import json
from pathlib import Path

SOURCE_DIRECTORY = Path(__file__).resolve().parent
WORK = SOURCE_DIRECTORY.parent / 'others' if SOURCE_DIRECTORY.name == 'src' else SOURCE_DIRECTORY
ROOT = next(p for p in WORK.parents if (p / 'research/RSCH_AGENT.md').is_file())


def read(name):
    return json.loads((WORK / name).read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    protocol = read('statistics_protocol.json')
    assert protocol['source_sha256'] == digest(SOURCE_DIRECTORY / 'statistics_analysis.py')
    for path, fingerprint in protocol['dependencies'].items():
        assert digest(ROOT / path) == fingerprint
    assert protocol['centers_sha256'] == digest(WORK / 'statistics_centers.json')
    assert protocol['inventory_sha256'] == digest(WORK / 'statistics_inventory.json')
    inventory = read('statistics_inventory.json')
    rows = [r for row in inventory['rows'] for r in [row, *row['aliases']]]
    assert inventory['published_account_count'] == len(rows)
    assert inventory['unique_implementations'] == len(inventory['rows'])
    assert len({r['reference']['sha256'] for r in rows}) == len(rows)
    assert len({r['implementation_sha256'] for r in inventory['rows']}) == len(inventory['rows'])
    assert all(r['reference']['experiment']['experiment_id'][:5] < 'EX050' for r in rows)
    for path in inventory['metadata_sources']:
        assert digest(ROOT / path['path']) == path['sha256']
    checks = ['Exact source/dependency/metadata hashes', 'Full standard-history identity and aliases',
              'No EX050 prior-selection candidates', 'Original NAR policy/no additional hard gates']
    assert protocol['new_hard_gates'] == []
    stage = 'PREPARATION_ONLY'
    if (WORK / 'statistics_temporal.json').exists():
        stage = 'CENTERS_READ_ONLY_COMPLETE'
        temporal = read('statistics_temporal.json')
        returns = read('statistics_center_returns.json')
        assert temporal['protocol_sha256'] == returns['protocol_sha256'] == digest(WORK / 'statistics_protocol.json')
        assert {x['candidate_id'] for x in temporal['candidates']} == set(protocol['centers'])
        assert set(returns['members']) == set(protocol['centers'])
        centers = {x['id']: x for x in read('statistics_centers.json')}
        for row in temporal['candidates']:
            cid = row['candidate_id']
            assert len(row['rolling']) == 46 and len(row['years']) == 5
            assert row['concentration_basis'] == 'MAX_SINGLE'
            assert returns['members'][cid]['reference'] == centers[cid]['references']['standard']
            assert len(returns['members'][cid]['returns']) == 1212
            for scenario in ('standard', 'pressure'):
                assert row['scenarios'][scenario]['reference'] == centers[cid]['references'][scenario]
                for output, expected in [('nar', 'nar'), ('mdd', 'drawdown'), ('calmar', 'calmar')]:
                    assert abs(row['scenarios'][scenario][output] - centers[cid][scenario][expected]) < 1e-10
        checks += ['Six scenario reference/metric matches', 'Three centers × five years × 46 rolling windows']
    output = {'status': 'PASS', 'stage': stage, 'new_accounts': 0, 'checks': checks,
              'source_sha256': digest(SOURCE_DIRECTORY / 'statistics_analysis.py'),
              'verification_source_sha256': digest(Path(__file__)),
              'protocol_sha256': digest(WORK / 'statistics_protocol.json'),
              'files': {p.name: digest(p) for p in WORK.glob('statistics*.json')
                        if p.name != 'statistics_verification.json'},
              'not_executed': ['Full-family incremental selection projection', 'Bootstrap unless separately requested']}
    (WORK / 'statistics_verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print('VERIFIED', stage, inventory['published_account_count'], inventory['unique_implementations'])


if __name__ == '__main__':
    main()
