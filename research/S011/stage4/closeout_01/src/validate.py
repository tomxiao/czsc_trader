"""Read-only consistency checks for the user-approved stage-four closeout."""
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file())
PACKAGE = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def check_hash(path, expected):
    assert sha256(path.read_bytes()).hexdigest() == expected, str(path)


def validate():
    manifest = read(PACKAGE / 'manifest.json')
    actual = {p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob('*')
              if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}
    assert actual == set(manifest['files'])
    for name, digest in manifest['files'].items():
        check_hash(PACKAGE / name, digest)
    for name, digest in manifest['inputs'].items():
        check_hash(ROOT / name, digest)
    d = read(PACKAGE / 'decision.json')
    assert d['status'] == 'USER_APPROVED_CANDIDATE_PROMOTION'
    assert d['stage_four_status'] == 'CLOSED_WITH_DISCLOSED_LIMITATIONS'
    assert d['selected_config_ids'] == ['S011-CFG-000621']
    assert d['user_approval']['authority'] == 'USER'
    assert d['user_approval']['verbatim'] == '同意晋升621，请你先收尾阶段四'
    assert d['stage_five_authorized'] is True
    for key in ('stage_five_started', 'candidate_package_created', 'cio_approved',
                'frozen', 'deployed', 'platform_modified'):
        assert d[key] is False, key
    assert d['candidate_id'] is None
    registry = read(ROOT / d['registry'])['configurations']
    selected = next(c for c in registry if c['config_id'] == d['selected_config_ids'][0])
    assert selected['config_fingerprint'] == d['selected_config_fingerprint']
    original = ROOT / 'research/S011/stage4/iteration_04'
    old_manifest = read(original / 'manifest.json')
    for name, digest in old_manifest['files'].items():
        check_hash(original / name, digest)
    for name, digest in old_manifest['inputs'].items():
        check_hash(ROOT / name, digest)
    assert read(ROOT / d['supersedes_decision'])['status'] == 'PENDING_USER_DECISION'
    qualified = read(original / 'qualified_configurations.json')['configurations']
    q = next(c for c in qualified if c['config_id'] == selected['config_id'])
    assert all(q[k] is True for k in ('qualified', 'return_pass', 'drawdown_pass', 'frequency_pass'))
    ranks = pd.read_parquet(original / 'rankings.parquet')
    front = ranks[ranks.pareto_layer.eq(1)].sort_values('recommendation_rank').config_id.tolist()
    assert front == d['selection_basis']['original_first_layer_order']
    assert front.index(selected['config_id']) + 1 == d['selection_basis']['selected_original_within_layer_rank']
    checks = read(original / 'additional_checks.json')
    assert len(checks['balanced_joint_missing_config_ids']) == 32
    assert len(checks['unresolved_pairs']) == 9
    assert selected['config_id'] not in checks['balanced_joint_missing_config_ids']
    count = 0
    for window in d['supplemental_backtests']:
        package = ROOT / window['package']
        for suffix in ('000618', '000621'):
            r = read(package / 'receipts' / f'CFG{suffix}.json')
            assert r['config_id'] == f'S011-CFG-{suffix}'
            c = next(c for c in registry if c['config_id'] == r['config_id'])
            assert r['config_fingerprint'] == c['config_fingerprint']
            assert r['status'] == 'COMPLETE' and r['engine'] == 'TDR_BACKTEST_V2'
            assert r['audit']['status'] == 'PASS'
            assert all(v['status'] == 'PASS' for v in r['audit']['benchmarks'].values())
            if package.name != 'tdr_run_20260930':
                for name, digest in r['source_hashes'].items():
                    check_hash(ROOT / name, digest)
            for name, digest in r['files'].items():
                check_hash(ROOT / r['output_dir'] / name, digest)
            account = pd.read_csv(ROOT / r['output_dir'] / 'account_daily.csv')
            assert len(account) == window['sessions']
            dates = pd.to_datetime(account.date)
            assert [dates.iloc[0].strftime('%Y-%m-%d'), dates.iloc[-1].strftime('%Y-%m-%d')] == window['window']
            assert account.cash_before.iloc[0] == 1_000_000 and account.quantity_before.iloc[0] == 0
            expected_return = (r['strategy_metrics']['return'] if package.name == 'tdr_run_20260930'
                               else r['metrics']['total_return'])
            assert np.isclose(account.equity.iloc[-1] / 1_000_000 - 1, expected_return, rtol=0, atol=1e-12)
            if package.name != 'tdr_run_20260930':
                for name in ('account_daily.csv', 'decisions.csv', 'orders.csv', 'fills.csv', 'trades.csv'):
                    check_hash(package / f'CFG{suffix}' / name, r['files'][name])
            count += 1
    return {'status': 'PASS', 'selected_config_id': selected['config_id'],
            'original_evidence_preserved': True, 'tdr_receipts_verified': count,
            'stage_four_closed': True, 'stage_five_started': False}


if __name__ == '__main__':
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
