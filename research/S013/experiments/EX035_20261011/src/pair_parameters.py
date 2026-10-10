"""Complete original-coordinate bear TIME-exit eligibility-refresh contrast."""
from statistics import mean
from common import RUNS,read,write


def pair_analysis(analysis):
    if analysis['status']=='NOT_APPLICABLE':
        return {'status':'NOT_APPLICABLE','reason':analysis['reason'],'comparisons':{}}
    assert analysis['status']=='PASS'
    assert set(analysis['points']) == {'B0-TIME','N0'}, 'EX035 requires original32 and qualified N0 complete32'
    assert analysis['summaries']['N0']['center_qualified']
    comparisons={'N0':contrast(analysis,'B0-TIME','N0',
        'bear TIME-exit entry-refresh structure minus original TIME at identical13 numeric coordinates/physical units')}
    return {'status':'PASS','comparisons':comparisons,
        'scope':'One complete32-point contrast shares all13 original full domains/numeric centers/point coordinates and physical units. Pending set remains EX034 exact active-bear/final-TIME/raw-bear/range<=entry. Only flat release expands to enabled original bear ACF/momentum strictly below thresholds, alongside old raw-route/range release; equality retains pending, confirmation score excluded. Equal numeric pairing does not remove shared entry/release threshold roles. Old range-refresh stays center-only without old parameters. Original opportunity/score/entry-age0/H units and exit priorities unchanged. Descriptive, non-independent S013 development evidence.',
        'eligibility':'Only qualified N0 receives parameters; no unqualified center is promoted or registered. Four original economic gates unchanged; parameter diagnostics add no veto.'}


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
