"""Describe retained continuous accounts; no replay or extra acceptance gates."""
import numpy as np

from stage4 import CACHE, OUT, read, save
from strategy_evaluator import research_models as m


def main():
    previous = read(OUT / 'temporal_diagnostics.json') if (OUT / 'temporal_diagnostics.json').exists() else None
    request = m.CandidateAssessmentRequest.from_dict(read(CACHE / 'nonparameter_request.json'))
    assert request.sha256 == read(OUT / 'nonparameter_summary.json')['source_request_sha256']
    panel = m.AssessmentPanel.from_dict(read(OUT / 'nonparameter_panel.json'))
    byid = {r.candidate: r for r in panel.rows}
    result = []
    for candidate in request.centers:
        account, = [x for x in request.evidence if x.candidate == candidate and x.scenario_id == 'standard']
        dates = [x.session for x in account.account]
        equity = np.r_[account.initial_cash, [x.equity for x in account.account]]
        benchmark = np.r_[account.initial_cash, account.benchmark_equity]
        assert len(equity) == len(benchmark) == 435
        def drawdown(values):
            return float(np.max(1 - values / np.maximum.accumulate(values)))
        years = []
        for year in sorted({x[:4] for x in dates}):
            ix = [i for i, day in enumerate(dates) if day.startswith(year)]
            start, end = ix[0], ix[-1] + 1
            years.append({'year': year, 'sessions': len(ix), 'start': dates[start], 'end': dates[end - 1],
                          'partial_year': year == '2026',
                          'net_return': float(equity[end] / equity[start] - 1),
                          'benchmark_net_return': float(benchmark[end] / benchmark[start] - 1),
                          'drawdown': drawdown(equity[start:end + 1]),
                          'benchmark_drawdown': drawdown(benchmark[start:end + 1]),
                          'net_yuan': float(equity[end] - equity[start])})
        rolling = []
        for start in range(0, len(dates) - 252 + 1, 21):
            end = start + 252
            ret, bh = equity[end] / equity[start] - 1, benchmark[end] / benchmark[start] - 1
            rolling.append({'start': dates[start], 'end': dates[end - 1],
                            'net_return': float(ret), 'benchmark_net_return': float(bh),
                            'drawdown': drawdown(equity[start:end + 1]),
                            'benchmark_drawdown': drawdown(benchmark[start:end + 1]),
                            'excess': float(ret - bh)})
        expected = next(x.value for x in byid[candidate].diagnostics
                        if x.metric is m.ResearchMetric.ROLLING_EXCESS_Q10)
        assert abs(float(np.quantile([x['excess'] for x in rolling], .1)) - expected) < 1e-12
        longest = current = 0
        below = equity[1:] < benchmark[1:]
        for flag in below:
            current = current + 1 if flag else 0
            longest = max(longest, current)
        result.append({'candidate_id': candidate.candidate_id.removeprefix('S015-'),
                       'evaluation_id': account.evaluation_id, 'years': years,
                       'rolling252_step21': rolling, 'rolling_count': len(rolling),
                       'rolling_wins': sum(x['excess'] > 0 for x in rolling),
                       'wealth_below_buyhold_sessions': int(np.sum(below)),
                       'longest_wealth_below_buyhold_sessions': longest})
    if previous is not None:
        # Add window risk to the unpublished descriptive checkpoint without
        # changing any previously computed return, membership or timing fact.
        for old, new in zip(previous['rows'], result, strict=True):
            for key, value in old.items():
                if key in ('years', 'rolling252_step21'):
                    assert all(all(b[k] == v for k, v in a.items())
                               for a, b in zip(value, new[key], strict=True))
                else:
                    assert new[key] == value
    save(OUT / 'temporal_diagnostics.json', {
        'status': 'DESCRIPTIVE_CHECKS_PASS', 'source_request_sha256': request.sha256,
        'new_accounts': 0, 'rows': result,
        'definitions': {'years': 'Continuous account carryover; yearly return starts at prior session equity; 2026 ends October 21.',
                        'rolling': '252-session inherited slices every21 sessions, 9 per candidate; not daily-start exhaustive windows.',
                        'drawdown': 'Drawdown within each slice includes the preceding session equity as its initial peak; actual account holdings and cash carry over.',
                        'underperformance': 'Strategy wealth strictly below same-cost buyhold wealth since the shared 100000 start; equality ends a run.'},
        'limitations': ['No new independent samples, new hard gates or account replays.',
                        'Window overlap and repeated development remain; slicing does not reset holdings or capital.']})
    print('TEMPORAL_DIAGNOSTICS_PASS', len(result), flush=True)


if __name__ == '__main__':
    main()
