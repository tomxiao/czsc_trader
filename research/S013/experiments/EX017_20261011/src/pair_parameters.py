"""Exact-coordinate paired mechanism evidence versus the unqualified original H3 control."""
from statistics import mean
from common import RUNS,read,write


def main():
    a=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS'
    old=sorted(a['points']['B2-TIME'],key=lambda row:row['point_index'])
    new=sorted(a['points']['N2'],key=lambda row:row['point_index'])
    assert len(old)==len(new)==32
    pairs=[]
    for first,second in zip(old,new,strict=True):
        assert first['point_index']==second['point_index'] and first['coordinates']==second['coordinates']
        assert first['actual_radius']==second['actual_radius']
        pairs.append({'point':first['point_index'],'same_numeric_coordinates':True,
            'cagr_difference':second['net_cagr']-first['net_cagr'],
            'drawdown_difference':second['drawdown']-first['drawdown'],
            'closed_difference':second['closed_trades']-first['closed_trades'],
            'y2022_difference':second['annual']['2022']['return']-first['annual']['2022']['return'],
            'y2023_difference':second['annual']['2023']['return']-first['annual']['2023']['return'],
            'original_qualified':first['qualified'],'new_qualified':second['qualified']})
    first,second=a['summaries']['B2-TIME'],a['summaries']['N2']
    metrics=('q10_cagr','q90_drawdown','return_degradation','drawdown_degradation')
    output={'status':'PASS','complete_same_coordinate_pairs':32,'pairs':pairs,
        'cagr_better_points':sum(row['cagr_difference']>0 for row in pairs),
        'cagr_worse_points':sum(row['cagr_difference']<0 for row in pairs),
        'drawdown_better_points':sum(row['drawdown_difference']<0 for row in pairs),
        'drawdown_worse_points':sum(row['drawdown_difference']>0 for row in pairs),
        'mean_cagr_difference':mean(row['cagr_difference'] for row in pairs),
        'mean_drawdown_difference':mean(row['drawdown_difference'] for row in pairs),
        'original_qualified_points':sum(row['original_qualified'] for row in pairs),
        'new_qualified_points':sum(row['new_qualified'] for row in pairs),
        'differences_from_h3_original':{key:second[key]-first[key] for key in metrics},
        'scope':'Exact numerical coordinates with differing categorical entry-confirmation implementation; descriptive policy pairing, no independent statistical test or new qualification gate.'}
    write(RUNS/'parameter_pairs.json',output)
    print({key:value for key,value in output.items() if key not in ('pairs','scope')})


if __name__=='__main__':
    main()
