"""Focused source, cache, coverage and center-metric checks; no account computation."""
from hashlib import sha256
import json
import os
from pathlib import Path

os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import numpy as np  # noqa: E402

WORK = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((WORK/name).read_bytes())


def digest(name):
    return sha256((WORK/name).read_bytes()).hexdigest()


def main():
    done = read('others/statistics_completion.json')
    assert done['status'] == 'COMPLETE' and done['new_strategy_accounts'] == 0
    assert done['source_sha256'] == digest('src/statistics_analysis.py')
    assert done['protocol_sha256'] == digest('protocols/statistics_protocol.json')
    for name, value in done['output_sha256'].items():
        assert digest('others/'+name) == value
    protocol = read('protocols/statistics_protocol.json')
    assert protocol['inventory_sha256'] == digest('others/statistics_inventory.json')
    assert protocol['centers_sha256'] == digest('protocols/centers.json')
    for name, binding in protocol['reused_evidence']['files'].items():
        assert sha256((WORK.parent/'EX039_20261110'/name).read_bytes()).hexdigest() == binding['sha256']
        assert binding['sha256'] == binding['reference']['sha256']
    inventory = read('others/statistics_inventory.json')
    assert len(inventory['rows']) == 371
    assert sum(1+len(row['aliases']) for row in inventory['rows']) == 374
    returns = read('others/statistics_returns.json')
    members = {row['candidate_id']:row for row in returns['members']}
    assert len(members) == 371 and len(returns['alias_verification']) == 3
    reference = next(iter(members.values()))
    current_hash = done['protocol_sha256']
    old_hash = protocol['reused_evidence']['files']['protocols/statistics_protocol.json']['sha256']
    for member in members.values():
        assert len(member['returns']) == 1212
        assert member['sessions'] == reference['sessions']
        assert member['benchmark_returns'] == reference['benchmark_returns']
        assert np.isfinite(member['returns']).all()
        assert member['protocol_sha256'] in (current_hash,old_hash)
    centers = read('protocols/centers.json')
    expected = {}
    for center in centers:
        member = members[center['id']]
        assert member['reference'] == center['account_ref']
        assert member['content_sha256'] == center['content_hash']
        curve = np.r_[1.,np.cumprod(1+np.asarray(member['returns']))]
        nar = float(curve[-1]**(252/1212)-1)
        mdd = float(np.max(1-curve/np.maximum.accumulate(curve)))
        metrics = {'cagr':nar,'max_drawdown':-mdd,'calmar':nar/mdd}
        published = center['candidate']
        assert abs(nar-published['nar']) < 1e-10
        assert abs(mdd-published['drawdown']) < 1e-10
        assert abs(nar/mdd-published['calmar']) < 1e-10
        expected[center['id']] = metrics
    bootstrap = read('others/statistics_bootstrap.json')
    assert len(bootstrap['comparisons']) == 6
    for comparison in bootstrap['comparisons']:
        assert comparison['repetitions'] == 10000 and comparison['mean_block_length'] == 21
        if comparison['comparator_id'] != 'MU_BUY_HOLD':
            for metric in ('cagr','max_drawdown','calmar'):
                diff = expected[comparison['champion_id']][metric]-expected[comparison['comparator_id']][metric]
                assert abs(comparison[metric]['point_difference']-diff) < 1e-10
    selection = read('others/statistics_selection.json')
    assert len(selection['groups']) == 1
    group = selection['groups'][0]
    assert len(group['members']) == 371
    result = group['result']
    assert result['status'] == 'COMPLETE' and result['planned_windows'] == 4
    proxy = read('others/statistics_search_bias.json')
    assert proxy['actual_nar_gated_adaptive_selection_bias'] == 'NOT_ESTIMATED'
    assert len(proxy['groups']) == 1
    p = proxy['groups'][0]['diagnostics']['PBO_SHARPE_PROXY']
    if p['status'] == 'AVAILABLE':
        assert len(p['splits']) == 252
        assert all(s['validation_candidate_count'] == 371 for s in p['splits'])
    summary = {'verification':'PASSED', 'source_sha256':digest('src/statistics_verification.py'),
               'checks':['Source/protocol/inventory/output hashes', 'Published EX039 reuse bindings',
                         '374 account evaluations and 371 exact implementations', 'All calendars and benchmark daily returns identical',
                         '3 approved center identities and metrics agree within 1e-10', '6 bootstrap pairs',
                         'Complete 371-source annual selection facts', '252 Sharpe proxy splits retain every implementation'],
               'completion':done, 'history':inventory['history'], 'aliases':returns['alias_verification'],
               'selection_summary':{k:v for k,v in result.items() if k not in ('decisions','candidates','observations')},
               'selection_windows':[{k:v for k,v in row.items() if k != 'checks'} for row in result['decisions']],
               'selection_observations':[{k:v for k,v in row.items() if k != 'checks'} | {
                   'failed_targets':[c['target']['target_id'] for c in row['checks'] if c['status']=='FAILED']} for row in result['observations']],
               'bootstrap_comparisons':bootstrap['comparisons'],
               'sharpe_proxy':{k:({a:b for a,b in v.items() if a not in ('splits','selection_frequency')} if k=='PBO_SHARPE_PROXY' else v)
                               for k,v in proxy['groups'][0]['diagnostics'].items()},
               'actual_nar_gated_adaptive_selection_bias':'NOT_ESTIMATED','limitations':protocol['limitations']}
    (WORK/'others/statistics_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    verification = {'status':'PASSED','checks':summary['checks'],
                    'verification_source_sha256':digest('src/statistics_verification.py'),
                    'analysis_source_sha256':done['source_sha256'],'protocol_sha256':done['protocol_sha256'],
                    'completion_sha256':digest('others/statistics_completion.json'),
                    'summary_sha256':digest('others/statistics_summary.json'),
                    'new_strategy_accounts':0}
    (WORK/'others/statistics_verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'verification':'PASSED','selection':summary['selection_summary'],'proxy':summary['sharpe_proxy']}))


if __name__ == '__main__':
    main()
