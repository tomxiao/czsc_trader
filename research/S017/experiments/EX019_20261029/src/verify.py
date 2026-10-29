"""Reconcile diagnostic totals and original executed entries without new accounts."""
from collections import Counter
import gzip
import json
from math import fsum, isclose
from study import ROOT, WORK, OLD, read, save, digest, EvidenceRef


def main():
    analysis = read(WORK/'others/analysis.json')
    rows = json.loads(gzip.decompress((WORK/'others/events.json.gz').read_bytes()))
    assert digest(WORK/'others/events.json.gz') == analysis['events_sha256']
    checks = []
    for n in (3,13,26):
        subset = [r for r in rows if r['n']==n]
        assert len(subset)==analysis['eligible'] and len({r['i'] for r in subset})==len(subset)
        for name,pop in [('all',subset),('pat',[r for r in subset if r['signal']]),
                         ('nonoverlap_pat',[r for r in subset if r['nonoverlap']])]:
            saved = analysis['horizons'][str(n)][name]
            assert dict(Counter(r['status'] for r in pop))==saved['status']
            complete = [r['price_net_return'] for r in pop if r['price_net_return'] is not None]
            assert len(complete)==saved['price']['count']
            if complete:
                assert isclose(fsum(complete)/len(complete),saved['price']['mean'],abs_tol=1e-14)
                assert isclose(sum(v>0 for v in complete)/len(complete),saved['price']['win_rate'],abs_tol=1e-14)
            for r in pop:
                if r['status']=='COMPLETE':
                    expected = (r['exit_price']-r['entry_price']-.001*(r['entry_price']+r['exit_price']))/(r['entry_price']*1.001)
                    assert isclose(expected,r['price_net_return'],abs_tol=1e-14)
                else:
                    assert r['price_net_return'] is None
            selected = sorted(r['i'] for r in pop)
            if name=='nonoverlap_pat':
                assert all(b>a+n+1 for a,b in zip(selected,selected[1:]))
        for name, flag in [('matched_pat','signal'),('matched_nonoverlap_pat','nonoverlap')]:
            complete = [r for r in subset if r[flag] and r['price_net_return'] is not None]
            differences = []
            for r in complete:
                control = [x['price_net_return'] for x in subset
                    if x['stratum']==r['stratum'] and x['price_net_return'] is not None]
                differences.append(r['price_net_return']-fsum(control)/len(control))
            if differences:
                assert isclose(fsum(differences)/len(differences),
                    analysis['horizons'][str(n)][name]['difference']['mean'],abs_tol=1e-14)
            else:
                assert analysis['horizons'][str(n)][name]['difference']['count']==0
        checks.append('horizon_'+str(n)+'_counts_net_formula_nonoverlap_matched_denominators')
    manifest = read(OLD/'others/accounts.json')['C0047']
    ref = EvidenceRef.from_dict(manifest['evidence'])
    path = ref.resolve(ROOT)
    payload = read(path)
    assert digest(path)==ref.sha256 and payload['evaluation_id']==manifest['evaluation_id']
    assert payload['request']['data_manifest']==analysis['prepared']['manifest_sha256']
    account = payload['runs']['candidate']
    events = {r['signal_at']:r for r in rows if r['n']==13}
    # Timestamp textual representations can differ by Z versus +00:00.
    from datetime import datetime
    def at(s):
        return datetime.fromisoformat(s.replace('Z','+00:00'))
    events = {at(k):v for k,v in events.items()}
    decisions = {r['decision_id']:r for r in account['decisions']}
    orders = {r['order_id']:r for r in account['orders']}
    flats = 0
    for d in decisions.values():
        facts = {r['key']:r['text'] for r in d['explanation']['basis']}
        if facts['held']=='False':
            event = events[at(d['observed_through'])]
            assert bool(d['target'])==event['signal']
            flats += 1
    buys = 0
    for fill in account['fills']:
        if fill['side']=='BUY':
            d = decisions[orders[fill['order_id']]['decision_id']]
            event = events[at(d['observed_through'])]
            assert event['signal'] and isclose(fill['price'],event['entry_price'],abs_tol=1e-12)
            assert at(fill['interval_start'])==at(event['entry_at'])
            buys += 1
    assert flats>0 and buys>0
    checks.append('original_C47_all_flat_decisions_and_executed_buy_prices_match')
    save(WORK/'others/result_validation.json', {'status':'PASS', 'checks':checks,
        'analysis_sha256':digest(WORK/'others/analysis.json'),
        'events_sha256':digest(WORK/'others/events.json.gz'),
        'verification_source_sha256':digest(WORK/'src/verify.py'),
        'original_account':ref.to_dict(), 'original_flat_decisions_matched':flats,
        'original_actual_buys_matched':buys, 'new_account_replays':0})
    print('RESULT VALIDATION PASS',flats,'flat decisions,',buys,'actual buys',flush=True)


if __name__=='__main__':
    main()
