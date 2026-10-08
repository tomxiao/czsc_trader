"""Compare same-route FULL accounts, retaining independent source identities."""
import json
import pandas as pd
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT, WORK, cache_read, context, save
from search import configuration_hash


def main():
    plan = json.loads((WORK / 'four_gate_adaptive_1_plan.json').read_text(encoding='utf-8'))
    rows = json.loads((WORK / 'search_results_r4.json').read_text(encoding='utf-8'))['rows']
    by_hash = {r['config_hash']: r for r in rows if r['status'] == 'SUCCEEDED'}
    checks = []
    for item in plan['configurations'][:3]:
        left = by_hash[configuration_hash(item['equivalence_original_parameters'])]
        right = by_hash[configuration_hash(item['parameters'])]
        a = cache_read(ROOT / f'.tmp/s013-stage3-hfq/{left["candidate_id"]}.pkl.gz')
        b = cache_read(ROOT / f'.tmp/s013-stage3-hfq/{right["candidate_id"]}.pkl.gz')
        columns = {}
        for table in ('decisions', 'orders', 'fills', 'account_daily', 'trades'):
            x, y = getattr(a.runs[0].execution, table), getattr(b.runs[0].execution, table)
            # Source-derived IDs are independent. Compare every original non-ID
            # field exactly; added causal regime diagnostics are named separately.
            selected = [c for c in x if c not in ('decision_id', 'order_id', 'fill_id', 'cycle_id')]
            pd.testing.assert_frame_equal(x[selected].reset_index(drop=True),
                                          y[selected].reset_index(drop=True),
                                          check_exact=True, check_dtype=True)
            columns[table] = {'rows': len(x), 'exact_columns': selected,
                              'adaptive_additional_columns': sorted(set(y) - set(x))}
        pd.testing.assert_frame_equal(a.runs[0].buyhold.account_daily,
                                      b.runs[0].buyhold.account_daily, check_exact=True)
        for key in ('net_cagr', 'closed_trades', 'total_fees', 'annual', 'buyhold_annual', 'gates'):
            assert left[key] == right[key], (item['label'], key)
        checks.append({'label': item['label'], 'status': 'PASS',
                       'original': {k: left[k] for k in ('candidate_id', 'content_sha256', 'request_hash', 'result_hash')},
                       'adaptive': {k: right[k] for k in ('candidate_id', 'content_sha256', 'request_hash', 'result_hash')},
                       'tables': columns})
    value = {'status': 'PASS', 'checks': checks,
             'comparison': 'FULL账户五表全部原非ID字段与基准逐项精确相等；新增状态诊断单列。独立候选身份及原始结果哈希保留；此项为研究同路线控制，不宣称SE全证据ECONOMIC等价。'}
    save('adaptive_controls_20261008.json', value)
    ref = publish_evidence(context(4), MaterialEvidenceWrite(ExperimentRef('S013', 'EX004_20261007'),
        'four-gate-adaptive-controls', (WORK / 'adaptive_controls_20261008.json').read_bytes(),
        'application/json', 'json'))
    save('adaptive_controls_reference_20261008.json', ref.to_dict())
    print(json.dumps({'status': value['status'], 'reference': ref.to_dict()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
