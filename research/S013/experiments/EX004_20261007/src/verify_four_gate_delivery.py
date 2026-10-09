"""Independent final recomputation from authenticated public account evidence."""
import json
import math
import pandas as pd
from czsc_trader.application import validate_delivery
from czsc_trader.research_tools import delivery as d
from common import ROOT, RUNS, context, save
from economics import annual_stats


def main():
    path = ROOT / 'research/S013/assets/deliveries/CANDIDATES/3/delivery.json'
    content = d.DeliveryContent.from_dict(json.loads(path.read_text(encoding='utf-8'))['content'])
    reference = d.DeliveryReference.from_dict(json.loads((RUNS / 'stage3_r3_reference.json').read_text(encoding='utf-8')))
    checked = validate_delivery(context(4).repository, reference)
    assert checked.status == d.ValidationStatus.PASS
    source = next(e for e in content.evidence if e.name == 'four-gate-search-results')
    rows = json.loads(source.resolve(ROOT).read_text(encoding='utf-8'))['rows']
    by_id = {r['candidate_id']: r for r in rows if r['status'] == 'SUCCEEDED'}
    actual_qualified = {r['candidate_id'] for r in by_id.values() if r['qualified']}
    assert actual_qualified == {c.candidate_id for c in content.payload.handoff}
    checks = []
    for entry in content.payload.candidates:
        c = entry.identity.key.candidate_id
        value = json.loads(entry.evaluations[0].evidence.resolve(ROOT).read_text(encoding='utf-8'))
        run = value['runs'][0]
        own = pd.DataFrame(run['ledgers']['account_daily']['data'])
        bh = pd.DataFrame(run['buyhold']['account_daily']['data'])
        trades = pd.DataFrame(run['ledgers']['trades']['data'])
        initial = value['request_identity']['initial_cash']
        annual, base = annual_stats(own, initial), annual_stats(bh, initial)
        cagr = (own.equity.iloc[-1] / initial) ** (252 / len(own)) - 1
        bcagr = (bh.equity.iloc[-1] / initial) ** (252 / len(bh)) - 1
        closed = int(trades.status.eq('CLOSED').sum())
        gates = {'return': bool(cagr >= 1.5 * bcagr),
                 'annual_drawdown': all(annual[y]['max_drawdown_magnitude'] < base[y]['max_drawdown_magnitude'] for y in annual),
                 'frequency': closed * 60 / len(own) >= 4,
                 'negative_buyhold_year_profit': all(annual[y]['return'] > 0 for y in annual if base[y]['return'] < 0)}
        assert gates == by_id[c]['gates'] and closed == by_id[c]['closed_trades']
        assert math.isclose(cagr, by_id[c]['net_cagr'], rel_tol=0, abs_tol=1e-12)
        for y in annual:
            for key in ('return', 'max_drawdown_magnitude'):
                assert math.isclose(annual[y][key], by_id[c]['annual'][y][key], rel_tol=0, abs_tol=1e-12)
        assert run['identity']['content_sha256'] == entry.identity.content_sha256 == by_id[c]['content_sha256']
        assert value['result_hash'] == by_id[c]['result_hash']
        checks.append({'candidate_id': c, 'gates': gates, 'qualified': all(gates.values()),
                       'matches_search_and_identity': True, 'account_evidence': entry.evaluations[0].evidence.to_dict()})
    assert {c['candidate_id'] for c in checks if c['qualified']} == actual_qualified
    value = {'status': 'PASS', 'delivery': reference.to_dict(), 'full_validation': checked.to_dict(),
             'retained_public_ledger_recomputations': checks, 'qualified_ids': sorted(actual_qualified)}
    save('four_gate_final_verification.json', value)
    print(json.dumps({'status': 'PASS', 'qualified': len(actual_qualified), 'retained': len(checks)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
