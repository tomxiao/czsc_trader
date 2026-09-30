"""Independent Fraction-based binning and dominance matrix verification."""
from pathlib import Path
from fractions import Fraction
import argparse
import json
import numpy as np
import pandas as pd
from build import validate, read, digest, UPSTREAM


def independent_bin(value, resolution, origin):
    fraction = (Fraction(str(value))-Fraction(origin))/Fraction(resolution)
    sign = 1 if fraction >= 0 else -1
    absolute = abs(fraction)
    return sign * ((2*absolute.numerator + absolute.denominator)//(2*absolute.denominator))


def audit(package):
    validate(package)
    rows = pd.read_parquet(package/'ranking_metrics.parquet')
    variants = {'main': read(package/'pareto.json'), **read(package/'ranking_sensitivity.json')}
    pairs = 0
    for name, result in variants.items():
        if name == 'previous_six_objectives':
            if result != read(UPSTREAM/'pareto.json'):
                raise ValueError('previous view changed')
            continue
        ids = [cid for layer in result['layers'] for cid in layer['config_ids']]
        table = rows.set_index('config_id').loc[ids]
        vectors = np.array([[independent_bin(float(row[m['name']]), m['resolution'], m['origin'])*(1 if m['direction'] == 'maximize' else -1)
                             for m in result['metrics']] for _, row in table.iterrows()], dtype=np.int64)
        relation = (vectors[:, None] >= vectors[None, :]).all(axis=2) & (vectors[:, None] > vectors[None, :]).any(axis=2)
        remaining = np.ones(len(ids), dtype=bool)
        for layer in result['layers']:
            front = np.flatnonzero(remaining & ~relation[remaining].any(axis=0))
            assert {ids[i] for i in front} == set(layer['config_ids'])
            remaining[front] = False
        assert not remaining.any()
        for j, cid in enumerate(ids):
            assert {ids[i] for i in np.flatnonzero(relation[:, j])} == set(result['dominated_by'][cid])
            assert vectors[j].tolist() == result['comparison_vectors'][cid]
        pairs += len(ids)**2
    groups = read(package/'behavior_groups.json')['groups']
    all_members = [cid for g in groups for cid in g['config_ids']]
    assert sorted(all_members) == sorted(rows.config_id) and len(set(all_members)) == len(all_members)
    for group in groups:
        members = rows.loc[rows.config_id.isin(group['config_ids'])]
        assert set(members.behavior_id) == {group['behavior_id']}
        assert group['fee20_status'] == ('PARTIAL' if members.fee20_cagr.isna().any() else 'COMPLETE')
    assert read(package/'decision.json')['selected_config_ids'] == []
    return {'status': 'PASS', 'manifest_sha256': digest(package/'manifest.json'), 'independent_binning': 'FRACTION_HALF_UP',
            'dominance_pair_checks': pairs, 'numeric_variants_checked': len(variants)-1,
            'all_36_configuration_members_preserved': True, 'risk_evidence_unchanged': True,
            'pending_user_decision': True, 'scope': 'Reranking and evidence identity; no new statistical, market-data or strategy validation'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--package', required=True, type=Path); a = p.parse_args()
    print(json.dumps(audit(a.package.resolve()), ensure_ascii=False))
