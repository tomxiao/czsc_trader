"""Small, deterministic research-only ranking contract; no promotion rules."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math


@dataclass(frozen=True)
class Metric:
    name: str
    direction: str
    resolution: str
    origin: str = '0'

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError('metric name required')
        if self.direction not in ('maximize', 'minimize'):
            raise ValueError('invalid direction')
        if type(self.resolution) is not str or type(self.origin) is not str:
            raise ValueError('decimal resolution and origin must be explicit strings')
        step, origin = Decimal(self.resolution), Decimal(self.origin)
        if not step.is_finite() or step <= 0 or not origin.is_finite():
            raise ValueError('finite positive resolution and finite origin required')

    def bin(self, value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('finite numeric value required')
        return int(((Decimal(str(value)) - Decimal(self.origin)) / Decimal(self.resolution))
                   .to_integral_value(rounding=ROUND_HALF_UP))


def rank(rows, metrics):
    if not metrics or len({m.name for m in metrics}) != len(metrics):
        raise ValueError('unique nonempty metric set required')
    if len({r['config_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate config ID')
    vectors, unranked = {}, {}
    for row in rows:
        missing = [m.name for m in metrics if type(row.get(m.name)) not in (int, float)
                   or not math.isfinite(row[m.name])]
        if missing:
            unranked[row['config_id']] = {'status': 'MISSING_COMPARISON_EVIDENCE', 'metrics': missing}
        else:
            vectors[row['config_id']] = [m.bin(row[m.name]) * (1 if m.direction == 'maximize' else -1)
                                        for m in metrics]
    dominated = {cid: sorted(other for other, b in vectors.items() if other != cid
                            and all(y >= x for x, y in zip(a, b))
                            and any(y > x for x, y in zip(a, b))) for cid, a in vectors.items()}
    remaining, layers = set(vectors), []
    while remaining:
        front = sorted(cid for cid in remaining if not remaining.intersection(dominated[cid]))
        if not front:
            raise ValueError('dominance cycle')
        layers.append({'layer': len(layers) + 1, 'config_ids': front})
        remaining.difference_update(front)
    return {'metrics': [m.__dict__ for m in metrics], 'layers': layers,
            'dominated_by': dominated, 'unranked': unranked,
            'comparison_vectors': vectors, 'automatic_promotion': False}


def group_behaviors(rows, ranking, definitions):
    layers = {c: x['layer'] for x in ranking['layers'] for c in x['config_ids']}
    groups = []
    for behavior in sorted({r['behavior_id'] for r in rows}):
        members = sorted((r for r in rows if r['behavior_id'] == behavior), key=lambda r: r['config_id'])
        ids = [r['config_id'] for r in members]
        pressure = [r['fee20_cagr'] for r in members if math.isfinite(r['fee20_cagr'])]
        parameters = {cid: definitions[cid]['definition']['parameters'] for cid in ids}
        changes = {k: sorted({p[k] for p in parameters.values()}) for k in next(iter(parameters.values()))
                   if len({p[k] for p in parameters.values()}) > 1}
        groups.append({'behavior_id': behavior, 'config_ids': ids,
                       'member_layers': {cid: layers.get(cid) for cid in ids},
                       'front_member_ids': [cid for cid in ids if layers.get(cid) == 1],
                       'unranked_members': [cid for cid in ids if cid in ranking['unranked']],
                       'parameter_variations': changes,
                       'source_sha256s': sorted({definitions[cid]['definition']['runtime']['source_sha256'] for cid in ids}),
                       'fee20_cagr_range': [min(pressure), max(pressure)] if pressure else None,
                       'fee20_status': 'PARTIAL' if len(pressure) != len(ids) else 'COMPLETE',
                       'equivalence_scope': 'STANDARD_ACCOUNT_ONLY_OTHER_SCENARIOS_NOT_ASSUMED'})
    return groups
