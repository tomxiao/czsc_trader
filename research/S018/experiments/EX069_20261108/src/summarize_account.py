"""Read published account facts; no replay or strategy evaluation."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json

from czsc_trader.research_tools import EvidenceRef
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT = Path(__file__).resolve().parents[5]
EXP = Path(__file__).resolve().parents[1]


def main():
    ref = EvidenceRef.from_dict(json.loads((EXP/'others/account_reference.json').read_text()))
    path = ref.resolve(ROOT)
    def resolve(item):
        content = path.with_name(item['sha256']+'.json').read_bytes()
        assert sha256(content).hexdigest() == item['sha256']
        return content
    value = materialize_equity(path.read_bytes(), resolve).payload
    result = {'account_reference': ref.to_dict(), 'candidate': value['request']['candidate_id'],
              'price_basis': value['request']['price_basis'],
              'quantity_basis': value['request']['quantity_basis'], 'runs': {}}
    for name, run in value['runs'].items():
        metrics = run['metrics']
        counts = metrics['rolling_60_closed_cycle_counts']
        decisions = run['decisions']
        blocked = [d for d in decisions if d['plan']['evidence']['planning_result']['status'] == 'BLOCKED']
        result['runs'][name] = {
            'annualized_return': metrics['annualized_return'],
            'max_drawdown': metrics['bar_max_drawdown'],
            'calmar': metrics['annualized_return']/metrics['bar_max_drawdown'],
            'total_return': metrics['total_return'],
            'closed_cycles': metrics['closed_cycles'],
            'rolling_60_closed_cycle_median': metrics['rolling_60_closed_cycle_median'],
            'at_least_3_coverage': sum(x >= 3 for x in counts)/len(counts),
            'rolling_windows': len(counts), 'decisions': len(decisions),
            'orders': len(run['orders']), 'fills': len(run['fills']),
            'planning_status_counts': dict(Counter(d['plan']['evidence']['planning_result']['status'] for d in decisions)),
            'blocked_decisions': [{'date':d['execution_start'], 'target':d['target'],
                                   'order_quantity':d['quantity'], 'result':d['plan']['evidence']['planning_result']}
                                  for d in blocked],
            'original_failure_day': [d for d in decisions if d['execution_start'].startswith('2025-02-10')],
            'last_account_point': run['account_points'][-1],
        }
    (EXP/'others/account_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:{x:y for x,y in v.items() if x not in ('blocked_decisions','original_failure_day','last_account_point')}
                      for k,v in result['runs'].items()},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
