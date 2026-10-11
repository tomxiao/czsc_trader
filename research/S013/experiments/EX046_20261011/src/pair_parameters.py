"""Three exact-coordinate original/coupled/segment context complete-account contrasts."""
from statistics import mean
from common import RUNS,read,write
from run_parameters import source_check


def pair_analysis(analysis):
    if analysis['status'] == 'NOT_APPLICABLE':
        return {'status': 'NOT_APPLICABLE', 'reason': analysis['reason'], 'comparisons': {}}
    assert analysis['status'] == 'PASS' and set(analysis['points']) == {'B0-TIME', 'B0-COUPLED', 'N0'}
    assert analysis['summaries']['N0']['center_qualified']
    comparisons = {
        'N0': contrast(analysis, 'B0-TIME', 'N0', 'Segment context versus original; identical13 coordinates, includes ACF/gate structural differences'),
        'N0-vs-B0-COUPLED': contrast(analysis, 'B0-COUPLED', 'N0', 'Rawbull category expiry versus persistent context; same actual-L MEAN/score, all numeric coordinates and original holding exits preserved'),
        'B0-COUPLED': contrast(analysis, 'B0-TIME', 'B0-COUPLED', 'Exact old native controls, no new evaluation; existing coupled versus original contrast'),
    }
    return {'status': 'PASS', 'comparisons': comparisons,
        'scope': 'Three complete32 cohorts, original13 common domains/numeric centers/5%L2/seed13 coordinates. Native reused identities and bindings preserved. Segment context and BELOW direction scope are categorical structures; shared-coordinate comparison does not certify their general stability.',
        'eligibility': 'Only original-four-gate-qualified newN0 receives32 new complete accounts. Both controls strictly reused; all point gates diagnostic, no additional economic veto.'}



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
    source_check()
    output=pair_analysis(read(RUNS/'parameter_analysis.json'))
    write(RUNS/'parameter_pairs.json',output)
    print({'paired_centers':list(output['comparisons']),'status':output['status']})


if __name__=='__main__':
    main()
