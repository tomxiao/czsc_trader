"""Compare the two policies on their exactly identical parameter points."""
from statistics import mean
from common import RUNS,read,write

def main():
    a=read(RUNS/'parameter_analysis.json')
    assert a['status']=='PASS'
    old=sorted(a['points']['B0-TIME'],key=lambda r:r['point_index'])
    new=sorted(a['points']['N8'],key=lambda r:r['point_index'])
    assert len(old)==len(new)==32
    pairs=[]
    for x,y in zip(old,new,strict=True):
        assert x['point_index']==y['point_index'] and x['coordinates']==y['coordinates']
        same=all(x[k]==y[k] for k in ('net_cagr','drawdown','closed_trades','annual','gates'))
        pairs.append({'point':x['point_index'],'same_numeric_coordinates':True,'same_economic_summary':same,
            'cagr_difference':y['net_cagr']-x['net_cagr'],'drawdown_difference':y['drawdown']-x['drawdown'],
            'closed_difference':y['closed_trades']-x['closed_trades'],
            'y2023_return_difference':y['annual']['2023']['return']-x['annual']['2023']['return'],
            'original_qualified':x['qualified'],'new_qualified':y['qualified']})
    output={'status':'PASS','pairs':pairs,'complete_same_coordinate_pairs':32,
        'identical_economic_summaries':sum(p['same_economic_summary'] for p in pairs),
        'cagr_better_points':sum(p['cagr_difference']>0 for p in pairs),
        'cagr_worse_points':sum(p['cagr_difference']<0 for p in pairs),
        'mean_cagr_difference':mean(p['cagr_difference'] for p in pairs),
        'mean_drawdown_difference':mean(p['drawdown_difference'] for p in pairs),
        'scope':'Economic summaries and annual outcomes only, not byte-equivalence of native generated account IDs. No hypothesis selection or extra gate.'}
    write(RUNS/'parameter_pairs.json',output)
    print({k:v for k,v in output.items() if k not in ('pairs','scope')})

if __name__=='__main__':
    main()
