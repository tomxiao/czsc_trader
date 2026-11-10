"""Explain final eligible leaders using existing account paths; zero new replays."""
import json
from hashlib import sha256
from pathlib import Path

from prior_diagnostics import ROOT, WORK, analyze, compare


def main():
    qualified = json.loads((WORK / 'others/qualified_candidates.json').read_bytes())
    prior = json.loads((WORK / 'others/prior_diagnostics.json').read_bytes())
    baseline = prior['accounts']['C0300']
    leaders = {r['id']: r for r in (qualified[0], max(qualified, key=lambda r: r['candidate']['calmar']))}
    scratch = ROOT / '.tmp/s019-stage3-final'
    scratch.mkdir(parents=True, exist_ok=True)
    accounts, comparisons = {}, {}
    for cid, row in leaders.items():
        path = scratch / f'{cid}.json'
        path.write_text(json.dumps(row['account']), encoding='utf-8')
        result = analyze(path, row['parameters'])
        assert result['reference'] == row['account']
        for key in ('nar', 'drawdown', 'calmar', 'frequency_median', 'frequency_coverage'):
            assert result['metrics'][key] == row['candidate'][key], (cid, key)
        accounts[cid] = result
        # An unchanged baseline would have a zero denominator in the descriptive concentration statistic.
        if result['daily_returns'] == baseline['daily_returns']:
            comparisons[cid] = {'identical_daily_path': True}
        else:
            comparisons[cid] = compare(result, baseline)
        print('FINAL_PATH_READ', cid, flush=True)
    out = {'status': 'COMPLETE', 'new_accounts': 0,
           'source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
           'analysis_source_sha256': sha256((WORK / 'src/prior_diagnostics.py').read_bytes()).hexdigest(),
           'qualified_sha256': sha256((WORK / 'others/qualified_candidates.json').read_bytes()).hexdigest(),
           'prior_diagnostics_sha256': sha256((WORK / 'others/prior_diagnostics.json').read_bytes()).hexdigest(),
           'baseline': 'C0300', 'accounts': accounts, 'comparisons': comparisons,
           'limitations': prior['limitations']}
    (WORK / 'others/final_diagnostics.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({cid: {'metrics': a['metrics'], 'mdd': a['mdd_episode'],
                           'yearly': a['yearly'],
                           'comparison': {k: v for k, v in comparisons[cid].items()
                                          if k not in ('changed_exits', 'largest_cycle_contribution_deltas',
                                                       'left_only_entries', 'right_only_entries',
                                                       'largest_daily_log_differences')}}
                      for cid, a in accounts.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
