"""Complete two-layer lagged-MEAN centering and EX020 transition-price contrasts."""
from statistics import mean
from common import RUNS,read,write


def pair_analysis(analysis):
    if analysis['status']=='NOT_APPLICABLE':
        return {'status':'NOT_APPLICABLE','reason':analysis['reason'],'comparisons':{}}
    assert analysis['status']=='PASS'
    labels=set(analysis['points'])
    assert labels == {'B0-TIME','M0-REFERENCE','N0','N1'}, 'EX029 requires the complete old-mean and symmetric price-gate parameter panel'
    assert not analysis['summaries']['M0-REFERENCE']['center_qualified']
    contrasts = (
        ('M0-REFERENCE','B0-TIME','M0-REFERENCE','unchanged EX028 lagged-MEAN centering minus original TIME'),
        ('N0','B0-TIME','N0','lagged-MEAN centering plus EX020 CLOSE minus original TIME'),
        ('N1','B0-TIME','N1','lagged-MEAN centering plus EX020 BODY minus original TIME'),
        ('N0-vs-M0','M0-REFERENCE','N0','EX020 CLOSE price-gate increment with lagged-MEAN mechanism fixed'),
        ('N1-vs-M0','M0-REFERENCE','N1','EX020 BODY price-gate increment with lagged-MEAN mechanism fixed'),
        ('N1-vs-N0','N0','N1','EX020 BODY minus CLOSE with lagged-MEAN mechanism fixed'))
    comparisons={key:contrast(analysis,reference,label,purpose) for key,reference,label,purpose in contrasts}
    return {'status':'PASS','comparisons':comparisons,
        'scope':'All six complete 32-point contrasts use exact13 numeric coordinates at original bull H8/bear H4. M0/B0 isolates lagged-MEAN centering; N0/M0 and N1/M0 isolate added EX020 CLOSE/BODY gates; N1/N0 isolates BODY versus CLOSE; N0/B0 and N1/B0 show combined effect. Original confirmation.lookback jointly supplies confirmation and lagged-reference L. Old EX020 price-gate controls are center-only. Descriptive, non-independent S013 development evidence.',
        'eligibility':'M0-REFERENCE remains the predeclared unqualified old-mean diagnostic; an unqualified new price gate is a symmetric diagnostic when the other qualifies. Four original economic gates unchanged; no parameter metric adds a veto or promotes/ registers a diagnostic.'}


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
