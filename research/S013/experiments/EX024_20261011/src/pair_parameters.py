"""Complete identical-coordinate majority versus original TIME contrasts."""
from statistics import mean
from common import RUNS,read,write


def pair_analysis(analysis):
    if analysis['status']=='NOT_APPLICABLE':
        return {'status':'NOT_APPLICABLE','reason':analysis['reason'],'comparisons':{}}
    assert analysis['status']=='PASS'
    labels=set(analysis['points'])
    selected = [label for label in ('N0', 'N1') if label in labels]
    if not selected:
        return {'status':'NOT_APPLICABLE','reason':'NO_COMPLETE_NEW_MAJORITY_CENTER',
                'comparisons':{},'available_centers':sorted(labels)}
    comparisons = {label: contrast(analysis, {'N0': 'B0-TIME', 'N1': 'B2-TIME'}[label], label)
                   for label in selected}
    return {'status':'PASS','comparisons':comparisons,
        'scope':'Each new qualified majority center against its own original TIME 32-point set: N0/B0 at bear H4, N1/B2 at bear H3. All 13 numeric coordinates exactly equal within each pair; fixed majority mechanism differs. Descriptive, non-independent S013 development evidence.',
        'original_comparison':'B0 is the overall baseline. Never pair N1/B0 as identical coordinates across bear H3/H4.',
        'eligibility':'Original unqualified B2 control remains diagnostic; no parameter metric creates an economic gate or promotes a control.'}


def contrast(analysis, reference, label):
    assert reference in analysis['points'], (label, reference)
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
    contrast={'control':reference,'control_role':first['role'],'control_center_qualified':first['center_qualified'],
        'new_center_qualified': second['center_qualified'],
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
    return contrast


def main():
    output=pair_analysis(read(RUNS/'parameter_analysis.json'))
    write(RUNS/'parameter_pairs.json',output)
    print({'paired_centers':list(output['comparisons']),'status':output['status']})


if __name__=='__main__':
    main()
