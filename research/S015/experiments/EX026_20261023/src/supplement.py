"""Complete prespecified temporal controls and opportunity density, no new labels."""
import numpy as np
import pandas as pd
from study import HERE, HORIZONS, SEGMENTS, save, stats


def maximum_nonoverlap(intervals):
    """Earliest-finish interval scheduling, allowing same-day exit and entry."""
    last, count = -1, 0
    for end, start in sorted(intervals):
        if start >= last:
            count += 1
            last = end
    return count


def main():
    e = pd.read_csv(HERE/'others/events.csv', float_precision='round_trip')
    dates = list(e[e.horizon.eq(1)].date)
    date_position = {day:i for i,day in enumerate(dates)}
    out = {'scope':'Prespecified existing-label summaries only; no new hypothesis, account or execution.', 'horizons':{}}
    compact = []
    for h in HORIZONS:
        g = e[e.horizon.eq(h)]
        closed = g[g.status.eq('CLOSED')]
        periods = {}
        for left,right in SEGMENTS:
            z = closed[closed.position.ge(left)&closed.position.lt(right)]
            periods[f'{left}:{right}'] = {'all':stats(z),
                'groups':{k:{'in':stats(z[z[k]]),'out':stats(z[~z[k]])} for k in ('A','B','C')},
                'B_increment':{'B':stats(z[z.B]),'A_not_B':stats(z[z.A & ~z.B])},
                'C_pressure_cells':{p:{f'C{int(c)}_P{int(v)}':stats(z[z.C.eq(c)&z[p].eq(v)])
                    for c in (False,True) for v in (False,True)} for p in ('P','P25')}}
        density = {}
        for k in ('A','B','C'):
            counts = closed[closed[k]].groupby('actual_exit_date').size().reindex(dates,fill_value=0)
            rolling = counts.rolling(60).sum().dropna()
            assert len(rolling) == 375
            intervals = [(date_position[r.actual_exit_date],date_position[r.entry_date]) for r in closed[closed[k]].itertuples()]
            bounds = [maximum_nonoverlap([(finish,start) for finish,start in intervals if end-59 <= finish <= end]) for end in range(59,434)]
            # Unrealistically allow all overlapping events as independent trades.
            # This is an optimistic count bound only for this fixed-event policy.
            density[k] = {'signal_n':int(g[k].sum()),'closed_n':int(closed[k].sum()),
                'signal_60_median':float(g[k].astype(int).rolling(60).sum().dropna().median()),
                'all_overlapping_events_closed_60_median':float(rolling.median()),
                'all_overlapping_events_closed_windows_at_least3':int((rolling>=3).sum()),
                'nonoverlap_optimistic_60_median_upper_bound':float(np.median(bounds)),
                'nonoverlap_optimistic_windows_at_least3_upper_bound':int(sum(v>=3 for v in bounds)),
                'nonoverlap_optimistic_rolling_upper_bounds':bounds,
                'windows':375,'interpretation':'Event counts with all overlapping events accepted; not actual account frequency. Upper bound for a one-buy-one-sell subset of these exact fixed-horizon events only.'}
            y = closed[closed[k]].net
            compact.append({'condition':k,'horizon':h,'n':len(y),'mean_return':float(y.mean()/100000),
                'positive_yuan':float(y[y>0].sum()),'negative_yuan':float(-y[y<0].sum()),
                'net_yuan':float(y.sum()),**density[k]})
        out['horizons'][str(h)] = {'periods':periods,'density':density}
    save(HERE/'others/supplement.json',out)
    pd.DataFrame(compact).to_csv(HERE/'others/comparison_summary.csv',index=False)
    print(pd.DataFrame(compact)[['condition','horizon','n','mean_return','all_overlapping_events_closed_60_median','all_overlapping_events_closed_windows_at_least3']].to_string(index=False),flush=True)
    for h,z in out['horizons'].items():
        print('B_periods',h,[(k,v['B_increment']['B'].get('net_mean_return'),v['B_increment']['A_not_B'].get('net_mean_return')) for k,v in z['periods'].items()],flush=True)


if __name__ == '__main__':
    main()
