"""Complete identical-coordinate reference contrasts against H4/H3 original controls."""
from statistics import mean
from common import RUNS,PROTOCOLS,read,write


def main():
    analysis=read(RUNS/'parameter_analysis.json')
    assert analysis['status']=='PASS'
    plan=read(PROTOCOLS/'plan.json')
    centers=read(RUNS/'analysis.json')['rows']
    contrasts={}
    for cfg in plan['configurations']:
        if not centers[cfg['label']]['qualified']:
            continue
        label=cfg['label']
        reference='B0-TIME' if cfg['background']=='B0' else 'B2-TIME'
        old=sorted(analysis['points'][reference],key=lambda row:row['point_index'])
        new=sorted(analysis['points'][label],key=lambda row:row['point_index'])
        assert len(old)==len(new)==32
        rows=[]
        for first,second in zip(old,new,strict=True):
            assert first['coordinates']==second['coordinates'] and first['point_index']==second['point_index']
            assert first['actual_radius']==second['actual_radius']
            rows.append({'point_index':first['point_index'],'cagr_difference':second['net_cagr']-first['net_cagr'],
                'drawdown_difference':second['drawdown']-first['drawdown'],
                'y2022_difference':second['annual']['2022']['return']-first['annual']['2022']['return'],
                'y2023_difference':second['annual']['2023']['return']-first['annual']['2023']['return'],
                'closed_difference':second['closed_trades']-first['closed_trades'],
                'original_qualified':first['qualified'],'new_qualified':second['qualified']})
        first,second=analysis['summaries'][reference],analysis['summaries'][label]
        contrasts[label]={'control':reference,'complete_pairs':32,'pairs':rows,
            'cagr_better_points':sum(row['cagr_difference']>0 for row in rows),
            'cagr_worse_points':sum(row['cagr_difference']<0 for row in rows),
            'drawdown_better_points':sum(row['drawdown_difference']<0 for row in rows),
            'drawdown_worse_points':sum(row['drawdown_difference']>0 for row in rows),
            'mean_cagr_difference':mean(row['cagr_difference'] for row in rows),
            'mean_drawdown_difference':mean(row['drawdown_difference'] for row in rows),
            'q10_cagr_difference':second['q10_cagr']-first['q10_cagr'],
            'q90_drawdown_difference':second['q90_drawdown']-first['q90_drawdown'],
            'return_degradation_difference':second['return_degradation']-first['return_degradation'],
            'drawdown_degradation_difference':second['drawdown_degradation']-first['drawdown_degradation']}
    write(RUNS/'parameter_pairs.json',{'status':'PASS','comparisons':contrasts,
        'scope':'All exact-coordinate pairs, differing only fixed regime reference implementation; descriptive and non-independent.'})
    print({'paired_centers':list(contrasts),'status':'PASS'})


if __name__=='__main__':
    main()
