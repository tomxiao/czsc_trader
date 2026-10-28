"""Authenticate and summarize already published stage-two analyses."""
from hashlib import sha256
import json
from math import prod
from pathlib import Path

from czsc_trader.research_tools import EvidenceRef

ROOT = Path(__file__).resolve().parents[5]
WORK = Path(__file__).resolve().parents[1]


def main():
    sources, records = [], {}
    for number in range(2, 6):
        work = ROOT / f'research/S017/experiments/EX00{number}_20261028'
        publication = json.loads((work / 'others/publication.json').read_text(encoding='utf-8'))
        assert publication['validation']['status'] == 'PASS'
        assert publication['experiment_validation']['status'] == 'PASS'
        content = (work / 'others/analysis.json').read_bytes()
        refs = [r for r in publication['evidence']
                if r['sha256'] == sha256(content).hexdigest()
                and r['experiment']['experiment_id'] == work.name]
        assert len(refs) == 1
        ref = EvidenceRef.from_dict(refs[0])
        assert ref.resolve(ROOT).read_bytes() == content
        sources.append(refs[0])
        analysis = json.loads(content)
        assert analysis['status'] == 'PASS'
        for key, value in analysis['accounts'].items():
            assert key not in records
            metrics = value['audited_metrics']
            annual = value['annual']
            years = {r['year']: r for r in annual}
            assert set(years) == set(range(2019, 2026))
            records[key] = {
                'origin': work.name,
                'account_reference': analysis['source_accounts'][key],
                'metrics': {k: metrics[k] for k in (
                    'annualized_return', 'bar_max_drawdown', 'total_return',
                    'closed_cycles', 'fees', 'rolling_60_closed_cycle_median')},
                'holding_bar_fraction': value['holding_bar_fraction'],
                'order_reason_counts': value['order_reason_counts'],
                'frequency_coverage_at_least_three': value['frequency_60_sessions']['coverage_at_least_three'],
                'pre2025_return': prod(1 + years[y]['candidate']['net_return'] for y in range(2019, 2025)) - 1,
                'annual': [{
                    'year': y, 'candidate_return': r['candidate']['net_return'],
                    'buyhold_return': r['buy_hold']['net_return'],
                    'excess_return': r['excess_net_return'],
                    'holding_bar_fraction': r['candidate']['holding_bar_fraction'],
                } for y, r in years.items()],
                'years_underperforming_buyhold': sum(r['excess_net_return'] < 0 for r in annual),
                'rolling_underperforming_count': sum(r['excess_net_return'] < 0 for r in value['rolling_252_step_21']),
                'rolling_count': len(value['rolling_252_step_21']),
            }
    assert len(records) == 19
    output = {'status': 'PASS', 'scope': 'Retained development evidence only, no new replay',
              'sources': sources, 'records': records,
              'limitations': ['Annual and overlapping rolling counts are descriptive, not independent tests.',
                              'Only retained evidence is counted; configurations do not equal independent hypotheses.']}
    (WORK / 'others/synthesis.json').write_bytes(json.dumps(output, ensure_ascii=False, indent=2).encode())
    for key in ('C0000', 'C0001', 'C0002', 'C0003', 'C0013', 'C0025', 'C0029'):
        r = records[key]
        print(key, r['metrics'], 'pre2025', r['pre2025_return'],
              'lag-years', r['years_underperforming_buyhold'],
              'lag-roll', r['rolling_underperforming_count'], '/', r['rolling_count'])


if __name__ == '__main__':
    main()
