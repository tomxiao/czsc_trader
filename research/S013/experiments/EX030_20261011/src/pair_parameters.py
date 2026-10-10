"""Complete same-coordinate fixed bull-only raw-regime exit-confirmation contrasts."""
from statistics import mean
from common import RUNS,read,write


def pair_analysis(analysis):
    if analysis['status']=='NOT_APPLICABLE':
        return {'status':'NOT_APPLICABLE','reason':analysis['reason'],'comparisons':{}}
    assert analysis['status']=='PASS'
    labels=set(analysis['points'])
    assert labels == {'B0-TIME','N0','N1'}, 'EX030 requires both complete symmetric exit-confirmation panels'
    contrasts = (
        ('N0','B0-TIME','N0','bull-only consecutive3 raw-bear regime-exit confirmation minus original TIME'),
        ('N1','B0-TIME','N1','bull-only two-of-last3 raw-bear regime-exit confirmation minus original TIME'),
        ('N1-vs-N0','N0','N1','two-of-last3 minus consecutive3; current raw entry regime and other exits fixed'))
    comparisons={key:contrast(analysis,reference,label,purpose) for key,reference,label,purpose in contrasts}
    return {'status':'PASS','comparisons':comparisons,
        'scope':'All three complete32-point contrasts share exact13 coordinates at original bull H8/bear H4. N0/B0 and N1/B0 isolate bull-only regime-exit confirmation; N1/N0 isolates two-of-last3 versus consecutive3. Original raw entry regime/ACF/confirmation, bear exits and TIME/RANGE priority unchanged. Old two-day/full-route-majority controls are center-only. Descriptive, non-independent S013 development evidence.',
        'eligibility':'An unqualified consecutive3 or two-of-last3 center is a predeclared symmetric diagnostic when the other qualifies. Four original economic gates unchanged; no parameter metric adds a veto or registers/promotes a diagnostic.'}


def contrast(analysis,reference,label,purpose):
    assert reference in analysis['points'], (label,reference)
    old=sorted(analysis['points'][reference],key=lambda row:row['point_index'])
    new=sorted(analysis['points'][label],key=lambda row:row['point_index'])
    assert len(old)==len(new)==32
    assert [row['point_index'] for row in old]==[row['point_index'] for row in new]==list(range(32))
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
    result={'control':reference,'new_center':label,'purpose':purpose,
        'control_role':first['role'],'control_center_qualified':first['center_qualified'],
        'new_center_qualified':second['center_qualified'],
        'complete_pairs':32,'pairs':rows,
        'cagr_better_points':sum(row['cagr_difference']>0 for row in rows),
        'cagr_worse_points':sum(row['cagr_difference']<0 for row in rows),
        'cagr_same_points':sum(row['cagr_difference']==0 for row in rows),
        'drawdown_better_points':sum(row['drawdown_difference']<0 for row in rows),
        'drawdown_worse_points':sum(row['drawdown_difference']>0 for row in rows),
        'drawdown_same_points':sum(row['drawdown_difference']==0 for row in rows),
        'mean_cagr_difference':mean(row['cagr_difference'] for row in rows),
        'mean_drawdown_difference':mean(row['drawdown_difference'] for row in rows),
        'q10_cagr_difference':second['q10_cagr']-first['q10_cagr'],
        'q90_drawdown_difference':second['q90_drawdown']-first['q90_drawdown'],
        'return_degradation_difference':second['return_degradation']-first['return_degradation'],
        'drawdown_degradation_difference':second['drawdown_degradation']-first['drawdown_degradation']}
    return result


def main():
    output=pair_analysis(read(RUNS/'parameter_analysis.json'))
    write(RUNS/'parameter_pairs.json',output)
    print({'paired_centers':list(output['comparisons']),'status':output['status']})


if __name__=='__main__':
    main()
